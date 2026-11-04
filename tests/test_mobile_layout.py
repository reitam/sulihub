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

    # Hosszú „utolsó frissítés / utolsó automatikus” szöveghez: legyen két futás
    # a sync_runs-ban (a production-höz hasonló hosszú fejléc-szöveg).
    conn = sqlite3.connect(db)
    try:
        for trigger, start, finish in (
            ("scheduled", "2026-11-03T18:00:00", "2026-11-03T18:02:00"),
            ("manual", "2026-11-03T21:16:00", "2026-11-03T21:18:00"),
        ):
            conn.execute(
                "INSERT INTO sync_runs (trigger, started_at, finished_at, status,"
                " ok_count, total_count) VALUES (?,?,?,?,?,?)",
                (trigger, start, finish, "done", 3, 3))
        conn.commit()
    finally:
        conn.close()

    import asyncio
    from playwright.async_api import async_playwright

    async def check():
        async with async_playwright() as p:
            b = await p.chromium.launch()
            ctx = await b.new_context(viewport={"width": 393, "height": 873}, device_scale_factor=2)
            page = await ctx.new_page()
            await page.goto(base, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(2500)

            # 0) a vendorolt frontend-könyvtárak tényleg betöltődtek (offline-képes)
            libs = await page.evaluate("""() => ({
                jquery: typeof window.jQuery,
                bootstrap: typeof window.bootstrap,
                datatable: !!(window.jQuery && window.jQuery.fn.DataTable),
                fullcalendar: typeof window.FullCalendar,
                fa: (() => {
                    const i = document.querySelector('.fa-solid');
                    return i ? getComputedStyle(i).fontFamily : '';
                })()
            })""")
            ok(libs["jquery"] == "function" and libs["bootstrap"] == "object"
               and libs["datatable"] and libs["fullcalendar"] == "object",
               f"a vendorolt JS-könyvtárak betöltődtek: {libs}")
            ok("Font Awesome" in libs["fa"],
               f"a vendorolt FontAwesome CSS betöltődött (font-family: '{libs['fa']}')")

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
            # 7) mobil: egyetlen karcsú státuszsáv, a technikai részletek koppintásra
            compact = await page.evaluate("""() => {
                const e = document.querySelector('#schedulerCompact');
                if (!e) return null;
                const r = e.getBoundingClientRect();
                const d = document.querySelector('#schedulerDetails');
                return {visible: r.width > 0 && r.height > 0,
                        height: Math.round(r.height),
                        right: Math.round(r.right),
                        text: e.innerText.trim(),
                        scroll: e.scrollWidth, client: e.clientWidth,
                        detailsVisible: !!d && d.getBoundingClientRect().height > 0};
            }""")
            ok(compact and compact["visible"], "mobilon látszik a kompakt szinkron-státuszsáv")
            ok(compact and compact["height"] <= 40,
               f"a státuszsáv egyetlen karcsú sor (magasság: {compact['height']} px)")
            ok(compact and "Frissítve" in compact["text"],
               f"a státuszsáv rövid, emberi szöveget mutat ('{compact['text']}')")
            ok(compact and not compact["detailsVisible"],
               "a technikai részletek (időablak, intervallum) mobilon alapból rejtve vannak")
            ok(compact and compact["right"] <= 394 and compact["scroll"] <= compact["client"] + 1,
               f"a státuszsáv nem csúszik ki: {compact}")

            # 7a) a dinamikus állapotok: futás / hiba / siker
            states = await page.evaluate("""() => {
                const running = schedulerCompactState({running: true, trigger: 'scheduled'});
                const err = schedulerCompactState({last_run: '2026-11-03 21:34:00', last_status: 'error'});
                const done = schedulerCompactState({last_run: '2026-11-03 21:33:00', last_status: 'done'});
                return {running: running.text, error: err.text, done: done.text,
                        spin: running.icon.indexOf('spinner') >= 0,
                        red: err.icon.indexOf('text-danger') >= 0,
                        green: done.icon.indexOf('text-success') >= 0};
            }""")
            ok(states["spin"] and "folyamatban" in states["running"],
               f"futás közben a sáv pörgő ikont és rövid szöveget mutat ('{states['running']}')")
            ok(states["red"] and "Sikertelen" in states["error"],
               f"hiba esetén piros állapot ('{states['error']}')")
            ok(states["green"] and "Frissítve" in states["done"],
               f"siker esetén zöld állapot ('{states['done']}')")

            # 7b) koppintásra megnyílik a részletek ablak
            await page.click('#schedulerCompact')
            await page.wait_for_selector('#schedulerDetailModal.show', timeout=5000)
            await page.wait_for_timeout(300)
            modal = await page.evaluate("""() => {
                const m = document.querySelector('#schedulerDetailModal');
                return {visible: m.classList.contains('show'), text: m.innerText};
            }""")
            ok(modal["visible"] and "Ütemező" in modal["text"],
               "a státuszsávra koppintva megnyílik a részletek ablak")
            ok("időablak" in modal["text"] and "Utolsó frissítés" in modal["text"],
               "a részletek ablakban ott van az időablak és az utolsó frissítés")
            modal_box = await page.evaluate("""() => {
                const body = document.querySelector('#schedulerDetailModal .modal-body');
                const wraps = [...document.querySelectorAll('#schedModalLast .text-nowrap')];
                return {scroll: body.scrollWidth, client: body.clientWidth,
                        wraps: wraps.length,
                        wrapped: wraps.length > 1
                            ? Math.round(wraps[1].getBoundingClientRect().top)
                              >= Math.round(wraps[0].getBoundingClientRect().bottom) - 1
                            : null};
            }""")
            ok(modal_box["scroll"] <= modal_box["client"] + 1,
               f"a részletek ablak tartalma nem csúszik ki ({modal_box['scroll']} <= {modal_box['client']})")
            ok(modal_box["wraps"] >= 2 and modal_box["wrapped"],
               "az utolsó frissítés és az utolsó automatikus futás külön sorba tördelve látszik")
            await page.click('#schedulerDetailModal .btn-close')
            await page.wait_for_timeout(400)

            # 7c) asztali nézetben is az egysoros státuszsáv látszik (Kaneo #63)
            await page.set_viewport_size({"width": 1200, "height": 873})
            await page.wait_for_timeout(400)
            desk = await page.evaluate("""() => {
                const d = document.querySelector('#schedulerDetails');
                const c = document.querySelector('#schedulerCompact');
                const h = document.querySelector('.app-header');
                return {detailsVisible: !!d && d.getBoundingClientRect().height > 0,
                        compactVisible: !!c && c.getBoundingClientRect().height > 0,
                        headerHeight: h ? Math.round(h.getBoundingClientRect().height) : 0,
                        headerScroll: h ? h.scrollWidth : 0,
                        headerClient: h ? h.clientWidth : 0};
            }""")
            ok(desk["compactVisible"] and not desk["detailsVisible"],
               "asztali nézetben is az egysoros szinkron-státusz látszik")
            ok(desk["headerHeight"] <= 80,
               f"a fejléc asztalon kompakt marad ({desk['headerHeight']} px)")
            ok(desk["headerScroll"] <= desk["headerClient"] + 1,
               f"a fejléc asztalon sem csúszik ki ({desk['headerScroll']} <= {desk['headerClient']})")
            await page.set_viewport_size({"width": 393, "height": 873})
            await page.wait_for_timeout(300)

            # 8) hiányzások fül: havi választó, összesítő és a két táblázat elfér
            await page.evaluate("() => bootstrap.Tab.getOrCreateInstance(document.getElementById('hianyzasok-tab')).show()")
            await page.wait_for_timeout(900)
            for sel in ("#hianyzasHonap", "#hianyzasSummary", "#hianyzasokTable", "#igazolasokTable"):
                box = await page.evaluate("""(s) => { const e = document.querySelector(s); if (!e) return null;
                    const r = e.getBoundingClientRect(); return {w: r.width, right: r.right}; }""", sel)
                ok(box and box["w"] > 0 and box["right"] <= 394, f"{sel} a képernyőn belül van")

            # 9) saját óra rögzítése (Kaneo #55): gomb → modal → mentés → naptárban látszik
            await page.evaluate("() => bootstrap.Tab.getOrCreateInstance(document.getElementById('orarend-tab')).show()")
            await page.wait_for_timeout(900)
            sajat_gomb = await page.evaluate("""() => {
                const b = document.querySelector('#btnSajatOra');
                if (!b) return null;
                const r = b.getBoundingClientRect();
                return {w: r.width, right: Math.round(r.right)};
            }""")
            ok(sajat_gomb and sajat_gomb["w"] > 0 and sajat_gomb["right"] <= 394,
               "a 'Saját óra' gomb mobilon is a képernyőn belül van")
            await page.click('#btnSajatOra')
            await page.wait_for_selector('#sajatOraModal.show', timeout=5000)
            await page.fill('#sajatOraCim', 'Teszt szakkör')
            await page.click('#btnSajatOraMent')
            await page.wait_for_timeout(1600)
            sajat_db = await page.evaluate("""() => {
                const evs = [...document.querySelectorAll('#orarendCalendar .fc-event')];
                const hit = evs.filter(e => (e.textContent || '').indexOf('Teszt szakkör') >= 0);
                return {n: hit.length, color: hit.length ? getComputedStyle(hit[0]).backgroundColor : ''};
            }""")
            ok(sajat_db and sajat_db["n"] >= 1,
               f"a mentett saját óra megjelenik a naptárban ({sajat_db})")
            ok(sajat_db and sajat_db["color"] == "rgb(111, 66, 193)",
               f"a saját óra megkülönböztető színű ({sajat_db and sajat_db['color']})")

            # 10) üzenet → naptárbejegyzés gombok (Kaneo #47)
            await page.evaluate("() => bootstrap.Tab.getOrCreateInstance(document.getElementById('uzenetek-tab')).show()")
            await page.wait_for_timeout(900)
            await page.click('#uzenetekTable .btn-read-msg')
            await page.wait_for_selector('#uzenetModal.show', timeout=5000)
            naptar_gombok = await page.evaluate("""() => {
                const google = document.querySelector('#btnUzenetNaptarGoogle');
                return {google: !!google && google.getBoundingClientRect().height > 0,
                        text: google ? google.innerText.trim() : '',
                        ics: !!document.querySelector('#btnUzenetNaptarIcs')};
            }""")
            ok(naptar_gombok["google"] and "Naptárba" in naptar_gombok["text"],
               f"az üzenet ablakban látszik a közvetlen naptárgomb ('{naptar_gombok['text']}')")
            ok(not naptar_gombok["ics"], "az üzenet ablakban nincs ICS-letöltés (közvetlen küldés)")
            await page.click('#uzenetModal .btn-secondary')
            await page.wait_for_timeout(400)

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
