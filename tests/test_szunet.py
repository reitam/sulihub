# -*- coding: utf-8 -*-
"""
Kaneo #145: szinkron-szünet (config intervallumok, napi opcionális szinkron).

1) `kreta_szunet` tiszta logika: parse, aktív/következő intervallum, napi idő.
2) `app.szunet_status` + `/api/scheduler/status` `szunet` mező.
3) Ütemező: szünet alatt nincs normál automata futás; a napi szinkron egyszer
   lefut a beállított idő után; a napló jelzi a szünetet.
4) A felületi sáv (HTML/JS) megvan.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import kreta_szunet  # noqa: E402

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


TODAY = date.today()
FIXED = datetime.combine(TODAY, time(10, 1))
INTERVAL = {
    "nev": "Teszt szünet",
    "kezdo": (TODAY - timedelta(days=1)).isoformat(),
    "vege": (TODAY + timedelta(days=1)).isoformat(),
    "napi_sync": True,
    "napi_ido": "10:00",
}

print("1) Intervallum-parse")
intervals = kreta_szunet.parse_intervals([
    INTERVAL,
    {"nev": "Hibás", "kezdo": "nincs", "vege": "2026-11-10"},
    {"kezdo": "2026. 12. 21.", "vege": "2027. 01. 02.", "napi_sync": "igen", "napi_ido": "7:5"},
])
ok(len(intervals) == 2, f"2 érvényes intervallum: {len(intervals)}")
ok(intervals[0]["nev"] == "Teszt szünet" and intervals[0]["napi_ido"] == "10:00",
   "az első intervallum normalizálva")
teli = next(i for i in intervals if i["nev"] == "Szünet")
ok(teli["kezdo"] == date(2026, 12, 21) and teli["napi_ido"] == "07:05"
   and teli["napi_sync"] is True, f"magyar dátum + idő normalizálás: {teli}")
ok(kreta_szunet.parse_intervals(None) == [] and kreta_szunet.parse_intervals("x") == [],
   "hibás config -> üres lista")

print("\n2) Aktív / következő intervallum")
aktiv = kreta_szunet.active_interval(intervals, TODAY)
ok(aktiv and aktiv["nev"] == "Teszt szünet", f"a mai nap aktív: {aktiv and aktiv['nev']}")
ok(kreta_szunet.active_interval(intervals, date(2026, 6, 1)) is None,
   "nincs aktív szünet nyáron")
kov = kreta_szunet.next_interval(intervals, date(2026, 6, 1))
ok(kov and kov["nev"] == "Teszt szünet", "a következő a teszt intervallum")
ok(kreta_szunet.interval_days(intervals[0]) == 3, "3 napos intervallum")
napok = kreta_szunet.all_days(intervals)
ok(TODAY in napok and date(2027, 1, 2) in napok and len(napok) == 16,
   f"az intervallumok összes napja (3 + 13 = 16): {len(napok)}")

print("\n3) Napi szinkron esedékessége")
ok(kreta_szunet.daily_sync_due(aktiv, FIXED, ""), "10:01-kor esedékes")
ok(not kreta_szunet.daily_sync_due(aktiv, datetime.combine(TODAY, time(9, 0)), ""),
   "09:00-kor még nem")
ok(not kreta_szunet.daily_sync_due(aktiv, FIXED, TODAY.isoformat()),
   "ugyanazon a napon nem ismétel")
ok(not kreta_szunet.daily_sync_due({**aktiv, "napi_sync": False}, FIXED, ""),
   "napi_sync=false -> nincs napi futás")
ok(not kreta_szunet.daily_sync_due(aktiv, datetime.combine(TODAY, time(23, 10)), ""),
   "23 óra után nem fut")

# ── App-integráció külön temp környezetben ──────────────────────────────────
work = Path(tempfile.mkdtemp(prefix="kreta_szunet_"))
db = work / "kreta_adatok.db"
cfg_path = work / "config.json"


def write_cfg(raw):
    cfg_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


write_cfg({
    "SCHEDULER": {"ENABLED": True, "INTERVAL_MINUTES": 180, "START_HOUR": 0, "END_HOUR": 24},
    "SYNC_SZUNET": [INTERVAL],
    "STUDENTS": [{"diak_nev": "Teszt", "active": False}],
})
env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(cfg_path),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": str(work / "csat"),
    "KRETA_SCHEDULER_STATE_FILE": str(work / "scheduler_state.json"),
    "KRETA_VERSION_FILE": str(work / "version.txt"),
    "PYTHONIOENCODING": "utf-8",
})
os.environ.update({k: v for k, v in env.items() if k.startswith("KRETA")})
subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import app  # noqa: E402

client = app.app.test_client()

print("\n4) API + felületi sáv")
st = client.get("/api/scheduler/status").get_json()
ok(isinstance(st.get("szunet"), dict) and (st["szunet"].get("active") or {}).get("nev") == "Teszt szünet",
   f"a /api/scheduler/status átadja az aktív szünetet: {st.get('szunet')}")
st_fixed = app.szunet_status(now=FIXED)
ok(st_fixed["active"]["napi_sync"] is True and st_fixed["active"]["napi_ido"] == "10:00",
   "a napi szinkron beállítása is átjön")
html = client.get("/").get_data(as_text=True)
js = client.get("/static/js/app-main.js").get_data(as_text=True)
ok('id="szunetBanner"' in html and "szunet-banner" in html
   and "#8b1e2d" in html,
   "van bordó, hangsúlyos szünet-sáv a felületen")
ok("renderSzunetBanner" in js and "szunet.active" in js
   and "A beállított rendszeres szinkron szüneti üzemmódban működik" in js,
   "a JS a rendszeres szinkron üzemmódját írja")
ok("szunet-title" in js and "szunet-daily" in js and "SZÜNET" in js
   and "Napi egy biztonsági szinkron bekapcsolva" in js,
   "a sáv címet, jelvényt és a napi biztonsági szinkront is mutatja")
ok("szunet-daily-short" in js and "Biztonsági szinkron:" in js
   and "szunet-title-text" in js,
   "mobilon rövid, két soros változat van (név + biztonsági szinkron)")
ok("Az automatikus szinkron most szünetel" not in js,
   "nincs ellentmondó „most szünetel” szöveg")
ok("daily_sync_due" in Path(ROOT / "app.py").read_text(encoding="utf-8"),
   "az ütemező a napi szinkron döntést használja")

print("\n5) Ütemező szünet alatt (napi szinkron egyszer)")
triggered = []


def fake_run(trigger="manual"):
    triggered.append(trigger)
    with app.sync_lock:
        app.sync_state["running"] = False


app.run_scraper_thread = fake_run
orig_now = app._now
orig_sleep = app.time.sleep
app._now = lambda: FIXED


class StopLoop(Exception):
    pass


def fake_sleep(_):
    raise StopLoop()


app.time.sleep = fake_sleep
app.set_meta(app.SZUNET_DAILY_META, "")
try:
    try:
        app._scheduler_loop()
    except StopLoop:
        pass
finally:
    app.time.sleep = orig_sleep

ok(triggered == ["scheduled"], f"a napi szinkron lefutott: {triggered}")
ok(app.get_meta(app.SZUNET_DAILY_META, "") == TODAY.isoformat(),
   "a napi futás napja mentve")

# Másodszor ugyanazon a napon: a jelölő miatt nem fut újra.
app.time.sleep = fake_sleep
try:
    try:
        app._scheduler_loop()
    except StopLoop:
        pass
finally:
    app.time.sleep = orig_sleep
ok(triggered == ["scheduled"], f"ugyanazon a napon nem fut újra: {triggered}")

# Napi szinkron kikapcsolása: szünet alatt nincs automatikus futás.
write_cfg({
    "SCHEDULER": {"ENABLED": True, "INTERVAL_MINUTES": 180, "START_HOUR": 0, "END_HOUR": 24},
    "SYNC_SZUNET": [{**INTERVAL, "napi_sync": False}],
    "STUDENTS": [{"diak_nev": "Teszt", "active": False}],
})
app.set_meta(app.SZUNET_DAILY_META, "")
triggered.clear()
app.time.sleep = fake_sleep
try:
    try:
        app._scheduler_loop()
    except StopLoop:
        pass
finally:
    app.time.sleep = orig_sleep
    app._now = orig_now
ok(triggered == [], f"napi szinkron nélkül a szünet alatt nincs futás: {triggered}")
log = (work / "sync.log").read_text(encoding="utf-8")
ok("[Szünet] Teszt szünet" in log and "szünetel" in log,
   "a napló jelzi a szünetet")

print("\n6) Mesterkapcsoló (SZUNET_AKTIV)")
base_cfg = {
    "SCHEDULER": {"ENABLED": True, "INTERVAL_MINUTES": 180, "START_HOUR": 0, "END_HOUR": 24},
    "SYNC_SZUNET": [INTERVAL],
    "STUDENTS": [{"diak_nev": "Teszt", "active": False}],
}
write_cfg({**base_cfg, "SZUNET_AKTIV": False})
ok(app.szunet_engedelyezve() is False, "a kapcsoló false")
ok(app.szunet_config() == [], "kikapcsolva nincs szünet-intervallum")
ok(app.szunet_status()["active"] is None, "a banner sem mutat aktív szünetet")
ok(app.szunet_engedelyezve({"SZUNET_AKTIV": "nem"}) is False, "a string 'nem' is kikapcsol")
write_cfg({**base_cfg, "SZUNET_AKTIV": True})
ok(app.szunet_engedelyezve() is True
   and (app.szunet_status()["active"] or {}).get("nev") == "Teszt szünet",
   "visszakapcsolva ismét aktív")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
