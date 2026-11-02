# -*- coding: utf-8 -*-
"""
#32 teszt: `app.ensure_db_schema` viselkedése bizonytalan adatbázis-állapotnál.

- zárolt DB: NEM indul init-db subprocess, a hívás False-t ad, és az önjavítás
  nincs véglegesen kikapcsolva (`_schema_failed` marad False);
- a zárolás megszűnte után a hiányzó séma bootstrapolható (True);
- séma meglétekor nincs bootstrap (False).
"""
import json
import os
import sqlite3
import sys
import tempfile
import shutil
import time
import types
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="kreta_dbguard_"))
(work / "config.json").write_text(
    json.dumps({"HEADLESS": True, "STUDENTS": []}, ensure_ascii=False), encoding="utf-8"
)
os.environ.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(work / "kreta_adatok.db"),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": str(work / "csat"),
    "KRETA_SCHEDULER_STATE_FILE": str(work / "scheduler_state.json"),
    "PYTHONIOENCODING": "utf-8",
})

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as kreta  # noqa: E402

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


sqlite3.connect(kreta.DB_FILE).close()  # üres DB, séma nélkül
# Az `import app` induláskor bootstrapolhat; a teszthez ismét "üres" DB kell.
_conn = sqlite3.connect(kreta.DB_FILE)
for _table in ("esemenyek", "uzenetek", "orarend", "hianyzasok", "igazolasok"):
    _conn.execute(f"DROP TABLE IF EXISTS {_table}")
_conn.commit()
_conn.close()

print("1) Zárolt adatbázis")
lock = sqlite3.connect(kreta.DB_FILE)
lock.execute("BEGIN EXCLUSIVE")

calls = []


class GuardSubprocess:
    @staticmethod
    def run(*args, **kwargs):
        calls.append(args)
        raise AssertionError("zárolt DB-nél nem indulhat init-db subprocess")


original_subprocess = kreta.subprocess
kreta.subprocess = types.SimpleNamespace(run=GuardSubprocess.run)
try:
    started = time.time()
    locked_result = kreta.ensure_db_schema(reason="lock-teszt")
    elapsed = time.time() - started
finally:
    kreta.subprocess = original_subprocess
    lock.rollback()
    lock.close()

ok(locked_result is False, f"False-t ad zárolt DB-nél ({elapsed:.1f} s)")
ok(calls == [], f"nem indult subprocess ({len(calls)} hívás)")
ok(kreta._schema_failed is False, "az önjavítás nincs véglegesen kikapcsolva")

print("\n2) A zárolás után bootstrap")
ok(kreta.ensure_db_schema(reason="bootstrap-teszt") is True, "a hiányzó séma létrejött (True)")
conn = sqlite3.connect(kreta.DB_FILE)
tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
conn.close()
ok("esemenyek" in tables, "az esemenyek tábla létrejött")
ok("hianyzasok" in tables and "orarend" in tables, "a hiányzás/órarend táblák is megvannak")

print("\n3) Meglévő séma")
ok(kreta.ensure_db_schema() is False, "séma meglétekor nincs bootstrap")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
