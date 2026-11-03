# -*- coding: utf-8 -*-
"""
Karbantarthatósági tesztek (Kaneo #12 és #17).

#12 — külső CDN-hivatkozások vendorolása:
  a `templates/index.html` nem hivatkozik külső http(s) erőforrásra, minden
  `static/vendor/...` fájl létezik és nem üres, és a vendor CSS-ek `url(...)`
  hivatkozásai (FontAwesome webfontok) is helyben megvannak.

#17 — apróságok:
  1. a gyökér `*.py` modulok `SyntaxWarning` nélkül fordulnak;
  2. a `config.json.example` érvényes JSON, két diákkal;
  3. a frontendben nincs hivatkozás a törölt `autoSyncAlert` blokkra.
"""
import json
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


tpl = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

print("1) #12: nincs külső CDN-hivatkozás")
external = re.findall(r'(?:href|src)="(https?://[^"]+)"', tpl)
ok(not external, f"a sablon nem hivatkozik külső URL-re (talált: {external or 'nincs'})")

print("\n2) #12: a vendorolt fájlok léteznek")
assets = re.findall(r"url_for\('static', filename='([^']+)'\)", tpl)
vendor = sorted(a for a in assets if a.startswith("vendor/"))
ok(len(vendor) >= 12, f"legalább 12 vendor-állomány hivatkozva van ({len(vendor)})")
missing = []
for rel in vendor:
    path = ROOT / "static" / rel
    if not path.is_file() or path.stat().st_size == 0:
        missing.append(rel)
ok(not missing, f"minden hivatkozott vendor-fájl létezik (hiányzó: {missing or 'nincs'})")

print("\n3) #12: a vendor CSS-ek belső hivatkozásai (webfontok) is helyben vannak")
font_missing = []
font_count = 0
for css in sorted((ROOT / "static" / "vendor").rglob("*.css")):
    text = css.read_text(encoding="utf-8", errors="replace")
    for raw in re.findall(r"url\(([^)]+)\)", text):
        ref = raw.strip("'\" ")
        if ref.startswith(("data:", "http://", "https://", "//")):
            continue
        font_count += 1
        target = (css.parent / ref).resolve()
        if not target.is_file():
            font_missing.append(f"{css.name} -> {ref}")
ok(not font_missing,
   f"a CSS-ek összes relatív hivatkozása megvan ({font_count} db; hiányzó: {font_missing or 'nincs'})")

print("\n4) #17: a Python modulok SyntaxWarning nélkül fordulnak")
warning_files = []
for path in sorted(ROOT.glob("*.py")):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    bad = [w for w in caught if issubclass(w.category, SyntaxWarning)]
    if bad:
        warning_files.append(f"{path.name}: {bad[0].message}")
ok(not warning_files, f"nincs SyntaxWarning (talált: {warning_files or 'nincs'})")

print("\n5) #17: a config.json.example érvényes JSON")
try:
    example = json.loads((ROOT / "config.json.example").read_text(encoding="utf-8"))
    diakok = example.get("STUDENTS") or []
    ok(len(diakok) == 2, f"a példa parse-olható, {len(diakok)} diák szerepel benne")
    ok(all("diak_nev" in d and "institute_code" in d for d in diakok),
       "a példa diákjai tartalmazzák a kötelező mezőket")
except Exception as e:
    ok(False, f"a config.json.example nem parse-olható: {type(e).__name__} {e}")

print("\n6) #17: nincs hivatkozás a törölt autoSyncAlert blokkra")
ok("autoSyncAlert" not in tpl and "autoAlert" not in tpl,
   "a frontendben nincs autoSyncAlert / autoAlert hivatkozás")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
