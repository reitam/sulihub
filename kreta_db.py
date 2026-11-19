# -*- coding: utf-8 -*-
"""
Adatbázis-réteg (KRÉ-14 #93): kapcsolat, séma, migrációk, meta, futásnapló.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. A route-ok és a futásidejű
mag (sync/ütemező/ntfy) továbbra is az `app.py`-ban él; ez a modul csak a DB-t
ismeri. **Nem importálhatja az `app`-ot** (körkörös import lenne).

A modul importálásakor lefut a szokásos induló séma-ellenőrzés (ugyanaz, ami
eddig az `app.py` végén, a route-ok előtt történt).
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime

import kreta_sajat_orarend
import kreta_tanev
from kreta_paths import APP_DIR, DATA_DIR, DB_FILE, SCHEDULER_STATE_FILE

# WAL: csak opt-in, lásd enable_wal() — a data kötet FUSE mount.
SQLITE_WAL = os.environ.get("KRETA_SQLITE_WAL", "0").strip().lower() in ("1", "true", "yes", "on")


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
SCHEMA_VERSION = 5
CORE_TABLES = SCRAPER_TABLES + APP_OWN_TABLES
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
    init_db_extensions()
    return True

# ==============================================================================
# === FUTÁS-NAPLÓ (sync_runs) ÉS ALKALMAZÁS-META (app_meta) =====================
# ==============================================================================
# Korábban a "legutóbbi futás" egy scheduler_state.json fájlban élt (olvasd-
# módosítsd-írd vissza, felülírással). Mostantól minden futás egy sor a DB-ben:
# van történet, tranzakció-védelem, és a mentés is DB-szintű.
SYNC_RUNNING_STATUS = "running"

# FTS5 (Kaneo #107): (alaptábla, FTS-tábla, oszlopok) — trigram tokenizálóval,
# hogy az infix keresés is működjön (a LIKE-kal azonos találatok).
FTS_TABLAK = (
    ("esemenyek", "esemenyek_fts",
     ("diak_nev", "tantargy", "tema", "cim", "tartalom", "ertek")),
    ("uzenetek", "uzenetek_fts", ("diak_nev", "felado", "targy", "szoveg")),
)


def ensure_fts_schema(conn):
    """FTS5 táblák + szinkron-triggerek létrehozása, szükség esetén rebuild (idempotens)."""
    cur = conn.cursor()
    for alap, fts, oszlopok in FTS_TABLAK:
        volt = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?", (fts,)).fetchone() is not None
        try:
            cur.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {fts} USING fts5("
                f"{', '.join(oszlopok)}, content='{alap}', content_rowid='id', "
                f"tokenize='trigram')")
        except sqlite3.Error as exc:
            print(f"[FTS] {fts} kihagyva ({exc}) — a keresés LIKE-kal megy tovább.")
            continue

        oszlop_lista = ", ".join(oszlopok)
        uj_ertekek = ", ".join(f"new.{o}" for o in oszlopok)
        regi_ertekek = ", ".join(f"old.{o}" for o in oszlopok)
        try:
            cur.execute(
                f"CREATE TRIGGER IF NOT EXISTS {alap}_fts_ai AFTER INSERT ON {alap} BEGIN "
                f"INSERT INTO {fts}(rowid, {oszlop_lista}) VALUES (new.id, {uj_ertekek}); END")
            cur.execute(
                f"CREATE TRIGGER IF NOT EXISTS {alap}_fts_ad AFTER DELETE ON {alap} BEGIN "
                f"INSERT INTO {fts}({fts}, rowid, {oszlop_lista}) "
                f"VALUES ('delete', old.id, {regi_ertekek}); END")
            cur.execute(
                f"CREATE TRIGGER IF NOT EXISTS {alap}_fts_au AFTER UPDATE ON {alap} BEGIN "
                f"INSERT INTO {fts}({fts}, rowid, {oszlop_lista}) "
                f"VALUES ('delete', old.id, {regi_ertekek}); "
                f"INSERT INTO {fts}(rowid, {oszlop_lista}) VALUES (new.id, {uj_ertekek}); END")
        except sqlite3.Error as exc:
            print(f"[FTS] {alap} triggerek kihagyva ({exc})")

        try:
            # External-content FTS-nél a COUNT(*) a tartalmi táblát olvassa,
            # ezért az indexelt dokumentumok számát a _docsize táblából vesszük.
            n_idx = cur.execute(f"SELECT COUNT(*) FROM {fts}_docsize").fetchone()[0]
            n_alap = cur.execute(f"SELECT COUNT(*) FROM {alap}").fetchone()[0]
            if n_alap and (not volt or n_idx != n_alap):
                cur.execute(f"INSERT INTO {fts}({fts}) VALUES('rebuild')")
                print(f"[FTS] {fts} újraépítve ({n_alap} sor)")
        except sqlite3.Error as exc:
            print(f"[FTS] {fts} rebuild kihagyva ({exc})")


def _migracio_4(conn):
    """v4: FTS5 index (Kaneo #107) — idempotens."""
    ensure_fts_schema(conn)


def _migracio_5(conn):
    """v5: a saját DB-be kerülés időpontja (#147) — idempotens.

    A logika a `kreta_tanev`-ben él, hogy a scraper (`init_db`) és a Flask
    migrációs lánca ugyanazt használja, körkörös import nélkül.
    """
    kreta_tanev.ensure_first_seen_schema(conn)


# Verziózott migrációs lánc (Kaneo #91). A meglévő oszlop-hozzáadásokat az
# idempotens init_db_extensions végzi (base séma), az új változások ide jönnek.
MIGRATIONS = [
    (4, _migracio_4),
    (5, _migracio_5),
]


def run_migrations(conn, backup=True):
    """A `schema_version`-nél újabb migrációk futtatása, idempotensen (Kaneo #91)."""
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT,"
                " updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    row = cur.execute(
        "SELECT value FROM app_meta WHERE key = 'schema_version'").fetchone()
    try:
        current = int(row[0]) if row and str(row[0]).isdigit() else 0
    except (TypeError, ValueError):
        current = 0
    if current >= SCHEMA_VERSION:
        return current
    if backup and current > 0:
        backup_path = f"{DB_FILE}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        try:
            dst = sqlite3.connect(backup_path)
            conn.backup(dst)
            dst.close()
            print(f"[Migráció] DB-másolat: {backup_path}")
        except sqlite3.Error as exc:
            print(f"[Migráció] A DB-másolat nem sikerült: {exc}")
    for version, fn in MIGRATIONS:
        if version <= current:
            continue
        try:
            fn(conn)
            cur.execute(
                "INSERT OR REPLACE INTO app_meta (key, value, updated_at) VALUES (?,?,?)",
                ("schema_version", str(version),
                 datetime.now().replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")))
            conn.commit()
            print(f"[Migráció] séma v{version} kész")
        except sqlite3.Error as exc:
            print(f"[Migráció] v{version} kihagyva: {exc}")
            conn.rollback()
            break
    return SCHEMA_VERSION


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

            # Migráció előtti automatikus DB-másolat (Kaneo #15).
            try:
                row = cursor.execute(
                    "SELECT value FROM app_meta WHERE key = 'schema_version'").fetchone()
                current_version = int(row[0]) if row and str(row[0]).isdigit() else 0
            except (sqlite3.Error, TypeError, ValueError):
                current_version = 0
            if 0 < current_version < SCHEMA_VERSION:
                backup_path = f"{DB_FILE}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                try:
                    dst = sqlite3.connect(backup_path)
                    conn.backup(dst)
                    dst.close()
                    print(f"[Migráció] DB-másolat: {backup_path}")
                except sqlite3.Error as exc:
                    print(f"[Migráció] A DB-másolat nem sikerült: {exc}")

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

            # Üzenetek: a postalada-elem azonosítója (#74) + helyi olvasott állapot (#11).
            cursor.execute("PRAGMA table_info(uzenetek)")
            uzenet_cols = [row["name"] for row in cursor.fetchall()]
            if uzenet_cols and "posta_id" not in uzenet_cols:
                cursor.execute("ALTER TABLE uzenetek ADD COLUMN posta_id TEXT")
                print("[Adatbázis séma frissítve]: 'posta_id' oszlop hozzáadva az 'uzenetek' táblához.")
            if uzenet_cols and "olvasott" not in uzenet_cols:
                cursor.execute("ALTER TABLE uzenetek ADD COLUMN olvasott INTEGER DEFAULT 0")
                # A migráció előtt mentett (történeti) üzenetek ne jelenjenek meg
                # olvasatlanként — a felhasználó ezeket már látta (Kaneo #11).
                cursor.execute("UPDATE uzenetek SET olvasott = 1")
                print("[Adatbázis séma frissítve]: 'olvasott' oszlop hozzáadva az 'uzenetek' táblához"
                      " (a meglévő üzenetek olvasottként indulnak).")

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

            # Saját (kézi) órarendi tételek — Kaneo #55. A szinkron nem érinti.
            kreta_sajat_orarend.ensure_schema(conn)

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

            # Gyakori lekérdezések indexei (Kaneo #15). Idempotens, régi DB-n is fut.
            indexes = [
                ("idx_esemenyek_diak_hatarido", "esemenyek(diak_nev, hatarido)"),
                ("idx_esemenyek_diak_bej", "esemenyek(diak_nev, bej_datum)"),
                ("idx_esemenyek_tanev", "esemenyek(tanev)"),
                ("idx_uzenetek_diak_idopont", "uzenetek(diak_nev, idopont)"),
                ("idx_uzenetek_tanev", "uzenetek(tanev)"),
                ("idx_kifizetesek_diak", "kifizetesek(diak_nev)"),
                ("idx_sync_runs_started", "sync_runs(started_at)"),
            ]
            for index_name, target in indexes:
                try:
                    cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {target}")
                except sqlite3.Error as exc:
                    print(f"[Index] {index_name} kihagyva: {exc}")
            # FTS5 keresőindexek (Kaneo #107); hiba esetén a LIKE marad.
            ensure_fts_schema(conn)

            # Verziózott migrációs lánc (Kaneo #91) — a sémaverziót lépteti.
            # A .bak mentés már fentebb megtörtént (ne készüljön dupla).
            run_migrations(conn, backup=False)

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Adatbázis inicializálási figyelmeztetés]: {e}")

# Ha a DB fájl hiányzik vagy üres (kézi áthelyezés/törlés), előbb a teljes séma.
ensure_db_schema(reason="indítás")
init_db_extensions()
