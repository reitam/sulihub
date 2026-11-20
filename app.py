from flask import Flask, render_template, request, jsonify, send_from_directory, make_response, Response
import sqlite3
import os
import sys
import subprocess
import json
import threading
import re
import io
import hashlib
import hmac
import csv
import socket
import time
import urllib.request
from datetime import datetime, timedelta
import kreta_tanev
import kreta_api
import kreta_digest
import kreta_sajat_orarend
import kreta_naptar
import kreta_szunet

# ReportLab importok a PDF generáláshoz
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from werkzeug.security import check_password_hash
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


app = Flask(__name__)


@app.before_request
def _basic_auth_guard():
    """Opcionális basic auth (Kaneo #16); a /health végpont kivétel.

    #137: ha a config hiányzik/olvashatatlan/érvénytelen, **fail-closed**:
    a védett végpontok 503-at adnak, nem kapcsolja ki csendben az authot.
    """
    if request.path == "/health":
        return None
    try:
        config = load_config_strict()
    except ConfigError as exc:
        return Response(f"Beállítási hiba: {exc}", 503)
    cfg = config.get("AUTH") or {}
    if not isinstance(cfg, dict):
        return Response("Beállítási hiba: az AUTH blokk nem JSON-objektum.", 503)
    if not cfg.get("ENABLED"):
        return None
    auth = request.authorization
    username = str(cfg.get("USERNAME") or "")
    password_hash = str(cfg.get("PASSWORD_HASH") or "")
    password_plain = str(cfg.get("PASSWORD") or "")
    valid = bool(auth and username and auth.username == username)
    if valid:
        if password_hash:
            valid = check_password_hash(password_hash, auth.password or "")
        else:
            valid = bool(password_plain) and hmac.compare_digest(
                password_plain, auth.password or "")
    if not valid:
        return Response(
            "Bejelentkezés szükséges.",
            401,
            {"WWW-Authenticate": 'Basic realm="SuliHub", charset="UTF-8"'},
        )
    return None


# ── Útvonalak ────────────────────────────────────────────────────────────────
# Az útvonalak a `kreta_paths.py`-ban élnek (KRÉ-14 #93); itt csak re-exportáljuk,
# hogy a meglévő hivatkozások és a tesztek (`import app as kreta`) működjenek.
from kreta_paths import (  # noqa: E402
    APP_DIR, CONFIG_FILE, CSATOLMANYOK_DIR, DATA_DIR, DB_FILE, LOG_API_MAX_BYTES,
    LOG_BACKUP_COUNT, LOG_FILE, LOG_MAX_BYTES, SCHEDULER_STATE_FILE, VERSION_FILE,
)
from kreta_paths import ensure_data_dir  # noqa: E402

# A data/ könyvtár létrehozása még a DB-megnyitás előtt (friss klón / törölt data/).
ensure_data_dir()

# Az adatbázis-réteg (KRÉ-14 #93) — a re-export a teszt-kompatibilitást tartja:
# a tesztek `kreta.get_db_connection()` / `kreta.ensure_db_schema()` néven hívják.
from kreta_db import (  # noqa: E402
    APP_OWN_TABLES, CORE_TABLES, KOMMENT_CEL_TIPUSOK, KOMMENT_MAX_HOSSZ,
    SCHEMA_VERSION, SCRAPER_TABLES, SQLITE_WAL, SYNC_RUNNING_STATUS,
    _ESEMENY_KULCS_MEZOK, _UZENET_KULCS_MEZOK, _db_ready, _missing_tables, _now_iso,
    _row_to_state, check_db_integrity, enable_wal, ensure_db_schema, ensure_run_tables,
    get_db_connection, get_meta, init_db_extensions, komment_kulcs_esemeny,
    komment_kulcs_uzenet, komment_szamok, last_recorded_tanev, mark_interrupted_runs,
    migrate_state_file, record_run_finish, record_run_start, scheduler_state, set_meta,
)

# Beállítások (KRÉ-14 #94) — config, verzió, órarend-színek.
from kreta_settings import (  # noqa: E402
    ConfigError, _HEX_SZIN, _orarend_szinek, get_app_version, load_config,
    load_config_strict,
)

# Közös nézet-segédek (KRÉ-14 #94) — a blueprintek és a még itt maradó route-ok közösen.
from views_common import (  # noqa: E402
    _date_range_from_request, _has_tanev_column, _is_keses, _month_bounds,
    _tanev_from_request, hianyzas_osszesito, normalize_date,
)

