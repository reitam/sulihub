# -*- coding: utf-8 -*-
"""
Kitűzött események (Kaneo #86): /api/kedvencek + felületi kötés.

- üres lista; hozzáadás/levétel/toggle; érvénytelen kérés;
- a kulcs a stabil tartalom-kulcs (a szinkron nem töri el);
- a felületi panel, a csillag gomb és a JS hívás megvan.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_kedvenc_"))
db = work / "kreta_adatok.db"
config = {"STUDENTS": [{"diak_nev": "Kedvenc", "enable_rewards": True, "active": False}]}
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
for i, (tantargy, tipus) in enumerate([("Matematika", "Értékelés"), ("Fizika", "Házi feladat")]):
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, hatarido, tema, cim, tartalom, kesz, tanev)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?)",
        ("Kedvenc", tipus, tantargy, "Jeles(5)" if tipus == "Értékelés" else "", 5 if tipus == "Értékelés" else 0,
         100, f"2026. 10. 1{i}.", "2026. 10. 20.", "Téma", "Cím", "Tartalom", "2026/2027"))
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


def post(payload):
    return client.post("/api/kedvencek", json=payload)


print("1) Kezdetben üres")
r = client.get("/api/kedvencek")
d = r.get_json()
ok(r.status_code == 200 and d.get("kulcsok") == [] and d.get("esemenyek") == [],
   f"üres lista: {d}")

esemenyek = client.get("/api/esemenyek").get_json()
kulcs = esemenyek[0]["komment_kulcs"]
ok(bool(kulcs), f"van stabil kulcs: {kulcs}")

print("\n2) Hozzáadás")
r = post({"kulcs": kulcs, "akcio": "add"})
d = r.get_json()
ok(r.status_code == 200 and d.get("kulcsok") == [kulcs], f"egy kulcs: {d.get('kulcsok')}")
ok(len(d.get("esemenyek") or []) == 1 and d["esemenyek"][0]["kulcs"] == kulcs,
   "a kitűzött esemény adatai is jönnek")
ok(d["esemenyek"][0]["diak_nev"] == "Kedvenc", "a diák neve megvan")

print("\n3) Levétel")
r = post({"kulcs": kulcs, "akcio": "remove"})
d = r.get_json()
ok(d.get("kulcsok") == [] and d.get("esemenyek") == [], "levétel után üres")

print("\n4) Toggle")
d = post({"kulcs": kulcs, "akcio": "toggle"}).get_json()
ok(d.get("kulcsok") == [kulcs], "toggle -> hozzáadva")
d = post({"kulcs": kulcs, "akcio": "toggle"}).get_json()
ok(d.get("kulcsok") == [], "toggle -> levéve")

print("\n5) Perzisztencia (app_meta) és érvénytelen kérés")
post({"kulcs": kulcs, "akcio": "add"})
d = client.get("/api/kedvencek").get_json()
ok(d.get("kulcsok") == [kulcs], "új kérésben is megvan (DB-ben tárolva)")
ok(post({}).status_code == 400, "kulcs nélkül 400")
ok(post({"kulcs": "  "}).status_code == 400, "üres kulcs 400")

print("\n5b) Megjegyzés és húzásos sorrend (Kaneo #108)")
kulcsok = [e["komment_kulcs"] for e in client.get("/api/esemenyek").get_json()]
ok(len(kulcsok) >= 2, f"legalább 2 stabil kulcs: {len(kulcsok)}")
k1, k2 = kulcsok[0], kulcsok[1]
post({"kulcs": k2, "akcio": "add"})
d = post({"akcio": "note", "kulcs": k1, "megjegyzes": "Fontos határidő"}).get_json()
jegyzet = {e["kulcs"]: e.get("megjegyzes") for e in d.get("esemenyek", [])}
ok(jegyzet.get(k1) == "Fontos határidő", f"a megjegyzés mentődik: {jegyzet}")
d = post({"akcio": "order", "kulcsok": [k2, k1]}).get_json()
ok(d.get("kulcsok") == [k2, k1], f"a sorrend mentődik: {d.get('kulcsok')}")
d = client.get("/api/kedvencek").get_json()
ok(d.get("kulcsok") == [k2, k1], "újratöltés után is a mentett sorrend")
ok({e["kulcs"]: e.get("megjegyzes") for e in d["esemenyek"]}.get(k1) == "Fontos határidő",
   "a sorrendezés nem veszíti el a megjegyzést")
d = post({"akcio": "remove", "kulcs": k2}).get_json()
ok(d.get("kulcsok") == [k1], f"levétel után marad a sorrend: {d.get('kulcsok')}")

print("\n6) Felületi kötés")
html = client.get("/").get_data(as_text=True)
js = client.get("/static/js/app-main.js").get_data(as_text=True)
ok('id="kedvencPanel"' in html and 'id="kedvencLista"' in html, "a dashboard panel a sablonban")
ok("btn-kedvenc" in js and "betoltKedvencek" in js and "/api/kedvencek" in js,
   "a csillag gomb és a JS hívás megvan")
ok("kedvenc-torol" in js and "kedvenc-ugras" in js, "a panelen van eltávolítás és ugrás")
ok("kedvenc-jegyzet-szerk" in js and "akcio: 'note'" in js,
   "a panelen megjegyzés szerkeszthető (#108)")
ok("kedvenc-sor" in js and "akcio: 'order'" in js and "dragstart" in js,
   "a sorok húzhatók és a sorrend mentődik (#108)")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
