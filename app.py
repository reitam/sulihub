from flask import Flask, render_template, request, jsonify, send_from_directory, make_response
import sqlite3
import os
import sys
import subprocess
import json
import threading
import re
import io
import hashlib
import socket
import time
import urllib.request
from datetime import datetime, timedelta
import kreta_tanev
import kreta_api

# ReportLab importok a PDF generáláshoz
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

app = Flask(__name__)

# ── Útvonalak ────────────────────────────────────────────────────────────────
# Alapból minden az aktuális könyvtárban él (lokális Windows-futtatás, változatlan
# viselkedés). Dockerben a KRETA_DATA_DIR=/app/data (bind mount) — így az adatbázis,
# a config.json, a sync.log és a csatolmányok a HDD-s adatköteten maradnak.
DATA_DIR = os.environ.get("KRETA_DATA_DIR", ".")
DB_FILE = os.environ.get("KRETA_DB_FILE", os.path.join(DATA_DIR, "kreta_adatok.db"))
CONFIG_FILE = os.environ.get("KRETA_CONFIG_FILE", os.path.join(DATA_DIR, "config.json"))
LOG_FILE = os.environ.get("KRETA_LOG_FILE", os.path.join(DATA_DIR, "sync.log"))
LOG_MAX_BYTES = int(os.environ.get("KRETA_LOG_MAX_BYTES", 1000000))
LOG_BACKUP_COUNT = int(os.environ.get("KRETA_LOG_BACKUP_COUNT", 2))
# Az /api/logs ennyi bájtot ad vissza a napló végéről (a UI-nak elég).
LOG_API_MAX_BYTES = int(os.environ.get("KRETA_LOG_API_MAX_BYTES", 300000))
CSATOLMANYOK_DIR = os.environ.get("KRETA_CSATOLMANYOK_DIR", os.path.join("static", "csatolmanyok"))
# Az ütemező állapota (legutóbbi futás, eredmény) — a data köteten él, hogy
# konténer-újraindítás/deploy után is megmaradjon a 3 órás ciklus.
SCHEDULER_STATE_FILE = os.environ.get(
    "KRETA_SCHEDULER_STATE_FILE", os.path.join(DATA_DIR, "scheduler_state.json")
)
# A deploy által a data kötetre írt verziószám (a felületen jelenik meg).
VERSION_FILE = os.environ.get("KRETA_VERSION_FILE", os.path.join(DATA_DIR, "version.txt"))

# A scraper ezzel a jelölővel küldi a gép-olvasható összegzést a kimenetén:
# ##KRETA_RESULT##{"total":3,"ok":2,"failed":["Név"]}
RESULT_MARKER = "##KRETA_RESULT##"

# WAL: csak opt-in, lásd enable_wal() — a data kötet FUSE mount.
SQLITE_WAL = os.environ.get("KRETA_SQLITE_WAL", "0").strip().lower() in ("1", "true", "yes", "on")

sync_state = {
    "running": False,
    "process": None,
    "logs": [],
    "status": "idle",
    "trigger": None,
    "failed_students": [],
    "ok_count": None,
    "total_students": None,
    "new_events": {},
    "new_messages": {},
    "new_hianyzasok": {},
    "sources": {}
}
sync_lock = threading.Lock()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    ensure_db_schema(conn)
    return conn


# A scraper hozza létre ezeket (`kreta_playwright.init_db`); a Flask csak a
# saját kiegészítőit (lásd APP_OWN_TABLES). Ha a DB fájlt kézzel áthelyezik/
# törlik, eddig üres fájl keletkezett, amiben nem volt `esemenyek`/`uzenetek`
# → minden oldal 500-as hibát adott. Ezért a hiányzó sémát itt pótoljuk.
SCRAPER_TABLES = ("esemenyek", "uzenetek", "orarend", "hianyzasok", "igazolasok")
APP_OWN_TABLES = ("kifizetesek", "sync_runs", "app_meta", "kommentek")
CORE_TABLES = SCRAPER_TABLES + APP_OWN_TABLES
APP_DIR = os.path.dirname(os.path.abspath(__file__))
_schema_lock = threading.Lock()
_schema_bootstrapping = False
_schema_failed = False


def _missing_tables(conn, tables):
    names = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    return [table for table in tables if table not in names]


def ensure_db_schema(conn=None, reason=""):
    """Teljes séma megléte; hiány esetén létrehozza (egy helyen, a scraperben).

    A scraper-táblák DDL-je a `kreta_playwright.init_db`-ben él, ezért a Flask
    nem duplikálja: külön processzben hívja meg `--init-db`-vel (böngésző
    nélkül, ~1 s). Utána a saját tábláit (kifizetesek, sync_runs, app_meta) az
    `init_db_extensions` hozza létre. Visszaad: True, ha most bootstrappelt.
    """
    global _schema_bootstrapping, _schema_failed
    own = conn is None
    if own:
        try:
            conn = sqlite3.connect(DB_FILE)
        except sqlite3.Error as exc:
            # Bizonytalan állapot (pl. elérhetetlen útvonal): ne bootstrapoljunk.
            print(f"[Adatbázis] Az adatbázis nem nyitható meg ({exc}) — séma-ellenőrzés kihagyva.")
            return False
    try:
        missing = _missing_tables(conn, SCRAPER_TABLES)
    except sqlite3.Error as exc:
        # Pl. zárolt adatbázis: NEM tudjuk, hogy hiányzik-e a séma → ne indítsunk
        # init-db subprocesszt, és ne kapcsoljuk ki véglegesen az önjavítást.
        print(f"[Adatbázis] A séma ellenőrzése nem sikerült ({exc}) — nem bootstrapolok.")
        return False
    finally:
        if own:
            conn.close()
    if not missing or _schema_bootstrapping or _schema_failed:
        return False

    with _schema_lock:
        check = sqlite3.connect(DB_FILE)
        try:
            missing = _missing_tables(check, SCRAPER_TABLES)
        except sqlite3.Error as exc:
            print(f"[Adatbázis] A séma újraellenőrzése nem sikerült ({exc}) — nem bootstrapolok.")
            return False
        finally:
            check.close()
        if not missing or _schema_bootstrapping:
            return False
        suffix = f" ({reason})" if reason else ""
        print(f"[Adatbázis] Hiányzó táblák: {', '.join(missing)}{suffix} — séma létrehozása...")
        env = os.environ.copy()
        env["KRETA_DATA_DIR"] = DATA_DIR
        env["KRETA_DB_FILE"] = DB_FILE
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        _schema_bootstrapping = True
        try:
            result = subprocess.run(
                [sys.executable, os.path.join(APP_DIR, "kreta_playwright.py"), "--init-db"],
                cwd=APP_DIR, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120)
        except Exception as exc:  # noqa: BLE001 — a bootstrap hibája ne borítsa a kérést
            _schema_failed = True
            print(f"[Adatbázis] A séma létrehozása nem sikerült: {exc}")
            return False
        finally:
            _schema_bootstrapping = False
        if result.returncode != 0:
            _schema_failed = True
            detail = (result.stderr or result.stdout or "").strip()[-300:]
            print(f"[Adatbázis] init-db hiba (exit {result.returncode}): {detail}")
            return False
        print("[Adatbázis] Séma létrehozva — üres adatbázis, az első szinkron tölti fel.")

    # A saját táblák (a függvény a fájlban később van definiálva).
    initializer = globals().get("init_db_extensions")
    if callable(initializer):
        initializer()
    return True

# ==============================================================================
# === FUTÁS-NAPLÓ (sync_runs) ÉS ALKALMAZÁS-META (app_meta) =====================
# ==============================================================================
# Korábban a "legutóbbi futás" egy scheduler_state.json fájlban élt (olvasd-
# módosítsd-írd vissza, felülírással). Mostantól minden futás egy sor a DB-ben:
# van történet, tranzakció-védelem, és a mentés is DB-szintű.
SYNC_RUNNING_STATUS = "running"


def ensure_run_tables(conn):
    """Létrehozza a futás-napló és meta táblákat (idempotens)."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger         TEXT NOT NULL,
            started_at      TEXT NOT NULL,
            finished_at     TEXT,
            status          TEXT NOT NULL DEFAULT 'running',
            ok_count        INTEGER,
            total_count     INTEGER,
            failed_students TEXT,
            new_events      TEXT,
            new_messages    TEXT,
            new_hianyzasok  TEXT,
            sources         TEXT,
            duration_sec    REAL,
            tanev           TEXT,
            tanev_zaro      TEXT
        )
    """)
    # Meglévő adatbázis: a hiányzás-összegzés oszlopa utólag is bekerül.
    cur.execute("PRAGMA table_info(sync_runs)")
    run_cols = [row[1] for row in cur.fetchall()]
    if "new_hianyzasok" not in run_cols:
        cur.execute("ALTER TABLE sync_runs ADD COLUMN new_hianyzasok TEXT")
    if "sources" not in run_cols:
        # Adatkörönkénti forrás (API / Playwright) és a fallback oka.
        cur.execute("ALTER TABLE sync_runs ADD COLUMN sources TEXT")
    if "tanev" not in run_cols:
        # A tanév-oszlop a kreta_tanev migrációban is létrejön — itt csak biztosítjuk.
        cur.execute("ALTER TABLE sync_runs ADD COLUMN tanev TEXT")
    if "tanev_zaro" not in run_cols:
        # Tanévzáró futás cél-tanéve (Kaneo #52); normál futásnál NULL.
        cur.execute("ALTER TABLE sync_runs ADD COLUMN tanev_zaro TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sync_runs_started ON sync_runs(started_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sync_runs_trigger ON sync_runs(trigger, started_at)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_meta (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at TEXT
        )
    """)
    # Saját megjegyzések (Kaneo #46): eseményhez/üzenethez, stabil tartalom-kulccsal.
    # Az események a szinkronnál újraíródnak (az id változik), ezért kulcs nem az id.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kommentek (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            cel_tipus  TEXT NOT NULL,
            cel_kulcs  TEXT NOT NULL,
            diak_nev   TEXT,
            szoveg     TEXT NOT NULL,
            szerzo     TEXT,
            letrehozva TEXT NOT NULL,
            modositva  TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_kommentek_cel "
                "ON kommentek(cel_tipus, cel_kulcs)")
    conn.commit()


# ── Saját megjegyzések (Kaneo #46) ──────────────────────────────────────────
KOMMENT_CEL_TIPUSOK = ("esemeny", "uzenet")
KOMMENT_MAX_HOSSZ = 2000

_ESEMENY_KULCS_MEZOK = ("diak_nev", "esemeny_tipus", "tantargy", "bej_datum", "hatarido",
                        "ertek", "szam_ertek", "tema", "cim", "tartalom")
_UZENET_KULCS_MEZOK = ("diak_nev", "felado", "targy", "idopont")


def _komment_hash(prefix, parts):
    text = "|".join("" if p is None else str(p) for p in parts)
    return prefix + hashlib.sha1(text.encode("utf-8")).hexdigest()[:24]


def komment_kulcs_esemeny(row):
    """Egy esemény stabil tartalom-kulcsa (a szinkron újraírja az id-ket)."""
    keys = row.keys()
    return _komment_hash("e:", [row[k] if k in keys else "" for k in _ESEMENY_KULCS_MEZOK])


def komment_kulcs_uzenet(row):
    """Egy üzenet stabil kulcsa: a KRÉTA `uzenet_id`, ha nincs, a tartalom."""
    keys = row.keys()
    uid = str(row["uzenet_id"] or "").strip() if "uzenet_id" in keys else ""
    if uid:
        return "m:" + uid
    return _komment_hash("m:", [row[k] if k in keys else "" for k in _UZENET_KULCS_MEZOK])


def komment_szamok(cursor, cel_tipus):
    """`{cel_kulcs: darab}` az adott cél-típusra (hiányzó táblánál üres)."""
    try:
        rows = cursor.execute(
            "SELECT cel_kulcs, COUNT(*) FROM kommentek WHERE cel_tipus = ? GROUP BY cel_kulcs",
            (cel_tipus,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {row[0]: row[1] for row in rows}


def enable_wal(conn):
    """
    A WAL mód CSAK opt-in (KRETA_SQLITE_WAL=1).

    A data kötet a szerveren ntfs-3g (FUSE) mount — a SQLite hivatalosan sem
    ajánlja a WAL-t ilyen fájlrendszeren (locking/mmap), és a csak-olvasható
    megnyitások (pl. az entrypoint DB-guardja) is elhasalhatnak tőle.
    Alapból ezért a bevált rollback journal marad; ha a DB-t korábban WAL-ra
    állítottuk, itt visszaállítjuk.
    """
    try:
        if SQLITE_WAL:
            conn.execute("PRAGMA journal_mode=WAL")
        else:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            if str(mode).lower() == "wal":
                conn.execute("PRAGMA journal_mode=delete")
    except sqlite3.Error as e:
        print(f"[DB] journal_mode beállítás nem sikerült: {e}")


def check_db_integrity(conn):
    """Induláskori gyors integritás-ellenőrzés (csak naplóz, nem blokkol)."""
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()[0]
        if str(result).lower() != "ok":
            print(f"[DB] FIGYELEM: az adatbázis integritás-ellenőrzése hibát jelzett: {result}")
    except sqlite3.Error as e:
        print(f"[DB] Integritás-ellenőrzés nem futott le: {e}")


def migrate_state_file(conn):
    """
    Egyszeri átvétel: ha még nincs futás a DB-ben, de van régi
    scheduler_state.json, abból létrehozunk egy lezárt sort.
    """
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sync_runs")
        if cur.fetchone()[0] > 0:
            return
        if not os.path.exists(SCHEDULER_STATE_FILE):
            return
        with open(SCHEDULER_STATE_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)
        if not isinstance(old, dict) or not old.get("last_run_started"):
            return
        cur.execute("""
            INSERT INTO sync_runs (trigger, started_at, finished_at, status,
                                   ok_count, total_count, failed_students)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            old.get("last_trigger") or "manual",
            old.get("last_run_started"),
            old.get("last_run_finished"),
            old.get("last_status") or "done",
            old.get("last_ok"),
            old.get("last_total"),
            json.dumps(old.get("last_failed_students") or [], ensure_ascii=False),
        ))
        if old.get("last_stale_alert"):
            cur.execute(
                "INSERT OR REPLACE INTO app_meta (key, value, updated_at) VALUES (?, ?, ?)",
                ("last_stale_alert", old.get("last_stale_alert"), _now_iso()),
            )
        conn.commit()
        # a régi fájlt nem töröljük, csak elnevezzük — így visszakereshető
        try:
            os.replace(SCHEDULER_STATE_FILE, SCHEDULER_STATE_FILE + ".migrated")
        except OSError:
            pass
        print(f"[Futásnapló] A régi {SCHEDULER_STATE_FILE} átemelve a DB-be.")
    except (sqlite3.Error, ValueError, OSError) as e:
        print(f"[Futásnapló] Migráció kihagyva: {e}")


