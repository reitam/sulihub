# -*- coding: utf-8 -*-
"""
KRÉ-126 regressziós teszt: a részletek modál a **naptárból** és az
**esemény-táblából** ugyanazt a tagolt szerkezetet adja.

Hiba volt: a naptár a régi, nyers szöveget adta át, és a leírásban lévő
kettőspont (pl. „… a tanult módon: módja, ideje …”) miatt a szöveg címke–érték
sorként jelent meg, összetörve a modál elrendezését.
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
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

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


LEIRAS = ("5 igét meghatározni a tanult módon: módja, ideje, száma és személye, "
          "igefajta meghatározása.")
HATARIDO = date.today() + timedelta(days=3)
HATARIDO_HU = f"{HATARIDO.year}. {HATARIDO.month:02d}. {HATARIDO.day:02d}."

work = Path(tempfile.mkdtemp(prefix="kreta_reszletek_"))
db = work / "kreta_adatok.db"
(work / "config.json").write_text(
    json.dumps({"SCHEDULER": {"ENABLED": False}}), encoding="utf-8")

# A teljes sémát a scraper init-db-je hozza létre (a valósághű oszlopokkal).
schema_env = os.environ.copy()
schema_env.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
})
subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=schema_env, capture_output=True, timeout=120)

today = date.today()
tanev = f"{today.year}/{today.year + 1}" if today.month >= 9 else f"{today.year - 1}/{today.year}"
conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz, suly_szazalek,"
    " tanev, tanev_forras)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Elek", "Házi feladat", "Magyar nyelv", "", 0, "2026. 11. 05.",
     HATARIDO_HU, "Szőke Gáborné", "", "", "", "", LEIRAS, 0, 0, tanev, "teszt"),
)
conn.commit()
conn.close()

(work / "config.json").write_text(
    json.dumps({"SCHEDULER": {"ENABLED": False}}), encoding="utf-8")

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

    MODAL_JS = """() => {
        const meta = Array.from(document.querySelectorAll('#detailsModal .reszletek-meta-item'))
            .map(el => ({
                cimke: (el.querySelector('.reszletek-label') || {}).textContent || '',
                ertek: (el.querySelector('.reszletek-ertek') || {}).textContent || ''
            }));
        const leiras = Array.from(document.querySelectorAll('#detailsModal .reszletek-leiras-szoveg'))
            .map(el => el.textContent.trim());
        return {
            title: (document.querySelector('#detailsModalTitle') || {}).textContent.trim(),
            hero: !!document.querySelector('#detailsModal .reszletek-hero'),
            meta: meta,
            leiras: leiras
        };
    }"""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1300, "height": 900})
        page.goto(base + "/", wait_until="networkidle")

        print("1) Naptárból nyitott részletek")
        page.click("#naptar-tab")
        page.wait_for_selector(".fc-event", timeout=20000)
        page.wait_for_timeout(1200)
        events = page.query_selector_all(".fc-event")
        target = None
        for ev in events:
            if "Magyar nyelv" in (ev.inner_text() or ""):
                target = ev
                break
        ok(target is not None, "a házi feladat esemény látszik a naptárban")
        calendar = {}
        if target:
            target.click()
            page.wait_for_selector("#detailsModal.show", timeout=15000)
            page.wait_for_timeout(400)
            calendar = page.evaluate(MODAL_JS)
            page.screenshot(path=str(work / "naptar_modál.png"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(700)

        ok(calendar.get("title") == "Házi feladat",
           f"a modál címe a típus: {calendar.get('title')!r}")
        ok(calendar.get("hero") is True, "van hero (tantárgy + jelvények)")
        labels = [m.get("cimke") for m in calendar.get("meta") or []]
        ok(any("Bejegyzés" in (l or "") for l in labels),
           f"a meta sorban ott a bejegyzés dátuma: {labels}")
        ok(not any("módon" in (m.get("ertek") or "") for m in calendar.get("meta") or []),
           "a leírás NEM került a címke–érték sorok közé")
        leiras = calendar.get("leiras") or []
        ok(len(leiras) == 1, f"egy leírás-blokk: {len(leiras)}")
        ok(leiras and "módon: módja, ideje" in leiras[0],
           f"a leírás a saját blokkjában, kettősponttal együtt: {leiras[0][:60]!r}...")

        print("\n2) Ugyanaz az esemény az esemény-táblából")
        page.click("#esemenyek-tab")
        page.wait_for_timeout(1000)
        page.click("#headingFilter button")
        page.wait_for_timeout(500)
        page.select_option("#filterTipus", "Házi feladat")
        page.wait_for_timeout(1800)

        table = {}
        buttons = page.query_selector_all("#esemenyek-pane .btn-show-details")
        for b in buttons:
            row_text = b.evaluate("el => { const tr = el.closest('tr'); return tr ? tr.innerText : ''; }")
            if "Magyar nyelv" in row_text:
                b.click()
                page.wait_for_selector("#detailsModal.show", timeout=15000)
                page.wait_for_timeout(400)
                table = page.evaluate(MODAL_JS)
                break

        ok(bool(table), "a táblából is megnyílt a részletek modál")
        ok(table.get("title") == calendar.get("title"),
           f"ugyanaz a cím: {table.get('title')!r} / {calendar.get('title')!r}")
        ok(table.get("leiras") == calendar.get("leiras"),
           "a leírás-blokk szövege azonos a két nézetben")
        ok(not any("módon" in (m.get("ertek") or "") for m in table.get("meta") or []),
           "a táblában sem kerül a leírás a meta sorokba")

        browser.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    shutil.rmtree(work, ignore_errors=True)

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
