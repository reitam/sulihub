import asyncio
import json
import sqlite3
import os
import re
import shutil
import sys
import logging
import logging.handlers
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

import kreta_api
import kreta_api_sync
import kreta_shadow
import kreta_sync

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
# WAL csak opt-in (a data kötet FUSE mount — lásd a Dockerfile/compose megjegyzést)
SQLITE_WAL = os.environ.get("KRETA_SQLITE_WAL", "0").strip().lower() in ("1", "true", "yes", "on")
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
# Szinkron forrása: playwright | api | api_first (lásd kreta_sync.py).
SYNC_MODE = kreta_sync.resolve_sync_mode(config)
# Árnyék/ellenőrző mód: api_first mellett a Playwright is lefut egy DB-másolaton,
# és csak összehasonlítunk (a valódi DB-hez nem nyúl).
SYNC_SHADOW = str(config.get("SYNC_SHADOW", False)).strip().lower() in ("1", "true", "yes", "on")

# Adatkör-szintű API-szolgáltatók: kulcs -> függvény(diák dict) -> None.
# A szolgáltató lekér és ment (nincs benne Playwright); hibát dobhat, arra a
# hívó (kreta_sync.run_api_datasets) fallbackot indít vagy hibát naplóz.
# A szolgáltatók a fájl alján, a mentő függvények után vannak regisztrálva;
# az üresen maradó adatkör Playwrighttal megy.

if not STUDENTS:
    log("HIBA: A config.json nem tartalmaz 'STUDENTS' listát!")
    exit(1)

def init_db():
    """Létrehozza az események, üzenetek és órarend táblákat az adatbázisban, és kezeli a sémafrissítéseket."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # WAL csak opt-in (KRETA_SQLITE_WAL=1): a data kötet FUSE mount, ahol a
    # WAL nem ajánlott. Ha korábban be volt kapcsolva, visszaállítjuk.
    try:
        if SQLITE_WAL:
            cursor.execute("PRAGMA journal_mode=WAL")
        else:
            mode = cursor.execute("PRAGMA journal_mode").fetchone()[0]
            if str(mode).lower() == "wal":
                cursor.execute("PRAGMA journal_mode=delete")
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

    # === HIÁNYZÁSOK / KÉSÉSEK ÉS IGAZOLÁSOK TÁBLÁI ===
    # A dátumok ISO (ÉÉÉÉ-HH-NN) formában vannak, hogy a havi szűrés
    # BETWEEN-nel egyszerű legyen; a felület formázza magyarra.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hianyzasok (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            diak_nev TEXT,
            kreta_id TEXT,
            mulasztas_datum TEXT,
            ora_sorszam INTEGER DEFAULT 0,
            perc INTEGER,
            tantargy TEXT,
            tema TEXT,
            tanar TEXT,
            mulasztas_tipus TEXT,
            igazolt INTEGER DEFAULT 0,
            tanorai_celu TEXT,
            igazolas_tipus TEXT,
            rogzites_datum TEXT
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hianyzasok_diak ON hianyzasok(diak_nev, mulasztas_datum)')

    # Régi séma: az 'oraszam' valójában a napon belüli órasorszám volt —
    # átnevezzük, hogy senki ne értelmezze óraszámként.
    cursor.execute("PRAGMA table_info(hianyzasok)")
    hianyzas_cols = [row[1] for row in cursor.fetchall()]
    if "oraszam" in hianyzas_cols and "ora_sorszam" not in hianyzas_cols:
        try:
            cursor.execute("ALTER TABLE hianyzasok RENAME COLUMN oraszam TO ora_sorszam")
            log("  [Adatbázis séma frissítve]: hianyzasok.oraszam -> ora_sorszam")
        except Exception as ex:
            log(f"  [Sémafrissítési figyelmeztetés (ora_sorszam)]: {ex}")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS igazolasok (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            diak_nev TEXT,
            kreta_id TEXT,
            kezdete TEXT,
            vege TEXT,
            igazolas_tipus TEXT,
            megjegyzes TEXT
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_igazolasok_diak ON igazolasok(diak_nev, kezdete)')

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


# ── Hiányzások / késések és igazolások ───────────────────────────────────────
# A szinkron során az új hiányzásokat is kimutatjuk (push-értesítéshez).
NEW_HIANYZAS_COUNTS = {}

_HIANYZAS_KEY_FIELDS = ("mulasztas_datum", "ora_sorszam", "tantargy", "mulasztas_tipus", "perc", "tema")


def hianyzas_key(row):
    """A hiányzás azonosítója: dátum + órasorszám (a KRÉTA ID csak tartalék).

    A felhasználó megerősítése szerint egy adott napon egy órasorszám
    egyértelműen azonosít egy mulasztást; így a szinkron újrafuttatása nem
    hoz létre duplikátumot és a sor ID-ja stabil marad.
    """
    datum = str(row.get("mulasztas_datum") or "").strip()
    try:
        ora = int(row.get("ora_sorszam") or 0)
    except (TypeError, ValueError):
        ora = 0
    if datum and ora > 0:
        return f"{datum}#{ora}"
    kreta_id = str(row.get("kreta_id") or "").strip()
    if kreta_id:
        return f"id:{kreta_id}"
    return "|".join(str(row.get(f) if row.get(f) is not None else "") for f in _HIANYZAS_KEY_FIELDS)


def get_hianyzas_key_set(diak_nev):
    """A diák összes eltárolt hiányzásának kulcsa (összehasonlításhoz)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    keys = set()
    try:
        cursor.execute(
            "SELECT kreta_id, mulasztas_datum, ora_sorszam, tantargy, mulasztas_tipus, perc, tema "
            "FROM hianyzasok WHERE diak_nev = ?", (diak_nev,)
        )
        for r in cursor.fetchall():
            keys.add(hianyzas_key({
                "kreta_id": r[0], "mulasztas_datum": r[1], "ora_sorszam": r[2],
                "tantargy": r[3], "mulasztas_tipus": r[4], "perc": r[5], "tema": r[6],
            }))
    except Exception as ex:
        log(f"  [DB lekérdezési hiba - hiányzások]: {ex}")
    finally:
        conn.close()
    return keys


