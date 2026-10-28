# -*- coding: utf-8 -*-
import os, sys
from pathlib import Path
import json, tempfile, shutil, threading, time
from datetime import datetime, timedelta

work = tempfile.mkdtemp(prefix="kreta_sched_")
cfg_path = os.path.join(work, "config.json")

def write_cfg(sched):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"SCHEDULER": sched, "STUDENTS": []}, f)

write_cfg({"ENABLED": True, "INTERVAL_MINUTES": 180, "START_HOUR": 0, "END_HOUR": 24})

os.environ.update({
    "KRETA_DATA_DIR": work,
    "KRETA_DB_FILE": os.path.join(work, "nincs.db"),
    "KRETA_CONFIG_FILE": cfg_path,
    "KRETA_LOG_FILE": os.path.join(work, "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csat"),
    "KRETA_SCHEDULER_STATE_FILE": os.path.join(work, "scheduler_state.json"),
})
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as kreta

_hibak = []

def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)

print("1) config parse + határolás")
c = kreta.scheduler_config()
ok(c == {"enabled": True, "interval_minutes": 180, "start_hour": 0, "end_hour": 24, "stale_alert_hours": 12}, f"alap config: {c}")
write_cfg({"ENABLED": "true", "INTERVAL_MINUTES": 1, "START_HOUR": 99, "END_HOUR": -5})
c = kreta.scheduler_config()
ok(c["interval_minutes"] == 5 and c["start_hour"] == 24 and c["end_hour"] == 0, f"clamp (min 5 perc, 0-24): {c}")
write_cfg({"ENABLED": True, "INTERVAL_MINUTES": "hulyeseg", "START_HOUR": None})
c = kreta.scheduler_config()
ok(c["interval_minutes"] == 180 and c["start_hour"] == 0 and c["end_hour"] == 24, f"rossz érték -> default: {c}")

print("\n2) időablak")
ok(kreta._in_time_window(datetime(2026,1,1,3), 0, 24) is True, "0-24 -> mindig nyitva")
ok(kreta._in_time_window(datetime(2026,1,1,23), 8, 22) is False, "8-22 -> 23:00 zárva")
ok(kreta._in_time_window(datetime(2026,1,1,23), 22, 6) is True, "átforduló ablak 22-6 -> 23:00 nyitva")
ok(kreta._in_time_window(datetime(2026,1,1,12), 8, 8) is True, "start==end -> nincs korlát")
n = kreta._next_window_start(datetime(2026,1,1,23), 8, 22)
ok(n == datetime(2026,1,2,8,0), f"zárt ablak -> következő nyitás: {n}")

print("\n3) next_run számítás")
write_cfg({"ENABLED": True, "INTERVAL_MINUTES": 180, "START_HOUR": 0, "END_HOUR": 24})
kreta._scheduler_boot = datetime(2026, 10, 28, 14, 0, 0)
n = kreta.scheduler_next_run(state={}, config=kreta.scheduler_config(), now=datetime(2026,10,28,14,0,0))
ok(n == datetime(2026,10,28,14,5), f"nincs előzmény -> boot + 5 perc: {n}")

n = kreta.scheduler_next_run(
    state={"last_scheduled_run": "2026-10-28T11:00:00", "last_trigger": "scheduled"},
    config=kreta.scheduler_config(), now=datetime(2026,10,28,14,0,0))
ok(n == datetime(2026,10,28,14,0), f"utolsó ütemezett futás 3 órája -> esedékes: {n}")

n = kreta.scheduler_next_run(
    state={"last_scheduled_run": "2026-10-28T12:30:00", "last_trigger": "scheduled"},
    config=kreta.scheduler_config(), now=datetime(2026,10,28,14,0,0))
ok(n == datetime(2026,10,28,15,30), f"utolsó ütemezett futás 1,5 órája -> 15:30: {n}")

