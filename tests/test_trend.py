# -*- coding: utf-8 -*-
"""
Tantárgyi trend + hiányzás-mintázat (Kaneo #80).

- `/api/atlagok`: tantárgyankénti trend (utolsó két hónap különbsége) és
  romlás-figyelmeztetés (<= -0.5);
- `/api/hianyzas-mintazat`: nap / órasorszám / tantárgy / hónap bontás;
- üres adat, tanév-szűrés, felületi kötés.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_trend_"))
db = work / "kreta_adatok.db"
config = {"ENABLE_REWARDS": True,
          "STUDENTS": [{"diak_nev": "TrendDiak", "enable_rewards": True, "active": False}]}
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

JEGYEK = [
    # tantárgy, jegy, dátum
    ("Romlo", 5, "2026. 09. 10."), ("Romlo", 4, "2026. 10. 10."), ("Romlo", 3, "2026. 11. 05."),
    ("Javulo", 3, "2026. 09. 12."), ("Javulo", 4, "2026. 10. 12."),
    ("Stabil", 4, "2026. 09. 15."), ("Stabil", 4, "2026. 10. 15."),
    ("EgyHonap", 5, "2026. 11. 01."),
]
HIANYZASOK = [
    ("2026-11-02", 1, "Matematika"),   # hétfő
    ("2026-11-03", 2, "Fizika"),       # kedd
    ("2026-11-09", 1, "Matematika"),   # hétfő
]

conn = sqlite3.connect(db)
for tantargy, jegy, datum in JEGYEK:
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, hatarido, tema, cim, tartalom, kesz, tanev)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?)",
        ("TrendDiak", "Értékelés", tantargy, f"Jegy({jegy})", jegy, 100, datum, "",
         "", "", "", "2026/2027"))
for datum, ora, tantargy in HIANYZASOK:
    conn.execute(
        "INSERT INTO hianyzasok (diak_nev, mulasztas_datum, ora_sorszam, perc, tantargy,"
        " tema, tanar, mulasztas_tipus, igazolt, tanorai_celu, igazolas_tipus,"
        " rogzites_datum, kreta_id, tanev)"
        " VALUES (?,?,?,NULL,?,?,?, 'Hiányzás',0,'Nem','',?,'x','2026/2027')",
        ("TrendDiak", datum, ora, tantargy, "Téma", "Tanár", datum))
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


print("1) Tantárgyi trend (/api/atlagok)")
d = client.get("/api/atlagok?diak=TrendDiak").get_json()
by_t = {t["tantargy"]: t for t in d.get("tantargyak", [])}
romlo = by_t.get("Romlo", {}).get("trend") or {}
ok(romlo.get("irany") == "romlik" and romlo.get("valtozas") == -1.0,
   f"Romlo: romlik, -1.0 ({romlo})")
javulo = by_t.get("Javulo", {}).get("trend") or {}
ok(javulo.get("irany") == "javul" and javulo.get("valtozas") == 1.0,
   f"Javulo: javul, +1.0 ({javulo})")
stabil = by_t.get("Stabil", {}).get("trend") or {}
ok(stabil.get("irany") == "stabil", f"Stabil: stabil ({stabil})")
egy = by_t.get("EgyHonap", {}).get("trend") or {}
ok(egy.get("irany") == "nincs" and egy.get("valtozas") is None,
   f"egy hónap -> nincs trend ({egy})")

print("\n2) Romlás-figyelmeztetés (<= -0.5) és javulás (>= +0.5)")
figy = d.get("figyelmeztetesek") or []
ok(len(figy) == 1 and figy[0]["tantargy"] == "Romlo" and figy[0]["valtozas"] == -1.0,
   f"csak a Romlo figyelmeztet: {figy}")
ok(figy and figy[0].get("diak") == "TrendDiak", f"a figyelmeztetésben benne a gyerek: {figy}")
ok(figy and figy[0].get("honapok") == ["2026-10", "2026-11"],
   f"a figyelmeztetésben benne az időszak: {figy and figy[0].get('honapok')}")
jav = d.get("javulasok") or []
ok(len(jav) == 1 and jav[0]["tantargy"] == "Javulo" and jav[0]["valtozas"] == 1.0
   and jav[0].get("diak") == "TrendDiak", f"a Javulo javulásként szerepel: {jav}")

print("\n2b) „Mind” nézet: gyermekenkénti figyelmeztetés")
d_mind = client.get("/api/atlagok").get_json()
figy_mind = d_mind.get("figyelmeztetesek") or []
jav_mind = d_mind.get("javulasok") or []
ok(len(figy_mind) == 1 and figy_mind[0].get("diak") == "TrendDiak"
   and figy_mind[0]["tantargy"] == "Romlo", f"gyerek nélkül is megvan a romló: {figy_mind}")
ok(len(jav_mind) == 1 and jav_mind[0].get("diak") == "TrendDiak"
   and jav_mind[0]["tantargy"] == "Javulo", f"gyerek nélkül is megvan a javuló: {jav_mind}")

print("\n3) Hiányzás-mintázat")
m = client.get("/api/hianyzas-mintazat?diak=TrendDiak").get_json()
ok(m.get("osszes") == 3, f"3 hiányzás: {m.get('osszes')}")
napok = {n["nev"]: n["db"] for n in m.get("hetnap", [])}
ok(napok.get("hétfő") == 2 and napok.get("kedd") == 1, f"napok: {napok}")
orak = {o["ora"]: o["db"] for o in m.get("ora", [])}
ok(orak.get(1) == 2 and orak.get(2) == 1, f"órasorszámok: {orak}")
tant = {t["tantargy"]: t["db"] for t in m.get("tantargyak", [])}
ok(tant.get("Matematika") == 2 and tant.get("Fizika") == 1, f"tantárgyak: {tant}")
ok(len(m.get("honapok") or []) >= 1, f"hónapok: {m.get('honapok')}")

print("\n4) Tanév-szűrés + üres adat")
m2 = client.get("/api/hianyzas-mintazat?diak=TrendDiak&tanev=2025%2F2026").get_json()
ok(m2.get("osszes") == 0, "más tanévben nincs hiányzás")
ures = client.get("/api/atlagok?diak=NincsIlyen").get_json()
ok(ures.get("tantargyak") == [] and ures.get("figyelmeztetesek") == [],
   "ismeretlen diák -> üres, hiba nélkül")

print("\n5) Felületi kötés")
html = client.get("/").get_data(as_text=True)
js = client.get("/static/js/app-main.js").get_data(as_text=True)
ok('id="trendFigyelmeztetes"' in html and 'id="trendJavulas"' in html
   and 'id="mintazatCard"' in html
   and 'id="mintazatNapok"' in html, "a figyelmeztető/javuló sáv és a mintázat-kártya a sablonban")
ok('class="trend-fej"' in html and 'aria-expanded="false"' in html
   and 'trend-torzs' in html and 'trend-nyitva' in html,
   "a trend-sáv lenyitható (gomb + lenyíló törzs)")
ok('position: fixed; inset: 0' in html and '@media (max-width: 767.98px)' in html,
   "mobilon kinyitva a trend-panel teljes képernyős")
ok('max-height: 320px' in html and '.trend-panel.trend-nyitva .trend-torzs' in html,
   "asztalon a trend-panel helyben, gordithetően nyilik")
ok('id="mintazatCollapse"' in html and 'collapse' in html.split('id="mintazatCollapse"')[0][-80:],
   "a mintázat alapból csukott (nem kezdésként jelenik meg)")
ok(html.index('id="mintazatCard"') > html.index('id="hianyzasokTable"'),
   "a mintázat-kártya a hiányzás-táblázat UTÁN van")
ok("sparklineSvg" in js and "trendCella" in js and "figyelmeztetesek" in js
   and "javulasok" in js and "trendSor" in js and "trendPanelFeltolt" in js
   and "trend-nyitva" in js,
   "a trend-sparkline és a lenyitható figyelmeztetés/javulás a JS-ben")
ok("loadHianyzasMintazat" in js and "/api/hianyzas-mintazat" in js,
   "a mintázat betöltése a JS-ben")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