# A scraper ezzel a jelölővel küldi a gép-olvasható összegzést a kimenetén:
# ##KRETA_RESULT##{"total":3,"ok":2,"failed":["Név"]}
RESULT_MARKER = "##KRETA_RESULT##"

# Blueprint-ek (KRÉ-14 #95) — prefix nélküliek, az URL-ek bájtra azonosak.
from views_absences import bp as _absences_bp  # noqa: E402
from views_events import bp as _events_bp  # noqa: E402
from views_messages import bp as _messages_bp  # noqa: E402
from views_orarend import bp as _orarend_bp  # noqa: E402
from views_rewards import bp as _rewards_bp  # noqa: E402
from views_search import bp as _search_bp  # noqa: E402
from views_stats import bp as _stats_bp  # noqa: E402
from kreta_exports import bp as _exports_bp  # noqa: E402
import kreta_archive  # noqa: E402
from views_pages import bp as _pages_bp  # noqa: E402

for _bp in (_pages_bp, _events_bp, _orarend_bp, _messages_bp, _absences_bp,
            _stats_bp, _rewards_bp, _exports_bp, _search_bp):
    app.register_blueprint(_bp)

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
# Szüneti napi szinkron (Kaneo #145): az utolsó ilyen futás napja + a naplózás
# memoja (ne írjon minden 30 mp-es ticknél új sort).
SZUNET_DAILY_META = "sync_szunet_napi"
_last_szunet_log = ""


def _now():
    return datetime.now().replace(microsecond=0)


def szunet_engedelyezve(config=None):
    """A tanítási szünetek figyelembevétele (SZUNET_AKTIV, alap: be)."""
    cfg = config if isinstance(config, dict) else load_config()
    raw = cfg.get("SZUNET_AKTIV", True)
    if isinstance(raw, str):
        return raw.strip().lower() in ("1", "true", "yes", "on", "igen")
    return bool(raw)


def szunet_config():
    """A config.json SYNC_SZUNET listája, normalizálva (Kaneo #145).

    Ha a `SZUNET_AKTIV` mesterkapcsoló ki van kapcsolva, üres listát ad — így
    sem a szinkron-szünet, sem a digest szünetnap-felismerése nem él.
    """
    cfg = load_config()
    if not szunet_engedelyezve(cfg):
        return []
    return kreta_szunet.parse_intervals(cfg.get("SYNC_SZUNET"))


def szunet_status(now=None):
    """Aktív/következő szinkron-szünet a felületi sávhoz (Kaneo #145)."""
    return kreta_szunet.status(szunet_config(), now or _now())


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

    health = _sync_health()
    last_run_dt = _parse_scheduler_dt(state.get("last_run_started"))
    health["last_run_age_hours"] = (
        round((_now() - last_run_dt).total_seconds() / 3600, 1) if last_run_dt else None)

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
        "health": health,
        # Szinkron-szünet (Kaneo #145): aktív/következő intervallum a fejléc-sávhoz.
        "szunet": szunet_status(),
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
# Új információ esetén menjen-e push (a sikeres, változás nélküli futás nem küld).
# A régi NOTIFY_SUCCESS kulcsot is elfogadjuk visszafelé kompatibilitás miatt.
_env_notify_new = os.environ.get("NTFY_NOTIFY_NEW")
if _env_notify_new is None or str(_env_notify_new).strip() == "":
    _env_notify_new = os.environ.get("NTFY_NOTIFY_SUCCESS")
if _env_notify_new is not None and str(_env_notify_new).strip() != "":
    NTFY_NOTIFY_NEW = str(_env_notify_new).strip().lower() in ("1", "true", "yes", "on")
else:
    _cfg_notify_new = _ntfy_config("NOTIFY_NEW")
    if _cfg_notify_new is None:
        _cfg_notify_new = _ntfy_config("NOTIFY_SUCCESS", True)
    NTFY_NOTIFY_NEW = str(_cfg_notify_new).strip().lower() in ("1", "true", "yes", "on")
# Visszafelé kompatibilis név (a régi tesztek/beállítások miatt).
NTFY_NOTIFY_SUCCESS = NTFY_NOTIFY_NEW

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


