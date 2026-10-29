import asyncio
import json
import sqlite3
import os
import re
import sys
import logging
import logging.handlers
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

# --- KONFIGURÁCIÓ ÉS LOGGING BEÁLLÍTÁSA ---
# Az útvonalak felülírhatók környezeti változókkal (Docker): alapból a régi,
# relatív elrendezés él (lokális futtatás), a konténerben KRETA_DATA_DIR=/app/data.
# FONTOS: a data könyvtárból (KRETA_DATA_DIR) vezetjük le az alapértékeket, mert
# a konténerben a munkakönyvtár /app, az adatok viszont /app/data alatt vannak.
# Lokálisan KRETA_DATA_DIR nincs beállítva -> "." -> a régi viselkedés.
DATA_DIR = os.environ.get("KRETA_DATA_DIR", ".")
CONFIG_FILE = os.environ.get("KRETA_CONFIG_FILE", os.path.join(DATA_DIR, "config.json"))
DB_FILE = os.environ.get("KRETA_DB_FILE", os.path.join(DATA_DIR, "kreta_adatok.db"))
LOG_FILE = os.environ.get("KRETA_LOG_FILE", os.path.join(DATA_DIR, "sync.log"))
CSATOLMANYOK_DIR = os.environ.get("KRETA_CSATOLMANYOK_DIR", os.path.join("static", "csatolmanyok"))# Napló-rotáció: ne nőjön korlátlanul a sync.log (a felület is ezt olvassa).
LOG_MAX_BYTES = int(os.environ.get("KRETA_LOG_MAX_BYTES", 1000000))
LOG_BACKUP_COUNT = int(os.environ.get("KRETA_LOG_BACKUP_COUNT", 2))
# A Flakon (app.py) ezt a jelölőt keresi a kimenetben az összegzéshez.
RESULT_MARKER = "##KRETA_RESULT##"

# Standard Python Logging konfiguráció: egyszerre fájlba (sync.log) és stdout-ra (konzol/Flask)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8", mode="a"
        ),
        logging.StreamHandler(sys.stdout)
    ]
)

def log(message=""):
    """Segédfüggvény a sima print helyett, ami formázva ír a logfájlba és a konzolra is."""
    logging.info(message)

if not os.path.exists(CONFIG_FILE):
    log(f"HIBA: A {CONFIG_FILE} fájl nem található!")
    exit(1)

# utf-8-sig: a Windows Notepad/PowerShell által írt BOM-ot is kezeli.
try:
    with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
        config = json.load(f)
except ValueError as e:
    log(f"HIBA: A {CONFIG_FILE} nem érvényes JSON: {e}")
    exit(1)

HEADLESS_MODE = config.get("HEADLESS", True)
STUDENTS = config.get("STUDENTS", [])
GLOBAL_SCRAPE_MESSAGES = config.get("SCRAPE_MESSAGES", True)

if not STUDENTS:
    log("HIBA: A config.json nem tartalmaz 'STUDENTS' listát!")
    exit(1)

def init_db():
    """Létrehozza az események, üzenetek és órarend táblákat az adatbázisban, és kezeli a sémafrissítéseket."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # WAL: az app és a scraper párhuzamos írása ne akadjon össze.
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS esemenyek (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            diak_nev TEXT,
            esemeny_tipus TEXT,
            tantargy TEXT,
            ertek TEXT,
            szam_ertek INTEGER,
            bej_datum TEXT,
            hatarido TEXT,
            ertekelo TEXT,
            tipus TEXT,
            mod TEXT,
            tema TEXT,
            cim TEXT,
            tartalom TEXT,
            kesz INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS uzenetek (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            diak_nev TEXT,
            uzenet_id TEXT,
            felado TEXT,
            targy TEXT,
            idopont TEXT,
            szoveg TEXT,
            csatolmany_nev TEXT,
            csatolmany_utvonal TEXT
        )
    ''')

    # === ÓRAREND TÁBLA LÉTREHOZÁSA ===
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orarend (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            diak_nev TEXT,
            kezdo_idopont TEXT,
            zaro_idopont TEXT,
            nap TEXT,
            ora_szam INTEGER,
            tantargy TEXT,
            tanar TEXT,
            terem TEXT,
            osztaly_csoport TEXT,
            allapot TEXT,
            sorszam INTEGER
        )
    ''')
    
    cursor.execute("PRAGMA table_info(esemenyek)")
    es_columns = [row[1] for row in cursor.fetchall()]
    if "kesz" not in es_columns:
        try:
            cursor.execute("ALTER TABLE esemenyek ADD COLUMN kesz INTEGER DEFAULT 0")
        except Exception:
            pass

    cursor.execute("PRAGMA table_info(uzenetek)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    
    required_columns = {
        "diak_nev": "TEXT",
        "uzenet_id": "TEXT",
        "felado": "TEXT",
        "targy": "TEXT",
        "idopont": "TEXT",
        "szoveg": "TEXT",
        "csatolmany_nev": "TEXT",
        "csatolmany_utvonal": "TEXT"
    }
    
    for col_name, col_type in required_columns.items():
        if col_name not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE uzenetek ADD COLUMN {col_name} {col_type}")
                log(f"  [Adatbázis séma frissítve]: '{col_name}' oszlop hozzáadva az 'uzenetek' táblához.")
            except Exception as ex:
                log(f"  [Sémafrissítési figyelmeztetés ({col_name})]: {ex}")

    conn.commit()
    conn.close()

def get_existing_hazi_keys(diak_nev):
    """Kinyeri a DB-ben már meglévő házi feladatok azonosítóit (Tantárgy | Bejegyzés dátuma | Határidő)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    existing = set()
    try:
        cursor.execute('''
            SELECT tantargy, bej_datum, hatarido 
            FROM esemenyek 
            WHERE diak_nev = ? AND esemeny_tipus = 'Házi feladat'
        ''', (diak_nev,))
        for r in cursor.fetchall():
            key = f"{r[0]}|{r[1]}|{r[2]}"
            existing.add(key)
    except Exception as ex:
        log(f"  [DB lekérdezési hiba - meglévő házik]: {ex}")
    finally:
        conn.close()
    return existing

