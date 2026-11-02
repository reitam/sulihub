# -*- coding: utf-8 -*-
"""Statisztika / zsebpénz végpont: súlyozott átlag és kikapcsolt zsebpénz.

- A tanulmányi átlag a jegyek súlyszázaléka szerint súlyozva számol (a KRÉTA
  `SulySzazalekErteke` / webes „Súly: N%" mezője), a 0%-os súlyú jegy kimarad.
- Súlyadat nélkül (régi DB) az egyszerű átlagot adja vissza.
- Ha a zsebpénz modul ki van kapcsolva a diáknál, a statisztika akkor is működik,
  csak a pénz-összegek 0-k (`rewards_enabled: false`).
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_hibak = []


def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


work = Path(tempfile.mkdtemp(prefix="kreta_stat_"))
db = work / "kreta_adatok.db"
config = {
    "ENABLE_REWARDS": True,
    "REWARDS": {"jegy_5": 500, "jegy_4": 200, "jegy_3": 0, "jegy_2": -200, "jegy_1": -500,
                "dicseret": 500, "megrovas": -500, "lecke_hiany": -300, "felszereles_hiany": -300},
    "STUDENTS": [
        {"diak_nev": "Sulyos", "enable_rewards": True, "active": False},
        {"diak_nev": "Reegi", "enable_rewards": True, "active": False},
        {"diak_nev": "NincsZsebpenz", "enable_rewards": False, "active": False},
    ],
}
(work / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_HOST": "127.0.0.1",
    "KRETA_PORT": str(free_port()),
    "KRETA_SERVER": "flask",
    "KRETA_DEBUG": "0",
    "PYTHONIOENCODING": "utf-8",
})
env.pop("KRETA_CSATOLMANYOK_DIR", None)

# Teljes séma a scraper --init-db módjával (kifizetesek tábla is kell).
subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

conn = sqlite3.connect(db)
ROWS = [
    # diák, típus, tantárgy, érték, szám, súly, dátum
    ("Sulyos", "Értékelés", "Matematika", "Jeles(5)", 5, 100, "2026. 09. 20."),
    ("Sulyos", "Értékelés", "Matematika", "Jeles(5)", 5, 100, "2026. 10. 10."),
    ("Sulyos", "Értékelés", "Matematika", "Jó(4)", 4, 200, "2026. 10. 12."),
    ("Sulyos", "Értékelés", "Fizika", "Közepes(3)", 3, 0, "2026. 10. 14."),
    ("Sulyos", "Feljegyzés", "-", "-", 0, 0, "2026. 10. 15."),
    ("Reegi", "Értékelés", "Történelem", "Jeles(5)", 5, 0, "2026. 10. 11."),
    ("Reegi", "Értékelés", "Történelem", "Közepes(3)", 3, 0, "2026. 10. 13."),
    ("NincsZsebpenz", "Értékelés", "Angol nyelv", "Jeles(5)", 5, 100, "2026. 10. 09."),
    ("NincsZsebpenz", "Értékelés", "Angol nyelv", "Jó(4)", 4, 50, "2026. 10. 16."),
]
for diak, tipus, tantargy, ertek, szam, suly, datum in ROWS:
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
        (diak, tipus, tantargy, ertek, szam, suly, datum, "", "Tanár", "Évközi jegy",
         "Írásbeli", "Téma", "Dicséret" if tipus == "Feljegyzés" else "", ""))
conn.execute("""
    CREATE TABLE IF NOT EXISTS kifizetesek (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        diak_nev TEXT NOT NULL,
        kezdo_datum TEXT NOT NULL,
        zaro_datum TEXT NOT NULL,
        kifizetve INTEGER DEFAULT 0,
        osszeg INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(diak_nev, kezdo_datum, zaro_datum)
    )
