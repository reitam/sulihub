# -*- coding: utf-8 -*-
"""
#64: a szinkron kizárólag a Kréta mobil API-ból fut, böngésző nélkül.

A böngészős (Playwright) scraper a v2.5.0-ben kikerült. A Playwright a
**böngészős UI-tesztek** fejlesztői függősége marad (`requirements-playwright.txt`),
a KRÉTA-adatlekéréshez nincs köze.

Ellenőrzések:
1. egyetlen gyökér modul sem importálja a `playwright`-ot (sehol a kódban);
2. az örökölt `api_first`/`playwright` config-értékek `api`-ra válnak;
3. a szinkron modul importálható és `init_db()` lefut (a `csatolmany_proba` oszloppal);
4. a `--init-db` külön folyamatban, config nélkül is működik.
"""
import ast
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


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


def _playwright_import_lines(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "playwright" for alias in node.names):
                found.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "playwright":
                found.append(node.lineno)
    return found


print("1) Nincs playwright import a gyökér modulokban")
offenders = {}
for path in sorted(ROOT.glob("*.py")):
    found = _playwright_import_lines(path)
    if found:
        offenders[path.name] = found
ok(not offenders,
   f"egyik gyökér modul sem importálja a playwrightot: {offenders or 'nincs'}")
ok(not (ROOT / "kreta_shadow.py").exists(),
   "az árnyék-ellenőrző modul (Playwright-függő) törölve")

work = Path(tempfile.mkdtemp(prefix="kreta_apionly_"))
data = work / "data"
data.mkdir()
(data / "config.json").write_text(
    json.dumps({"SCRAPE_MESSAGES": True, "SYNC_MODE": "api_first",
                "STUDENTS": [{"diak_nev": "Teszt", "active": False}]}, ensure_ascii=False),
    encoding="utf-8")

probe = work / "probe.py"
probe.write_text(
    """# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r'{root}')
import kreta_playwright as k
print('MODE=' + k.SYNC_MODE)
print('REQUESTED=' + k._requested_sync_mode)
print('AVAILABLE=' + str(k.PLAYWRIGHT_AVAILABLE))
print('EFFECTIVE_API_FIRST=' + k.effective_sync_mode('api_first', False))
print('EFFECTIVE_API=' + k.effective_sync_mode('api', False))
print('EFFECTIVE_PLAYWRIGHT=' + k.effective_sync_mode('playwright', True))
k.init_db()
print('INIT_OK')
""".replace("{root}", str(ROOT)),
    encoding="utf-8",
)

env = os.environ.copy()
env["KRETA_DATA_DIR"] = str(data)
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"
for key in ("KRETA_CONFIG_FILE", "KRETA_DB_FILE", "KRETA_LOG_FILE"):
    env.pop(key, None)

result = subprocess.run([sys.executable, str(probe)], cwd=str(work), env=env,
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=120)
out = result.stdout
payload = {}
for line in out.splitlines():
    if "=" in line and line.split("=", 1)[0] in {
            "MODE", "REQUESTED", "AVAILABLE", "EFFECTIVE_API_FIRST",
            "EFFECTIVE_API", "EFFECTIVE_PLAYWRIGHT"}:
        key, value = line.split("=", 1)
        payload[key] = value

print("\n2) Az örökölt böngészős mód-értékek api-ra váltanak")
ok(result.returncode == 0 and "INIT_OK" in out,
   f"a modul importálható és init_db() lefut (exit={result.returncode})")
ok(payload.get("REQUESTED") == "api_first",
   f"a kért (örökölt) mód megmarad kérésként: {payload.get('REQUESTED')}")
expected_mode = "api_first" if payload.get("AVAILABLE") == "True" else "api"
ok(payload.get("MODE") == expected_mode,
   f"a tényleges mód: {payload.get('MODE')} (elérhető: {payload.get('AVAILABLE')})")
ok(payload.get("EFFECTIVE_API_FIRST") == "api",
   f"örökölt api_first böngésző nélkül -> api: {payload.get('EFFECTIVE_API_FIRST')}")
ok(payload.get("EFFECTIVE_API") == "api", "api mód változatlan")
ok(payload.get("EFFECTIVE_PLAYWRIGHT") == "playwright",
   "a mód-feloldás tiszta logikája változatlan")

print("\n3) Séma: a csatolmány-pótlás oszlopa létrejön")
db = data / "kreta_adatok.db"
ok(db.exists(), f"a DB létrejött: {db.name}")
try:
    conn = sqlite3.connect(db)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(uzenetek)")]
    conn.close()
except sqlite3.Error as exc:
    cols = []
    print("   sqlite hiba:", exc)
ok("csatolmany_proba" in cols, f"az uzenetek.csatolmany_proba oszloppal: {cols}")

print("\n4) --init-db config nélkül, külön folyamatban")
init_data = work / "initdb"
init_env = os.environ.copy()
init_env["KRETA_DATA_DIR"] = str(init_data)
init_env["PYTHONIOENCODING"] = "utf-8"
init_env["PYTHONUTF8"] = "1"
for key in ("KRETA_CONFIG_FILE", "KRETA_DB_FILE", "KRETA_LOG_FILE"):
    init_env.pop(key, None)
init_result = subprocess.run([sys.executable, str(ROOT / "kreta_playwright.py"), "--init-db"],
                             cwd=str(ROOT), env=init_env, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120)
ok(init_result.returncode == 0, f"--init-db exit=0 (exit={init_result.returncode})")
ok((init_data / "kreta_adatok.db").exists(), "a --init-db létrehozta a DB-t")
ok("Séma kész" in (init_result.stdout or ""), "a --init-db visszajelzése megvan")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
