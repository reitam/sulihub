# -*- coding: utf-8 -*-
import os, sys
from pathlib import Path
import json, sqlite3, tempfile, shutil, threading, time
from datetime import datetime, timedelta

work = tempfile.mkdtemp(prefix="kreta_sched_")
cfg_path = os.path.join(work, "config.json")
log_path = os.path.join(work, "sync.log")
db_path = os.path.join(work, "kreta_adatok.db")

def write_cfg(sched):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"SCHEDULER": sched, "STUDENTS": []}, f)

write_cfg({"ENABLED": True, "INTERVAL_MINUTES": 180, "START_HOUR": 0, "END_HOUR": 24})

# valódi DB (a futásnapló mostantól ott van)
sqlite3.connect(db_path).close()

os.environ.update({
    "KRETA_DATA_DIR": work,
    "KRETA_DB_FILE": db_path,
    "KRETA_CONFIG_FILE": cfg_path,
    "KRETA_LOG_FILE": log_path,
    "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csat"),
    "KRETA_SCHEDULER_STATE_FILE": os.path.join(work, "scheduler_state.json"),
})
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as kreta

kreta.init_db_extensions()   # létrehozza a táblákat (WAL, sync_runs, app_meta)

_hibak = []

def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)

def clear_runs():
    conn = kreta.get_db_connection()
    conn.execute("DELETE FROM sync_runs")
    conn.execute("DELETE FROM app_meta")
    conn.commit()
    conn.close()

def seed_run(trigger, started, status="done", finished=None, ok_n=None, total=None, failed=None):
    rid = kreta.record_run_start(trigger, started)
    kreta.record_run_finish(rid, status, finished_at=finished or started,
                            ok_count=ok_n, total_count=total, failed_students=failed or [])
    return rid

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

# Visszafelé kompatibilitás: olyan állapot, ahol a last_run_started ütemezett volt.
n = kreta.scheduler_next_run(
    state={"last_run_started": "2026-10-28T12:30:00", "last_trigger": "scheduled"},
    config=kreta.scheduler_config(), now=datetime(2026,10,28,14,0,0))
ok(n == datetime(2026,10,28,15,30), f"kompatibilitás (legacy dict) -> 15:30: {n}")

# Csak kézi előzmény: nem számít ciklusalapnak.
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

write_cfg({"ENABLED": True, "INTERVAL_MINUTES": 180, "START_HOUR": 22, "END_HOUR": 6})
n = kreta.scheduler_next_run(state={"last_scheduled_run": "2026-10-29T01:00:00", "last_trigger": "scheduled"},
                             now=datetime(2026,10,29,2,0,0))
ok(n == datetime(2026,10,29,4,0), f"átforduló ablakban a 04:00 érvényes: {n}")

print("\n4) futásnapló a DB-ben (nem JSON)")
clear_runs()
seed_run("scheduled", "2026-10-28T12:30:00", "done", ok_n=3, total=3)
st = kreta.scheduler_state()
ok(st.get("last_status") == "done" and st.get("last_trigger") == "scheduled",
   f"visszaolvasva: {st.get('last_status')}/{st.get('last_trigger')}")
ok(st.get("last_scheduled_run") == "2026-10-28T12:30:00", f"ütemezett futás is: {st.get('last_scheduled_run')}")