def _now_iso():
    return datetime.now().replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


def _db_ready():
    """Ne hozzunk létre 'üres' adatbázist csak azért, mert futásnaplót írnánk."""
    return os.path.exists(DB_FILE)


def record_run_start(trigger, started_at=None):
    """Új futás sora (status=running); visszaadja az id-t vagy None-t."""
    if not _db_ready():
        return None
    started_at = started_at or _now_iso()
    try:
        conn = get_db_connection()
        ensure_run_tables(conn)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sync_runs (trigger, started_at, status) VALUES (?, ?, ?)",
            (trigger, started_at, SYNC_RUNNING_STATUS),
        )
        conn.commit()
        run_id = cur.lastrowid
        conn.close()
        return run_id
    except sqlite3.Error as e:
        print(f"[Futásnapló] Indítás mentése nem sikerült: {e}")
        return None


def record_run_finish(run_id, status, finished_at=None, ok_count=None, total_count=None,
                      failed_students=None, new_events=None, new_messages=None,
                      new_hianyzasok=None, sources=None, duration_sec=None, tanev=None):
    """A futás sorának lezárása (a tanév a futás napjából számítva, Kaneo #40)."""
    if run_id is None or not _db_ready():
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE sync_runs SET finished_at = ?, status = ?, ok_count = ?, total_count = ?,
                   failed_students = ?, new_events = ?, new_messages = ?, new_hianyzasok = ?,
                   sources = ?, duration_sec = ?, tanev = ?
            WHERE id = ?
        """, (
            finished_at or _now_iso(), status, ok_count, total_count,
            json.dumps(failed_students or [], ensure_ascii=False),
            json.dumps(new_events or {}, ensure_ascii=False),
            json.dumps(new_messages or {}, ensure_ascii=False),
            json.dumps(new_hianyzasok or {}, ensure_ascii=False),
            json.dumps(sources or {}, ensure_ascii=False),
            duration_sec, tanev, run_id,
        ))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"[Futásnapló] Lezárás mentése nem sikerült: {e}")


def last_recorded_tanev():
    """A legutóbbi futásnál rögzített tanév (tanévváltás-figyeléshez)."""
    if not _db_ready():
        return ""
    try:
        conn = get_db_connection()
        ensure_run_tables(conn)
        row = conn.execute(
            "SELECT tanev FROM sync_runs WHERE tanev IS NOT NULL AND tanev <> ''"
            " ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return (row[0] if row else "") or ""
    except sqlite3.Error:
        return ""


# ── Tanév-állapot a TanevUid alapján (Kaneo #43) ────────────────────────────
def update_tanev_state_from_api(log_fn=None):
    """A diákonkénti `TanuloAdatlap.TanevUid` ellenőrzése és a tanév-állapot frissítése.

    A szinkronfutás **után** hívjuk (a scraper már kilépett), így nincs
    token-párhuzamosság. Visszaadja a tanévváltásokat (ha voltak).
    """
    log_fn = log_fn or print
    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    students = [s for s in cfg.get("STUDENTS", []) if s.get("active", True)]
    changes = []
    for student in students:
        diak = str(student.get("diak_nev") or "").strip()
        if not diak:
            continue
        try:
            with kreta_api.KretaApiClient(student) as client:
                uid = client.fetch_tanev_uid()
        except Exception as exc:  # noqa: BLE001 — hálózat/auth/parse
            log_fn(f"[Tanév-állapot] {diak}: a TanevUid nem olvasható "
                   f"({type(exc).__name__})")
            continue
        try:
            conn = get_db_connection()
            res = kreta_tanev.apply_tanev_uid(conn, diak, uid, log_fn=log_fn)
            conn.close()
        except sqlite3.Error as exc:
            log_fn(f"[Tanév-állapot] {diak}: mentési hiba: {exc}")
            continue
        if res.get("lezart_tanev") or res.get("uj_tanev"):
            changes.append(res)
    for ch in changes:
        log_fn(f"> TANÉV LEZÁRVA: {ch.get('lezart_tanev') or '-'}, "
               f"MEGNYITVA: {ch.get('uj_tanev') or '-'} ({ch.get('diak_nev')})")
    return changes


def mark_interrupted_runs():
    """Induláskor: a beragadt 'running' sorok megszakadtak (a folyamat már nincs)."""
    try:
        conn = get_db_connection()
        ensure_run_tables(conn)
        cur = conn.cursor()
        cur.execute(
            "UPDATE sync_runs SET status = 'interrupted' WHERE status = ?", (SYNC_RUNNING_STATUS,)
        )
        if cur.rowcount:
            print(f"[Futásnapló] {cur.rowcount} megszakadt futás jelölve.")
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"[Futásnapló] A megszakadt futások jelölése nem sikerült: {e}")


def get_meta(key, default=None):
    if not _db_ready():
        return default
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT value FROM app_meta WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else default
    except sqlite3.Error:
        return default


def set_meta(key, value):
    if not _db_ready():
        return
    try:
        conn = get_db_connection()
        ensure_run_tables(conn)
        conn.execute(
            "INSERT OR REPLACE INTO app_meta (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, _now_iso()),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"[Meta] Írás nem sikerült ({key}): {e}")


def _row_to_state(row):
    if row is None:
        return {}
    def _loads(value, fallback):
        try:
            return json.loads(value) if value else fallback
        except (ValueError, TypeError):
            return fallback
    return {
        "id": row["id"],
        "last_run_started": row["started_at"],
        "last_run_finished": row["finished_at"],
        "last_status": row["status"],
        "last_trigger": row["trigger"],
        "last_ok": row["ok_count"],
        "last_total": row["total_count"],
        "last_failed_students": _loads(row["failed_students"], []),
        "last_new_events": _loads(row["new_events"], {}),
        "last_new_messages": _loads(row["new_messages"], {}),
        "last_new_hianyzasok": _loads(row["new_hianyzasok"], {}),
        "last_sources": _loads(row["sources"], {}),
        "last_duration_sec": row["duration_sec"],
    }


def scheduler_state():
    """A 'legutóbbi futás' állapot a DB-ből (a régi JSON-állapot helyett)."""
    state = {}
    try:
        conn = get_db_connection()
        ensure_run_tables(conn)
        cur = conn.cursor()
        cur.execute("SELECT * FROM sync_runs ORDER BY started_at DESC, id DESC LIMIT 1")
        state = _row_to_state(cur.fetchone())

        cur.execute(
            "SELECT * FROM sync_runs WHERE trigger = 'scheduled' ORDER BY started_at DESC, id DESC LIMIT 1"
        )
        scheduled = _row_to_state(cur.fetchone())
        if scheduled:
            state["last_scheduled_run"] = scheduled.get("last_run_started")
            state["last_scheduled_status"] = scheduled.get("last_status")
            state["last_scheduled_finished"] = scheduled.get("last_run_finished")
            state["last_scheduled_failed_students"] = scheduled.get("last_failed_students") or []

        state["last_stale_alert"] = get_meta("last_stale_alert")
        conn.close()
    except sqlite3.Error as e:
        print(f"[Futásnapló] Olvasás nem sikerült: {e}")
    return state


def init_db_extensions():
    if os.path.exists(DB_FILE):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # WAL + futásnapló táblák + egyszeri átvétel a régi JSON-ból
            enable_wal(conn)
            check_db_integrity(conn)
            ensure_run_tables(conn)
            migrate_state_file(conn)
            mark_interrupted_runs()
            
            # Kifizetések tábla
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kifizetesek (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    diak_nev TEXT NOT NULL,
                    kezdo_datum TEXT NOT NULL,
                    zaro_datum TEXT NOT NULL,
                    kifizetve INTEGER DEFAULT 0,
                    osszeg INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(diak_nev, kezdo_datum, zaro_datum)
                )
            """)
            
            # Hiányzások / késések és igazolások táblái (a scraper is létrehozza,
            # itt azért kell, hogy a felület a legelső szinkron előtt se hibázzon).
            cursor.execute("""
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
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_hianyzasok_diak ON hianyzasok(diak_nev, mulasztas_datum)")
            # Régi séma: az 'oraszam' valójában a napon belüli órasorszám volt.
            cursor.execute("PRAGMA table_info(hianyzasok)")
            hianyzas_cols = [row["name"] for row in cursor.fetchall()]
            if "oraszam" in hianyzas_cols and "ora_sorszam" not in hianyzas_cols:
                try:
                    cursor.execute("ALTER TABLE hianyzasok RENAME COLUMN oraszam TO ora_sorszam")
                    print("[Adatbázis séma frissítve]: hianyzasok.oraszam -> ora_sorszam")
                except sqlite3.Error as ex:
                    print(f"[Sémafrissítési figyelmeztetés]: {ex}")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS igazolasok (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    diak_nev TEXT,
                    kreta_id TEXT,
                    kezdete TEXT,
                    vege TEXT,
                    igazolas_tipus TEXT,
                    megjegyzes TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_igazolasok_diak ON igazolasok(diak_nev, kezdete)")

            # Órarend tábla
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orarend (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    diak_nev TEXT,
                    kezdo_idopont TEXT,
                    zaro_idopont TEXT,
                    nap TEXT,
                    tantargy TEXT,
                    tanar TEXT,
                    terem TEXT
                )
            """)
            
            # Ellenőrizzük, hogy az esemenyek táblában létezik-e a 'kesz' oszlop
            cursor.execute("PRAGMA table_info(esemenyek)")
            columns = [row["name"] for row in cursor.fetchall()]
            if "kesz" not in columns:
                cursor.execute("ALTER TABLE esemenyek ADD COLUMN kesz INTEGER DEFAULT 0")
                print("[Adatbázis séma frissítve]: 'kesz' oszlop hozzáadva az 'esemenyek' táblához.")
            # A jegyek súlyszázaléka (mobil API: SulySzazalekErteke); régi DB-ben nincs.
            if "suly_szazalek" not in columns:
                cursor.execute("ALTER TABLE esemenyek ADD COLUMN suly_szazalek INTEGER")
                print("[Adatbázis séma frissítve]: 'suly_szazalek' oszlop hozzáadva az 'esemenyek' táblához.")

            # Tanév-dimenzió (Kaneo #40): oszlopok + a meglévő sorok feltöltése.
            added = kreta_tanev.ensure_tanev_schema(conn, log_fn=print)
            if added:
                print(f"[Adatbázis séma frissítve]: tanév-oszlopok: {', '.join(added)}")
            kreta_tanev.backfill_tanev(conn, log_fn=print, batch=200)
            # Tanév-állapot (Kaneo #43): tanevek + tanulo_tanev_uid, kezdeti állapot.
            kreta_tanev.ensure_tanev_state_schema(conn, log_fn=print)
            kreta_tanev.seed_tanev_state(conn, log_fn=print)

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Adatbázis inicializálási figyelmeztetés]: {e}")

# Ha a DB fájl hiányzik vagy üres (kézi áthelyezés/törlés), előbb a teljes séma.
ensure_db_schema(reason="indítás")
init_db_extensions()

def get_app_version():
    """A deploy által a data kötetre írt verzió (version.txt), pl. 'v1.1.1'."""
    try:
        with open(VERSION_FILE, "r", encoding="utf-8-sig") as f:
            version = f.read().strip()
        return version or "dev"
    except OSError:
        return "dev"


def load_config():
    if os.path.exists(CONFIG_FILE):
        # utf-8-sig: a Windows Notepad/PowerShell által írt BOM-ot is kezeli,
        # különben egy BOM-os config.json-tól nem indulna el az alkalmazás.
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except ValueError as e:
            print(f"[Konfiguráció hiba] A {CONFIG_FILE} nem érvényes JSON: {e}")
            return {}
    return {}

# ==============================================================================
# === ÜTEMEZETT SZINKRONIZÁCIÓ (config.json → SCHEDULER blokk) ==================
# ==============================================================================
# Alapelv: NINCS lemaradt futás pótlás. Egyetlen szabály van: az utolsó futás
# kezdete + INTERVAL_MINUTES. Ha közben állt a konténer, a következő ticknél
# egyszer lefut, majd visszaáll a normál ciklusra.
#
# A "legutóbbi futás" a data köteten lévő scheduler_state.json-ban él, így a
# gyakori deploy/újraindítás nem indít minden alkalommal azonnal szinkront.
SCHEDULER_TICK_SECONDS = 30          # ennyit vár a ciklus két ellenőrzés között
SCHEDULER_FIRST_DELAY_MIN = 5        # ha még sosem futott (friss telepítés)
SCHEDULER_TS_FMT = "%Y-%m-%dT%H:%M:%S"

scheduler_lock = threading.Lock()
_scheduler_thread = None
_scheduler_boot = datetime.now().replace(microsecond=0)
# Memória-beli biztonsági háló: ha az állapotfájlt nem sikerül írni (pl. HDD
# leszakadás), akkor se essen bele végtelen újraindításba az ütemező.
_last_scheduled_memo = None


def _now():
    return datetime.now().replace(microsecond=0)


def scheduler_config():
    """A config.json SCHEDULER blokkja, ésszerű alapértékekkel és határolással."""
    raw = load_config().get("SCHEDULER") or {}
    try:
        interval = int(raw.get("INTERVAL_MINUTES", 180))
    except (TypeError, ValueError):
        interval = 180
    try:
        start_hour = int(raw.get("START_HOUR", 0))
        end_hour = int(raw.get("END_HOUR", 24))
    except (TypeError, ValueError):
        start_hour, end_hour = 0, 24
    try:
        stale_hours = int(raw.get("STALE_ALERT_HOURS", 12))
    except (TypeError, ValueError):
        stale_hours = 12
    return {
        "enabled": bool(raw.get("ENABLED", False)),
        # 5 perc alatti intervallum értelmetlen (egy szinkron ~2,2 perc)
        "interval_minutes": max(5, interval),
        "start_hour": max(0, min(24, start_hour)),
        "end_hour": max(0, min(24, end_hour)),
        # Elavult adat riasztás: ennyi óra után push (0 = kikapcsolva).
        "stale_alert_hours": max(0, stale_hours),
    }


def load_scheduler_state():
    """Kompatibilitási név: a 'legutóbbi futás' állapota most a DB-ből jön."""
    return scheduler_state()


def save_scheduler_state(state):
    """Már nem használt (a futásnapló a DB-ben van); a régi hívások nem törjenek el."""
    return None


