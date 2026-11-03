# -*- coding: utf-8 -*-
"""Tanév-szűrés az API-n (Kaneo #40 4. fázis / #45).

Két tanév adatán ellenőrzi, hogy a `?tanev=` paraméter szétválasztja az adatokat,
a `/api/tanevek` listázza őket, és a dashboard zsebpénze nem vonja le a korábbi
tanév kifizetését.
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


work = Path(tempfile.mkdtemp(prefix="kreta_tanev_api_"))
db = work / "kreta_adatok.db"
(work / "config.json").write_text(json.dumps({
    "ENABLE_REWARDS": True,
    "REWARDS": {"jegy_5": 500, "jegy_4": 200, "jegy_3": 0, "jegy_2": -200, "jegy_1": -500,
                "dicseret": 500, "megrovas": -500, "lecke_hiany": -300,
                "felszereles_hiany": -300},
    "SCHEDULER": {"ENABLED": False},
    "STUDENTS": [{"diak_nev": "Teszt Elek", "enable_rewards": True, "active": False}],
}, ensure_ascii=False), encoding="utf-8")

env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(work), "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"), "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_HOST": "127.0.0.1", "KRETA_SERVER": "flask", "KRETA_DEBUG": "0",
    "PYTHONIOENCODING": "utf-8",
    "KRETA_TODAY": "2026-11-03",
})
env.pop("KRETA_CSATOLMANYOK_DIR", None)
subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

conn = sqlite3.connect(db)
SOROK = [
    # diák, típus, tantárgy, érték, szám, súly, bej_datum, tanev
    ("Teszt Elek", "Értékelés", "Matematika", "Jeles(5)", 5, 100, "2026. 03. 10.", "2025/2026"),
    ("Teszt Elek", "Értékelés", "Matematika", "Közepes(3)", 3, 100, "2026. 10. 05.", "2026/2027"),
    ("Teszt Elek", "Értékelés", "Fizika", "Jeles(5)", 5, 100, "2026. 10. 06.", "2026/2027"),
]
for diak, tipus, tantargy, ertek, szam, suly, datum, tanev in SOROK:
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
        " tanev, tanev_forras) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
        (diak, tipus, tantargy, ertek, szam, suly, datum, "", "Tanár", "Évközi jegy",
         "Írásbeli", "Téma", "", "", tanev, "szamitott"))
conn.execute("""
    CREATE TABLE IF NOT EXISTS kifizetesek (
        id INTEGER PRIMARY KEY AUTOINCREMENT, diak_nev TEXT NOT NULL,
        kezdo_datum TEXT NOT NULL, zaro_datum TEXT NOT NULL,
        kifizetve INTEGER DEFAULT 0, osszeg INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        tanev TEXT, tanev_forras TEXT,
        UNIQUE(diak_nev, kezdo_datum, zaro_datum))
