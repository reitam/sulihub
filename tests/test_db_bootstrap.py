# -*- coding: utf-8 -*-
"""
Adatbázis-séma bootstrap: hiányzó vagy üres DB fájl esetén se legyen 500.

Háttér: a Flask eddig csak a saját kiegészítő tábláit hozta létre, az
`esemenyek`/`uzenetek` táblákat a scraper (`kreta_playwright.init_db`) hozza
létre. Ha a `kreta_adatok.db`-t kézzel áthelyezték/törölték, üres fájl
keletkezett, és minden oldal „Internal Server Error"-t adott.

A teszt külön folyamatban importálja az appot (mint a migrációs teszt), így a
valódi adatokat nem érinti.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_hibak = []
CORE = ("esemenyek", "uzenetek", "orarend", "hianyzasok", "igazolasok",
        "kifizetesek", "sync_runs", "app_meta")


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


def tables(db_path):
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
    finally:
        conn.close()


def make_env(work, db):
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
    return env


def run_app_import(work, db):
    """Az app importja (init_db_extensions) külön folyamatban."""
    probe = work / "probe_app.py"
    probe.write_text(
        "import sys\n"
        f"sys.path.insert(0, r'{ROOT}')\n"
        "import app as kreta\n"
        "print('IMPORT_OK')\n",
        encoding="utf-8",
    )
    return subprocess.run([sys.executable, str(probe)], cwd=str(work),
                          env=make_env(work, db), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)


def write_config(work):
    (work / "config.json").write_text(
        json.dumps({"HEADLESS": True, "STUDENTS": []}), encoding="utf-8")


print("1) Hiányzó DB fájl: importkor létrejön a teljes séma")
work = Path(tempfile.mkdtemp(prefix="kreta_boot_"))
db = work / "kreta_adatok.db"
write_config(work)
result = run_app_import(work, db)
ok(result.returncode == 0, f"az app importja lefutott (exit={result.returncode})")
found = tables(db)
missing = [t for t in CORE if t not in found]
ok(not missing, f"mind a 8 tábla megvan (hiányzó: {missing or 'nincs'})")
ok("Séma létrehozva" in result.stdout, "a napló jelzi a séma létrehozását")
ok(os.path.exists(db), "a DB fájl létrejött")

print("\n2) Második indítás: nincs újabb bootstrap")
again = run_app_import(work, db)
ok(again.returncode == 0, "a második import is lefut")
ok("Séma létrehozva" not in again.stdout, "a kész sémán nem fut le újra a bootstrap")

print("\n3) Üres (0 bájtos) DB fájl")
work2 = Path(tempfile.mkdtemp(prefix="kreta_boot2_"))
db2 = work2 / "kreta_adatok.db"
write_config(work2)
db2.write_text("", encoding="utf-8")
result3 = run_app_import(work2, db2)
ok(result3.returncode == 0, f"az app importja üres fájllal is lefut (exit={result3.returncode})")
missing = [t for t in CORE if t not in tables(db2)]
ok(not missing, f"üres fájlból is lett teljes séma (hiányzó: {missing or 'nincs'})")

print("\n4) Nem üres, de séma nélküli DB (pl. félig létrejött fájl)")
work3 = Path(tempfile.mkdtemp(prefix="kreta_boot3_"))
db3 = work3 / "kreta_adatok.db"
write_config(work3)
conn = sqlite3.connect(db3)
conn.execute("CREATE TABLE proba (id INTEGER PRIMARY KEY)")
conn.commit()
conn.close()
result4 = run_app_import(work3, db3)
ok(result4.returncode == 0, f"az app importja félig kész DB-vel is lefut (exit={result4.returncode})")
missing = [t for t in CORE if t not in tables(db3)]
ok(not missing, f"a hiányzó táblák pótlódtak (hiányzó: {missing or 'nincs'})")

print("\n5) `kreta_playwright.py --init-db` önmagában")
work4 = Path(tempfile.mkdtemp(prefix="kreta_boot4_"))
db4 = work4 / "kreta_adatok.db"
write_config(work4)
init_run = subprocess.run([sys.executable, str(ROOT / "kreta_playwright.py"), "--init-db"],
                          cwd=str(work4), env=make_env(work4, db4), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=180)
ok(init_run.returncode == 0, f"az --init-db lefutott (exit={init_run.returncode})")
scraper_tables = ("esemenyek", "uzenetek", "orarend", "hianyzasok", "igazolasok")
missing = [t for t in scraper_tables if t not in tables(db4)]
ok(not missing, f"a scraper táblái megvannak (hiányzó: {missing or 'nincs'})")
ok("Séma kész" in init_run.stdout, "a szkript visszajelzést ad")

for path in (work, work2, work3, work4):
    shutil.rmtree(path, ignore_errors=True)

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