def format_new_events(new_events, new_messages=None, new_hianyzasok=None, include_names=True):
    """
    Emberi olvasású bontás a push-üzenethez:
        ["Teszt Elek: 2 jegy, 1 házi", "Teszt Anna: 1 üzenet, 3 hiányzás (2 igazolatlan óra)"]
    Csak azt a diákot írja ki, akinél történt valami. `include_names=False`
    esetén a nevek helyett „1. gyermek", „2. gyermek" áll.
    """
    new_messages = new_messages or {}
    new_hianyzasok = new_hianyzasok or {}
    diakok = list(dict.fromkeys(
        list(new_events or {}) + list(new_messages) + list(new_hianyzasok)
    ))
    lines = []
    for idx, diak in enumerate(diakok, 1):
        label = diak if include_names else f"{idx}. gyermek"
        parts = _count_parts((new_events or {}).get(diak) or {},
                             new_messages.get(diak, 0),
                             new_hianyzasok.get(diak) or {})
        if parts:
            lines.append(f"{label}: {', '.join(parts)}")
    return lines


def _count_parts(counts, n_msg=0, hianyzas=None):
    """Egy diák új adatainak rövid, emberi bontása (darabszámok)."""
    parts = []
    for tipus in EVENT_TYPE_ORDER:
        n = int((counts or {}).get(tipus, 0) or 0)
        if n:
            parts.append(f"{n} {EVENT_TYPE_LABELS.get(tipus, tipus)}")
    n_msg = int(n_msg or 0)
    if n_msg:
        parts.append(f"{n_msg} üzenet")
    h = hianyzas or {}
    n_h = int(h.get("db", 0) or 0)
    if n_h:
        ora = int(h.get("igazolatlan_ora", 0) or 0)
        parts.append(f"{n_h} hiányzás" + (f" ({ora} igazolatlan óra)" if ora else ""))
    return parts


def has_new_information(new_events, new_messages=None, new_hianyzasok=None):
    """Volt-e érdemi új információ a futásban (bármelyik diák bármely adatköre)?"""
    if any(int(v or 0) for counts in (new_events or {}).values()
           for v in (counts or {}).values()):
        return True
    if any(int(v or 0) for v in (new_messages or {}).values()):
        return True
    return any(int((h or {}).get("db", 0) or 0)
               for h in (new_hianyzasok or {}).values())


def _sync_detail_block(new_events, new_messages, new_hianyzasok):
    """A napi összefoglaló részletességű blokk a push-hoz (diákonként).

    A szinkron csak darabszámokat ad vissza, ezért a részleteket a DB-ből,
    a napi digesttel azonos formában állítjuk elő. Ha egy diákhoz a mai napon
    nincs megjeleníthető sor (pl. visszamenőleges rögzítés), a darabszámos
    összegzés marad.
    """
    diakok = list(dict.fromkeys(
        list(new_events or {}) + list(new_messages or {}) + list(new_hianyzasok or {})
    ))
    diakok = [d for d in diakok if _count_parts(
        (new_events or {}).get(d) or {}, (new_messages or {}).get(d, 0),
        (new_hianyzasok or {}).get(d) or {})]
    if not diakok:
        return ""

    nap = _now().date()
    blocks = []
    conn = None
    try:
        conn = get_db_connection()
    except Exception:  # noqa: BLE001 — a push ne akadjon el egy DB-hibán
        conn = None
    try:
        for idx, diak in enumerate(diakok, 1):
            label = diak if NTFY_INCLUDE_NAMES else f"{idx}. gyermek"
            adat = {}
            if conn is not None:
                try:
                    adat = kreta_digest.collect_day(conn, diak, nap)
                except Exception:  # noqa: BLE001
                    adat = {}
            if adat and not kreta_digest.is_empty_day(adat):
                _, torzs = kreta_digest.build_message(
                    diak, nap, adat, include_names=False)
                blocks.append(f"{label}\n{torzs}")
            else:
                parts = _count_parts((new_events or {}).get(diak) or {},
                                     (new_messages or {}).get(diak, 0),
                                     (new_hianyzasok or {}).get(diak) or {})
                blocks.append(f"{label}: {', '.join(parts)}")
    finally:
        if conn is not None:
            conn.close()
    return "\n\n".join(blocks)


NTFY_MESSAGE_LIMIT = 3900  # bájt; az ntfy üzenettörzsének felső korlátja 4096


