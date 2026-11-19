# -*- coding: utf-8 -*-
"""Kaneo #139: tanév-archívum ZIP, integritás, idempotencia."""
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_archive_"))
db = work / "kreta_adatok.db"
config = {
    "STUDENTS": [{"diak_nev": "Teszt Elek", "enable_rewards": True, "active": False}],
    "SCHEDULER": {"ENABLED": False},
}
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

sys.path.insert(0, str(ROOT))
import kreta_archive  # noqa: E402

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


def insert_event(conn, tanev, bej, tantargy="Matematika", ertek="Jeles(5)"):
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
        " suly_szazalek, tanev, tanev_forras)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("Teszt Elek", "Értékelés", tantargy, ertek, 5, bej, "", "Kovács Anna",
         "Évközi jegy/értékelés", "Írásbeli", "Törtek", "", "", 0, 100, tanev,
         "szamitott"))


conn = sqlite3.connect(db)
insert_event(conn, "2025/2026", "2025. 10. 03.")
insert_event(conn, "2026/2027", "2026. 10. 05.")
conn.execute(
    "INSERT INTO hianyzasok (diak_nev, mulasztas_datum, ora_sorszam, tantargy,"
    " mulasztas_tipus, igazolt, tanev, tanev_forras)"
    " VALUES (?,?,?,?,?,?,?,?)",
    ("Teszt Elek", "2025. 10. 06.", 2, "Fizika", "Hiányzás", 0, "2025/2026", "szamitott"))
conn.execute(
    "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg,"
    " tanev, tanev_forras)"
    " VALUES (?,?,?,?,?,?,?,?)",
    ("Teszt Elek", "1", "Iskola", "Régi üzenet", "2025. 10. 07. 9:00", "Szöveg",
     "2025/2026", "szamitott"))
conn.execute(
    "INSERT INTO kifizetesek (diak_nev, kezdo_datum, zaro_datum, kifizetve, osszeg,"
    " tanev, tanev_forras)"
    " VALUES (?,?,?,?,?,?,?)",
    ("Teszt Elek", "2025-09-01", "2025-09-30", 1, 1000, "2025/2026", "szamitott"))
conn.execute(
    "INSERT INTO orarend (diak_nev, kezdo_idopont, zaro_idopont, nap, tantargy, tanar, terem)"
    " VALUES (?,?,?,?,?,?,?)",
    ("Teszt Elek", "2025-09-02 08:00", "2025-09-02 08:45", "kedd", "Matematika",
     "Kovács Anna", "101"))
conn.execute(
    "INSERT INTO tanevek (tanev, kezdet, veg, allapot, forras)"
    " VALUES (?,?,?,?,?)", ("2025/2026", "2025-09-01", "2026-08-31", "lezart", "teszt"))
conn.commit()
conn.close()

print("1) Archívum készítése")
path = kreta_archive.create_tanev_archive("2025/2026")
ok(path.exists() and path.suffix == ".zip", f"ZIP létrejött: {path.name}")
ok(kreta_archive.verify_archive(path), "a ZIP külső és belső SHA-256 ellenőrzése OK")

print("\n2) Tartalom")
with zipfile.ZipFile(path) as zf:
    names = set(zf.namelist())
    kell = {"manifest.json", "checksums.sha256", "ARCHIVE_INFO.txt", "adatok.xlsx",
            "adatok/esemenyek.json", "adatok/esemenyek.csv", "adatok/hianyzasok.json",
            "adatok/uzenetek.csv", "adatok/orarend.json", "riportok/riport_Teszt_Elek.pdf"}
    ok(kell <= names, f"a szükséges fájlok benne vannak (hiányzó: {kell - names})")
    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    ok(manifest.get("tanev") == "2025/2026", f"manifest tanév: {manifest.get('tanev')}")
    ok(manifest.get("tables", {}).get("esemenyek", {}).get("rows") == 1,
       "a manifestben 1 esemény szerepel")
    esemenyek = json.loads(zf.read("adatok/esemenyek.json").decode("utf-8"))
    ok(len(esemenyek) == 1 and esemenyek[0]["tanev"] == "2025/2026",
       "csak a zárt tanév eseménye került a JSON-ba")
    csv_szoveg = zf.read("adatok/esemenyek.csv").decode("utf-8-sig")
    ok("Matematika" in csv_szoveg and "2026/2027" not in csv_szoveg,
       "a CSV is a zárt tanévre szűrt")
    pdf = zf.read("riportok/riport_Teszt_Elek.pdf")
    ok(pdf.startswith(b"%PDF"), "a PDF-bizonyítvány érvényes PDF")

print("\n3) Excel")
import openpyxl  # noqa: E402
with zipfile.ZipFile(path) as zf:
    wb = openpyxl.load_workbook(io.BytesIO(zf.read("adatok.xlsx")))
    ok("esemenyek" in wb.sheetnames and "orarend" in wb.sheetnames,
       f"Excel munkalapok: {wb.sheetnames}")
    ws = wb["esemenyek"]
    ok(ws.max_row == 2, f"az események munkalapon fejléc + 1 sor: {ws.max_row}")

print("\n4) Idempotencia")
mtime = path.stat().st_mtime_ns
path2 = kreta_archive.create_tanev_archive("2025/2026")
ok(path2 == path, "ugyanazt a ZIP-et adja vissza")
ok(path.stat().st_mtime_ns == mtime, "ismételt híváskor nem írja felül")

print("\n5) Hibás tanév")
try:
    kreta_archive.create_tanev_archive("2025-2026")
    ok(False, "a hibás tanévformátumot el kell utasítani")
except ValueError:
    ok(True, "a hibás tanévformátumot elutasítja")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
