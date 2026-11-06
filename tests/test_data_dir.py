# -*- coding: utf-8 -*-
"""
A futásidejű adatok `data/` alá költöztetése (KRÉ-14 #98).

Ellenőrzi:
1. az útvonal-feloldás alapértékét (nincs env): új elrendezés = `data/`;
2. a visszafelé kompatibilitást: ha a gyökérben van DB, de a `data/` alatt nincs,
   akkor a régi (gyökér) elrendezés marad;
3. ha már a `data/` alatt van DB, az új elrendezés nyer (a gyökérben maradt
   fájlok nem zavarnak);
4. a `tools/migrate_local_data.py` dry-run / migráció / rollback körét.
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


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


def probe(app_dir):
    """A kreta_paths.py-t egy izolált mappába másolva, tiszta env-vel futtatjuk."""
    app_dir = Path(app_dir)
    app_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kreta_paths.py", app_dir / "kreta_paths.py")
    env = os.environ.copy()
    for key in ("KRETA_DATA_DIR", "KRETA_DB_FILE", "KRETA_CONFIG_FILE", "KRETA_LOG_FILE",
                "KRETA_CSATOLMANYOK_DIR", "KRETA_SCHEDULER_STATE_FILE", "KRETA_VERSION_FILE"):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    code = (
        "import json, kreta_paths as k\n"
        "print(json.dumps({'DATA_DIR': k.DATA_DIR, 'DB_FILE': k.DB_FILE,\n"
        "  'CSATOLMANYOK_DIR': k.CSATOLMANYOK_DIR, 'LEGACY': k.LEGACY_LAYOUT}))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=str(app_dir), env=env,
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [line for line in out.stdout.strip().splitlines() if line.startswith("{")]
    if not lines:
        raise SystemExit(f"probe hiba: {out.stdout}\n{out.stderr}")
    return json.loads(lines[-1])


work = Path(tempfile.mkdtemp(prefix="kreta_datadir_"))

print("1) Új alapértelmezés: minden a data/ alatt")
app1 = work / "app1"
vals = probe(app1)
ok(vals["DATA_DIR"] == "data", f"DATA_DIR = data ({vals['DATA_DIR']})")
ok(vals["DB_FILE"] == os.path.join("data", "kreta_adatok.db"), f"DB_FILE: {vals['DB_FILE']}")
ok(vals["CSATOLMANYOK_DIR"] == os.path.join("data", "csatolmanyok"),
   f"CSATOLMANYOK_DIR: {vals['CSATOLMANYOK_DIR']}")
ok(vals["LEGACY"] is False, "nincs legacy mód")

print("\n2) Visszafelé kompatibilitás: gyökér-DB -> régi elrendezés")
app2 = work / "app2"
app2.mkdir()
sqlite3.connect(app2 / "kreta_adatok.db").close()
vals = probe(app2)
ok(vals["LEGACY"] is True and vals["DATA_DIR"] == ".", f"legacy: {vals}")
ok(vals["CSATOLMANYOK_DIR"] == os.path.join("static", "csatolmanyok"),
   f"legacy csatolmány-út: {vals['CSATOLMANYOK_DIR']}")

print("\n3) Ha már a data/ alatt van DB, az új elrendezés nyer")
app3 = work / "app3"
(app3 / "data").mkdir(parents=True)
sqlite3.connect(app3 / "kreta_adatok.db").close()
sqlite3.connect(app3 / "data" / "kreta_adatok.db").close()
vals = probe(app3)
ok(vals["LEGACY"] is False and vals["DATA_DIR"] == "data", f"új elrendezés: {vals}")

print("\n4) Migrációs szkript: dry-run -> átmozgatás -> rollback")
mig = work / "mig"
(mig / "static" / "csatolmanyok").mkdir(parents=True)
(mig / "browser_user_data").mkdir()
(mig / "config.json").write_text('{"STUDENTS": []}', encoding="utf-8")
(mig / "sync.log").write_text("napló", encoding="utf-8")
(mig / "static" / "csatolmanyok" / "a.txt").write_text("x", encoding="utf-8")
(mig / "browser_user_data" / "profil.txt").write_text("x", encoding="utf-8")
db = sqlite3.connect(mig / "kreta_adatok.db")
db.execute("CREATE TABLE esemenyek (id INTEGER PRIMARY KEY)")
db.commit()
db.close()

tool = str(ROOT / "tools" / "migrate_local_data.py")
r = subprocess.run([sys.executable, tool, "--root", str(mig), "--dry-run"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
ok(r.returncode == 0 and "dry-run" in r.stdout, "dry-run lefut")
ok((mig / "kreta_adatok.db").exists() and not (mig / "data").exists(),
   "dry-run nem mozgat semmit")

r = subprocess.run([sys.executable, tool, "--root", str(mig)],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
ok(r.returncode == 0, f"migráció lefut (exit {r.returncode}): {r.stdout.strip()[-120:]}")
data = mig / "data"
ok((data / "config.json").is_file() and (data / "sync.log").is_file(), "fájlok a data/ alatt")
ok((data / "csatolmanyok" / "a.txt").is_file(), "csatolmányok a data/csatolmanyok alatt")
ok((data / "browser_user_data" / "profil.txt").is_file(), "böngészőprofil a data/ alatt")
ok((data / ".migration_log.json").is_file(), "migrációs napló készült")
ok(not (mig / "config.json").exists(), "a gyökér kiürült")

r = subprocess.run([sys.executable, tool, "--root", str(mig), "--rollback"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
ok(r.returncode == 0, f"rollback lefut (exit {r.returncode})")
ok((mig / "config.json").is_file() and (mig / "kreta_adatok.db").is_file(),
   "a fájlok visszakerültek a gyökérbe")
ok((mig / "static" / "csatolmanyok" / "a.txt").is_file(), "a csatolmányok visszakerültek")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
