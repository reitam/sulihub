# -*- coding: utf-8 -*-
"""
„Milyen jegy kell?” kalkulátor (Kaneo #78).

- a súlyozott átlag a KRÉTA logikáját követi (0%-os súly kimarad);
- egy új jegy (a választott súllyal) vagy több ötös szükséges-e;
- elérhetetlen cél, hiányzó jegy, érvénytelen bemenet;
- tanév-szűrés (a korábbi tanév jegyét nem számolja);
- a felületi kártya és a JS-kötés megvan.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_kalk_"))
db = work / "kreta_adatok.db"
config = {
    "ENABLE_REWARDS": True,
    "STUDENTS": [{"diak_nev": "KalkDiak", "enable_rewards": True, "active": False}],
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

GRADES = [
    # tantárgy, jegy, súly, dátum, tanév
    ("Matek", 5, 100, "2026. 09. 10.", "2026/2027"),
    ("Matek", 4, 100, "2026. 10. 10.", "2026/2027"),
    ("Matek", 1, 100, "2025. 10. 10.", "2025/2026"),
    ("Fizika", 2, 100, "2026. 09. 20.", "2026/2027"),
    ("NullaSuly", 3, 0, "2026. 09. 25.", "2026/2027"),
]
conn = sqlite3.connect(db)
for tantargy, jegy, suly, datum, tanev in GRADES:
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, tanev, kesz, hatarido, ertekelo, tipus, mod, tema, cim, tartalom)"
        " VALUES (?,?,?,?,?,?,?,?,0,'','Tanár','Évközi jegy','Írásbeli','Téma','','')",
        ("KalkDiak", "Értékelés", tantargy, f"Jegy({jegy})", jegy, suly, datum, tanev))
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


def get(path):
    return client.get(path)


print("1) Már megvan a cél")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Matek&cel=4.5&suly=100&tanev=2026%2F2027")
d = r.get_json()
ok(r.status_code == 200, f"HTTP 200 ({r.status_code})")
ok(d.get("elerheto") is True and d.get("szukseges_jegy") is None,
   f"nincs szükség új jegyre: {d.get('uzenet')}")
ok(d.get("aktualis_atlag") == 4.5, f"aktuális átlag 4.5: {d.get('aktualis_atlag')}")
ok("Már megvan" in (d.get("uzenet") or ""), "a magyarázat jelzi, hogy már megvan")

print("\n2) Egy ötös kell")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Matek&cel=4.6&suly=100&tanev=2026%2F2027")
d = r.get_json()
ok(d.get("elerheto") is True and d.get("szukseges_jegy") == 5 and d.get("szukseges_darab") == 1,
   f"1 db ötös: {d.get('szukseges_jegy')} × {d.get('szukseges_darab')}")
ok(d.get("varhato_atlag") == 4.67, f"várható átlag 4.67: {d.get('varhato_atlag')}")
ok("1 db 5-ös" in (d.get("uzenet") or ""), f"üzenet: {d.get('uzenet')}")

print("\n3) Több ötös kell")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Fizika&cel=4&suly=100&tanev=2026%2F2027")
d = r.get_json()
ok(d.get("elerheto") is True and d.get("szukseges_jegy") == 5 and d.get("szukseges_darab") == 2,
   f"2 db ötös: {d.get('szukseges_jegy')} × {d.get('szukseges_darab')}")
ok(d.get("varhato_atlag") == 4.0, f"várható átlag 4.0: {d.get('varhato_atlag')}")

print("\n4) Elérhetetlen cél (5.0)")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Fizika&cel=5&suly=100&tanev=2026%2F2027")
d = r.get_json()
ok(d.get("elerheto") is False and d.get("szukseges_jegy") is None,
   f"5.0 nem érhető el: {d.get('uzenet')}")

print("\n5) 0%-os súly kimarad (súly nélküli adat -> egyszerű átlag)")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=NullaSuly&cel=4&suly=100&tanev=2026%2F2027")
d = r.get_json()
ok(d.get("aktualis_atlag") == 3.0 and d.get("suly_db") == 0,
   f"a 0%-os jegy nem súlyozott: {d.get('aktualis_atlag')} / suly_db={d.get('suly_db')}")
ok(d.get("elerheto") is True and d.get("szukseges_jegy") == 5 and d.get("szukseges_darab") == 1,
   f"egyszerű átlaggal 1 db ötös: {d.get('uzenet')}")

print("\n6) Nincs jegy a tantárgyban")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Ures&cel=4&suly=100&tanev=2026%2F2027")
d = r.get_json()
ok(d.get("elerheto") is False and d.get("aktualis_atlag") is None,
   f"nincs jegy: {d.get('uzenet')}")

print("\n7) Tanév-szűrés: a korábbi tanév jegyét nem számolja")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Matek&cel=4.5&suly=100&tanev=2026%2F2027")
d = r.get_json()
ok(d.get("jegy_db") == 2 and d.get("aktualis_atlag") == 4.5,
   f"csak a 2026/2027 jegyek: {d.get('jegy_db')} db, {d.get('aktualis_atlag')}")

print("\n7b) A meglévő jegyek listája (Kaneo #78)")
jegyek = d.get("jegyek") or []
ok(len(jegyek) == 2, f"2 meglévő jegy a válaszban: {jegyek}")
ok([j.get("szam") for j in jegyek] == [4, 5], f"legfrissebb elöl: {[j.get('szam') for j in jegyek]}")
ok(jegyek and jegyek[0].get("datum") == "2026-10-10" and jegyek[0].get("suly") == 100,
   f"dátum és súly is megvan: {jegyek and jegyek[0]}")
ok(all(j.get("szam") != 1 for j in jegyek), "a korábbi tanév jegyét nem listázza")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Ures&cel=4&suly=100&tanev=2026%2F2027")
ok(r.get_json().get("jegyek") == [], "nincs jegy -> üres lista")

print("\n8) Érvénytelen bemenetek")
ok(get("/api/jegy_kalkulator?tantargy=Matek&cel=6").status_code == 400, "cel=6 -> 400")
ok(get("/api/jegy_kalkulator?tantargy=Matek&cel=abc").status_code == 400, "cel=abc -> 400")
ok(get("/api/jegy_kalkulator?tantargy=Matek&suly=0").status_code == 400, "suly=0 -> 400")
ok(get("/api/jegy_kalkulator?cel=4").status_code == 400, "tantárgy nélkül -> 400")
ok(get("/api/jegy_kalkulator?tantargy=Matek&felevi=6").status_code == 400, "felevi=6 -> 400")

print("\n8b) Több várható jegy (Kaneo #101)")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Matek&cel=4.7&sulyok=100,100"
        "&tanev=2026%2F2027")
d = r.get_json()
ok(r.status_code == 200 and d.get("tobb") is True, f"több jegy mód ({r.status_code})")
ok(d.get("jegyek_szama") == 2 and d.get("suly_osszeg") == 200,
   f"2 jegy, 200% összsúly: {d.get('jegyek_szama')} / {d.get('suly_osszeg')}")
ok(d.get("szukseges_atlag") == 4.9,
   f"súlyozottan 4.9-es átlag kell: {d.get('szukseges_atlag')}")
ok("4.9" in (d.get("uzenet") or ""), f"az üzenet mondja a szükséges átlagot: {d.get('uzenet')}")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Matek&cel=5&sulyok=100,100"
        "&tanev=2026%2F2027")
d = r.get_json()
ok(d.get("elerheto") is False and d.get("szukseges_atlag") is None,
   f"5.0 két jegyből nem érhető el: {d.get('uzenet')}")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Fizika&cel=4&sulyok=100,100"
        "&tanev=2026%2F2027")
d = r.get_json()
ok(d.get("elerheto") is True and d.get("szukseges_atlag") == 5.0,
   f"Fizika 2-ből 4.0-hoz 5.0-es átlag kell: {d.get('szukseges_atlag')}")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Matek&cel=4.5&sulyok=100,100"
        "&varhato=5,4&tanev=2026%2F2027")
d = r.get_json()
ok(d.get("szimulalt_atlag") == 4.5 and d.get("cel_teljesul") is True,
   f"5+4 várható jegy -> 4.5-es átlag: {d.get('szimulalt_atlag')}")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Matek&cel=4.6&sulyok=100"
        "&tanev=2026%2F2027")
d = r.get_json()
ok(d.get("tobb") is False and "1 db 5-ös" in (d.get("uzenet") or ""),
   f"egy várható jegy -> a régi, konkrét üzenet: {d.get('uzenet')}")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Matek&cel=4.6&sulyok=100&varhato=5"
        "&tanev=2026%2F2027")
d = r.get_json()
ok(d.get("szimulalt_atlag") == 4.67, f"1 db 5-ös -> 4.67: {d.get('szimulalt_atlag')}")

print("\n8c) Félévi cél és mentett célátlag (Kaneo #101)")
r = get("/api/jegy_kalkulator?diak=KalkDiak&tantargy=Fizika&cel=4&felevi=3&sulyok=100"
        "&tanev=2026%2F2027")
d = r.get_json()
ok(d.get("felevi_cel") == 3 and d.get("felevi_kuszob") == 2.5,
   f"félévi 3-hoz 2.5-es küszöb: {d.get('felevi_kuszob')}")
ok(d.get("felevi_elerheto") is True and d.get("felevi_szukseges_atlag") == 3.0,
   f"a hátralévő jegyen 3.0 kell: {d.get('felevi_szukseges_atlag')}")
r = client.post("/api/kalkulator_cel", json={"diak": "KalkDiak", "tantargy": "Matek",
                                             "cel": 4.2, "felevi": 4})
ok(r.status_code == 200, f"mentés ({r.status_code})")
d = client.get("/api/kalkulator_cel?diak=KalkDiak&tantargy=Matek").get_json()
ok(d.get("cel") == 4.2 and d.get("felevi") == 4, f"visszatöltés: {d}")
r = client.post("/api/kalkulator_cel", json={"diak": "KalkDiak", "tantargy": "Matek",
                                             "cel": "", "felevi": ""})
d = client.get("/api/kalkulator_cel?diak=KalkDiak&tantargy=Matek").get_json()
ok(r.status_code == 200 and d.get("cel") is None and d.get("felevi") is None,
   "üres cél törli a mentést")
ok(client.post("/api/kalkulator_cel", json={"tantargy": ""}).status_code == 400,
   "tantárgy nélkül -> 400")
ok(client.post("/api/kalkulator_cel", json={"tantargy": "Matek", "felevi": 9}).status_code == 400,
   "felevi=9 -> 400")

print("\n9) A felületi kártya és a JS-kötés megvan")
html = client.get("/").get_data(as_text=True)
js = client.get("/static/js/app-main.js").get_data(as_text=True)
ok('id="jegyKalkulatorCard"' in html and 'id="kalkTantargy"' in html
   and 'id="kalkCel"' in html and 'id="kalkSuly"' in html and 'id="btnKalkulal"' in html,
   "a kártya és a vezérlők a sablonban")
ok('id="kalkFelevi"' in html and 'id="kalkVarhatoJegy"' in html
   and 'id="kalkVarhatoLista"' in html and 'id="btnKalkVarhatoAdd"' in html,
   "van félévi cél és több várható jegy (Kaneo #101)")
ok('— Válassz tantárgyat —' in html,
   "a tantárgy-választó alapból üres (Kaneo #78)")
ok('id="kalkEredmeny"' in html and "Milyen jegy kell?" in html, "van eredmény-hely és cím")
ok('id="kalkJegyek"' in html, "van külön hely a meglévő jegyek listájának")
ok("szamolJegyKalkulator" in js and "/api/jegy_kalkulator" in js, "a JS hívja az API-t")
ok("kezdo_datum" not in js.split("function szamolJegyKalkulator")[1].split("function ")[0],
   "a kalkulátor nem küld időszak-szűrést (a teljes tanév jegyállományát használja)")
ok("renderKalkJegyek" in js and "Meglévő jegyek" in js and "res.jegyek" in js,
   "a JS táblázatban kilistázza a meglévő jegyeket")
ok("kalkCelBetolt" in js and "/api/kalkulator_cel" in js and "kalkCelMent" in js,
   "a célátlag betöltése/mentése bekötve")
ok("if ($sel.val()) szamolJegyKalkulator();" not in js,
   "a kártya nyitáskor nem számol automatikusan (üres a választó)")
ok("if (!tantargy) {" in js and "$('#kalkJegyek').empty();" in js,
   "üres tantárgynál nincs jegy-lista")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
