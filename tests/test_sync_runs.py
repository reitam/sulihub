# -*- coding: utf-8 -*-
"""Futástörténet API (Kaneo #10) — temp adatbázison."""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = tempfile.mkdtemp(prefix="kreta_runs_")
db = os.path.join(work, "kreta_adatok.db")
os.environ.update({
    "KRETA_DATA_DIR": work,
    "KRETA_DB_FILE": db,
    "KRETA_CONFIG_FILE": os.path.join(work, "config.json"),
    "KRETA_LOG_FILE": os.path.join(work, "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csat"),
    "KRETA_SCHEDULER_STATE_FILE": os.path.join(work, "scheduler_state.json"),
})
sys.path.insert(0, str(ROOT))
import app as kreta  # noqa: E402

kreta.init_db_extensions()
client = kreta.app.test_client()
_hibak = []


def ok(cond, msg):
    print(("  OK   " if cond else "  HIBA ") + msg)
    if not cond:
        _hibak.append(msg)


print("1) üres futásnapló")
res = client.get("/api/sync_runs")
ok(res.status_code == 200 and res.get_json() == [], "kezdetben üres lista")

print("\n2) futások mentése és lekérése")
conn = sqlite3.connect(db)
rows = [
    ("scheduled", "2026-11-04T06:00:00", "2026-11-04T06:01:30", "done", 3, 3,
     [], {"Teszt Elek": {"Értékelés": 2, "Házi feladat": 1}}, 90.0, "2026/2027"),
    ("manual", "2026-11-04T08:00:00", "2026-11-04T08:00:40", "done_with_errors", 2, 3,
     ["Teszt Elek"], {"Teszt Elek": {"Értékelés": 1}}, 40.0, "2026/2027"),
    ("scheduled", "2026-11-04T10:00:00", None, "running", None, None,
     [], {}, None, "2026/2027"),
    ("manual", "2026-11-03T21:00:00", "2026-11-03T21:02:00", "error", 0, 0,
     ["Teszt Elek"], [], 120.0, "2026/2027"),
]
for (trigger, start, finish, status, okc, total, failed, new_events, dur, tanev) in rows:
    conn.execute(
        "INSERT INTO sync_runs (trigger, started_at, finished_at, status, ok_count,"
        " total_count, failed_students, new_events, duration_sec, tanev)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (trigger, start, finish, status, okc, total, json.dumps(failed, ensure_ascii=False),
         json.dumps(new_events, ensure_ascii=False), dur, tanev),
    )
conn.commit()
conn.close()

res = client.get("/api/sync_runs?limit=20")
data = res.get_json()
ok(res.status_code == 200 and len(data) == 4, f"mind a négy futás megjön ({len(data)})")
ok(data[0]["status"] == "error", "a legutóbbi futás van legelöl (id szerint csökkenő)")
ok(data[3]["new_event_count"] == 3, f"a new_events szótár összegződik ({data[3]['new_event_count']})")
ok(data[2]["failed_students"] == ["Teszt Elek"], "a hibás diákok listája parse-olva jön")
ok(data[2]["status"] == "done_with_errors", "a részleges hiba státusz megmarad")
ok(data[1]["duration_sec"] is None and data[1]["finished_at"] is None,
   "a futó futásnak nincs vége/ideje")

print("\n3) limit és lista-változat")
res = client.get("/api/sync_runs?limit=2")
ok(len(res.get_json()) == 2, f"a limit működik ({len(res.get_json())})")
conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO sync_runs (trigger, started_at, status, new_events) VALUES (?,?,?,?)",
    ("manual", "2026-11-04T11:00:00", "done", json.dumps([1, 2], ensure_ascii=False)),
)
conn.commit()
conn.close()
data = client.get("/api/sync_runs?limit=1").get_json()
ok(data and data[0]["new_event_count"] == 2, "a lista alakú new_events hossza is számít")

print("\n4) a felület tartalmazza a futástörténetet")
html = client.get("/").get_data(as_text=True)
js = client.get("/static/js/app-main.js").get_data(as_text=True)
ok('id="syncRunsTable"' in html and 'id="syncRunsSparkline"' in html,
   "a Rendszernapló fülön van táblázat és sparkline")
ok("loadSyncRuns" in js, "a betöltő JS-függvény hivatkozva van")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
