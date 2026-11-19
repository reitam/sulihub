# -*- coding: utf-8 -*-
"""Dashboard (Kaneo #38) és tantárgyi átlagok (#39) — valódi böngészőben.

Ellenőrzi:
  - az Áttekintés fül az alapértelmezett, a csempék számai helyesek,
  - a csempére kattintás a szűrt eseménylistát nyitja,
  - a „Vissza az áttekintésre" gomb működik, a szűrőpanel csak a listán látszik,
  - a Statisztika fülön a tantárgyi átlagok táblázata (havi bontás) megjelenik.
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
from datetime import date, datetime, timedelta
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


def hu(d):
    return f"{d.year}. {d.month:02d}. {d.day:02d}."


def tanev_of(d):
    """Iskolai tanév a dátum alapján (szept. 1. – aug. 31.), mint a kreta_tanev."""
    kezdet = d.year if d.month >= 9 else d.year - 1
    return f"{kezdet}/{kezdet + 1}"


today = date(2026, 11, 4)   # determinisztikus teszt (a valódi naptártól független)
monday = today - timedelta(days=(today.weekday()))
sunday = monday + timedelta(days=6)

work = Path(tempfile.mkdtemp(prefix="kreta_dash_"))
db = work / "kreta_adatok.db"
(work / "config.json").write_text(json.dumps({
    "ENABLE_REWARDS": True,
    "REWARDS": {"jegy_5": 500, "jegy_4": 200, "jegy_3": 0, "jegy_2": -200, "jegy_1": -500,
                "dicseret": 500, "megrovas": -500, "lecke_hiany": -300, "felszereles_hiany": -300},
    "SCHEDULER": {"ENABLED": False},
    "STUDENTS": [{"diak_nev": "Teszt Elek", "enable_rewards": True, "active": False}],
}, ensure_ascii=False), encoding="utf-8")

env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(work), "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"), "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_HOST": "127.0.0.1", "KRETA_SERVER": "flask", "KRETA_DEBUG": "0",
    "PYTHONIOENCODING": "utf-8",
})
env.pop("KRETA_CSATOLMANYOK_DIR", None)
subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

conn = sqlite3.connect(db)


def add_event(tipus, tantargy, ertek, szam, suly, bej, hatarido="", tema="Téma"):
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
        " tanev, tanev_forras)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
        ("Teszt Elek", tipus, tantargy, ertek, szam, suly, hu(bej), hu(hatarido) if hatarido else "",
         "Tanár", "Évközi jegy", "Írásbeli", tema, "", "", tanev_of(bej), "szamitott"))


# Jegyek: 2 db az elmúlt 7 napban, 1 régi (de előző hónapban)
add_event("Értékelés", "Matematika", "Jeles(5)", 5, 100, today - timedelta(days=1))
add_event("Értékelés", "Fizika", "Jó(4)", 4, 50, today - timedelta(days=3))
add_event("Értékelés", "Matematika", "Közepes(3)", 3, 0, today - timedelta(days=30))
# Házik / számonkérések: 2 ezen a héten, 1 jövő héten, 1 múltban
add_event("Házi feladat", "Magyar nyelv", "", 0, 0, today, hatarido=today)
add_event("Bejelentett számonkérés", "Történelem", "", 0, 0, today - timedelta(days=2),
          hatarido=monday + timedelta(days=min(6, max(0, (today - monday).days + 1))))
add_event("Házi feladat", "Angol nyelv", "", 0, 0, today, hatarido=today + timedelta(days=10))
add_event("Házi feladat", "Biológia", "", 0, 0, today - timedelta(days=20),
          hatarido=today - timedelta(days=10))
# Feljegyzés (figyelmeztetés) a dashboard alsó feedjéhez
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " suly_szazalek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " tanev, tanev_forras) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
    ("Teszt Elek", "Feljegyzés", "Magatartás", "", 0, 0,
     hu(today - timedelta(days=2)), "", "Tanár", "Szaktanári figyelmeztetés", "",
     "Téma", "", "Órai fegyelmezés", tanev_of(today), "szamitott"))
# Üzenetek: 2 friss, 1 régi
for i, nap in enumerate([1, 3, 30]):
    conn.execute(
        "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg)"
        " VALUES (?,?,?,?,?,?)",
        ("Teszt Elek", str(i), "Iskola", f"Üzenet {i}",
         f"{hu(today - timedelta(days=nap))} 10:00", "Szöveg"))
# Hiányzások: 2 igazolatlan + 1 igazolt
for i, igazolt in enumerate([0, 0, 1]):
    h_datum = today - timedelta(days=i + 1)
    conn.execute(
        "INSERT INTO hianyzasok (diak_nev, mulasztas_datum, ora_sorszam, perc, tantargy,"
        " tema, tanar, mulasztas_tipus, igazolt, tanorai_celu, igazolas_tipus,"
        " rogzites_datum, kreta_id, tanev, tanev_forras)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("Teszt Elek", h_datum.isoformat(), i + 1, None,
         "Matematika", "Téma", "Tanár", "Hiányzás", igazolt, "Nem", "", today.isoformat(),
         f"h{i}", tanev_of(h_datum), "szamitott"))
# Egy már kifizetett időszak (500 Ft) — a dashboardon ezt le kell vonni
conn.execute("""
    CREATE TABLE IF NOT EXISTS kifizetesek (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        diak_nev TEXT NOT NULL,
        kezdo_datum TEXT NOT NULL,
        zaro_datum TEXT NOT NULL,
        kifizetve INTEGER DEFAULT 0,
        osszeg INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        tanev TEXT, tanev_forras TEXT,
        UNIQUE(diak_nev, kezdo_datum, zaro_datum)
    )
