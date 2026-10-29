# -*- coding: utf-8 -*-
"""
Új események kimutatása (a szinkron előtti és utáni állapot különbsége).

A scraper `get_event_key_set()` / `diff_event_counts()` logikáját valódi SQLite
adatbázison ellenőrzi — külön folyamatban, hogy a modul importja ne zavarja a többi tesztet.
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


work = Path(tempfile.mkdtemp(prefix="kreta_new_"))
data = work / "data"
data.mkdir()
(data / "config.json").write_text(
    json.dumps({"HEADLESS": True, "STUDENTS": [{"diak_nev": "Teszt", "active": False}]}, ensure_ascii=False),
    encoding="utf-8",
)

probe = work / "probe.py"
probe.write_text(
    """# -*- coding: utf-8 -*-
import json, sqlite3, sys
sys.path.insert(0, r'{root}')
import kreta_playwright as k

k.init_db()

def ins(tipus, tantargy, ertek=""):
    conn = sqlite3.connect(k.DB_FILE)
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
        ("Teszt", tipus, tantargy, ertek, 0, "2026. 10. 20.", "", "Tanar", "", "", "", "", ""),
    )
    conn.commit(); conn.close()

ins("Értékelés", "Matematika", "5")
ins("Házi feladat", "Magyar")
before = k.get_event_key_set("Teszt")

# két új esemény + egy meglévő törlése
ins("Értékelés", "Fizika", "4")
ins("Bejelentett számonkérés", "Történelem")
conn = sqlite3.connect(k.DB_FILE)
conn.execute("DELETE FROM esemenyek WHERE diak_nev='Teszt' AND tantargy='Magyar'")
conn.commit(); conn.close()

after = k.get_event_key_set("Teszt")
print("DIFF=" + json.dumps(k.diff_event_counts(before, after), ensure_ascii=False))
print("BEFORE=" + str(len(before)))
print("AFTER=" + str(len(after)))
""".replace("{root}", str(ROOT)),
    encoding="utf-8",
)

env = os.environ.copy()
env["KRETA_DATA_DIR"] = str(data)
env["PYTHONIOENCODING"] = "utf-8"
for key in ("KRETA_CONFIG_FILE", "KRETA_DB_FILE", "KRETA_LOG_FILE"):
    env.pop(key, None)

r = subprocess.run([sys.executable, str(probe)], cwd=str(work), env=env,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
out = r.stdout
if r.returncode != 0 and not out:
    print(r.stderr[-800:])

vals = {}
for line in out.splitlines():
    if "=" in line:
        k_, v = line.split("=", 1)
        vals[k_] = v

print("1) A különbség számítása")
ok(vals.get("BEFORE") == "2", f"frissítés előtt 2 esemény: {vals.get('BEFORE')}")
ok(vals.get("AFTER") == "3", f"frissítés után 3 esemény: {vals.get('AFTER')}")
diff = json.loads(vals.get("DIFF", "{}"))
ok(diff.get("Értékelés") == 1, f"1 új jegy: {diff.get('Értékelés')}")
ok(diff.get("Bejelentett számonkérés") == 1, f"1 új számonkérés: {diff.get('Bejelentett számonkérés')}")
ok("Házi feladat" not in diff, "a törölt házi nem számít újnak")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
