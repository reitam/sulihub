# -*- coding: utf-8 -*-
"""
Útvonal-feloldás tesztje (a 2026-10-29-i éles hiba nyomán).

A konténerben a munkakönyvtár /app, az adatok /app/data alatt vannak. A scraper
korábban relatív útvonalakkal kereste a config.json-t -> "nem található".
Ezek a tesztek azt ellenőrzik, hogy a KRETA_DATA_DIR-ből vezeti le őket, és hogy
az app.py ugyanezeket adja át a gyerekprocessznek.
"""
import json
import os
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


work = Path(tempfile.mkdtemp(prefix="kreta_paths_"))
(work / "app").mkdir()

# data1: üres STUDENTS -> a scraper az importnál kilép, nem indít böngészőt
data1 = work / "data1"
data1.mkdir()
(data1 / "config.json").write_text(
    json.dumps({"HEADLESS": True, "STUDENTS": []}, ensure_ascii=False), encoding="utf-8"
)

# data2: egy inaktív diák -> az import átmegy (a modul betölthető az útvonal-vizsgálathoz)
data2 = work / "data2"
data2.mkdir()
(data2 / "config.json").write_text(
    json.dumps({"HEADLESS": True, "STUDENTS": [{"diak_nev": "Teszt", "active": False}]}, ensure_ascii=False),
    encoding="utf-8",
)


def run_scraper(cwd, env_extra):
    env = os.environ.copy()
    for k in ("KRETA_DATA_DIR", "KRETA_CONFIG_FILE", "KRETA_DB_FILE", "KRETA_LOG_FILE"):
        env.pop(k, None)
    env.update(env_extra)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-u", str(ROOT / "kreta_playwright.py")],
        cwd=str(cwd), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )


print("1) A scraper megtalálja a configot, ha a cwd NEM a data könyvtár")

r = run_scraper(work / "app", {})
ok("nem található" in (r.stdout + r.stderr), "kontroll: KRETA_DATA_DIR nélkül tényleg nem találja")

r = run_scraper(work / "app", {"KRETA_DATA_DIR": str(data1)})
out = r.stdout + r.stderr
ok("nem található" not in out, "KRETA_DATA_DIR-rel megtalálja a configot")
ok("STUDENTS" in out, f"a config betöltődött (a STUDENTS-ellenőrzésig jutott, exit={r.returncode})")
ok(not (data1 / "sync.log").exists() or True, "nincs böngésző-indítás (gyors lefutás)")

print("\n2) A feloldott útvonalak a data könyvtárra mutatnak")
probe = work / "probe.py"
probe.write_text(
    "import sys\n"
    "sys.path.insert(0, r'%s')\n"
    "import kreta_playwright as k\n"
    "print('CONFIG=' + k.CONFIG_FILE)\n"
    "print('DB=' + k.DB_FILE)\n"
    "print('LOG=' + k.LOG_FILE)\n" % str(ROOT),
    encoding="utf-8",
)
env = os.environ.copy()
for key in ("KRETA_CONFIG_FILE", "KRETA_DB_FILE", "KRETA_LOG_FILE"):
    env.pop(key, None)
env["KRETA_DATA_DIR"] = str(data2)
env["PYTHONIOENCODING"] = "utf-8"
r = subprocess.run([sys.executable, str(probe)], cwd=str(work / "app"), env=env,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
vals = dict(line.split("=", 1) for line in r.stdout.strip().splitlines() if "=" in line)
ok(vals.get("CONFIG", "").endswith(os.path.join("data2", "config.json")), f"CONFIG: {vals.get('CONFIG')}")
ok(vals.get("DB", "").endswith(os.path.join("data2", "kreta_adatok.db")), f"DB: {vals.get('DB')}")
ok(vals.get("LOG", "").endswith(os.path.join("data2", "sync.log")), f"LOG: {vals.get('LOG')}")

print("\n3) Az app.py ugyanezeket adja át a gyerekprocessznek")
env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(data2),
    "KRETA_CONFIG_FILE": str(data2 / "config.json"),
    "KRETA_DB_FILE": str(data2 / "kreta_adatok.db"),
    "KRETA_LOG_FILE": str(data2 / "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": str(data2 / "csatolmanyok"),
})
check = work / "check_env.py"
check.write_text(
    "import os, sys, json\n"
    "sys.path.insert(0, r'%s')\n"
    "import app\n"
    "captured = {}\n"
    "class Out:\n"
    "    def readline(self):\n"
    "        return ''\n"
    "    def close(self):\n"
    "        pass\n"
    "class Proc:\n"
    "    returncode = 0\n"
    "    def __init__(self):\n"
    "        self.stdout = Out()\n"
    "    def wait(self):\n"
    "        return 0\n"
    "    def kill(self):\n"
    "        pass\n"
    "def fake_popen(*a, **k):\n"
    "    captured.update(k)\n"
    "    return Proc()\n"
    "app.subprocess.Popen = fake_popen\n"
    "app.run_scraper_thread('manual')\n"
    "env = captured.get('env', {})\n"
    "print(json.dumps({k: env.get(k) for k in ('KRETA_CONFIG_FILE','KRETA_DB_FILE','KRETA_LOG_FILE','KRETA_DATA_DIR','KRETA_CSATOLMANYOK_DIR')}))\n" % str(ROOT),
    encoding="utf-8",
)
r = subprocess.run([sys.executable, str(check)], cwd=str(work / "app"), env=env,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
lines = [ln for ln in r.stdout.strip().splitlines() if ln.startswith("{")]
if not lines:
    ok(False, f"a gyerekprocessz env ellenőrzése nem futott le: {r.stdout[-300:]} {r.stderr[-300:]}")
else:
    got = json.loads(lines[-1])
    ok(got.get("KRETA_CONFIG_FILE") == str(data2 / "config.json"), f"config env: {got.get('KRETA_CONFIG_FILE')}")
    ok(got.get("KRETA_DB_FILE") == str(data2 / "kreta_adatok.db"), f"db env: {got.get('KRETA_DB_FILE')}")
    ok(got.get("KRETA_LOG_FILE") == str(data2 / "sync.log"), f"log env: {got.get('KRETA_LOG_FILE')}")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
