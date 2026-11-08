# -*- coding: utf-8 -*-
"""
#32 teszt: adatvédelem a teljes cserés mentésnél.

- üres (de 200-as) API-válasz nem törli a meglévő jegyeket/feljegyzéseket;
- az 50%-os küszöb (env: `KRETA_SYNC_MIN_RATIO`) működik;
- az órarend csak teljes ürülésnél véd (részleges csökkenés megengedett);
- a szolgáltató hibát dob, ha a mentés védve kimaradt (fallbackhez).
"""
import json
import os
import sqlite3
import sys
import tempfile
import shutil
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="kreta_guard_"))
(work / "config.json").write_text(
    json.dumps({"HEADLESS": True, "SYNC_MODE": "api_first",
                "STUDENTS": [{"diak_nev": "Teszt", "active": False}]}, ensure_ascii=False),
    encoding="utf-8",
)
os.environ.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(work / "kreta_adatok.db"),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": str(work / "csat"),
    "PYTHONIOENCODING": "utf-8",
})
os.environ.pop("KRETA_SYNC_MIN_RATIO", None)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import kreta_playwright as k  # noqa: E402

k.init_db()

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


def jegy(i):
    return {"esemeny_tipus": "Értékelés", "tantargy": f"Tantárgy{i}", "ertek": "Jeles(5)",
            "szam_ertek": 5, "bej_datum": "2026. 10. 20."}


def feljegyzes(i):
    return {"esemeny_tipus": "Feljegyzés", "bej_datum": "2026. 10. 20.", "tipus": "Dicséret",
            "cim": f"Cím{i}", "tartalom": "x"}


def ora(i):
    return {"start": f"2026-11-0{i}T08:00:00", "end": f"2026-11-0{i}T08:45:00",
            "title": f"Tantárgy{i}", "tanarNev": "Tanár", "teremNev": "T1"}


def count(table, tipus=None):
    conn = sqlite3.connect(k.DB_FILE)
    try:
        if tipus:
            return conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE diak_nev='Teszt' AND "
                + ("esemeny_tipus = ?" if table == "esemenyek" else "1=0"),
                (tipus,)).fetchone()[0]
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE diak_nev='Teszt'").fetchone()[0]
    finally:
        conn.close()


print("1) Kiinduló adatok")
k.save_esemenyek_by_type("Teszt", [jegy(i) for i in range(4)], set(), ["Értékelés"])
k.save_esemenyek_by_type("Teszt", [feljegyzes(0), feljegyzes(1)], set(), ["Feljegyzés"])
ok(count("esemenyek", "Értékelés") == 4, f"4 jegy a DB-ben: {count('esemenyek', 'Értékelés')}")
ok(count("esemenyek", "Feljegyzés") == 2, f"2 feljegyzés a DB-ben: {count('esemenyek', 'Feljegyzés')}")

print("\n2) Üres API-válasz nem töröl")
r = k.save_esemenyek_by_type("Teszt", [], set(), ["Értékelés"])
ok(r["blocked"].get("Értékelés", {}).get("old") == 4, f"a védőkorlát jelezte: {r['blocked']}")
ok(count("esemenyek", "Értékelés") == 4, "a 4 jegy megmaradt")
r = k.save_esemenyek_by_type("Teszt", [jegy(9)], set(), ["Értékelés"])
ok("Értékelés" in r["blocked"], "1 sor a 4 helyett -> blokkolt")
ok(count("esemenyek", "Értékelés") == 4, "továbbra is 4 jegy")
r = k.save_esemenyek_by_type("Teszt", [jegy(10), jegy(11)], set(), ["Értékelés"])
ok(not r["blocked"] and r["saved"] == 2, f"2 sor a 4-ből (50%) -> mentve: {r}")
ok(count("esemenyek", "Értékelés") == 2, "a jegyek száma 2-re változott")

r = k.save_esemenyek_by_type("Teszt", [], set(), ["Feljegyzés"])
ok("Feljegyzés" in r["blocked"], "üres feljegyzés-lista -> blokkolt")
ok(count("esemenyek", "Feljegyzés") == 2, "a 2 feljegyzés megmaradt")

print("\n3) Órarend: csak teljes ürülés véd")
k.save_orarend_to_db("Teszt", [ora(2), ora(3), ora(4)])
ok(count("orarend") == 3, f"3 órarendi sor: {count('orarend')}")
r = k.save_orarend_to_db("Teszt", [])
ok("orarend" in r["blocked"], "üres lista -> blokkolt")
ok(count("orarend") == 3, "az órarend megmaradt")
r = k.save_orarend_to_db("Teszt", [ora(5)])
ok(not r["blocked"] and r["saved"] == 1, "részleges csökkenés (3 -> 1) megengedett")
ok(count("orarend") == 4, "a múltbeli 3 sor megmaradt + az új (Kaneo #122)")
r = k.save_orarend_to_db("Teszt", [dict(ora(5), title="Módosított")])
ok(count("orarend") == 4, "az ablakon belüli sor cserélődik, nem duplikálódik")

