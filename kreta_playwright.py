# -*- coding: utf-8 -*-
"""A KRÉTA szinkron futtatója: config/logging, DB-séma, mentők, API-szolgáltatók.

Kaneo #64 (v2.5.0): a böngészős (Playwright) scraper útja kikerült — minden
adatkör a Kréta mobil API-ból frissül, böngésző nélkül. A korábbi `api_first` /
`playwright` config-értékek figyelmeztetés mellett automatikusan `api`-ra váltanak.
"""
import asyncio
import importlib.util
import json
import sqlite3
import os
import sys
import logging
import logging.handlers
from datetime import datetime

import kreta_api
import kreta_api_sync
import kreta_sync
import kreta_tanev
from kreta_paths import CSATOLMANYOK_DIR as _PATHS_CSATOLMANYOK_DIR
from kreta_paths import DATA_DIR as _PATHS_DATA_DIR
from kreta_paths import ensure_data_dir as _ensure_data_dir

# A data/ könyvtár létrehozása a napló/DB megnyitása előtt (KRÉ-14 audit, F2).
_ensure_data_dir()

# --- KONFIGURÁCIÓ ÉS LOGGING BEÁLLÍTÁSA ---
# Az útvonalak a `kreta_paths.py`-ból jönnek (egy igazságforrás, KRÉ-14 #98).
# A konténerben KRETA_DATA_DIR=/app/data jön a compose-ból; lokálisan a `data/`
# (vagy visszafelé kompatibilisen a régi gyökér-elrendezés) él.
DATA_DIR = _PATHS_DATA_DIR
CONFIG_FILE = os.environ.get("KRETA_CONFIG_FILE", os.path.join(DATA_DIR, "config.json"))
DB_FILE = os.environ.get("KRETA_DB_FILE", os.path.join(DATA_DIR, "kreta_adatok.db"))
LOG_FILE = os.environ.get("KRETA_LOG_FILE", os.path.join(DATA_DIR, "sync.log"))
# WAL csak opt-in (a data kötet FUSE mount — lásd a Dockerfile/compose megjegyzést)
SQLITE_WAL = os.environ.get("KRETA_SQLITE_WAL", "0").strip().lower() in ("1", "true", "yes", "on")
CSATOLMANYOK_DIR = _PATHS_CSATOLMANYOK_DIR
# Napló-rotáció: ne nőjön korlátlanul a sync.log (a felület is ezt olvassa).
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


# Az API-kliens naplózza, honnan jött a munkamenet (cache / refresh / új belépés),
# hogy a sync.log-ban látszódjon: küld-e a KRÉTA új-belépés e-mailt vagy sem.
kreta_api.set_log_hook(log)

# `--init-db`: csak a sémát hozza létre (a Flask app hívja, ha a DB fájl
# hiányzik vagy üres) — ilyenkor config és diákok nélkül is futnia kell.
INIT_DB_ONLY = "--init-db" in sys.argv[1:]

if INIT_DB_ONLY:
    config = {}
else:
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

STUDENTS = config.get("STUDENTS", [])
GLOBAL_SCRAPE_MESSAGES = config.get("SCRAPE_MESSAGES", True)


def effective_sync_mode(mode, playwright_available):
    """A kért mód, ha nincs böngészős út, biztonságosan `api`-ra vált.

    A böngészős (Playwright) scraper a v2.5.0-ban kikerült (Kaneo #64). A régi
    config-értékek (`api_first`/`playwright`) miatt nem szabad elszállni —
    a futtató figyelmeztetés mellett API módban megy tovább.
    """
    if kreta_sync.needs_playwright(mode) and not playwright_available:
        return "api"
    return mode


# Szinkron forrása: api (lásd kreta_sync.py). A böngészős értékek visszamenőleg
# kompatibilisen viselkednek: a `PLAYWRIGHT_AVAILABLE` itt mindig hamis lesz,
# így az `api_first`/`playwright` kérés automatikusan `api`-ra vált.
_requested_sync_mode = kreta_sync.resolve_sync_mode(config)
PLAYWRIGHT_AVAILABLE = importlib.util.find_spec("playwright") is not None
SYNC_MODE = effective_sync_mode(_requested_sync_mode, PLAYWRIGHT_AVAILABLE)
if SYNC_MODE != _requested_sync_mode:
    log("[FIGYELEM] A böngészős (Playwright) út a v2.5.0-ban kikerült — "
        "API módban folytatom.")

# Adatkör-szintű API-szolgáltatók: kulcs -> függvény(diák dict) -> None.
# A szolgáltató lekér és ment; ha hibát dob, az adatkör részleges hibának
# számít (a többi adatkör és diák megy tovább, a futás riasztást kap).
# A szolgáltatók a fájl alján, a mentő függvények után vannak regisztrálva.

