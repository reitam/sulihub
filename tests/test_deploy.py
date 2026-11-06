# -*- coding: utf-8 -*-
"""
Deploy-konzisztencia: a Docker képben legyen minden, ami kell.

Egy 2026-11-02-i éles hiba miatt készült: a `Dockerfile` csak az `app.py`-t és a
`kreta_playwright.py`-t másolta be, ezért a v1.6.0 új moduljai (`kreta_api.py`
stb.) hiányoztak a képből → `ModuleNotFoundError: No module named 'kreta_api'`,
és minden szinkron azonnal `error` lett. A `requests` sem volt a
`requirements.txt`-ben (a Playwright nem hozza magával).

A teszt statikusan ellenőrzi:
1. a Dockerfile minden gyökér `*.py` modult bemásol (explicit lista vagy `*.py` glob);
2. a `requirements.txt` lefedi a gyökér modulok harmadik féltől származó importjait;
3. a `.dockerignore` nem zárja ki a szükséges fájlokat, a `config.json` viszont nem
   kerülhet a képbe.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

root_modules = sorted(path.stem for path in ROOT.glob("*.py"))
print("gyökér modulok:", ", ".join(root_modules))

print("\n1) Dockerfile: minden gyökér modul bekerül a képbe")
copy_lines = [line.strip() for line in dockerfile.splitlines()
              if line.strip().upper().startswith("COPY ")]
copy_text = " ".join(copy_lines)
ok(bool(copy_lines), f"van COPY utasítás ({len(copy_lines)})")
glob_copy = re.search(r"COPY\s+\*\.py\b", copy_text) is not None
missing = []
for module in root_modules:
    explicit = re.search(rf"COPY[^\n]*\b{re.escape(module)}\.py\b", dockerfile) is not None
    if not (explicit or glob_copy):
        missing.append(module)
ok(not missing, f"minden modul bemásolva (hiányzó: {missing or 'nincs'})")
ok(glob_copy or len(copy_lines) >= 3, "a kódmásolás külön lépésben történik")

print("\n2) requirements.txt: a harmadik féltől származó importok lefedve")
imports = set()
for path in ROOT.glob("*.py"):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imports.add(node.module.split(".")[0])
stdlib = set(sys.stdlib_module_names)
local = set(root_modules)
third_party = sorted(imports - stdlib - local - {"__future__"})
print("   harmadik féltől:", ", ".join(third_party))
# csomagnév → a requirements-ben szereplő név (ékezet/kötőjel nélkül)
aliases = {
    "flask": "flask",
    "playwright": "playwright",
    "reportlab": "reportlab",
    "waitress": "waitress",
    "requests": "requests",
    "openpyxl": "openpyxl",
    "werkzeug": "flask",   # a Flask része, külön nem kell a requirements-be
}
not_declared = [name for name in third_party
                if aliases.get(name, name).lower() not in requirements]
ok(not not_declared, f"minden import a requirements-ben (hiányzó: {not_declared or 'nincs'})")
ok("requests" in requirements, "a requests (kreta_api HTTP) benne van")

print("\n3) .dockerignore: a szükséges fájlok nem esnek ki, a titkok nem mennek be")
ignored = {line.strip().rstrip("/") for line in dockerignore.splitlines()
           if line.strip() and not line.strip().startswith("#")}
ok(not (set(f"{module}.py" for module in root_modules) & ignored),
   "egyik gyökér modult sem zárja ki a .dockerignore")
ok("config.json" in ignored, "a config.json (jelszavak) ki van zárva a képből")
ok("config.json" not in re.sub(r"#.*", "", dockerfile),
   "a Dockerfile nem másolja be a config.json-t")
ok("tests" in ignored, "a tesztek nem kerülnek a képbe")
ok("docs" in ignored, "a docs/ (dokumentáció) nem kerül a képbe")
ok("data" in ignored, "a data/ (futásidejű adatok) nem kerül a képbe")
ok("api_tokens.json" in ignored, "az api_tokens.json (tokenek) ki van zárva a képből")
ok({".opencode", "poc", "tools"} <= ignored,
   "a fejlesztői mappák (.opencode, poc, tools) ki vannak zárva a képből")

print("\n3b) deploy.ps1: csak a futásidejű fájlok mennek fel")
deploy_src = (ROOT / "deploy.ps1").read_text(encoding="utf-8", errors="replace")
ok('"api_tokens.json"' in deploy_src or "api_tokens.json" in deploy_src,
   "a deploy kizárja az api_tokens.json-t")
ok('"OSSZEFOGLALO-*.md"' in deploy_src, "a deploy kizárja az összefoglaló markdownokat")
ok('"docs"' in deploy_src and "REMOTE_DIR_PLACEHOLDER/docs" in deploy_src,
   "a docs/ mappa nem kerül a szerverre, és a szerveroldali tisztítás eltávolítja")
ok('"data"' in deploy_src, "a deploy kizárja a data/ (futásidejű adatok) mappát")
ok('"$SourceDir\\static\\csatolmanyok"' in deploy_src,
   "a csatolmányok kizárása abszolút úttal történik (robocopy /XD)")
ok("REMOTE_DIR_PLACEHOLDER/tools" in deploy_src
   and "REMOTE_DIR_PLACEHOLDER/poc" in deploy_src,
   "a szerveroldali tisztítás eltávolítja a fejlesztői mappákat")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
