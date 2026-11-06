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

print("\n8) Érvénytelen bemenetek")
ok(get("/api/jegy_kalkulator?tantargy=Matek&cel=6").status_code == 400, "cel=6 -> 400")
ok(get("/api/jegy_kalkulator?tantargy=Matek&cel=abc").status_code == 400, "cel=abc -> 400")
ok(get("/api/jegy_kalkulator?tantargy=Matek&suly=0").status_code == 400, "suly=0 -> 400")
ok(get("/api/jegy_kalkulator?cel=4").status_code == 400, "tantárgy nélkül -> 400")

print("\n9) A felületi kártya és a JS-kötés megvan")
html = client.get("/").get_data(as_text=True)
js = client.get("/static/js/app-main.js").get_data(as_text=True)
ok('id="jegyKalkulatorCard"' in html and 'id="kalkTantargy"' in html
   and 'id="kalkCel"' in html and 'id="kalkSuly"' in html and 'id="btnKalkulal"' in html,
   "a kártya és a vezérlők a sablonban")
ok('id="kalkEredmeny"' in html and "Milyen jegy kell?" in html, "van eredmény-hely és cím")
ok("szamolJegyKalkulator" in js and "/api/jegy_kalkulator" in js, "a JS hívja az API-t")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
