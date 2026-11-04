# -*- coding: utf-8 -*-
"""DB-indexek és sémaverzió (Kaneo #15)."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = tempfile.mkdtemp(prefix="kreta_idx_")
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

_hibak = []


def ok(cond, msg):
    print(("  OK   " if cond else "  HIBA ") + msg)
    if not cond:
        _hibak.append(msg)


kreta.init_db_extensions()
kreta.init_db_extensions()   # idempotencia
conn = sqlite3.connect(db)


def indexes(table):
    return {row[1] for row in conn.execute(f"PRAGMA index_list({table})").fetchall()}


print("1) indexek")
expected = {
    "esemenyek": {"idx_esemenyek_diak_hatarido", "idx_esemenyek_diak_bej", "idx_esemenyek_tanev"},
    "uzenetek": {"idx_uzenetek_diak_idopont", "idx_uzenetek_tanev"},
    "kifizetesek": {"idx_kifizetesek_diak"},
    "sync_runs": {"idx_sync_runs_started"},
    "hianyzasok": {"idx_hianyzasok_diak"},
    "igazolasok": {"idx_igazolasok_diak"},
}
for table, names in expected.items():
    got = indexes(table)
    missing = names - got
    ok(not missing, f"{table}: {sorted(names)} (hiányzó: {missing or 'nincs'})")

print("\n2) sémaverzió")
row = conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
ok(row and row[0] == "3", f"app_meta.schema_version = {row[0] if row else 'nincs'}")

print("\n3) ismételt init nem hibázik")
kreta.init_db_extensions()
ok(True, "a második init lefutott")

print("\n4) migráció előtti DB-másolat")
conn.execute("UPDATE app_meta SET value='2' WHERE key='schema_version'")
conn.commit()
conn.close()
kreta.init_db_extensions()
backups = list(Path(work).glob("kreta_adatok.db.bak-*"))
ok(bool(backups), f"készült DB-másolat ({[b.name for b in backups]})")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