def _parse_scheduler_dt(value):
    try:
        return datetime.strptime(value, SCHEDULER_TS_FMT)
    except (TypeError, ValueError):
        return None


# Ha egy RÉGI állapotfájlban még nincs last_scheduled_status (a mező bevezetése
# előtti futás), a sync.log záró sorából pótoljuk. Kulcs: last_scheduled_run.
_scheduled_status_cache = {}


def _scheduled_status_from_log(last_scheduled_run):
    if not last_scheduled_run:
        return None
    if last_scheduled_run in _scheduled_status_cache:
        return _scheduled_status_cache[last_scheduled_run]

    status = None
    started = _parse_scheduler_dt(last_scheduled_run)
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(
                    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[INFO\] SZINKRONIZÁCIÓ VÉGE \(ütemezett\): (\w+)",
                    line,
                )
                if not m:
                    continue
                try:
                    finished = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                # csak az adott ütemezett futáshoz tartozó záró sor
                if started and started <= finished <= started + timedelta(hours=2):
                    status = m.group(2)
    except OSError:
        status = None

    _scheduled_status_cache[last_scheduled_run] = status
    return status


def _in_time_window(now, start_hour, end_hour):
    """START_HOUR..END_HOUR között? Ha a kettő egyenlő: nincs időablak (0-24)."""
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= now.hour < end_hour
    return now.hour >= start_hour or now.hour < end_hour   # átforduló ablak


def _next_window_start(now, start_hour, end_hour):
    if _in_time_window(now, start_hour, end_hour):
        return now
    target = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def scheduler_next_run(state=None, config=None, now=None):
    """Mikor lenne esedékes a következő automatikus futás (datetime vagy None)."""
    cfg = config or scheduler_config()
    if not cfg["enabled"]:
        return None
    now = now or _now()
    state = scheduler_state() if state is None else state

    # FONTOS: a ciklus KIZÁRÓLAG az utolsó ÜTEMEZETT futáshoz igazodik — egy
    # kézi "Adatok frissítése" nem tolja el az automatikus időzítést.
    last_scheduled = _parse_scheduler_dt(state.get("last_scheduled_run"))
    if last_scheduled is None and state.get("last_trigger") == "scheduled":
        # Visszafelé kompatibilitás: a korábbi állapotfájlban nem volt külön
        # last_scheduled_run mező, de a last_run_started ütemezett futás volt.
        last_scheduled = _parse_scheduler_dt(state.get("last_run_started"))
    last_scheduled = last_scheduled or _last_scheduled_memo

    if last_scheduled:
        due = last_scheduled + timedelta(minutes=cfg["interval_minutes"])
    else:
        due = _scheduler_boot + timedelta(minutes=SCHEDULER_FIRST_DELAY_MIN)

    # A TÉNYLEGES következő futás: ha az esedékesség időpontja az időablakon
    # kívülre esik (pl. 22:16 + 3 óra = 01:16, de az ablak 6-22), akkor az
    # ablak következő nyitására tolódik (06:00) — így a felület sem írhat
    # olyan időpontot, amikor valójában nem fut le.
    reference = max(due, now)
    if not _in_time_window(reference, cfg["start_hour"], cfg["end_hour"]):
        reference = _next_window_start(reference, cfg["start_hour"], cfg["end_hour"])
    return reference


def scheduler_status():
    cfg = scheduler_config()
    state = scheduler_state()
    nxt = scheduler_next_run(state=state, config=cfg)
    with sync_lock:
        running = sync_state["running"]
        trigger = sync_state.get("trigger")

    # Ha a DB-ben "running" van, de nincs futó folyamat (pl. a konténer közben
    # újraindult), akkor az előző futás félbeszakadt.
    last_status = state.get("last_status")
    if last_status == "running" and not running:
        last_status = "interrupted"

    # Az utolsó ÜTEMEZETT futás eredménye külön (a felület mindkettőt kiírja).
    last_scheduled_status = state.get("last_scheduled_status")
    if last_scheduled_status is None and state.get("last_trigger") == "scheduled":
        # Régi állapotfájl: akkor a last_status az ütemezett futásé.
        last_scheduled_status = last_status
    if last_scheduled_status is None:
        # Még régebbi állapot + kézi utolsó futás: a naplóból pótoljuk.
        last_scheduled_status = _scheduled_status_from_log(state.get("last_scheduled_run"))
    if last_scheduled_status == "running" and not running:
        last_scheduled_status = "interrupted"

    return {
        "enabled": cfg["enabled"],
        "interval_minutes": cfg["interval_minutes"],
        "start_hour": cfg["start_hour"],
        "end_hour": cfg["end_hour"],
        "next_run": nxt.strftime("%Y-%m-%d %H:%M") if nxt else None,
        "next_run_iso": nxt.strftime(SCHEDULER_TS_FMT) if nxt else None,
        "last_run": state.get("last_run_started"),
        "last_run_finished": state.get("last_run_finished"),
        "last_status": last_status,
        "last_trigger": state.get("last_trigger"),
        "last_failed_students": state.get("last_failed_students") or [],
        "last_scheduled_run": state.get("last_scheduled_run")
        or (state.get("last_run_started") if state.get("last_trigger") == "scheduled" else None),
        "last_scheduled_status": last_scheduled_status,
        "last_scheduled_finished": state.get("last_scheduled_finished"),
        "last_scheduled_failed_students": state.get("last_scheduled_failed_students") or [],
        "running": running,
        "trigger": trigger,
    }


def _append_sync_log(message):
    """Bekezdés a sync.log-ba ugyanabban a formátumban, amit a scraper használ."""
    try:
        _rotate_log_if_needed()
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{_now().strftime('%Y-%m-%d %H:%M:%S')} [INFO] {message}\n")
    except OSError as e:
        print(f"[Ütemező] A sync.log írása nem sikerült: {e}")


def _rotate_log_if_needed():
    """sync.log rotáció (a scraper RotatingFileHandler-jával azonos méret mellett)."""
    try:
        if not os.path.exists(LOG_FILE):
            return
        if os.path.getsize(LOG_FILE) < LOG_MAX_BYTES:
            return
        # .1 -> .2, sync.log -> .1 (a régieket felülírva; max 2 mentés)
        for i in range(LOG_BACKUP_COUNT, 1, -1):
            src = f"{LOG_FILE}.{i-1}"
            dst = f"{LOG_FILE}.{i}"
            if os.path.exists(src):
                os.replace(src, dst)
        os.replace(LOG_FILE, f"{LOG_FILE}.1")
    except OSError as e:
        # Windows: ha épp a scraper tartja nyitva, hagyjuk — a következő írásnál újrapróbáljuk
        print(f"[Napló] Rotáció kihagyva: {e}")


