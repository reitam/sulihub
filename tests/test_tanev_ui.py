# -*- coding: utf-8 -*-
"""Tanév-UI bugfixek valódi böngészőben (Kaneo #51, #52, #53).

- #51: tanévváltás után a dashboard csempéi azonnal frissülnek (nincs F5),
  akkor is, ha az esemény-válasz lassabb az üzenet-válasznál;
- #52: létezik „Tanév lezárása” gomb, és a lezárt (előző) tanévvel hívja a
  `/api/sync/start` végpontot;
- #53: a dátumválasztók a kiválasztott tanév határain belül maradnak.
"""
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_hibak = []
TODAY = date(2026, 11, 3)
AKTUALIS = "2026/2027"
ELOZO = "2025/2026"


def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


work = Path(tempfile.mkdtemp(prefix="kreta_tanev_ui_"))
db = work / "kreta_adatok.db"
(work / "config.json").write_text(json.dumps({
    "ENABLE_REWARDS": True,
    "SCHEDULER": {"ENABLED": False},
    "STUDENTS": [{"diak_nev": "Teszt Elek", "enable_rewards": True, "active": False}],
}, ensure_ascii=False), encoding="utf-8")

env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(work), "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"), "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_HOST": "127.0.0.1", "KRETA_SERVER": "flask", "KRETA_DEBUG": "0",
    "PYTHONIOENCODING": "utf-8", "KRETA_TODAY": TODAY.isoformat(),
})
env.pop("KRETA_CSATOLMANYOK_DIR", None)
env.pop("KRETA_ZARO_TANEV", None)
subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

conn = sqlite3.connect(db)


def add_event(tipus, tantargy, ertek, szam, bej, hatarido, tanev):
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " suly_szazalek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
        " tanev, tanev_forras) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
        ("Teszt Elek", tipus, tantargy, ertek, szam, 100, bej, hatarido,
         "Tanár", "Évközi jegy", "Írásbeli", "Téma", "", "", tanev, "szamitott"))


# Aktuális tanév: 1 jegy az elmúlt 7 napból + 1 heti határidő.
add_event("Értékelés", "Matematika", "Jeles(5)", 5, "2026. 11. 01.", "", AKTUALIS)
add_event("Házi feladat", "Magyar", "", 0, "2026. 11. 02.", "2026. 11. 05.", AKTUALIS)
# Előző tanév: 1 jegy (a záró gomb és a dátumkorlát miatt kell).
add_event("Értékelés", "Fizika", "Közepes(3)", 3, "2026. 03. 10.", "", ELOZO)
# Még korábbi tanév: a választóval ez is zárható legyen.
add_event("Értékelés", "Kémia", "Jó(4)", 4, "2025. 03. 10.", "", "2024/2025")
conn.commit()
conn.close()