def get_existing_szamonkeres_keys(diak_nev):
    """Kinyeri a DB-ben már meglévő bejelentett számonkérések azonosítóit (Tantárgy | Bejelentés dátuma | Határidő)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    existing = set()
    try:
        cursor.execute('''
            SELECT tantargy, bej_datum, hatarido 
            FROM esemenyek 
            WHERE diak_nev = ? AND esemeny_tipus = 'Bejelentett számonkérés'
        ''', (diak_nev,))
        for r in cursor.fetchall():
            key = f"{r[0]}|{r[1]}|{r[2]}"
            existing.add(key)
    except Exception as ex:
        log(f"  [DB lekérdezési hiba - meglévő számonkérések]: {ex}")
    finally:
        conn.close()
    return existing

def get_completed_hazi_map(diak_nev):
    """Kinyeri az adott diák már megjelölt (kesz=1) házi feladatainak azonosítóit, hogy frissítés után is megmaradjanak."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    completed = set()
    try:
        cursor.execute('''
            SELECT tantargy, bej_datum, hatarido 
            FROM esemenyek 
            WHERE diak_nev = ? AND esemeny_tipus = 'Házi feladat' AND kesz = 1
        ''', (diak_nev,))
        for r in cursor.fetchall():
            key = f"{r[0]}|{r[1]}|{r[2]}"
            completed.add(key)
    except Exception:
        pass
    finally:
        conn.close()
    return completed

def clear_student_data(diak_nev):
    """Törli az adott diák változó eseményeit (Értékelések, Feljegyzések) az adatbázisból (a Házi feladatokat, Számonkéréseket és Üzeneteket megőrizzük!)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM esemenyek WHERE diak_nev = ? AND esemeny_tipus NOT IN ('Házi feladat', 'Bejelentett számonkérés')", (diak_nev,))
    conn.commit()
    conn.close()

# ── Új események kimutatása a szinkron során ─────────────────────────────────
# A Flask app ezt küldi ki a push-értesítésben (diákonként, típusonként).
NEW_EVENT_COUNTS = {}
NEW_MESSAGE_COUNTS = {}

_EVENT_KEY_COLUMNS = (
    "esemeny_tipus, tantargy, bej_datum, hatarido, ertek, szam_ertek, tema, cim, tartalom"
)


def get_event_key_set(diak_nev):
    """Az adott diák összes eseményének tartalom-alapú kulcsa (összehasonlításhoz)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    keys = set()
    try:
        cursor.execute(
            f"SELECT {_EVENT_KEY_COLUMNS} FROM esemenyek WHERE diak_nev = ?", (diak_nev,)
        )
        for row in cursor.fetchall():
            keys.add(tuple("" if v is None else str(v) for v in row))
    except Exception as ex:
        log(f"  [DB hiba - esemény kulcsok]: {ex}")
    finally:
        conn.close()
    return keys


def diff_event_counts(before_keys, after_keys):
    """Új események típusonként: after - before."""
    counts = {}
    for key in (after_keys - before_keys):
        tipus = key[0] if key else "?"
        counts[tipus] = counts.get(tipus, 0) + 1
    return counts

