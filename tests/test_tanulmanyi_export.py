# -*- coding: utf-8 -*-
"""
Tanulmányi Excel exportok (Kaneo #83).

- `/api/esemenyek/export.xlsx`: Jegyek / Feljegyzések / Házi feladatok munkalapok,
  diák + tanév + időszak szűrővel.
- `/api/hianyzasok/export.xlsx`: Hiányzások / Igazolások, ugyanazokkal a szűrőkkel.
- a felület gombjai és a letöltési URL-ek.
"""
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_export_"))
db = work / "kreta_adatok.db"
config = {"STUDENTS": [
    {"diak_nev": "ExportDiak", "enable_rewards": True, "active": False},
    {"diak_nev": "MasDiak", "enable_rewards": True, "active": False},
]}
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
ESEMENYEK = [
    # diák, típus, tantárgy, érték, szám, súly, bej, határidő, téma, tartalom, tanár, kész, tanév
    ("ExportDiak", "Értékelés", "Matematika", "Jeles(5)", 5, 100,
     "2026. 09. 10.", "", "Törtek", "", "Tanár A", 0, "2026/2027"),
    ("ExportDiak", "Értékelés", "Matematika", "Közepes(3)", 3, 50,
     "2026. 10. 10.", "", "Egyenletek", "", "Tanár A", 0, "2026/2027"),
    ("ExportDiak", "Értékelés", "Fizika", "Jó(4)", 4, 100,
     "2025. 10. 10.", "", "Régi", "", "Tanár B", 0, "2025/2026"),
    ("ExportDiak", "Feljegyzés", "Magatartás", "", 0, 0,
     "2026. 10. 12.", "", "Dicséret", "Kiváló órai munka", "Tanár C", 0, "2026/2027"),
    ("ExportDiak", "Házi feladat", "Matematika", "", 0, 0,
     "2026. 10. 13.", "2026. 10. 20.", "Törtek gyakorlása", "", "Tanár A", 1, "2026/2027"),
    ("ExportDiak", "Bejelentett számonkérés", "Fizika", "", 0, 0,
     "2026. 10. 14.", "2026. 10. 25.", "Erő", "", "Tanár B", 0, "2026/2027"),
    ("MasDiak", "Értékelés", "Angol", "Jeles(5)", 5, 100,
     "2026. 10. 15.", "", "Present", "", "Tanár D", 0, "2026/2027"),
]
for r in ESEMENYEK:
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, hatarido, tema, tartalom, ertekelo, kesz, tanev)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", r)

HIANYZASOK = [
    ("ExportDiak", "2026-10-05", 1, None, "Matematika", "Törtek", "Tanár A",
     "Hiányzás", 0, "Nem", "", "2026-10-05", "h1", "2026/2027"),
    ("ExportDiak", "2026-10-06", 2, 5, "Fizika", "Erő", "Tanár B",
     "Késés", 1, "Nem", "Szülői", "2026-10-06", "h2", "2026/2027"),
    ("MasDiak", "2026-10-07", 1, None, "Angol", "Present", "Tanár D",
     "Hiányzás", 0, "Nem", "", "2026-10-07", "h3", "2026/2027"),
]
for r in HIANYZASOK:
    conn.execute(
        "INSERT INTO hianyzasok (diak_nev, mulasztas_datum, ora_sorszam, perc, tantargy,"
        " tema, tanar, mulasztas_tipus, igazolt, tanorai_celu, igazolas_tipus,"
        " rogzites_datum, kreta_id, tanev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", r)

conn.execute(
    "INSERT INTO igazolasok (diak_nev, kreta_id, kezdete, vege, igazolas_tipus,"
    " megjegyzes, tanev) VALUES (?,?,?,?,?,?,?)",
    ("ExportDiak", "i1", "2026-10-05", "2026-10-06", "Orvosi", "Láz", "2026/2027"))
conn.commit()
conn.close()

sys.path.insert(0, str(ROOT))
import app as kreta  # noqa: E402

client = kreta.app.test_client()
_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


def wb_get(url):
    r = client.get(url)
    ok(r.status_code == 200, f"HTTP 200 ({url} -> {r.status_code})")
    ok("spreadsheetml" in (r.headers.get("Content-Type") or ""),
       f"xlsx tartalomtípus: {r.headers.get('Content-Type')}")
    return r, openpyxl.load_workbook(io.BytesIO(r.data))


def sorok(ws):
    return list(ws.iter_rows(min_row=2, values_only=True))


print("1) Esemény-export: munkalapok és tartalom")
r, wb = wb_get("/api/esemenyek/export.xlsx?tanev=2026%2F2027")
ok(wb.sheetnames == ["Szűrt lista", "Jegyek", "Feljegyzések", "Házi feladatok"],
   f"munkalapok: {wb.sheetnames}")
ws_lista = wb["Szűrt lista"]
ok([c.value for c in ws_lista[1]][:4] == ["Diák", "Típus", "Tantárgy", "Érték / Mód"],
   "Szűrt lista fejléc")
