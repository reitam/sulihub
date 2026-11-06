# -*- coding: utf-8 -*-
"""
„Ma” nézet (Kaneo #9): /api/ma + felületi kötés.

- mai órák (a két hét duplikátumai nélkül),
- ma/holnap esedékes házik és számonkérések a kész jelzővel,
- friss jegyek (7 nap), olvasatlan üzenetek,
- diák-szűrés, érvénytelen dátum, üres adat.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_ma_"))
db = work / "kreta_adatok.db"
config = {
    "STUDENTS": [
        {"diak_nev": "MaDiak", "enable_rewards": True, "active": False},
        {"diak_nev": "MasDiak", "enable_rewards": True, "active": False},
    ]
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

conn = sqlite3.connect(db)
# Mai órák: ugyanaz az óra két hétből (dedupe) + egy másik időpont
ORAK = [
    ("MaDiak", "2026-11-06T08:00:00", "2026-11-06T08:45:00", "hétfő", "Matematika", "Tanár", "101"),
    ("MaDiak", "2026-11-06T08:00:00", "2026-11-06T08:45:00", "hétfő", "Matematika", "Tanár", "101"),
    ("MaDiak", "2026-11-06T09:00:00", "2026-11-06T09:45:00", "hétfő", "Fizika", "Tanár2", "102"),
    ("MasDiak", "2026-11-06T08:00:00", "2026-11-06T08:45:00", "hétfő", "Angol", "Tanár3", "103"),
]
for row in ORAK:
    conn.execute(
        "INSERT INTO orarend (diak_nev, kezdo_idopont, zaro_idopont, nap, tantargy, tanar, terem)"
        " VALUES (?,?,?,?,?,?,?)", row)

ESEMENYEK = [
    ("MaDiak", "Házi feladat", "Matematika", "2026. 11. 06.", 0, "Törtek"),
    ("MaDiak", "Bejelentett számonkérés", "Fizika", "2026. 11. 07.", 0, "Erő"),
    ("MaDiak", "Házi feladat", "Angol", "2026. 11. 06.", 1, "Szavak"),
    ("MaDiak", "Házi feladat", "Biológia", "2026. 11. 10.", 0, "Későbbi"),
    ("MasDiak", "Házi feladat", "Más", "2026. 11. 06.", 0, "Más diák"),
]
for diak, tipus, tantargy, hatarido, kesz, tema in ESEMENYEK:
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, hatarido, tema, cim, tartalom, kesz, tanev)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (diak, tipus, tantargy, "", 0, 0, "2026. 11. 01.", hatarido, tema, "", "", kesz,
         "2026/2027"))

JEGYEK = [
    ("MaDiak", "Matematika", "2026. 11. 05."),
    ("MaDiak", "Fizika", "2026. 10. 01."),
]
for diak, tantargy, bej in JEGYEK:
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, hatarido, tema, cim, tartalom, kesz, tanev)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?)",
        (diak, "Értékelés", tantargy, "Jeles(5)", 5, 100, bej, "", "", "", "", "2026/2027"))

UZENETEK = [
    ("MaDiak", "Osztályfőnök", "Kirándulás", 0),
    ("MaDiak", "Titkár", "Befizetés", 0),
    ("MaDiak", "Iskola", "Régi", 1),
]
for diak, felado, targy, olvasott in UZENETEK:
    conn.execute(
        "INSERT INTO uzenetek (diak_nev, felado, targy, idopont, szoveg, olvasott)"
        " VALUES (?,?,?,?,?,?)",
        (diak, felado, targy, "2026. 11. 05.", "Szöveg", olvasott))
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


def ma(keres="", datum="2026-11-06"):
    return client.get(f"/api/ma?datum={datum}{keres}").get_json()


print("1) Mai órák (duplikátum nélkül)")
d = ma()
# 4 DB-sor: MaDiak Matematika kétszer (két hét) + Fizika, MasDiak Angol -> 3 egyedi
ok(len(d.get("orak") or []) == 3, f"3 egyedi óra (a duplikátum kimarad): {len(d.get('orak') or [])}")
ok(sum(1 for o in d["orak"] if o["tantargy"] == "Matematika") == 1,
   "a kéthetes duplikátumból egy Matematika-óra marad")
ok(d["orak"][0]["kezdes"] == "08:00" and d["orak"][0]["tantargy"] == "Matematika",
   f"az első óra 08:00 Matematika: {d['orak'][0]}")
ok(d["orak"][0]["terem"] == "101" and d["orak"][0]["tanar"] == "Tanár", "terem és tanár megvan")

print("\n2) Ma / holnap esedékes határidők")
hat = d.get("hataridok") or []
ok(len(hat) == 4, f"4 határidő (ma 3 + holnap 1, a későbbi nem): {len(hat)}")
ok(sum(1 for e in hat if e["mikor"] == "ma") == 3, "3 mai")
ok(any(e["kesz"] == 1 for e in hat), "a kész jelző átjön")
ok(all(e["hatarido"] in ("2026-11-06", "2026-11-07") for e in hat), "csak ma/holnap")

print("\n3) Friss jegyek (7 nap) és olvasatlan üzenetek")
ok(len(d.get("uj_jegyek") or []) == 1, f"1 friss jegy: {len(d.get('uj_jegyek') or [])}")
ok(d["uj_jegyek"][0]["tantargy"] == "Matematika", "a friss jegy a Matematika")
ok(d.get("olvasatlan_db") == 2, f"2 olvasatlan: {d.get('olvasatlan_db')}")
ok(len(d.get("uzenetek") or []) == 2, "2 üzenet-előnézet")

print("\n4) Diák-szűrés")
d2 = ma("&diak=MasDiak")
ok(len(d2.get("orak") or []) == 1 and d2["orak"][0]["tantargy"] == "Angol", "MasDiak órái")
ok(len(d2.get("hataridok") or []) == 1, "MasDiak határideje")
ok(d2.get("olvasatlan_db") == 0, "MasDiaknak nincs olvasatlanja")

print("\n5) Más nap / üres adat / hibás dátum")
ures = ma(datum="2026-12-24")
ok(ures.get("orak") == [] and ures.get("hataridok") == [] and ures.get("uj_jegyek") == [],
   "üres napon üres a válasz")
r = client.get("/api/ma?datum=2026-13-99")
ok(r.status_code == 400, f"hibás dátum -> 400 ({r.status_code})")

print("\n6) Felületi kötés")
html = client.get("/").get_data(as_text=True)
js = client.get("/static/js/app-main.js").get_data(as_text=True)
ok('id="maCard"' in html and 'id="maOrak"' in html and 'id="maHataridok"' in html
   and 'id="maJegyek"' in html and 'id="maUzenetek"' in html, "a Ma kártya a sablonban")
ok("loadMa" in js and "/api/ma" in js and "ma-kesz" in js and "ma-uzenet" in js,
   "a JS betölti és a gyors műveletek bekötve")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
