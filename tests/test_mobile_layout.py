# -*- coding: utf-8 -*-
"""
Mobil elrendezés regressziós teszt (Redmi 12/13/14 ~393 CSS px).

Valódi böngészőben (Playwright/Chromium) nyitja meg az appot, és minden fülön
ellenőrzi, hogy nincs vízszintes túlcsordulás, a fő elemek láthatók, és a
koppintható célok nem túl kicsik.
"""
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import shutil
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
    targy TEXT, idopont TEXT, szoveg TEXT, csatolmany_nev TEXT, csatolmany_utvonal TEXT,
    olvasott INTEGER DEFAULT 1, letrehozva TEXT);
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
# Határidős tétel: a mobil sorban a határidő legyen a dátum, ne a bejegyzés kelte.
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek, "
    "bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
    ("Teszt Elek", "Bejelentett számonkérés", "Fizika", "", 0,
     "2026. 11. 02.", "2026. 11. 25.", "Kovács Anna", "Írásbeli", "Dolgozat",
     "Témakör", "", "Részletes leírás"),
)
for i in range(8):
    conn.execute(
        "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg) VALUES (?,?,?,?,?,?)",
        ("Teszt Elek", str(i), "Iskola", f"Tájékoztató üzenet {i}", "2026. 10. 20.", "Szöveg"),
    )
# Olvasatlan, hosszú tárgy: a pötty mellett is látszania kell a szövegnek.
conn.execute(
    "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg,"
    " olvasott, letrehozva) VALUES (?,?,?,?,?,?,?,?)",
    ("Teszt Elek", "99", "Iskola",
     "Vasárnapi osztálymise (11.29.) - hosszú tárgy a tördelés ellenőrzéséhez",
     "2026. 10. 21.", "Szöveg", 0, "2026-10-21 10:00:00"),
)
# Második gyermek: az üzenetek fül saját gyermek-szűrőjének tesztjéhez.
conn.execute(
    "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg,"
    " olvasott, letrehozva) VALUES (?,?,?,?,?,?,?,?)",
    ("Második Elek", "100", "Iskola", "Második gyermek üzenete",
     "2026. 10. 20.", "Szöveg", 1, "2026-10-20 10:00:00"),
)
# A Ma fül részletek-modál tesztjéhez a /api/ma válaszát egészítjük ki
# (a DB-fixture marad változatlan, így az Események táblázat tesztjeit nem érinti).
MAI = date.today().isoformat()
HETFO = (date.today() - timedelta(days=date.today().weekday())).isoformat()


def ma_hatarido(id_, tipus, tantargy, tema, tartalom, hatarido):
    return {
        "id": id_, "diak_nev": "Teszt Elek", "esemeny_tipus": tipus,
        "tantargy": tantargy, "megnevezes": tema, "hatarido": hatarido,
        "mikor": "ma", "kesz": 0, "ertek": "", "suly_szazalek": 0,
        "bej_datum": "2026. 11. 01.", "ertekelo": "Kovács Anna", "tipus": tipus,
        "mod": "", "tema": tema, "cim": "", "tartalom": tartalom,
    }
for i, nap in enumerate(["hétfő", "kedd", "szerda", "csütörtök", "péntek"]):
    conn.execute(
        "INSERT INTO orarend (diak_nev, kezdo_idopont, zaro_idopont, nap, tantargy, tanar, terem)"
        " VALUES (?,?,?,?,?,?,?)",
        ("Teszt Elek", f"2026-10-{26 + i:02d}T08:00:00", f"2026-10-{26 + i:02d}T08:45:00",
         nap, "Matematika", "Kovács Anna", "101"),
    )
