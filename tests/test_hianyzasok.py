# -*- coding: utf-8 -*-
"""
Hiányzások / késések és igazolások modul.

- a scraper oldali mentés, tartalom-kulcs és új-hiányzás számítás,
- az API végpontok (havi szűrés, összesítő: igazolt/igazolatlan óra, késés),
- a push-üzenet bontása.

Külön folyamatban fut, hogy az app és a scraper importja ne zavarja a többi tesztet.
"""
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_hibak = []


def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)


work = Path(tempfile.mkdtemp(prefix="kreta_hianyzas_"))
data = work / "data"
data.mkdir()
(data / "config.json").write_text(
    json.dumps({"HEADLESS": True, "STUDENTS": [{"diak_nev": "Teszt Elek", "active": False}]},
               ensure_ascii=False),
    encoding="utf-8",
)

probe = work / "probe.py"
probe.write_text(
    """# -*- coding: utf-8 -*-
import json, sqlite3, sys
sys.path.insert(0, r'{root}')

import app as kreta
import kreta_playwright as k

k.init_db()

# --- séma ---
conn = sqlite3.connect(k.DB_FILE)
tables = {{r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}}
print("TABLES=" + json.dumps(sorted(tables)))
cols = [r[1] for r in conn.execute("PRAGMA table_info(hianyzasok)")]
print("COLS=" + json.dumps(cols))
conn.close()

# --- mentés + dedupe ---
rows = [
    {{"kreta_id": "1", "mulasztas_datum": "2026-10-05", "oraszam": 2, "perc": None,
      "tantargy": "Matematika", "tema": "Dolgozat", "mulasztas_tipus": "Hiányzás",
      "igazolt": 1, "igazolas_tipus": "Orvosi", "rogzites_datum": "2026-10-05"}},
    {{"kreta_id": "2", "mulasztas_datum": "2026-10-06", "oraszam": 1, "perc": None,
      "tantargy": "Magyar", "tema": "", "mulasztas_tipus": "Hiányzás",
      "igazolt": 0, "igazolas_tipus": "", "rogzites_datum": "2026-10-06"}},
    {{"kreta_id": "3", "mulasztas_datum": "2026-10-07", "oraszam": 0, "perc": 5,
      "tantargy": "Fizika", "tema": "", "mulasztas_tipus": "Késés",
      "igazolt": 0, "igazolas_tipus": "", "rogzites_datum": "2026-10-07"}},
    {{"kreta_id": "4", "mulasztas_datum": "2026-10-08", "oraszam": 3, "perc": None,
      "tantargy": "Történelem", "tema": "", "mulasztas_tipus": "Hiányzás",
      "igazolt": 0, "igazolas_tipus": "", "rogzites_datum": "2026-10-08"}},
    {{"kreta_id": "5", "mulasztas_datum": "2026-10-09", "oraszam": 2, "perc": None,
      "tantargy": "Német", "tema": "Verseny", "mulasztas_tipus": "Hiányzás",
      "igazolt": 0, "tanorai_celu": "Igen", "igazolas_tipus": "",
      "rogzites_datum": "2026-10-09"}},
    # ugyanaz az ID mégegyszer -> nem duplikálódhat
    {{"kreta_id": "4", "mulasztas_datum": "2026-10-08", "oraszam": 3, "perc": None,
      "tantargy": "Történelem", "tema": "", "mulasztas_tipus": "Hiányzás",
      "igazolt": 0, "igazolas_tipus": "", "rogzites_datum": "2026-10-08"}},
]
before = k.get_hianyzas_key_set("Teszt Elek")
k.save_hianyzasok_to_db("Teszt Elek", rows)
after = k.get_hianyzas_key_set("Teszt Elek")
print("BEFORE=" + str(len(before)))
print("AFTER=" + str(len(after)))
print("DIFF=" + json.dumps(k.diff_hianyzas_counts(before, rows), ensure_ascii=False))

# --- igazolások ---
ig = [
    {{"kreta_id": "10", "kezdete": "2026-10-05", "vege": "2026-10-06",
      "igazolas_tipus": "Orvosi igazolás", "megjegyzes": "Dr. Példa"}},
    {{"kreta_id": "11", "kezdete": "2026-09-01", "vege": "2026-09-02",
      "igazolas_tipus": "Szülői", "megjegyzes": ""}},
]
k.save_igazolasok_to_db("Teszt Elek", ig)

# --- API ---
c = kreta.app.test_client()
r = c.get("/api/hianyzasok?honap=2026-10")
res = r.get_json()
print("API_STATUS=" + str(r.status_code))
print("API_ROWS=" + str(len(res["rows"])))
print("API_O=" + json.dumps(res["osszesito"], ensure_ascii=False))
r2 = c.get("/api/hianyzasok")
print("API_ALL_ROWS=" + str(len(r2.get_json()["rows"])))
r3 = c.get("/api/igazolasok?honap=2026-10")
print("IG_ROWS=" + str(len(r3.get_json())))
r4 = c.get("/api/igazolasok?honap=2026-09")
print("IG_SEPT=" + str(len(r4.get_json())))
r5 = c.get("/api/hianyzasok?honap=2026-11")
print("NOV_ROWS=" + str(len(r5.get_json()["rows"])))

# --- push szöveg ---
lines = kreta.format_new_events({{"Teszt Elek": {{"Értékelés": 1}}}}, {{}},
                                {{"Teszt Elek": {{"db": 2, "igazolatlan_ora": 3}}}})
print("PUSH=" + json.dumps(lines, ensure_ascii=False))
""".format(root=str(ROOT)),
    encoding="utf-8",
)