def _limit_ntfy_message(text, limit=NTFY_MESSAGE_LIMIT):
    """Az ntfy üzenettörzsét a szolgáltatás korlátja alatt tartja (sorhatáron)."""
    raw = str(text or "")
    if len(raw.encode("utf-8")) <= limit:
        return raw
    lines = raw.splitlines()
    out = []
    used = 0
    for line in lines:
        size = len((line + "\n").encode("utf-8"))
        if used + size > limit - 90:
            break
        out.append(line)
        used += size
    return "\n".join(out).rstrip() + "\n… (a többi részlet a felületen)"


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
                       new_events=None, new_messages=None, new_hianyzasok=None,
                       health_alert=None):
    """A szinkron eredményéről szóló push (Kaneo #128).

    - hiba / részleges hiba: **mindig** megy, egy üzenet futásonként;
    - sikeres futás **új információval**: egy üzenet, a napi összefoglaló
      részletességével (a DB-ből, diákonként csoportosítva);
    - sikeres futás új információ nélkül: **nincs** push.

    `health_alert` esetén (token-lejárat / ismétlődő hiba) az adott riasztás
    lesz az egyetlen üzenet, a részletekkel kiegészítve.
    """
    failed_txt = ", ".join(failed_students) if failed_students else ""
    has_new = has_new_information(new_events, new_messages, new_hianyzasok)
    details = _sync_detail_block(new_events, new_messages, new_hianyzasok) if has_new else ""
    details_block = ("\n\n" + details) if details else ""

    if status == "done_with_errors":
        if failed_students and NTFY_INCLUDE_NAMES:
            detail = f"Nem frissült: {failed_txt}"
        elif failed_students:
            detail = f"{len(failed_students)} diák nem frissült (részletek a Rendszernaplóban)"
        else:
            detail = "Részletek a Rendszernaplóban"
        summary = f"{trigger_label(trigger)} futás · {duration_min:.1f} perc · {detail}"
        if health_alert:
            title, message, priority, tags = health_alert
            return send_notification(
                title, _limit_ntfy_message(f"{message}\n\n{summary}" + details_block),
                priority, tags)
        return send_notification(
            "KRÉTA szinkron: részleges hiba",
            _limit_ntfy_message(summary + details_block),
            3,
            ["warning"],
        )

    if status == "error":
        summary = (f"A {trigger_label(trigger)} szinkron hibával ért véget "
                   f"({duration_min:.1f} perc). Részletek a Rendszernaplóban.")
        if health_alert:
            title, message, priority, tags = health_alert
            return send_notification(
                title, _limit_ntfy_message(f"{message}\n\n{summary}" + details_block),
                priority, tags)
        return send_notification(
            "KRÉTA szinkron: HIBA",
            _limit_ntfy_message(summary + details_block),
            4,
            ["rotating_light"],
        )

    if status == "done":
        # Sikeres, de nincs új információ -> nincs push (Kaneo #128).
        if not has_new or not NTFY_NOTIFY_NEW:
            return False
        if ok_count is not None and total is not None:
            detail = f"{ok_count}/{total} diák frissült."
        else:
            detail = "Minden diák adata frissült."
        return send_notification(
            "SuliHub – új adatok",
            _limit_ntfy_message(
                f"{trigger_label(trigger)} futás · {duration_min:.1f} perc · {detail}"
                + details_block),
            3,
            ["inbox_tray"],
        )
    return False


SYNC_HEALTH_META = "sync_health"
SYNC_HEALTH_ERROR_LIMIT = 3
SYNC_HEALTH_ALERT_REPEAT_HOURS = 6

SYNC_DATASET_LABELS = {
    "orarend": "órarend",
    "jegyek": "jegyek",
    "feljegyzesek": "feljegyzések",
    "hazi": "házi feladatok",
    "szamonkeresek": "számonkérések",
    "hianyzasok": "hiányzások",
    "igazolasok": "igazolások",
    "uzenetek": "üzenetek",
}


def _failed_dataset_labels(sources):
    """A sikertelen adatkörök emberi nevei (pl. ['üzenetek'])."""
    failed = set()
    if isinstance(sources, dict):
        for student_sources in sources.values():
            if not isinstance(student_sources, dict):
                continue
            for key, outcome in student_sources.items():
                if isinstance(outcome, dict) and not outcome.get("ok", True):
                    failed.add(SYNC_DATASET_LABELS.get(key, key))
    return sorted(failed)


def _sync_health():
    """A szinkron-egészség állapota (app_meta JSON; Kaneo #88)."""
    raw = get_meta(SYNC_HEALTH_META, "") or ""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("consecutive_errors", 0)
    data.setdefault("last_status", "")
    data.setdefault("last_error_type", "")
    data.setdefault("last_error_at", "")
    data.setdefault("last_alert_at", "")
    data.setdefault("last_token_alert_at", "")
    data.setdefault("last_failed_datasets", [])
    return data


def _sync_health_ment(data):
    set_meta(SYNC_HEALTH_META, json.dumps(data, ensure_ascii=False))