def save_esemenyek_to_db(diak_nev, esemenyek, completed_set):
    """Menti az adott diák kinyert eseményeit az adatbázisba megőrizve a korábbi 'kesz' státuszt és elkerülve a duplikációkat."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    existing_hazi = get_existing_hazi_keys(diak_nev)
    existing_szamonkeres = get_existing_szamonkeres_keys(diak_nev)

    for e in esemenyek:
        es_tipus = e.get('esemeny_tipus', '')
        kesz_val = 0
        
        if es_tipus == 'Házi feladat':
            key = f"{e.get('tantargy', '')}|{e.get('bej_datum', '')}|{e.get('hatarido', '')}"
            if key in existing_hazi:
                continue
            if key in completed_set:
                kesz_val = 1

        elif es_tipus == 'Bejelentett számonkérés':
            key = f"{e.get('tantargy', '')}|{e.get('bej_datum', '')}|{e.get('hatarido', '')}"
            if key in existing_szamonkeres:
                continue

        cursor.execute('''
            INSERT INTO esemenyek 
            (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            diak_nev, 
            es_tipus,
            e.get('tantargy', ''),
            e.get('ertek', ''),
            e.get('szam_ertek', 0),
            e.get('bej_datum', ''),
            e.get('hatarido', ''),
            e.get('ertekelo', ''),
            e.get('tipus', ''),
            e.get('mod', ''),
            e.get('tema', ''),
            e.get('cim', ''),
            e.get('tartalom', ''),
            kesz_val
        ))
        
    conn.commit()
    conn.close()

def is_uzenet_saved(diak_nev, felado, targy, idopont):
    """Ellenőrzi, hogy egy adott üzenet el van-e már mentve az SQLite adatbázisba."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id FROM uzenetek 
        WHERE diak_nev = ? AND felado = ? AND targy = ? AND idopont = ?
    ''', (diak_nev, felado, targy, idopont))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def save_uzenet_to_db(diak_nev, felado, targy, idopont, szoveg, csatolmany_nev="", csatolmany_utvonal=""):
    """Menti a beolvasott új üzenetet az adatbázisba."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO uzenetek 
            (diak_nev, felado, targy, idopont, szoveg, csatolmany_nev, csatolmany_utvonal)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (diak_nev, felado, targy, idopont, szoveg, csatolmany_nev, csatolmany_utvonal))
        conn.commit()
    except Exception as ex:
        log(f"      [Hiba az üzenet mentésekor]: {ex}")
    finally:
        conn.close()

# ==============================================================================
# === ÓRAREND KINYERÉSI BLOKK (AKTUÁLIS ÉS KÖVETKEZŐ HÉT) ===
# ==============================================================================
def save_orarend_to_db(diak_nev, orarend_lista):
    """Elmenti a diák órarendi adatait az SQLite adatbázisba törlés után."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM orarend WHERE diak_nev = ?", (diak_nev,))

    def to_str(val):
        if val is None:
            return ""
        if isinstance(val, dict):
            return str(val.get('_i') or val.get('d') or str(val))
        return str(val).strip()

    for ora in orarend_lista:
        kezdo = to_str(ora.get('start') or ora.get('Kezdet'))
        zaro = to_str(ora.get('end') or ora.get('Veg'))
        raw_title = to_str(ora.get('title') or ora.get('tantargyNev') or ora.get('Tantargy'))
        tanar = to_str(ora.get('tanarNev') or ora.get('Tanar'))
        terem = to_str(ora.get('teremNev') or ora.get('Terem'))
        nap = to_str(ora.get('day') or ora.get('NapNev'))

        if "\n" in raw_title:
            lines = [l.strip() for l in raw_title.split("\n") if l.strip()]
            tantargy = lines[0] if len(lines) >= 1 else raw_title
            if len(lines) >= 2 and not tanar:
                tanar = lines[1]
            if len(lines) >= 3 and not terem:
                terem = lines[2].strip("()")
        else:
            tantargy = raw_title

        if not nap and kezdo and len(kezdo) >= 10:
            try:
                dt = datetime.strptime(kezdo[:10], "%Y-%m-%d")
                napok = ["hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap"]
                nap = napok[dt.weekday()]
            except Exception:
                pass

        cursor.execute('''
            INSERT INTO orarend 
            (diak_nev, kezdo_idopont, zaro_idopont, nap, tantargy, tanar, terem)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            diak_nev,
            kezdo,
            zaro,
            nap,
            tantargy,
            tanar,
            terem
        ))

    conn.commit()
    conn.close()

async def scrape_orarend(page, diak_nev, institute_code):
    """Lekéri az aktuális ÉS a következő hét órarendjét a bal felső nyilakkal történő elnavigálással."""
    log("\n[ÓRAREND] Navigáció az Órarend oldalra és adatlekérés...")
    try:
        await page.goto(f"https://{institute_code}.e-kreta.hu/Orarend/InformaciokOrarend")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_selector('#Calendar', timeout=15000)
        await asyncio.sleep(2)

        def parse_events_js():
            return '''() => {
                try {
                    let events = [];
                    if (window.SDAFullCalendarInstance && window.SDAFullCalendarInstance.events) {
                        events = window.SDAFullCalendarInstance.events;
                    } else {
                        let calEl = $('#Calendar');
                        if (calEl.length && calEl.fullCalendar) {
                            events = calEl.fullCalendar('clientEvents');
                        }
                    }

                    return events.map(e => ({
                        title: e.title || "",
                        start: (e.start && typeof e.start.format === 'function') ? e.start.format() : (e.start || ""),
                        end: (e.end && typeof e.end.format === 'function') ? e.end.format() : (e.end || ""),
                        tanarNev: e.tanarNev || e.tanar || (e.extendedProps ? e.extendedProps.tanarNev : ""),
                        teremNev: e.teremNev || e.terem || (e.extendedProps ? e.extendedProps.teremNev : ""),
                        oraSzam: e.oraSzam || e.oraszam || (e.extendedProps ? e.extendedProps.oraSzam : 0),
                        allapotNev: e.allapotNev || (e.extendedProps ? e.extendedProps.allapotNev : "")
                    }));
                } catch(e) {
                    return [];
                }
            }'''

        log("  -> 1/2. Aktuális hét órarendjének beolvasása...")
        aktuális_heti_orák = await page.evaluate(parse_events_js())
        log(f"     Siker! Aktuális hétről beolvasva {len(aktuális_heti_orák)} db elem.")

        log("  -> 2/2. Navigáció a következő hétre (következő nyíl gomb)...")
        next_btn = await page.query_selector('.fc-next-button, #Calendar .fc-button-next, button:has(.fc-icon-right-single-arrow), .fc-header-left .fc-button:has-text(">")')
        
        if not next_btn:
            await page.evaluate('''() => {
                let calEl = $('#Calendar');
                if (calEl.length && calEl.fullCalendar) {
                    calEl.fullCalendar('next');
                } else {
                    $('.fc-next-button').click();
                }
            }''')
        else:
            await next_btn.click()

        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        következő_heti_orák = await page.evaluate(parse_events_js())
        log(f"     Siker! Következő hétről beolvasva {len(következő_heti_orák)} db elem.")

        osszes_ora = aktuális_heti_orák + következő_heti_orák
        
        if len(osszes_ora) > 0:
            save_orarend_to_db(diak_nev, osszes_ora)
            log(f"  [ÓRAREND OK] Összesen {len(osszes_ora)} db tanóra és bejegyzés elmentve az adatbázisba.")
        else:
            log("  [Figyelmeztetés]: Egyik hétről sem sikerült adatot kinyerni.")

    except Exception as ex:
        log(f"  [Órarend lekérési hiba]: {ex}")