# Kaneo #144: munkaszombati óra a heti nézet hétvége-tesztjéhez (aktuális hét)
SZOMBAT = date.fromisoformat(HETFO) + timedelta(days=5)
conn.execute(
    "INSERT INTO orarend (diak_nev, kezdo_idopont, zaro_idopont, nap, tantargy, tanar, terem)"
    " VALUES (?,?,?,?,?,?,?)",
    ("Teszt Elek", f"{SZOMBAT}T09:00:00", f"{SZOMBAT}T09:45:00",
     "szombat", "Matematika", "Kovács Anna", "101"),
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

            async def ma_route(route):
                """A /api/ma válaszát kiegészíti a részletek-modál tesztadatokkal."""
                resp = await route.fetch()
                data = await resp.json()
                query = parse_qs(urlparse(route.request.url).query)
                datum = (query.get("datum") or [data.get("datum") or ""])[0]
                extra = []
                if datum == MAI:
                    extra.append(ma_hatarido(900001, "Házi feladat", "Biológia",
                                             "Ma teszt házi", "Részletes leírás a modálhoz", MAI))
                if datum == HETFO:
                    extra.append(ma_hatarido(900002, "Bejelentett számonkérés", "Fizika",
                                             "Heti teszt dolgozat", "Heti részletek a modálhoz", HETFO))
                data["hataridok"] = (data.get("hataridok") or []) + extra
                await route.fulfill(response=resp, json=data)

            await page.route("**/api/ma*", ma_route)
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
            for tab in ("ma", "esemenyek", "hianyzasok", "orarend", "naptar", "uzenetek", "rewards", "logs"):
                await page.evaluate(
                    "(id) => bootstrap.Tab.getOrCreateInstance(document.getElementById(id)).show()", tab + "-tab")
                await page.wait_for_timeout(900)
                sw = await page.evaluate("document.documentElement.scrollWidth")
                ok(sw <= 393, f"'{tab}' fül: nincs vízszintes túlcsordulás ({sw} px)")

            # 1b) a Ma fül tartalma betöltődik (Kaneo #9)
            await page.evaluate("() => bootstrap.Tab.getOrCreateInstance(document.getElementById('ma-tab')).show()")
            await page.wait_for_timeout(700)
            ma = await page.evaluate("""() => { const q = s => document.querySelectorAll(s).length;
                return {title: (document.querySelector('#maDatumCim') || {}).innerText || '',
                        db: q('#maOrak .list-group-item') + q('#maHataridok .list-group-item')
                            + q('#maJegyek .list-group-item') + q('#maUzenetek .list-group-item')}; }""")
            ok(ma["title"].startswith("Ma,"), f"a Ma fül dátumfejléce betöltődött ('{ma['title']}')")
            ok(ma["db"] > 0, f"a Ma fül kártyái feltöltődtek ({ma['db']} sor)")

            # 1b1) a ma/holnapi határidőre koppintva részletek modál (felhasználói kérés)
            await page.click("#maHataridok .ma-hatarido:has-text('Ma teszt házi')")
            await page.wait_for_selector('#detailsModal.show', timeout=5000)
            await page.wait_for_timeout(250)
            reszlet = await page.evaluate("""() => {
                const body = document.querySelector('#detailsModalBody');
                const status = [...body.querySelectorAll('.reszletek-hero-fej .badge')]
                    .find(b => b.innerText.trim() === 'Aktív');
                return {
                    visible: document.querySelector('#detailsModal').classList.contains('show'),
                    text: (body || {}).innerText || '',
                    hero: !!body.querySelector('.reszletek-hero'),
                    subject: (body.querySelector('.reszletek-tantargy') || {}).innerText || '',
                    adat: body.querySelectorAll('.reszletek-hero-adat').length,
                    statusClass: status ? status.className : '',
                    meta: body.querySelectorAll('.reszletek-meta-item').length,
                    leiras: (body.querySelector('.reszletek-leiras-szoveg') || {}).innerText || ''
                };
            }""")
            ok(reszlet["visible"] and reszlet["hero"] and reszlet["subject"] == "Biológia"
               and reszlet["adat"] == 2 and reszlet["meta"] >= 2
               and "Részletes leírás a modálhoz" in reszlet["leiras"],
               f"a Ma fül határidő-sorára koppintva tagolt részletek modál nyílik: {reszlet}")
            ok("text-bg-success" in reszlet["statusClass"],
               f"az aktív állapot zöld jelvény ({reszlet['statusClass']})")
            await page.click('#detailsModal .btn-close')
            await page.wait_for_timeout(400)

            # 1b2) Ma / Hét nézetváltó (Kaneo #104) — kompakt heti kártya, havi nézet nincs
            await page.click('#maNezetKapcsolo [data-nezet="het"]')
            await page.wait_for_timeout(1500)
            het = await page.evaluate("""() => ({
                visible: !document.querySelector('#maHetNezet').classList.contains('d-none'),
                napok: document.querySelectorAll('#maHetNezet .ma-het-kartya').length,
                cim: (document.querySelector('#maHetNezet .ma-het-cim') || {}).innerText || '',
                honapGomb: document.querySelectorAll('#maNezetKapcsolo [data-nezet="honap"]').length,
                tulcsordulas: document.querySelector('#maHetNezet').scrollWidth
                    > document.querySelector('#maHetNezet').clientWidth + 1})""")
            ok(het["visible"] and het["napok"] == 6,
               f"a heti nézet 6 napkártyát mutat (munkaszombat, #144): {het}")
            ok("hétfő–vasárnap" in het["cim"],
               f"a heti fejléc hétvégére vált: {het['cim']!r}")
            ok(het["honapGomb"] == 0, "nincs havi nézet gomb a kapcsolón")
            ok(not het["tulcsordulas"], "a heti nézet nem csordul túl mobilon")

            # 1b3) a heti nézet határidő-sorára koppintva is részletek modál nyílik
            await page.click("#maHetNezet .ma-hatarido:has-text('Heti teszt dolgozat')")
            await page.wait_for_selector('#detailsModal.show', timeout=5000)
            await page.wait_for_timeout(250)
            het_reszlet = await page.evaluate("""() => ({
                visible: document.querySelector('#detailsModal').classList.contains('show'),
                text: (document.querySelector('#detailsModalBody') || {}).innerText || ''})""")
            ok(het_reszlet["visible"] and "Heti részletek a modálhoz" in het_reszlet["text"],
               f"a heti nézet határidő-sorára koppintva részletek modál nyílik: "
               f"{het_reszlet['text'][:80]!r}")
            await page.click('#detailsModal .btn-close')
            await page.wait_for_timeout(400)

            await page.click('#maNezetKapcsolo [data-nezet="nap"]')
            await page.wait_for_timeout(600)

            # 1c) a kereső fókuszát külön, óra-mock nélküli oldalon ellenőrizzük
            # (a rögzített óra mellett a Bootstrap átmenet-timerje nem fut le).
            await page.wait_for_timeout(50)
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
                const ertekIdx = ths.findIndex(th => /Érték/i.test(th.textContent));
                return {n: avatars.length,
                        text: avatars.length ? avatars[0].textContent.trim() : '',
                        bg: avatars.length ? getComputedStyle(avatars[0]).backgroundColor : '',
                        dateVisible: dateIdx >= 0 && ths[dateIdx].getBoundingClientRect().width > 0,
                        ertekVisible: ertekIdx >= 0 && ths[ertekIdx].getBoundingClientRect().width > 0,
                        ertekText: ertekIdx >= 0 ? (t.querySelector('tbody tr td:nth-child(' + (ertekIdx + 1) + ')') || {}).textContent || '' : ''};
            }""")
            ok(av["n"] > 0, f"a diák oszlopban avatar van ({av['n']} db, pl. '{av['text']}')")
            ok(len(av["text"]) in (2, 3), f"a monogram 2-3 betűs ('{av['text']}')")
            hidden = await page.evaluate("""() => {
                const ths = [...document.querySelectorAll('#esemenyekTable thead th')];
                return [3, 4].every(i => !ths[i] || ths[i].getBoundingClientRect().width === 0);
            }""")
            ok(hidden, "mobilon a külön Érték/Dátum oszlop rejtve (a jegy+dátum a tantárgy mellett)")
            muvelet = await page.evaluate("""() => {
                const ths = [...document.querySelectorAll('#esemenyekTable thead th')];
                const idx = ths.findIndex(th => /Műveletek/i.test(th.textContent));
                return idx >= 0 && ths[idx].getBoundingClientRect().width > 0;
            }""")
            ok(muvelet, "a Műveletek oszlop mobilon is látszik")
            # 6b) a tantárgy mellett a jegy, egy sorban a dátummal (Kaneo #153)
            extra = await page.evaluate("""() => {
                return [...document.querySelectorAll('#esemenyekTable tbody .mobile-subject-line .mobile-datum')]
                    .map(x => x.innerText.trim()).filter(Boolean);
            }""")
            egy = await page.evaluate("""() => {
                const k = document.querySelector('#esemenyekTable tbody .mobile-subject-line .jegy-kor');
                return k ? k.innerText.trim() : '';
            }""")
            diak_w = await page.evaluate(
                "() => document.querySelector('#esemenyekTable thead th').getBoundingClientRect().width")
            egy_sor = await page.evaluate("""() => {
                const line = document.querySelector('#esemenyekTable tbody .mobile-subject-line');
                if (!line) return false;
                const nev = line.querySelector('.mobile-subject-nev');
                const datum = line.querySelector('.mobile-datum');
                return !!nev && !!datum
                    && Math.abs(nev.getBoundingClientRect().top - datum.getBoundingClientRect().top) < 4;
            }""")
            ok(any("." in t for t in extra),
               f"mobilon a tantárgy mellett ott a rövid dátum: {extra[:2]}")
            ok(egy == "5", f"mobilon a jegy a jobb szélen, színes körben: {egy!r}")
            ok(diak_w <= 60, f"a diák-oszlop a monogramnyi szélességre szűkült ({diak_w:.0f} px)")
            one_line = await page.evaluate("""() => {
                const line = [...document.querySelectorAll('#esemenyekTable tbody .mobile-subject-line')]
                    .find(l => l.querySelector('.jegy-kor'));
                if (!line) return null;
                const td = line.closest('td');
                const k = line.querySelector('.jegy-kor');
                const tr = td.getBoundingClientRect();
                const lr = line.getBoundingClientRect();
                const kr = k ? k.getBoundingClientRect() : null;
                return {tdRight: Math.round(tr.right), lineRight: Math.round(lr.right),
                        lineWidth: Math.round(lr.width), tdWidth: Math.round(tr.width),
                        kRight: kr ? Math.round(kr.right) : null,
                        display: getComputedStyle(line).display};
            }""")
            ok(one_line and one_line["kRight"] is not None and
               (one_line["tdRight"] - one_line["kRight"]) < 12,
               f"a jegy a cella jobb szélén van: {one_line}")
            rovid = await page.evaluate("""() => {
                return [...document.querySelectorAll('#esemenyekTable tbody .mobile-tipus-rovid')]
                    .map(x => x.innerText.trim()).filter(Boolean);
            }""")
            ok(any(t in ("É", "F", "HF", "SZK") for t in rovid),
               f"mobilon a típus rövidítése is látszik: {rovid[:3]}")
            date_rights = await page.evaluate("""() => {
                return [...document.querySelectorAll('#esemenyekTable tbody .mobile-subject-line .mobile-datum')]
                    .map(x => Math.round(x.getBoundingClientRect().right));
            }""")
            ok(len(set(date_rights)) <= 1,
               f"a dátum minden sorban fix helyen van: {sorted(set(date_rights))[:4]}")
            # 6c) határidős tételnél a mobil sor a határidőt mutatja (nem a bejegyzés kelte)
            szk = await page.evaluate("""() => {
                const line = [...document.querySelectorAll('#esemenyekTable tbody .mobile-subject-line')]
                    .find(l => /Fizika/.test(l.innerText));
                if (!line) return null;
                const d = line.querySelector('.mobile-datum');
                const tipus = line.querySelector('.mobile-tipus-rovid');
                return {datum: d ? d.innerText.trim() : '',
                        title: d ? (d.getAttribute('title') || '') : '',
                        tipus: tipus ? tipus.innerText.trim() : ''};
            }""")
            ok(szk and szk["tipus"] == "SZK", f"a számonkérés rövidítése SZK: {szk}")
            ok(szk and szk["datum"] == "11.25.",
               f"mobilon a számonkérés mellett a határidő látszik: {szk and szk['datum']!r}")
            ok(szk and "Határidő" in szk["title"] and "2026. 11. 25." in szk["title"],
               f"a dátum tooltipje a határidőt jelzi: {szk and szk['title']!r}")
            await page.evaluate("""() => {
                const row = [...document.querySelectorAll('#esemenyekTable tbody tr')]
                    .find(tr => /Fizika/.test(tr.innerText));
                const btn = row && row.querySelector('.btn-show-details');
                if (btn) btn.click();
            }""")
            await page.wait_for_selector('#detailsModal.show', timeout=5000)
            modal_szoveg = " ".join((await page.inner_text('#detailsModalBody')).split())
            ok("bejegyzés dátuma" in modal_szoveg.lower() and "2026. 11. 02." in modal_szoveg,
               f"a részletekben megmarad a bejegyzés (rögzítés) dátuma: {modal_szoveg[:160]}")
            ok("Határidő: 2026. 11. 25." in modal_szoveg,
               "a részletekben a határidő is látszik")
            await page.click('#detailsModal .modal-footer .btn-secondary')
            await page.wait_for_timeout(400)
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
                const token = schedulerCompactState({last_run: '2026-11-03 21:33:00',
                    last_status: 'done_with_errors', health: {last_error_type: 'token'}});
                const help = schedulerHelpText({last_status: 'done_with_errors',
                    health: {last_error_type: 'token'}});
                const partial = schedulerCompactState({last_run: '2026-11-03 21:33:00',
                    last_status: 'done_with_errors',
                    health: {last_failed_datasets: ['üzenetek']}});
                const helpPartial = schedulerHelpText({last_status: 'done_with_errors',
                    health: {last_failed_datasets: ['üzenetek']}});
                return {running: running.text, error: err.text, done: done.text,
                        token: token.text, help: help,
                        partial: partial.text, helpPartial: helpPartial,
                        spin: running.icon.indexOf('spinner') >= 0,
                        red: err.icon.indexOf('text-danger') >= 0,
                        tokenRed: token.icon.indexOf('text-danger') >= 0,
                        green: done.icon.indexOf('text-success') >= 0};
            }""")
            ok(states["spin"] and "folyamatban" in states["running"],
               f"futás közben a sáv pörgő ikont és rövid szöveget mutat ('{states['running']}')")
            ok(states["red"] and "Sikertelen" in states["error"],
               f"hiba esetén piros állapot ('{states['error']}')")
            ok(states["green"] and "Frissítve" in states["done"],
               f"siker esetén zöld állapot ('{states['done']}')")
            ok(states["tokenRed"] and "belépés" in states["token"].lower()
               and "koppints" in states["token"].lower(),
               f"token-hiba esetén érthető, koppintásra hívó állapot ('{states['token']}')")
            ok("automatikusan" in states["help"].lower()
               and "config.json" in states["help"].lower(),
               "a részletek ablak elmagyarázza az automatikus újrabelépést")
            ok("üzenetek" in states["partial"].lower()
               and "üzenetek" in states["helpPartial"].lower(),
               f"részleges hibánál látszik a sikertelen adatkör ('{states['partial']}')")

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
                        headerClient: h ? h.clientWidth : 0,
                        logoWidth: (() => {
                            const l = document.querySelector('.app-logo');
                            return l ? Math.round(l.getBoundingClientRect().width) : 0;
                        })(),
                        titleSize: (() => {
                            const t = document.querySelector('.app-title');
                            return t ? Math.round(parseFloat(getComputedStyle(t).fontSize)) : 0;
                        })()};
            }""")
            ok(desk["compactVisible"] and not desk["detailsVisible"],
               "asztali nézetben is az egysoros szinkron-státusz látszik")
            ok(desk["headerHeight"] <= 100,
               f"a fejléc asztalon kompakt marad ({desk['headerHeight']} px)")
            ok(desk["headerScroll"] <= desk["headerClient"] + 1,
               f"a fejléc asztalon sem csúszik ki ({desk['headerScroll']} <= {desk['headerClient']})")
            ok(desk["logoWidth"] >= 64 and desk["titleSize"] >= 32,
               f"a középső logó/név nagy (logó {desk['logoWidth']} px, név {desk['titleSize']} px)")

            # 7d) széles kijelzőn a Ma fül ugyanúgy középre igazított, mint az Áttekintés
            await page.set_viewport_size({"width": 1600, "height": 950})
            await page.wait_for_timeout(400)
            await page.evaluate("() => bootstrap.Tab.getOrCreateInstance(document.getElementById('attekintes-tab')).show()")
            await page.wait_for_timeout(400)
            attek = await page.evaluate("""() => {
                const r = document.querySelector('#attekintes-pane').getBoundingClientRect();
                return {w: Math.round(r.width), l: Math.round(r.left), r: Math.round(r.right)}; }""")
            await page.evaluate("() => bootstrap.Tab.getOrCreateInstance(document.getElementById('ma-tab')).show()")
            await page.wait_for_timeout(600)
            ma_szeles = await page.evaluate("""() => {
                const r = document.querySelector('#ma-pane').getBoundingClientRect();
                return {w: Math.round(r.width), l: Math.round(r.left), r: Math.round(r.right)}; }""")
            ok(attek["w"] <= 1200 and ma_szeles["w"] <= 1200
               and abs(attek["w"] - ma_szeles["w"]) <= 1
               and abs(attek["l"] - ma_szeles["l"]) <= 1
               and abs(attek["r"] - ma_szeles["r"]) <= 1,
               f"a Ma fül ugyanakkora középre igazított sávot használ, mint az Áttekintés "
               f"({attek} / {ma_szeles})")

            # 7e) asztali részletek modál: kétoszlopos meta, nincs túlcsordulás
            await page.click("#maHataridok .ma-hatarido:has-text('Ma teszt házi')")
            await page.wait_for_selector('#detailsModal.show', timeout=5000)
            await page.wait_for_timeout(250)
            asztali_modal = await page.evaluate("""() => {
                const body = document.querySelector('#detailsModalBody');
                const meta = body.querySelector('.reszletek-meta');
                const modal = document.querySelector('#detailsModal .modal-dialog');
                return {
                    cols: meta ? getComputedStyle(meta).gridTemplateColumns.split(' ').length : 0,
                    bodyScroll: body.scrollWidth, bodyClient: body.clientWidth,
                    modalWidth: Math.round(modal.getBoundingClientRect().width),
                    heroAdat: body.querySelectorAll('.reszletek-hero-adat').length
                };
            }""")
            ok(asztali_modal["cols"] == 2, f"asztalon a részletek kétoszloposak ({asztali_modal})")
            ok(asztali_modal["bodyScroll"] <= asztali_modal["bodyClient"] + 1,
               f"a részletek modál tartalma nem csúszik ki ({asztali_modal})")
            await page.click('#detailsModal .btn-close')
            await page.wait_for_timeout(400)

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
            # Az olvasatlan pötty ne szorítsa ki a hosszú tárgyat a cellából.
            uzenet_cella = await page.evaluate("""() => {
                const tr = document.querySelector('#uzenetekTable tbody tr.uzenet-olvasatlan');
                if (!tr) return null;
                const td = [...tr.children].find(x => x.querySelector && x.querySelector('.uzenet-targy-cell'));
                if (!td) return null;
                const sp = td.querySelector('.cell-truncate');
                const tdr = td.getBoundingClientRect(), spr = sp.getBoundingClientRect();
                return {text: sp.innerText.slice(0, 40), width: Math.round(spr.width),
                        tdRight: Math.round(tdr.right), spRight: Math.round(spr.right),
                        dot: !!td.querySelector('.uzenet-status-dot')};
            }""")
            ok(uzenet_cella is not None and uzenet_cella["dot"],
               f"az olvasatlan üzenetsor pöttyöt kap: {uzenet_cella}")
            ok(uzenet_cella and uzenet_cella["width"] >= 80,
               f"a hosszú tárgy látható helyet kap az olvasatlan sorban: {uzenet_cella}")
            ok(uzenet_cella and uzenet_cella["spRight"] <= uzenet_cella["tdRight"] - 2,
               f"az olvasatlan tárgy nem csúszik ki a cellából: {uzenet_cella}")
            # A hosszú tárgy miatt a Műveletek oszlop a gyermeksorba csúszhat:
            # ott is elérhető az Olvasás gomb, ezt használjuk.
            olvas = page.locator('#uzenetekTable .btn-read-msg:visible').first
            if await olvas.count() == 0:
                await page.click('#uzenetekTable tbody tr:first-child td.dtr-control')
                await page.wait_for_timeout(400)
                olvas = page.locator('#uzenetekTable .btn-read-msg:visible').first
            await olvas.click()
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
            ai_gomb = await page.evaluate("""() => !!document.querySelector('#btnUzenetAi')""")
            ok(not ai_gomb, "az üzenet ablakban nincs AI-elemzés gomb (a felületből kivette, #61)")
            await page.click('#uzenetModal .btn-secondary')
            await page.wait_for_timeout(400)

            # 10b) az üzenetek fül saját gyermek-szűrője (nem az Áttekintés kiválasztása)
            await page.select_option('#uzenetFilterDiak', 'Második Elek')
            await page.wait_for_timeout(700)
            szurt = await page.evaluate("""() => {
                const dt = window.jQuery('#uzenetekTable').DataTable();
                return {n: dt.rows().count(),
                        names: [...new Set(dt.rows().data().toArray()
                            .map(d => d ? d.diak_nev : '?'))]};
            }""")
            ok(szurt["n"] >= 1 and szurt["names"] == ["Második Elek"],
               f"az üzenetek fül gyermek-szűrője működik: {szurt}")
            await page.select_option('#uzenetFilterDiak', '')
            await page.wait_for_timeout(700)
            minden = await page.evaluate("""() => {
                const dt = window.jQuery('#uzenetekTable').DataTable();
                return [...new Set(dt.rows().data().toArray()
                    .map(d => d ? d.diak_nev : '?'))];
            }""")
            ok(len(minden) >= 2,
               f"visszaváltva ismét minden gyermek üzenete látszik: {minden}")

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

            # 11) Sötét mód + nyomtatás (Kaneo #86)
            await page.click('#btnTheme')
            await page.wait_for_timeout(300)
            tema = await page.evaluate("() => document.documentElement.getAttribute('data-bs-theme')")
            ok(tema == 'dark', f"a gomb sötét módra vált ('{tema}')")
            await page.reload()
            await page.wait_for_timeout(1200)
            tema2 = await page.evaluate("() => document.documentElement.getAttribute('data-bs-theme')")
            ok(tema2 == 'dark', "a választás újratöltés után is megmarad (localStorage)")
            chip = await page.evaluate("""() => {
                const e = [...document.querySelectorAll('#dashboardDiakChips .chip-diak')]
                    .find(x => !x.classList.contains('active'));
                if (!e) return null;
                const s = getComputedStyle(e);
                return {color: s.color, border: s.borderColor};
            }""")
            def _vilagossag(c):
                p = [int(x) for x in re.findall(r"\d+", c or "")[:3]]
                return sum(p) if len(p) == 3 else 0
            ok(chip is not None and _vilagossag(chip["color"]) > 300,
               f"sötét módban a szűrő-címkék olvashatók ({chip})")
            # a naptár címének ellenőrzéséhez nyissuk meg az órarend fület
            await page.evaluate("() => bootstrap.Tab.getOrCreateInstance(document.getElementById('orarend-tab')).show()")
            await page.wait_for_timeout(900)
            dark = await page.evaluate("""() => {
                const c = (sel) => { const e = document.querySelector(sel); return e ? getComputedStyle(e).color : ''; };
                const bg = (sel) => { const e = document.querySelector(sel); return e ? getComputedStyle(e).backgroundColor : ''; };
                return {kpi: c('#tileHazi .kpi-title'), hianyzas: c('#stHianyzasOra'),
                        fc: c('.fc .fc-toolbar-title'), tableBg: bg('.table-container'),
                        schedBg: bg('#schedulerCompact'), modalFej: c('.modal-header.bg-info')};
            }""")
            ok(_vilagossag(dark["kpi"]) > 300,
               f"a dashboard kártyacím olvasható sötét módban ({dark['kpi']})")
            ok(_vilagossag(dark["hianyzas"]) > 300,
               f"a hiányzás-összesítő érték olvasható ({dark['hianyzas']})")
            ok(_vilagossag(dark["fc"]) > 300,
               f"a naptár címe olvasható sötét módban ({dark['fc']})")
            ok(_vilagossag(dark["tableBg"]) < 220,
               f"a táblázat-konténer sötét ({dark['tableBg']})")
            ok(_vilagossag(dark["schedBg"]) < 220,
               f"a státuszsáv sötét ({dark['schedBg']})")
            ok(_vilagossag(dark["modalFej"]) < 300,
               f"a ciánkék modálfejlécen sötét a szöveg ({dark['modalFej']})")
            await page.click('#btnTheme')
            await page.wait_for_timeout(200)

            # nyomtatási nézet: a gomb felépíti a táblát és meghívja a window.print-et
            await page.evaluate("() => bootstrap.Tab.getOrCreateInstance(document.getElementById('orarend-tab')).show()")
            await page.wait_for_timeout(600)
            await page.evaluate("() => { window.__printed = false; window.print = () => { window.__printed = true; }; }")
            await page.click('#btnOrarendNyomtat')
            await page.wait_for_timeout(1200)
            nyomtat = await page.evaluate("""() => ({
                called: !!window.__printed,
                tablak: document.querySelectorAll('#printOrarend table').length,
                sorok: document.querySelectorAll('#printOrarend tbody tr').length,
                diak: (document.querySelector('#printOrarend h3') || {}).innerText || ''
            })""")
            ok(nyomtat["called"], "a Nyomtatás gomb meghívja a böngésző nyomtatását")
            ok(nyomtat["tablak"] >= 1 and nyomtat["sorok"] >= 1,
               f"a nyomtatási nézet felépül ({nyomtat['tablak']} tábla, {nyomtat['sorok']} sor)")
            ok("Teszt" in nyomtat["diak"], f"a nyomtatási nézetben ott a diák neve ('{nyomtat['diak']}')")
            cim = await page.evaluate("() => document.title")
            ok(cim.startswith("SuliHub - Órarend -") and cim.count(" - ") >= 3,
               f"a nyomtatási fejléc a dokumentum címe: gyerek + időszak ('{cim}')")
            meta = await page.evaluate(
                "() => (document.querySelector('#printOrarend .print-meta') || {}).innerText || ''")
            ok(meta.strip() != "", f"a nyomtatási tartalom fejlécében is ott a gyerek és az időszak ('{meta}')")

            # 12) kereső: a nagyító ikon után a mező azonnal aktív (Kaneo #117)
            # Külön, óra-mock nélküli oldal, mert a rögzített óra mellett a
            # Bootstrap átmenet-timerje nem fut le.
            fctx = await b.new_context(viewport={"width": 393, "height": 873})
            fp = await fctx.new_page()
            await fp.goto(base, wait_until="networkidle")
            await fp.click("#btnKereses")
            await fp.wait_for_timeout(900)
            fokusz = await fp.evaluate("() => document.activeElement && document.activeElement.id")
            ok(fokusz == "keresesInput",
               f"a nagyító ikonnal nyitott kereső mező azonnal aktív ('{fokusz}')")
            await fctx.close()

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
