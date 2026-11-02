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
from datetime import date, timedelta
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


today = date.today()
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
        " suly_szazalek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
        ("Teszt Elek", tipus, tantargy, ertek, szam, suly, hu(bej), hu(hatarido) if hatarido else "",
         "Tanár", "Évközi jegy", "Írásbeli", tema, "", ""))


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
# Üzenetek: 2 friss, 1 régi
for i, nap in enumerate([1, 3, 30]):
    conn.execute(
        "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg)"
        " VALUES (?,?,?,?,?,?)",
        ("Teszt Elek", str(i), "Iskola", f"Üzenet {i}",
         f"{hu(today - timedelta(days=nap))} 10:00", "Szöveg"))
conn.commit()
conn.close()

# Várt értékek (ugyanaz a szabály, mint a frontenden)
week_deadlines = sum(
    1 for t, h in [("Házi feladat", today),
                   ("Bejelentett számonkérés", monday + timedelta(days=min(6, max(0, (today - monday).days + 1)))),
                   ("Házi feladat", today + timedelta(days=10)),
                   ("Házi feladat", today - timedelta(days=10))]
    if monday <= h <= sunday)
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
        page.goto(base, wait_until="networkidle")
        page.wait_for_timeout(1200)

        print("\n1) Áttekintés fül (alapértelmezett)")
        ok(page.is_visible("#attekintes-pane"),
           "az Áttekintés fül aktív betöltéskor")
        ok(page.get_attribute("#attekintes-tab", "class").find("active") >= 0,
           "az Áttekintés tab 'active'")
        ok(not page.is_visible("#accordionFilterBlock"),
           "a szűrőpanel a dashboardon nem látszik")

        print("\n2) Csempék számai")
        hat = page.inner_text("#tileHataridokSzam").strip()
        jegy = page.inner_text("#tileUjJegyekSzam").strip()
        uzen = page.inner_text("#tileUjUzenetekSzam").strip()
        ok(hat == str(week_deadlines), f"heti határidők: {hat} (várt {week_deadlines})")
        ok(jegy == str(new_grades), f"új jegyek: {jegy} (várt {new_grades})")
        ok(uzen == str(new_messages), f"új üzenetek: {uzen} (várt {new_messages})")
        page.screenshot(path=str(work / "attekintes.png"))
        print("SCREENSHOT (áttekintés):", work / "attekintes.png")


        print("\n3) Csempe -> szűrt eseménylista")
        page.click("#tileUjJegyek")
        page.wait_for_timeout(1200)
        ok(page.is_visible("#esemenyek-pane"), "az Események fül megnyílt")
        ok(page.is_visible("#accordionFilterBlock"), "a szűrőpanel itt látszik")
        ok(page.input_value("#filterTipus") == "Értékelés", "típus = Értékelés")
        rows = page.eval_on_selector_all("#esemenyekTable tbody tr",
                                         "rows => rows.filter(r => r.querySelectorAll('td').length > 1).length")
        ok(rows == new_grades, f"a listában {rows} jegy (várt {new_grades}, a régi kimaradt)")

        print("\n4) Vissza az áttekintésre")
        page.click(".btn-back-dashboard")
        page.wait_for_timeout(500)
        ok(page.is_visible("#attekintes-pane"), "visszalépés a dashboardra")
        ok(not page.is_visible("#accordionFilterBlock"), "a szűrőpanel ismét rejtve")

        print("\n5) Tantárgyi átlagok a Statisztika fülön (#39)")
        page.click("#rewards-tab")
        page.wait_for_timeout(1500)
        fej = page.eval_on_selector_all("#atlagokHeadRow th", "els => els.map(e => e.innerText.trim())")
        testek = page.eval_on_selector_all("#atlagokBody tr",
                                           "rows => rows.map(r => r.innerText.replace(/\\s+/g, ' ').trim())")
        ok(len(fej) >= 4, f"a táblázat fejléce: {fej}")
        ok(any("Tantárgy" in f for f in fej), "van Tantárgy oszlop")
        ok(any("Összes" in f for f in fej), "van Összes oszlop")
        mat = next((s for s in testek if s.startswith("Matematika")), "")
        fiz = next((s for s in testek if s.startswith("Fizika")), "")
        ok(bool(mat), f"Matematika sor: {mat}")
        ok(bool(fiz), f"Fizika sor: {fiz}")
        # Matematika: 5 (100%) + 3 (0%) -> súlyozva 5.0 ; Fizika: 4.0
        ok("5" in mat.split(), f"a Matematika összes átlaga 5: {mat}")
        ok("4" in fiz.split(), f"a Fizika átlaga 4: {fiz}")
        ok(any(s.startswith("Összesen") for s in testek), "van Összesen sor")

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