# `--init-db`: csak a sémát hozza létre, diákok nélkül is (ezt hívja a Flask
# app, ha a DB fájl hiányzik vagy üres). Ezért ott nem lépünk ki.
if not STUDENTS and not INIT_DB_ONLY:
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
            suly_szazalek INTEGER,
            bej_datum TEXT,
            hatarido TEXT,
            ertekelo TEXT,
            tipus TEXT,
            mod TEXT,
            tema TEXT,
            cim TEXT,
            tartalom TEXT,
            kesz INTEGER DEFAULT 0,
            letrehozva TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS uzenetek (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            diak_nev TEXT,
            uzenet_id TEXT,
            posta_id TEXT,
            felado TEXT,
            targy TEXT,
            idopont TEXT,
            szoveg TEXT,
            csatolmany_nev TEXT,
            csatolmany_utvonal TEXT,
            csatolmany_proba INTEGER DEFAULT 0,
            olvasott INTEGER DEFAULT 0,
            letrehozva TEXT
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
            rogzites_datum TEXT,
            letrehozva TEXT
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
            megjegyzes TEXT,
            letrehozva TEXT
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
    # A jegyek súlyszázaléka (mobil API: SulySzazalekErteke) - csak az API adja.
    if "suly_szazalek" not in es_columns:
        try:
            cursor.execute("ALTER TABLE esemenyek ADD COLUMN suly_szazalek INTEGER")
        except Exception:
            pass

    cursor.execute("PRAGMA table_info(uzenetek)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    
    required_columns = {
        "diak_nev": "TEXT",
        "uzenet_id": "TEXT",
        "posta_id": "TEXT",
        "felado": "TEXT",
        "targy": "TEXT",
        "idopont": "TEXT",
        "szoveg": "TEXT",
        "csatolmany_nev": "TEXT",
        "csatolmany_utvonal": "TEXT",
        "csatolmany_proba": "INTEGER DEFAULT 0",
        "olvasott": "INTEGER DEFAULT 0"
    }
    
    for col_name, col_type in required_columns.items():
        if col_name not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE uzenetek ADD COLUMN {col_name} {col_type}")
                log(f"  [Adatbázis séma frissítve]: '{col_name}' oszlop hozzáadva az 'uzenetek' táblához.")
                if col_name == "olvasott":
                    # A történeti üzenetek olvasottként indulnak (Kaneo #11).
                    cursor.execute("UPDATE uzenetek SET olvasott = 1")
                    log("  [Adatbázis séma frissítve]: a meglévő üzenetek olvasottként indulnak.")
            except Exception as ex:
                log(f"  [Sémafrissítési figyelmeztetés ({col_name})]: {ex}")

    # Tanév-dimenzió (Kaneo #40): oszlopok + a meglévő sorok feltöltése.
    # Csak ALTER/UPDATE, ID-stabil; a backfill újraindítható.
    added = kreta_tanev.ensure_tanev_schema(conn, log_fn=log)
    if added:
        log(f"  [Adatbázis séma frissítve]: tanév-oszlopok: {', '.join(added)}")
    kreta_tanev.backfill_tanev(conn, log_fn=log, batch=200)

    # A saját DB-be kerülés időpontja (#147): új oszlop + régi sorok backfillje.
    kreta_tanev.ensure_first_seen_schema(conn, log_fn=log)

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

_EVENT_KEY_FIELDS = (
    "esemeny_tipus", "tantargy", "bej_datum", "hatarido", "ertek",
    "szam_ertek", "tema", "cim", "tartalom",
)
_EVENT_KEY_COLUMNS = ", ".join(_EVENT_KEY_FIELDS)


def _event_key_from_mapping(row):
    return tuple("" if row.get(col) is None else str(row.get(col))
                 for col in _EVENT_KEY_FIELDS)


def get_event_first_seen_map(diak_nev, tipus):
    """A meglévő események `letrehozva` értékei tartalom-kulcs szerint (#147)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    out = {}
    try:
        cursor.execute(
            f"SELECT {_EVENT_KEY_COLUMNS}, letrehozva FROM esemenyek"
            " WHERE diak_nev = ? AND esemeny_tipus = ?", (diak_nev, tipus))
        for row in cursor.fetchall():
            key = tuple("" if v is None else str(v) for v in row[:-1])
            out[key] = row[-1] or ""
    except Exception as ex:
        log(f"  [DB hiba - letrehozva kulcsok]: {ex}")
    finally:
        conn.close()
    return out


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


def save_hianyzasok_to_db(diak_nev, rows, window=None):
    """Inkrementális mentés: a rekord azonosítója a dátum + órasorszám.

    A KRÉTA mindig a teljes listát adja (nincs delta végpont), ezért a beolvasás
    teljes; a DB-be viszont csak a változás megy: a meglévő sor frissül (stabil
    ID), az új beszúródik, a KRÉTA-ból eltűnt sor pedig törlődik.

    **Tanév-scope (Kaneo #40):** az „eltűnt" sorok törlése csak a most letöltött
    tanévekre és a lekérési ablakon belülre hat (`window=(start, end)`); a
    korábbi tanévek hiányzásai akkor sem törlődnek, ha az API nem adja vissza
    őket. A sorok tanéve a `mulasztas_datum`-ból számítva kerül a DB-be.
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
            })] = (rid, datum)

        seen = set()
        for r in rows:
            key = hianyzas_key(r)
            if key in seen:
                continue
            seen.add(key)
            tanev = kreta_tanev.tanev_of(r.get("mulasztas_datum"))
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
                tanev,
                kreta_tanev.TANEV_FORRAS_SZAMITOTT,
            )
            if key in existing:
                cursor.execute('''
                    UPDATE hianyzasok SET
                        kreta_id = ?, mulasztas_datum = ?, ora_sorszam = ?, perc = ?,
                        tantargy = ?, tema = ?, tanar = ?, mulasztas_tipus = ?,
                        igazolt = ?, tanorai_celu = ?, igazolas_tipus = ?, rogzites_datum = ?,
                        tanev = ?, tanev_forras = ?
                    WHERE id = ?
                ''', values + (existing[key][0],))
            else:
                cursor.execute('''
                    INSERT INTO hianyzasok
                    (kreta_id, mulasztas_datum, ora_sorszam, perc, tantargy, tema, tanar,
                     mulasztas_tipus, igazolt, tanorai_celu, igazolas_tipus, rogzites_datum,
                     tanev, tanev_forras, diak_nev, letrehozva)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', values + (diak_nev, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        # A KRÉTA-ból eltűnt (törölt/javított) sorok eltávolítása — csak a most
        # letöltött tanévekből és az ablakon belül (Kaneo #40).
        batch_years = {kreta_tanev.tanev_of(r.get("mulasztas_datum")) for r in rows} - {""}
        deletable = _deletable_years(batch_years, window)
        stale_pairs = [(rid, datum) for key, (rid, datum) in existing.items()
                       if key not in seen]
        for rid in _deletable_ids(stale_pairs, deletable, window):
            cursor.execute("DELETE FROM hianyzasok WHERE id = ?", (rid,))
        conn.commit()
    except Exception as ex:
        log(f"  [Hiba a hiányzások mentésekor]: {ex}")
    finally:
        conn.close()


def save_igazolasok_to_db(diak_nev, rows, window=None):
    """A diák igazolásainak mentése **upserttel** és adatvédelemmel (Kaneo #40/#42).

    - A meglévő sor a `kreta_id` (ennek híján a mezők kulcsa) alapján **frissül**
      (stabil ID), az új beszúródik; a KRÉTA-ból eltűnt sor csak a most letöltött
      tanévekből törlődik.
    - **Adatvédelem:** ha az új lista a meglévő sorok `KRETA_SYNC_MIN_RATIO`
      (alap 0,5) arányánál kevesebbet hoz — vagy teljesen üres, miközben volt
      adat —, a törlést **kihagyja**, naplóz, és `blocked` jelzést ad vissza.

    Visszatérés: `{"saved": int, "blocked": {kulcs: {"old","new"}}, "error": str}`
    """
    result = {"saved": 0, "blocked": {}, "error": ""}
    seen = set()
    egyedi = []
    for r in rows or []:
        kreta_id = str(r.get("kreta_id") or "").strip()
        key = kreta_id or f"{r.get('kezdete')}|{r.get('vege')}|{r.get('igazolas_tipus')}|{r.get('megjegyzes')}"
        if key in seen:
            continue
        seen.add(key)
        egyedi.append((key, kreta_id, r))

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        existing = {}
        for rid, kid, kezd, veg, tip, megj in cursor.execute(
            "SELECT id, kreta_id, kezdete, vege, igazolas_tipus, megjegyzes"
            " FROM igazolasok WHERE diak_nev = ?", (diak_nev,)
        ).fetchall():
            key = str(kid or "").strip() or f"{kezd}|{veg}|{tip}|{megj}"
            existing[key] = (rid, kezd, veg)
        old_count = len(existing)
        new_count = len(egyedi)
        if old_count > 0 and (new_count == 0 or _would_drop_too_much(old_count, new_count)):
            log(f"  [FIGYELEM] Igazolások: {new_count} új sor a meglévő {old_count} helyett "
                f"— a teljes cserét kihagytam (adatvédelem, küszöb: {sync_min_ratio():.2f}).")
            result["blocked"]["igazolasok"] = {"old": old_count, "new": new_count}
            return result

        # A törölhető tanévek: a most letöltött sorok tanévei (ablak nélkül mind).
        batch_years = {kreta_tanev.tanev_of(r.get("kezdete") or r.get("vege"))
                       for _, _, r in egyedi} - {""}
        deletable = _deletable_years(batch_years, window)

        for key, kreta_id, r in egyedi:
            tanev = kreta_tanev.tanev_of(r.get("kezdete") or r.get("vege"))
            if key in existing:
                cursor.execute('''
                    UPDATE igazolasok SET kezdete = ?, vege = ?, igazolas_tipus = ?,
                        megjegyzes = ?, tanev = ?, tanev_forras = ?
                    WHERE id = ?
                ''', (
                    r.get("kezdete") or "", r.get("vege") or "",
                    r.get("igazolas_tipus") or "", r.get("megjegyzes") or "",
                    tanev, kreta_tanev.TANEV_FORRAS_SZAMITOTT, existing[key][0],
                ))
            else:
                cursor.execute('''
                    INSERT INTO igazolasok
                    (diak_nev, kreta_id, kezdete, vege, igazolas_tipus, megjegyzes,
                     tanev, tanev_forras, letrehozva)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    diak_nev, kreta_id, r.get("kezdete") or "", r.get("vege") or "",
                    r.get("igazolas_tipus") or "", r.get("megjegyzes") or "",
                    tanev, kreta_tanev.TANEV_FORRAS_SZAMITOTT,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ))
        # Az eltűnt sorok törlése — csak a batch tanéveiből, ablakon belül.
        stale_pairs = [(rid, kezd or veg) for key, (rid, kezd, veg) in existing.items()
                       if key not in seen]
        for rid in _deletable_ids(stale_pairs, deletable, window):
            cursor.execute("DELETE FROM igazolasok WHERE id = ?", (rid,))
        conn.commit()
        result["saved"] = new_count
    except Exception as ex:
        log(f"  [Hiba az igazolások mentésekor]: {ex}")
        result["error"] = str(ex)
    finally:
        conn.close()
    return result


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