async def scrape_uzenetek(page, diak_nev):
    """Be- és letölti az e-Ügyintézés felületről az új üzeneteket és csatolmányokat."""
    log("\n6. Navigáció az e-Ügyintézés (Üzenetek) oldalra...")
    uj_cnt = 0

    try:
        eugy_page = page
        
        eugy_link = await page.query_selector('a[href*="Eugyintezes"], a[href*="eugyintezes"]')
        
        if eugy_link:
            async with page.context.expect_page() as new_page_info:
                await eugy_link.click()
            eugy_page = await new_page_info.value
            await eugy_page.wait_for_load_state("networkidle")
            log("  -> e-Ügyintézés megnyitva új fülön!")
        else:
            await page.goto("https://eugyintezes.e-kreta.hu/uzenetek")
            await page.wait_for_load_state("networkidle")

        if "uzenetek" not in eugy_page.url:
            await eugy_page.goto("https://eugyintezes.e-kreta.hu/uzenetek")
            await eugy_page.wait_for_load_state("networkidle")

        await asyncio.sleep(4)

        await eugy_page.wait_for_selector('table tbody tr, kozelkep-app-root', timeout=20000)
        await asyncio.sleep(2)

        rows = await eugy_page.query_selector_all('table tbody tr')
        log(f"  -> {len(rows)} db beérkezett üzenet található a listában.")

        uj_cnt = 0
        
        for i in range(len(rows)):
            current_rows = await eugy_page.query_selector_all('table tbody tr')
            if i >= len(current_rows):
                break
                
            row = current_rows[i]
            cols = await row.query_selector_all('td')
            
            if len(cols) >= 3:
                felado = (await cols[-3].inner_text()).strip()
                targy = (await cols[-2].inner_text()).strip()
                idopont = (await cols[-1].inner_text()).strip()

                if is_uzenet_saved(diak_nev, felado, targy, idopont):
                    continue

                log(f"    [ÚJ ÜZENET]: {felado} | {targy} ({idopont})")
                
                await row.click()
                await eugy_page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)

                szoveg = ""
                szoveg_el = await eugy_page.query_selector('.message-body, .message-content, [class*="message-body"], .szoveg-container')
                if szoveg_el:
                    szoveg = (await szoveg_el.inner_text()).strip()
                else:
                    try:
                        szoveg = await eugy_page.evaluate('''() => {
                            let labels = Array.from(document.querySelectorAll('label, div, span, h6'));
                            let szovegLabel = labels.find(el => el.textContent.trim() === 'Szöveg');
                            if (szovegLabel && szovegLabel.nextElementSibling) {
                                return szovegLabel.nextElementSibling.innerText.trim();
                            }
                            return "";
                        }''')
                    except Exception:
                        szoveg = ""

                if szoveg:
                    szoveg = re.sub(r'\n{3,}', '\n\n', szoveg)

                csatolmany_nev = ""
                csatolmany_utvonal = ""

                csatolmany_btn = await eugy_page.query_selector('a[href*="download"], button:has-text(".jpg"), button:has-text(".pdf"), .attachment-link, a:has(.fa-paperclip), [class*="attachment"]')
                if csatolmany_btn:
                    try:
                        target_dir = os.path.join(CSATOLMANYOK_DIR, diak_nev.replace(" ", "_"))
                        os.makedirs(target_dir, exist_ok=True)

                        async with eugy_page.expect_download(timeout=10000) as download_info:
                            await csatolmany_btn.click()
                        
                        download = await download_info.value
                        save_path = os.path.join(target_dir, download.suggested_filename)
                        await download.save_as(save_path)
                        
                        csatolmany_nev = download.suggested_filename
                        # A DB-be a csatolmány-könyvtárhoz KÉPEST relatív utat
                        # mentünk ("diak_nev/fajl.pdf"). Abszolút útvonallal
                        # (KRETA_CSATOLMANYOK_DIR=/app/data/csatolmanyok) a
                        # frontend linkje //app/... protokoll-relatív URL-ként
                        # halott lenne, a route pedig safe_join-nal 404-et adna.
                        csatolmany_utvonal = os.path.relpath(save_path, CSATOLMANYOK_DIR).replace("\\", "/")
                        log(f"      -> Csatolmány letöltve: {csatolmany_nev}")
                    except Exception as ex_dl:
                        log(f"      [Csatolmány letöltési hiba]: {ex_dl}")

                save_uzenet_to_db(diak_nev, felado, targy, idopont, szoveg, csatolmany_nev, csatolmany_utvonal)
                uj_cnt += 1

                vissza_btn = await eugy_page.query_selector('button:has-text("Vissza"), a:has-text("Vissza")')
                if vissza_btn:
                    await vissza_btn.click()
                    await eugy_page.wait_for_load_state("networkidle")
                    await asyncio.sleep(2)
                else:
                    await eugy_page.goto("https://eugyintezes.e-kreta.hu/uzenetek")
                    await eugy_page.wait_for_load_state("networkidle")
                    await asyncio.sleep(2)

        log(f"Siker! {uj_cnt} db új üzenet lett elmentve az adatbázisba.")

        if eugy_page != page:
            await eugy_page.close()
        return uj_cnt

    except Exception as ex:
        log(f"Figyelmeztetés az üzenetek lekérésekor: {ex}")
        return 0

