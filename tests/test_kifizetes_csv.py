# -*- coding: utf-8 -*-
"""Zsebpénz CSV export (Kaneo #11)."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = tempfile.mkdtemp(prefix="kreta_csv_")
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
conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO kifizetesek (diak_nev, kezdo_datum, zaro_datum, kifizetve, osszeg)"
    " VALUES (?,?,?,?,?)",
    ("Teszt Elek", "2026-10-01", "2026-10-31", 1, 500),
)
conn.execute(
    "INSERT INTO kifizetesek (diak_nev, kezdo_datum, zaro_datum, kifizetve, osszeg)"
    " VALUES (?,?,?,?,?)",
    ("Másik Diák", "2026-10-01", "2026-10-31", 0, 300),
)
conn.commit()
conn.close()

client = kreta.app.test_client()
res = client.get("/api/kifizetesek/export.csv")
text = res.get_data(as_text=True)
ok(res.status_code == 200, f"a CSV végpont 200 ({res.status_code})")
ok(text.startswith("\ufeff"), "UTF-8 BOM (Excel-kompatibilis)")
ok("diak_nev;kezdo_datum;zaro_datum;osszeg;kifizetve;kategoria;megjegyzes" in text,
   "a fejléc tartalmazza a kért oszlopokat")
ok("Teszt Elek;2026-10-01;2026-10-31;500;igen;zsebpenz" in text,
   "a sor adatai helyesek")
ok("Másik Diák;2026-10-01;2026-10-31;300;nem;zsebpenz" in text,
   "a kifizetetlen sor is exportálódik")
ok("attachment" in res.headers.get("Content-Disposition", ""), "mellékletként jön")

res = client.get("/api/kifizetesek/export.csv?diak=Teszt%20Elek")
text = res.get_data(as_text=True)
ok("Teszt Elek" in text and "Másik Diák" not in text, "a diák-szűrő működik")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