ok(len(sorok(ws_lista)) == 6,
   f"a szűrt lista minden típust tartalmaz (6 sor): {len(sorok(ws_lista))}")
ws = wb["Jegyek"]
ok([c.value for c in ws[1]][:3] == ["Diák", "Tantárgy", "Jegy"], "Jegyek fejléc")
jegyek = sorok(ws)
ok(len(jegyek) == 3, f"3 jegy a 2026/2027 tanévben: {len(jegyek)}")
ok(jegyek[0][0] == "ExportDiak" and jegyek[0][1] == "Matematika" and jegyek[0][2] == "Jeles(5)",
   f"első jegysor: {jegyek[0]}")
ok(any(s[2] == "Jeles(5)" and s[0] == "MasDiak" for s in jegyek),
   "másik diák jegyét is exportálja (diák nélkül)")
fel = sorok(wb["Feljegyzések"])
ok(len(fel) == 1 and "Dicséret" in str(fel[0]), f"1 feljegyzés: {fel}")
hazi = sorok(wb["Házi feladatok"])
ok(len(hazi) == 2, f"2 házi/számonkérés: {len(hazi)}")
ok(any(s[6] == "Elkészítve" for s in hazi) and any(s[6] == "-" for s in hazi),
   f"a házi állapota (elkészítve/–): {[s[6] for s in hazi]}")

print("\n2) Esemény-export szűrők")
_, wb2 = wb_get("/api/esemenyek/export.xlsx?diak=ExportDiak&tanev=2026%2F2027")
ok(len(sorok(wb2["Jegyek"])) == 2, "diák-szűrés: csak ExportDiak 2 jegye")
_, wb3 = wb_get("/api/esemenyek/export.xlsx?diak=ExportDiak&tanev=2025%2F2026")
ok(len(sorok(wb3["Jegyek"])) == 1 and sorok(wb3["Jegyek"])[0][1] == "Fizika",
   "tanév-szűrés: a 2025/2026-os Fizika")
_, wb4 = wb_get("/api/esemenyek/export.xlsx?diak=ExportDiak"
                "&kezdo_datum=2026-10-01&zaro_datum=2026-10-31")
ok(len(sorok(wb4["Jegyek"])) == 1 and len(sorok(wb4["Házi feladatok"])) == 2,
   "időszak-szűrés (október)")
_, wb6 = wb_get("/api/esemenyek/export.xlsx?diak=ExportDiak&tipus=Feljegyz%C3%A9s")
ok(len(sorok(wb6["Szűrt lista"])) == 1 and len(sorok(wb6["Jegyek"])) == 0
   and len(sorok(wb6["Feljegyzések"])) == 1,
   "típus-szűrés: csak a feljegyzés (a szűrt listában és a saját munkalapon)")
_, wb7 = wb_get("/api/esemenyek/export.xlsx?diak=ExportDiak&tantargy=Matematika"
                "&status=lejart")
ok(len(sorok(wb7["Szűrt lista"])) == 1,
   f"tantárgy + lejárt szűrés a szűrt listán: {len(sorok(wb7['Szűrt lista']))}")
_, wb5 = wb_get("/api/esemenyek/export.xlsx?diak=NincsIlyen")
ok(all(len(sorok(wb5[s])) == 0 for s in wb5.sheetnames), "üres szűrés -> üres munkalapok")

print("\n3) Hiányzás-export")
_, wh = wb_get("/api/hianyzasok/export.xlsx?tanev=2026%2F2027")
ok(wh.sheetnames == ["Hiányzások", "Igazolások"], f"munkalapok: {wh.sheetnames}")
h = sorok(wh["Hiányzások"])
ok(len(h) == 3, f"3 hiányzás: {len(h)}")
ok(any(s[7] == "Igen" and s[8] == 5 for s in h), f"igazolt + 5 perc késés: {h}")
ig = sorok(wh["Igazolások"])
ok(len(ig) == 1 and ig[0][3] == "Orvosi", f"1 igazolás: {ig}")
_, wh2 = wb_get("/api/hianyzasok/export.xlsx?diak=ExportDiak&kezdo_datum=2026-10-06"
                "&zaro_datum=2026-10-06")
ok(len(sorok(wh2["Hiányzások"])) == 1 and len(sorok(wh2["Igazolások"])) == 1,
   "időszak-szűrés: a 10.06-i késés + az átfedő igazolás")

print("\n4) Felületi gombok és letöltési URL-ek")
html = client.get("/").get_data(as_text=True)
js = client.get("/static/js/app-main.js").get_data(as_text=True)
ok('id="btnEsemenyExportXlsx"' in html and 'id="btnHianyzasExportXlsx"' in html,
   "az Excel export gombok a sablonban")
ok("/api/esemenyek/export.xlsx" in js and "/api/hianyzasok/export.xlsx" in js,
   "a JS a helyes végpontokat hívja")
ok("kezdo_datum" in js and "zaro_datum" in js and "tanevQueryParam" in js,
   "a szűrők (diák/tanév/időszak) átkerülnek az export URL-re")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
