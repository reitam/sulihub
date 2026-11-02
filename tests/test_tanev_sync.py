# -*- coding: utf-8 -*-
"""Tanév-tudatos szinkron tesztek (Kaneo #40 2+3. fázis, #45).

Éles KRÉTA nélkül, szimulált tanévváltással:
- a lekérési ablak a **tanév elején** kezdődik (nem a DB legkorábbi soránál);
- a teljes csere csak a letöltött tanévekre és az **ablakon belülre** hat;
- a korábbi tanév sorai érintetlenek maradnak;
- „óra-bomba”: 08-31 → 09-01 (üres válasz) → 09-03 (új adat) — nincs adatvesztés.
"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_tanev_sync_"))
(work / "config.json").write_text(
    json.dumps({"HEADLESS": True, "SYNC_MODE": "api",
                "STUDENTS": [{"diak_nev": "Teszt", "active": False}]}, ensure_ascii=False),
    encoding="utf-8")
os.environ.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(work / "kreta_adatok.db"),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "PYTHONIOENCODING": "utf-8",
})
os.environ.pop("KRETA_SYNC_MIN_RATIO", None)
sys.path.insert(0, str(ROOT))

import kreta_playwright as k  # noqa: E402
import kreta_tanev  # noqa: E402

k.init_db()

_hibak = []


def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)


def db_rows(sql, params=()):
    conn = sqlite3.connect(k.DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def raw_item(uid, datum, tantargy="Matematika", ertek="Jeles(5)", szam=5):
    return {"Uid": uid, "Tantargy": {"Nev": tantargy}, "Tema": "Téma",
            "SzovegesErtek": ertek, "SzamErtek": szam,
            "ErtekeloTanarNeve": "Tanár", "Tipus": {"Leiras": "Évközi jegy"},
            "Mod": {"Leiras": "Írásbeli"}, "SulySzazalekErteke": 100,
            "RogzitesDatuma": f"{datum}T10:00:00Z"}


class TanevFakeClient:
    """A KRÉTA mintájára **csak az ablakon belüli** sorokat adja vissza."""

    def __init__(self, items):
        self.items = items
        self.calls = []

    def fetch_evaluations(self, start, end):
        self.calls.append((start, end))
        out = []
        for it in self.items:
            d = kreta_tanev.parse_date(it.get("RogzitesDatuma"))
            if d and start <= d <= end:
                out.append(it)
        return out


print("\n1) Az API-ablak a tanév elején kezdődik (nem a DB legkorábbi soránál)")
os.environ["KRETA_TODAY"] = "2026-11-03"
start, end = k.evaluation_api_window("Teszt")
ok(start == date(2026, 9, 1), f"ablak kezdete a tanév első napja: {start}")
ok(end == date(2026, 11, 3), f"ablak vége a mai nap: {end}")
start2, end2 = k.events_api_window("Teszt", "Házi feladat")
ok((end2 - end).days == 90, f"a házi/számonkérés ablaka +90 nap: {end2}")

# Legyen a DB-ben korábbi tanévi sor is: az ablak akkor sem nyúlik vissza.
conn = sqlite3.connect(k.DB_FILE)
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz, tanev, tanev_forras)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
    ("Teszt", "Értékelés", "Irodalom", "Jeles(5)", 5, "2026. 03. 10.", "", "Tanár", "",
     "Írásbeli", "Régi", "", "", "2025/2026", "szamitott"))
conn.commit()
conn.close()
start3, _ = k.evaluation_api_window("Teszt")
ok(start3 == date(2026, 9, 1), f"a korábbi tanév sora nem nyújtja vissza az ablakot: {start3}")

print("\n2) Szinkron: csak a tanévbe eső sorok jönnek le és cserélődnek")
fake = TanevFakeClient([
    raw_item("1", "2026-09-20"), raw_item("2", "2026-10-05", "Fizika", "Jó(4)", 4),
    raw_item("3", "2026-03-10", "Irodalom"),  # előző tanév: kívül esik az ablakon
])
k.api_provider_jegyek({"diak_nev": "Teszt"}, client_factory=lambda s: fake)
ok(len(fake.calls) == 1 and fake.calls[0][0] == date(2026, 9, 1),
   f"a kliens a tanév elejétől kapott ablakot: {fake.calls}")
rows = db_rows("SELECT tantargy, bej_datum, tanev FROM esemenyek WHERE diak_nev='Teszt'"
               " ORDER BY tantargy")
tant = sorted(r["tantargy"] for r in rows)
ok(tant == ["Fizika", "Irodalom", "Matematika"], f"3 sor a DB-ben: {tant}")
ok(all(r["tanev"] in ("2025/2026", "2026/2027") for r in rows),
   f"minden sor kapott tanévet: {[(r['tantargy'], r['tanev']) for r in rows]}")
irod = next((r for r in rows if r["tantargy"] == "Irodalom"), {})
ok(irod.get("tanev") == "2025/2026" and irod.get("bej_datum") == "2026. 03. 10.",
   "a korábbi tanévi sor érintetlen maradt")

print("\n3) Ablakon kívüli (jövőbeli) sor nem törlődik a teljes cserénél")
os.environ["KRETA_TODAY"] = "2026-11-03"
k.save_esemenyek_by_type("Teszt", [
    {"esemeny_tipus": "Feljegyzés", "bej_datum": "2026. 11. 10.", "tipus": "Dicséret",
     "cim": "Jövőbeli feljegyzés", "tartalom": "x"},
], set(), ["Feljegyzés"], window=(date(2026, 9, 1), date(2026, 11, 3)))
elotte = db_rows("SELECT id, cim FROM esemenyek WHERE esemeny_tipus='Feljegyzés'")
r = k.save_esemenyek_by_type("Teszt", [
    {"esemeny_tipus": "Feljegyzés", "bej_datum": "2026. 10. 20.", "tipus": "Dicséret",
     "cim": "Októberi", "tartalom": "y"},
], set(), ["Feljegyzés"], window=(date(2026, 9, 1), date(2026, 11, 3)))
utana = db_rows("SELECT id, cim FROM esemenyek WHERE esemeny_tipus='Feljegyzés'")
cimek = sorted(x["cim"] for x in utana)
ok("Jövőbeli feljegyzés" in cimek,
   f"az ablakon túli sor megmaradt (Kaneo #40 / R3): {cimek}")
ok("Októberi" in cimek, "az új sor bekerült")
ok(len(elotte) == 1 and len(utana) == 2, f"1 → 2 sor: {len(elotte)} → {len(utana)}")

print("\n4) Óra-bomba: tanévváltás szimulációja (08-31 → 09-01 → 09-03)")
os.environ["KRETA_TODAY"] = "2027-08-31"
k.save_esemenyek_by_type("Teszt", [
    {"esemeny_tipus": "Értékelés", "tantargy": "Kémia", "ertek": "Jeles(5)", "szam_ertek": 5,
     "bej_datum": "2027. 06. 10."},
    {"esemeny_tipus": "Értékelés", "tantargy": "Biológia", "ertek": "Jó(4)", "szam_ertek": 4,
     "bej_datum": "2027. 08. 30."},
], set(), ["Értékelés"], window=(date(2026, 9, 1), date(2027, 8, 31)))
elotte = db_rows("SELECT id, tantargy, tanev FROM esemenyek WHERE esemeny_tipus='Értékelés'"
                 " AND tanev='2026/2027' ORDER BY id")
ok(len(elotte) == 2, f"2 jegy a 2026/2027 tanévben: {len(elotte)}")

# Szeptember 1.: az API még üres — semmi nem törlődhet.
os.environ["KRETA_TODAY"] = "2027-09-01"
r = k.save_esemenyek_by_type("Teszt", [], set(), ["Értékelés"],
                             window=(date(2027, 9, 1), date(2027, 9, 1)))
kozben = db_rows("SELECT id, tantargy, tanev FROM esemenyek WHERE esemeny_tipus='Értékelés'"
                 " AND tanev='2026/2027' ORDER BY id")
ok(kozben == elotte, "a tanévváltás napján (üres válasz) semmi nem törlődött")
ok("Értékelés" in r["blocked"], "az üres választ a védőkorlát jelezte")

# Szeptember 3.: jön az első új tanévi jegy.
os.environ["KRETA_TODAY"] = "2027-09-03"
k.save_esemenyek_by_type("Teszt", [
    {"esemeny_tipus": "Értékelés", "tantargy": "Történelem", "ertek": "Jeles(5)", "szam_ertek": 5,
     "bej_datum": "2027. 09. 02."},
], set(), ["Értékelés"], window=(date(2027, 9, 1), date(2027, 9, 3)))
veg = db_rows("SELECT id, tantargy, tanev FROM esemenyek WHERE esemeny_tipus='Értékelés'"
              " ORDER BY id")
regi = [x for x in veg if x["tanev"] == "2026/2027"]
uj = [x for x in veg if x["tanev"] == "2027/2028"]
ok([ (x["id"], x["tantargy"]) for x in regi] == [(x["id"], x["tantargy"]) for x in elotte],
   "az előző tanév jegyei ID-ra és tartalomra változatlanok")
ok(len(uj) == 1 and uj[0]["tantargy"] == "Történelem",
   f"az új tanév jegye a 2027/2028 alá került: {uj}")

print("\n5) tanev_api_window a tanévváltás után")
s, e = k.kreta_api_sync.tanev_api_window(date(2027, 9, 3))
ok(s == date(2027, 9, 1) and e == date(2027, 9, 3),
   f"az új tanév első napjától kér: {s} .. {e}")

os.environ.pop("KRETA_TODAY", None)

print("\n" + "=" * 60)
if _hibak:
    print(f"BUKOTT ({len(_hibak)} hiba)")
    sys.exit(1)
print("MINDEN ELLENŐRZÉS OK")