def _health_throttled(data, kulcs):
    last = _parse_scheduler_dt(data.get(kulcs))
    return not last or (_now() - last).total_seconds() >= SYNC_HEALTH_ALERT_REPEAT_HOURS * 3600


_TOKEN_ERROR_MARKERS = (
    "http 401", "http 403", "401 unauthorized", "403 forbidden",
    "token expired", "token lejárt", "invalid_grant", "invalid token",
    "bejelentkezési hiba", "login failed", "hitelesítési hiba",
)


def _token_failure(sources=None, logs_text=""):
    """Valódi token/login hiba? (Kaneo #88/#128)

    Elsődlegesen a **sikertelen adatkörök okát** nézi, nem a teljes naplót:
    a naplóban ugyanis lehetnek „tárolt tokenből", „refresh tokennel" info-sorok,
    amelyek korábban tévesen „újra be kell jelentkezni" állapotot adtak.
    """
    reasons = []
    if isinstance(sources, dict):
        for student_sources in sources.values():
            if not isinstance(student_sources, dict):
                continue
            for outcome in student_sources.values():
                if isinstance(outcome, dict) and not outcome.get("ok", True):
                    reasons.append(str(outcome.get("reason") or "").lower())
    if reasons:
        return any(any(marker in reason for marker in _TOKEN_ERROR_MARKERS)
                   for reason in reasons)
    low = (logs_text or "").lower()
    return any(marker in low for marker in _TOKEN_ERROR_MARKERS)


def _update_sync_health(status, failed_students, logs_text="", sources=None):
    """Egymást követő hibák / token-lejárat állapota (Kaneo #88).

    **Nem küld** külön push-t: a riasztást `_alert` kulcsban adja vissza, és a
    `notify_sync_result` küldi el a futás egyetlen üzeneteként (Kaneo #128).
    """
    data = _sync_health()
    hibas = status in ("error", "done_with_errors")
    token_hiba = hibas and _token_failure(sources, logs_text)
    if hibas:
        data["consecutive_errors"] = int(data.get("consecutive_errors") or 0) + 1
        data["last_error_type"] = "token" if token_hiba else "sync"
        data["last_error_at"] = _now().strftime(SCHEDULER_TS_FMT)
        data["last_failed_datasets"] = _failed_dataset_labels(sources)
    else:
        data["consecutive_errors"] = 0
        data["last_error_type"] = ""
        data["last_failed_datasets"] = []
    data["last_status"] = status

    alert = None
    if NTFY_TOPIC:
        if token_hiba and _health_throttled(data, "last_token_alert_at"):
            alert = (
                "KRÉTA: újra be kell jelentkezni",
                "A KRÉTA munkamenet lejárt. A következő szinkron automatikusan "
                "megpróbál belépni a config.json-ban megadott felhasználónévvel és "
                "jelszóval. Ha ez ismétlődik, ellenőrizd a belépési adatokat, majd "
                "indíts kézi frissítést (a részletek a Rendszernaplóban).",
                4, ["key"],
            )
            data["last_token_alert_at"] = _now().strftime(SCHEDULER_TS_FMT)
        elif int(data.get("consecutive_errors") or 0) >= SYNC_HEALTH_ERROR_LIMIT \
                and _health_throttled(data, "last_alert_at"):
            n = data["consecutive_errors"]
            alert = (
                "KRÉTA: ismétlődő szinkronhiba",
                f"{n} egymást követő szinkronhiba. "
                + (f"Nem frissült: {', '.join(failed_students)}. " if failed_students else "")
                + "Ellenőrizd a Rendszernaplót.",
                5, ["rotating_light"],
            )
            data["last_alert_at"] = _now().strftime(SCHEDULER_TS_FMT)

    _sync_health_ment({k: v for k, v in data.items() if not k.startswith("_")})
    if alert:
        data["_alert"] = alert
    return data


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


# ── Esti digest (KRÉ-8) ─────────────────────────────────────────────────────
def digest_settings():
    """Az esti digest beállításai: config.json DIGEST alap + app_meta felülírás."""
    cfg = (load_config() or {}).get("DIGEST") or {}
    meta = get_meta(kreta_digest.DIGEST_SETTINGS_META, "") or ""
    return kreta_digest.load_settings(cfg, meta)


def build_digest_for(diak_nev, nap=None, kezdo=None):
    """Egy diák digestje (cím, törzs) a megadott időszakra."""
    nap = nap or _now().date()
    kezdo = kezdo or nap
    conn = get_db_connection()
    try:
        adat = kreta_digest.collect_range(conn, diak_nev, kezdo, nap)
    finally:
        conn.close()
    settings = digest_settings()
    return kreta_digest.build_message(
        diak_nev, nap, adat, bool(settings.get("include_names", True)), kezdo=kezdo
    )