def hianyzas_api_window(diak_nev, today=None):
    """Az API-lekérés ablaka: az aktuális tanév kezdete – ma (Kaneo #40).

    A `diak_nev` paraméter a hívói kompatibilitás miatt maradt meg.
    """
    return kreta_api_sync.tanev_api_window(today)


def api_provider_hianyzasok(student, client_factory=None):
    """Hiányzások/késések frissítése a mobil API-ból (inkrementális, stabil ID)."""
    diak_nev = student.get("diak_nev", "Ismeretlen")
    start, end = hianyzas_api_window(diak_nev)
    log(f"\n[API] Hiányzások lekérése: {start} .. {end} ...")
    client = client_factory(student) if client_factory else kreta_api_sync.client_for(student)
    rows = kreta_api_sync.fetch_omissions(client, start, end)
    merge_existing_hianyzas_fields(rows, get_existing_hianyzas_fields(diak_nev))
    before = get_hianyzas_key_set(diak_nev)
    save_hianyzasok_to_db(diak_nev, rows, window=(start, end))
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
    result = save_igazolasok_to_db(diak_nev, rows)
    _raise_if_blocked(result, "igazolások")
    log(f"  [IGAZOLÁSOK OK] {len(rows)} db igazolás az API-ból.")


def evaluation_api_window(diak_nev, today=None):
    """A jegyek API-ablaka: az aktuális tanév kezdete – ma (Kaneo #40)."""
    return kreta_api_sync.tanev_api_window(today)


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
    saved = save_esemenyek_by_type(diak_nev, rows, set(), ["Értékelés"], window=(start, end))
    _raise_if_blocked(saved, "jegyek")
    log(f"  [JEGYEK OK] {len(rows)} db értékelés az API-ból.")


