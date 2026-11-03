# -*- coding: utf-8 -*-
"""Tanév-séma migráció tesztje (Kaneo #40, 1. fázis).

Régi (tanév-oszlop nélküli) adatbázison ellenőrzi:
- az oszlopok létrejönnek (5 tábla + sync_runs), az `orarend` NEM kap tanévet;
- a backfill helyes tanévet ír (két tanév + ismeretlen dátum);
- az ID-k nem változnak (csak UPDATE történik);
- a második futás idempotens.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_hibak = []


def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)


work = Path(tempfile.mkdtemp(prefix="kreta_tanev_migr_"))
db = work / "adatok.db"
env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "PYTHONIOENCODING": "utf-8",
})
(work / "config.json").write_text('{"STUDENTS": []}', encoding="utf-8")


def init_db():
    res = subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"],
                         cwd=str(ROOT), env=env, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=120)
    if res.returncode != 0:
        print(res.stdout[-2000:])
        print(res.stderr[-2000:])
    return res


print("\n1) Kiinduló (új) séma, majd a tanév-oszlopok eltávolítása = régi DB")
init_db()
conn = sqlite3.connect(db)
TABLES = ("esemenyek", "uzenetek", "hianyzasok", "igazolasok", "kifizetesek", "sync_runs")
for table in TABLES:
    conn.execute(f"DROP INDEX IF EXISTS idx_{table}_tanev")
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    for column in ("tanev", "tanev_forras"):
        if column in cols:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
conn.commit()
cols_esemenyek = [r[1] for r in conn.execute("PRAGMA table_info(esemenyek)")]
ok("tanev" not in cols_esemenyek, "a régi séma szimulálva: nincs tanev oszlop")

print("\n2) Két tanév adatai + ismeretlen dátum")
conn.executemany(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
    [
        ("Teszt", "Értékelés", "Matematika", "Jeles(5)", 5, "2026. 03. 10.", "",
         "Tanár", "", "Írásbeli", "Téma", "", ""),
        ("Teszt", "Értékelés", "Fizika", "Jó(4)", 4, "2026. 10. 05.", "",
         "Tanár", "", "Írásbeli", "Téma", "", ""),
        ("Teszt", "Házi feladat", "Angol", "", 0, "2026. 08. 30.", "2026. 09. 05.",
         "Tanár", "", "", "", "", ""),
        ("Teszt", "Értékelés", "Ismeretlen", "Jeles(5)", 5, "hibás dátum", "",
         "Tanár", "", "", "", "", ""),
    ])
conn.executemany(
    "INSERT INTO hianyzasok (diak_nev, mulasztas_datum, ora_sorszam, perc, tantargy,"
    " tema, tanar, mulasztas_tipus, igazolt, tanorai_celu, igazolas_tipus,"
    " rogzites_datum, kreta_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
    [("Teszt", "2026-05-12", 3, None, "Matematika", "", "", "Hiányzás", 1, "Nem", "",
      "2026-05-12", "h1"),
     ("Teszt", "2026-10-07", 2, None, "Fizika", "", "", "Hiányzás", 0, "Nem", "",
      "2026-10-07", "h2")])
conn.execute(
    "INSERT INTO igazolasok (diak_nev, kreta_id, kezdete, vege, igazolas_tipus, megjegyzes)"
    " VALUES (?,?,?,?,?,?)",
    ("Teszt", "i1", "2026-06-10", "2026-06-12", "Orvosi", ""))
conn.execute(
    "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg)"
    " VALUES (?,?,?,?,?,?)",
    ("Teszt", "u1", "Iskola", "Üzenet", "2026. 09. 22. 1:33", "Szöveg"))
conn.execute("""
    CREATE TABLE IF NOT EXISTS kifizetesek (
        id INTEGER PRIMARY KEY AUTOINCREMENT, diak_nev TEXT NOT NULL,
        kezdo_datum TEXT NOT NULL, zaro_datum TEXT NOT NULL,
        kifizetve INTEGER DEFAULT 0, osszeg INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(diak_nev, kezdo_datum, zaro_datum))
""")
conn.execute(
    "INSERT INTO kifizetesek (diak_nev, kezdo_datum, zaro_datum, kifizetve, osszeg)"
    " VALUES (?,?,?,?,?)", ("Teszt", "2026-10-01", "2026-10-31", 1, 500))
conn.execute("""
    CREATE TABLE IF NOT EXISTS sync_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT,
        started_at TEXT, status TEXT)
