# -*- coding: utf-8 -*-
"""
Egyszeri migráció: a régi scheduler_state.json -> sync_runs tábla.

Külön folyamatban fut, mert a migráció az app importjakor (init_db_extensions)
történik, és csak akkor, ha a sync_runs még üres.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_hibak = []


def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)


work = Path(tempfile.mkdtemp(prefix="kreta_migr_"))
db = work / "kreta_adatok.db"
sqlite3.connect(db).close()

(work / "config.json").write_text(
    json.dumps({"HEADLESS": True, "STUDENTS": []}), encoding="utf-8"
)
state = {
    "last_run_started": "2026-10-29T01:08:33",
    "last_trigger": "scheduled",
    "last_status": "done",
    "last_run_finished": "2026-10-29T01:11:14",
    "last_failed_students": ["Teszt Elek"],
    "last_ok": 2,
    "last_total": 3,
    "last_stale_alert": "2026-10-29T00:00:00",
}
(work / "scheduler_state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

probe = work / "probe.py"
probe.write_text(
    """import json, sys
sys.path.insert(0, r'{root}')
import app as kreta
print("STATE=" + json.dumps(kreta.scheduler_state(), ensure_ascii=False))
print("META=" + str(kreta.get_meta("last_stale_alert")))
print("MIGRATED_FILE=" + str(__import__("os").path.exists(r'{state}.migrated')))
print("JSON_STILL=" + str(__import__("os").path.exists(r'{state}')))
""".format(root=str(ROOT), state=str(work / "scheduler_state.json")),
    encoding="utf-8",
)

env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "PYTHONIOENCODING": "utf-8",
})
for key in ("KRETA_SCHEDULER_STATE_FILE", "KRETA_CSATOLMANYOK_DIR"):
    env.pop(key, None)

r = subprocess.run([sys.executable, str(probe)], cwd=str(work), env=env,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
vals = {}
for line in r.stdout.splitlines():
    if "=" in line:
        k_, v = line.split("=", 1)
        vals[k_] = v
if not vals:
    print(r.stdout[-500:], r.stderr[-800:])

print("1) A JSON átkerült a DB-be")
st = json.loads(vals.get("STATE", "{}"))
ok(st.get("last_status") == "done", f"státusz: {st.get('last_status')}")
ok(st.get("last_trigger") == "scheduled", f"trigger: {st.get('last_trigger')}")
ok(st.get("last_run_started") == "2026-10-29T01:08:33", f"kezdés: {st.get('last_run_started')}")
ok(st.get("last_ok") == 2 and st.get("last_total") == 3, f"ok/total: {st.get('last_ok')}/{st.get('last_total')}")
ok(st.get("last_failed_students") == ["Teszt Elek"], f"hibás diák: {st.get('last_failed_students')}")
ok(st.get("last_scheduled_run") == "2026-10-29T01:08:33", f"ütemezett futás is: {st.get('last_scheduled_run')}")

print("\n2) Meta és fájlkezelés")
ok(vals.get("META") == "2026-10-29T00:00:00", f"last_stale_alert átvéve: {vals.get('META')}")
ok(vals.get("MIGRATED_FILE") == "True", "a régi JSON .migrated néven megmarad")
ok(vals.get("JSON_STILL") == "False", "az eredeti JSON már nincs a helyén")

print("\n3) Második indítás: nincs duplikáció")
r2 = subprocess.run([sys.executable, str(probe)], cwd=str(work), env=env,
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
conn = sqlite3.connect(str(db))
count = conn.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0]
conn.close()
ok(count == 1, f"továbbra is 1 futás-sor: {count}")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