""")
conn.execute(
    "INSERT INTO kifizetesek (diak_nev, kezdo_datum, zaro_datum, kifizetve, osszeg,"
    " tanev, tanev_forras)"
    " VALUES (?,?,?,?,?,?,?)",
    ("Teszt Elek",
     date(today.year, today.month, 1).isoformat(),
     date(today.year, today.month, 1).isoformat(),
     1, 500, tanev_of(today), "szamitott"))
conn.commit()
conn.close()

# Zsebpénz: 5-ös +500, 4-es +200, 3-as 0 -> 700; ebből 500 kifizetve -> 200 marad.
expected_hatralevo = 700 - 500

# Várt értékek (ugyanaz a szabály, mint a frontenden): következő 10 nap.
deadline_end = today + timedelta(days=10)


def _in10(d):
    return today <= d <= deadline_end


hazi_10 = sum(1 for t, h in [("Házi feladat", today),
                             ("Házi feladat", today + timedelta(days=10)),
                             ("Házi feladat", today - timedelta(days=10))]
              if t == "Házi feladat" and _in10(h))
szam_10 = sum(1 for t, h in [("Bejelentett számonkérés",
                              monday + timedelta(days=min(6, max(0, (today - monday).days + 1))))]
              if _in10(h))
new_grades = 2
new_messages = 2

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

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 950})
        # A dashboard timeablak a BÖNGÉSZŐ dátumát használja — rögzítjük, hogy a
        # teszt fix "today"-je és a oldal megegyezzen (Kaneo #75: a CI-ban a
        # másnapi futásnál a "ma" határidő kicsúszott a 10 napos ablakból).
        page.clock.install(time=datetime(today.year, today.month, today.day, 12, 0))
        page.goto(base, wait_until="networkidle")
        page.wait_for_timeout(1200)

        print("\n1) Áttekintés fül (alapértelmezett)")
        ok(page.is_visible("#attekintes-pane"),
           "az Áttekintés fül aktív betöltéskor")
        ok(page.get_attribute("#attekintes-tab", "class").find("active") >= 0,
           "az Áttekintés tab 'active'")
        ok(not page.is_visible("#accordionFilterBlock"),
           "a szűrőpanel a dashboardon nem látszik")
        ok(page.input_value("#rewardFilterDiak") == "",
           "a statisztika gyermek-szűrője betöltéskor üres")
        ok(page.input_value("#riportDiak") == "",
           "a bizonyítvány gyermek-választója betöltéskor üres")
        ok(page.get_attribute(".app-brand", "href") == "/",
           "a SuliHub logó linkként az Áttekintésre mutat")

        print("\n2) Csempék számai")
        hazi = page.inner_text("#tileHaziSzam").strip()
        szam = page.inner_text("#tileSzamSzam").strip()
        jegy = page.inner_text("#tileUjJegyekSzam").strip()
        uzen = page.inner_text("#tileUjUzenetekSzam").strip()
        ok(hazi == str(hazi_10), f"következő házi feladatok: {hazi} (várt {hazi_10})")
        ok(szam == str(szam_10), f"következő számonkérések: {szam} (várt {szam_10})")
        ok(jegy == str(new_grades), f"új jegyek: {jegy} (várt {new_grades})")
        ok(uzen == str(new_messages), f"új üzenetek: {uzen} (várt {new_messages})")

        page.wait_for_timeout(800)
        iga = page.inner_text("#tileIgazolatlanSzam").strip()
        penz = page.inner_text("#tileZsebpenzSzam").strip()
        ok(iga.startswith("2"), f"igazolatlan hiányzás: {iga} (várt 2 óra)")
        ok(penz.replace(" ", "").replace("+", "").replace("Ft", "") == str(expected_hatralevo),
           f"kifizetetlen zsebpénz: {penz} (várt {expected_hatralevo} Ft, a kifizetett időszak levonva)")

        print("\n2b) Gyermekenkénti összesítő kártyák")
        kartya = page.eval_on_selector_all("#dashboardDiakCards .card",
                                           "els => els.map(e => e.innerText.replace(/\\s+/g, ' ').trim())")
        ok(len(kartya) == 1, f"1 gyermekkártya: {len(kartya)}")
        ok(kartya and "4.67" in kartya[0], f"a tanulmányi átlag a kártyán: {kartya[0] if kartya else ''}")
        ok(kartya and "200" in kartya[0], "a kifizetetlen egyenleg a kártyán")
        page.screenshot(path=str(work / "attekintes.png"))
        print("SCREENSHOT (áttekintés):", work / "attekintes.png")

        print("\n2b/2) Átlagkártyáról a statisztika havi bontására")
        page.click("#dashboardDiakCards .diak-atlag-kartya")
        page.wait_for_timeout(1800)
        ok(page.is_visible("#rewards-pane"), "a Statisztika fül megnyílt")
        ok(page.input_value("#rewardFilterDiak") == "Teszt Elek",
           f"a kiválasztott gyermek: {page.input_value('#rewardFilterDiak')}")
        ok(page.is_visible("#atlagokBody"), "a tantárgyi átlagok lenyíltak")
        idoszak_kartya = " ".join(page.inner_text("#atlagokIdoszak").split())
        ok("időszak" in idoszak_kartya and "2026. 09. 01." in idoszak_kartya
           and "2027. 08. 31." in idoszak_kartya,
           f"a teljes tanév időszaka látszik: {idoszak_kartya}")
        page.click('#atlagokCard button[data-bs-target="#atlagokCollapse"]')
        page.wait_for_timeout(300)
        page.click("#attekintes-tab")
        page.wait_for_timeout(900)

        print("\n2c) Alsó feed: figyelmet igénylő bejegyzés + legutóbbi jegyek")
        figy = " ".join(page.inner_text("#dashFigyelemLista").split())
        ok("Figyelmeztetés" in figy and "Órai fegyelmezés" in figy,
           f"a figyelmeztető bejegyzés látszik: {figy[:120]}")
        jegy_sorok = page.eval_on_selector_all("#dashJegyLista .list-group-item",
                                               "els => els.length")
        ok(jegy_sorok >= 3, f"a legutóbbi jegyek listája: {jegy_sorok} sor")

        print("\n3) Csempe -> szűrt eseménylista")
        page.click("#tileUjJegyek")
        page.wait_for_timeout(1200)
        ok(page.is_visible("#esemenyek-pane"), "az Események fül megnyílt")
        ok(page.is_visible("#accordionFilterBlock") and not page.is_visible("#collapseFilter"),
           "a szűrőpanel alapból zárva van (csak a fejléc látszik)")
        page.click('#accordionFilterBlock .accordion-button')
        page.wait_for_timeout(600)
        ok(page.is_visible("#collapseFilter"), "kattintásra lenyílik a szűrőpanel")
        # A felső menüsor pozíciója ne változzon, a szűrőpanel alatta legyen (#121).
        tab_top_esemenyek = page.evaluate(
            "() => Math.round(document.querySelector('#mainTab').getBoundingClientRect().top)")
        below = page.evaluate("""() => {
            const t = document.querySelector('#mainTab').getBoundingClientRect();
            const f = document.querySelector('#accordionFilterBlock').getBoundingClientRect();
            return f.top >= t.bottom - 1;
        }""")
        ok(below, "a szűrőpanel a felső menüsor ALATT van")
        page.click('.app-brand')
        page.wait_for_timeout(700)
        ok(page.is_visible('#attekintes-pane'),
           "a logó kattintása visszavisz az Áttekintés fülre")
        tab_top_dash = page.evaluate(
            "() => Math.round(document.querySelector('#mainTab').getBoundingClientRect().top)")
        ok(abs(tab_top_esemenyek - tab_top_dash) <= 1,
           f"a felső menüsor nem ugrál (Események {tab_top_esemenyek} px, Áttekintés {tab_top_dash} px)")
        page.click('#esemenyek-tab')
        page.wait_for_timeout(700)
        ok(page.input_value("#filterTipus") == "Értékelés", "típus = Értékelés")
        rows = page.eval_on_selector_all("#esemenyekTable tbody tr",
                                         "rows => rows.filter(r => r.querySelectorAll('td').length > 1).length")
        ok(rows == new_grades, f"a listában {rows} jegy (várt {new_grades}, a régi kimaradt)")

        print("\n4) Vissza az áttekintésre — az adatok F5 nélkül is visszatérnek (Kaneo #76)")
        page.click(".btn-back-dashboard")
        page.wait_for_timeout(900)
        ok(page.is_visible("#attekintes-pane"), "visszalépés a dashboardra")
        ok(not page.is_visible("#accordionFilterBlock"), "a szűrőpanel ismét rejtve")
        jegy_ujra = page.inner_text("#tileUjJegyekSzam").strip()
        hazi_ujra = page.inner_text("#tileHaziSzam").strip()
        ok(jegy_ujra == str(new_grades),
           f"új jegyek csempe visszaállt szűrés nélkül: {jegy_ujra} (várt {new_grades})")
        ok(hazi_ujra == str(hazi_10),
           f"házi feladatok csempe szűrés nélkül: {hazi_ujra} (várt {hazi_10})")
        figy_ujra = " ".join(page.inner_text("#dashFigyelemLista").split())
        ok("Nincs" not in figy_ujra, f"a feed nem maradt üres: {figy_ujra[:80]}")
        jegy_ujra_feed = page.eval_on_selector_all(
            "#dashJegyLista .list-group-item", "els => els.length")
        ok(jegy_ujra_feed >= 3, f"a legutóbbi jegyek feed megint feltöltődött: {jegy_ujra_feed}")

        print("\n5) Tantárgyi átlagok a Statisztika fülön (#39)")
        page.click("#rewards-tab")
        page.wait_for_timeout(1500)
        # Új: a statisztika fülön betöltéskor nincs gyermek kiválasztva.
        page.select_option("#rewardFilterDiak", "")
        page.wait_for_timeout(400)
        ok(page.is_visible("#rewardNoDiakAlert") and not page.is_visible("#rewardContainer"),
           "üres gyermekválasztónál súgó látszik, a statisztika rejtve")
        page.select_option("#rewardFilterDiak", "Teszt Elek")
        page.wait_for_timeout(1500)
        ok(not page.is_visible("#rewardNoDiakAlert"), "kiválasztás után a súgó eltűnik")
        # Az átlagok kártya alapból zárt accordion: kinyitjuk.
        ok(not page.is_visible("#atlagokBody"), "az átlagok táblázat alapból zárva")
        page.click('#atlagokCard button[data-bs-target="#atlagokCollapse"]')
        page.wait_for_timeout(600)
        ok(page.is_visible("#atlagokBody"), "kinyitás után látszik a táblázat")
        fej = page.eval_on_selector_all("#atlagokHeadRow th", "els => els.map(e => e.innerText.trim())")
        testek = page.eval_on_selector_all("#atlagokBody tr",
                                           "rows => rows.map(r => r.innerText.replace(/\\s+/g, ' ').trim())")
        ok(len(fej) >= 4, f"a táblázat fejléce: {fej}")
        ok(any("Tantárgy" in f for f in fej), "van Tantárgy oszlop")
        ok(any(f.startswith("Összes") for f in fej), "van Összes oszlop")
        ok(not any(" 26" in f for f in fej),
           f"a hónap-oszlopokban nincs évszám: {fej}")
        idoszak = " ".join(page.inner_text("#atlagokIdoszak").split())
        ok("tanév" in idoszak and "időszak" in idoszak,
           f"az időszak/tanév felirat látszik: {idoszak}")
        mat = next((s for s in testek if s.startswith("Matematika")), "")
        fiz = next((s for s in testek if s.startswith("Fizika")), "")
        ok(bool(mat), f"Matematika sor: {mat}")
        ok(bool(fiz), f"Fizika sor: {fiz}")
        # Matematika: 5 (100%) + 3 (0%) -> súlyozva 5.0 ; Fizika: 4.0
        ok("5" in mat.split(), f"a Matematika összes átlaga 5: {mat}")
        ok("4" in fiz.split(), f"a Fizika átlaga 4: {fiz}")
        ok(any(s.startswith("Hónapok átlaga") for s in testek), "van havi teljes átlag lábléc")
        ok(any("4.67" in s for s in testek), f"a láblécben a teljes időszak átlaga: {testek[-1] if testek else ''}")

        print("\n5b) Kalkulátor: meglévő jegyek táblázata (#78) + több jegy/félévi cél (#101)")
        ok(page.input_value("#kalkTantargy") == "",
           "a tantárgy alapból nincs kiválasztva (üres a választó)")
        ok(page.eval_on_selector_all("#kalkJegyek tbody tr", "els => els.length") == 0,
           "kiválasztás nélkül nincs jegy-lista")
        page.select_option("#kalkTantargy", "Matematika")
        page.wait_for_timeout(900)
        kalk_sorok = page.eval_on_selector_all("#kalkJegyek tbody tr", "els => els.length")
        ok(kalk_sorok == 2, f"a kalkulátor kilistázza a Matematika jegyeit ({kalk_sorok} sor)")
        kalk_szoveg = " ".join(page.inner_text("#kalkJegyek").split())
        ok("Meglévő jegyek" in kalk_szoveg and "Jeles(5)" in kalk_szoveg,
           f"a jegyek fejléce és értéke is látszik: {kalk_szoveg[:120]}")
        kalk_suly = page.eval_on_selector_all("#kalkJegyek tbody tr",
                                             "rows => rows.map(r => r.innerText.replace(/\\s+/g, ' ').trim())")
        ok(any("100%" in s for s in kalk_suly), f"a súly is megjelenik: {kalk_suly}")
        page.click("#btnKalkVarhatoAdd")
        page.select_option("#kalkFelevi", "5")
        page.wait_for_timeout(900)
        kalk_eredmeny = " ".join(page.inner_text("#kalkEredmeny").split())
        ok("félévi" in kalk_eredmeny.lower(),
           f"a félévi cél eredménye is megjelenik: {kalk_eredmeny[:160]}")
        ok(page.eval_on_selector_all("#kalkVarhatoLista .kalk-varhato-sor",
                                     "els => els.length") == 2,
           "a „további jegy” gomb második sort ad")

        print("\n6) Mobil nézet: két bontás kapcsolóval (#39)")
        mctx = browser.new_context(viewport={"width": 393, "height": 873})
        mp = mctx.new_page()
        mp.clock.install(time=datetime(today.year, today.month, today.day, 12, 0))
        mp.goto(base, wait_until="networkidle")
        mp.click("#rewards-tab")
        mp.wait_for_timeout(1500)
        ok(mp.input_value("#rewardFilterDiak") == "",
           "mobilon a statisztika gyermek-szűrője betöltéskor üres")
        mp.select_option("#rewardFilterDiak", "Teszt Elek")
        mp.wait_for_timeout(1500)
        mp.click('#atlagokCard button[data-bs-target="#atlagokCollapse"]')
        mp.wait_for_timeout(600)
        ok(mp.is_visible("#atlagokMobil"), "mobilon a fa látszik")
        ok(not mp.is_visible("#atlagokTable"), "a táblázat mobilon rejtve")
        ok(mp.is_visible("#atlagNezetKapcsolo"), "van nézet-kapcsoló")

        teljes = " ".join(mp.inner_text("#atlagokMobil > div").split())
        ok("Teljes átlag" in teljes and "4.67" in teljes,
           f"fő sor: teljes átlag: {teljes}")

        # 1. nézet (alap): havi bontás — hónapok, bennük tantárgyak
        honapok_szoveg = mp.eval_on_selector_all(
            "#atlagokMobil .accordion .accordion-item > h2 > button",
            "els => els.filter(e => e.offsetParent !== null).map(e => e.innerText.replace(/\\s+/g, ' ').trim())")
        ok(len(honapok_szoveg) == 2, f"havi bontás: {honapok_szoveg}")
        ok(any("október" in h and "3" in h for h in honapok_szoveg),
           f"október havi teljes átlaga 3: {honapok_szoveg}")
        ok(any("november" in h and "4.67" in h for h in honapok_szoveg),
           f"november havi teljes átlaga (súlyozva 4.67): {honapok_szoveg}")

        mp.evaluate("""() => {
            const els = Array.from(document.querySelectorAll(
                '#atlagokMobil .accordion .accordion-item > h2 > button'));
            const v = els.find(function (e) { return e.offsetParent !== null; });
            if (v) v.click();
        }""")
        mp.wait_for_timeout(600)
        tantargy_szoveg = mp.eval_on_selector_all(
            "#atlagokMobil .accordion .accordion-item > .accordion-collapse > .accordion-body",
            "els => els.filter(e => e.offsetParent !== null).map(e => e.innerText.replace(/\\s+/g, ' ').trim())")
        ok(any("Matematika 3 (1)" in t for t in tantargy_szoveg),
           f"havi tantárgyi átlag: {tantargy_szoveg}")

        # 2. nézet: tantárgy szerint (teljes időszak)
        mp.click('#atlagNezetKapcsolo .btn[data-nezet="tantargy"]')
        mp.wait_for_timeout(500)
        ok(len(mp.query_selector_all("#atlagokMobil .accordion")) == 0,
           "a tantárgy-nézetben nincsenek hónap-accordionok")
        tant_blokk = mp.eval_on_selector_all(
            "#atlagokMobil .border.rounded div", "els => els.map(e => e.innerText.replace(/\\s+/g, ' ').trim())")
        ok(any("Matematika 5 (2)" in t for t in tant_blokk),
           f"tantárgyak szerint (teljes időszak): {tant_blokk}")
        teljes2 = " ".join(mp.inner_text("#atlagokMobil > div").split())
        ok("Teljes átlag" in teljes2 and "4.67" in teljes2,
           f"a teljes átlag a 2. nézetben is ott van: {teljes2}")

        mp.eval_on_selector("#atlagokCard", "el => el.scrollIntoView({block: 'start'})")
        mp.wait_for_timeout(400)
        mp.screenshot(path=str(work / "mobil_atlagok.png"))
        print("SCREENSHOT (mobil):", work / "mobil_atlagok.png")
        mctx.close()

        print("\n7) Tanév-választó (Kaneo #40): alapérték és 'Összes tanév' mód")
        ok(page.input_value("#tanevValaszto") == tanev_of(today),
           f"alapból az aktuális tanév: {page.input_value('#tanevValaszto')}")
        opts = page.eval_on_selector_all("#tanevValaszto option",
                                         "els => els.map(e => e.textContent.trim())")
        ok(any("(aktuális)" in o for o in opts), f"az aktuális tanév jelölve: {opts}")
        page.select_option("#tanevValaszto", "")
        page.wait_for_timeout(1500)
        page.click("#attekintes-tab")
        page.wait_for_timeout(1200)
        kartya2 = page.eval_on_selector_all(
            "#dashboardDiakCards .card",
            "els => els.map(e => e.innerText.replace(/\\s+/g, ' ').trim())")
        ok(kartya2 and " - " in (" " + kartya2[0] + " ") and "4.67" not in kartya2[0],
           f"'Összes tanév' módban nincs átlag: {kartya2[0] if kartya2 else ''}")
        osszesito = " ".join(page.inner_text("#diakOsszesitoInfo").split())
        ok("válassz tanévet" in osszesito,
           f"a szakasz fejléce kéri a tanévválasztást: {osszesito}")
        page.click("#rewards-tab")
        page.wait_for_timeout(1500)
        ok(page.inner_text("#atlagokIdoszak").strip().startswith("Összes tanév"),
           f"az átlagok fejléce jelzi az összes tanévet: {page.inner_text('#atlagokIdoszak')}")
        ok(page.inner_text("#atlagokBody").strip().startswith("Az átlagokhoz"),
           "az átlagokhoz tanévválasztást kér")
        ok(page.inner_text("#statAtlag").strip() == "–",
           f"'Összes tanév' módban a KPI-átlag sem szám: {page.inner_text('#statAtlag')}")
        page.select_option("#tanevValaszto", tanev_of(today))
        page.wait_for_timeout(1200)

        page.screenshot(path=str(work / "dashboard.png"))
        print("SCREENSHOT:", work / "dashboard.png")
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