""")
conn.execute(
    "INSERT INTO sync_runs (trigger, started_at, status) VALUES (?,?,?)",
    ("manual", "2026-11-02 10:00:00", "done"))
conn.commit()
ids_before = {t: [r[0] for r in conn.execute(f"SELECT id FROM {t} ORDER BY id")]
              for t in TABLES}
counts_before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
conn.close()

print("\n3) Migráció (init-db) — oszlopok és backfill")
res = init_db()
ok(res.returncode == 0, f"a migráció lefutott (exit={res.returncode})")
ok("tanév-oszlopok" in res.stdout or "tanev" in res.stdout, "a napló jelzi a sémafrissítést")

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
for table in TABLES:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    ok("tanev" in cols, f"{table}: van tanev oszlop")
cols_orarend = [r[1] for r in conn.execute("PRAGMA table_info(orarend)")]
ok("tanev" not in cols_orarend, "az orarend szándékosan NEM kap tanévet")

rows = {r["tantargy"]: r for r in conn.execute("SELECT * FROM esemenyek")}
ok(rows["Matematika"]["tanev"] == "2025/2026", "2026. 03. -> 2025/2026")
ok(rows["Fizika"]["tanev"] == "2026/2027", "2026. 10. -> 2026/2027")
ok(rows["Angol"]["tanev"] == "2026/2027", "házi: a határidő dönt (2026. 09. 05.)")
ok(rows["Ismeretlen"]["tanev"] == "", "hibás dátum -> üres (ismeretlen), nem NULL")
ok(rows["Fizika"]["tanev_forras"] == "migracio", "a backfill forrása: migracio")

hiany = {r["mulasztas_datum"]: r["tanev"] for r in conn.execute("SELECT * FROM hianyzasok")}
ok(hiany.get("2026-05-12") == "2025/2026" and hiany.get("2026-10-07") == "2026/2027",
   f"hiányzások tanéve: {hiany}")
ok(conn.execute("SELECT tanev FROM igazolasok").fetchone()[0] == "2025/2026",
   "igazolás: kezdete szerint")
ok(conn.execute("SELECT tanev FROM uzenetek").fetchone()[0] == "2026/2027",
   "üzenet: időpont szerint")
ok(conn.execute("SELECT tanev FROM kifizetesek").fetchone()[0] == "2026/2027",
   "kifizetés: kezdő dátum szerint")
ok(conn.execute("SELECT tanev FROM sync_runs").fetchone()[0] is None,
   "sync_runs.tanev egyelőre NULL (a futás tölti, 6. fázis)")

print("\n4) ID-stabilitás és darabszám")
for table in TABLES:
    ids_after = [r[0] for r in conn.execute(f"SELECT id FROM {table} ORDER BY id")]
    counts_after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    ok(ids_after == ids_before[table] and counts_after == counts_before[table],
       f"{table}: ID-k és darabszám változatlan ({len(ids_after)} sor)")

snapshot = {}
for table in ("esemenyek", "hianyzasok", "igazolasok", "uzenetek", "kifizetesek"):
    snapshot[table] = [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
conn.close()

print("\n5) Idempotencia: a második migráció nem módosít")
res = init_db()
ok(res.returncode == 0, "a második futás is lefut")
conn = sqlite3.connect(db)
for table in ("esemenyek", "hianyzasok", "igazolasok", "uzenetek", "kifizetesek"):
    now = [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
    ok(now == snapshot[table], f"{table}: változatlan a második futás után")
conn.close()

print("\n6) Többkörös backfill (batch=100) + unsynced_rows")
sys.path.insert(0, str(ROOT))
import kreta_tanev  # noqa: E402
conn = sqlite3.connect(db)
for i in range(450):
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, bej_datum)"
        " VALUES (?,?,?,?,?)",
        ("Teszt", "Értékelés", f"Bulk-{i}", "Jeles(5)", "2026. 10. 01."))
conn.commit()
ok(kreta_tanev.unsynced_rows(conn) == 450,
   f"450 sor vár kitöltésre: {kreta_tanev.unsynced_rows(conn)}")
kreta_tanev.backfill_tanev(conn, batch=100, log_fn=None)
ok(kreta_tanev.unsynced_rows(conn) == 0,
   f"a többkörös backfill mindent kitöltött: {kreta_tanev.unsynced_rows(conn)}")
db_450 = conn.execute("SELECT COUNT(*) FROM esemenyek WHERE tantargy LIKE 'Bulk-%'"
                      " AND tanev = '2026/2027'").fetchone()[0]
ok(db_450 == 450, f"mind a 450 sor a 2026/2027 tanévben: {db_450}")
conn.close()

print("\n" + "=" * 60)
if _hibak:
    print(f"BUKOTT ({len(_hibak)} hiba)")
    sys.exit(1)
print("MINDEN ELLENŐRZÉS OK")