def _active_students():
    return [s for s in (load_config().get("STUDENTS") or []) if s.get("active", True)]


def _maybe_send_digests(now=None):
    """Esti digest: gyermekenként egy üzenet, naponta egyszer (a tickből hívva).

    A napot `app_meta` jelölő zárja le (`digest_sent:<diák>`), az elküldés
    időpontját a `digest_last_at:<diák>` őrzi (a manuális összefoglaló ez óta
    kérdezi az eseményeket). Üres napon is küld — kivéve hétvégén/szünetnapon,
    ahol csak a „nem történt semmi" üzenetet hagyjuk ki (Kaneo #133).
    """
    now = now or _now()
    settings = digest_settings()
    if not settings.get("enabled") or not NTFY_TOPIC:
        return 0
    if sync_state.get("running") or not os.path.exists(DB_FILE):
        return 0

    cfg = load_config()
    szunet_aktiv = szunet_engedelyezve(cfg)
    extra_szunet: set = set()
    if szunet_aktiv:
        # A tanítási szünetek EGY helyen: a SYNC_SZUNET intervallumai. A
        # DIGEST.SZUNET_NAPOK csak kiegészítés (pl. tanév rendje napok).
        extra_szunet |= kreta_digest.parse_szunet_napok(
            (cfg.get("DIGEST") or {}).get("SZUNET_NAPOK"))
        extra_szunet |= kreta_szunet.all_days(
            kreta_szunet.parse_intervals(cfg.get("SYNC_SZUNET")))

    sent = 0
    for student in _active_students():
        diak = str(student.get("diak_nev") or "").strip()
        if not diak:
            continue
        key = kreta_digest.DIGEST_SENT_PREFIX + diak
        if not kreta_digest.should_send(settings, get_meta(key, "") or "", now):
            continue
        try:
            conn = get_db_connection()
            try:
                adat = kreta_digest.collect_day(conn, diak, now.date())
                szunet = (kreta_digest.is_szunet_nap(conn, diak, now.date(), extra_szunet)
                          if szunet_aktiv else False)
            finally:
                conn.close()
            if kreta_digest.should_skip_empty_digest(now.date(), adat, szunet):
                set_meta(key, now.date().isoformat())
                _append_sync_log(f"[Digest] {diak}: szünet/hétvége, üres nap — kihagyva")
                continue
            cim, torzs = kreta_digest.build_message(
                diak, now.date(), adat, bool(settings.get("include_names", True)))
        except Exception as exc:  # noqa: BLE001 — egy diák hibája ne állítsa meg a többit
            print(f"[Digest] {diak}: nem sikerült összeállítani ({exc})")
            continue
        if not send_notification(cim, torzs, 2, ["memo"]):
            break
        set_meta(key, now.date().isoformat())
        set_meta(kreta_digest.DIGEST_LAST_AT_PREFIX + diak,
                 now.strftime("%Y-%m-%dT%H:%M:%S"))
        sent += 1
        _append_sync_log(f"[Digest] {diak}: esti összefoglaló elküldve")
    return sent


def digest_last_auto():
    """A legutóbbi automatikus digest időpontja (a legfrissebb diák szerint)."""
    latest = ""
    for student in _active_students():
        diak = str(student.get("diak_nev") or "").strip()
        if not diak:
            continue
        value = get_meta(kreta_digest.DIGEST_LAST_AT_PREFIX + diak, "") or ""
        if value > latest:
            latest = value
    return latest


def manual_digest(diak=None, now=None):
    """Manuális összefoglaló: az utolsó **automatikus** digest óta (diákonként).

    A manuális küldés nem írja felül a napi jelölőt (`digest_sent`) és a
    `digest_last_at`-et sem, tehát az automatikus digest időpontját és
    tartalmát nem befolyásolja.
    """
    now = now or _now()
    students = _active_students()
    if diak:
        students = [s for s in students if s.get("diak_nev") == diak]

    results = []
    for student in students:
        nev = str(student.get("diak_nev") or "")
        # Diákonként az ő utolsó automatikus küldése számít; ha még nem volt,
        # az előző napot vesszük alapnak (gyakorlatilag a mai nap).
        kezdo_alap = kreta_digest.parse_date(
            get_meta(kreta_digest.DIGEST_LAST_AT_PREFIX + nev, "") or ""
        ) or (now.date() - timedelta(days=1))
        kezdo = kezdo_alap + timedelta(days=1)
        if kezdo > now.date() or kezdo_alap >= now.date():
            kezdo = now.date()
        try:
            cim, torzs = build_digest_for(nev, now.date(), kezdo=kezdo)
        except Exception as exc:  # noqa: BLE001
            results.append({"diak": nev, "error": f"{type(exc).__name__}: {exc}"})
            continue
        ok_sent = send_notification(cim, torzs, 2, ["memo"])
        results.append({
            "diak": nev, "sent": ok_sent,
            "kezdo": kezdo.isoformat(), "vege": now.date().isoformat(),
        })
    return results


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