async def process_student(page, student):
    diak_nev = student.get("diak_nev", "Ismeretlen")
    institute_code = student.get("institute_code", "")
    username = student.get("username", "")
    password = student.get("password", "")

    student_scrape_messages = student.get("scrape_messages", GLOBAL_SCRAPE_MESSAGES)

    log("\n" + "=" * 70)
    log(f"  FELDOLGOZÁS: {diak_nev.upper()} (Iskola: {institute_code})")
    log("=" * 70)

    # A frissítés ELŐTTI állapot — a végén ebből számoljuk az új eseményeket.
    before_event_keys = get_event_key_set(diak_nev)

    # Korábban elkészült házi feladatok és a DB-ben meglévő házi / számonkérés kulcsok kimentése
    completed_hazi = get_completed_hazi_map(diak_nev)
    existing_hazi_keys = get_existing_hazi_keys(diak_nev)
    existing_szamonkeres_keys = get_existing_szamonkeres_keys(diak_nev)

    # --- 1. BELÉPÉS ---
    login_url = f"https://{institute_code}.e-kreta.hu"
    log(f"1. Kapcsolódás: {login_url} ...")
    await page.goto(login_url)

    try:
        cookie_btn = await page.wait_for_selector(
            'form[action*="acceptnecessarycookies"] button, button:has-text("Az összes kötelező cookie elfogadása")',
            timeout=3000
        )
        if cookie_btn:
            log("  -> Süti tájékoztató elfogadása...")
            await cookie_btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)
    except Exception:
        pass

    await page.wait_for_selector('input[name="UserName"]', timeout=15000)
    await page.fill('input[name="UserName"]', username)
    await page.fill('input[name="Password"]', password)
    await page.press('input[name="Password"]', 'Enter')

    await page.wait_for_url(lambda url: "login" not in url.lower(), timeout=30000)
    await page.wait_for_load_state("networkidle")
    log("Sikeres belépés!")

    # --- ÓRAREND KINYERÉSE ---
    await scrape_orarend(page, diak_nev, institute_code)

    # --- 2. OSZTÁLYZATOK KINYERÉSE ---
    log("\n2. Navigáció az 'Osztályzatok' oldalra...")
    await page.goto(f"https://{institute_code}.e-kreta.hu/TanuloErtekeles/Osztalyzatok")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector('tr.k-master-row, tbody tr:not(.k-no-data)', timeout=15000)
    await asyncio.sleep(2)

    await page.evaluate('''() => {
        if (typeof KretaGridHelper !== 'undefined' && KretaGridHelper.openAllGrid) {
            KretaGridHelper.openAllGrid();
        } else {
            let links = document.querySelectorAll('.k-hierarchy-cell a, .k-i-expand, td.k-hierarchy-cell');
            links.forEach(l => l.click());
        }
    }''')
    await asyncio.sleep(3)

    js_ertekeles_extractor = """
    () => {
        let lista = [];
        let gridEl = document.querySelector('.k-grid');
        if (!gridEl) return lista;
        let grid = $(gridEl).data("kendoGrid");
        if (!grid) return lista;
        
        let masterRows = grid.tbody.find('> tr.k-master-row');
        masterRows.each(function() {
            let mRow = $(this);
            let dataItem = grid.dataItem(mRow);
            let tantargy = dataItem ? (dataItem.TantargyNev || "") : "";
            
            let dRow = mRow.next('tr.k-detail-row');
            if (dRow.length > 0) {
                let detailRows = dRow.find('tbody tr');
                detailRows.each(function() {
                    let cols = $(this).find('td');
                    if (cols.length >= 5) {
                        let datum = cols.eq(1).text().trim();
                        let ertekelo = cols.eq(2).text().trim();
                        let tipus = cols.eq(3).text().trim();
                        let mod = cols.eq(4).text().trim();
                        let ertekStr = cols.eq(5).text().trim();
                        let tema = cols.eq(6).text().trim();
                        
                        if (datum && datum.length >= 8 && datum !== "Bej. dátum") {
                            let szam = 0;
                            let match = ertekStr.match(/\\((\\d+)\\)/);
                            if (match) {
                                szam = parseInt(match[1]);
                            } else if (!isNaN(parseInt(ertekStr))) {
                                szam = parseInt(ertekStr);
                            }

                            lista.push({
                                esemeny_tipus: 'Értékelés',
                                tantargy: tantargy || "Általános",
                                ertek: ertekStr,
                                szam_ertek: szam,
                                bej_datum: datum,
                                ertekelo: ertekelo,
                                tipus: tipus,
                                mod: mod,
                                tema: tema
                            });
                        }
                    }
                });
            }
        });
        return lista;
    }
    """
    jegyek = await page.evaluate(js_ertekeles_extractor)
    log(f"Siker! Beolvasva {len(jegyek)} db osztályzat.")

    # --- 3. FELJEGYZÉSEK KINYERÉSE ---
    log("\n3. Navigáció a 'Feljegyzések' oldalra...")
    await page.goto(f"https://{institute_code}.e-kreta.hu/TanuloErtekeles/InformaciokFeljegyzesek")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector('#InformaciokFeljegyzesekGrid tbody tr', timeout=15000)
    await asyncio.sleep(2)

    js_feljegyzes_extractor = """
    () => {
        let lista = [];
        let gridEl = document.querySelector('#InformaciokFeljegyzesekGrid');
        if (!gridEl) return lista;
        let grid = $(gridEl).data("kendoGrid");
        if (grid) {
            let dataItems = grid.dataSource.data();
            dataItems.forEach(item => {
                let datumStr = "";
                if (item.Datum) {
                    let d = new Date(item.Datum);
                    if (!isNaN(d.getTime())) {
                        let y = d.getFullYear();
                        let m = String(d.getMonth() + 1).padStart(2, '0');
                        let day = String(d.getDate()).padStart(2, '0');
                        datumStr = `${y}. ${m}. ${day}.`;
                    } else {
                        datumStr = String(item.Datum);
                    }
                }

                lista.push({
                    esemeny_tipus: 'Feljegyzés',
                    bej_datum: datumStr,
                    tipus: item.Tipus_DNAME || "",
                    ertekelo: item.TanarElotagNelkul || item.Tanar || "",
                    cim: item.Cim || "",
                    tartalom: item.Tartalom || ""
                });
            });
        }
        return lista;
    }
    """
    feljegyzesek = await page.evaluate(js_feljegyzes_extractor)
    log(f"Siker! Beolvasva {len(feljegyzesek)} db feljegyzés.")

    # --- 4. HÁZI FELADATOK KINYERÉSE (INKREMENTÁLIS MEGOLDÁSSAL) ---
    log("\n4. Navigáció a 'Házi feladatok' oldalra...")
    await page.goto(f"https://{institute_code}.e-kreta.hu/Tanulo/TanuloHaziFeladat")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector('#searchForm', timeout=15000)
    await asyncio.sleep(1)

    await page.evaluate('''() => {
        let cb = document.getElementById('RegiHaziFeladatokElrejtese');
        if (cb) cb.checked = false;
        if (typeof KretaGridHelper !== 'undefined' && KretaGridHelper.refreshGridSearchPanel) {
            KretaGridHelper.refreshGridSearchPanel("TanulotHaziFeladatkGrid", "searchForm");
        } else {
            let btn = document.getElementById('searchPanelBtn');
            if (btn) btn.click();
        }
    }''')
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(3)

    js_hazifeladat_extractor = """
    () => {
        let lista = [];
        let gridEl = document.querySelector('#TanulotHaziFeladatkGrid');
        if (!gridEl) return lista;
        let grid = $(gridEl).data("kendoGrid");
        if (grid) {
            let dataItems = grid.dataSource.data();
            dataItems.forEach((item, index) => {
                let formatDate = (dVal) => {
                    if (!dVal) return "";
                    let d = new Date(dVal);
                    if (isNaN(d.getTime())) return String(dVal);
                    let y = d.getFullYear();
                    let m = String(d.getMonth() + 1).padStart(2, '0');
                    let day = String(d.getDate()).padStart(2, '0');
                    return `${y}. ${m}. ${day}.`;
                };

                lista.push({
                    grid_index: index,
                    eventId: item.EventId,
                    esemeny_tipus: 'Házi feladat',
                    tantargy: item.TantargyNev || "",
                    ertekelo: item.TanarNeve || "",
                    tartalom: item.HaziFeladatSzoveg || "",
                    bej_datum: formatDate(item.HaziFeladatTenylegesRogzitesDatuma),
                    hatarido: formatDate(item.HaziFeladatHatarido)
                });
            });
        }
        return lista;
    }
    """
    hazifeladatok = await page.evaluate(js_hazifeladat_extractor)

    uj_hf_cnt = 0
    for hf in hazifeladatok:
        # Tiszta kulcs: Tantárgy | Bej. dátum | Határidő
        hf_key = f"{hf['tantargy']}|{hf['bej_datum']}|{hf['hatarido']}"

        # HA MÁR BENNE VAN AZ ADATBÁZISBAN -> Átugorjuk a lassú ablaknyitást!
        if hf_key in existing_hazi_keys:
            continue

        uj_hf_cnt += 1
        szoveg = hf['tartalom'].strip()

        if szoveg.endswith("...") or szoveg.endswith("…"):
            log(f"  -> Új csonkított leírás detektálva ({hf['tantargy']}). Teljes szöveg kinyerése megnyitással...")
            try:
                await page.evaluate('''(idx) => {
                    let grid = $('#TanulotHaziFeladatkGrid').data("kendoGrid");
                    if (grid) {
                        let dataItem = grid.dataSource.data()[idx];
                        if (dataItem && typeof InformaciokOrarend !== 'undefined') {
                            InformaciokOrarend.openDetailTanuloHaziFeladatWindow(dataItem);
                        }
                    }
                }''', hf['grid_index'])

                await page.wait_for_selector('#detailOraAdatokWindow', timeout=7000)
                await asyncio.sleep(1)

                await page.evaluate('''() => {
                    let haziTab = Array.from(document.querySelectorAll('#detailOraAdatokWindow a, #detailOraAdatokWindow li, #detailOraAdatokWindow span'))
                        .find(el => el.innerText && el.innerText.trim() === 'Házi feladat');
                    if (haziTab) haziTab.click();
                }''')
                await asyncio.sleep(1)

                teljes_szoveg = await page.evaluate('''() => {
                    let win = document.querySelector('#detailOraAdatokWindow');
                    if (!win) return "";

                    let container = win.querySelector('.k-card-body, .panel-body, div[style*="float: right"], .col-xs-9, .col-sm-9') || win;

                    let rawText = container.innerText || "";
                    let lines = rawText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);

                    let validLines = [];
                    for (let line of lines) {
                        if (!line.includes("Óra adatai") && 
                            !line.includes("Házi feladat") && 
                            !line.startsWith("Fájl") && 
                            !line.includes("Nincs találat") && 
                            !line.includes("MÉGSE") &&
                            !/^\d{4}\.\s*\d{2}\.\s*\d{2}\./.test(line) && 
                            !/^Határidő:\s*\d{4}/.test(line)) {
                            
                            validLines.push(line);
                        }
                    }

                    return validLines.join('\\n').trim();
                }''')

                if teljes_szoveg:
                    hf['tartalom'] = teljes_szoveg
                    log(f"    [Sikeres kinyerés]: {teljes_szoveg[:60]}...")
                else:
                    log(f"    [Figyelmeztetés]: Az ablak megnyílt, de a leírás üres maradt.")

                await page.evaluate('''() => {
                    if (typeof InformaciokOrarend !== 'undefined' && InformaciokOrarend.detailOraInfoCancel) {
                        InformaciokOrarend.detailOraInfoCancel();
                    } else {
                        let win = $('#detailOraAdatokWindow').data("kendoWindow");
                        if (win) win.close();
                    }
                }''')
                await page.wait_for_selector('#detailOraAdatokWindow', state='hidden', timeout=3000)

            except Exception as ex_hf:
                log(f"    [Figyelmeztetés]: Hiba a szöveg kinyerésekor: {ex_hf}")

    for hf in hazifeladatok:
        hf.pop('grid_index', None)
        hf.pop('eventId', None)

    if uj_hf_cnt > 0:
        log(f"Siker! Beolvasva {len(hazifeladatok)} db házi feladat a gridből ({uj_hf_cnt} db ÚJ házi feladat felvéve).")
    else:
        log(f"Siker! Beolvasva {len(hazifeladatok)} db házi feladat a gridből (Nem volt új házi feladat).")

    # --- 5. BEJELENTETT SZÁMONKÉRÉSEK KINYERÉSE (INKREMENTÁLIS MEGOLDÁSSAL) ---
    log("\n5. Navigáció a 'Bejelentett számonkérés' oldalra...")
    await page.goto(f"https://{institute_code}.e-kreta.hu/Tanulo/TanuloBejelentettSzamonkeresek")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector('#searchForm, .k-grid', timeout=15000)
    await asyncio.sleep(1)

    await page.evaluate('''() => {
        let checkboxes = document.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => cb.checked = false);
        let gridEl = document.querySelector('.k-grid');
        let gridId = gridEl ? gridEl.id : "";
        if (typeof KretaGridHelper !== 'undefined' && KretaGridHelper.refreshGridSearchPanel && gridId) {
            KretaGridHelper.refreshGridSearchPanel(gridId, "searchForm");
        } else {
            let btn = document.getElementById('searchPanelBtn');
            if (btn) btn.click();
        }
    }''')
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(3)

    js_szamonkeres_extractor = """
    () => {
        let lista = [];
        let gridEl = document.querySelector('#BejelentettSzamonkeresekGrid') || document.querySelector('.k-grid');
        if (!gridEl) return lista;
        let grid = $(gridEl).data("kendoGrid");
        if (grid) {
            let dataItems = grid.dataSource.data();
            dataItems.forEach(item => {
                let formatDate = (dVal) => {
                    if (!dVal) return "";
                    let d = new Date(dVal);
                    if (isNaN(d.getTime())) return String(dVal);
                    let y = d.getFullYear();
                    let m = String(d.getMonth() + 1).padStart(2, '0');
                    let day = String(d.getDate()).padStart(2, '0');
                    return `${y}. ${m}. ${day}.`;
                };

                lista.push({
                    esemeny_tipus: 'Bejelentett számonkérés',
                    tantargy: item.TargyNev || "",
                    ertekelo: item.TanarNev || "",
                    mod: item.ErtekelesModNev || "",
                    tema: item.SzamonkeresMegnevezes || "",
                    hatarido: formatDate(item.SzamonkeresDatuma),
                    bej_datum: formatDate(item.BejelentesDatuma)
                });
            });
        }
        return lista;
    }
    """
    szamonkeresek = await page.evaluate(js_szamonkeres_extractor)

    uj_szk_cnt = 0
    for szk in szamonkeresek:
        szk_key = f"{szk['tantargy']}|{szk['bej_datum']}|{szk['hatarido']}"
        if szk_key not in existing_szamonkeres_keys:
            uj_szk_cnt += 1
            log(f"    [ÚJ SZÁMONKÉRÉS]: {szk['tantargy']} | Határidő: {szk['hatarido']} (Bejelentve: {szk['bej_datum']}) - Téma: {szk['tema'] or '-'}")

    if uj_szk_cnt > 0:
        log(f"Siker! Beolvasva {len(szamonkeresek)} db bejelentett számonkérés ({uj_szk_cnt} db ÚJ számonkérés felvéve).")
    else:
        log(f"Siker! Beolvasva {len(szamonkeresek)} db bejelentett számonkérés (Nem volt új számonkérés).")

    # Mentés az adatbázisba
    clear_student_data(diak_nev)
    osszes_esemeny = jegyek + feljegyzesek + hazifeladatok + szamonkeresek

    if len(osszes_esemeny) > 0:
        save_esemenyek_to_db(diak_nev, osszes_esemeny, completed_hazi)
        log(f"\n{diak_nev} adataiból {len(osszes_esemeny)} db esemény sikeresen elmentve!")
    else:
        log(f"Figyelem: {diak_nev} fiókjából nem sikerült eseményadatot kinyerni.")

    # --- 6. E-ÜGYINTÉZÉS ÜZENETEK KINYERÉSE ---
    if student_scrape_messages:
        new_msg_count = await scrape_uzenetek(page, diak_nev) or 0
        NEW_MESSAGE_COUNTS[diak_nev] = new_msg_count
    else:
        NEW_MESSAGE_COUNTS[diak_nev] = 0
        log(f"\n6. Üzenetek lekérése KI VAN KAPCSOLVA ennél a diáknál ({diak_nev}).")

    # Új események (a frissítés előtti és utáni állapot különbsége)
    NEW_EVENT_COUNTS[diak_nev] = diff_event_counts(before_event_keys, get_event_key_set(diak_nev))

    # --- 7. KIJELENTKEZÉS A FIÓKBÓL ---
    log(f"\nKijelentkezés ({diak_nev})...")
    try:
        await page.goto(f"https://{institute_code}.e-kreta.hu/Home/LogOut")
        await page.wait_for_load_state("networkidle")
        log("Sikeres kijelentkezés!")
    except Exception as e:
        log(f"Kijelentkezési figyelmeztetés: {e}")

