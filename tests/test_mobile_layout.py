# -*- coding: utf-8 -*-
"""
Mobil elrendezés regressziós teszt (Redmi 12/13/14 ~393 CSS px).

Valódi böngészőben (Playwright/Chromium) nyitja meg az appot, és minden fülön
ellenőrzi, hogy nincs vízszintes túlcsordulás, a fő elemek láthatók, és a
koppintható célok nem túl kicsik.
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import shutil
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


work = Path(tempfile.mkdtemp(prefix="kreta_mobil_"))
db = work / "kreta_adatok.db"

# minimális, de valósághű adatbázis (hogy a táblázatok feltöltődjenek)
conn = sqlite3.connect(db)
conn.executescript("""
CREATE TABLE esemenyek (
    id INTEGER PRIMARY KEY AUTOINCREMENT, diak_nev TEXT, esemeny_tipus TEXT,
    tantargy TEXT, ertek TEXT, szam_ertek INTEGER, bej_datum TEXT, hatarido TEXT,
    ertekelo TEXT, tipus TEXT, mod TEXT, tema TEXT, cim TEXT, tartalom TEXT,
    kesz INTEGER DEFAULT 0);
CREATE TABLE uzenetek (
    id INTEGER PRIMARY KEY AUTOINCREMENT, diak_nev TEXT, uzenet_id TEXT, felado TEXT,
    targy TEXT, idopont TEXT, szoveg TEXT, csatolmany_nev TEXT, csatolmany_utvonal TEXT);
CREATE TABLE orarend (
    id INTEGER PRIMARY KEY AUTOINCREMENT, diak_nev TEXT, kezdo_idopont TEXT,
    zaro_idopont TEXT, nap TEXT, tantargy TEXT, tanar TEXT, terem TEXT);