conn = kreta.get_db_connection()
ok(str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal", "WAL alapból KI (FUSE kötet)")
ok(kreta.SQLITE_WAL is False, "KRETA_SQLITE_WAL opt-in (alapból ki)")
cols = [r[1] for r in conn.execute("PRAGMA table_info(sync_runs)")]
ok(all(c in cols for c in ("trigger", "started_at", "status", "new_events", "duration_sec")), f"sync_runs séma: {cols}")
conn.close()

kreta.set_meta("teszt_kulcs", "ertek")
ok(kreta.get_meta("teszt_kulcs") == "ertek", "app_meta írás/olvasás")
ok(kreta.get_meta("nincs_ilyen", "alap") == "alap", "app_meta default")
ok(not os.path.exists(os.path.join(work, "scheduler_state.json")), "nem keletkezik scheduler_state.json")

print("\n5) dupla indítás elleni védelem")
clear_runs()
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
_log = open(log_path, encoding="utf-8").read()
ok("KÉZI SZINKRONIZÁCIÓ INDÍTÁSA" in _log, "a napló jelzi, hogy kézi indítás volt")

print("\n6) API végpontok (nincs holtpont)")
clear_runs()
seed_run("scheduled", "2026-10-28T12:30:00", "done")
cl = kreta.app.test_client()
r = cl.get("/api/scheduler/status")
d = r.get_json()
ok(r.status_code == 200 and "next_run_iso" in d and "interval_minutes" in d, f"/api/scheduler/status -> {d}")
r = cl.get("/api/sync/status")
d = r.get_json()
ok(r.status_code == 200 and isinstance(d.get("scheduler"), dict) and "logs" in d,
   f"/api/sync/status -> scheduler kulcs OK, {len(d.get('logs', []))} log sor")
r = cl.get("/api/sync/status")   # második hívás: a lock nem maradt zárva
ok(r.status_code == 200, "második /api/sync/status is válaszol (lock felszabadult)")

# Nyitva hagyott (running) sor + nincs futó folyamat -> interrupted
clear_runs()
kreta.record_run_start("manual", "2026-10-28T22:12:00")
d = cl.get("/api/scheduler/status").get_json()
ok(d["last_status"] == "interrupted", f"running sor, de nincs folyamat -> interrupted: {d['last_status']}")
with kreta.sync_lock:
    kreta.sync_state["running"] = True
d = cl.get("/api/scheduler/status").get_json()
ok(d["last_status"] == "running", f"tényleg futó folyamat -> running: {d['last_status']}")
with kreta.sync_lock:
    kreta.sync_state["running"] = False

# Kézi és ütemezett eredmény egyszerre
clear_runs()
seed_run("scheduled", "2026-10-28T22:16:00", "error")
seed_run("manual", "2026-10-28T22:19:00", "done")
d = cl.get("/api/scheduler/status").get_json()
ok(d["last_status"] == "done" and d["last_scheduled_status"] == "error",
   f"kézi=sikeres, automatikus=hiba egyszerre: {d['last_status']} / {d['last_scheduled_status']}")

print("\n7) ütemező ciklus tényleg elindítja a szinkront")
clear_runs()
seed_run("manual", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "done")
seed_run("scheduled", (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S"), "done")
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
log = open(log_path, encoding="utf-8").read()
ok("ÜTEMEZETT SZINKRONIZÁCIÓ INDÍTÁSA" in log, "sync.log kapott ütemezett-indítás sort")

print("\n8) futás közben nem indít másodikat")
clear_runs()
seed_run("scheduled", (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S"), "done")
with kreta.sync_lock:
    kreta.sync_state["running"] = True
ok(kreta.start_sync("scheduled") is False, "futó szinkron mellett az ütemező nem indít újat")
with kreta.sync_lock:
    kreta.sync_state["running"] = False

print("\n9) ha a DB nem elérhető: memória-beli fallback")
kreta._scheduler_boot = datetime(2026, 10, 28, 14, 0, 0)
kreta._last_scheduled_memo = datetime(2026, 10, 28, 13, 0, 0)
n = kreta.scheduler_next_run(state={}, config=kreta.scheduler_config(), now=datetime(2026,10,28,14,10,0))
ok(n == datetime(2026, 10, 28, 16, 0), f"memória-beli utolsó futásból számol (13:00+3h): {n}")
kreta._last_scheduled_memo = None

print("\n10) hiányzó ütemezett eredmény pótlása a sync.log-ból")
with open(log_path, "a", encoding="utf-8") as f:
    f.write("2026-10-28 22:18:20 [INFO] SZINKRONIZÁCIÓ VÉGE (ütemezett): done, 2.2 perc\n")
kreta._scheduled_status_cache.clear()
ok(kreta._scheduled_status_from_log("2026-10-28T22:16:10") == "done", "a naplóból kiolvassa")
ok(kreta._scheduled_status_from_log("2026-10-29T09:00:00") is None, "nincs naplósor -> nem találgat")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