def _maybe_log_szunet(interval, now):
    """Naponta egyszer naplózza, hogy a szinkron szünetel (Kaneo #145)."""
    global _last_szunet_log
    key = f"{interval['kezdo'].isoformat()}:{now.date().isoformat()}"
    if _last_szunet_log == key:
        return
    _last_szunet_log = key
    extra = (f"; napi automatikus szinkron {interval['napi_ido']}-kor"
             if interval["napi_sync"] else "; nincs napi automatikus szinkron")
    _append_sync_log(
        f"[Szünet] {interval['nev']} ({interval['kezdo']}–{interval['vege']}): "
        f"az automatikus szinkron szünetel{extra}. A kézi frissítés elérhető.")


def _scheduler_loop():
    """Háttérszál: 30 másodpercenként dönt, hogy esedékes-e a szinkron."""
    print("[Ütemező] Háttérszál elindult.")
    while True:
        try:
            cfg = scheduler_config()
            now = _now()
            szunet = kreta_szunet.active_interval(szunet_config(), now.date())
            if szunet:
                # Szünet: a normál intervallum helyett csak az opcionális napi
                # szinkron fut (ha be van állítva); a kézi gomb mindig megy.
                _maybe_log_szunet(szunet, now)
                if (cfg["enabled"] and kreta_szunet.daily_sync_due(
                        szunet, now, get_meta(SZUNET_DAILY_META, "") or "")):
                    if start_sync("scheduled"):
                        set_meta(SZUNET_DAILY_META, now.date().isoformat())
                        _append_sync_log(
                            f"[Szünet] {szunet['nev']}: napi automatikus szinkron "
                            f"({szunet['napi_ido']})")
            else:
                due = scheduler_next_run(config=cfg)
                if due and now >= due and _in_time_window(now, cfg["start_hour"], cfg["end_hour"]):
                    # a naplózást a start_sync végzi (egységesen, mindkét triggerre)
                    start_sync("scheduled")
                    # ha épp fut valami, a következő tick újra próbálja (nincs sorban állás)
            _maybe_notify_stale(cfg)
            _maybe_send_digests()
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
            final_logs = "\n".join(sync_state["logs"])

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

        # Szinkron-egészség: egymást követő hibák / token-lejárat (Kaneo #88).
        health = _update_sync_health(final_status, final_failed, final_logs, final_sources)
        health_alert = health.get("_alert")

        # Push értesítés: egy üzenet futásonként — hiba, vagy új információ
        # (a napi összefoglaló részletességével); változás nélküli siker: nincs.
        notify_sync_result(final_status, final_failed, trigger, duration_min, final_ok, final_total,
                           final_new_events, final_new_messages, final_new_hianyzasok,
                           health_alert=health_alert)

        if tanev_changes:
            lezart = sorted({ch.get("lezart_tanev") for ch in tanev_changes if ch.get("lezart_tanev")})
            ujak = sorted({ch.get("uj_tanev") for ch in tanev_changes if ch.get("uj_tanev")})
            # Tanév-archívum (Kaneo #139): a lezárt tanév egyszeri, ellenőrizhető ZIP-je.
            for tanev in lezart:
                try:
                    path = kreta_archive.create_tanev_archive(tanev)
                    _tanev_state_log(f"[Tanév-archívum] {tanev}: {path}")
                except Exception as exc:  # noqa: BLE001 — az archívum hibája ne akassza meg a futást
                    _tanev_state_log(
                        f"[Tanév-archívum] {tanev}: hiba ({type(exc).__name__}: {exc})")
            send_notification(
                "KRÉTA: új tanév",
                f"Tanév lezárva: {', '.join(lezart) or '-'} · megnyitva: {', '.join(ujak) or '-'}. "
                f"Adatlekérés nélkül, a KRÉTA TanevUid változása alapján.",
                3,
                ["calendar"],
            )


# ── Saját (kézi) órarendi tételek — Kaneo #55 ─────────────────────────────