async def main():
    log("=" * 70)
    log(f"SZINKRONIZÁCIÓ INDÍTÁSA - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 70)
    init_db()
    
    active_students = [s for s in STUDENTS if s.get("active", True)]
    log(f"Készülődés {len(active_students)} diák adatainak lekérésére...")
    log(f"Böngésző üzemmód: {'Háttérben (Headless)' if HEADLESS_MODE else 'Látható (Headed)'}")
    log(f"Globális üzenet-szinkronizálás: {'BE' if GLOBAL_SCRAPE_MESSAGES else 'KI'}")

    user_data_dir = os.environ.get("KRETA_BROWSER_DATA_DIR", os.path.join(DATA_DIR, "browser_user_data"))

    async with async_playwright() as p:
        # launch_persistent_context használata a sütik és munkamenetek megőrzéséhez
        # és az automatizációs/headless jelek teljes elrejtéséhez
        context = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=HEADLESS_MODE,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox"
            ],
            ignore_default_args=["--enable-automation"]
        )
        page = context.pages[0] if context.pages else await context.new_page()

        failed = []
        ok_count = 0
        for student in active_students:
            try:
                await process_student(page, student)
                ok_count += 1
                await asyncio.sleep(2)
            except Exception as err:
                failed.append(student.get("diak_nev", "?"))
                log(f"\nHIBA történt {student.get('diak_nev')} feldolgozása során: {err}")

        log("\n" + "=" * 70)
        log("MINDEN DIÁK FELDOLGOZÁSA BEFEJEZŐDÖTT!")
        if failed:
            log(f"FIGYELEM: {len(failed)} diák adata NEM frissült: {', '.join(failed)}")
        log("=" * 70)
        
        await asyncio.sleep(2)
        await context.close()

    # Géppel olvasható összegzés a Flask appnak (stdout-ra, a naplóba nem kell).
    summary = {
        "total": len(active_students),
        "ok": ok_count,
        "failed": failed,
        "new_events": NEW_EVENT_COUNTS,
        "new_messages": NEW_MESSAGE_COUNTS,
    }
    print(RESULT_MARKER + json.dumps(summary, ensure_ascii=False), flush=True)

    # Kilépési kód: 0 = minden diák rendben, 2 = részleges hiba, 1 = végzetes.
    return 0 if not failed else 2

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))