port = free_port()
env["KRETA_PORT"] = str(port)
proc = subprocess.Popen([sys.executable, "app.py"], cwd=str(ROOT), env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = f"http://127.0.0.1:{port}"

try:
    for _ in range(80):
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
        page.wait_for_timeout(1500)

        print("\n1) #43: tanév-állapot (automatikus zárás/nyitás)")
        ok(page.query_selector("#btnTanevZaras") is None, "a kézi záró gomb megszűnt")
        ok(page.is_visible("#tanevAllapotBadge"), "az állapotjelző látszik")
        ok("nyitott" in page.inner_text("#tanevAllapotBadge"),
           f"az aktuális tanév nyitott: {page.inner_text('#tanevAllapotBadge')}")
        opts = page.eval_on_selector_all("#tanevValaszto option",
                                         "els => els.map(e => e.textContent.trim())")
        ok(any("(lezárt)" in o for o in opts), f"a lezárt tanév jelölve: {opts}")
        page.select_option("#tanevValaszto", ELOZO)
        page.wait_for_timeout(700)
        ok("lezárt" in page.inner_text("#tanevAllapotBadge"),
           f"a korábbi tanév lezárt: {page.inner_text('#tanevAllapotBadge')}")
        page.select_option("#tanevValaszto", AKTUALIS)
        page.wait_for_timeout(700)
        ok("nyitott" in page.inner_text("#tanevAllapotBadge"),
           f"visszaváltás után nyitott: {page.inner_text('#tanevAllapotBadge')}")

        print("\n2) #51: a csempék a friss adatból számolnak (versenyhelyzet)")
        page.wait_for_timeout(300)
        ok(page.inner_text("#tileHataridokSzam").strip() == "1",
           f"alap heti határidő: {page.inner_text('#tileHataridokSzam')}")
        page.select_option("#tanevValaszto", ELOZO)
        page.wait_for_timeout(1200)
        ok(page.inner_text("#tileHataridokSzam").strip() == "0",
           f"a korábbi tanévben nincs heti határidő: {page.inner_text('#tileHataridokSzam')}")
        page.select_option("#tanevValaszto", AKTUALIS)
        page.wait_for_timeout(1200)
        ok(page.inner_text("#tileHataridokSzam").strip() == "1",
           "visszaváltás után is friss a csempe")

        # Késleltetett esemény-válasz: az üzenet-válasz előbb érkezik.
        ctx = browser.new_context(viewport={"width": 1280, "height": 950})
        p2 = ctx.new_page()

        def slow_events(route):
            time.sleep(0.9)
            route.continue_()

        p2.route("**/api/esemenyek*", slow_events)
        p2.goto(base, wait_until="networkidle")
        p2.wait_for_timeout(3000)
        ok(p2.inner_text("#tileHataridokSzam").strip() == "1",
           f"késleltetett esemény-válasz után is friss a csempe: "
           f"{p2.inner_text('#tileHataridokSzam')}")
        ok(p2.inner_text("#tileUjJegyekSzam").strip() == "1",
           f"az új jegyek csempe is friss: {p2.inner_text('#tileUjJegyekSzam')}")
        ctx.close()

        print("\n3) #53: dátumválasztók a tanév határain belül")
        page.select_option("#tanevValaszto", ELOZO)
        page.wait_for_timeout(1000)
        ok(page.get_attribute("#filterBejKezdoDatum", "min") == "2025-09-01",
           f"min: {page.get_attribute('#filterBejKezdoDatum', 'min')}")
        ok(page.get_attribute("#filterBejKezdoDatum", "max") == "2026-08-31",
           f"max: {page.get_attribute('#filterBejKezdoDatum', 'max')}")
        ok(page.get_attribute("#rewardKezdoDatum", "max") == "2026-08-31",
           "a zsebpénz időszak is korlátozva")
        ok(page.get_attribute("#hianyzasHonap", "min") == "2025-09",
           f"hónapválasztó min: {page.get_attribute('#hianyzasHonap', 'min')}")
        page.eval_on_selector(
            "#filterBejKezdoDatum",
            "el => { el.value = '2026-11-02'; el.dispatchEvent(new Event('change', {bubbles: true})); }")
        page.wait_for_timeout(300)
        ok(page.input_value("#filterBejKezdoDatum") == "",
           f"a tanéven kívüli dátum törlődik: {page.input_value('#filterBejKezdoDatum')}")
        page.select_option("#tanevValaszto", "")
        page.wait_for_timeout(800)
        ok(page.get_attribute("#filterBejKezdoDatum", "min") is None,
           "Összes tanévnél nincs alsó korlát")
        ok(page.get_attribute("#hianyzasHonap", "max") is None,
           "Összes tanévnél nincs felső korlát")

        page.screenshot(path=str(work / "tanev_ui.png"))
        print("SCREENSHOT:", work / "tanev_ui.png")
        browser.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    shutil.rmtree(work, ignore_errors=True)

print("\n" + "=" * 60)
if _hibak:
    print(f"BUKOTT ({len(_hibak)} hiba)")
    sys.exit(1)
print("MINDEN ELLENŐRZÉS OK")
