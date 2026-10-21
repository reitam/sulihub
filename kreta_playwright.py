import asyncio
import json
import sqlite3
import os
from playwright.async_api import async_playwright

# --- KONFIGURÁCIÓ BEOLVASÁSA ---
CONFIG_FILE = "config.json"
DB_FILE = "kreta_adatok.db"
CSATOLMANYOK_DIR = os.path.join("static", "csatolmanyok")

if not os.path.exists(CONFIG_FILE):
    print(f"HIBA: A {CONFIG_FILE} fájl nem található!")
    exit(1)

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

HEADLESS_MODE = config.get("HEADLESS", True)
STUDENTS = config.get("STUDENTS", [])
GLOBAL_SCRAPE_MESSAGES = config.get("SCRAPE_MESSAGES", True)

if not STUDENTS:
    print("HIBA: A config.json nem tartalmaz 'STUDENTS' listát!")
    exit(1)

def init_db():
    """Létrehozza az események és az üzenetek táblát az adatbázisban, és kezeli a sémafrissítéseket."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
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
                print(f"  [Adatbázis séma frissítve]: '{col_name}' oszlop hozzáadva az 'uzenetek' táblához.")
            except Exception as ex:
                print(f"  [Sémafrissítési figyelmeztetés ({col_name})]: {ex}")

    conn.commit()
    conn.close()

def get_completed_hazi_map(diak_nev):
    """Kinyeri az adott diák már megjelölt (kesz=1) házi feladatainak azonosítóit, hogy frissítés után is megmaradjanak."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    completed = set()
    try:
        cursor.execute('''
            SELECT tantargy, bej_datum, hatarido, tartalom 
            FROM esemenyek 
            WHERE diak_nev = ? AND esemeny_tipus = 'Házi feladat' AND kesz = 1
        ''', (diak_nev,))
        for r in cursor.fetchall():
            key = f"{r[0]}|{r[1]}|{r[2]}|{r[3]}"
            completed.add(key)
    except Exception:
        pass
    finally:
        conn.close()
    return completed

def clear_student_data(diak_nev):
    """Csak az adott diák korábbi eseményeit törli az adatbázisból (az üzeneteket megőrizzük!)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM esemenyek WHERE diak_nev = ?", (diak_nev,))
    conn.commit()
    conn.close()

def save_esemenyek_to_db(diak_nev, esemenyek, completed_set):
    """Menti az adott diák kinyert eseményeit az adatbázisba megőrizve a korábbi 'kesz' státuszt."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    for e in esemenyek:
        es_tipus = e.get('esemeny_tipus', '')
        kesz_val = 0
        if es_tipus == 'Házi feladat':
            key = f"{e.get('tantargy', '')}|{e.get('bej_datum', '')}|{e.get('hatarido', '')}|{e.get('tartalom', '')}"
            if key in completed_set:
                kesz_val = 1

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
        print(f"      [Hiba az üzenet mentésekor]: {ex}")
    finally:
        conn.close()

async def scrape_uzenetek(page, diak_nev):
    """Be- és letölti az e-Ügyintézés felületről az új üzeneteket és csatolmányokat."""
    print("\n6. Navigáció az e-Ügyintézés (Üzenetek) oldalra...")
    
    try:
        eugy_page = page
        
        eugy_link = await page.query_selector('a[href*="Eugyintezes"], a[href*="eugyintezes"]')
        
        if eugy_link:
            async with page.context.expect_page() as new_page_info:
                await eugy_link.click()
            eugy_page = await new_page_info.value
            await eugy_page.wait_for_load_state("networkidle")
            print("  -> e-Ügyintézés megnyitva új fülön!")
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
        print(f"  -> {len(rows)} db beérkezett üzenet található a listában.")

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

                print(f"    [ÚJ ÜZENET]: {felado} | {targy} ({idopont})")
                
                await row.click()
                await eugy_page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)

                # Üzenet szöveg kiolvasása
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

                # Csatolmány kezelése
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
                        csatolmany_utvonal = save_path.replace("\\", "/")
                        print(f"      -> Csatolmány letöltve: {csatolmany_nev}")
                    except Exception as ex_dl:
                        print(f"      [Csatolmány letöltési hiba]: {ex_dl}")

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

        print(f"Siker! {uj_cnt} db új üzenet lett elmentve az adatbázisba.")

        if eugy_page != page:
            await eugy_page.close()

    except Exception as ex:
        print(f"Figyelmeztetés az üzenetek lekérésekor: {ex}")