""")
tanarok = ["Kovács Anna", "Szabó Béla", "Tóth Gábor"]
for i in range(12):
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek, "
        "bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
        ("Teszt Elek", "Értékelés", "Matematika", "Jeles(5)", 5,
         f"2026. 10. {10+i:02d}.", "", tanarok[i % 3], "Írásbeli", "Dolgozat",
         "Témakör", "", "Részletes leírás szövege"),
    )
for i in range(8):
    conn.execute(
        "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg) VALUES (?,?,?,?,?,?)",
        ("Teszt Elek", str(i), "Iskola", f"Tájékoztató üzenet {i}", "2026. 10. 20.", "Szöveg"),
    )
conn.commit()
conn.close()

(work / "config.json").write_text(json.dumps({"SCHEDULER": {"ENABLED": True, "INTERVAL_MINUTES": 180}}), encoding="utf-8")

port = free_port()
env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_HOST": "127.0.0.1",
    "KRETA_PORT": str(port),
    "KRETA_SERVER": "flask",
    "KRETA_DEBUG": "0",
})
env.pop("KRETA_CSATOLMANYOK_DIR", None)

proc = subprocess.Popen([sys.executable, "app.py"], cwd=str(ROOT), env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    base = f"http://127.0.0.1:{port}"
    for _ in range(40):
        try:
            with urllib.request.urlopen(base + "/health", timeout=1) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.3)
    else:
        print("HIBA: az app nem indult el")
        sys.exit(1)

    import asyncio
    from playwright.async_api import async_playwright

    async def check():
        async with async_playwright() as p:
            b = await p.chromium.launch()
            ctx = await b.new_context(viewport={"width": 393, "height": 873}, device_scale_factor=2)
            page = await ctx.new_page()
            await page.goto(base, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(2500)

            # 1) nincs vízszintes túlcsordulás
            for tab in ("esemenyek", "hianyzasok", "orarend", "naptar", "uzenetek", "rewards", "logs"):
                await page.evaluate(
                    "(id) => bootstrap.Tab.getOrCreateInstance(document.getElementById(id)).show()", tab + "-tab")
                await page.wait_for_timeout(900)
                sw = await page.evaluate("document.documentElement.scrollWidth")
                ok(sw <= 393, f"'{tab}' fül: nincs vízszintes túlcsordulás ({sw} px)")

            # 2) a fő elemek láthatók és elférnek
            await page.evaluate("() => bootstrap.Tab.getOrCreateInstance(document.getElementById('esemenyek-tab')).show()")
            await page.wait_for_timeout(500)
            for sel in ("#btnSync", "#mainTab", "#esemenyekTable"):
                box = await page.evaluate("""(s) => { const e = document.querySelector(s); if (!e) return null;
                    const r = e.getBoundingClientRect(); return {w: r.width, right: r.right}; }""", sel)
                ok(box and box["w"] > 0 and box["right"] <= 394, f"{sel} a képernyőn belül van")

            # 3) a szinkron gomb mobilra méretezett
            h = await page.evaluate("() => Math.round(document.querySelector('#btnSync').getBoundingClientRect().height)")
            ok(h >= 44, f"a frissítés gomb elég nagy (magasság: {h} px)")

            # 4) a táblázat összecsukott (nem 8 oszlop)
            vis = await page.evaluate("""() => {
                const t = document.querySelector('#esemenyekTable');
                return [...t.querySelectorAll('thead th')].filter(x => x.getBoundingClientRect().width > 0).length;
            }""")
            ok(0 < vis <= 4, f"a táblázat mobilon összecsukott ({vis} látható oszlop)")

            # 6) avatar a diák oszlopban + a dátum oszlop látszik
            await page.evaluate("() => bootstrap.Tab.getOrCreateInstance(document.getElementById('esemenyek-tab')).show()")
            await page.wait_for_timeout(800)
            av = await page.evaluate("""() => {
                const t = document.querySelector('#esemenyekTable');
                const avatars = [...t.querySelectorAll('tbody .avatar')];
                const ths = [...t.querySelectorAll('thead th')];
                const dateIdx = ths.findIndex(th => /dátuma/i.test(th.textContent));
                return {n: avatars.length,
                        text: avatars.length ? avatars[0].textContent.trim() : '',
                        bg: avatars.length ? getComputedStyle(avatars[0]).backgroundColor : '',
                        dateVisible: dateIdx >= 0 && ths[dateIdx].getBoundingClientRect().width > 0};
            }""")
            ok(av["n"] > 0, f"a diák oszlopban avatar van ({av['n']} db, pl. '{av['text']}')")
            ok(len(av["text"]) in (2, 3), f"a monogram 2-3 betűs ('{av['text']}')")
            ok(av["dateVisible"], "a bejegyzés dátuma oszlop látszik mobilon")
            # 7) a fejlécben mobilon is látszik az utolsó frissítés
            sched_txt = await page.evaluate("() => document.querySelector('#schedulerInfo').innerText")
            ok("Utolsó frissítés" in sched_txt, "a fejlécben mobilon is látszik az utolsó frissítés")
            ok("Ütemező" in sched_txt and "időablak" in sched_txt, "az ütemező állapota és az időablak is látszik")

            # 8) hiányzások fül: havi választó, összesítő és a két táblázat elfér
            await page.evaluate("() => bootstrap.Tab.getOrCreateInstance(document.getElementById('hianyzasok-tab')).show()")
            await page.wait_for_timeout(900)
            for sel in ("#hianyzasHonap", "#hianyzasSummary", "#hianyzasokTable", "#igazolasokTable"):
                box = await page.evaluate("""(s) => { const e = document.querySelector(s); if (!e) return null;
                    const r = e.getBoundingClientRect(); return {w: r.width, right: r.right}; }""", sel)
                ok(box and box["w"] > 0 and box["right"] <= 394, f"{sel} a képernyőn belül van")

            # 5) a fülek tördelődnek — minden fül látszik, nem fut ki
            tabs_info = await page.evaluate("""() => {
                const nav = document.getElementById('mainTab');
                const items = [...nav.querySelectorAll('.nav-link')];
                return {scroll: nav.scrollWidth, client: nav.clientWidth,
                        wrap: getComputedStyle(nav).flexWrap,
                        count: items.length,
                        lastRight: Math.round(items[items.length - 1].getBoundingClientRect().right),
                        rows: new Set(items.map(i => Math.round(i.getBoundingClientRect().top))).size};
            }""")
            ok(tabs_info["scroll"] <= tabs_info["client"] + 1,
               f"a fül-sáv nem csúszik ki ({tabs_info['scroll']} <= {tabs_info['client']})")
            ok(tabs_info["lastRight"] <= 394, f"az utolsó fül is a képernyőn belül van (jobb szél: {tabs_info['lastRight']})")
            ok(tabs_info["rows"] >= 1, f"a fülek {tabs_info['rows']} sorba rendeződnek")

            await b.close()

    asyncio.run(check())
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    shutil.rmtree(work, ignore_errors=True)

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
