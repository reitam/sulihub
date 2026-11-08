# -*- coding: utf-8 -*-
"""
Félévi / év végi riportkártya PDF (Kaneo #82).

- generálás + mentés a data kötetre, DB-rekord;
- visszamenőleges lista és letöltés (gyermek + tanév szerint);
- A4 PDF, magyar ékezetek (szövegkinyeréses ellenőrzés, ha van pypdf);
- félévi / teljes tanév időszak, hibás bemenetek.
"""
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_riport_"))
db = work / "kreta_adatok.db"
riport_dir = work / "riportkartyak"
config = {"STUDENTS": [
    {"diak_nev": "RiportDiak", "enable_rewards": True, "active": False},
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
    "KRETA_RIPORTKARTYA_DIR": str(riport_dir),
    "KRETA_SCHEDULER_STATE_FILE": str(work / "scheduler_state.json"),
    "KRETA_VERSION_FILE": str(work / "version.txt"),
    "PYTHONIOENCODING": "utf-8",
})
os.environ.update({k: v for k, v in env.items() if k.startswith("KRETA")})

subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

conn = sqlite3.connect(db)
EVENTS = [
    ("RiportDiak", "Értékelés", "Matematika", "Jeles(5)", 5, 100, "2026. 09. 10.", "2026/2027"),
    ("RiportDiak", "Értékelés", "Matematika", "Közepes(3)", 3, 50, "2026. 10. 10.", "2026/2027"),
    ("RiportDiak", "Értékelés", "Irodalom", "Jó(4)", 4, 100, "2026. 09. 15.", "2026/2027"),
    ("RiportDiak", "Értékelés", "Magatartás", "Példás", 0, 0, "2026. 09. 20.", "2026/2027"),
    ("RiportDiak", "Feljegyzés", "Matematika", "", 0, 0, "2026. 10. 12.", "2026/2027"),
    ("MasDiak", "Értékelés", "Angol", "Jeles(5)", 5, 100, "2026. 09. 11.", "2026/2027"),
]
for r in EVENTS:
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, tema, mod, ertekelo, tanev)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (r[0], r[1], r[2], r[3], r[4], r[5], r[6],
         "Törtek" if r[1] == "Feljegyzés" else "", "Dicséret" if r[1] == "Feljegyzés" else "",
         "Tanár", r[7]))
for i, (datum, igazolt) in enumerate([("2026-09-20", 0), ("2026-10-01", 1)]):
    conn.execute(
        "INSERT INTO hianyzasok (diak_nev, mulasztas_datum, ora_sorszam, tantargy, tema,"
        " tanar, mulasztas_tipus, igazolt, tanorai_celu, igazolas_tipus, rogzites_datum,"
        " kreta_id, tanev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("RiportDiak", datum, i + 1, "Matematika", "Törtek", "Tanár", "Hiányzás",
         igazolt, "Nem", "", datum, f"r{i}", "2026/2027"))
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


def general(periodus="ev", diak="RiportDiak", tanev="2026/2027"):
    return client.post("/api/riportkartya",
                       json={"diak": diak, "periodus": periodus, "tanev": tanev})


print("1) Riportkártya generálása")
r = general("ev")
ok(r.status_code == 200, f"HTTP 200 ({r.status_code})")
d = r.get_json() or {}
ok(d.get("id") and d.get("url") == f"/api/riportkartyak/{d.get('id')}/pdf",
   f"id + letöltési URL: {d}")
ok(d.get("kezdo_datum") == "2026-09-01" and d.get("zaro_datum") == "2027-08-31",
   f"teljes tanév időszak: {d.get('kezdo_datum')} – {d.get('zaro_datum')}")
fajlok = list(riport_dir.rglob("*.pdf"))
ok(len(fajlok) == 1 and fajlok[0].stat().st_size > 1500,
   f"a PDF a data kötetre mentődött ({len(fajlok)} fájl, "
   f"{fajlok[0].stat().st_size if fajlok else 0} byte)")

print("\n2) Letöltés és PDF-tartalom")
r = client.get(d["url"])
ok(r.status_code == 200 and r.mimetype == "application/pdf", f"PDF letöltés ({r.mimetype})")
ok(r.data.startswith(b"%PDF"), "a válasz PDF")
try:
    from pypdf import PdfReader
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(r.data)).pages)
    ok("RiportDiak" in text, "a gyermek neve a PDF-ben")
    ok("Matematika" in text and "Irodalom" in text, "a tantárgyak a PDF-ben")
    ok("Tanulmányi riportkártya" in text, "a PDF címe")
except ImportError:
    print("  (pypdf nincs — a szövegkinyeréses ellenőrzések kimaradnak)")

print("\n3) Visszamenőleges lista + félévi riport")
r = general("felvet")
ok(r.status_code == 200, "félévi riport is generálható")
d2 = r.get_json() or {}
ok(d2.get("zaro_datum") == "2027-01-31", f"félév vége jan. 31.: {d2.get('zaro_datum')}")
lista = client.get("/api/riportkartyak?diak=RiportDiak&tanev=2026%2F2027").get_json()
ok(len(lista.get("rows") or []) == 2, f"2 korábbi riport: {len(lista.get('rows') or [])}")
ok({x["periodus_nev"] for x in lista["rows"]} == {"félév", "tanév"},
   f"periodus-nevek: {[x['periodus_nev'] for x in lista['rows']]}")
ok(client.get("/api/riportkartyak?diak=MasDiak").get_json().get("rows") == [],
   "másik gyermeknél nincs riport")
ok(client.get("/api/riportkartyak/999999/pdf").status_code == 404, "ismeretlen id -> 404")

print("\n4) Hibás bemenetek")
ok(client.post("/api/riportkartya", json={"periodus": "ev"}).status_code == 400,
   "gyermek nélkül -> 400")
ok(client.post("/api/riportkartya", json={"diak": "RiportDiak", "periodus": "xx"}).status_code == 400,
   "rossz időszak -> 400")
ok(client.post("/api/riportkartya", json={"diak": "RiportDiak", "tanev": "2026"}).status_code == 400,
   "rossz tanév -> 400")

print("\n5) Felületi kártya és JS")
html = client.get("/").get_data(as_text=True)
js = client.get("/static/js/app-main.js").get_data(as_text=True)
ok('id="riportKartyaCard"' in html and 'id="riportDiak"' in html
   and 'id="riportPeriodus"' in html and 'id="btnRiportGeneral"' in html,
   "a riportkártya kártya a sablonban")
ok("loadRiportLista" in js and "/api/riportkartyak" in js and "/api/riportkartya" in js,
   "a JS listázza és generálja a riportot")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