# ── Értesítés (ntfy) ─────────────────────────────────────────────────────────
# A backup-script már használ ntfy-t; ugyanaz a csatorna itt is működik.
# A beállítás jöhet a config.json `NTFY` blokkjából (kényelmes lokálisan), de a
# környezeti változó mindig erősebb — a szerveren a .env a hiteles forrás.
def _ntfy_config(key, default=None):
    """A config.json `NTFY` blokkja (pl. {"NTFY": {"TOPIC": "kreta-..."}})."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            block = (json.load(f) or {}).get("NTFY") or {}
    except (OSError, ValueError):
        return default
    if not isinstance(block, dict):
        return default
    value = block.get(key)
    return default if value is None else value


def _ntfy_flag(env_name, config_key, default):
    """Kapcsoló: env változó → config.json NTFY kulcs → alapérték."""
    env_value = os.environ.get(env_name)
    if env_value is not None and str(env_value).strip() != "":
        return str(env_value).strip().lower() in ("1", "true", "yes", "on")
    value = _ntfy_config(config_key)
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


NTFY_TOPIC = (os.environ.get("NTFY_TOPIC", "").strip()
              or str(_ntfy_config("TOPIC", "") or "").strip())
NTFY_URL = (os.environ.get("NTFY_URL", "").strip()
            or str(_ntfy_config("URL", "https://ntfy.sh") or "https://ntfy.sh")).rstrip("/")
NTFY_TIMEOUT = int(os.environ.get("NTFY_TIMEOUT", 5))
STALE_ALERT_REPEAT_HOURS = 6
# A diáknevek személyes adatok — a nyilvános ntfy.sh-ra alapból NEM küldjük őket.
NTFY_INCLUDE_NAMES = _ntfy_flag("NTFY_INCLUDE_NAMES", "INCLUDE_NAMES", False)
# Sikeres futásról is küldjünk-e push-t (alapból igen, mert ezt kérték).
NTFY_NOTIFY_SUCCESS = _ntfy_flag("NTFY_NOTIFY_SUCCESS", "NOTIFY_SUCCESS", True)

# Ha mindkét helyen van topic, induláskor jelezzük, hogy a config.json értéke
# nem érvényesül (az env az erősebb) — így nem kell találgatni, miért nem az a
# topic kap értesítést, amit a config.json-ba írtunk.
_env_topic = os.environ.get("NTFY_TOPIC", "").strip()
_cfg_topic = str(_ntfy_config("TOPIC", "") or "").strip()
if _env_topic and _cfg_topic and _env_topic != _cfg_topic:
    print(f"[ntfy] A .env NTFY_TOPIC-ja él ({_env_topic[:10]}…), a config.json "
          f"NTFY.TOPIC-ot ({_cfg_topic[:10]}…) nem használom.")


def _http_post_ntfy(url, data, headers, timeout):
    """A tényleges HTTP hívás — tesztben monkeypatch-elhető."""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def _ntfy_target():
    """
    Visszaadja (publish_url, topic) párban.

    FONTOS: a JSON publish API-t a szerver GYÖKÉRE kell POST-olni
    (pl. https://ntfy.sh) — a topic URL-re küldött JSON-t a szolgáltatás magát
    az üzenetnek tekinti, ezért jelent meg nyers JSON a telefonon.

    A backup-script konvenciója szerint a NTFY_TOPIC lehet teljes URL is
    (https://ntfy.sh/kreta-xyz); ilyenkor a topic az utolsó path-szegmens.
    """
    if NTFY_TOPIC.startswith("http://") or NTFY_TOPIC.startswith("https://"):
        base, _, topic = NTFY_TOPIC.rstrip("/").rpartition("/")
        return (base or NTFY_URL), topic
    return NTFY_URL, NTFY_TOPIC


_NTFY_PRIORITIES = {"min": 1, "low": 2, "default": 3, "high": 4, "max": 5, "urgent": 5}

# Az eseménytípusok rövid, üzenetbarát nevei (a DB-ben tárolt értékek)
EVENT_TYPE_LABELS = {
    "Értékelés": "jegy",
    "Feljegyzés": "feljegyzés",
    "Házi feladat": "házi",
    "Bejelentett számonkérés": "számonkérés",
}
EVENT_TYPE_ORDER = ["Értékelés", "Házi feladat", "Bejelentett számonkérés", "Feljegyzés"]


def format_new_events(new_events, new_messages=None, new_hianyzasok=None):
    """
    Emberi olvasású bontás a push-üzenethez:
        ["Teszt Elek: 2 jegy, 1 házi", "Teszt Anna: 1 üzenet, 3 hiányzás (2 igazolatlan óra)"]
    Csak azt a diákot írja ki, akinél történt valami.
    """
    new_messages = new_messages or {}
    new_hianyzasok = new_hianyzasok or {}
    diakok = list(dict.fromkeys(
        list(new_events or {}) + list(new_messages) + list(new_hianyzasok)
    ))
    lines = []
    for diak in diakok:
        counts = (new_events or {}).get(diak) or {}
        parts = []
        for tipus in EVENT_TYPE_ORDER:
            n = int((counts or {}).get(tipus, 0) or 0)
            if n:
                parts.append(f"{n} {EVENT_TYPE_LABELS.get(tipus, tipus)}")
        n_msg = int(new_messages.get(diak, 0) or 0)
        if n_msg:
            parts.append(f"{n_msg} üzenet")
        h = new_hianyzasok.get(diak) or {}
        n_h = int(h.get("db", 0) or 0)
        if n_h:
            ora = int(h.get("igazolatlan_ora", 0) or 0)
            parts.append(f"{n_h} hiányzás" + (f" ({ora} igazolatlan óra)" if ora else ""))
        if parts:
            lines.append(f"{diak}: {', '.join(parts)}")
    return lines


def _ntfy_priority(value):
    """A JSON API számot vár (1-5); a szöveges neveket is elfogadjuk."""
    if isinstance(value, str):
        return _NTFY_PRIORITIES.get(value.strip().lower(), 3)
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return 3


def send_notification(title, message, priority=3, tags=None):
    """
    ntfy push küldése háttérszálban. Ha nincs NTFY_TOPIC, csendben nem tesz semmit.
    A JSON publish API-t használjuk (a fejlécek nem bírnak el ékezetet).
    A priority a JSON API-ban SZÁM (1=min … 5=max) — szöveges értéket 400-zal elutasít,
    ezért itt alakítjuk át.
    """
    if not NTFY_TOPIC:
        return False

    url, topic = _ntfy_target()
    payload = json.dumps(
        {
            "topic": topic,
            "title": title,
            "message": message,
            "priority": _ntfy_priority(priority),
            "tags": tags or ["warning"],
        },
        ensure_ascii=False,
    ).encode("utf-8")

    def _send():
        try:
            _http_post_ntfy(
                url,
                payload,
                {"Content-Type": "application/json; charset=utf-8"},
                NTFY_TIMEOUT,
            )
        except Exception as e:
            print(f"[Értesítés] Nem sikerült elküldeni: {e}")

    threading.Thread(target=_send, name="kreta-ntfy", daemon=True).start()
    return True


def notify_sync_result(status, failed_students, trigger, duration_min, ok_count=None, total=None,
                       new_events=None, new_messages=None, new_hianyzasok=None):
    """A szinkron eredményéről szóló push (hiba / részleges hiba / sikeres)."""
    failed_txt = ", ".join(failed_students) if failed_students else ""
    event_lines = format_new_events(new_events, new_messages, new_hianyzasok)
    events_block = ("\n\n" + "\n".join(event_lines)) if event_lines else ""

    if status == "done_with_errors":
        if failed_students and NTFY_INCLUDE_NAMES:
            detail = f"Nem frissült: {failed_txt}"
        elif failed_students:
            detail = f"{len(failed_students)} diák nem frissült (részletek a Rendszernaplóban)"
        else:
            detail = "Részletek a Rendszernaplóban"
        return send_notification(
            "KRÉTA szinkron: részleges hiba",
            f"{trigger_label(trigger)} futás · {duration_min:.1f} perc · {detail}" + events_block,
            3,
            ["warning"],
        )
    if status == "done":
        if not NTFY_NOTIFY_SUCCESS:
            return False
        if ok_count is not None and total is not None:
            detail = f"{ok_count}/{total} diák frissült."
        else:
            detail = "Minden diák adata frissült."
        return send_notification(
            "KRÉTA szinkron: sikeres",
            f"{trigger_label(trigger)} futás · {duration_min:.1f} perc · {detail}"
            + (events_block or "\n\nNem volt új esemény."),
            2,
            ["white_check_mark"],
        )
    if status == "error":
        return send_notification(
            "KRÉTA szinkron: HIBA",
            f"A {trigger_label(trigger)} szinkron hibával ért véget ({duration_min:.1f} perc). "
            f"Részletek a Rendszernaplóban."
            + events_block,
            4,
            ["rotating_light"],
        )
    return False


def _maybe_notify_stale(cfg):
    """Ha túl régi az utolsó futás, egyszer riasztunk (legfeljebb 6 óránként)."""
    stale_hours = cfg.get("stale_alert_hours", 12)
    if not stale_hours or stale_hours <= 0 or not NTFY_TOPIC:
        return False
    state = scheduler_state()
    last = _parse_scheduler_dt(state.get("last_run_started"))
    if not last:
        return False
    age_h = (_now() - last).total_seconds() / 3600
    if age_h < stale_hours:
        return False
    last_alert = _parse_scheduler_dt(state.get("last_stale_alert"))
    if last_alert and (_now() - last_alert).total_seconds() < STALE_ALERT_REPEAT_HOURS * 3600:
        return False
    sent = send_notification(
        "KRÉTA: elavult adatok",
        f"Az utolsó szinkron {age_h:.0f} órával ezelőtt volt (küszöb: {stale_hours} óra).",
        4,
        ["hourglass"],
    )
    if sent:
        set_meta("last_stale_alert", _now().strftime(SCHEDULER_TS_FMT))
    return sent


def trigger_label(trigger):
    """A naplóban/UI-ban használt magyar megnevezés."""
    return {"manual": "kézi", "scheduled": "ütemezett"}.get(trigger, trigger or "-")


def start_sync(trigger="manual"):
    """
    Egyetlen belépési pont a szinkron indítására (kézi gomb és ütemező is ezt
    használja). A 'running' jelzőt a szál indítása ELŐTT, a lock alatt foglalja
    le, így két egyszerre érkező kérés nem indíthat két párhuzamos futást.
    """
    with sync_lock:
        if sync_state["running"]:
            return False
        sync_state["running"] = True
        sync_state["status"] = "starting"
        sync_state["trigger"] = trigger
    try:
        threading.Thread(target=run_scraper_thread, args=(trigger,), daemon=True).start()
    except Exception:
        # Ha a szál nem indult el, ne maradjon örökre "fut" állapotban.
        with sync_lock:
            sync_state["running"] = False
            sync_state["status"] = "error"
        raise

    # A naplóban mindig látszik, hogy kézi vagy ütemezett futás indult.
    if trigger == "scheduled":
        _append_sync_log(
            f"ÜTEMEZETT SZINKRONIZÁCIÓ INDÍTÁSA (ütemező: {scheduler_config()['interval_minutes']} percenként)"
        )
    else:
        _append_sync_log("KÉZI SZINKRONIZÁCIÓ INDÍTÁSA (felületi gomb)")
    return True


def _scheduler_loop():
    """Háttérszál: 30 másodpercenként dönt, hogy esedékes-e a szinkron."""
    print("[Ütemező] Háttérszál elindult.")
    while True:
        try:
            cfg = scheduler_config()
            due = scheduler_next_run(config=cfg)
            if due and _now() >= due and _in_time_window(_now(), cfg["start_hour"], cfg["end_hour"]):
                # a naplózást a start_sync végzi (egységesen, mindkét triggerre)
                start_sync("scheduled")
                # ha épp fut valami, a következő tick újra próbálja (nincs sorban állás)
            _maybe_notify_stale(cfg)
        except Exception as e:
            print(f"[Ütemező] Hiba a ciklusban: {e}")
        time.sleep(SCHEDULER_TICK_SECONDS)


def start_scheduler():
    """Az ütemező szál indítása — csak egyszer, és csak a fő processzből."""
    global _scheduler_thread
    with scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return
        # Egy hibás config.json soha ne akadályozza meg a webszerver indulását.
        try:
            cfg = scheduler_config()
        except Exception as e:
            print(f"[Ütemező] A SCHEDULER beállítás nem olvasható ({e}) — ütemező kikapcsolva.")
            cfg = {"enabled": False, "interval_minutes": 180, "start_hour": 0, "end_hour": 24}
        _scheduler_thread = threading.Thread(
            target=_scheduler_loop, name="kreta-scheduler", daemon=True
        )
        _scheduler_thread.start()
        print(
            f"[Ütemező] enabled={cfg['enabled']}, intervallum={cfg['interval_minutes']} perc, "
            f"ablak={cfg['start_hour']}-{cfg['end_hour']} óra"
        )


def run_scraper_thread(trigger="manual"):
    global sync_state, _last_scheduled_memo
    
    with sync_lock:
        sync_state["running"] = True
        sync_state["trigger"] = trigger
        sync_state["logs"] = ["> Szinkronizáció indítása a háttérben..."]
        sync_state["status"] = "running"
        sync_state["failed_students"] = []
        sync_state["ok_count"] = None
        sync_state["total_students"] = None
        sync_state["new_events"] = {}
        sync_state["new_messages"] = {}
        sync_state["new_hianyzasok"] = {}
        sync_state["sources"] = {}

    # A ciklus alapja a futás KEZDEMÉNYEZÉSE (nem a vége), így a ~2,2 perces
    # futás nem tolja el az ütemezést. Az ütemező ciklusához CSAK az ütemezett
    # futás számít — a kézi indítás csak a "legutóbbi frissítés" infóhoz kell.
    started_at = _now()
    run_id = record_run_start(trigger, started_at.strftime(SCHEDULER_TS_FMT))
    if trigger == "scheduled":
        _last_scheduled_memo = started_at

    # Tanév-naplózás (Kaneo #40): a futás naptári tanéve a sync_runs-ba kerül.
    # A tanév-állapotot (zárás/nyitás) a futás UTÁN a TanevUid alapján frissítjük
    # (Kaneo #43) — itt még nincs UID-információ.
    run_tanev = kreta_tanev.current_tanev()
    with sync_lock:
        sync_state["logs"].append(f"> Tanév: {run_tanev}")

    failed_students = []
    try:
        # A scraper ugyanazokat az útvonalakat kapja, amiket az app használ —
        # így nem fordulhat elő, hogy a konténerben máshol keresi a configot.
        child_env = os.environ.copy()
        child_env["KRETA_DATA_DIR"] = DATA_DIR
        child_env["KRETA_CONFIG_FILE"] = CONFIG_FILE
        child_env["KRETA_DB_FILE"] = DB_FILE
        child_env["KRETA_LOG_FILE"] = LOG_FILE
        child_env["KRETA_CSATOLMANYOK_DIR"] = CSATOLMANYOK_DIR

        # A scraper mindig UTF-8-at írjon és a Flask is UTF-8-ként olvassa: a
        # Windows alapértelmezett kódlapja (cp1250) és a Docker locale eltérhet,
        # ettől korábban a kimenet-olvasó szál elszállt (UnicodeDecodeError),
        # a futás "hiba" állapotba került, a scraper gyerekprocessz pedig árva
        # maradt és megakadt a teli pipe-on.
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUTF8"] = "1"

        process = subprocess.Popen(
            [sys.executable, "-u", "kreta_playwright.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_env
        )

        with sync_lock:
            sync_state["process"] = process

        try:
            for line in iter(process.stdout.readline, ''):
                if line:
                    cleaned_line = line.strip()
                    with sync_lock:
                        sync_state["logs"].append(cleaned_line)
                        if len(sync_state["logs"]) > 500:
                            sync_state["logs"].pop(0)
        finally:
            # Ha az olvasás bármiért megszakad, ne maradjon futó scraper
            # (böngészőprofil-ütközés és megakadt pipe nélkül).
            try:
                process.stdout.close()
            except Exception:
                pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass

        process.wait()

        # A scraper gép-olvasható összegzése + kilépési kódja:
        #   0 = minden diák rendben, 2 = részleges hiba (a többi diák mentve),
        #   egyéb = végzetes hiba.
        failed_students = []
        ok_count = None
        total_students = None
        new_events = {}
        new_messages = {}
        new_hianyzasok = {}
        sources = {}
        with sync_lock:
            log_lines = list(sync_state["logs"])
        for line in log_lines:
            if RESULT_MARKER in line:
                try:
                    payload = json.loads(line.split(RESULT_MARKER, 1)[1])
                    failed_students = [str(n) for n in payload.get("failed", [])]
                    ok_count = payload.get("ok")
                    total_students = payload.get("total")
                    new_events = payload.get("new_events") or {}
                    new_messages = payload.get("new_messages") or {}
                    new_hianyzasok = payload.get("new_hianyzasok") or {}
                    sources = payload.get("sources") or {}
                except (ValueError, AttributeError, TypeError):
                    pass

        with sync_lock:
            sync_state["failed_students"] = failed_students
            sync_state["ok_count"] = ok_count
            sync_state["total_students"] = total_students
            sync_state["new_events"] = new_events
            sync_state["new_messages"] = new_messages
            sync_state["new_hianyzasok"] = new_hianyzasok
            sync_state["sources"] = sources
            if sync_state["status"] != "stopped":
                if process.returncode == 0:
                    sync_state["status"] = "done"
                    sync_state["logs"].append("> SZINKRONIZÁCIÓ SIKERESEN BEFEJEZŐDÖTT!")
                elif process.returncode == 2:
                    sync_state["status"] = "done_with_errors"
                    sync_state["logs"].append(
                        "> SZINKRONIZÁCIÓ RÉSZBEN SIKERES — hibás diák: "
                        + (", ".join(failed_students) if failed_students else "ismeretlen")
                    )
                else:
                    sync_state["status"] = "error"
                    sync_state["logs"].append("> HIBA TÖRTÉNT A SZINKRONIZÁCIÓ SORÁN!")

    except Exception as e:
        with sync_lock:
            sync_state["status"] = "error"
            sync_state["logs"].append(f"> Kivétel történt: {str(e)}")
    finally:
        with sync_lock:
            sync_state["running"] = False
            sync_state["process"] = None
            final_status = sync_state["status"]
            final_failed = list(sync_state.get("failed_students") or [])
            final_ok = sync_state.get("ok_count")
            final_total = sync_state.get("total_students")
            final_new_events = sync_state.get("new_events") or {}
            final_new_messages = sync_state.get("new_messages") or {}
            final_new_hianyzasok = sync_state.get("new_hianyzasok") or {}
            final_sources = sync_state.get("sources") or {}

        # Tanév-állapot (Kaneo #43): a TanevUid ellenőrzése a futás után; ha
        # megváltozott, a nyitott tanévet lezárjuk és az újat megnyitjuk.
        def _tanev_state_log(msg):
            with sync_lock:
                sync_state["logs"].append(str(msg))
            _append_sync_log(str(msg))

        try:
            tanev_changes = update_tanev_state_from_api(log_fn=_tanev_state_log)
        except Exception as exc:  # noqa: BLE001 — a futás eredményét ne rontsa el
            tanev_changes = []
            _tanev_state_log(f"[Tanév-állapot] hiba: {type(exc).__name__}: {exc}")

        # A futás sorát lezárjuk a DB-ben (ez a "legutóbbi futás" állapot is).
        duration_sec = (_now() - started_at).total_seconds()
        record_run_finish(
            run_id, final_status,
            finished_at=_now().strftime(SCHEDULER_TS_FMT),
            ok_count=final_ok, total_count=final_total,
            failed_students=final_failed,
            new_events=final_new_events, new_messages=final_new_messages,
            new_hianyzasok=final_new_hianyzasok,
            sources=final_sources,
            duration_sec=duration_sec,
            tanev=run_tanev,
        )

        # Záró sor a naplóba: látszik a trigger (kézi/ütemezett) és az eredmény.
        duration_min = duration_sec / 60
        _append_sync_log(
            f"SZINKRONIZÁCIÓ VÉGE ({trigger_label(trigger)}): {final_status}, {duration_min:.1f} perc"
            + (f" — hibás diák: {', '.join(final_failed)}" if final_failed else "")
        )

        # Push értesítés: hiba / részleges hiba / sikeres (beállítástól függően).
        notify_sync_result(final_status, final_failed, trigger, duration_min, final_ok, final_total,
                           final_new_events, final_new_messages, final_new_hianyzasok)

        if tanev_changes:
            lezart = sorted({ch.get("lezart_tanev") for ch in tanev_changes if ch.get("lezart_tanev")})
            ujak = sorted({ch.get("uj_tanev") for ch in tanev_changes if ch.get("uj_tanev")})
            send_notification(
                "KRÉTA: új tanév",
                f"Tanév lezárva: {', '.join(lezart) or '-'} · megnyitva: {', '.join(ujak) or '-'}. "
                f"Adatlekérés nélkül, a KRÉTA TanevUid változása alapján.",
                3,
                ["calendar"],
            )

@app.route("/")
def index():
    config = load_config()
    global_enable_rewards = config.get("ENABLE_REWARDS", True)

    if not os.path.exists(DB_FILE):
        diakok, tipusok, tantargyak = [], [], []
    else:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT diak_nev FROM esemenyek UNION SELECT DISTINCT diak_nev FROM uzenetek UNION SELECT DISTINCT diak_nev FROM orarend UNION SELECT DISTINCT diak_nev FROM hianyzasok ORDER BY diak_nev")
        diakok = [row["diak_nev"] for row in cursor.fetchall() if row["diak_nev"]]

        cursor.execute("SELECT DISTINCT esemeny_tipus FROM esemenyek ORDER BY esemeny_tipus")
        tipusok = [row["esemeny_tipus"] for row in cursor.fetchall() if row["esemeny_tipus"]]

        cursor.execute("SELECT DISTINCT tantargy FROM esemenyek WHERE tantargy IS NOT NULL AND tantargy != '' ORDER BY tantargy")
        tantargyak = [row["tantargy"] for row in cursor.fetchall()]

        conn.close()

    return render_template(
        "index.html", 
        diakok=diakok, 
        tipusok=tipusok, 
        tantargyak=tantargyak,
        global_enable_rewards=global_enable_rewards,
        app_version=get_app_version()
    )

@app.route("/api/esemenyek")
def api_esemenyek():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "")
    tipus = request.args.get("tipus", "")
    tantargy = request.args.get("tantargy", "")
    tanev = _tanev_from_request()

    query = "SELECT * FROM esemenyek WHERE 1=1"
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    if tipus:
        query += " AND esemeny_tipus = ?"
        params.append(tipus)
    if tantargy:
        query += " AND tantargy = ?"
        params.append(tantargy)
    if tanev:
        query += " AND tanev = ?"
        params.append(tanev)

    query += " ORDER BY id DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    komment_db = komment_szamok(cursor, "esemeny")

    esemenyek = []
    for r in rows:
        keys = r.keys()
        kesz_val = r["kesz"] if "kesz" in keys else 0
        kulcs = komment_kulcs_esemeny(r)

        esemenyek.append({
            "id": r["id"],
            "diak_nev": r["diak_nev"],
            "esemeny_tipus": r["esemeny_tipus"],
            "tantargy": r["tantargy"] or "-",
            "ertek": r["ertek"] or "-",
            "szam_ertek": r["szam_ertek"] or 0,
            "suly_szazalek": (r["suly_szazalek"] or 0) if "suly_szazalek" in keys else 0,
            "tanev": (r["tanev"] or "") if "tanev" in keys else "",
            "bej_datum": r["bej_datum"] or "-",
            "hatarido": r["hatarido"] or "-",
            "ertekelo": r["ertekelo"] or "-",
            "tipus": r["tipus"] or "-",
            "mod": r["mod"] or "-",
            "tema": r["tema"] or "-",
            "cim": r["cim"] or "-",
            "tartalom": r["tartalom"] or "-",
            "kesz": int(kesz_val or 0),
            "komment_kulcs": kulcs,
            "komment_db": int(komment_db.get(kulcs, 0))
        })

    conn.close()
    return jsonify(esemenyek)

@app.route("/api/orarend")
def api_orarend():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "")
    query = "SELECT * FROM orarend WHERE 1=1"
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)

    query += " ORDER BY kezdo_idopont ASC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return jsonify([dict(row) for row in rows])

@app.route("/api/orarend_naptar")
def api_orarend_naptar():
    """Órarend lekérdezése a FullCalendar idősávos nézetéhez egyedi diák színkódolással."""
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT diak_nev FROM orarend ORDER BY diak_nev")
    osszes_diak = [r["diak_nev"] for r in cursor.fetchall() if r["diak_nev"]]

    color_palette = [
        {"bg": "#0d6efd", "border": "#0a58ca"},
        {"bg": "#198754", "border": "#146c43"},
        {"bg": "#6f42c1", "border": "#59359a"},
        {"bg": "#d63384", "border": "#ab296a"},
        {"bg": "#20c997", "border": "#1aa179"},
        {"bg": "#fd7e14", "border": "#ca6510"}
    ]

    diak_color_map = {}
    for idx, d_nev in enumerate(osszes_diak):
        diak_color_map[d_nev] = color_palette[idx % len(color_palette)]

    diak = request.args.get("diak", "")
    query = "SELECT * FROM orarend WHERE 1=1"
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    multi_student = not diak

    events = []
    for r in rows:
        d_nev = r["diak_nev"] or "Ismeretlen"
        kezdo = r["kezdo_idopont"]
        zaro = r["zaro_idopont"]
        tantargy = r["tantargy"] or "Tanóra"
        tanar = r["tanar"] or ""
        terem = r["terem"] or ""

        is_all_day = not zaro or "T" not in kezdo

        student_colors = diak_color_map.get(d_nev, {"bg": "#0d6efd", "border": "#0a58ca"})

        if is_all_day:
            title = f"🔴 {d_nev}: {tantargy}" if multi_student else f"🔴 {tantargy}"
            bg_color = "#fd7e14"
            border_color = "#ca6510"
        else:
            title = f"[{d_nev}] {tantargy}" if multi_student else tantargy
            if terem:
                title += f" ({terem})"
            bg_color = student_colors["bg"]
            border_color = student_colors["border"]

        events.append({
            "id": r["id"],
            "title": title,
            "start": kezdo,
            "end": zaro if zaro else None,
            "allDay": is_all_day,
            "backgroundColor": bg_color,
            "borderColor": border_color,
            "extendedProps": {
                "diak": d_nev,
                "tantargy": tantargy,
                "tanar": tanar,
                "terem": terem,
                "nap": r["nap"] or ""
            }
        })

    return jsonify(events)

# ==============================================================================
# === PDF BETŰKÉSZLET (magyar ő/ű támogatás) ===================================
# ==============================================================================
# A ReportLab beépített Type1 betűi (Helvetica stb.) csak Latin-1-et tudnak,
# így a hosszú ő/Ő és ű/Ű (U+0150–U+0171) NEM jelenik meg helyesen a PDF-ben.
# Ezért egy Unicode TrueType betűt regisztrálunk (amilyen épp elérhető a gépen):
# a konténerben Liberation/DejaVu, lokálisan (Windows) Arial/Calibri.
_PDF_FONT_REG = "KretaHU"
_PDF_FONT_BOLD = "KretaHU-Bold"


def _pdf_font_candidates():
    """(regular, bold) jelölt betűkészlet-párok, preferencia-sorrendben."""
    return [
        # Linux (Debian; a Dockerfile a playwright --with-deps / fonts-liberation miatt ezt tartalmazza)
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/freefont/FreeSans.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
        # Windows (fejlesztés)
        ("C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"),
        ("C:\\Windows\\Fonts\\calibri.ttf", "C:\\Windows\\Fonts\\calibrib.ttf"),
        ("C:\\Windows\\Fonts\\segoeui.ttf", "C:\\Windows\\Fonts\\seguisb.ttf"),
    ]


def _register_pdf_fonts():
    """Regisztrál egy ő/ű-t támogató betűkészletet; True ha sikerült."""
    if _PDF_FONT_REG in pdfmetrics.getRegisteredFontNames():
        return True
    for regular, bold in _pdf_font_candidates():
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont(_PDF_FONT_REG, regular))
                pdfmetrics.registerFont(TTFont(_PDF_FONT_BOLD, bold))
                pdfmetrics.registerFontFamily(
                    _PDF_FONT_REG,
                    normal=_PDF_FONT_REG,
                    bold=_PDF_FONT_BOLD,
                    italic=_PDF_FONT_REG,
                    boldItalic=_PDF_FONT_BOLD,
                )
                return True
            except Exception as e:
                print(f"[PDF] A(z) {regular} betűkészlet regisztrálása sikertelen: {e}")
    print("[PDF] FIGYELEM: nem található Unicode betűkészlet — az ő/ű hibás lehet.")
    return False


def _pdf_font():
    return _PDF_FONT_REG if _PDF_FONT_REG in pdfmetrics.getRegisteredFontNames() else "Helvetica"


def _pdf_font_bold():
    return _PDF_FONT_BOLD if _PDF_FONT_BOLD in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"


@app.route("/api/orarend/export_pdf")
def export_orarend_pdf():
    """Órarend PDF generálása teljesen elkülönített 'Egész napos' sor kezelésével."""
    if not os.path.exists(DB_FILE):
        return "Adatbázis nem található!", 404

    # Magyar ő/ű támogatáshoz Unicode betűkészlet regisztrálása (ha még nincs).
    _register_pdf_fonts()

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "").strip()

    # A frontend a naptárban ÉPPEN MEGJELENÍTETT hét kezdőnapját küldi a 'datum'
    # paraméterben — a PDF ahhoz a héthez készül. Üres/hibás paraméternél az
    # aktuális hét marad (visszafelé kompatibilis viselkedés).
    datum_param = request.args.get("datum", "").strip()
    try:
        hetfo = datetime.strptime(datum_param, "%Y-%m-%d")
    except ValueError:
        hetfo = datetime.now()
    hetfo = hetfo - timedelta(days=hetfo.weekday())
    hetfo_str = hetfo.strftime("%Y-%m-%d")
    vasarnap_str = (hetfo + timedelta(days=6)).strftime("%Y-%m-%d")

    if diak:
        diakok = [diak]
    else:
        cursor.execute("SELECT DISTINCT diak_nev FROM orarend WHERE diak_nev IS NOT NULL AND diak_nev != '' ORDER BY diak_nev")
        diakok = [r["diak_nev"] for r in cursor.fetchall()]

    if not diakok:
        conn.close()
        return "Nincs elérhető órarendi adat!", 404

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1.2*cm,
        leftMargin=1.2*cm,
        topMargin=1.0*cm,
        bottomMargin=1.0*cm
    )

    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'HeaderTitle',
        parent=styles['Heading1'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0d6efd'),
        alignment=0,
        spaceAfter=2,
        fontName=_pdf_font_bold()
    )
    
    subtitle_style = ParagraphStyle(
        'HeaderSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#6c757d'),
        alignment=0,
        spaceAfter=8,
        fontName=_pdf_font()
    )

    cell_time_style = ParagraphStyle(
        'CellTime',
        fontSize=8,
        leading=10,
        alignment=1,
        textColor=colors.HexColor('#333333'),
        fontName=_pdf_font()
    )

    cell_header_style = ParagraphStyle(
        'CellHeader',
        fontSize=10,
        leading=12,
        alignment=1,
        textColor=colors.white,
        fontName=_pdf_font_bold()
    )

    story = []

    days = ["hetfo", "kedd", "szerda", "csutortok", "pentek"]
    day_headers = ["Hétfő", "Kedd", "Szerda", "Csütörtök", "Péntek"]

    def get_subject_bg(tantargy_name):
        if not tantargy_name:
            return colors.HexColor('#f8f9fa')
        t = tantargy_name.lower()
        if any(x in t for x in ["szünet", "tanítási szünet", "ünnepnap", "rendkívüli"]):
            return colors.HexColor('#fff3cd')
        if any(x in t for x in ["matematika", "fizika", "kémia", "biológia", "informatika", "digitális"]):
            return colors.HexColor('#e7f1ff')
        if any(x in t for x in ["magyar", "irodalom", "nyelvtan", "történelem", "angol", "német"]):
            return colors.HexColor('#f0fff4')
        if any(x in t for x in ["testnevelés", "tesi"]):
            return colors.HexColor('#e8f5e9')
        if any(x in t for x in ["ének", "rajz", "vizuális", "technika", "dráma"]):
            return colors.HexColor('#f3e8ff')
        return colors.HexColor('#f8f9fa')

    for idx, d_nev in enumerate(diakok):
        if idx > 0:
            story.append(PageBreak())

        cursor.execute("""
            SELECT * FROM orarend 
            WHERE diak_nev = ? 
              AND (kezdo_idopont >= ? AND kezdo_idopont <= ? OR kezdo_idopont IS NULL OR kezdo_idopont = '')
            ORDER BY kezdo_idopont ASC
        """, (d_nev, hetfo_str, vasarnap_str + "T23:59:59"))
        rows = cursor.fetchall()

        all_day_map = {d: None for d in days}
        time_slots_dict = {}
        parsed_lessons = []
        has_all_day_event = False

        for r in rows:
            kezdo = r["kezdo_idopont"] or ""
            zaro = r["zaro_idopont"] or ""
            nap_raw = (r["nap"] or "").lower()

            day_key = None
            if "hétfő" in nap_raw or "hetfo" in nap_raw: day_key = "hetfo"
            elif "kedd" in nap_raw: day_key = "kedd"
            elif "szerda" in nap_raw: day_key = "szerda"
            elif "csütörtök" in nap_raw or "csutortok" in nap_raw: day_key = "csutortok"
            elif "péntek" in nap_raw or "pentek" in nap_raw: day_key = "pentek"
            
            if not day_key and len(kezdo) >= 10:
                try:
                    dt = datetime.strptime(kezdo[:10], "%Y-%m-%d")
                    w = dt.weekday()
                    if w < 5: day_key = days[w]
                except Exception:
                    pass

            if not day_key:
                continue

            k_time = kezdo.split("T")[1][:5] if "T" in kezdo and len(kezdo) >= 16 else ""
            z_time = zaro.split("T")[1][:5] if "T" in zaro and len(zaro) >= 16 else ""

            is_all_day = not k_time or "T" not in kezdo

            if is_all_day:
                has_all_day_event = True
                all_day_map[day_key] = {
                    "tantargy": r["tantargy"] or "",
                    "tanar": r["tanar"] or "",
                    "terem": r["terem"] or ""
                }
            else:
                slot_str = f"{k_time} - {z_time}" if z_time else k_time
                time_slots_dict[k_time] = slot_str

                parsed_lessons.append({
                    "day_key": day_key,
                    "slot_str": slot_str,
                    "k_time": k_time,
                    "tantargy": r["tantargy"] or "",
                    "tanar": r["tanar"] or "",
                    "terem": r["terem"] or ""
                })

        sorted_k_times = sorted(list(time_slots_dict.keys()))

        schedule_map = {time_slots_dict[kt]: {d: None for d in days} for kt in sorted_k_times}

        for item in parsed_lessons:
            slot = item["slot_str"]
            d_key = item["day_key"]
            if slot in schedule_map:
                schedule_map[slot][d_key] = item

        table_data = []
        header_row = [Paragraph("<b>Óra / Idő</b>", cell_header_style)] + [Paragraph(f"<b>{dh}</b>", cell_header_style) for dh in day_headers]
        table_data.append(header_row)

        table_styles = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]

        current_row_idx = 1

        if has_all_day_event:
            row = [Paragraph("<b>Egész napos</b><br/><font size=6.5 color='#666666'>esemény / szünet</font>", cell_time_style)]
            for d_col_idx, d_key in enumerate(days, start=1):
                cell_data = all_day_map.get(d_key)
                if cell_data:
                    tt = cell_data["tantargy"]
                    cell_html = f"<b><font size=8 color='#d97706'>{tt}</font></b>"
                    bg_c = get_subject_bg(tt)
                    table_styles.append(('BACKGROUND', (d_col_idx, current_row_idx), (d_col_idx, current_row_idx), bg_c))
                    p = Paragraph(cell_html, ParagraphStyle('CellContent', fontSize=8, leading=9.5, alignment=1, fontName=_pdf_font()))
                else:
                    p = Paragraph("<font color='#cccccc'>-</font>", cell_time_style)
                row.append(p)
            
            table_data.append(row)
            current_row_idx += 1

        for lesson_num, kt in enumerate(sorted_k_times, start=1):
            slot_name = time_slots_dict[kt]
            row = []
            time_p = Paragraph(f"<b>{lesson_num}. óra</b><br/><font size=7 color='#666666'>{slot_name}</font>", cell_time_style)
            row.append(time_p)

            for d_col_idx, d_key in enumerate(days, start=1):
                cell_data = schedule_map[slot_name].get(d_key)
                if cell_data:
                    tt = cell_data["tantargy"]
                    tr = cell_data["terem"]
                    tn = cell_data["tanar"]

                    cell_html = f"<b><font size=8 color='#0d6efd'>{tt}</font></b>"
                    if tr or tn:
                        sub_info = []
                        if tr: sub_info.append(f"<b>{tr}</b>")
                        if tn: sub_info.append(tn)
                        cell_html += f"<br/><font size=6.5 color='#555555'>{' • '.join(sub_info)}</font>"

                    bg_c = get_subject_bg(tt)
                    table_styles.append(('BACKGROUND', (d_col_idx, current_row_idx), (d_col_idx, current_row_idx), bg_c))
                    p = Paragraph(cell_html, ParagraphStyle('CellContent', fontSize=8, leading=9.5, alignment=1, fontName=_pdf_font()))
                else:
                    p = Paragraph("<font color='#cccccc'>-</font>", cell_time_style)

                row.append(p)

            table_data.append(row)
            current_row_idx += 1

        col_widths = [3.2*cm] + [4.8*cm]*5
        t = Table(table_data, colWidths=col_widths)
        t.setStyle(TableStyle(table_styles))

        header_p = Paragraph(f"Heti Órarend – {d_nev}", title_style)
        sub_p = Paragraph(f"Aktuális hét: {hetfo_str} – {vasarnap_str} | Generálva: {datetime.now().strftime('%Y.%m.%d. %H:%M')}", subtitle_style)

        story.append(header_p)
        story.append(sub_p)
        story.append(Spacer(1, 0.2*cm))
        story.append(t)

    conn.close()
    doc.build(story)

    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    filename = f"orarend_{diak if diak else 'osszes_gyerek'}.pdf"
    response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
    return response

@app.route("/api/naptar_esemenyek")
def api_naptar_esemenyek():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "")
    
    query = """
        SELECT * FROM esemenyek 
        WHERE esemeny_tipus IN ('Házi feladat', 'Bejelentett számonkérés')
          AND hatarido IS NOT NULL AND hatarido != '' AND hatarido != '-'
    """
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    mai_datum_str = datetime.now().strftime("%Y-%m-%d")

    events = []
    for r in rows:
        norm_date = normalize_date(r["hatarido"])
        if not norm_date:
            continue

        es_tipus = r["esemeny_tipus"]
        keys = r.keys()
        is_kesz = bool(r["kesz"]) if "kesz" in keys and r["kesz"] else False

        teljes_nev = r["diak_nev"] or "Ismeretlen"

        # Bejelentett számonkérés esetén a 'mod' mező értékét jelenítjük meg, ha rendelkezésre áll
        megjelenitendo_tipus = r["mod"] if (es_tipus == "Bejelentett számonkérés" and r["mod"] and r["mod"] != "-") else es_tipus

        title = f"{teljes_nev}: {r['tantargy']} - {megjelenitendo_tipus}"
        if es_tipus == 'Házi feladat' and is_kesz:
            title = f"✔ {title}"

        is_past = norm_date < mai_datum_str

        if es_tipus == 'Bejelentett számonkérés':
            color = "#f18b95" if is_past else "#dc3545"
        elif es_tipus == 'Házi feladat' and is_kesz:
            color = "#75c099" if is_past else "#198754"
        else:
            color = "#8bb9fe" if is_past else "#0d6efd"

        reszletek = []
        if r['tema'] and r['tema'] != '-': reszletek.append(f"Téma: {r['tema']}")
        if r['cim'] and r['cim'] != '-': reszletek.append(f"Cím: {r['cim']}")
        if r['tartalom'] and r['tartalom'] != '-': reszletek.append(f"{r['tartalom']}")
        leiras = " | ".join(reszletek) or "Nincs részletes leírás"

        events.append({
            "id": r["id"],
            "title": title,
            "start": norm_date,
            "color": color,
            "extendedProps": {
                "diak": teljes_nev,
                "tipus": es_tipus,
                "mod": r["mod"] or "-",
                "tantargy": r["tantargy"],
                "tanar": r["ertekelo"] or "-",
                "leiras": leiras,
                "kesz": is_kesz
            }
        })

    return jsonify(events)

@app.route("/api/esemeny/statusz", methods=["POST"])
def api_esemeny_statusz():
    data = request.json or {}
    esemeny_id = data.get("id")
    kesz = 1 if data.get("kesz") else 0

    if not esemeny_id:
        return jsonify({"status": "error", "message": "Hiányzó azonosító"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE esemenyek SET kesz = ? WHERE id = ?", (kesz, esemeny_id))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "kesz": kesz})

@app.route("/api/uzenetek")
def api_uzenetek():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "")
    query = "SELECT * FROM uzenetek WHERE 1=1"
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)

    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    komment_db = komment_szamok(cursor, "uzenet")

    uzenetek = []
    for r in rows:
        keys = r.keys()
        cs_nev = r["csatolmany_nev"] if "csatolmany_nev" in keys else ""
        cs_ut = r["csatolmany_utvonal"] if "csatolmany_utvonal" in keys else ""
        
        nyers_szoveg = r["szoveg"] if "szoveg" in keys and r["szoveg"] else ""
        tisztitott_szoveg = re.sub(r'\n{3,}', '\n\n', nyers_szoveg) if nyers_szoveg else ""
        kulcs = komment_kulcs_uzenet(r)

        uzenetek.append({
            "id": r["id"],
            "diak_nev": r["diak_nev"] if "diak_nev" in keys else "",
            "felado": r["felado"] if "felado" in keys else "-",
            "targy": r["targy"] if "targy" in keys else "-",
            "idopont": r["idopont"] if "idopont" in keys else "-",
            "szoveg": tisztitott_szoveg,
            "csatolmany_nev": cs_nev or "",
            "csatolmany_utvonal": cs_ut or "",
            "komment_kulcs": kulcs,
            "komment_db": int(komment_db.get(kulcs, 0))
        })

    conn.close()
    return jsonify(uzenetek)


# ==============================================================================
# === SAJÁT MEGJEGYZÉSEK (Kaneo #46) ===========================================
# ==============================================================================
@app.route("/api/kommentek")
def api_kommentek_list():
    """Egy esemény/üzenet saját megjegyzései (legrégebbi elöl)."""
    cel_tipus = (request.args.get("cel_tipus") or "").strip()
    cel_kulcs = (request.args.get("cel_kulcs") or "").strip()
    if cel_tipus not in KOMMENT_CEL_TIPUSOK or not cel_kulcs:
        return jsonify({"status": "error", "message": "Hiányzó vagy hibás cél."}), 400
    if not os.path.exists(DB_FILE):
        return jsonify([])
    try:
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, cel_tipus, cel_kulcs, diak_nev, szoveg, szerzo, letrehozva, modositva"
            " FROM kommentek WHERE cel_tipus = ? AND cel_kulcs = ? ORDER BY id",
            (cel_tipus, cel_kulcs),
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify([dict(r) for r in rows])


@app.route("/api/kommentek", methods=["POST"])
def api_kommentek_add():
    """Új saját megjegyzés hozzáfűzése."""
    data = request.get_json(silent=True) or {}
    cel_tipus = str(data.get("cel_tipus") or "").strip()
    cel_kulcs = str(data.get("cel_kulcs") or "").strip()
    szoveg = str(data.get("szoveg") or "").strip()
    diak_nev = str(data.get("diak_nev") or "").strip()[:120]
    szerzo = str(data.get("szerzo") or "").strip()[:60] or "Szülő"

    if cel_tipus not in KOMMENT_CEL_TIPUSOK:
        return jsonify({"status": "error", "message": "Ismeretlen cél-típus."}), 400
    if not cel_kulcs or len(cel_kulcs) > 80:
        return jsonify({"status": "error", "message": "Hiányzó vagy hibás cél-azonosító."}), 400
    if not szoveg:
        return jsonify({"status": "error", "message": "A megjegyzés nem lehet üres."}), 400
    if len(szoveg) > KOMMENT_MAX_HOSSZ:
        return jsonify({"status": "error",
                        "message": f"A megjegyzés legfeljebb {KOMMENT_MAX_HOSSZ} karakter lehet."}), 400
    if not os.path.exists(DB_FILE):
        return jsonify({"status": "error", "message": "Az adatbázis még nem létezik."}), 503
    try:
        conn = get_db_connection()
        ensure_run_tables(conn)   # a kommentek tábla migrációja (idempotens)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO kommentek (cel_tipus, cel_kulcs, diak_nev, szoveg, szerzo, letrehozva)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (cel_tipus, cel_kulcs, diak_nev or None, szoveg, szerzo, _now_iso()),
        )
        conn.commit()
        uj_id = cur.lastrowid
        conn.close()
    except sqlite3.Error as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "ok", "id": uj_id})


@app.route("/api/kommentek/<int:komment_id>", methods=["DELETE"])
def api_kommentek_delete(komment_id):
    """Saját megjegyzés törlése."""
    if not os.path.exists(DB_FILE):
        return jsonify({"status": "error", "message": "Nincs adatbázis."}), 404
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM kommentek WHERE id = ?", (komment_id,))
        torolve = cur.rowcount
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    if not torolve:
        return jsonify({"status": "error", "message": "Nincs ilyen megjegyzés."}), 404
    return jsonify({"status": "ok"})


# ==============================================================================
# === HIÁNYZÁSOK / KÉSÉSEK ÉS IGAZOLÁSOK API ===================================
# ==============================================================================
def _month_bounds(honap):
    """'ÉÉÉÉ-HH' -> (hónap első napja, utolsó napja) ISO alakban."""
    m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})\s*", honap or "")
    if not m:
        return None, None
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None, None
    first = f"{year:04d}-{month:02d}-01"
    next_month = f"{year + 1:04d}-01-01" if month == 12 else f"{year:04d}-{month + 1:02d}-01"
    last = (datetime.strptime(next_month, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    return first, last


def _is_keses(row):
    """Késés: van Perc érték, vagy a típus neve tartalmazza, hogy 'késés'."""
    if row.get("perc") is not None:
        return True
    return "késés" in str(row.get("mulasztas_tipus") or "").lower()


def hianyzas_osszesito(rows):
    """Havi/összesített mutatók a hiányzás-sorokból.

    A KRÉTA egy sora egy tanórát jelent (az 'Óra' oszlop a napon belüli
    órasorszám), ezért az órákat soronként 1-ként számoljuk. A tanórai célú
    jelzőt tároljuk, de a statisztikában nem különböztetjük meg.
    """
    o = {
        "hianyzas_db": 0,
        "igazolt_ora": 0,
        "igazolatlan_ora": 0,
        "keses_db": 0,
        "keses_perc": 0,
        "keses_igazolatlan_db": 0,
    }
    for r in rows:
        if _is_keses(r):
            o["keses_db"] += 1
            o["keses_perc"] += int(r.get("perc") or 0)
            if not int(r.get("igazolt") or 0):
                o["keses_igazolatlan_db"] += 1
            continue
        o["hianyzas_db"] += 1
        if int(r.get("igazolt") or 0):
            o["igazolt_ora"] += 1
        else:
            o["igazolatlan_ora"] += 1
    return o


def _date_range_from_request():
    """kezdo/zaro paraméter, vagy a honap=ÉÉÉÉ-HH paraméterből számolva."""
    kezdo = request.args.get("kezdo", "").strip()
    zaro = request.args.get("zaro", "").strip()
    if not kezdo and not zaro:
        kezdo, zaro = _month_bounds(request.args.get("honap", ""))
    return kezdo or None, zaro or None


def _tanev_from_request() -> str:
    """A `tanev` query param (Kaneo #40).

    Üres / ``all`` = **összes tanév** (visszafelé kompatibilis alap), ``current`` =
    a naptár szerinti aktuális tanév, egyébként a megadott érték (pl. ``2026/2027``).
    """
    raw = (request.args.get("tanev") or "").strip()
    if raw.lower() in ("", "all", "osszes", "összes"):
        return ""
    if raw.lower() == "current":
        return kreta_tanev.current_tanev()
    return raw


def _has_tanev_column(cursor, table: str) -> bool:
    try:
        return any(row[1] == "tanev" for row in cursor.execute(f"PRAGMA table_info({table})"))
    except sqlite3.Error:
        return False


@app.route("/api/tanevek")
def api_tanevek():
    """A DB-ben előforduló tanévek, az aktuális tanév és a határok (Kaneo #40)."""
    aktualis = kreta_tanev.current_tanev()
    empty = {"tanevek": [], "aktualis": aktualis, "hatarok": {}, "ismeretlen_db": 0,
             "allapot": {}}
    if not os.path.exists(DB_FILE):
        return jsonify(empty)

    conn = get_db_connection()
    cursor = conn.cursor()
    tanevek = set()
    ismeretlen = 0
    for table in ("esemenyek", "hianyzasok", "igazolasok", "uzenetek", "kifizetesek"):
        if not _has_tanev_column(cursor, table):
            continue
        try:
            rows = cursor.execute(
                f"SELECT tanev, COUNT(*) FROM {table} WHERE tanev IS NOT NULL GROUP BY tanev"
            ).fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            if row[0]:
                tanevek.add(row[0])
            else:
                ismeretlen += row[1]

    hatarok = {}
    for tanev in tanevek:
        kezd, veg = kreta_tanev.tanev_bounds(tanev)
        hatarok[tanev] = {
            "kezdo": kezd.isoformat() if kezd else "",
            "zaro": veg.isoformat() if veg else "",
        }
    # A tanév-állapotot (Kaneo #43) is visszaadjuk: nyitott/le zárt + időpont.
    allapot = kreta_tanev.tanev_allapotok(conn)
    conn.close()
    return jsonify({"tanevek": sorted(tanevek), "aktualis": aktualis,
                    "hatarok": hatarok, "ismeretlen_db": ismeretlen,
                    "allapot": allapot})


@app.route("/api/dashboard")
def api_dashboard():
    """Dashboard összesítők (Kaneo #38).

    - diákonkénti **tanulmányi átlag** (teljes időszak, súlyozva),
    - **zsebpénz-egyenleg**: a teljes időszak egyenlege mínusz a már kifizetett
      időszakok rögzített összegei (a maradék a „kifizetetlen”),
    - **igazolatlan hiányzás** órában (a hiányzások fül összesítőjével azonos logika).
    """
    empty = {"enabled": True, "diakok": [], "osszes_hatralevo": 0, "igazolatlan_ora": 0}
    if not os.path.exists(DB_FILE):
        return jsonify(empty)

    config = load_config()
    global_enable = config.get("ENABLE_REWARDS", True)
    rewards = config.get("REWARDS", {
        "jegy_5": 500, "jegy_4": 200, "jegy_3": 0, "jegy_2": -200, "jegy_1": -500,
        "dicseret": 500, "megrovas": -500, "lecke_hiany": -300, "felszereles_hiany": -300
    })
    keywords = config.get("KEYWORDS", {
        "dicseret": ["dicséret", "dicséretben", "kiemelkedő"],
        "megrovas": ["intő", "megrovás", "figyelmeztetés"],
        "lecke_hiany": ["házi feladat hiány", "házi hiány", "lecke hiány", "nem készített házi"],
        "felszereles_hiany": ["felszerelés hiány", "felszerelése hiányzott", "felszereléshiány"]
    })
    diak_param = request.args.get("diak", "")
    tanev_szuro = _tanev_from_request()
    tanev_clause = " AND tanev = ?" if tanev_szuro else ""
    tanev_vals = (tanev_szuro,) if tanev_szuro else ()

    conn = get_db_connection()
    cursor = conn.cursor()

    def jegy_atlag(nev):
        try:
            cursor.execute(
                "SELECT szam_ertek, suly_szazalek FROM esemenyek"
                " WHERE diak_nev = ? AND esemeny_tipus = 'Értékelés'" + tanev_clause,
                (nev,) + tanev_vals)
            rows = cursor.fetchall()
            has_suly = True
        except sqlite3.Error:
            cursor.execute(
                "SELECT szam_ertek FROM esemenyek"
                " WHERE diak_nev = ? AND esemeny_tipus = 'Értékelés'" + tanev_clause,
                (nev,) + tanev_vals)
            rows = cursor.fetchall()
            has_suly = False
        osszeg = 0
        db = 0
        suly_sum = 0
        sulyozott = 0.0
        for r in rows:
            val = r["szam_ertek"]
            if val not in (1, 2, 3, 4, 5):
                continue
            db += 1
            osszeg += val
            suly = (r["suly_szazalek"] if has_suly else 0) or 0
            if suly > 0:
                suly_sum += suly
                sulyozott += val * suly
        if not db:
            return None, 0
        return (round(sulyozott / suly_sum, 2) if suly_sum else round(osszeg / db, 2)), db

    def teljes_egyenleg(nev):
        """A teljes időszak zsebpénz-egyenlege (minden jegy és feljegyzés)."""
        total = 0
        cursor.execute(
            "SELECT szam_ertek FROM esemenyek"
            " WHERE diak_nev = ? AND esemeny_tipus = 'Értékelés'" + tanev_clause,
            (nev,) + tanev_vals)
        for r in cursor.fetchall():
            val = r["szam_ertek"]
            if val in (1, 2, 3, 4, 5):
                total += rewards.get(f"jegy_{val}", 0)
        cursor.execute(
            "SELECT cim, tartalom FROM esemenyek"
            " WHERE diak_nev = ? AND esemeny_tipus = 'Feljegyzés'" + tanev_clause,
            (nev,) + tanev_vals)
        for r in cursor.fetchall():
            text = f"{r['cim'] or ''} {r['tartalom'] or ''}".lower()
            for cat, kw_list in keywords.items():
                if any(kw in text for kw in kw_list):
                    total += rewards.get(cat, 0)
        return total

    def kifizetett_osszeg(nev):
        try:
            cursor.execute(
                "SELECT COALESCE(SUM(osszeg), 0) AS s FROM kifizetesek"
                " WHERE diak_nev = ? AND kifizetve = 1" + tanev_clause,
                (nev,) + tanev_vals)
            row = cursor.fetchone()
            return int(row["s"] or 0)
        except sqlite3.Error:
            return 0

    diakok = []
    osszes_hatralevo = 0
    for s in config.get("STUDENTS", []):
        nev = s.get("diak_nev")
        if not nev or (diak_param and nev != diak_param):
            continue
        atlag, jegy_db = jegy_atlag(nev)
        rewards_enabled = bool(global_enable) and bool(s.get("enable_rewards", True))
        teljes = teljes_egyenleg(nev) if rewards_enabled else 0
        fizetve = kifizetett_osszeg(nev) if rewards_enabled else 0
        hatralevo = teljes - fizetve
        osszes_hatralevo += hatralevo
        diakok.append({
            "diak": nev,
            "atlag": atlag,
            "jegy_db": jegy_db,
            "teljes_egyenleg": teljes,
            "kifizetve_osszeg": fizetve,
            "hatralevo": hatralevo,
            "rewards_enabled": rewards_enabled,
        })

    try:
        query = "SELECT * FROM hianyzasok WHERE 1=1"
        params = []
        if diak_param:
            query += " AND diak_nev = ?"
            params.append(diak_param)
        if tanev_szuro:
            query += " AND tanev = ?"
            params.append(tanev_szuro)
        cursor.execute(query, params)
        hianyzas_rows = [dict(r) for r in cursor.fetchall()]
        igazolatlan = hianyzas_osszesito(hianyzas_rows)["igazolatlan_ora"]
    except sqlite3.Error:
        igazolatlan = 0

    conn.close()
    return jsonify({
        "enabled": True,
        "diakok": diakok,
        "osszes_hatralevo": osszes_hatralevo,
        "igazolatlan_ora": igazolatlan,
    })


@app.route("/api/hianyzasok")
def api_hianyzasok():
    empty = {"rows": [], "osszesito": hianyzas_osszesito([])}
    if not os.path.exists(DB_FILE):
        return jsonify(empty)

    diak = request.args.get("diak", "")
    kezdo, zaro = _date_range_from_request()
    tanev = _tanev_from_request()

    query = "SELECT * FROM hianyzasok WHERE 1=1"
    params = []
    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    if tanev:
        query += " AND tanev = ?"
        params.append(tanev)
    if kezdo:
        query += " AND mulasztas_datum >= ?"
        params.append(kezdo)
    if zaro:
        query += " AND mulasztas_datum <= ?"
        params.append(zaro)
    query += " ORDER BY mulasztas_datum DESC, id DESC"

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
    except sqlite3.Error as e:
        print(f"[Hiányzások API] Olvasás nem sikerült: {e}")
        return jsonify(empty)

    for r in rows:
        r["igazolt"] = int(r.get("igazolt") or 0)
        r["ora_sorszam"] = int(r.get("ora_sorszam") or 0)
        r["keses"] = 1 if _is_keses(r) else 0
    return jsonify({"rows": rows, "osszesito": hianyzas_osszesito(rows)})


@app.route("/api/igazolasok")
def api_igazolasok():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    diak = request.args.get("diak", "")
    kezdo, zaro = _date_range_from_request()
    tanev = _tanev_from_request()

    query = "SELECT * FROM igazolasok WHERE 1=1"
    params = []
    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    if tanev:
        query += " AND tanev = ?"
        params.append(tanev)
    # A hónaphoz kapcsolódó igazolások: az intervallum metszi a hónapot.
    if kezdo:
        query += " AND (vege IS NULL OR vege = '' OR vege >= ?)"
        params.append(kezdo)
    if zaro:
        query += " AND (kezdete IS NULL OR kezdete = '' OR kezdete <= ?)"
        params.append(zaro)
    query += " ORDER BY kezdete DESC, id DESC"

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
    except sqlite3.Error as e:
        print(f"[Igazolások API] Olvasás nem sikerült: {e}")
        return jsonify([])
    return jsonify(rows)

def normalize_date(d_str):
    if not d_str or d_str == "-":
        return None
    clean = d_str.replace(". ", "-").replace(".", "-").strip()
    parts = [p for p in clean.split("-") if p]
    if len(parts) >= 3:
        try:
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        except ValueError:
            return None
    return None

@app.route("/api/atlagok")
def api_atlagok():
    """Tantárgyankénti tanulmányi átlagok, havi bontással (Kaneo #39).

    A súlyozás ugyanaz, mint a statisztikában: Σ(jegy×súly)/Σ(súly), a 0%-os
    súlyú jegy kimarad; súlyadat nélkül egyszerű átlag.
    """
    if not os.path.exists(DB_FILE):
        return jsonify({"honapok": [], "tantargyak": [], "osszes": {"atlag": None, "db": 0}})

    diak = request.args.get("diak", "")
    kezdo_datum = request.args.get("kezdo_datum", "")
    zaro_datum = request.args.get("zaro_datum", "")
    tanev_szuro = _tanev_from_request()

    conn = get_db_connection()
    cursor = conn.cursor()
    query = ("SELECT tantargy, ertek, szam_ertek, bej_datum, suly_szazalek,"
             " ertekelo, tema, mod FROM esemenyek WHERE esemeny_tipus = 'Értékelés'")
    params = []
    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    if tanev_szuro:
        query += " AND tanev = ?"
        params.append(tanev_szuro)
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        has_suly = True
    except sqlite3.Error:
        # Régi DB, ahol még nincs suly_szazalek oszlop.
        cursor.execute(query.replace(", suly_szazalek ", " "), params)
        rows = cursor.fetchall()
        has_suly = False
    conn.close()

    def summarize(items):
        """[{val, suly, ...}] -> {atlag, db, jegyek} (súlyozva, ha van súly)."""
        if not items:
            return {"atlag": None, "db": 0, "jegyek": []}
        osszeg = 0
        suly_sum = 0
        sulyozott = 0.0
        jegyek = []
        for it in items:
            val = it["val"]
            suly = it["suly"]
            osszeg += val
            if suly and suly > 0:
                suly_sum += suly
                sulyozott += val * suly
            jegyek.append({
                "datum": it["datum"],
                "ertek": it["ertek"],
                "szam": val,
                "suly": suly,
                "tema": it["tema"],
                "tanar": it["tanar"],
                "mod": it["mod"],
            })
        atlag = round(sulyozott / suly_sum, 2) if suly_sum else round(osszeg / len(items), 2)
        jegyek.sort(key=lambda j: j["datum"], reverse=True)
        return {"atlag": atlag, "db": len(items), "jegyek": jegyek}

    per_tantargy = {}
    per_honap = {}
    honapok = set()
    mind = []

    for r in rows:
        val = r["szam_ertek"]
        if val not in (1, 2, 3, 4, 5):
            continue
        norm = normalize_date(r["bej_datum"])
        if norm:
            if kezdo_datum and norm < kezdo_datum:
                continue
            if zaro_datum and norm > zaro_datum:
                continue
        honap = norm[:7] if norm else "ismeretlen"
        if honap != "ismeretlen":
            honapok.add(honap)
        suly = (r["suly_szazalek"] if has_suly else 0) or 0
        tantargy = (r["tantargy"] or "Egyéb").strip()
        item = {
            "val": val,
            "suly": suly,
            "datum": norm or (r["bej_datum"] or ""),
            "ertek": r["ertek"] or "",
            "tema": r["tema"] or "",
            "tanar": r["ertekelo"] or "",
            "mod": r["mod"] or "",
        }
        entry = per_tantargy.setdefault(tantargy, {"honapok": {}, "mind": []})
        entry["honapok"].setdefault(honap, []).append(item)
        entry["mind"].append(item)
        per_honap.setdefault(honap, []).append(item)
        mind.append(item)

    tantargyak = []
    for tantargy in sorted(per_tantargy):
        entry = per_tantargy[tantargy]
        tantargyak.append({
            "tantargy": tantargy,
            "honapok": {h: summarize(v) for h, v in entry["honapok"].items()},
            "osszes": summarize(entry["mind"]),
        })

    def summarize_light(items):
        """Csak az átlag + darabszám (a havi teljes átlagokhoz, jegyek nélkül)."""
        r = summarize(items)
        return {"atlag": r["atlag"], "db": r["db"]}

    return jsonify({
        "honapok": sorted(honapok),
        "tantargyak": tantargyak,
        # Havi TELJES átlag (minden tantárgy együtt) - a fa középső szintje.
        "honap_osszes": {h: summarize_light(v) for h, v in sorted(per_honap.items())},
        "osszes": summarize_light(mind),
        "tanev": tanev_szuro,
        "aktualis_tanev": kreta_tanev.current_tanev(),
    })


@app.route("/api/statisztika")
def api_statisztika():
    config = load_config()
    global_enable = config.get("ENABLE_REWARDS", True)

    # A statisztika akkor is működik, ha a zsebpénz modul ki van kapcsolva:
    # ilyenkor csak a pénz-összegek maradnak 0-n, és a felület jelzi a tényt.
    if not os.path.exists(DB_FILE):
        return jsonify({"enabled": False})

    diak = request.args.get("diak", "")
    kezdo_datum = request.args.get("kezdo_datum", "")
    zaro_datum = request.args.get("zaro_datum", "")
    tanev_szuro = _tanev_from_request()

    student_enable = True
    students = config.get("STUDENTS", [])
    for s in students:
        if s.get("diak_nev") == diak:
            student_enable = s.get("enable_rewards", True)
            break

    rewards_enabled = bool(global_enable) and bool(student_enable)

    rewards = config.get("REWARDS", {
        "jegy_5": 500, "jegy_4": 200, "jegy_3": 0, "jegy_2": -200, "jegy_1": -500,
        "dicseret": 500, "megrovas": -500, "lecke_hiany": -300, "felszereles_hiany": -300
    })

    keywords = config.get("KEYWORDS", {
        "dicseret": ["dicséret", "dicséretben", "kiemelkedő"],
        "megrovas": ["intő", "megrovás", "figyelmeztetés"],
        "lecke_hiany": ["házi feladat hiány", "házi hiány", "lecke hiány", "nem készített házi"],
        "felszereles_hiany": ["felszerelés hiány", "felszerelése hiányzott", "felszereléshiány"]
    })

    conn = get_db_connection()
    cursor = conn.cursor()

    # JEGYEK LEKÉRDEZÉSE ÉS TÉTELES LISTÁJA
    jegy_query = "SELECT id, tantargy, ertek, szam_ertek, bej_datum, mod, tema FROM esemenyek WHERE esemeny_tipus = 'Értékelés'"
    params = []
    if diak:
        jegy_query += " AND diak_nev = ?"
        params.append(diak)
    if tanev_szuro:
        jegy_query += " AND tanev = ?"
        params.append(tanev_szuro)

    cursor.execute(jegy_query, params)
    jegy_rows = cursor.fetchall()

    # A súlyszázalék csak az API-s szinkronból van meg; régi DB-ben lehet, hogy
    # még nincs oszlop, ezért a SELECT *-ot nem használjuk, hanem külön kérdezzük.
    jegy_suly = {}
    try:
        cursor.execute(
            "SELECT id, suly_szazalek FROM esemenyek WHERE esemeny_tipus = 'Értékelés'"
            + (" AND diak_nev = ?" if diak else ""),
            params,
        )
        jegy_suly = {row["id"]: (row["suly_szazalek"] or 0) for row in cursor.fetchall()}
    except sqlite3.Error:
        jegy_suly = {}

    jegy_counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
    jegy_sum = 0
    jegy_total_count = 0
    # Súlyozott átlaghoz (a KRÉTA SulySzazalekErteke / webes "Súly: N%" mezője).
    suly_sum = 0
    sulyozott_sum = 0.0
    sulyozott_db = 0
    teteles_lista = []

    for r in jegy_rows:
        norm_d = normalize_date(r["bej_datum"])
        if norm_d:
            if kezdo_datum and norm_d < kezdo_datum:
                continue
            if zaro_datum and norm_d > zaro_datum:
                continue

        val = r["szam_ertek"]
        if val in jegy_counts:
            jegy_counts[val] += 1
            jegy_sum += val
            jegy_total_count += 1

            suly = jegy_suly.get(r["id"], 0)
            if suly > 0:
                suly_sum += suly
                sulyozott_sum += val * suly
                sulyozott_db += 1

            jutalom = rewards.get(f"jegy_{val}", 0) if rewards_enabled else 0
            reszletek = f"{r['mod'] or ''} {r['tema'] or ''}".strip()
            if suly:
                reszletek = f"{reszletek} ({suly}%)".strip()
            teteles_lista.append({
                "datum": r["bej_datum"],
                "tipus": "Értékelés",
                "megnevezes": f"{r['tantargy']} - {r['ertek']}",
                "reszletek": reszletek,
                "osszeg": jutalom
            })

    # Tanulmányi átlag: ha van súlyszázalék, a KRÉTA logikája szerint súlyozva
    # (súlyozott összeg / súlyösszeg); a 0%-os súlyú jegy nem számít bele. Ha
    # egyetlen jegynek sincs súlya (régi adat / Playwright nélküli súly), akkor
    # a hagyományos egyszerű átlagot adjuk.
    atlag_egyszeru = round(jegy_sum / jegy_total_count, 2) if jegy_total_count > 0 else 0.0
    atlag_sulyozott = round(sulyozott_sum / suly_sum, 2) if suly_sum > 0 else None
    atlag = atlag_sulyozott if atlag_sulyozott is not None else atlag_egyszeru

    # FELJEGYZÉSEK LEKÉRDEZÉSE ÉS TÉTELES LISTÁJA
    felj_query = "SELECT id, bej_datum, tipus, cim, tartalom FROM esemenyek WHERE esemeny_tipus = 'Feljegyzés'"
    f_params = []
    if diak:
        felj_query += " AND diak_nev = ?"
        f_params.append(diak)
    if tanev_szuro:
        felj_query += " AND tanev = ?"
        f_params.append(tanev_szuro)

    cursor.execute(felj_query, f_params)
    felj_rows = cursor.fetchall()

    counts = {
        "dicseret": 0,
        "megrovas": 0,
        "lecke_hiany": 0,
        "felszereles_hiany": 0
    }

    cat_names = {
        "dicseret": "Dicséret",
        "megrovas": "Intő / Megrovás",
        "lecke_hiany": "Lecke hiány",
        "felszereles_hiany": "Felszerelés hiány"
    }

    for r in felj_rows:
        norm_d = normalize_date(r["bej_datum"])
        if norm_d:
            if kezdo_datum and norm_d < kezdo_datum:
                continue
            if zaro_datum and norm_d > zaro_datum:
                continue

        text = f"{r['cim'] or ''} {r['tartalom'] or ''}".lower()

        for cat, kw_list in keywords.items():
            if any(kw in text for kw in kw_list):
                counts[cat] += 1
                jutalom = rewards.get(cat, 0) if rewards_enabled else 0
                teteles_lista.append({
                    "datum": r["bej_datum"],
                    "tipus": "Feljegyzés",
                    "megnevezes": cat_names.get(cat, "Feljegyzés"),
                    "reszletek": f"{r['cim'] or ''} {r['tartalom'] or ''}".strip(),
                    "osszeg": jutalom
                })

    kifizetve = False
    if diak and kezdo_datum and zaro_datum:
        cursor.execute("""
            SELECT kifizetve FROM kifizetesek 
            WHERE diak_nev = ? AND kezdo_datum = ? AND zaro_datum = ?
        """, (diak, kezdo_datum, zaro_datum))
        k_row = cursor.fetchone()
        if k_row:
            kifizetve = bool(k_row["kifizetve"])

    conn.close()

    teteles_lista.sort(key=lambda x: x["datum"], reverse=True)

    if rewards_enabled:
        jegy_osszeg = (
            jegy_counts[5] * rewards.get("jegy_5", 0) +
            jegy_counts[4] * rewards.get("jegy_4", 0) +
            jegy_counts[3] * rewards.get("jegy_3", 0) +
            jegy_counts[2] * rewards.get("jegy_2", 0) +
            jegy_counts[1] * rewards.get("jegy_1", 0)
        )

        feljegyzes_osszeg = (
            counts["dicseret"] * rewards.get("dicseret", 0) +
            counts["megrovas"] * rewards.get("megrovas", 0) +
            counts["lecke_hiany"] * rewards.get("lecke_hiany", 0) +
            counts["felszereles_hiany"] * rewards.get("felszereles_hiany", 0)
        )
    else:
        jegy_osszeg = 0
        feljegyzes_osszeg = 0

    vegosszeg = jegy_osszeg + feljegyzes_osszeg

    return jsonify({
        "enabled": True,
        "rewards_enabled": rewards_enabled,
        "jegy_counts": jegy_counts,
        "atlag": atlag,
        "atlag_egyszeru": atlag_egyszeru,
        "atlag_sulyozott": atlag_sulyozott,
        "sulyozott_db": sulyozott_db,
        "jegy_total_count": jegy_total_count,
        "counts": counts,
        "rewards": rewards,
        "jegy_osszeg": jegy_osszeg,
        "feljegyzes_osszeg": feljegyzes_osszeg,
        "vegosszeg": vegosszeg,
        "kifizetve": kifizetve,
        "teteles_lista": teteles_lista
    })

@app.route("/api/kifizetes", methods=["POST"])
def api_kifizetes_save():
    data = request.json or {}
    diak = data.get("diak", "")
    kezdo_datum = data.get("kezdo_datum", "")
    zaro_datum = data.get("zaro_datum", "")
    kifizetve = 1 if data.get("kifizetve") else 0
    osszeg = data.get("osszeg", 0)

    if not diak or not kezdo_datum or not zaro_datum:
        return jsonify({"status": "error", "message": "Hiányzó paraméterek"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    # A kifizetés tanéve az időszak kezdetéből (Kaneo #40): enélkül a
    # `?tanev=` szűrt dashboard nem venné figyelembe a frissen kifizetett összeget.
    tanev = kreta_tanev.tanev_of(kezdo_datum)
    cursor.execute("""
        INSERT INTO kifizetesek (diak_nev, kezdo_datum, zaro_datum, kifizetve, osszeg,
                                 tanev, tanev_forras, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'szamitott', CURRENT_TIMESTAMP)
        ON CONFLICT(diak_nev, kezdo_datum, zaro_datum) DO UPDATE SET
            kifizetve = excluded.kifizetve,
            osszeg = excluded.osszeg,
            tanev = CASE WHEN ? <> '' THEN excluded.tanev ELSE kifizetesek.tanev END,
            tanev_forras = CASE WHEN ? <> '' THEN excluded.tanev_forras
                                ELSE kifizetesek.tanev_forras END,
            updated_at = CURRENT_TIMESTAMP
    """, (diak, kezdo_datum, zaro_datum, kifizetve, osszeg, tanev, tanev, tanev))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "kifizetve": bool(kifizetve)})

@app.route("/api/sync/start", methods=["POST"])
def api_sync_start():
    if not start_sync("manual"):
        return jsonify({"status": "already_running", "message": "A szinkronizáció már fut!"})
    return jsonify({"status": "started", "message": "Szinkronizáció elindítva."})

@app.route("/api/sync/stop", methods=["POST"])
def api_sync_stop():
    global sync_state
    with sync_lock:
        if not sync_state["running"] or not sync_state["process"]:
            return jsonify({"status": "not_running", "message": "Nincs futó folyamat."})

        try:
            sync_state["process"].kill()
            sync_state["status"] = "stopped"
            sync_state["logs"].append("> SZINKRONIZÁLÁS A FELHASZNÁLÓ ÁLTAL LEÁLLÍTVA!")
            return jsonify({"status": "stopped", "message": "Folyamat leállítva."})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Hiba a leállításkor: {str(e)}"})

@app.route("/api/sync/status")
def api_sync_status():
    # Figyelem: a scheduler_status() maga is fogja a sync_lock-ot, ezért ELŐBB
    # hívjuk, és csak utána lépünk be a lock alá (a Lock nem újrabeléphető).
    sched = scheduler_status()
    with sync_lock:
        payload = {
            "running": sync_state["running"],
            "status": sync_state["status"],
            "trigger": sync_state.get("trigger"),
            "tanev": kreta_tanev.current_tanev(),
            "failed_students": list(sync_state.get("failed_students") or []),
            "sources": dict(sync_state.get("sources") or {}),
            "logs": list(sync_state["logs"]),
        }
    payload["scheduler"] = sched
    return jsonify(payload)

@app.route("/api/scheduler/status")
def api_scheduler_status():
    """
    Könnyű végpont a fejléc "Következő automatikus szinkron" feliratához —
    a /api/sync/status-tól eltérően nem küldi át a teljes log tömböt.
    """
    return jsonify(scheduler_status())

# ==============================================================================
# === SYNC.LOG KEZELŐ API VÉGPONTOK ===
# ==============================================================================
@app.route("/api/logs")
def api_get_logs():
    """Visszaadja a sync.log végét (a teljes fájl helyett, hogy ne nőjön a válasz)."""
    if not os.path.exists(LOG_FILE):
        return jsonify({"status": "ok", "content": "A sync.log fájl még nem létezik."})
    
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size > LOG_API_MAX_BYTES:
                f.seek(size - LOG_API_MAX_BYTES)
                f.readline()  # az első, csonka sor eldobása
                content = "…(a napló eleje levágva, az utolsó " + str(LOG_API_MAX_BYTES) + " bájt)…\n" + f.read()
            else:
                f.seek(0)
                content = f.read()
        return jsonify({"status": "ok", "content": content if content else "A sync.log fájl üres."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/logs/clear", methods=["POST"])
def api_clear_logs():
    """Kiüríti a sync.log fájlt."""
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("")
        return jsonify({"status": "ok", "message": "A sync.log sikeresen kiürítve."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/static/csatolmanyok/<path:filename>")
def download_csatolmany(filename):
    # A DB-ben tárolt érték történetileg több formátumban szerepelt
    # ("static/csatolmanyok/...", "/app/data/csatolmanyok/...", tiszta
    # "diak/fajl.pdf") — a biztonság kedvéért (régi gyorsítótárazott oldalak,
    # kézzel írt linkek) mindegyikből a tiszta relatív nevet állítjuk elő,
    # a safe_join ezt illeszti a CSATOLMANYOK_DIR alá.
    filename = re.sub(r"^.*?csatolmanyok/", "", filename)
    filename = filename.lstrip("/")
    return send_from_directory(CSATOLMANYOK_DIR, filename)

@app.route("/health")
def health():
    """Docker healthcheck végpont."""
    return jsonify({"status": "ok", "version": get_app_version()})


@app.route("/api/ntfy/test", methods=["POST"])
def api_ntfy_test():
    """Teszt-push az ntfy csatornára (beállítás-ellenőrzés).

    Válasz: `configured` (van-e topic), `url`, `topic` és a küldés eredménye.
    Ha nincs topic, 400 — így rögtön látszik, hogy a config/env hiányos.
    """
    if not NTFY_TOPIC:
        return jsonify({
            "ok": False, "configured": False,
            "message": "Nincs ntfy topic beállítva: config.json → NTFY.TOPIC "
                       "vagy NTFY_TOPIC környezeti változó.",
        }), 400
    url, topic = _ntfy_target()
    payload = json.dumps({
        "topic": topic,
        "title": "KRÉTA – teszt értesítés",
        "message": f"Teszt push innen: {os.environ.get('COMPUTERNAME') or 'dev'}",
        "priority": 3,
        "tags": ["white_check_mark"],
    }, ensure_ascii=False).encode("utf-8")
    try:
        status = _http_post_ntfy(url, payload,
                                 {"Content-Type": "application/json; charset=utf-8"},
                                 NTFY_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — hálózati/időtúllépés bármi lehet
        return jsonify({"ok": False, "configured": True, "url": url, "topic": topic,
                        "error": f"{type(exc).__name__}: {exc}"}), 502
    return jsonify({"ok": status == 200, "configured": True, "url": url,
                    "topic": topic, "status": status})

if __name__ == "__main__":
    host = os.environ.get("KRETA_HOST", "127.0.0.1")
    port = int(os.environ.get("KRETA_PORT", "5000"))
    debug = os.environ.get("KRETA_DEBUG", "0") == "1"
    # Windows-on két process is listenelhet ugyanarra a portra (SO_REUSEADDR):
    # ilyenkor a böngésző a RÉGI példányt éri el, és érthetetlen hibák jönnek.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError:
        print(f"HIBA: a(z) {port} port már foglalt — valószínűleg fut egy másik példány.")
        print("      Zárd be a régi ablakot (vagy állítsd a KRETA_PORT környezeti változót),")
        print("      különben a böngésző a régi kódot és a régi adatbázist szolgálja ki.")
        sys.exit(1)
    finally:
        probe.close()
    print(f"Web szerver indítása: http://{host}:{port}")
    # Az ütemezőt csak egyszer indítjuk: debug módban a reloader két processzt
    # futtat, ezért ott csak a gyerek-processzben (WERKZEUG_RUN_MAIN) indul.
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_scheduler()

    # Élesben waitress (a Flask dev szerver csak fejlesztésre való).
    # KRETA_SERVER=waitress a compose-ban; lokálisan marad a Flask dev szerver.
    server = os.environ.get("KRETA_SERVER", "flask").lower()
    if server == "waitress" and not debug:
        try:
            from waitress import serve
            threads = int(os.environ.get("KRETA_WAITRESS_THREADS", "8"))
            print(f"Waitress produkciós szerver indítása ({threads} szál)...")
            serve(app, host=host, port=port, threads=threads)
        except ImportError:
            print("[Figyelmeztetés] A waitress nincs telepítve — Flask dev szerverrel indul.")
            app.run(host=host, port=port, debug=debug, threaded=True)
    else:
        app.run(host=host, port=port, debug=debug, threaded=True)
