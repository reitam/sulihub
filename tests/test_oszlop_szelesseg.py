# -*- coding: utf-8 -*-
"""Oszlopszélesség-állítás regressziós teszt (valódi böngésző, 1280 px).

Ellenőrzi a #35 hibát:
  - az átméretezés NEM változtathatja meg a táblázat sorrendjét,
  - a hiányzások/igazolások táblán is legyen fogantyú.
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


work = Path(tempfile.mkdtemp(prefix="kreta_oszlop_"))
db = work / "kreta_adatok.db"
(work / "config.json").write_text(json.dumps({
    "SCHEDULER": {"ENABLED": False},
    "STUDENTS": [{"diak_nev": "Teszt Elek", "active": False}],
}, ensure_ascii=False), encoding="utf-8")

env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_HOST": "127.0.0.1",
    "KRETA_SERVER": "flask",
    "KRETA_DEBUG": "0",
    "PYTHONIOENCODING": "utf-8",
})
env.pop("KRETA_CSATOLMANYOK_DIR", None)

subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

conn = sqlite3.connect(db)
# A tantárgy szerinti rendezés MÁS sorrendet adna, mint a dátum szerinti (alap),
# így kiderül, ha az átméretezés rendezést indít.
for i, (tantargy, datum) in enumerate([
        ("Matematika", "2026. 10. 01."), ("Biológia", "2026. 10. 02."),
        ("Angol nyelv", "2026. 10. 03."), ("Történelem", "2026. 10. 04."),
        ("Fizika", "2026. 10. 05.")]):
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
        ("Teszt Elek", "Értékelés", tantargy, "Jeles(5)", 5, 100, datum, "",
         "Tanár", "Évközi jegy", "Írásbeli", "Téma", "", ""))
for i in range(5):
    conn.execute(
        "INSERT INTO hianyzasok (diak_nev, mulasztas_datum, ora_sorszam, perc, tantargy,"
        " tema, tanar, mulasztas_tipus, igazolt, tanorai_celu, igazolas_tipus,"
        " rogzites_datum, kreta_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("Teszt Elek", f"2026-10-0{i + 1}", i + 1, None, "Matematika", "Téma", "Tanár",
         "Hiányzás", 1, "Nem", "", "2026-10-01", f"k{i}"))
for i in range(5):
    conn.execute(
        "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg)"
        " VALUES (?,?,?,?,?,?)",
        ("Teszt Elek", str(i), "Iskola", f"Üzenet {i}", "2026. 10. 20.", "Szöveg"))
conn.commit()
conn.close()

port = free_port()
env["KRETA_PORT"] = str(port)
proc = subprocess.Popen([sys.executable, "app.py"], cwd=str(ROOT), env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = f"http://127.0.0.1:{port}"

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

    from playwright.sync_api import sync_playwright

    def drag_resizer(page, table_sel, col_index, delta=70):
        """A megadott oszlop fogantyúját húzza jobbra; visszaadja a szélesség-változást."""
        th = page.query_selector(f"{table_sel} thead th:nth-child({col_index + 1})")
        box = th.bounding_box()
        res = page.query_selector(f"{table_sel} thead th:nth-child({col_index + 1}) .resizer")
        rbox = res.bounding_box()
        start_w = box["width"]
        x = rbox["x"] + rbox["width"] / 2
        y = rbox["y"] + rbox["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        for step in range(1, 8):
            page.mouse.move(x + delta * step / 7, y)
        page.mouse.up()
        page.wait_for_timeout(250)
        return box["width"], page.query_selector(
            f"{table_sel} thead th:nth-child({col_index + 1})").bounding_box()["width"]

    def row_texts(page, table_sel):
        return page.eval_on_selector_all(
            f"{table_sel} tbody tr",
            "rows => rows.map(r => r.innerText.replace(/\\s+/g, ' ').trim())")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base, wait_until="networkidle")
        page.wait_for_selector("#esemenyekTable tbody tr", timeout=15000)

        print("\n1) Iskolai események: átméretezés nem rendez át")
        before = row_texts(page, "#esemenyekTable")
        order_before = page.evaluate("() => $('#esemenyekTable').DataTable().order()")
        w0, w1 = drag_resizer(page, "#esemenyekTable", 2)   # Tantárgy oszlop
        after = row_texts(page, "#esemenyekTable")
        order_after = page.evaluate("() => $('#esemenyekTable').DataTable().order()")
        ok(len(before) == 5, f"5 sor a táblában: {len(before)}")
        ok(w1 > w0 + 20, f"az oszlop szélesebb lett ({w0:.0f} -> {w1:.0f} px)")
        ok(before == after, "a sorok sorrendje nem változott")
        ok(order_before == order_after,
           f"a DataTables rendezése nem változott: {order_before} -> {order_after}")

        print("\n1b) A fogantyúra kattintás sem rendez (nem húzás)")
        w_before = page.query_selector(
            "#esemenyekTable thead th:nth-child(2)").bounding_box()["width"]
        rbox = page.query_selector(
            "#esemenyekTable thead th:nth-child(2) .resizer").bounding_box()
        page.mouse.move(rbox["x"] + rbox["width"] / 2, rbox["y"] + rbox["height"] / 2)
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(300)
        order_click = page.evaluate("() => $('#esemenyekTable').DataTable().order()")
        ok(order_click == order_before,
           f"kattintás után is marad a rendezés: {order_click}")
        ok(row_texts(page, "#esemenyekTable") == before, "kattintás után is marad a sorrend")

        print("\n2) Hiányzások: van oszlop-fogantyú")
        page.click("#hianyzasok-tab")
        page.wait_for_timeout(700)
        page.wait_for_selector("#hianyzasokTable tbody tr", timeout=15000)
        gy = page.eval_on_selector_all("#hianyzasokTable thead th .resizer", "els => els.length")
        ok(gy >= 5, f"a hiányzások táblán {gy} fogantyú van")
        hb = row_texts(page, "#hianyzasokTable")
        drag_resizer(page, "#hianyzasokTable", 3)
        ha = row_texts(page, "#hianyzasokTable")
        ok(hb == ha, "a hiányzások sorrendje sem változik átméretezéskor")

        print("\n3) Beérkezett üzenetek: átméretezés nem rendez át")
        page.click("#uzenetek-tab")
        page.wait_for_timeout(700)
        page.wait_for_selector("#uzenetekTable tbody tr", timeout=15000)
        ub = row_texts(page, "#uzenetekTable")
        uorder_b = page.evaluate("() => $('#uzenetekTable').DataTable().order()")
        drag_resizer(page, "#uzenetekTable", 2)
        ua = row_texts(page, "#uzenetekTable")
        uorder_a = page.evaluate("() => $('#uzenetekTable').DataTable().order()")
        ok(ub == ua, "az üzenetek sorrendje nem változott")
        ok(uorder_b == uorder_a, f"az üzenetek rendezése nem változott: {uorder_b} -> {uorder_a}")

        browser.close()
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
