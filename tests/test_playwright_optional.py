# -*- coding: utf-8 -*-
"""
#138: a Playwright legyen opcionális a futásidejű (alap) image-ben.

A cél, hogy az alap image-ben ne legyen `playwright` csomag és Chromium, de a
szinkron `api` módban fusson, a `--init-db` séma pedig böngésző nélkül is
létrejöjjön. A böngészős fallback külön image-target (`:playwright`).

Ellenőrzések:
1. egyetlen gyökér modul sem importálja a `playwright`-ot modulszinten;
2. a `kreta_playwright.py` lazy importja a `main()`-ben van;
3. a `effective_sync_mode` hiányzó csomagnál `api`-ra vált;
4. a modul importálható és `init_db()` lefut (a `csatolmany_proba` oszloppal);
5. a `--init-db` külön folyamatban, config nélkül is működik.
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


def _module_level_playwright_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "playwright" for alias in node.names):
                found.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "playwright":
                found.append(node.lineno)
    return tree, found


print("1) Nincs modulszintű playwright import")
offenders = {}
for path in sorted(ROOT.glob("*.py")):
    _tree, found = _module_level_playwright_imports(path)
    if found:
        offenders[path.name] = found
ok(not offenders, f"egyik gyökér modul sem importálja a playwrightot modulszinten: {offenders or 'nincs'}")

tree = ast.parse((ROOT / "kreta_playwright.py").read_text(encoding="utf-8"))
main_node = next((node for node in tree.body
                  if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"), None)
lazy_in_main = bool(main_node) and any(
    isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "playwright"
    for node in ast.walk(main_node))
ok(lazy_in_main, "a playwright import a main()-ben van (lazy import)")

work = Path(tempfile.mkdtemp(prefix="kreta_pwoptional_"))
data = work / "data"
data.mkdir()
(data / "config.json").write_text(
    json.dumps({"HEADLESS": True, "SYNC_MODE": "api_first",
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

print("\n2) Mód-feloldás hiányzó böngészős csomagnál")
ok(result.returncode == 0 and "INIT_OK" in out,
   f"a modul importálható és init_db() lefut (exit={result.returncode})")
ok(payload.get("REQUESTED") == "api_first",
   f"a kért mód az api_first marad: {payload.get('REQUESTED')}")
available = payload.get("AVAILABLE") == "True"
expected_mode = "api_first" if available else "api"
ok(payload.get("MODE") == expected_mode,
   f"a tényleges mód a csomag meglététől függ: {payload.get('MODE')} (elérhető: {available})")
ok(payload.get("EFFECTIVE_API_FIRST") == "api",
   f"hiányzó csomagnál api_first -> api: {payload.get('EFFECTIVE_API_FIRST')}")
ok(payload.get("EFFECTIVE_API") == "api", "api mód változatlan")
ok(payload.get("EFFECTIVE_PLAYWRIGHT") == "playwright",
   "meglévő csomagnál a playwright mód megmarad")

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