# A lényeg: a KÉZI futás nem tolja el az automatát.
n = kreta.scheduler_next_run(
    state={"last_scheduled_run": "2026-10-28T12:30:00",
           "last_run_started": "2026-10-28T14:00:00",
           "last_trigger": "manual"},
    config=kreta.scheduler_config(), now=datetime(2026,10,28,14,5,0))
ok(n == datetime(2026,10,28,15,30), f"14:00-as KÉZI futás ellenére is 15:30 az automata: {n}")

# Visszafelé kompatibilitás: régi állapotfájl, ahol a last_run_started ütemezett volt.
n = kreta.scheduler_next_run(
    state={"last_run_started": "2026-10-28T12:30:00", "last_trigger": "scheduled"},
    config=kreta.scheduler_config(), now=datetime(2026,10,28,14,0,0))
ok(n == datetime(2026,10,28,15,30), f"régi formátum (last_trigger=scheduled) -> 15:30: {n}")

# Régi formátum, de az utolsó futás kézi volt: nem számít ciklusalapnak.
n = kreta.scheduler_next_run(
    state={"last_run_started": "2026-10-28T13:50:00", "last_trigger": "manual"},
    config=kreta.scheduler_config(), now=datetime(2026,10,28,14,0,0))
ok(n == datetime(2026,10,28,14,5), f"csak kézi előzmény -> boot + 5 perc: {n}")

write_cfg({"ENABLED": False, "INTERVAL_MINUTES": 180})
ok(kreta.scheduler_next_run(state={}, now=datetime(2026,10,28,14,0,0)) is None, "ENABLED=false -> nincs next_run")

write_cfg({"ENABLED": True, "INTERVAL_MINUTES": 180, "START_HOUR": 8, "END_HOUR": 22})
n = kreta.scheduler_next_run(state={"last_scheduled_run": "2026-10-28T19:00:00", "last_trigger": "scheduled"},
                             now=datetime(2026,10,28,23,0,0))
ok(n == datetime(2026,10,29,8,0), f"esedékes de zárt ablak -> másnap 8:00: {n}")

# A felhasználó esete: 6-22 ablak, 3 órás ciklus, az utolsó ütemezett 22:16-kor
# volt -> a 01:16 HELYETT valójában reggel 6-kor fut.
write_cfg({"ENABLED": True, "INTERVAL_MINUTES": 180, "START_HOUR": 6, "END_HOUR": 22})
n = kreta.scheduler_next_run(state={"last_scheduled_run": "2026-10-28T22:16:00", "last_trigger": "scheduled"},
                             now=datetime(2026,10,28,22,30,0))
ok(n == datetime(2026,10,29,6,0), f"22:16 + 3h = 01:16, de ablak 6-22 -> holnap 6:00: {n}")

n = kreta.scheduler_next_run(state={"last_scheduled_run": "2026-10-28T09:00:00", "last_trigger": "scheduled"},
                             now=datetime(2026,10,28,10,0,0))
ok(n == datetime(2026,10,28,12,0), f"ablakon belüli esedékesség marad 12:00: {n}")

n = kreta.scheduler_next_run(state={"last_scheduled_run": "2026-10-29T16:00:00", "last_trigger": "scheduled"},
                             now=datetime(2026,10,29,17,0,0))
ok(n == datetime(2026,10,29,19,0), f"16:00 + 3h = 19:00, még nyitva -> 19:00: {n}")

# Átforduló ablak (22-6): hajnali esedékesség beleesik
write_cfg({"ENABLED": True, "INTERVAL_MINUTES": 180, "START_HOUR": 22, "END_HOUR": 6})
n = kreta.scheduler_next_run(state={"last_scheduled_run": "2026-10-29T01:00:00", "last_trigger": "scheduled"},
                             now=datetime(2026,10,29,2,0,0))
ok(n == datetime(2026,10,29,4,0), f"átforduló ablakban a 04:00 érvényes: {n}")

