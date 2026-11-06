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

print("\n2b) KRÉ-14: a frontend JS modulok helyben vannak, nincs inline script")
js_assets = sorted(a for a in assets if a.startswith("js/"))
ok(js_assets == ["js/app-main.js", "js/core.js"],
   f"a két JS modul hivatkozva van ({js_assets})")
js_missing = [rel for rel in js_assets
              if not (ROOT / "static" / rel).is_file() or (ROOT / "static" / rel).stat().st_size == 0]
ok(not js_missing, f"a JS fájlok léteznek és nem üresek (hiányzó: {js_missing or 'nincs'})")
ok(not re.search(r"<script>\s", tpl), "a sablonban nincs beágyazott (inline) script")

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

print("\n7) #62/#63: SuliHub brand és egysoros fejléc")
ok("SuliHub" in tpl and "sulihub.svg" in tpl, "a felület a SuliHub nevet és logót használja")
logo = ROOT / "static" / "sulihub.svg"
ok(logo.is_file() and logo.stat().st_size > 100, "a Sulihub logó létezik")
ok((ROOT / "static" / "favicon.svg").is_file(), "a favicon megvan")
ok('class="app-brand' in tpl and 'app-left' in tpl,
   "a fejléc brand + bal oldali tanév + controls szerkezetű")
ok('id="schedulerDetails" class="d-none"' in tpl,
   "a részletes szinkron-sor rejtett (a modál szolgálja ki)")
compact_tag = tpl[tpl.find('id="schedulerCompact"'):tpl.find('id="schedulerCompact"') + 320]
ok("d-md-none" not in compact_tag,
   "a státuszsáv minden nézetben ugyanaz az egysoros elem")
ok("btnUzenetAi" not in tpl and "aiEredmeny" not in tpl,
   "az üzenet felületéből az AI-elemzés gomb ki van véve (#61)")

print("\n8) KRÉ-14: nincs körkörös import (a modulok nem importálják az app-ot)")
offenders = []
for path in sorted(ROOT.glob("*.py")):
    if path.name == "app.py":
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    if re.search(r"^\s*(?:import\s+app\b|from\s+app\s+import\b)", text, re.M):
        offenders.append(path.name)
ok(not offenders, f"egyik modul sem importálja az app.py-t (talált: {offenders or 'nincs'})")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
