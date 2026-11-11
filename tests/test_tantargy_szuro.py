# -*- coding: utf-8 -*-
"""
Kaneo #127: a tantárgy-szűrő legyen kis/nagybetű-független.

A KRÉTA tantárgynevei nem egységesek („Angol nyelv" vs. „angol nyelv"), ezért a
szűrés, a statisztika-csoportosítás és a tantárgylista is a normalizált kulcsot
használja. Ellenőrizzük az eseménylistát, az Excel exportot, az átlagokat, a
jegy-kalkulátort és a főoldali választót is.
"""
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_tantargy_"))
db = work / "kreta_adatok.db"
(work / "config.json").write_text(json.dumps({"STUDENTS": []}), encoding="utf-8")

os.environ.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": str(work / "csat"),
    "KRETA_SCHEDULER_STATE_FILE": str(work / "scheduler_state.json"),
    "PYTHONIOENCODING": "utf-8",
})
sys.path.insert(0, str(ROOT))

subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=os.environ.copy(), capture_output=True, timeout=120)

import app  # noqa: E402
from views_common import legjobb_tantargy_nev, tantargy_kulcs  # noqa: E402

app.init_db_extensions()

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


DIAK = "Teszt Elek"


def jegy(tantargy, ertek, szam, bej, tanev="2026/2027", suly=100):
    return (DIAK, "Értékelés", tantargy, ertek, szam, bej, "", "Tanár", "", "", "", "",
            "", 0, suly, tanev)


conn = sqlite3.connect(db)
conn.executemany(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " suly_szazalek, tanev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    [
        jegy("Angol nyelv", "Jeles(5)", 5, "2026. 09. 15."),
        jegy("angol nyelv", "Jó(4)", 4, "2026. 10. 01."),
        jegy("ANGOL NYELV", "Közepes(3)", 3, "2026. 10. 20.", suly=0),
        jegy("Matematika", "Jeles(5)", 5, "2026. 09. 20."),
        jegy("Angol nyelv", "Jeles(5)", 5, "2025. 10. 10.", tanev="2025/2026"),
    ],
)
conn.commit()
conn.close()

print("1) Segédfüggvények")
ok(tantargy_kulcs("  Angol   nyelv ") == "angol nyelv", "szóköz + kisbetű normalizálás")
ok(tantargy_kulcs(None) == "", "None -> üres kulcs")
ok(legjobb_tantargy_nev({"Angol nyelv": 2, "angol nyelv": 1}) == "Angol nyelv",
   "a leggyakoribb írásmód nyer")
ok(legjobb_tantargy_nev({"angol nyelv": 1, "Angol nyelv": 1}) == "Angol nyelv",
   "holtversenynél a nagybetűs")

client = app.app.test_client()


def esemenyek(**params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    res = client.get("/api/esemenyek?" + query)
    return res.status_code, res.get_json()


print("\n2) Eseménylista szűrő (kis/nagybetű-független)")
for tantargy in ("Angol nyelv", "angol nyelv", "ANGOL NYELV", "  angol NYELV  "):
    status, rows = esemenyek(diak=DIAK, tipus="Értékelés", tantargy=tantargy,
                             tanev="2026/2027")
    ok(status == 200 and len(rows) == 3,
       f"{tantargy!r}: {len(rows) if isinstance(rows, list) else rows} sor (várt 3)")
status, rows = esemenyek(diak=DIAK, tantargy="angol nyelv")
ok(len(rows) == 4, f"tanév nélkül a korábbi tanév is benne: {len(rows)}")
status, rows = esemenyek(diak=DIAK, tantargy="Történelem")
ok(rows == [], "nem létező tantárgy -> üres")

print("\n3) Átlagok: egy tantárgy, összevont jegyekkel")
res = client.get("/api/atlagok?diak=" + DIAK + "&tanev=2026/2027")
data = res.get_json()
angol = [t for t in data.get("tantargyak", []) if "angol" in t["tantargy"].casefold()]
ok(len(angol) == 1, f"egy angol tantárgy a listában: {[t['tantargy'] for t in angol]}")
ok(angol and angol[0]["osszes"]["db"] == 3,
   f"mind a 3 írásmód összevonva: {angol[0]['osszes'] if angol else None}")
ok(angol and angol[0]["osszes"]["atlag"] == 4.5,
   f"a súlyozott átlag helyes (5,4,3@0%): {angol[0]['osszes']['atlag'] if angol else None}")

print("\n4) Jegy-kalkulátor")
for tantargy in ("Angol nyelv", "angol nyelv", "ANGOL NYELV"):
    res = client.get("/api/jegy_kalkulator?diak=" + DIAK + "&tantargy=" + tantargy
                     + "&tanev=2026/2027&cel=4.5")
    k = res.get_json()
    ok(res.status_code == 200 and k.get("jegy_db") == 3 and k.get("aktualis_atlag") == 4.5,
       f"{tantargy!r}: jegy_db={k.get('jegy_db')} átlag={k.get('aktualis_atlag')}")

print("\n5) Főoldali tantárgy-választó")
html = client.get("/").get_data(as_text=True)
import re
block = re.search(r'<select id="filterTantargy".*?</select>', html, re.S)
values = re.findall(r'<option value="([^"]*)"', block.group(0)) if block else []
angol_opts = [v for v in values if "angol" in v.casefold()]
ok(len(angol_opts) == 1, f"egy angol opció a választóban: {angol_opts}")
ok(angol_opts == ["Angol nyelv"], f"a leggyakoribb írásmóddal: {angol_opts}")

print("\n6) Excel export szűrő")
res = client.get("/api/esemenyek/export.xlsx?tantargy=angol%20nyelv&tanev=2026/2027")
ok(res.status_code == 200, f"export: {res.status_code}")
wb = openpyxl.load_workbook(io.BytesIO(res.data))
ws = wb.active
tantargyak = [ws.cell(row=r, column=3).value for r in range(2, ws.max_row + 1)]
ok(len(tantargyak) == 3, f"3 angol sor az exportban: {len(tantargyak)}")
ok(all("angol" in str(t).casefold() for t in tantargyak), f"sorok: {tantargyak}")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
