# -*- coding: utf-8 -*-
import os, sys
from pathlib import Path
import tempfile, sqlite3, io

work = tempfile.mkdtemp(prefix="kreta_pdf_")
db = os.path.join(work, "kreta_adatok.db")

conn = sqlite3.connect(db)
conn.execute("""CREATE TABLE orarend (
    id INTEGER PRIMARY KEY AUTOINCREMENT, diak_nev TEXT, kezdo_idopont TEXT,
    zaro_idopont TEXT, nap TEXT, tantargy TEXT, tanar TEXT, terem TEXT)""")
# hétfő, 2026-10-26 — ő/ű betűkkel a tantárgyban, tanárban, teremben
conn.execute("""INSERT INTO orarend (diak_nev, kezdo_idopont, zaro_idopont, nap, tantargy, tanar, terem)
                VALUES (?,?,?,?,?,?,?)""",
    ("Teszt Diák", "2026-10-26T08:00:00", "2026-10-26T08:45:00", "hétfő",
     "Történelem – őskőkor és művelődés", "Kővári Őrs Űrhajós", "1. terem"))
conn.commit(); conn.close()

os.environ.update({
    "KRETA_DATA_DIR": work,
    "KRETA_DB_FILE": db,
    "KRETA_CONFIG_FILE": os.path.join(work, "config.json"),
    "KRETA_LOG_FILE": os.path.join(work, "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csat"),
})
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as kreta

print("regisztrált betű (route előtt):", kreta._pdf_font(), "| bold:", kreta._pdf_font_bold())

c = kreta.app.test_client()
r = c.get("/api/orarend/export_pdf?diak=" + "Teszt%20Di%C3%A1k" + "&datum=2026-10-26")
print("HTTP", r.status_code, "| méret", len(r.data), "byte")

print("regisztrált betűk (route után):", sorted(kreta.pdfmetrics.getRegisteredFontNames()))
open(os.path.join(work, "out.pdf"), "wb").write(r.data)

# A beágyazott betűk listája (fitz/PyMuPDF) — opcionális, csak diagnosztikához
try:
    import fitz
    doc = fitz.open(os.path.join(work, "out.pdf"))
    fonts = set()
    for page in doc:
        for f in page.get_fonts():
            fonts.add((f[3], f[2]))  # (basefont, type)
    print("beágyazott betűk a PDF-ben:", sorted(fonts))
except ImportError:
    print("(fitz nincs telepítve — a betűlista ellenőrzése kimarad)")

_hibak = []

def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)

try:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(r.data))
    text = "".join((p.extract_text() or "") for p in reader.pages)
    print("--- kinyert szöveg ---")
    print(text)

    print("--- ellenőrzés ---")
    ok(r.status_code == 200, f"HTTP {r.status_code}")
    ok(r.data[:4] == b"%PDF", "a válasz PDF")
    for ch in ["ő", "Ő", "ű", "Ű", "Kővári", "művelődés"]:
        ok(ch in text, f"'{ch}' a PDF szövegében")
except ImportError:
    print("(pypdf nincs telepítve — a szövegkinyerés ellenőrzése kimarad)")

sys.exit(1 if _hibak else 0)