def events_api_window(diak_nev, tipus, today=None):
    """Az eseménytípus API-ablaka: a tanév kezdete – ma (+ lookahead).

    A házi feladat és a bejelentett számonkérés **jövőbeli** határidőt hordoz,
    ezért ezeknél az ablak előre is nyúlik (`FUTURE_LOOKAHEAD_DAYS`) — enélkül a
    következő hetek dolgozatai/házijai nem jönnének le az API-ból.
    """
    lookahead = (kreta_api_sync.FUTURE_LOOKAHEAD_DAYS
                 if tipus in kreta_api_sync.FUTURE_DATED_EVENT_TYPES else 0)
    return kreta_api_sync.tanev_api_window(today, lookahead_days=lookahead)


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
    save_esemenyek_by_type(diak_nev, rows, get_completed_hazi_map(diak_nev),
                           ["Házi feladat"], window=(start, end))
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
    save_esemenyek_by_type(diak_nev, rows, set(), ["Bejelentett számonkérés"], window=(start, end))
    uj = len({_hazi_key(r) for r in rows} - before)
    log(f"  [SZÁMONKÉRÉS OK] {len(rows)} db számonkérés az API-ból ({uj} db új).")


def api_provider_feljegyzesek(student, client_factory=None):
    """Feljegyzések frissítése az API-ból (teljes csere a szeleten belül)."""
    diak_nev = student.get("diak_nev", "Ismeretlen")
    start, end = events_api_window(diak_nev, "Feljegyzés")
    log(f"\n[API] Feljegyzések lekérése: {start} .. {end} ...")
    client = client_factory(student) if client_factory else kreta_api_sync.client_for(student)
    rows = kreta_api_sync.fetch_notes(client, start, end)
    saved = save_esemenyek_by_type(diak_nev, rows, set(), ["Feljegyzés"], window=(start, end))
    _raise_if_blocked(saved, "feljegyzések")
    log(f"  [FELJEGYZÉS OK] {len(rows)} db feljegyzés az API-ból.")


def api_provider_orarend(student, client_factory=None):
    """Órarend frissítése az API-ból (aktuális + következő hét, fogadóórákkal)."""
    diak_nev = student.get("diak_nev", "Ismeretlen")
    start, end = kreta_api_sync.week_window()
    log(f"\n[API] Órarend lekérése: {start} .. {end} ...")
    client = client_factory(student) if client_factory else kreta_api_sync.client_for(student)
    rows = kreta_api_sync.fetch_lessons(client, start, end)
    consultations = kreta_api_sync.fetch_consultations(client, start, end)
    saved = save_orarend_to_db(diak_nev, rows + consultations)
    _raise_if_blocked(saved, "órarend")
    log(f"  [ÓRAREND OK] {len(rows)} db órarendi elem + {len(consultations)} fogadóóra az API-ból.")


