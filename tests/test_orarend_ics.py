# -*- coding: utf-8 -*-
"""Órarend ICS export (Kaneo #73) — temp adatbázison."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = tempfile.mkdtemp(prefix="kreta_ics_")
db = os.path.join(work, "kreta_adatok.db")
os.environ.update({
    "KRETA_DATA_DIR": work,
    "KRETA_DB_FILE": db,
    "KRETA_CONFIG_FILE": os.path.join(work, "config.json"),
    "KRETA_LOG_FILE": os.path.join(work, "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csat"),
    "KRETA_SCHEDULER_STATE_FILE": os.path.join(work, "scheduler_state.json"),
    "KRETA_TODAY": "2026-11-04",
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
    "INSERT INTO orarend (diak_nev, kezdo_idopont, zaro_idopont, nap, tantargy, tanar, terem)"
    " VALUES (?,?,?,?,?,?,?)",
    ("Teszt Elek", "2026-11-02T08:00:00", "2026-11-02T08:45:00", "Hétfő",
     "Fizika", "Tanár", "101"),
)
conn.execute(
    "INSERT INTO orarend (diak_nev, kezdo_idopont, zaro_idopont, nap, tantargy, tanar, terem)"
    " VALUES (?,?,?,?,?,?,?)",
    ("Másik Diák", "2026-11-03T09:00:00", "2026-11-03T09:45:00", "Kedd",
     "Kémia", "Tanár2", "102"),
)
conn.commit()
conn.close()

client = kreta.app.test_client()

print("1) heti export (egy diák)")
res = client.get("/api/orarend/export_ics?diak=Teszt%20Elek&period=het&datum=2026-11-04")
ics = res.get_data(as_text=True)
ok(res.status_code == 200 and "text/calendar" in res.headers.get("Content-Type", ""),
   f"200 + text/calendar ({res.status_code})")
ok(ics.count("BEGIN:VEVENT") == 1, "egy heti minta → egy VEVENT")
ok("RRULE:FREQ=WEEKLY;UNTIL=20261108T235959Z" in ics, "a hét végéig ismétlődik")
ok("SUMMARY:Fizika" in ics and "LOCATION:101" in ics, "tantárgy és terem")
ok("DTSTART:20261102T070000Z" in ics, "hétfő 08:00 (CET → 07:00Z)")
ok("attachment" in res.headers.get("Content-Disposition", ""), "mellékletként jön")

print("\n2) hónap / félév / tanév")
for period, until in (("honap", "20261130"), ("felev", "20270131"),
                      ("tanev", "20270831")):
    res = client.get(f"/api/orarend/export_ics?diak=Teszt%20Elek&period={period}&datum=2026-11-04")
    ics = res.get_data(as_text=True)
    ok(f"UNTIL={until}T235959Z" in ics, f"{period}: UNTIL {until}")

print("\n3) összes diák")
res = client.get("/api/orarend/export_ics?period=honap&datum=2026-11-04")
ics = res.get_data(as_text=True)
ok(ics.count("BEGIN:VEVENT") == 2, "két diák → két VEVENT")
ok("SUMMARY:[Teszt Elek] Fizika" in ics and "SUMMARY:[Másik Diák] Kémia" in ics,
   "többgyermekes cím-prefix")

print("\n4) üres órarend")
res = client.get("/api/orarend/export_ics?diak=Nincs%20Ilyen&period=het&datum=2026-11-04")
ics = res.get_data(as_text=True)
ok(res.status_code == 200 and "BEGIN:VCALENDAR" in ics and "BEGIN:VEVENT" not in ics,
   "ismeretlen diák → üres, érvényes naptár")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