env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(data),
    "KRETA_CONFIG_FILE": str(data / "config.json"),
    "PYTHONIOENCODING": "utf-8",
})
for key in ("KRETA_DB_FILE", "KRETA_LOG_FILE", "KRETA_SCHEDULER_STATE_FILE",
            "KRETA_CSATOLMANYOK_DIR", "NTFY_TOPIC"):
    env.pop(key, None)

r = subprocess.run([sys.executable, str(probe)], cwd=str(work), env=env,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
vals = {}
for line in r.stdout.splitlines():
    if "=" in line:
        k_, v = line.split("=", 1)
        vals[k_] = v
if not vals:
    print(r.stdout[-800:])
    print(r.stderr[-1200:])

print("1) Táblák és oszlopok")
tables = json.loads(vals.get("TABLES", "[]"))
cols = json.loads(vals.get("COLS", "[]"))
ok("hianyzasok" in tables, "a 'hianyzasok' tábla létrejött")
ok("igazolasok" in tables, "az 'igazolasok' tábla létrejött")
for col in ("mulasztas_datum", "oraszam", "perc", "tantargy", "mulasztas_tipus",
            "igazolt", "igazolas_tipus", "rogzites_datum"):
    ok(col in cols, f"a 'hianyzasok' táblában van '{col}' oszlop")

print("\n2) Mentés és új-hiányzás számítás")
ok(vals.get("BEFORE") == "0", f"kezdetben nincs hiányzás: {vals.get('BEFORE')}")
ok(vals.get("AFTER") == "5", f"a duplikált sor nem került be (5 sor): {vals.get('AFTER')}")
diff = json.loads(vals.get("DIFF", "{}"))
ok(diff.get("db") == 5, f"5 új hiányzás: {diff.get('db')}")
ok(diff.get("igazolatlan_ora") == 4, f"4 új igazolatlan óra (késés és tanórai célú nélkül): {diff.get('igazolatlan_ora')}")

print("\n3) API és havi összesítő")
ok(vals.get("API_STATUS") == "200", f"a /api/hianyzasok válasza: {vals.get('API_STATUS')}")
ok(vals.get("API_ROWS") == "5", f"októberi sorok: {vals.get('API_ROWS')}")
o = json.loads(vals.get("API_O", "{}"))
ok(o.get("hianyzas_db") == 3, f"3 hiányzás-sor (késés és tanórai célú külön): {o.get('hianyzas_db')}")
ok(o.get("igazolt_ora") == 2, f"2 igazolt óra: {o.get('igazolt_ora')}")
ok(o.get("igazolatlan_ora") == 4, f"4 igazolatlan óra: {o.get('igazolatlan_ora')}")
ok(o.get("tanorai_celu_db") == 1, f"1 tanórai célú mulasztás: {o.get('tanorai_celu_db')}")
ok(o.get("tanorai_celu_ora") == 2, f"2 tanórai célú óra: {o.get('tanorai_celu_ora')}")
ok(o.get("keses_db") == 1, f"1 késés: {o.get('keses_db')}")
ok(o.get("keses_perc") == 5, f"5 perc késés: {o.get('keses_perc')}")
ok(vals.get("API_ALL_ROWS") == "5", f"szűrés nélkül is 5 sor: {vals.get('API_ALL_ROWS')}")
ok(vals.get("NOV_ROWS") == "0", f"novemberben nincs sor: {vals.get('NOV_ROWS')}")
ok(vals.get("IG_ROWS") == "1", f"októberi igazolás: {vals.get('IG_ROWS')}")
ok(vals.get("IG_SEPT") == "1", f"szeptemberi igazolás: {vals.get('IG_SEPT')}")

print("\n4) Push szöveg")
push = json.loads(vals.get("PUSH", "[]"))
ok(len(push) == 1 and "2 hiányzás" in push[0], f"a push tartalmazza az új hiányzást: {push}")
ok(len(push) == 1 and "3 igazolatlan óra" in push[0], f"a push tartalmazza az igazolatlan órát: {push}")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
