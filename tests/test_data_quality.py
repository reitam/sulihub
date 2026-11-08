# -*- coding: utf-8 -*-
"""Adatminőség- és integritás-riport (Kaneo #89) — csak olvas."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import data_quality_report as dq  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="kreta_quality_"))
db = work / "kreta_adatok.db"
config = {"STUDENTS": [{"diak_nev": "Quality", "enable_rewards": True, "active": False}]}
(work / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": str(work / "csatolmanyok"),
    "KRETA_SCHEDULER_STATE_FILE": str(work / "scheduler_state.json"),
    "KRETA_VERSION_FILE": str(work / "version.txt"),
    "PYTHONIOENCODING": "utf-8",
})
os.environ.update({k: v for k, v in env.items() if k.startswith("KRETA")})

subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

sys.path.insert(0, str(ROOT))
import app as _kreta  # noqa: E402,F401  — létrehozza a saját táblákat (kommentek, FTS)

conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " suly_szazalek, bej_datum, hatarido, tema, cim, tartalom, kesz, tanev)"
    " VALUES ('Quality','Értékelés','Matematika','Jeles(5)',5,100,'2026. 10. 10.',"
    " '','Téma','','',0,'2026/2027')")
conn.execute(
    "INSERT INTO uzenetek (diak_nev, felado, targy, idopont, szoveg)"
    " VALUES ('Quality','Tanár','Tárgy','2026. 10. 10.','Szöveg')")
conn.commit()
conn.close()

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


print("1) Tiszta adatbázis")
ok_all, riport = dq.check(db)
ok(ok_all and not riport["hibak"] and not riport["figyelmeztetesek"],
   f"nincs hiba/figyelmeztetés: {riport['hibak']} {riport['figyelmeztetesek']}")
ok(riport["integritas"] == "ok", "integrity_check ok")
ok(riport["tablak"].get("esemenyek") == 1 and riport["tablak"].get("uzenetek") == 1,
   f"tábla-sorszámok: {riport['tablak']}")

print("\n2) Szimulált hibák")
conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " suly_szazalek, bej_datum, hatarido, tema, cim, tartalom, kesz, tanev)"
    " VALUES ('Quality','Értékelés','Matematika','Jeles(5)',5,100,'2026. 10. 10.',"
    " '','Téma','','',0,'2026/2027')")   # duplikátum
conn.execute(
    "INSERT INTO uzenetek (diak_nev, felado, targy, idopont, szoveg, csatolmany_nev,"
    " csatolmany_utvonal) VALUES ('Quality','Tanár','Melléklet','2026. 10. 11.',"
    " 'Szöveg','hianyzo.pdf','data/csatolmanyok/hianyzo.pdf')")
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " suly_szazalek, bej_datum, hatarido, tema, cim, tartalom, kesz, tanev)"
    " VALUES ('','','','',0,0,'','','','','',0,'')")   # üres kötelező mezők
conn.execute(
    "INSERT INTO kommentek (cel_tipus, cel_kulcs, diak_nev, szoveg, letrehozva)"
    " VALUES ('esemeny','e:nincsilyen','Quality','Árva','2026-11-08T10:00:00')")
conn.commit()
conn.close()
ok_all, riport = dq.check(db)
ok(not ok_all, "hibák esetén nem OK")
ok(riport.get("duplikalt_esemeny") == 1, f"1 duplikált esemény: {riport.get('duplikalt_esemeny')}")
ok(riport.get("hianyzo_csatolmany") == 1,
   f"1 hiányzó csatolmány: {riport.get('hianyzo_csatolmany')}")
ok(any("hiányzó diák/típus" in h for h in riport["hibak"]), "üres kötelező mező hiba")
ok(riport.get("arva_komment") == 1, f"1 árva megjegyzés: {riport.get('arva_komment')}")

print("\n3) CLI (--json) és ntfy nélkül")
saved = sys.stdout
sys.stdout = open(os.devnull, "w", encoding="utf-8")
try:
    rc = dq.main(["--db", str(db), "--json"])
finally:
    sys.stdout.close()
    sys.stdout = saved
ok(rc == 1, f"hibás DB -> kilépés 1 ({rc})")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