def save_hianyzasok_to_db(diak_nev, rows):
    """Inkrementális mentés: a rekord azonosítója a dátum + órasorszám.

    A KRÉTA mindig a teljes listát adja (nincs delta végpont), ezért a beolvasás
    teljes; a DB-be viszont csak a változás megy: a meglévő sor frissül (stabil
    ID), az új beszúródik, a KRÉTA-ból eltűnt sor pedig törlődik.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        existing = {}
        for rid, kid, datum, ora in cursor.execute(
            "SELECT id, kreta_id, mulasztas_datum, ora_sorszam FROM hianyzasok WHERE diak_nev = ?",
            (diak_nev,),
        ).fetchall():
            existing[hianyzas_key({
                "kreta_id": kid, "mulasztas_datum": datum, "ora_sorszam": ora,
            })] = rid

        seen = set()
        for r in rows:
            key = hianyzas_key(r)
            if key in seen:
                continue
            seen.add(key)
            values = (
                str(r.get("kreta_id") or ""),
                r.get("mulasztas_datum") or "",
                int(r.get("ora_sorszam") or 0),
                r.get("perc"),
                r.get("tantargy") or "",
                r.get("tema") or "",
                r.get("tanar") or "",
                r.get("mulasztas_tipus") or "",
                int(r.get("igazolt") or 0),
                r.get("tanorai_celu") or "",
                r.get("igazolas_tipus") or "",
                r.get("rogzites_datum") or "",
            )
            if key in existing:
                cursor.execute('''
                    UPDATE hianyzasok SET
                        kreta_id = ?, mulasztas_datum = ?, ora_sorszam = ?, perc = ?,
                        tantargy = ?, tema = ?, tanar = ?, mulasztas_tipus = ?,
                        igazolt = ?, tanorai_celu = ?, igazolas_tipus = ?, rogzites_datum = ?
                    WHERE id = ?
                ''', values + (existing[key],))
            else:
                cursor.execute('''
                    INSERT INTO hianyzasok
                    (kreta_id, mulasztas_datum, ora_sorszam, perc, tantargy, tema, tanar,
                     mulasztas_tipus, igazolt, tanorai_celu, igazolas_tipus, rogzites_datum, diak_nev)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', values + (diak_nev,))

        # A KRÉTA-ból eltűnt (törölt/javított) sorok eltávolítása.
        stale_ids = [rid for key, rid in existing.items() if key not in seen]
        for rid in stale_ids:
            cursor.execute("DELETE FROM hianyzasok WHERE id = ?", (rid,))
        conn.commit()
    except Exception as ex:
        log(f"  [Hiba a hiányzások mentésekor]: {ex}")
    finally:
        conn.close()


def save_igazolasok_to_db(diak_nev, rows):
    """A diák igazolásainak teljes cseréje."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM igazolasok WHERE diak_nev = ?", (diak_nev,))
        seen = set()
        for r in rows:
            kreta_id = str(r.get("kreta_id") or "").strip()
            key = kreta_id or f"{r.get('kezdete')}|{r.get('vege')}|{r.get('igazolas_tipus')}|{r.get('megjegyzes')}"
            if key in seen:
                continue
            seen.add(key)
            cursor.execute('''
                INSERT INTO igazolasok
                (diak_nev, kreta_id, kezdete, vege, igazolas_tipus, megjegyzes)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                diak_nev,
                kreta_id,
                r.get("kezdete") or "",
                r.get("vege") or "",
                r.get("igazolas_tipus") or "",
                r.get("megjegyzes") or "",
            ))
        conn.commit()
    except Exception as ex:
        log(f"  [Hiba az igazolások mentésekor]: {ex}")
    finally:
        conn.close()


def diff_hianyzas_counts(before_keys, rows):
    """Új hiányzások száma és az új igazolatlan tanórák száma.

    FIGYELEM: a KRÉTA egy sora egy tanórát jelent (az 'Óra' oszlop a napon
    belüli órasorszám), ezért az órákat soronként 1-ként számoljuk.
    """
    new_rows = []
    seen = set()
    for r in rows:
        key = hianyzas_key(r)
        if key in before_keys or key in seen:
            continue
        seen.add(key)
        new_rows.append(r)
    igazolatlan = 0
    for r in new_rows:
        if int(r.get("igazolt") or 0):
            continue
        if r.get("perc") is not None and str(r.get("perc")) != "":
            continue  # késés — nem számít hiányzó órának
        igazolatlan += 1
    return {"db": len(new_rows), "igazolatlan_ora": igazolatlan}


# ── API-szolgáltatók (D3–D7) ────────────────────────────────────────────────
PRESERVED_HIANYZAS_FIELDS = ("tema", "tanar", "tanorai_celu")


def get_existing_hianyzas_fields(diak_nev):
    """A meglévő hiányzás-sorok megőrzendő mezői: kulcs -> {téma, tanár, tanórai cél}."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    existing = {}
    try:
        cursor.execute(
            "SELECT kreta_id, mulasztas_datum, ora_sorszam, tantargy, mulasztas_tipus, "
            "perc, tema, tanar, tanorai_celu FROM hianyzasok WHERE diak_nev = ?",
            (diak_nev,),
        )
        for r in cursor.fetchall():
            key = hianyzas_key({
                "kreta_id": r[0], "mulasztas_datum": r[1], "ora_sorszam": r[2],
                "tantargy": r[3], "mulasztas_tipus": r[4], "perc": r[5],
            })
            existing[key] = {
                "tema": r[6] or "", "tanar": r[7] or "", "tanorai_celu": r[8] or "",
            }
    except Exception as ex:
        log(f"  [DB lekérdezési hiba - meglévő hiányzás mezők]: {ex}")
    finally:
        conn.close()
    return existing


def merge_existing_hianyzas_fields(rows, existing):
    """Az API-ból hiányzó mezőket (pl. táboros téma) a meglévő DB-sorból pótolja.

    A `/sajat/Mulasztasok` nem ad témát a tanórai célú (táboros) hiányzásokhoz,
    és az órarendi join sem talál hozzá órát — ilyenkor a korábbi webes érték
    marad, nem törlődik.
    """
    for row in rows:
        old = existing.get(hianyzas_key(row))
        if not old:
            continue
        for field in PRESERVED_HIANYZAS_FIELDS:
            if not str(row.get(field) or "").strip() and str(old.get(field) or "").strip():
                row[field] = old[field]
    return rows


def hianyzas_api_window(diak_nev):
    """Az API-lekérés ablaka a DB legkorábbi hiányzásához igazítva."""
    conn = sqlite3.connect(DB_FILE)
    earliest = None
    try:
        row = conn.execute(
            "SELECT MIN(mulasztas_datum) FROM hianyzasok WHERE diak_nev = ?", (diak_nev,)
        ).fetchone()
        earliest = row[0] if row else None
    except Exception as ex:
        log(f"  [DB lekérdezési hiba - hiányzás ablak]: {ex}")
    finally:
        conn.close()
    return kreta_api_sync.api_window(earliest)


def api_provider_hianyzasok(student, client_factory=None):
    """Hiányzások/késések frissítése a mobil API-ból (inkrementális, stabil ID)."""
    diak_nev = student.get("diak_nev", "Ismeretlen")
    start, end = hianyzas_api_window(diak_nev)
    log(f"\n[API] Hiányzások lekérése: {start} .. {end} ...")
    client = client_factory(student) if client_factory else kreta_api_sync.client_for(student)
    rows = kreta_api_sync.fetch_omissions(client, start, end)
    merge_existing_hianyzas_fields(rows, get_existing_hianyzas_fields(diak_nev))
    before = get_hianyzas_key_set(diak_nev)
    save_hianyzasok_to_db(diak_nev, rows)
    uj = diff_hianyzas_counts(before, rows)
    NEW_HIANYZAS_COUNTS[diak_nev] = uj
    if uj.get("db"):
        log(f"    [ÚJ HIÁNYZÁS]: {uj['db']} db (ebből {uj.get('igazolatlan_ora', 0)} igazolatlan óra)")
    keses = sum(1 for r in rows if r.get("perc") is not None)
    log(f"  [HIÁNYZÁSOK OK] {len(rows)} db mulasztás az API-ból ({keses} db késés).")


def api_provider_igazolasok(student, client_factory=None):
    """Igazolások frissítése a mobil API-ból (KRÉTA ID a kulcs)."""
    diak_nev = student.get("diak_nev", "Ismeretlen")
    log("\n[API] Igazolások lekérése ...")
    client = client_factory(student) if client_factory else kreta_api_sync.client_for(student)
    rows = kreta_api_sync.fetch_justifications(client)
    save_igazolasok_to_db(diak_nev, rows)
    log(f"  [IGAZOLÁSOK OK] {len(rows)} db igazolás az API-ból.")


def evaluation_api_window(diak_nev):
    """A jegyek API-ablaka a DB legkorábbi értékeléséhez igazítva."""
    conn = sqlite3.connect(DB_FILE)
    earliest = None
    try:
        row = conn.execute(
            "SELECT MIN(bej_datum) FROM esemenyek "
            "WHERE diak_nev = ? AND esemeny_tipus = 'Értékelés'",
            (diak_nev,),
        ).fetchone()
        earliest = row[0] if row else None
    except Exception as ex:
        log(f"  [DB lekérdezési hiba - jegy ablak]: {ex}")
    finally:
        conn.close()
    return kreta_api_sync.api_window(earliest)


def api_provider_jegyek(student, client_factory=None):
    """Jegyek/értékelések frissítése a mobil API-ból (teljes csere a szeleten belül).

    A Magatartás és a Szorgalom az API-ban két külön sor (0 számértékkel), így az
    átlag/zsebpénz számítást nem módosítják; a webes egy soros megjelenés helyett
    két sor jelenik meg.
    """
    diak_nev = student.get("diak_nev", "Ismeretlen")
    start, end = evaluation_api_window(diak_nev)
    log(f"\n[API] Jegyek lekérése: {start} .. {end} ...")
    client = client_factory(student) if client_factory else kreta_api_sync.client_for(student)
    rows = kreta_api_sync.fetch_evaluations(client, start, end)
    save_esemenyek_by_type(diak_nev, rows, set(), ["Értékelés"])
    log(f"  [JEGYEK OK] {len(rows)} db értékelés az API-ból.")


def events_api_window(diak_nev, tipus):
    """Az eseménytípus API-ablaka a DB legkorábbi `bej_datum`-jához igazítva."""
    conn = sqlite3.connect(DB_FILE)
    earliest = None
    try:
        row = conn.execute(
            "SELECT MIN(bej_datum) FROM esemenyek WHERE diak_nev = ? AND esemeny_tipus = ?",
            (diak_nev, tipus),
        ).fetchone()
        earliest = row[0] if row else None
    except Exception as ex:
        log(f"  [DB lekérdezési hiba - {tipus} ablak]: {ex}")
    finally:
        conn.close()
    return kreta_api_sync.api_window(earliest)


def _hazi_key(row):
    return f"{row.get('tantargy', '')}|{row.get('bej_datum', '')}|{row.get('hatarido', '')}"


def api_provider_hazi(student, client_factory=None):
    """Házi feladatok frissítése az API-ból (csak új sorok, `kesz` megmarad)."""
    diak_nev = student.get("diak_nev", "Ismeretlen")
    start, end = events_api_window(diak_nev, "Házi feladat")
    log(f"\n[API] Házi feladatok lekérése: {start} .. {end} ...")
    client = client_factory(student) if client_factory else kreta_api_sync.client_for(student)
    rows = kreta_api_sync.fetch_homeworks(client, start, end)
    before = get_existing_hazi_keys(diak_nev)
    save_esemenyek_by_type(diak_nev, rows, get_completed_hazi_map(diak_nev), ["Házi feladat"])
    uj = len({_hazi_key(r) for r in rows} - before)
    log(f"  [HÁZI OK] {len(rows)} db házi feladat az API-ból ({uj} db új).")


def api_provider_szamonkeresek(student, client_factory=None):
    """Bejelentett számonkérések frissítése az API-ból (dedupe a meglévő kulcsokkal)."""
    diak_nev = student.get("diak_nev", "Ismeretlen")
    start, end = events_api_window(diak_nev, "Bejelentett számonkérés")
    log(f"\n[API] Bejelentett számonkérések lekérése: {start} .. {end} ...")
    client = client_factory(student) if client_factory else kreta_api_sync.client_for(student)
    rows = kreta_api_sync.fetch_announced_tests(client, start, end)
    before = get_existing_szamonkeres_keys(diak_nev)
    save_esemenyek_by_type(diak_nev, rows, set(), ["Bejelentett számonkérés"])
    uj = len({_hazi_key(r) for r in rows} - before)
    log(f"  [SZÁMONKÉRÉS OK] {len(rows)} db számonkérés az API-ból ({uj} db új).")


def api_provider_feljegyzesek(student, client_factory=None):
    """Feljegyzések frissítése az API-ból (teljes csere a szeleten belül)."""
    diak_nev = student.get("diak_nev", "Ismeretlen")
    start, end = events_api_window(diak_nev, "Feljegyzés")
    log(f"\n[API] Feljegyzések lekérése: {start} .. {end} ...")
    client = client_factory(student) if client_factory else kreta_api_sync.client_for(student)
    rows = kreta_api_sync.fetch_notes(client, start, end)
    save_esemenyek_by_type(diak_nev, rows, set(), ["Feljegyzés"])
    log(f"  [FELJEGYZÉS OK] {len(rows)} db feljegyzés az API-ból.")


def api_provider_orarend(student, client_factory=None):
    """Órarend frissítése az API-ból (aktuális + következő hét, fogadóórákkal)."""
    diak_nev = student.get("diak_nev", "Ismeretlen")
    start, end = kreta_api_sync.week_window()
    log(f"\n[API] Órarend lekérése: {start} .. {end} ...")
    client = client_factory(student) if client_factory else kreta_api_sync.client_for(student)
    rows = kreta_api_sync.fetch_lessons(client, start, end)
    consultations = kreta_api_sync.fetch_consultations(client, start, end)
    save_orarend_to_db(diak_nev, rows + consultations)
    log(f"  [ÓRAREND OK] {len(rows)} db órarendi elem + {len(consultations)} fogadóóra az API-ból.")


def api_provider_uzenetek(student, client_factory=None):
    """Beérkezett üzenetek + csatolmányok frissítése az API-ból (csak az újakat).

    A csatolmányok tartalma is API-ból jön (2026-10-31 óta):

    1. `dokumentumok/uzenetek/{csatolmanyAzonosito}` → 302 a
       `files.e-kreta.hu/fajlok/?nonce=...` címre, onnan a fájl bájtjai;
    2. a fájl a `CSATOLMANYOK_DIR/<diák>/` alá kerül, a DB-be a könyvtárhoz
       viszonyított relatív út megy (mint a webes útnál).

    Ha egy letöltés elhal, `api_first` módban szándékosan hibát dobunk, hogy a
    Playwright végezze el a teljes üzenet-adatkört (nincs félkész mentés);
    tiszta `api` módban a fájl nélkül mentjük az üzenetet és figyelmeztetünk.
    """
    diak_nev = student.get("diak_nev", "Ismeretlen")
    if not student.get("scrape_messages", GLOBAL_SCRAPE_MESSAGES):
        NEW_MESSAGE_COUNTS[diak_nev] = 0
        log(f"  [ÜZENETEK] kikapcsolva ennél a diáknál ({diak_nev}).")
        return

    log("\n[API] Üzenetek lekérése ...")
    client = client_factory(student) if client_factory else kreta_api_sync.client_for(student)
    messages = kreta_api_sync.fetch_messages(client)

    new_messages = [
        m for m in messages
        if not is_uzenet_saved(diak_nev, m["felado"], m["targy"], m["idopont"])
    ]

    # A csatolmányokat ELŐBB töltjük le, hogy hiba esetén még semmi ne kerüljön
    # a DB-be (a Playwright-fallback így teljes adatkört kap).
    downloads: dict[str, list[tuple[str, bytes]]] = {}
    expected_names: dict[str, list[str]] = {}
    for m in new_messages:
        for attachment in m.get("csatolmanyok") or []:
            attachment = attachment or {}
            attachment_id = attachment.get("azonosito")
            if not attachment_id:
                continue
            fajlnev = kreta_api.safe_fajlnev(
                attachment.get("fajlNev") or f"csatolmany_{attachment_id}")
            expected_names.setdefault(m["uzenet_id"], []).append(fajlnev)
            try:
                content, _content_type = kreta_api_sync.fetch_attachment(client, attachment_id)
            except Exception as exc:  # noqa: BLE001 — hálózat/parse/méret bármi
                reason = kreta_sync.describe_error(exc)
                if kreta_sync.needs_playwright(SYNC_MODE):
                    raise RuntimeError(
                        f"csatolmány letöltés nem sikerült ({fajlnev}): {reason}") from exc
                log(f"    [FIGYELEM] a csatolmány nem lett letöltve: {fajlnev} ({reason})")
                continue
            downloads.setdefault(m["uzenet_id"], []).append((fajlnev, content))
            log(f"      -> Csatolmány letöltve: {fajlnev} ({len(content)} B)")

    uj = 0
    for m in new_messages:
        csatolmany_nev = ""
        csatolmany_utvonal = ""
        files = downloads.get(m["uzenet_id"]) or []
        if files:
            target_dir = os.path.join(CSATOLMANYOK_DIR, diak_nev.replace(" ", "_"))
            os.makedirs(target_dir, exist_ok=True)
            saved = []
            for fajlnev, content in files:
                save_path = _unique_path(os.path.join(target_dir, fajlnev))
                with open(save_path, "wb") as handle:
                    handle.write(content)
                saved.append(save_path)
            csatolmany_nev = os.path.basename(saved[0])
            csatolmany_utvonal = os.path.relpath(saved[0], CSATOLMANYOK_DIR).replace("\\", "/")
            if len(saved) > 1:
                log(f"    [INFO] {len(saved)} csatolmány (a felület az elsőt linkeli): "
                    + ", ".join(os.path.basename(p) for p in saved))
        elif expected_names.get(m["uzenet_id"]):
            # a fájl nem jött le (csak api módban jutunk ide): a nevet mentjük,
            # az útvonal üres marad — a felület így is látja, hogy volt csatolmány
            csatolmany_nev = expected_names[m["uzenet_id"]][0]
        save_uzenet_to_db(diak_nev, m["felado"], m["targy"], m["idopont"], m["szoveg"],
                          csatolmany_nev, csatolmany_utvonal)
        uj += 1

    NEW_MESSAGE_COUNTS[diak_nev] = uj
    log(f"  [ÜZENETEK OK] {len(messages)} üzenet az API-ból ({uj} új).")


def _unique_path(path):
    """Létező fájlnevet nem ír felül: `nev.pdf` -> `nev (2).pdf`."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    index = 2
    while os.path.exists(f"{stem} ({index}){ext}"):
        index += 1
    return f"{stem} ({index}){ext}"


API_PROVIDERS = {
    "orarend": api_provider_orarend,
    "jegyek": api_provider_jegyek,
    "feljegyzesek": api_provider_feljegyzesek,
    "hazi": api_provider_hazi,
    "szamonkeresek": api_provider_szamonkeresek,
    "hianyzasok": api_provider_hianyzasok,
    "igazolasok": api_provider_igazolasok,
    "uzenetek": api_provider_uzenetek,
}


VOLATILE_EVENT_TYPES = ("Értékelés", "Feljegyzés")


def _insert_esemeny(cursor, diak_nev, e, completed_set, existing_hazi, existing_szamonkeres):
    """Egy eseménysor beszúrása; visszaadja, hogy történt-e beszúrás."""
    es_tipus = e.get('esemeny_tipus', '')
    kesz_val = 0

    if es_tipus == 'Házi feladat':
        key = f"{e.get('tantargy', '')}|{e.get('bej_datum', '')}|{e.get('hatarido', '')}"
        if key in existing_hazi:
            return False
        if key in completed_set:
            kesz_val = 1

    elif es_tipus == 'Bejelentett számonkérés':
        key = f"{e.get('tantargy', '')}|{e.get('bej_datum', '')}|{e.get('hatarido', '')}"
        if key in existing_szamonkeres:
            return False

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
    return True


def save_esemenyek_to_db(diak_nev, esemenyek, completed_set):
    """Menti az adott diák kinyert eseményeit az adatbázisba megőrizve a korábbi 'kesz' státuszt és elkerülve a duplikációkat."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        existing_hazi = get_existing_hazi_keys(diak_nev)
        existing_szamonkeres = get_existing_szamonkeres_keys(diak_nev)
        for e in esemenyek:
            _insert_esemeny(cursor, diak_nev, e, completed_set,
                            existing_hazi, existing_szamonkeres)
        conn.commit()
    except Exception as ex:
        log(f"  [Hiba az események mentésekor]: {ex}")
    finally:
        conn.close()


def save_esemenyek_by_type(diak_nev, esemenyek, completed_set, tipusok):
    """Típusonkénti mentés: az API-ból már frissült típusokat ki lehet hagyni.

    - `Értékelés` / `Feljegyzés`: teljes csere (a KRÉTA-ból eltűnt sor törlődik);
    - `Házi feladat` / `Bejelentett számonkérés`: inkrementális, a korábbi
      `kesz` jelölés és a duplikátumvédelem megmarad.

    Csak a `tipusok` listában szereplő sorok íródnak ki, így a Playwright és az
    API út ugyanabban a futásban nem írja felül egymást.
    """
    tipusok = tuple(tipusok)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        for tipus in tipusok:
            if tipus in VOLATILE_EVENT_TYPES:
                cursor.execute(
                    "DELETE FROM esemenyek WHERE diak_nev = ? AND esemeny_tipus = ?",
                    (diak_nev, tipus),
                )
        existing_hazi = get_existing_hazi_keys(diak_nev) if 'Házi feladat' in tipusok else set()
        existing_szamonkeres = (
            get_existing_szamonkeres_keys(diak_nev)
            if 'Bejelentett számonkérés' in tipusok else set()
        )
        for e in esemenyek:
            if e.get('esemeny_tipus') not in tipusok:
                continue
            _insert_esemeny(cursor, diak_nev, e, completed_set,
                            existing_hazi, existing_szamonkeres)
        conn.commit()
    except Exception as ex:
        log(f"  [Hiba az események mentésekor]: {ex}")
    finally:
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

# ==============================================================================
# === HIÁNYZÁSOK / KÉSÉSEK ÉS IGAZOLÁSOK KINYERÉSE ============================
# ==============================================================================
# A KRÉTA Kendo gridjei lapozottak (HianyzasGrid: 100, IgazolasGrid: 10 sor).
# Ezért nem elég az első oldalt kiolvasni: a teljes találatszámból számoljuk a
# oldalakat, és mindegyiket beolvassuk. A dátumokat ISO alakban mentjük.
_JS_FORMAT_DATE = """
    const fmtDate = (v) => {
        if (v === null || v === undefined || v === "") return "";
        let d = (v instanceof Date) ? v : new Date(v);
        if (isNaN(d.getTime())) return String(v);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    };
"""

_HIANYZAS_MAPPER = """(item) => {""" + _JS_FORMAT_DATE + """
    const bname = String(item.Igazolt_BNAME || "");
    let igazolt = (item.Igazolt_BOOL === true || item.Igazolt_BOOL === "true" || /igen/i.test(bname));
    if (/nem|igazolatlan/i.test(bname)) igazolt = false;
    return {
        kreta_id: (item.ID === null || item.ID === undefined) ? "" : String(item.ID),
        mulasztas_datum: fmtDate(item.MulasztasDatum),
        ora_sorszam: parseInt(item.Oraszam || 0, 10) || 0,
        perc: (item.Perc === null || item.Perc === undefined || item.Perc === "") ? null : (parseInt(item.Perc, 10) || null),
        tantargy: item.Targy || "",
        tema: item.Tema || "",
        tanar: item.Tanar || item.TanarNev || "",
        mulasztas_tipus: item.MulasztasTipus_DNAME || "",
        igazolt: igazolt ? 1 : 0,
        tanorai_celu: item.TanoraiCeluMulasztas_BNAME || "",
        igazolas_tipus: item.IgazolasTipus_DNAME || "",
        rogzites_datum: fmtDate(item.RogzitesDatum)
    };
}"""

_IGAZOLAS_MAPPER = """(item) => {""" + _JS_FORMAT_DATE + """
    const stripHtml = (v) => {
        if (v === null || v === undefined) return "";
        let s = String(v);
        if (s.indexOf('<') === -1) return s.trim();
        // A blokk-elemek határán szóköz kell, különben a szövegek összeolvadnak.
        s = s.replace(/<\\/(p|div|li|tr|h[1-6]|td|th)>/gi, ' ')
             .replace(/<br\\s*\\/?>/gi, ' ');
        let d = document.createElement('div');
        d.innerHTML = s;
        return (d.textContent || d.innerText || "").replace(/\\s+/g, " ").trim();
    };
    return {
        kreta_id: (item.ID === null || item.ID === undefined) ? "" : String(item.ID),
        kezdete: fmtDate(item.Kezdete),
        vege: fmtDate(item.Vege),
        igazolas_tipus: item.IgazolasTipusa_DNAME || "",
        megjegyzes: stripHtml(item.Megjegyzes)
    };
}"""

_JS_GRID_STATE = """
(gridId) => {
    let g = $(gridId).data('kendoGrid');
    if (!g) return null;
    let ds = g.dataSource;
    return {total: ds.total() || 0, page: ds.page() || 1,
            pageSize: ds.pageSize() || 0, count: ds.data().length};
}
"""

_JS_GRID_PAGE_ROWS = """
([gridId, mapperSrc, pageNum]) => {
    let g = $(gridId).data('kendoGrid');
    if (!g) return {missing: true};
    let ds = g.dataSource;
    if (pageNum && ds.page() !== pageNum) {
        ds.page(pageNum);
        return {pending: true};
    }
    try {
        const map = eval('(' + mapperSrc + ')');
        return {rows: ds.data().map(map)};
    } catch (e) {
        return {error: String(e)};
    }
}
"""

# A Kendo grid dataBound eseménye jelzi, melyik oldal töltődött be —
# így nem olvassuk ki az előző oldal adatait a lapozás közben.
_JS_GRID_INSTALL_HOOK = """
(gridId) => {
    let g = $(gridId).data('kendoGrid');
    if (!g) return false;
    if (!g.__kretaLoadedHook) {
        g.__kretaLoadedHook = true;
        g.bind('dataBound', function () {
            window.__kretaGridLoaded = window.__kretaGridLoaded || {};
            window.__kretaGridLoaded[gridId] = this.dataSource.page();
        });
    }
    return true;
}
"""

_JS_GRID_GOTO_PAGE = """
([gridId, pageNum]) => {
    window.__kretaGridLoaded = window.__kretaGridLoaded || {};
    window.__kretaGridLoaded[gridId] = null;
    let g = $(gridId).data('kendoGrid');
    if (g) g.dataSource.page(pageNum);
}
"""

_JS_GRID_QUERY_ALL = """
([gridId, total]) => {
    let g = $(gridId).data('kendoGrid');
    if (!g) return false;
    window.__kretaGridLoaded = window.__kretaGridLoaded || {};
    window.__kretaGridLoaded[gridId] = null;
    g.dataSource.query({ page: 1, pageSize: total });
    return true;
}
"""

_JS_GRID_LOADED_PAGE = """
(gridId) => ((window.__kretaGridLoaded || {})[gridId] || null)
"""


async def _wait_grid_data(page, grid_id, timeout=8.0):
    """Megvárja, hogy a grid betöltse az adatot (üres találatnál is visszatér)."""
    waited = 0.0
    state = None
    while waited <= timeout:
        state = await page.evaluate(_JS_GRID_STATE, grid_id)
        if not state:
            return None
        if (state.get("total") or 0) > 0 or (state.get("count") or 0) > 0:
            return state
        await asyncio.sleep(0.5)
        waited += 0.5
    return state


async def _grid_rows_now(page, grid_id, mapper_src, page_num):
    res = await page.evaluate(_JS_GRID_PAGE_ROWS, [grid_id, mapper_src, page_num])
    if res.get("error"):
        log(f"  [Grid olvasási hiba] {grid_id}: {res['error']}")
        return []
    return res.get("rows") or []


async def _read_kendo_grid_all(page, grid_id, mapper_src, max_pages=50):
    """A grid összes oldalának kiolvasása. None = a grid nem található."""
    state = await _wait_grid_data(page, grid_id)
    if not state:
        return None

    total = int(state.get("total") or 0)
    page_size = int(state.get("pageSize") or 0)
    current = int(state.get("page") or 1)
    count = int(state.get("count") or 0)

    if not await page.evaluate(_JS_GRID_INSTALL_HOOK, grid_id):
        return None

    # Első kör: kérjük le egy lapon az összes sort (a gyakorlatban < 1000 sor).
    if total > count and total > 0:
        await page.evaluate(_JS_GRID_QUERY_ALL, [grid_id, total])
        waited = 0.0
        while waited <= 12.0:
            await asyncio.sleep(0.4)
            waited += 0.4
            st = await page.evaluate(_JS_GRID_STATE, grid_id)
            if st and int(st.get("count") or 0) >= total:
                current, page_size = 1, total
                break
        else:
            st = await page.evaluate(_JS_GRID_STATE, grid_id)
            if st:
                current = int(st.get("page") or 1)
                page_size = int(st.get("pageSize") or page_size or 0)

    rows = await _grid_rows_now(page, grid_id, mapper_src, current)

    # Ha a szerver mégis lapozott (pageSize-korlát), oldalanként folytatjuk.
    if page_size > 0 and total > len(rows):
        pages = min(max_pages, (total + page_size - 1) // page_size)
        for p in range(current + 1, pages + 1):
            await page.evaluate(_JS_GRID_GOTO_PAGE, [grid_id, p])
            waited = 0.0
            while waited <= 8.0:
                await asyncio.sleep(0.3)
                waited += 0.3
                loaded = await page.evaluate(_JS_GRID_LOADED_PAGE, grid_id)
                if loaded == p:
                    break
            rows.extend(await _grid_rows_now(page, grid_id, mapper_src, p))
    return rows


async def scrape_hianyzasok(page, diak_nev, institute_code):
    """Késések és hiányzások kiolvasása a 'Mulasztások' menü oldaláról."""
    log("\n[HIÁNYZÁSOK] Navigáció a 'Késések, hiányzások' oldalra...")
    try:
        await page.goto(f"https://{institute_code}.e-kreta.hu/Hianyzas/Hianyzasok")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_selector('#HianyzasGrid, #searchForm', timeout=15000)
        await asyncio.sleep(1)

        # A grid autoBind=false → a keresőpanel frissítése indítja a betöltést.
        await page.evaluate('''() => {
            if (typeof KretaGridHelper !== 'undefined' && KretaGridHelper.refreshGridSearchPanel) {
                KretaGridHelper.refreshGridSearchPanel("HianyzasGrid", "searchForm");
            } else {
                let btn = document.getElementById('searchPanelBtn');
                if (btn) btn.click();
            }
        }''')
        await page.wait_for_load_state("networkidle")

        rows = await _read_kendo_grid_all(page, "#HianyzasGrid", _HIANYZAS_MAPPER)
        if rows is None:
            log("  [Figyelmeztetés]: a #HianyzasGrid nem található, a korábbi adatok megmaradnak.")
            return None

        save_hianyzasok_to_db(diak_nev, rows)
        keses = sum(1 for r in rows if r.get("perc") is not None)
        log(f"  [HIÁNYZÁSOK OK] {len(rows)} db mulasztás rögzítve ({keses} db késés).")
        return rows
    except Exception as ex:
        log(f"  [Hiányzás lekérési hiba]: {ex}")
        return None


async def scrape_igazolasok(page, diak_nev, institute_code):
    """Igazolások kiolvasása az 'Igazolások' oldalról."""
    log("\n[IGAZOLÁSOK] Navigáció az 'Igazolások' oldalra...")
    try:
        await page.goto(f"https://{institute_code}.e-kreta.hu/Hianyzas/InformaciokIgazolasok")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_selector('#IgazolasGrid', timeout=15000)
        await asyncio.sleep(1)

        await page.evaluate('''() => {
            let g = $('#IgazolasGrid').data('kendoGrid');
            if (g) g.dataSource.read();
        }''')
        await page.wait_for_load_state("networkidle")

        rows = await _read_kendo_grid_all(page, "#IgazolasGrid", _IGAZOLAS_MAPPER)
        if rows is None:
            log("  [Figyelmeztetés]: az #IgazolasGrid nem található, a korábbi adatok megmaradnak.")
            return None

        save_igazolasok_to_db(diak_nev, rows)
        log(f"  [IGAZOLÁSOK OK] {len(rows)} db igazolás rögzítve.")
        return rows
    except Exception as ex:
        log(f"  [Igazolás lekérési hiba]: {ex}")
        return None

async def scrape_uzenetek(page, diak_nev):
    """Be- és letölti az e-Ügyintézés felületről az új üzeneteket és csatolmányokat."""
    log("\n7. Navigáció az e-Ügyintézés (Üzenetek) oldalra...")
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

async def scrape_esemenyek(page, diak_nev, institute_code,
                           existing_hazi_keys, existing_szamonkeres_keys):
    """Értékelések, feljegyzések, házi feladatok és számonkérések kiolvasása.

    A négy adatkör egy navigációs sorozatban jön le; a mentés típusonként
    történik (save_esemenyek_by_type), hogy az API-ból már frissült típusokat
    ki lehessen hagyni, és ne legyen dupla írás.
    """
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

    return {
        "jegyek": jegyek,
        "feljegyzesek": feljegyzesek,
        "hazi": hazifeladatok,
        "szamonkeresek": szamonkeresek,
    }


async def process_student(page, student, skip=None, tracker=None,
                          before_event_keys=None, before_hianyzas_keys=None):
    """Egy diák teljes Playwright-szinkronja.

    `skip`: azon adatkörök kulcsai, amelyeket az API már sikeresen frissített —
    ezeket itt nem írjuk felül (nincs dupla írás). `tracker`: forrásnapló.
    A `before_*` kulcsokat a hívó rögzítheti az API-szakasz ELŐTT, hogy az új
    események kimutatása az API-mentést is helyesen beszámolja.
    """
    diak_nev = student.get("diak_nev", "Ismeretlen")
    institute_code = student.get("institute_code", "")
    username = student.get("username", "")
    password = student.get("password", "")

    skip = set(skip or ())
    if tracker is None:
        tracker = kreta_sync.SourceTracker(diak_nev)

    student_scrape_messages = student.get("scrape_messages", GLOBAL_SCRAPE_MESSAGES)

    log("\n" + "=" * 70)
    log(f"  FELDOLGOZÁS: {diak_nev.upper()} (Iskola: {institute_code})")
    log("=" * 70)
    if skip:
        log("  API-ból már frissült adatkörök: " + ", ".join(
            kreta_sync.LABELS.get(key, key)
            for key in kreta_sync.DATASET_KEYS if key in skip))

    # A frissítés ELŐTTI állapot — a végén ebből számoljuk az új eseményeket.
    if before_event_keys is None:
        before_event_keys = get_event_key_set(diak_nev)
    if before_hianyzas_keys is None:
        before_hianyzas_keys = get_hianyzas_key_set(diak_nev)

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
    if "orarend" in skip:
        log("[ÓRAREND] API-ból már frissült — a Playwright lépés kihagyva.")
    else:
        await scrape_orarend(page, diak_nev, institute_code)
        kreta_sync.mark_playwright(tracker, "orarend")

    # --- 2-5. ESEMÉNYEK KINYERÉSE (a már API-ból frissült típusok kihagyásával) ---
    esemenyek = {}
    if any(key not in skip for key in kreta_sync.EVENT_DATASETS):
        esemenyek = await scrape_esemenyek(
            page, diak_nev, institute_code, existing_hazi_keys, existing_szamonkeres_keys
        )
        for key in kreta_sync.EVENT_DATASETS:
            if key not in skip:
                kreta_sync.mark_playwright(tracker, key)
    else:
        log("\n[ESEMÉNYEK] Minden eseménytípus API-ból frissült — a Playwright blokk kihagyva.")

    # --- ESEMÉNYEK MENTÉSE (csak a Playwrightból jött típusok) ---
    tipus_parok = (
        ("jegyek", "Értékelés"),
        ("feljegyzesek", "Feljegyzés"),
        ("hazi", "Házi feladat"),
        ("szamonkeresek", "Bejelentett számonkérés"),
    )
    mentendo_tipusok = [tipus for key, tipus in tipus_parok if key not in skip]
    mentendo = [row for key, _ in tipus_parok if key not in skip
                for row in esemenyek.get(key, [])]

    if mentendo_tipusok:
        save_esemenyek_by_type(diak_nev, mentendo, completed_hazi, mentendo_tipusok)

    if mentendo:
        log(f"\n{diak_nev} adataiból {len(mentendo)} db esemény sikeresen elmentve!")
    elif mentendo_tipusok:
        log(f"Figyelem: {diak_nev} fiókjából nem sikerült eseményadatot kinyerni.")

    # --- 6. HIÁNYZÁSOK / KÉSÉSEK ÉS IGAZOLÁSOK KINYERÉSE ---
    if "hianyzasok" in skip:
        log("[HIÁNYZÁSOK] API-ból már frissült — a Playwright lépés kihagyva.")
    else:
        hianyzasok = await scrape_hianyzasok(page, diak_nev, institute_code)
        if hianyzasok is not None:
            NEW_HIANYZAS_COUNTS[diak_nev] = diff_hianyzas_counts(before_hianyzas_keys, hianyzasok)
            uj = NEW_HIANYZAS_COUNTS[diak_nev]
            kreta_sync.mark_playwright(tracker, "hianyzasok")
            if uj.get("db"):
                log(f"    [ÚJ HIÁNYZÁS]: {uj['db']} db (ebből {uj.get('igazolatlan_ora', 0)} igazolatlan óra)")
        else:
            NEW_HIANYZAS_COUNTS[diak_nev] = {"db": 0, "igazolatlan_ora": 0}
            tracker.record("hianyzasok", "playwright", ok=False,
                           reason="a hiányzás grid nem olvasható")

    if "igazolasok" in skip:
        log("[IGAZOLÁSOK] API-ból már frissült — a Playwright lépés kihagyva.")
    else:
        await scrape_igazolasok(page, diak_nev, institute_code)
        kreta_sync.mark_playwright(tracker, "igazolasok")

    # --- 7. E-ÜGYINTÉZÉS ÜZENETEK KINYERÉSE ---
    if "uzenetek" in skip:
        log("\n7. Üzenetek: API-ból már frissült — a Playwright lépés kihagyva.")
    elif student_scrape_messages:
        new_msg_count = await scrape_uzenetek(page, diak_nev) or 0
        NEW_MESSAGE_COUNTS[diak_nev] = new_msg_count
        kreta_sync.mark_playwright(tracker, "uzenetek")
    else:
        NEW_MESSAGE_COUNTS[diak_nev] = 0
        kreta_sync.mark_playwright(tracker, "uzenetek", reason="üzenet-szinkron kikapcsolva")
        log(f"\n7. Üzenetek lekérése KI VAN KAPCSOLVA ennél a diáknál ({diak_nev}).")

    # Új események (a frissítés előtti és utáni állapot különbsége)
    NEW_EVENT_COUNTS[diak_nev] = diff_event_counts(before_event_keys, get_event_key_set(diak_nev))

    # --- 8. KIJELENTKEZÉS A FIÓKBÓL ---
    log(f"\nKijelentkezés ({diak_nev})...")
    try:
        await page.goto(f"https://{institute_code}.e-kreta.hu/Home/LogOut")
        await page.wait_for_load_state("networkidle")
        log("Sikeres kijelentkezés!")
    except Exception as e:
        log(f"Kijelentkezési figyelmeztetés: {e}")

SYNC_SOURCES = {}
SYNC_SHADOW_REPORTS = {}


def _finalize_student_counts(diak_nev, before_event_keys):
    """Az új események/számlálók lezárása akkor is, ha nincs Playwright-szakasz."""
    NEW_EVENT_COUNTS[diak_nev] = diff_event_counts(before_event_keys, get_event_key_set(diak_nev))
    NEW_HIANYZAS_COUNTS.setdefault(diak_nev, {})
    NEW_MESSAGE_COUNTS.setdefault(diak_nev, 0)


async def run_shadow_student(student, page):
    """Árnyék-ellenőrzés: a Playwright egy DB-másolaton fut, csak összehasonlítunk.

    A valódi DB-hez csak az API ír, így nincs dupla írás és dupla értesítés.
    A `NEW_*` számlálókat a végén visszaállítjuk, hogy az API eredménye maradjon.
    """
    global DB_FILE

    diak_nev = student.get("diak_nev", "Ismeretlen")
    if page is None:
        return None

    main_db = DB_FILE
    shadow_db = main_db + ".shadow"
    log(f"\n[ÁRNYÉK] Playwright-ellenőrzés külön DB-másolaton ({diak_nev}) ...")
    try:
        if os.path.exists(shadow_db):
            os.remove(shadow_db)
        shutil.copyfile(main_db, shadow_db)
    except OSError as exc:
        log(f"  [ÁRNYÉK] a DB másolása nem sikerült: {exc}")
        return None

    saved = (dict(NEW_EVENT_COUNTS), dict(NEW_MESSAGE_COUNTS), dict(NEW_HIANYZAS_COUNTS))
    try:
        DB_FILE = shadow_db
        await process_student(page, student, tracker=kreta_sync.SourceTracker(diak_nev))
    except Exception as exc:
        log(f"  [ÁRNYÉK] a Playwright-ellenőrzés hibával futott: {exc}")
        return None
    finally:
        DB_FILE = main_db
        NEW_EVENT_COUNTS.clear()
        NEW_EVENT_COUNTS.update(saved[0])
        NEW_MESSAGE_COUNTS.clear()
        NEW_MESSAGE_COUNTS.update(saved[1])
        NEW_HIANYZAS_COUNTS.clear()
        NEW_HIANYZAS_COUNTS.update(saved[2])

    report = kreta_shadow.compare_databases(main_db, shadow_db, diak_nev)
    for line in kreta_shadow.format_report(report):
        log(line)
    log(f"  [ÁRNYÉK] összes eltérés: {report['total_diffs']}"
        + (" — minden egyezik" if report["is_match"] else " — FIGYELEM, ellenőrizni kell"))
    SYNC_SHADOW_REPORTS[diak_nev] = {
        "is_match": report["is_match"],
        "total_diffs": report["total_diffs"],
        "tables": {
            name: {"primary": data.get("primary"), "shadow": data.get("shadow"),
                   "diffs": data.get("diffs")}
            for name, data in report.get("tables", {}).items()
        },
    }
    try:
        os.remove(shadow_db)
    except OSError:
        pass
    return report


async def run_student(student, page, tracker):
    """Egy diák szinkronja a beállított mód szerint (API és/vagy Playwright)."""
    diak_nev = student.get("diak_nev", "Ismeretlen")

    # Az "előtte" állapotot az API-szakasz ELŐTT kell rögzíteni.
    before_events = get_event_key_set(diak_nev)
    before_hianyzas = get_hianyzas_key_set(diak_nev)

    if kreta_sync.needs_api(SYNC_MODE):
        await kreta_sync.run_api_datasets(student, API_PROVIDERS, tracker, log)
        if kreta_sync.needs_playwright(SYNC_MODE):
            kreta_sync.log_playwright_plan(tracker, SYNC_MODE, log)

    if SYNC_SHADOW and kreta_sync.needs_playwright(SYNC_MODE):
        await run_shadow_student(student, page)

    skip = tracker.api_done()

    if not kreta_sync.needs_playwright(SYNC_MODE):
        _finalize_student_counts(diak_nev, before_events)
        failures = tracker.failures()
        if failures:
            raise RuntimeError(
                "API-ból nem frissült: " + ", ".join(
                    f"{kreta_sync.LABELS.get(key, key)} ({reason})"
                    for key, reason in failures.items()))
        return

    missing = [key for key in kreta_sync.DATASET_KEYS if key not in skip]
    if not missing:
        log(f"  {diak_nev}: minden adatkör API-ból frissült — Playwright nélkül.")
        _finalize_student_counts(diak_nev, before_events)
        return

    if page is None:
        raise RuntimeError("Nincs böngésző a Playwright-szakaszhoz.")

    await process_student(page, student, skip=skip, tracker=tracker,
                          before_event_keys=before_events,
                          before_hianyzas_keys=before_hianyzas)


async def run_students(active_students, page):
    """A diákon végigmenő ciklus; az egyik diák hibája nem állítja meg a többit."""
    failed = []
    ok_count = 0
    for student in active_students:
        diak_nev = student.get("diak_nev", "Ismeretlen")
        tracker = kreta_sync.SourceTracker(diak_nev)
        try:
            await run_student(student, page, tracker)
            ok_count += 1
            if page is not None:
                await asyncio.sleep(2)
        except Exception as err:
            failed.append(diak_nev)
            log(f"\nHIBA történt {diak_nev} feldolgozása során: {err}")
        finally:
            SYNC_SOURCES[diak_nev] = tracker.as_dict()
            if tracker.outcomes:
                log(f"  {diak_nev} adatforrások: {tracker.summary_line()}")
    kreta_api_sync.close_clients()
    return ok_count, failed


async def main():
    log("=" * 70)
    log(f"SZINKRONIZÁCIÓ INDÍTÁSA - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 70)
    init_db()

    active_students = [s for s in STUDENTS if s.get("active", True)]
    log(f"Készülődés {len(active_students)} diák adatainak lekérésére...")
    log(f"Szinkron mód: {SYNC_MODE} (playwright | api | api_first)")
    if SYNC_SHADOW:
        log("Árnyék/ellenőrző mód: BE (a Playwright külön DB-másolaton fut, csak összehasonlítás)")
    if kreta_sync.needs_playwright(SYNC_MODE):
        log(f"Böngésző üzemmód: {'Háttérben (Headless)' if HEADLESS_MODE else 'Látható (Headed)'}")
    log(f"Globális üzenet-szinkronizálás: {'BE' if GLOBAL_SCRAPE_MESSAGES else 'KI'}")

    ok_count = 0
    failed = []

    if kreta_sync.needs_playwright(SYNC_MODE):
        user_data_dir = os.environ.get("KRETA_BROWSER_DATA_DIR",
                                       os.path.join(DATA_DIR, "browser_user_data"))
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
            ok_count, failed = await run_students(active_students, page)

            await asyncio.sleep(2)
            await context.close()
    else:
        # Tiszta API mód: böngésző nélkül.
        ok_count, failed = await run_students(active_students, None)

    log("\n" + "=" * 70)
    log("MINDEN DIÁK FELDOLGOZÁSA BEFEJEZŐDÖTT!")
    if failed:
        log(f"FIGYELEM: {len(failed)} diák adata NEM frissült: {', '.join(failed)}")
    log("=" * 70)

    # Géppel olvasható összegzés a Flask appnak (stdout-ra, a naplóba nem kell).
    summary = {
        "total": len(active_students),
        "ok": ok_count,
        "failed": failed,
        "new_events": NEW_EVENT_COUNTS,
        "new_messages": NEW_MESSAGE_COUNTS,
        "new_hianyzasok": NEW_HIANYZAS_COUNTS,
        "sources": SYNC_SOURCES,
        "shadow": SYNC_SHADOW_REPORTS,
    }
    print(RESULT_MARKER + json.dumps(summary, ensure_ascii=False), flush=True)

    # Kilépési kód: 0 = minden diák rendben, 2 = részleges hiba, 1 = végzetes.
    return 0 if not failed else 2

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))