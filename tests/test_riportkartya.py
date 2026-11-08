# -*- coding: utf-8 -*-
"""
Félévi / év végi riportkártya PDF (Kaneo #82).

- közvetlen generálás (`GET /api/riportkartya/export_pdf`), mentés/history nélkül;
- A4 PDF, magyar ékezetek (szövegkinyeréses ellenőrzés, ha van pypdf);
- félévi / teljes tanév időszak, a tanév a címben;
- a kártyán nincs „Viselkedés” és „Feljegyzések” szekció;
- hibás bemenetek, felületi gomb.
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
config = {"STUDENTS": [
    {"diak_nev": "RiportDiak", "enable_rewards": True, "active": False},
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
EVENTS = [
    ("RiportDiak", "Értékelés", "Matematika", "Jeles(5)", 5, 100, "2026. 09. 10.", "2026/2027"),
    ("RiportDiak", "Értékelés", "Matematika", "Közepes(3)", 3, 50, "2026. 10. 10.", "2026/2027"),
    ("RiportDiak", "Értékelés", "Irodalom", "Jó(4)", 4, 100, "2026. 09. 15.", "2026/2027"),
    ("RiportDiak", "Értékelés", "Magatartás", "Példás", 0, 0, "2026. 09. 20.", "2026/2027"),
    ("RiportDiak", "Feljegyzés", "Matematika", "", 0, 0, "2026. 10. 12.", "2026/2027"),
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


def pdf(periodus="ev", diak="RiportDiak", tanev="2026/2027"):
    return client.get("/api/riportkartya/export_pdf"
                      f"?diak={diak}&periodus={periodus}&tanev={tanev}")


print("1) Közvetlen PDF-generálás")
r = pdf("ev")
ok(r.status_code == 200 and r.mimetype == "application/pdf",
   f"HTTP 200, PDF ({r.mimetype})")
ok(r.data.startswith(b"%PDF") and len(r.data) > 1500, f"PDF bytes: {len(r.data)}")
ok("attachment" not in (r.headers.get("Content-Disposition") or "").lower(),
   f"a PDF inline nyílik meg: {r.headers.get('Content-Disposition')}")

print("\n2) Tartalom")
try:
    from pypdf import PdfReader
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(r.data)).pages)
    ok("SuliHub - RiportDiak - 2026/2027 év" in text,
       "a cím a gyermeket, a tanévet és az időszakot mutatja")
    ok("Matematika" in text and "Irodalom" in text, "a tantárgyak a PDF-ben")
    ok("2 óra" in text, "a hiányzás-összesítő a valós óraszámot mutatja (nem 0)")
    ok("Feljegyzések" not in text, "nincs Feljegyzések szekció a kártyán")
    ok("Viselkedés / magatartás" not in text, "nincs Viselkedés szekció a kártyán")
except ImportError:
    print("  (pypdf nincs — a szövegkinyeréses ellenőrzések kimaradnak)")

print("\n3) Félévi időszak és hibás bemenetek")
r = pdf("felvet")
ok(r.status_code == 200 and r.data.startswith(b"%PDF"), "félévi riport is generálható")
try:
    from pypdf import PdfReader
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(r.data)).pages)
    ok("2026/2027 1. félév" in text, "a félévi címben benne a tanév és a félév")
except ImportError:
    pass
ok(client.get("/api/riportkartya/export_pdf?periodus=ev").status_code == 400,
   "gyermek nélkül -> 400")
ok(client.get("/api/riportkartya/export_pdf?diak=RiportDiak&periodus=xx").status_code == 400,
   "rossz időszak -> 400")
ok(client.get("/api/riportkartya/export_pdf?diak=RiportDiak&tanev=2026").status_code == 400,
   "rossz tanév -> 400")

print("\n4) Felületi kártya és JS")
html = client.get("/").get_data(as_text=True)
js = client.get("/static/js/app-main.js").get_data(as_text=True)
ok('id="riportKartyaCard"' in html and 'id="riportDiak"' in html
   and 'id="riportPeriodus"' in html and 'id="btnRiportGeneral"' in html,
   "a riportkártya kártya a sablonban")
ok("/api/riportkartya/export_pdf" in js and "btnRiportGeneral" in js,
   "a JS közvetlenül a PDF végpontot nyitja")
ok("loadRiportLista" not in js and "riportLista" not in html,
   "nincs mentett riportok listája (mentés elhagyva)")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
