# -*- coding: utf-8 -*-
"""
Teljesítmény-mérés (Kaneo #109): /api/ma, /api/kereses, /api/statisztika, /api/atlagok.

Nagyobb (5 000 esemény + 500 üzenet) fixture-ön méri a válaszidőket; a küszöbök
env-ből állíthatók (`PERF_THRESHOLD_MS`, alap 500 ms). A fast csomag része.
"""
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_perf_"))
db = work / "kreta_adatok.db"
config = {"STUDENTS": [{"diak_nev": "PerfDiak", "enable_rewards": True, "active": False}]}
(work / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": str(work / "csat"),
    "KRETA_SCHEDULER_STATE_FILE": str(work / "scheduler_state.json"),
    "KRETA_VERSION_FILE": str(work / "version.txt"),
    "PYTHONIOENCODING": "utf-8",
})
os.environ.update({k: v for k, v in env.items() if k.startswith("KRETA")})

subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

conn = sqlite3.connect(db)
mai = date(2026, 11, 8)
tantargyak = ["Matematika", "Irodalom", "Fizika", "Kémia", "Biológia", "Történelem"]
sorok = []
for i in range(5000):
    nap = mai - timedelta(days=i % 120)
    sorok.append((
        "PerfDiak", "Értékelés", tantargyak[i % len(tantargyak)],
        f"Jegy({1 + i % 5})", 1 + i % 5, [50, 100, 200][i % 3],
        nap.strftime("%Y. %m. %d."), "", f"Téma {i}", "", "Tanár", 0, "2026/2027"))
conn.executemany(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " suly_szazalek, bej_datum, hatarido, tema, cim, ertekelo, kesz, tanev)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", sorok)
uzenetek = []
for i in range(500):
    uzenetek.append((
        "PerfDiak", f"Osztalyfonok{i}", f"Targy {i}", "2026. 10. 20.",
        f"Szoveg {i} " + ("törtek " * 20)))
conn.executemany(
    "INSERT INTO uzenetek (diak_nev, felado, targy, idopont, szoveg)"
    " VALUES (?,?,?,?,?)", uzenetek)
conn.commit()
conn.close()

sys.path.insert(0, str(ROOT))
import app as kreta  # noqa: E402

client = kreta.app.test_client()
_hibak = []
KUSZOB = float(os.environ.get("PERF_THRESHOLD_MS", "500"))


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


def meres(url, ismetles=3):
    idok = []
    for _ in range(ismetles):
        t0 = time.perf_counter()
        r = client.get(url)
        idok.append((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            return None, r.status_code
    return statistics.median(idok), 200


print(f"1) Végpontok mérése (5 000 esemény, 500 üzenet; küszöb {KUSZOB:.0f} ms)")
VEGPONTOK = [
    ("/api/ma?diak=PerfDiak&datum=2026-11-08", "/api/ma"),
    ("/api/kereses?q=t%C3%B6rtek&limit=20", "/api/kereses"),
    ("/api/statisztika?diak=PerfDiak&tanev=2026%2F2027", "/api/statisztika"),
    ("/api/atlagok?diak=PerfDiak&tanev=2026%2F2027", "/api/atlagok"),
]
for url, nev in VEGPONTOK:
    ido, status = meres(url)
    ok(status == 200 and ido is not None and ido <= KUSZOB,
       f"{nev}: {ido:.1f} ms (HTTP {status})" if ido is not None else f"{nev}: HTTP {status}")

print("\n2) A kereső FTS-t használ (a nagy adaton is)")
conn = sqlite3.connect(db)
fts = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name LIKE '%_fts'")}
n_fts = conn.execute("SELECT COUNT(*) FROM esemenyek_fts").fetchone()[0] if "esemenyek_fts" in fts else 0
conn.close()
ok("esemenyek_fts" in fts and n_fts == 5000, f"FTS index: {n_fts} sor")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