def api_provider_uzenetek(student, client_factory=None):
    """Beérkezett üzenetek + csatolmányok frissítése az API-ból (csak az újakat).

    A csatolmányok tartalma is API-ból jön (2026-10-31 óta):

    1. `dokumentumok/uzenetek/{csatolmanyAzonosito}` → 302 a
       `files.e-kreta.hu/fajlok/?nonce=...` címre, onnan a fájl bájtjai;
    2. a fájl a `CSATOLMANYOK_DIR/<diák>/` alá kerül, a DB-be a könyvtárhoz
       viszonyított relatív út megy (mint a webes útnál).

    Ha egy letöltés elhal: örökölt `api_first` módban az adatkör hibának számít
    (nincs félkész mentés); `api` módban a fájl nélkül mentjük az üzenetet,
    és a csatolmány-pótlás a következő futásokon újrapróbál (max. 3 próba).
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

    # A lista csak előnézetet ad (rövid, sortörések nélkül): az ÚJ üzenetekhez
    # lekérjük a részletes törzset, és a hosszabb szöveget mentjük (Kaneo #74).
    for m in new_messages:
        teljes = kreta_api_sync.fetch_message_body(client, m.get("posta_id"))
        if len(teljes) > len(m.get("szoveg") or ""):
            m["szoveg"] = teljes

    # #74: a már mentett üzenetekhez utólag rögzítjük a postalada-elem azonosítóját
    # (feladó + tárgy + időpont egyezéssel a listából), hogy a teljes törzs lekérhető legyen.
    lista_index = {(m["felado"], m["targy"], m["idopont"]): m.get("posta_id")
                   for m in messages}
    for sor in uzenet_hianyzo_posta_idk(diak_nev):
        posta = lista_index.get((sor["felado"], sor["targy"], sor["idopont"]))
        if posta:
            uzenet_posta_id_mentes(sor["id"], posta)

    # A korábban mentett, előnézet-szövegű üzenetek utólag feltöltése (Kaneo #74).
    feltoltott = 0
    for row in uzenet_rovid_szoveguak(diak_nev):
        teljes = kreta_api_sync.fetch_message_body(client, row["posta_id"])
        if len(teljes) > (row["len"] or 0):
            update_uzenet_szoveg(row["id"], teljes)
            feltoltott += 1
    if feltoltott:
        log(f"    [Üzenetek] {feltoltott} korábbi üzenet szövege feltöltve (teljes törzs).")

    # A csatolmányokat ELŐBB töltjük le, hogy hiba esetén még semmi ne kerüljön
    # a DB-be (így nincs félkész mentés; a pótlás később megpróbálja újra).
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
            csatolmany_nev, csatolmany_utvonal = _ment_csatolmanyok(diak_nev, files)
        elif expected_names.get(m["uzenet_id"]):
            # a fájl nem jött le (csak api módban jutunk ide): a nevet mentjük,
            # az útvonal üres marad — a felület így is látja, hogy volt csatolmány
            csatolmany_nev = expected_names[m["uzenet_id"]][0]
        save_uzenet_to_db(diak_nev, m["felado"], m["targy"], m["idopont"], m["szoveg"],
                          csatolmany_nev, csatolmany_utvonal, m.get("posta_id") or "",
                          olvasott=1 if m.get("olvasott") else 0)
        uj += 1

    # `api` módban a letöltési hiba miatt fájl nélkül mentett üzenetek pótlása
    # a következő futásokon (max. 3 próba), hogy ne legyen végleges adatrés.
    _csatolmany_potlas(diak_nev, client)

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


def _ment_csatolmanyok(diak_nev, files):
    """A letöltött csatolmányok kiírása a data kötetre; `(név, relatív út)`."""
    target_dir = os.path.join(CSATOLMANYOK_DIR, diak_nev.replace(" ", "_"))
    os.makedirs(target_dir, exist_ok=True)
    saved = []
    for fajlnev, content in files:
        save_path = _unique_path(os.path.join(target_dir, fajlnev))
        with open(save_path, "wb") as handle:
            handle.write(content)
        saved.append(save_path)
    if len(saved) > 1:
        log(f"    [INFO] {len(saved)} csatolmány (a felület az elsőt linkeli): "
            + ", ".join(os.path.basename(p) for p in saved))
    return (os.path.basename(saved[0]),
            os.path.relpath(saved[0], CSATOLMANYOK_DIR).replace("\\", "/"))


def _csatolmany_potlas(diak_nev, client, limit=5):
    """Fájl nélkül mentett üzenetek csatolmányának pótlása (api mód).

    A részletes üzenet-válaszból vesszük a csatolmány-azonosítókat, letöltjük,
    majd a sor `csatolmany_utvonal` mezőjét frissítjük. Sikertelen próbánál a
    `csatolmany_proba` nő; 3 után nem próbálkozik tovább (nincs végtelen kör).
    """
    rows = uzenet_hianyzo_csatolmanyok(diak_nev, limit=limit)
    if not rows:
        return
    potolt = 0
    for row in rows:
        try:
            detail = client.fetch_message_detail(row["posta_id"])
            files = []
            for attachment in kreta_api.attachments_from_detail(detail):
                attachment_id = attachment.get("azonosito")
                if not attachment_id:
                    continue
                fajlnev = kreta_api.safe_fajlnev(
                    attachment.get("fajlNev") or f"csatolmany_{attachment_id}")
                content, _content_type = kreta_api_sync.fetch_attachment(
                    client, attachment_id)
                files.append((fajlnev, content))
            if not files:
                # nincs (már) csatolmány a részletes válaszban: ne pörögjön örökre
                uzenet_csatolmany_proba_novel(row["id"])
                continue
            nev, utvonal = _ment_csatolmanyok(diak_nev, files)
            update_uzenet_csatolmany(row["id"], nev, utvonal)
            potolt += 1
            log(f"    [CSATOLMÁNY PÓTLÁS] {row['csatolmany_nev']} -> {utvonal}")
        except Exception as exc:  # noqa: BLE001 — hálózat/parse/méret bármi
            uzenet_csatolmany_proba_novel(row["id"])
            log(f"    [FIGYELEM] csatolmány-pótlás nem sikerült "
                f"({row['csatolmany_nev']}): {kreta_sync.describe_error(exc)}")
    if potolt:
        log(f"    [Üzenetek] {potolt} korábbi csatolmány pótolva.")


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

# A teljes cserés mentés védelmi küszöbe: ha az új sorok száma a meglévők ennyi
# aránya alá esik, nem törlünk (üres, de 200-as API-válasz ne okozzon adatvesztést).
DEFAULT_SYNC_MIN_RATIO = 0.5


def sync_min_ratio() -> float:
    """A védelmi küszöb (env: `KRETA_SYNC_MIN_RATIO`, alap 0,5; 0 = kikapcsolva)."""
    raw = os.environ.get("KRETA_SYNC_MIN_RATIO", "")
    try:
        value = float(raw) if str(raw).strip() else DEFAULT_SYNC_MIN_RATIO
    except (TypeError, ValueError):
        return DEFAULT_SYNC_MIN_RATIO
    return min(max(value, 0.0), 1.0)


def _would_drop_too_much(old_count: int, new_count: int) -> bool:
    """Igaz, ha a teljes csere a meglévő sorok túl nagy részét törölné."""
    if old_count <= 0:
        return False
    return new_count < old_count * sync_min_ratio()


def _raise_if_blocked(result: dict, label: str) -> None:
    """Ha a mentés adatvédelem miatt kimaradt, hibát dob (az adatkör hibás).

    Így az adatkör részleges hibának számít (riasztás jár vele), de a meglévő
    adatok megmaradnak — a védőkorlát a teljes cserés törlést akadályozta meg.
    """
    blocked = (result or {}).get("blocked") or {}
    if not blocked:
        return
    detail = ", ".join(
        f"{tipus}: {data.get('old')} → {data.get('new')}" for tipus, data in blocked.items()
    )
    raise RuntimeError(f"{label}: a teljes cserét adatvédelem miatt kihagytam ({detail})")


def _insert_esemeny(cursor, diak_nev, e, completed_set, existing_hazi, existing_szamonkeres,
                    first_seen_map=None):
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

    # A saját DB-be kerülés időpontja (#147): ismételt teljes cserénél a korábbi
    # érték megmarad, új sornál mostani időpont.
    first_seen = (first_seen_map or {}).get(_event_key_from_mapping(e))
    if not first_seen:
        first_seen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute('''
        INSERT INTO esemenyek 
        (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek, suly_szazalek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz, tanev, tanev_forras, letrehozva)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        diak_nev, 
        es_tipus,
        e.get('tantargy', ''),
        e.get('ertek', ''),
        e.get('szam_ertek', 0),
        e.get('suly_szazalek', 0),
        e.get('bej_datum', ''),
        e.get('hatarido', ''),
        e.get('ertekelo', ''),
        e.get('tipus', ''),
        e.get('mod', ''),
        e.get('tema', ''),
        e.get('cim', ''),
        e.get('tartalom', ''),
        kesz_val,
        kreta_tanev.row_tanev("esemenyek", e),
        kreta_tanev.TANEV_FORRAS_SZAMITOTT,
        first_seen,
    ))
    return True


def _event_tanev(row) -> str:
    """Egy mentendő esemény tanéve (a rekord dátumából; a házinál a határidő dönt)."""
    return kreta_tanev.row_tanev("esemenyek", row)


def _deletable_years(years, window) -> set:
    """Azon tanévek, amelyekre a teljes csere (törlés) engedett (Kaneo #40)."""
    out = set()
    for year in years:
        if not year:
            continue
        if window is None:
            out.add(year)
        elif kreta_tanev.teljesen_lekert(year, window[0], window[1]):
            out.add(year)
    return out


def _in_window(value, window) -> bool:
    """A dátum beleesik-e a lekérési ablakba (window=None: igen)."""
    if window is None:
        return True
    datum = kreta_tanev.parse_date(value)
    start = kreta_tanev.parse_date(window[0])
    end = kreta_tanev.parse_date(window[1])
    if datum is None or start is None or end is None:
        return False
    return start <= datum <= end


def _deletable_ids(pairs, deletable_years, window) -> list:
    """`[(id, dátum)]` -> a törölhető id-k (tanév a scope-ban és dátum az ablakban)."""
    ids = []
    for rid, datum in pairs:
        year = kreta_tanev.tanev_of(datum)
        if year and year in deletable_years and _in_window(datum, window):
            ids.append(rid)
    return ids


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


def save_esemenyek_by_type(diak_nev, esemenyek, completed_set, tipusok, window=None):
    """Típusonkénti mentés: az API-ból már frissült típusokat ki lehet hagyni.

    - `Értékelés` / `Feljegyzés`: teljes csere (a KRÉTA-ból eltűnt sor törlődik);
    - `Házi feladat` / `Bejelentett számonkérés`: inkrementális, a korábbi
      `kesz` jelölés és a duplikátumvédelem megmarad.

    Csak a `tipusok` listában szereplő sorok íródnak ki — így a hívó pontosan
    szabályozza, mely típusok cserélődnek az adott mentésben.

    **Adatvédelem:** ha egy teljes cserés típusnál az új sorok száma a meglévők
    `KRETA_SYNC_MIN_RATIO` (alap 0,5) aránya alá esik, a törlést kihagyjuk, és a
    visszatérési érték jelzi (`blocked`). Így egy üres, de 200-as API-válasz nem
    törli a meglévő jegyeket/feljegyzéseket.

    Visszaad: `{"saved": int, "blocked": {típus: {"old", "new"}}, "per_type": {...}}`.
    """
    tipusok = tuple(tipusok)
    result = {"saved": 0, "blocked": {}, "per_type": {}, "error": ""}
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        rows_by_type = {}
        for e in esemenyek:
            tipus = e.get('esemeny_tipus')
            if tipus in tipusok:
                rows_by_type.setdefault(tipus, []).append(e)
        result["per_type"] = {tipus: len(rows) for tipus, rows in rows_by_type.items()}

        existing_hazi = get_existing_hazi_keys(diak_nev) if 'Házi feladat' in tipusok else set()
        existing_szamonkeres = (
            get_existing_szamonkeres_keys(diak_nev)
            if 'Bejelentett számonkérés' in tipusok else set()
        )
        # A teljes cserénél is őrizzük meg a „mikor került be” időpontot (#147).
        first_seen_map = {}
        for tipus in tipusok:
            if tipus in VOLATILE_EVENT_TYPES:
                first_seen_map.update(get_event_first_seen_map(diak_nev, tipus))

        for tipus in tipusok:
            rows = rows_by_type.get(tipus, [])
            deletable = set()
            skipped = 0
            if tipus in VOLATILE_EVENT_TYPES:
                # Tanév-scope (Kaneo #40): csak a batch tanévei, teljes ablakkal.
                batch_years = {_event_tanev(e) for e in rows} - {""}
                deletable = _deletable_years(batch_years, window)
                pairs = cursor.execute(
                    "SELECT id, bej_datum FROM esemenyek"
                    " WHERE diak_nev = ? AND esemeny_tipus = ?",
                    (diak_nev, tipus),
                ).fetchall()
                if not rows and pairs:
                    # Üres batch: soha nem törlünk (Kaneo #40), de jelezzük a hívónak,
                    # hogy ez fallbacket érdemelhet (api_first).
                    result["blocked"][tipus] = {"old": len(pairs), "new": 0}
                    log(f"  [FIGYELEM] {tipus}: üres lista a meglévő {len(pairs)} sor "
                        f"helyett — a teljes cserét kihagytam (adatvédelem).")
                    continue
                del_ids = _deletable_ids(pairs, deletable, window)
                new_count = sum(1 for e in rows if _event_tanev(e) in deletable)
                if del_ids and _would_drop_too_much(len(del_ids), new_count):
                    result["blocked"][tipus] = {"old": len(del_ids), "new": new_count}
                    log(f"  [FIGYELEM] {tipus}: {new_count} új sor a meglévő "
                        f"{len(del_ids)} helyett — a teljes cserét kihagytam "
                        f"(adatvédelem, küszöb: {sync_min_ratio():.2f}).")
                    continue
                for rid in del_ids:
                    cursor.execute("DELETE FROM esemenyek WHERE id = ?", (rid,))
            for e in rows:
                if tipus in VOLATILE_EVENT_TYPES and _event_tanev(e) not in deletable:
                    skipped += 1
                    continue  # nem törölt tanév: nem is írjuk (duplikáció ellen)
                if _insert_esemeny(cursor, diak_nev, e, completed_set,
                                   existing_hazi, existing_szamonkeres,
                                   first_seen_map=first_seen_map):
                    result["saved"] += 1
            if skipped:
                result.setdefault("skipped", {})[tipus] = skipped
                log(f"  [FIGYELEM] {tipus}: {skipped} sor a letöltött tanéveken "
                    f"kívülre esett (pl. korábbi tanév) — kihagytam, hogy ne "
                    f"duplikálódjon.")
        conn.commit()
    except Exception as ex:
        result["error"] = str(ex)
        log(f"  [Hiba az események mentésekor]: {ex}")
    finally:
        conn.close()
    return result

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


def uzenet_rovid_szoveguak(diak_nev, max_len=200, limit=20):
    """A mentett, de rövid (valószínűleg előnézet) szövegű üzenetek.

    Csak olyan sorok jöhetnek szóba, amelyekben van `posta_id` — e nélkül nem
    lehet kikérni a részletes törzset. (Kaneo #74)
    """
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT id, posta_id, length(szoveg) AS len FROM uzenetek "
            "WHERE diak_nev = ? AND posta_id IS NOT NULL AND posta_id != '' "
            "AND length(szoveg) < ? ORDER BY id DESC LIMIT ?",
            (diak_nev, max_len, limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def uzenet_hianyzo_posta_idk(diak_nev, limit=25):
    """A mentett üzenetek, amelyekhez még nem rögzült a postalada-elem azonosító."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT id, felado, targy, idopont FROM uzenetek "
            "WHERE diak_nev = ? AND (posta_id IS NULL OR posta_id = '') "
            "ORDER BY id DESC LIMIT ?", (diak_nev, limit)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def uzenet_posta_id_mentes(row_id, posta_id):
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute("UPDATE uzenetek SET posta_id = ? WHERE id = ?", (posta_id, row_id))
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def update_uzenet_szoveg(row_id, szoveg):
    """A teljes szövegre cseréli a mentett előnézetet (Kaneo #74)."""
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute("UPDATE uzenetek SET szoveg = ? WHERE id = ?", (szoveg, row_id))
        conn.commit()
    finally:
        conn.close()


def uzenet_hianyzo_csatolmanyok(diak_nev, limit=5):
    """A mentett üzenetek, amelyekhez a csatolmány neve megvan, de a fájl nem.

    `api` módban a letöltési hiba nem állítja meg az üzenet mentését: a sor a
    fájl nélkül (üres `csatolmany_utvonal`) kerül a DB-be. Ezeket a következő
    futások pótolják (max. 3 próbáig), hogy ne legyen végleges adatrés.
    """
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT id, posta_id, csatolmany_nev FROM uzenetek "
            "WHERE diak_nev = ? AND csatolmany_nev IS NOT NULL AND csatolmany_nev != '' "
            "AND (csatolmany_utvonal IS NULL OR csatolmany_utvonal = '') "
            "AND posta_id IS NOT NULL AND posta_id != '' "
            "AND COALESCE(csatolmany_proba, 0) < 3 "
            "ORDER BY id DESC LIMIT ?", (diak_nev, limit)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def update_uzenet_csatolmany(row_id, csatolmany_nev, csatolmany_utvonal):
    """A pótolt csatolmány útjának mentése; a próbaszámláló nullázódik."""
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute(
            "UPDATE uzenetek SET csatolmany_nev = ?, csatolmany_utvonal = ?, "
            "csatolmany_proba = 0 WHERE id = ?",
            (csatolmany_nev, csatolmany_utvonal, row_id))
        conn.commit()
    finally:
        conn.close()


def uzenet_csatolmany_proba_novel(row_id):
    """Sikertelen csatolmány-pótlás: a próbaszámláló növelése (max. 3)."""
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute(
            "UPDATE uzenetek SET csatolmany_proba = COALESCE(csatolmany_proba, 0) + 1 "
            "WHERE id = ?", (row_id,))
        conn.commit()
    finally:
        conn.close()


def save_uzenet_to_db(diak_nev, felado, targy, idopont, szoveg, csatolmany_nev="",
                      csatolmany_utvonal="", posta_id="", olvasott=0):
    """Menti a beolvasott új üzenetet az adatbázisba."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        tanev = kreta_tanev.tanev_of(idopont)
        cursor.execute('''
            INSERT INTO uzenetek 
            (diak_nev, felado, targy, idopont, szoveg, csatolmany_nev, csatolmany_utvonal,
             posta_id, olvasott, tanev, tanev_forras, letrehozva)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (diak_nev, felado, targy, idopont, szoveg, csatolmany_nev, csatolmany_utvonal,
              posta_id, 1 if olvasott else 0, tanev, kreta_tanev.TANEV_FORRAS_SZAMITOTT,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    except Exception as ex:
        log(f"      [Hiba az üzenet mentésekor]: {ex}")
    finally:
        conn.close()

# ==============================================================================
# === ÓRAREND KINYERÉSI BLOKK (AKTUÁLIS ÉS KÖVETKEZŐ HÉT) ===
# ==============================================================================
def save_orarend_to_db(diak_nev, orarend_lista):
    """Elmenti a diák órarendi adatait; a **múltbeli** sorokat nem törli (Kaneo #122).

    A frissítés csak a most lekért időablakra érvényes: a lista legkorábbi
    dátumától kezdődő sorok cserélődnek, a korábbi (múltbeli) órarend megmarad.
    **Adatvédelem:** ha üres lista érkezik, de a diákhoz már van órarend, a
    törlést kihagyjuk (egy elhalt API/web-lista ne ürítse ki a naptárt).

    Visszaad: `{"saved": int, "blocked": {"orarend": {"old", "new"}}}`.
    """
    result = {"saved": 0, "blocked": {}}
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    def to_str(val):
        if val is None:
            return ""
        if isinstance(val, dict):
            return str(val.get('_i') or val.get('d') or str(val))
        return str(val).strip()

    old_count = cursor.execute(
        "SELECT COUNT(*) FROM orarend WHERE diak_nev = ?", (diak_nev,)
    ).fetchone()[0]
    if old_count > 0 and not orarend_lista:
        result["blocked"]["orarend"] = {"old": old_count, "new": 0}
        log(f"  [FIGYELEM] Órarend: üres lista érkezett a meglévő {old_count} sor helyett "
            f"— a törlést kihagytam (adatvédelem).")
        conn.close()
        return result

    # Csak az új ablak kezdetétől törlünk; a korábbi hetek megmaradnak.
    kezdo_datumok = []
    for ora in orarend_lista:
        kezdo = to_str(ora.get('start') or ora.get('Kezdet'))
        if len(kezdo) >= 10:
            kezdo_datumok.append(kezdo[:10])
    if kezdo_datumok:
        ablak_kezdo = min(kezdo_datumok)
        old_window = cursor.execute(
            "SELECT COUNT(*) FROM orarend WHERE diak_nev = ?"
            " AND substr(kezdo_idopont, 1, 10) >= ?", (diak_nev, ablak_kezdo)
        ).fetchone()[0]
        if old_window > 0 and _would_drop_too_much(old_window, len(orarend_lista)):
            result["blocked"]["orarend"] = {"old": old_window, "new": len(orarend_lista)}
            log(f"  [FIGYELEM] Órarend: {len(orarend_lista)} új sor a meglévő "
                f"{old_window} helyett az ablakban — a cserét kihagytam "
                f"(adatvédelem, küszöb: {sync_min_ratio():.2f}).")
            conn.close()
            return result
        cursor.execute(
            "DELETE FROM orarend WHERE diak_nev = ? AND substr(kezdo_idopont, 1, 10) >= ?",
            (diak_nev, ablak_kezdo))
    else:
        # Nincs értelmezhető dátum — a biztonság kedvéért nem törlünk.
        pass

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
    result["saved"] = len(orarend_lista)
    return result

SYNC_SOURCES = {}


def _finalize_student_counts(diak_nev, before_event_keys):
    """Az új események/számlálók lezárása a diák futásának végén."""
    NEW_EVENT_COUNTS[diak_nev] = diff_event_counts(before_event_keys, get_event_key_set(diak_nev))
    NEW_HIANYZAS_COUNTS.setdefault(diak_nev, {})
    NEW_MESSAGE_COUNTS.setdefault(diak_nev, 0)


async def run_student(student, tracker):
    """Egy diák szinkronja — kizárólag a mobil API-ból (Kaneo #64).

    A böngészős (Playwright) út a v2.5.0-ban kikerült. Ha egy adatkör hibázik,
    az részleges hiba: a többi adatkör és diák frissül, a futás riasztást kap.
    """
    diak_nev = student.get("diak_nev", "Ismeretlen")

    # Az "előtte" állapotot a lekérés ELŐTT kell rögzíteni.
    before_events = get_event_key_set(diak_nev)

    if kreta_sync.needs_api(SYNC_MODE):
        await kreta_sync.run_api_datasets(student, API_PROVIDERS, tracker, log)

    _finalize_student_counts(diak_nev, before_events)
    failures = tracker.failures()
    if failures:
        raise RuntimeError(
            "API-ból nem frissült: " + ", ".join(
                f"{kreta_sync.LABELS.get(key, key)} ({reason})"
                for key, reason in failures.items()))


async def run_students(active_students):
    """A diákon végigmenő ciklus; az egyik diák hibája nem állítja meg a többit."""
    failed = []
    ok_count = 0
    for student in active_students:
        diak_nev = student.get("diak_nev", "Ismeretlen")
        tracker = kreta_sync.SourceTracker(diak_nev)
        try:
            await run_student(student, tracker)
            ok_count += 1
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
    log(f"Szinkron mód: {SYNC_MODE} (Kréta mobil API, böngésző nélkül)")
    log(f"Globális üzenet-szinkronizálás: {'BE' if GLOBAL_SCRAPE_MESSAGES else 'KI'}")

    ok_count, failed = await run_students(active_students)

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
    }
    print(RESULT_MARKER + json.dumps(summary, ensure_ascii=False), flush=True)

    # Kilépési kód: 0 = minden diák rendben, 2 = részleges hiba, 1 = végzetes.
    return 0 if not failed else 2

if __name__ == "__main__":
    # `--init-db`: csak a sémát hozza létre (a Flask app ezt hívja, ha a DB
    # fájl hiányzik vagy üres), böngésző és belépés nélkül.
    if INIT_DB_ONLY:
        init_db()
        print("Séma kész (init-db).")
        sys.exit(0)
    sys.exit(asyncio.run(main()))