""")
conn.execute(
    "INSERT INTO kifizetesek (diak_nev, kezdo_datum, zaro_datum, kifizetve, osszeg)"
    " VALUES (?,?,?,?,?)", ("Sulyos", "2026-09-01", "2026-09-30", 1, 500))
for i, igazolt in enumerate([0, 0, 1]):
    conn.execute(
        "INSERT INTO hianyzasok (diak_nev, mulasztas_datum, ora_sorszam, perc, tantargy,"
        " tema, tanar, mulasztas_tipus, igazolt, tanorai_celu, igazolas_tipus,"
        " rogzites_datum, kreta_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("Sulyos", f"2026-10-0{i + 1}", i + 1, None, "Matematika", "Téma", "Tanár",
         "Hiányzás", igazolt, "Nem", "", "2026-10-01", f"h{i}"))
conn.commit()
conn.close()

port = free_port()
env["KRETA_PORT"] = str(port)
proc = subprocess.Popen([sys.executable, "app.py"], cwd=str(ROOT), env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = f"http://127.0.0.1:{port}"


def get_json(path):
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


try:
    for _ in range(60):
        try:
            with urllib.request.urlopen(base + "/health", timeout=1) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.3)
    else:
        print("HIBA: az app nem indult el")
        sys.exit(1)

    print("\n1) Súlyozott átlag")
    sulyos = get_json("/api/statisztika?diak=Sulyos&kezdo_datum=2026-10-01&zaro_datum=2026-10-31")
    ok(sulyos.get("enabled") is True, "enabled = true")
    ok(sulyos.get("atlag_sulyozott") == 4.33,
       f"súlyozott átlag (5*100 + 4*200) / 300 = 4.33: {sulyos.get('atlag_sulyozott')}")
    ok(sulyos.get("atlag_egyszeru") == 4.0, f"egyszerű átlag 4.0: {sulyos.get('atlag_egyszeru')}")
    ok(sulyos.get("atlag") == 4.33, f"a megjelenített atlag a súlyozott: {sulyos.get('atlag')}")
    ok(sulyos.get("sulyozott_db") == 2, f"2 jegynek van súlya: {sulyos.get('sulyozott_db')}")
    ok(sulyos.get("jegy_total_count") == 3, "3 numerikus jegy")
    ok(sulyos.get("jegy_counts", {}).get("5") == 1 or sulyos.get("jegy_counts", {}).get(5) == 1,
       "a jegy-eloszlás változatlan")

    print("\n2) Súlyadat nélkül (régi DB) -> egyszerű átlag")
    regi = get_json("/api/statisztika?diak=Reegi&kezdo_datum=2026-10-01&zaro_datum=2026-10-31")
    ok(regi.get("atlag_sulyozott") is None, "nincs súlyozott átlag (None)")
    ok(regi.get("atlag") == 4.0 and regi.get("atlag_egyszeru") == 4.0,
       f"átlag = egyszerű (5+3)/2 = 4.0: {regi.get('atlag')}")

    print("\n3) Kikapcsolt zsebpénz -> statisztika él, pénz 0")
    nz = get_json("/api/statisztika?diak=NincsZsebpenz&kezdo_datum=2026-10-01&zaro_datum=2026-10-31")
    ok(nz.get("enabled") is True, "enabled = true (a statisztika nem tűnik el)")
    ok(nz.get("rewards_enabled") is False, "rewards_enabled = false")
    ok(nz.get("jegy_total_count") == 2, f"a jegyek számolva vannak: {nz.get('jegy_total_count')}")
    ok(nz.get("atlag") == 4.67, f"a súlyozott átlag él ((5*100+4*50)/150): {nz.get('atlag')}")
    ok(nz.get("vegosszeg") == 0 and nz.get("jegy_osszeg") == 0,
       f"a pénz-összegek 0-k: {nz.get('vegosszeg')}")
    ok(all(t.get("osszeg") == 0 for t in (nz.get("teteles_lista") or [])),
       "a tételes lista összegei 0-k")

    print("\n4) Zsebpénz engedélyezve -> pénz számol")
    ok(sulyos.get("rewards_enabled") is True, "rewards_enabled = true")
    ok(sulyos.get("vegosszeg") == 500 + 200 + 500,
       f"vegösszeg = 5-ös 500 + 4-es 200 + dicséret 500 = 1200: {sulyos.get('vegosszeg')}")

    print("\n5) Tantárgyi átlagok havi bontással (/api/atlagok, Kaneo #39)")
    atl = get_json("/api/atlagok?diak=Sulyos")
    ok(atl.get("honapok") == ["2026-09", "2026-10"], f"hónapok: {atl.get('honapok')}")
    by_t = {t["tantargy"]: t for t in atl.get("tantargyak", [])}
    ok(set(by_t) == {"Fizika", "Matematika"}, f"tantárgyak: {sorted(by_t)}")
    mat = by_t.get("Matematika", {})
    ok((mat.get("honapok") or {}).get("2026-09", {}).get("atlag") == 5.0,
       f"szeptember: {mat.get('honapok', {}).get('2026-09')}")
    ok((mat.get("honapok") or {}).get("2026-10", {}).get("atlag") == 4.33,
       f"október súlyozva: {mat.get('honapok', {}).get('2026-10')}")
    ok((mat.get("osszes") or {}).get("atlag") == 4.5,
       f"Matematika összes (5*100+5*100+4*200)/400 = 4.5: {mat.get('osszes')}")
    fiz = by_t.get("Fizika", {})
    ok((fiz.get("osszes") or {}).get("atlag") == 3.0, "0%-os súly -> egyszerű átlag (3.0)")
    ok((atl.get("osszes") or {}).get("atlag") == 4.5 and (atl.get("osszes") or {}).get("db") == 4,
       f"összesített: {atl.get('osszes')}")
    atl_okt = get_json("/api/atlagok?diak=Sulyos&kezdo_datum=2026-10-01&zaro_datum=2026-10-31")
    ok(atl_okt.get("honapok") == ["2026-10"], f"októberi szűrés: {atl_okt.get('honapok')}")
    ho = atl.get("honap_osszes") or {}
    ok(ho.get("2026-09", {}).get("atlag") == 5.0 and ho.get("2026-09", {}).get("db") == 1,
       f"havi TELJES átlag szeptember: {ho.get('2026-09')}")
    ok(ho.get("2026-10", {}).get("atlag") == 4.33 and ho.get("2026-10", {}).get("db") == 3,
       f"havi TELJES átlag október (súlyozva): {ho.get('2026-10')}")
    ok((mat.get("honapok") or {}).get("2026-10", {}).get("jegyek") is not None,
       "a hónap jegyei is megvannak a válaszban")
    print("\n6) Dashboard összesítő (/api/dashboard, Kaneo #38)")
    dash = get_json("/api/dashboard?diak=Sulyos")
    d0 = (dash.get("diakok") or [{}])[0]
    ok(d0.get("atlag") == 4.5 and d0.get("jegy_db") == 4,
       f"diákonkénti teljes időszaki átlag: {d0.get('atlag')} / {d0.get('jegy_db')} jegy")
    ok(d0.get("teljes_egyenleg") == 1700,
       f"teljes egyenleg (2×500 + 200 + dicséret 500): {d0.get('teljes_egyenleg')}")
    ok(d0.get("kifizetve_osszeg") == 500, f"kifizetett összeg: {d0.get('kifizetve_osszeg')}")
    ok(d0.get("hatralevo") == 1200, f"kifizetetlen (1700-500): {d0.get('hatralevo')}")
    ok(dash.get("igazolatlan_ora") == 2, f"igazolatlan óra: {dash.get('igazolatlan_ora')}")
    dash_all = get_json("/api/dashboard")
    ok(len(dash_all.get("diakok") or []) == 3, "diák nélkül mind a 3 diák")
    nz_dash = get_json("/api/dashboard?diak=NincsZsebpenz")
    nz0 = (nz_dash.get("diakok") or [{}])[0]
    ok(nz0.get("rewards_enabled") is False and nz0.get("hatralevo") == 0,
       "kikapcsolt zsebpénznél 0 egyenleg")
    ok(nz0.get("atlag") == 4.67, f"az átlag kikapcsolt zsebpénznél is él: {nz0.get('atlag')}")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print("\n" + "=" * 60)
if _hibak:
    print(f"BUKOTT ({len(_hibak)} hiba)")
    sys.exit(1)
print("MINDEN ELLENŐRZÉS OK")