# ── Órarend ICS export (Kaneo #73) ────────────────────────────────────────


# ==============================================================================
# === NAPTÁRBEJEGYZÉS GENERÁLÁS (Kaneo #47) ===================================
# ==============================================================================


# ==============================================================================
# === PDF BETŰKÉSZLET (magyar ő/ű támogatás) ===================================
# ==============================================================================
# A ReportLab beépített Type1 betűi (Helvetica stb.) csak Latin-1-et tudnak,
# így a hosszú ő/Ő és ű/Ű (U+0150–U+0171) NEM jelenik meg helyesen a PDF-ben.
# Ezért egy Unicode TrueType betűt regisztrálunk (amilyen épp elérhető a gépen):
# a konténerben Liberation/DejaVu, lokálisan (Windows) Arial/Calibri.


# ==============================================================================
# === SAJÁT MEGJEGYZÉSEK (Kaneo #46) ===========================================
# ==============================================================================


# ==============================================================================
# === HIÁNYZÁSOK / KÉSÉSEK ÉS IGAZOLÁSOK API ===================================
# ==============================================================================


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


@app.route("/api/sync_runs")
def api_sync_runs():
    """Legutóbbi szinkronfutások a Rendszernapló fülhöz (Kaneo #10)."""
    try:
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(100, limit))
    if not os.path.exists(DB_FILE):
        return jsonify([])

    def _loads(value, default):
        try:
            return json.loads(value) if value else default
        except (TypeError, ValueError):
            return default

    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, trigger, started_at, finished_at, status, ok_count, total_count,"
            " failed_students, new_events, new_messages, new_hianyzasok, duration_sec, tanev"
            " FROM sync_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()

    result = []
    for row in rows:
        new_events = _loads(row["new_events"], {})
        new_count = 0
        if isinstance(new_events, dict):
            for value in new_events.values():
                if isinstance(value, dict):
                    new_count += sum(int(x or 0) for x in value.values())
                else:
                    try:
                        new_count += int(value or 0)
                    except (TypeError, ValueError):
                        pass
        elif isinstance(new_events, list):
            new_count = len(new_events)
        failed = _loads(row["failed_students"], [])
        if not isinstance(failed, list):
            failed = [str(failed)]
        result.append({
            "id": row["id"],
            "trigger": row["trigger"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "ok_count": row["ok_count"],
            "total_count": row["total_count"],
            "duration_sec": row["duration_sec"],
            "new_event_count": new_count,
            "failed_students": failed,
            "tanev": row["tanev"],
        })
    return jsonify(result)


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


# ── Esti digest beállításai és tesztje (KRÉ-8) ─────────────────────────────
@app.route("/api/digest/settings", methods=["GET", "PUT"])
def api_digest_settings():
    """A napi esti összefoglaló beállításai (config alap + app_meta felülírás)."""
    if request.method == "GET":
        return jsonify({
            "status": "ok",
            "settings": digest_settings(),
            "ntfy_configured": bool(NTFY_TOPIC),
            "last_auto": digest_last_auto(),
        })

    data = request.get_json(silent=True) or {}
    settings, errors = kreta_digest.parse_settings(data, base=digest_settings())
    if errors:
        return jsonify({"status": "error", "errors": errors}), 400
    set_meta(kreta_digest.DIGEST_SETTINGS_META, json.dumps(settings, ensure_ascii=False))
    _append_sync_log("[Digest] beállítások mentve: " + json.dumps(settings, ensure_ascii=False))
    return jsonify({"status": "ok", "settings": settings})


@app.route("/api/digest/run", methods=["POST"])
def api_digest_run():
    """Manuális összefoglaló az utolsó **automatikus** digest óta.

    Tesztelési/kérési célra; a napi jelölőt és a `digest_last_at`-et nem
    módosítja, tehát az automatikus digest időpontja/tartalma változatlan marad.
    """
    if not NTFY_TOPIC:
        return jsonify({
            "status": "error",
            "message": "Nincs ntfy topic beállítva (config.json → NTFY.TOPIC vagy NTFY_TOPIC).",
        }), 400
    data = request.get_json(silent=True) or {}
    diak = str(data.get("diak") or "").strip()
    if diak and not any(s.get("diak_nev") == diak for s in _active_students()):
        return jsonify({"status": "error", "message": "Nincs ilyen aktív diák."}), 400

    results = manual_digest(diak or None)
    sent = [r["diak"] for r in results if r.get("sent")]
    return jsonify({"status": "ok", "sent": sent, "results": results})


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
