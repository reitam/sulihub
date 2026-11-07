# -*- coding: utf-8 -*-
"""
Globális kereső (Kaneo #85).

- jegyek, feljegyzések, házik, üzenetek (teljes törzs) és hiányzások keresése;
- legalább 2 karakter, max. 20 találat, dátum szerint csökkenő sorrend;
- LIKE-speciális karakterek (% _) escape-elve;
- a felületi modal, a Ctrl+K gyorsgomb és a navigáció megvan.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_search_"))
db = work / "kreta_adatok.db"
config = {"STUDENTS": [{"diak_nev": "Kereso", "enable_rewards": True, "active": False}]}
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
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek, suly_szazalek,"
    " bej_datum, hatarido, tema, cim, tartalom, kesz, tanev)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?)",
    ("Kereso", "Értékelés", "Fizika", "Jeles(5)", 5, 100, "2026. 10. 20.", "",
     "Elektromosság", "Dolgozat", "Az elektromos áramkörök", "2026/2027"))
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek, suly_szazalek,"
    " bej_datum, hatarido, tema, cim, tartalom, kesz, tanev)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?)",
    ("Kereso", "Házi feladat", "Matematika", "", 0, 0, "2026. 10. 18.", "2026. 10. 22.",
     "Törtek gyakorlása", "Házi", "Oldd meg a törteket", "2026/2027"))
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek, suly_szazalek,"
    " bej_datum, hatarido, tema, cim, tartalom, kesz, tanev)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?)",
    ("Kereso", "Feljegyzés", "-", "", 0, 0, "2026. 10. 15.", "",
     "Dicséret", "Dicséret", "Kiváló órai munka", "2026/2027"))
conn.execute(
    "INSERT INTO uzenetek (diak_nev, felado, targy, idopont, szoveg)"
    " VALUES (?,?,?,?,?)",
    ("Kereso", "Osztályfőnök", "Kirándulás", "2026. 10. 19. 10:00",
     "Kedves Szülők! A törtek témazáró miatt egyeztetünk."))
conn.execute(
    "INSERT INTO uzenetek (diak_nev, felado, targy, idopont, szoveg)"
    " VALUES (?,?,?,?,?)",
    ("Kereso", "Titkár", "Akció", "2026. 10. 17. 08:00", "100% kedvezmény a büfében"))
conn.execute(
    "INSERT INTO hianyzasok (diak_nev, mulasztas_datum, ora_sorszam, perc, tantargy, tema,"
    " tanar, mulasztas_tipus, igazolt, tanorai_celu, igazolas_tipus, rogzites_datum, kreta_id)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Kereso", "2026-10-21", 3, None, "Fizika", "Elektromosság", "Tanár", "Hiányzás",
     0, "Nem", "", "2026-10-21", "h1"))
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


def search(q, limit=None):
    url = f"/api/kereses?q={q}"
    if limit:
        url += f"&limit={limit}"
    r = client.get(url)
    return r, (r.get_json() or {})


print("1) Keresés több adatforrásban (jegy, házi, feljegyzés, üzenet, hiányzás)")
r, d = search("elektromoss%C3%A1g")
ok(r.status_code == 200, f"HTTP 200 ({r.status_code})")
tipusok = {t["tipus"] for t in d.get("talalatok", [])}
ok("esemeny" in tipusok and "hianyzas" in tipusok,
   f"jegy és hiányzás is találat: {sorted(tipusok)}")
ok(d.get("count") == len(d.get("talalatok", [])), "a count egyezik a lista hosszával")
ok(d.get("ido_ms", 999) < 300, f"gyors (<300 ms): {d.get('ido_ms')} ms")

print("\n2) Üzenet teljes törzsben (nem csak tárgy)")
r, d = search("t%C3%B6rtek")
tipusok = {t["tipus"] for t in d.get("talalatok", [])}
ok("uzenet" in tipusok and "esemeny" in tipusok, f"üzenet + házi: {sorted(tipusok)}")
uzenet = next((t for t in d.get("talalatok", []) if t["tipus"] == "uzenet"), {})
ok("törtek" in (uzenet.get("reszlet") or "").lower(), f"a törzsből van kivonat: {uzenet.get('reszlet')}")

print("\n3) Rendezés dátum szerint csökkenő + limit")
r, d = search("%C3%B6r", limit=2)  # "ör": áramkörök, törtek, Kirándulás
tal = d.get("talalatok", [])
ok(len(tal) == 2, f"limit érvényesül: {len(tal)}")
datumok = [t.get("datum") or "" for t in tal]
ok(datumok == sorted(datumok, reverse=True), f"dátum szerint csökkenő: {datumok}")
ok(tal and datumok[0] >= datumok[-1], "a legfrissebb van legelöl")

print("\n4) Rövid keresés és nincs találat")
r, d = search("a")
ok(d.get("count") == 0 and d.get("talalatok") == [], "1 karakter -> üres")
r, d = search("zzzznincs")
ok(d.get("count") == 0, "nincs találat -> üres")

print("\n5) LIKE-speciális karakterek escape-elve")
r, d = search("100%25")
tal = d.get("talalatok", [])
ok(any("100% kedvezmény" in (t.get("reszlet") or "") for t in tal),
   f"a '%' literálként keresve is megtalálja: {[t.get('cim') for t in tal]}")
r, d = search("100%25%25")
ok(d.get("count") == 0, "a '%' nem működik wildcardként")

print("\n6) A felületi modal, a gyorsgomb és a navigáció")
html = client.get("/").get_data(as_text=True)
js = client.get("/static/js/app-main.js").get_data(as_text=True)
ok('id="keresesModal"' in html and 'id="keresesInput"' in html
   and 'id="keresesEredmeny"' in html, "a kereső modal a sablonban")
ok('id="btnKereses"' in html, "van kereső gomb a fejlécben")
ok("keresesModalNyitas" in js and "ctrlKey" in js and "e.key" in js,
   "Ctrl+K / ⌘K gyorsgomb bekötve")
ok("keresesTalalatMegnyit" in js and "goToEvents" in js and "openUzenetModal" in js
   and "hianyzasok-tab" in js, "a találat a megfelelő nézetet nyitja")
kb = js.split("function keresesBadge")[1].split("function ")[0]
ok("badge-ertekeles" in kb and "badge-feljegyzes" in kb and "badge-hazi" in kb
   and "badge-szamonkeres" in kb and "Bejelentett számonkérés" in kb
   and "Házi feladat" in kb, "a kereső típus-címkéi egyeznek az Események füllel")
ok("reszletekModal" in js and "esemenyReszletekSzoveg" in js
   and "hianyzasReszletekSzoveg" in js and "hidden.bs.modal" in js,
   "a találat sorára kattintva az adott sor részletei nyílnak meg (Kaneo #85)")
ok("250" in js, "a gépelésre debounce (250 ms) van")
ev = client.get("/api/esemenyek?diak=Kereso").get_json()
ok(any(e.get("tema") == "Elektromosság" and e.get("tartalom") for e in ev),
   "a részletek modálhoz a teljes esemény lekérhető (/api/esemenyek)")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