print("\n4) A szolgáltató hibát dob, ha a mentés védve maradt")


class EmptyClient:
    def fetch_evaluations(self, start, end):
        return []


try:
    k.api_provider_jegyek({"diak_nev": "Teszt"}, client_factory=lambda s: EmptyClient())
    hiba = ""
except RuntimeError as exc:
    hiba = str(exc)
ok("adatvédelem" in hiba, f"RuntimeError a fallbackhez: {hiba}")
ok(count("esemenyek", "Értékelés") == 2, "a jegyek érintetlenek")

print("\n5) KRETA_SYNC_MIN_RATIO")
os.environ["KRETA_SYNC_MIN_RATIO"] = "0.2"
r = k.save_esemenyek_by_type("Teszt", [jegy(20)], set(), ["Értékelés"])
ok(not r["blocked"] and r["saved"] == 1,
   f"0.2 küszöbbel az 1 a 2-ből már menthető: {r}")
ok(count("esemenyek", "Értékelés") == 1, "1 jegy maradt")

os.environ["KRETA_SYNC_MIN_RATIO"] = "0"
r = k.save_esemenyek_by_type("Teszt", [], set(), ["Értékelés"])
ok("Értékelés" in r["blocked"],
   "0 küszöb mellett is véd az üres lista (Kaneo #40: üres batch soha nem töröl)")
ok(count("esemenyek", "Értékelés") == 1, "a jegy megmaradt")
os.environ.pop("KRETA_SYNC_MIN_RATIO", None)

print("\n6) A Playwright-út is véd (nincs kivétel)")
k.save_esemenyek_by_type("Teszt", [feljegyzes(5)], set(), ["Feljegyzés"])
r = k.save_esemenyek_by_type("Teszt", [], set(), ["Feljegyzés"])
ok("Feljegyzés" in r["blocked"] and count("esemenyek", "Feljegyzés") == 1,
   "a webes mentésnél is megmarad a sor")

print("\n7) Igazolások: adatvédelem (Kaneo #42)")


def igazolas(i, kezdet="2026. 06. 10."):
    return {"kreta_id": f"i{i}", "kezdete": kezdet, "vege": "2026. 06. 12.",
            "igazolas_tipus": "Orvosi igazolás", "megjegyzes": ""}


k.save_igazolasok_to_db("Teszt", [igazolas(1), igazolas(2), igazolas(3)])
ok(count("igazolasok") == 3, f"3 igazolás a DB-ben: {count('igazolasok')}")
r = k.save_igazolasok_to_db("Teszt", [])
ok(r["blocked"].get("igazolasok", {}).get("old") == 3, f"üres lista -> blokkolt: {r['blocked']}")
ok(count("igazolasok") == 3, "a 3 igazolás megmaradt")
r = k.save_igazolasok_to_db("Teszt", [igazolas(4)])
ok("igazolasok" in r["blocked"], "1 sor a 3 helyett (50% alatt) -> blokkolt")
ok(count("igazolasok") == 3, "továbbra is 3 igazolás")
r = k.save_igazolasok_to_db("Teszt", [igazolas(5), igazolas(6), igazolas(7)])
ok(not r["blocked"] and r["saved"] == 3, f"3 sor a 3-ból -> mentve: {r}")
ok(count("igazolasok") == 3, "az igazolások cserélődtek")
# Dedupe: 2 azonos kulcs -> 1 sor (üres DB-n, hogy a küszöb ne blokkoljon)
conn = sqlite3.connect(k.DB_FILE)
conn.execute("DELETE FROM igazolasok")
conn.commit()
conn.close()
r = k.save_igazolasok_to_db("Teszt", [igazolas(9), igazolas(9)])
ok(not r["blocked"] and r["saved"] == 1, f"duplikált kulcs -> egyszer mentve: {r}")
ok(count("igazolasok") == 1, "1 igazolás maradt")

os.environ["KRETA_SYNC_MIN_RATIO"] = "0"
r = k.save_igazolasok_to_db("Teszt", [])
ok("igazolasok" in r["blocked"], "0 küszöb mellett is véd az üres lista (#42 szigorítás)")
ok(count("igazolasok") == 1, "az igazolás megmaradt")
os.environ.pop("KRETA_SYNC_MIN_RATIO", None)

print("\n8) Az API-út hibát dob, ha az igazolások mentése védve maradt")


class UresIgazolasKliens:
    def fetch_justifications(self):
        return []


try:
    k.api_provider_igazolasok({"diak_nev": "Teszt"},
                              client_factory=lambda s: UresIgazolasKliens())
    hiba = ""
except RuntimeError as exc:
    hiba = str(exc)
ok("adatvédelem" in hiba, f"RuntimeError a fallbackhez: {hiba}")
ok(count("igazolasok") == 1, "az igazolás érintetlen")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