print("\n4) állapot perzisztencia (atomikus írás)")
kreta.save_scheduler_state({"last_run_started": "2026-10-28T12:30:00", "last_status": "done", "magyar": "ékezet"})
st = kreta.load_scheduler_state()
ok(st.get("magyar") == "ékezet" and st.get("last_status") == "done", f"visszaolvasva: {st}")
ok(not os.path.exists(kreta.SCHEDULER_STATE_FILE + ".tmp"), "nincs .tmp maradvány")
with open(kreta.SCHEDULER_STATE_FILE, "w", encoding="utf-8") as f:
    f.write("{ torott json")
ok(kreta.load_scheduler_state() == {}, "sérült állapotfájl -> üres dict (nem omlik össze)")

print("\n5) dupla indítás elleni védelem + állapotírás")
kreta.save_scheduler_state({})
started = []
def fake_run(trigger="manual"):
    started.append(trigger)
    time.sleep(0.3)
    with kreta.sync_lock:
        kreta.sync_state["running"] = False
kreta.run_scraper_thread = fake_run

r1 = kreta.start_sync("manual")
r2 = kreta.start_sync("scheduled")     # ezt már el kell utasítani
ok(r1 is True and r2 is False, f"első indítás OK, második elutasítva (r1={r1}, r2={r2})")
time.sleep(0.6)
ok(started == ["manual"], f"csak egy futás indult: {started}")
ok(not kreta.sync_state["running"], "futás után running=False")
_log = open(os.environ["KRETA_LOG_FILE"], encoding="utf-8").read()
ok("KÉZI SZINKRONIZÁCIÓ INDÍTÁSA" in _log, "a napló jelzi, hogy kézi indítás volt")

print("\n6) API végpontok (nincs holtpont)")
kreta.save_scheduler_state({"last_run_started": "2026-10-28T12:30:00", "last_status": "done", "last_trigger": "scheduled"})
cl = kreta.app.test_client()
r = cl.get("/api/scheduler/status")
d = r.get_json()
ok(r.status_code == 200 and "next_run_iso" in d and "interval_minutes" in d, f"/api/scheduler/status -> {d}")
r = cl.get("/api/sync/status")
d = r.get_json()
ok(r.status_code == 200 and isinstance(d.get("scheduler"), dict) and "logs" in d, f"/api/sync/status -> scheduler kulcs OK, {len(d.get('logs', []))} log sor")
r = cl.get("/api/sync/status")   # második hívás: a lock nem maradt zárva
ok(r.status_code == 200, "második /api/sync/status is válaszol (lock felszabadult)")

# Futás közben ne az előző eredmény látszódjon
kreta.save_scheduler_state({"last_run_started": "2026-10-28T22:12:00", "last_status": "running", "last_trigger": "manual"})
d = cl.get("/api/scheduler/status").get_json()
ok(d["last_status"] == "interrupted", f"running allapot, de nincs futo folyamat -> interrupted: {d['last_status']}")
with kreta.sync_lock:
    kreta.sync_state["running"] = True
d = cl.get("/api/scheduler/status").get_json()
ok(d["last_status"] == "running", f"tényleg futo folyamat -> running: {d['last_status']}")
with kreta.sync_lock:
    kreta.sync_state["running"] = False

# Az ütemezett futás eredménye külön mezőben (kézi futás után is megmarad)
kreta.save_scheduler_state({"last_run_started": "2026-10-28T22:19:00", "last_trigger": "manual",
                            "last_status": "done",
                            "last_scheduled_run": "2026-10-28T22:16:00", "last_scheduled_status": "error"})
d = cl.get("/api/scheduler/status").get_json()
ok(d["last_status"] == "done" and d["last_scheduled_status"] == "error",
   f"kézi=sikeres, automatikus=hiba egyszerre: {d['last_status']} / {d['last_scheduled_status']}")
