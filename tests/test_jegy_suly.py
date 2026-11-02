# -*- coding: utf-8 -*-
"""A jegyek súlyszázaléka: webes tooltip-parse, API-normalizálás, DB-oszlop.

A súly két forrásból jön:
  - mobil API: `SulySzazalekErteke` (pl. 50 / 100 / 200),
  - webes grid: a jegy-cellában lévő tooltip `data-suly` attribútuma ("Súly: 50%").
Mindkettő ugyanabba az `esemenyek.suly_szazalek` oszlopba kerül.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_hibak = []


def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)


work = Path(tempfile.mkdtemp(prefix="kreta_suly_"))
os.environ["KRETA_DATA_DIR"] = str(work)
os.environ["KRETA_DB_FILE"] = str(work / "adatok.db")
os.environ["KRETA_LOG_FILE"] = str(work / "sync.log")
os.environ["KRETA_CONFIG_FILE"] = str(work / "config.json")
(work / "config.json").write_text(
    '{"STUDENTS": [{"diak_nev": "Teszt", "active": false}]}', encoding="utf-8")
sys.path.insert(0, str(ROOT))

import kreta_api  # noqa: E402
import kreta_playwright as k  # noqa: E402

print("\n1) Webes tooltip szövegének parse-olása")
ok(k._parse_suly("Súly: 50%") == 50, "Súly: 50% -> 50")
ok(k._parse_suly("Súly: 100%") == 100, "Súly: 100% -> 100")
ok(k._parse_suly("Súly: 200%") == 200, "200% is előfordul (duplán számító jegy)")
ok(k._parse_suly("") == 0 and k._parse_suly(None) == 0, "hiányzó érték -> 0")
ok(k._parse_suly(100) == 100, "számként kapott értéket is kezeli")

print("\n2) Mobil API normalizálás (SulySzazalekErteke)")
ok(kreta_api.normalize_evaluation({"SulySzazalekErteke": 100})["suly_szazalek"] == 100,
   "szám típus -> 100")
ok(kreta_api.normalize_evaluation({"SulySzazalekErteke": "50"})["suly_szazalek"] == 50,
   "sztring -> 50")
ok(kreta_api.normalize_evaluation({})["suly_szazalek"] == 0,
   "hiányzó mező -> 0 (nem None)")
ok(kreta_api.normalize_evaluation({"SulySzazalekErteke": None})["suly_szazalek"] == 0,
   "null -> 0")

print("\n3) DB oszlop és mentés")
k.init_db()
conn = sqlite3.connect(k.DB_FILE)
cols = [row[1] for row in conn.execute("PRAGMA table_info(esemenyek)")]
ok("suly_szazalek" in cols, f"az esemenyek táblában van suly_szazalek oszlop: {cols}")

cursor = conn.cursor()
k._insert_esemeny(cursor, "Teszt", {
    "esemeny_tipus": "Értékelés", "tantargy": "Irodalom", "ertek": "Jeles(5)",
    "szam_ertek": 5, "suly_szazalek": 200, "bej_datum": "2026. 11. 02.",
    "ertekelo": "Tanár", "tipus": "Évközi jegy", "mod": "Írásbeli", "tema": "Dolgozat",
}, set(), set(), set())
k._insert_esemeny(cursor, "Teszt", {
    "esemeny_tipus": "Értékelés", "tantargy": "Matematika", "ertek": "Jó(4)",
    "szam_ertek": 4, "bej_datum": "2026. 11. 01.",
}, set(), set(), set())
conn.commit()
rows = conn.execute(
    "SELECT tantargy, suly_szazalek FROM esemenyek ORDER BY id").fetchall()
conn.close()
ok(rows[0] == ("Irodalom", 200), f"a súly mentődik: {rows[0]}")
ok(rows[1] == ("Matematika", 0), f"forrás nélkül 0 (nem NULL): {rows[1]}")

print("\n" + "=" * 60)
if _hibak:
    print(f"BUKOTT ({len(_hibak)} hiba)")
    sys.exit(1)
print("MINDEN ELLENŐRZÉS OK")