""")
for datum, tanev, osszeg in (("2026-02-01", "2025/2026", 500), ("2026-10-01", "2026/2027", 200)):
    conn.execute(
        "INSERT INTO kifizetesek (diak_nev, kezdo_datum, zaro_datum, kifizetve, osszeg, tanev)"
        " VALUES (?,?,?,?,?,?)", ("Teszt Elek", datum, datum, 1, osszeg, tanev))
conn.commit()
conn.close()

port = free_port()
env["KRETA_PORT"] = str(port)
proc = subprocess.Popen([sys.executable, "app.py"], cwd=str(ROOT), env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = f"http://127.0.0.1:{port}"


def get(path):
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

    print("\n1) /api/tanevek")
    tanevek = get("/api/tanevek")
    ok(tanevek.get("tanevek") == ["2025/2026", "2026/2027"],
       f"két tanév listázva: {tanevek.get('tanevek')}")
    ok(tanevek.get("aktualis") == "2026/2027", f"aktuális (KRETA_TODAY): {tanevek.get('aktualis')}")
    ok(tanevek.get("hatarok", {}).get("2026/2027", {}).get("kezdo") == "2026-09-01",
       "a tanév-határok is megvannak")

    print("\n2) /api/esemenyek?tanev=")
    ok(len(get("/api/esemenyek")) == 3, "tanev nélkül minden sor (visszafelé kompatibilis)")
    ok(len(get("/api/esemenyek?tanev=2026/2027")) == 2, "2026/2027: 2 sor")
    ok(len(get("/api/esemenyek?tanev=2025/2026")) == 1, "2025/2026: 1 sor")

    print("\n3) /api/atlagok?tanev=")
    uj = get("/api/atlagok?diak=Teszt%20Elek&tanev=2026/2027")
    ok(uj.get("osszes", {}).get("atlag") == 4.0 and uj.get("osszes", {}).get("db") == 2,
       f"2026/2027 átlag (3,5): {uj.get('osszes')}")
    ok(uj.get("tanev") == "2026/2027", "a válasz jelzi a tanévet")
    regi = get("/api/atlagok?diak=Teszt%20Elek&tanev=2025/2026")
    ok(regi.get("osszes", {}).get("atlag") == 5.0 and regi.get("osszes", {}).get("db") == 1,
       f"2025/2026 átlag (5): {regi.get('osszes')}")

    print("\n4) /api/statisztika?tanev=")
    st = get("/api/statisztika?diak=Teszt%20Elek&tanev=2026/2027")
    ok(st.get("jegy_total_count") == 2 and st.get("vegosszeg") == 500,
       f"2026/2027: 2 jegy (3-as 0 Ft + 5-ös 500 Ft): {st.get('vegosszeg')}")

    print("\n5) /api/dashboard?tanev= — a korábbi tanév kifizetése nem vonódik le")
    d = get("/api/dashboard?tanev=2026/2027")
    d0 = (d.get("diakok") or [{}])[0]
    ok(d0.get("teljes_egyenleg") == 500,
       f"teljes egyenleg (3-as 0 + 5-ös 500): {d0.get('teljes_egyenleg')}")
    ok(d0.get("kifizetve_osszeg") == 200, f"csak a 2026/2027 kifizetés: {d0.get('kifizetve_osszeg')}")
    ok(d0.get("hatralevo") == 300, f"hátralévő 500-200: {d0.get('hatralevo')}")

    print("\n6) /api/hianyzasok?tanev= (üres, de nem hibázik)")
    h = get("/api/hianyzasok?tanev=2026/2027")
    ok(h.get("rows") == [] and "osszesito" in h, "üres lista + összesítő")

    print("\n7) POST /api/kifizetes: a tanév beíródik, a dashboard azonnal levonja")
    req = urllib.request.Request(
        base + "/api/kifizetes",
        data=json.dumps({"diak": "Teszt Elek", "kezdo_datum": "2026-10-01",
                         "zaro_datum": "2026-10-31", "kifizetve": True,
                         "osszeg": 300}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        ok(r.status == 200, f"a kifizetés mentése: HTTP {r.status}")
    conn2 = sqlite3.connect(db)
    uj_sor = conn2.execute(
        "SELECT tanev, tanev_forras FROM kifizetesek WHERE diak_nev='Teszt Elek'"
        " AND kezdo_datum='2026-10-01'").fetchone()
    regi_sor = conn2.execute(
        "SELECT tanev FROM kifizetesek WHERE diak_nev='Teszt Elek'"
        " AND kezdo_datum='2026-02-01'").fetchone()
    conn2.close()
    ok(uj_sor and uj_sor[0] == "2026/2027",
       f"a kifizetesek.tanev kitöltve: {uj_sor[0] if uj_sor else None}")
    ok(regi_sor and regi_sor[0] == "2025/2026", "a korábbi tanév kifizetése érintetlen")
    d2 = get("/api/dashboard?tanev=2026/2027")
    d2o = (d2.get("diakok") or [{}])[0]
    ok(d2o.get("kifizetve_osszeg") == 500 and d2o.get("hatralevo") == 0,
       f"a friss kifizetés azonnal levonódik: {d2o.get('kifizetve_osszeg')} / "
       f"{d2o.get('hatralevo')}")

    print("\n8) API élek: tanév-aliasok, igazolások, ismeretlen_db")
    ok(len(get("/api/esemenyek?tanev=current")) == 2,
       "tanev=current -> az aktuális tanév sorai")
    ok(len(get("/api/esemenyek?tanev=all")) == 3, "tanev=all -> minden sor")
    ok(len(get("/api/esemenyek?tanev=osszes")) == 3, "tanev=osszes -> minden sor")
    ok(len(get("/api/esemenyek?tanev=ALL")) == 3, "tanev=ALL -> minden sor")
    ok(get("/api/esemenyek?tanev=1999/2000") == [],
       "ismeretlen tanév -> üres lista (nem hiba)")
    ok(get("/api/igazolasok?tanev=2026/2027") == [], "igazolások tanév-szűrése (üres)")
    ok(get("/api/igazolasok?tanev=all") == [], "igazolások tanev=all")
    ok(get("/api/igazolasok?tanev=1999/2000") == [], "igazolások ismeretlen tanévre")

    # ismeretlen (üres) tanév: a /api/tanevek számolja, de nem listázza
    conn3 = sqlite3.connect(db)
    conn3.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
        " tanev, tanev_forras) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
        ("Teszt Elek", "Értékelés", "Kémia", "Jeles(5)", 5, 100, "2026. 10. 09.", "",
         "Tanár", "Évközi jegy", "Írásbeli", "Téma", "", "", "", "szamitott"))
    conn3.commit()
    conn3.close()
    tv = get("/api/tanevek")
    ok(tv.get("ismeretlen_db", 0) >= 1,
       f"ismeretlen (üres) tanévű sor számolva: {tv.get('ismeretlen_db')}")
    ok("" not in tv.get("tanevek", []), "az ismeretlen tanév nem kerül a listába")
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