# Régi állapotfájl (nincs last_scheduled_status, az utolsó futás ütemezett volt)
kreta.save_scheduler_state({"last_run_started": "2026-10-28T22:16:00", "last_trigger": "scheduled", "last_status": "done"})
d = cl.get("/api/scheduler/status").get_json()
ok(d["last_scheduled_status"] == "done", f"régi formátum: last_scheduled_status a last_status-ból: {d['last_scheduled_status']}")

print("\n7) ütemező ciklus tényleg elindítja a szinkront")
kreta.save_scheduler_state({"last_scheduled_run": (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S"),
                            "last_run_started": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                            "last_trigger": "manual"})
write_cfg({"ENABLED": True, "INTERVAL_MINUTES": 180, "START_HOUR": 0, "END_HOUR": 24})
triggered = []
def fake_run2(trigger="manual"):
    triggered.append(trigger)
    with kreta.sync_lock:
        kreta.sync_state["running"] = False
kreta.run_scraper_thread = fake_run2

class StopLoop(Exception): pass
orig_sleep = kreta.time.sleep
def fake_sleep(_): raise StopLoop()
kreta.time.sleep = fake_sleep
try:
    kreta._scheduler_loop()
except StopLoop:
    pass
finally:
    kreta.time.sleep = orig_sleep

ok(triggered == ["scheduled"], f"ciklus indított ütemezett futást: {triggered}")
log = open(os.environ["KRETA_LOG_FILE"], encoding="utf-8").read()
ok("ÜTEMEZETT SZINKRONIZÁCIÓ INDÍTÁSA" in log, "sync.log kapott ütemezett-indítás sort")

print("\n8) futás közben nem indít másodikat")
kreta.save_scheduler_state({"last_scheduled_run": (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S"), "last_trigger": "scheduled"})
with kreta.sync_lock:
    kreta.sync_state["running"] = True
ok(kreta.start_sync("scheduled") is False, "futó szinkron mellett az ütemező nem indít újat")
with kreta.sync_lock:
    kreta.sync_state["running"] = False

print("\n9) ha az állapotfájl nem írható: nincs végtelen újraindítás")
kreta._scheduler_boot = datetime(2026, 10, 28, 14, 0, 0)
kreta._last_scheduled_memo = datetime(2026, 10, 28, 13, 0, 0)
n = kreta.scheduler_next_run(state={}, config=kreta.scheduler_config(), now=datetime(2026,10,28,14,10,0))
ok(n == datetime(2026, 10, 28, 16, 0), f"memória-beli utolsó futásból számol (13:00+3h): {n}")
kreta._last_scheduled_memo = None

print("\n10) régi állapotfájl: az ütemezett futás eredménye a sync.log-ból pótolható")
with open(os.environ["KRETA_LOG_FILE"], "a", encoding="utf-8") as f:
    f.write("2026-10-28 22:18:20 [INFO] SZINKRONIZÁCIÓ VÉGE (ütemezett): done, 2.2 perc\n")
kreta._scheduled_status_cache.clear()
kreta.save_scheduler_state({"last_run_started": "2026-10-28T22:19:58", "last_trigger": "manual",
                            "last_status": "done", "last_scheduled_run": "2026-10-28T22:16:10"})
d = cl.get("/api/scheduler/status").get_json()
ok(d["last_scheduled_status"] == "done", f"naplóból pótolt ütemezett eredmény: {d['last_scheduled_status']}")

# Ha nincs hozzá tartozó naplósor, ne találgasson
kreta._scheduled_status_cache.clear()
kreta.save_scheduler_state({"last_run_started": "2026-10-28T22:19:58", "last_trigger": "manual",
                            "last_status": "done", "last_scheduled_run": "2026-10-29T09:00:00"})
d = cl.get("/api/scheduler/status").get_json()
ok(d["last_scheduled_status"] is None, f"nincs naplósor -> nincs kitalált eredmény: {d['last_scheduled_status']}")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