async def process_student(page, student):
    diak_nev = student.get("diak_nev", "Ismeretlen")
    institute_code = student.get("institute_code", "")
    username = student.get("username", "")
    password = student.get("password", "")

    student_scrape_messages = student.get("scrape_messages", GLOBAL_SCRAPE_MESSAGES)

    print("\n" + "=" * 70)
    print(f"  FELDOLGOZÁS: {diak_nev.upper()} (Iskola: {institute_code})")
    print("=" * 70)

    # Korábban elkészült házi feladatok kimentése a frissítés előtt
    completed_hazi = get_completed_hazi_map(diak_nev)

    # --- 1. BELÉPÉS ---
    login_url = f"https://{institute_code}.e-kreta.hu"
    print(f"1. Kapcsolódás: {login_url} ...")
    await page.goto(login_url)

    # --- SÜTI (COOKIE) BANNER KEZELÉSE ---
    try:
        cookie_btn = await page.wait_for_selector(
            'form[action*="acceptnecessarycookies"] button, button:has-text("Az összes kötelező cookie elfogadása")',
            timeout=3000
        )
        if cookie_btn:
            print("  -> Süti tájékoztató elfogadása...")
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
    print("Sikeres belépés!")

    # --- 2. OSZTÁLYZATOK KINYERÉSE ---
    print("\n2. Navigáció az 'Osztályzatok' oldalra...")
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
    print(f"Siker! Beolvasva {len(jegyek)} db osztályzat.")

    # --- 3. FELJEGYZÉSEK KINYERÉSE ---
    print("\n3. Navigáció a 'Feljegyzések' oldalra...")
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
    print(f"Siker! Beolvasva {len(feljegyzesek)} db feljegyzés.")

    # --- 4. HÁZI FELADATOK KINYERÉSE ---
    print("\n4. Navigáció a 'Házi feladatok' oldalra...")
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
    print(f"Siker! Beolvasva {len(hazifeladatok)} db házi feladat.")

    # --- 5. BEJELENTETT SZÁMONKÉRÉSEK KINYERÉSE ---
    print("\n5. Navigáció a 'Bejelentett számonkérések' oldalra...")
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
    print(f"Siker! Beolvasva {len(szamonkeresek)} db bejelentett számonkérés.")

    # Mentés az adatbázisba (események)
    clear_student_data(diak_nev)
    osszes_esemeny = jegyek + feljegyzesek + hazifeladatok + szamonkeresek

    if len(osszes_esemeny) > 0:
        save_esemenyek_to_db(diak_nev, osszes_esemeny, completed_hazi)
        print(f"\n{diak_nev} adataiból {len(osszes_esemeny)} db esemény sikeresen elmentve!")
    else:
        print(f"Figyelem: {diak_nev} fiókjából nem sikerült eseményadatot kinyerni.")

    # --- 6. E-ÜGYINTÉZÉS ÜZENETEK KINYERÉSE ---
    if student_scrape_messages:
        await scrape_uzenetek(page, diak_nev)
    else:
        print(f"\n6. Üzenetek lekérése KI VAN KAPCSOLVA ennél a diáknál ({diak_nev}).")

    # --- 7. KIJELENTKEZÉS A FIÓKBÓL ---
    print(f"\nKijelentkezés ({diak_nev})...")
    try:
        await page.goto(f"https://{institute_code}.e-kreta.hu/Home/LogOut")
        await page.wait_for_load_state("networkidle")
        print("Sikeres kijelentkezés!")
    except Exception as e:
        print(f"Kijelentkezési figyelmeztetés: {e}")

async def main():
    init_db()
    
    active_students = [s for s in STUDENTS if s.get("active", True)]
    print(f"Készülődés {len(active_students)} diák adatainak lekérésére...")
    print(f"Böngésző üzemmód: {'Háttérben (Headless)' if HEADLESS_MODE else 'Látható (Headed)'}")
    print(f"Globális üzenet-szinkronizálás: {'BE' if GLOBAL_SCRAPE_MESSAGES else 'KI'}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS_MODE)
        context = await browser.new_context()
        page = await context.new_page()

        for student in active_students:
            try:
                await process_student(page, student)
                await asyncio.sleep(2)
            except Exception as err:
                print(f"\nHIBA történt {student.get('diak_nev')} feldolgozása során: {err}")

        print("\n" + "=" * 70)
        print("MINDEN DIÁK FELDOLGOZÁSA BEFEJEZŐDÖTT!")
        print("=" * 70)
        
        await asyncio.sleep(2)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())