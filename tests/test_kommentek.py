# -*- coding: utf-8 -*-
"""Saját megjegyzések (Kaneo #46).

API + adatbázis: eseményhez és üzenethez is lehet megjegyzést fűzni, a kulcs
tartalom-alapú (a szinkron újraírja az id-ket), a darabszám megjelenik a
listákban, a törlés működik, a séma migrálódik.
Böngésző: az események sorában lévő gomb modálja menti és visszaolvassa a
megjegyzést; az üzenet részleteinél is működik a hozzáfűzés.
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
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="kreta_komment_"))
db_path = work / "kreta_adatok.db"
sqlite3.connect(str(db_path)).close()
(work / "config.json").write_text(json.dumps({
    "SCHEDULER": {"ENABLED": False},
    "STUDENTS": [{"diak_nev": "Teszt Elek", "active": False}],
}, ensure_ascii=False), encoding="utf-8")

os.environ.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db_path),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": str(work / "csat"),
    "NTFY_TOPIC": "",
})
os.environ.pop("KRETA_TEST_SKIP_BOOTSTRAP", None)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as kreta  # noqa: E402

kreta.init_db_extensions()
_hibak = []


def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)


today = kreta.kreta_tanev.today()
BEJ = today.strftime("%Y. %m. %d.")
TANEV = kreta.kreta_tanev.current_tanev(today)

conn = kreta.get_db_connection()
cur = conn.cursor()
cur.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " suly_szazalek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " tanev, tanev_forras) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
    ("Teszt Elek", "Értékelés", "Matematika", "Jeles(5)", 5, 100,
     BEJ, "", "Tanár", "Évközi jegy", "Írásbeli", "Téma", "", "", TANEV, "szamitott"))
event_id = cur.lastrowid
cur.execute(
    "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg,"
    " csatolmany_nev, csatolmany_utvonal, tanev, tanev_forras)"
    " VALUES (?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Elek", "U-1", "Iskola", "Teszt üzenet", BEJ + " 10:00", "Szöveg", "", "",
     TANEV, "szamitott"))
conn.commit()
conn.close()

cl = kreta.app.test_client()


def esemeny_row():
    data = cl.get("/api/esemenyek").get_json() or []
    return next((x for x in data if x.get("id") == event_id), {})


def uzenet_row():
    data = cl.get("/api/uzenetek").get_json() or []
    return next((x for x in data if x.get("targy") == "Teszt üzenet"), {})


print("\n1) A séma és a kulcsok")
conn = kreta.get_db_connection()
cols = [r[1] for r in conn.execute("PRAGMA table_info(kommentek)")]
conn.close()
ok({"cel_tipus", "cel_kulcs", "szoveg", "szerzo", "letrehozva"} <= set(cols),
   f"kommentek séma: {cols}")
ev = esemeny_row()
ok(str(ev.get("komment_kulcs", "")).startswith("e:"),
   f"az esemény kap stabil kulcsot: {ev.get('komment_kulcs')}")
ok(ev.get("komment_db") == 0, "kezdetben 0 megjegyzés")
uz = uzenet_row()
ok(uz.get("komment_kulcs") == "m:U-1", f"az üzenet kulcsa az uzenet_id: {uz.get('komment_kulcs')}")

print("\n2) Hozzáfűzés eseményhez")
r = cl.post("/api/kommentek", json={"cel_tipus": "esemeny", "cel_kulcs": ev["komment_kulcs"],
                                    "diak_nev": "Teszt Elek", "szoveg": "Első megjegyzés"})
ok(r.status_code == 200 and (r.get_json() or {}).get("id"), f"POST: HTTP {r.status_code}")
lista = cl.get(f"/api/kommentek?cel_tipus=esemeny&cel_kulcs={ev['komment_kulcs']}").get_json()
ok(len(lista) == 1 and lista[0]["szoveg"] == "Első megjegyzés", f"visszaolvasás: {lista}")
ok(lista[0]["szerzo"] == "Szülő", f"alap szerző: {lista[0].get('szerzo')}")
ok(esemeny_row().get("komment_db") == 1, "a lista darabszáma 1")

print("\n3) Hozzáfűzés üzenethez")
r = cl.post("/api/kommentek", json={"cel_tipus": "uzenet", "cel_kulcs": uz["komment_kulcs"],
                                    "diak_nev": "Teszt Elek", "szoveg": "Üzenethez fűzött"})
ok(r.status_code == 200, f"POST: HTTP {r.status_code}")
ok(uzenet_row().get("komment_db") == 1, "az üzenet listában is látszik a darabszám")

print("\n4) Validáció")
r = cl.post("/api/kommentek", json={"cel_tipus": "esemeny", "cel_kulcs": ev["komment_kulcs"],
                                    "szoveg": "   "})
ok(r.status_code == 400, f"üres szöveg: HTTP {r.status_code}")
r = cl.post("/api/kommentek", json={"cel_tipus": "ismeretlen", "cel_kulcs": "e:x", "szoveg": "x"})
ok(r.status_code == 400, f"ismeretlen cél-típus: HTTP {r.status_code}")
r = cl.post("/api/kommentek", json={"cel_tipus": "esemeny", "cel_kulcs": "", "szoveg": "x"})
ok(r.status_code == 400, f"hiányzó kulcs: HTTP {r.status_code}")
r = cl.post("/api/kommentek", json={"cel_tipus": "esemeny", "cel_kulcs": ev["komment_kulcs"],
                                    "szoveg": "x" * 2001})
ok(r.status_code == 400, f"túl hosszú szöveg: HTTP {r.status_code}")

print("\n5) Törlés")
kid = lista[0]["id"]
r = cl.delete(f"/api/kommentek/{kid}")
ok(r.status_code == 200, f"DELETE: HTTP {r.status_code}")
ok(esemeny_row().get("komment_db") == 0, "a darabszám visszaáll 0-ra")
r = cl.delete(f"/api/kommentek/{kid}")
ok(r.status_code == 404, f"második törlés: HTTP {r.status_code}")

print("\n6) A szinkron újraírja az id-t, a megjegyzés megmarad")
cl.post("/api/kommentek", json={"cel_tipus": "esemeny", "cel_kulcs": ev["komment_kulcs"],
                                "szoveg": "Túlélő megjegyzés"})
conn = kreta.get_db_connection()
cur = conn.cursor()
cur.execute(
    "DELETE FROM esemenyek WHERE id = ?", (event_id,))
# ugyanaz a tartalom, új id (a teljes cserés szinkron így jár el)
cur.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " suly_szazalek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " tanev, tanev_forras) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
    ("Teszt Elek", "Értékelés", "Matematika", "Jeles(5)", 5, 100,
     BEJ, "", "Tanár", "Évközi jegy", "Írásbeli", "Téma", "", "", TANEV, "szamitott"))
event_id = cur.lastrowid
conn.commit()
conn.close()
uj = esemeny_row()
ok(uj.get("komment_kulcs") == ev["komment_kulcs"], "a kulcs ugyanaz maradt")
ok(uj.get("komment_db") == 1, f"a megjegyzés túlélte az újraírást: {uj.get('komment_db')}")

print("\n7) Régi DB: a kommentek tábla migrálódik")
conn = kreta.get_db_connection()
conn.execute("DROP TABLE kommentek")
conn.commit()
ok(kreta._missing_tables(conn, ("kommentek",)) == ["kommentek"], "a tábla hiányzik")
kreta.ensure_run_tables(conn)
ok(kreta._missing_tables(conn, ("kommentek",)) == [], "ensure_run_tables létrehozza")
conn.close()

print("\n8) Böngésző: esemény- és üzenet-megjegyzés a felületen")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


port = free_port()
env = os.environ.copy()
env.update({"KRETA_HOST": "127.0.0.1", "KRETA_PORT": str(port), "KRETA_SERVER": "flask",
            "KRETA_DEBUG": "0", "PYTHONIOENCODING": "utf-8"})
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
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 950})
        page.goto(base, wait_until="networkidle")
        page.wait_for_timeout(1200)
        page.click("#esemenyek-tab")
        page.wait_for_timeout(1000)
        ok(page.is_visible(".btn-show-komment"), "az eseménysorban van megjegyzés-gomb")
        page.click(".btn-show-komment")
        page.wait_for_timeout(600)
        ok(page.is_visible("#kommentModal"), "a megjegyzés-modál megnyílt")
        page.fill("#kommentUj", "UI-ból fűzött megjegyzés")
        page.click("#btnKommentMent")
        page.wait_for_timeout(800)
        lista_szoveg = page.inner_text("#kommentLista")
        ok("UI-ból fűzött megjegyzés" in lista_szoveg, f"a megjegyzés mentődött: {lista_szoveg[:80]}")
        ok("1" in page.inner_text(".btn-show-komment"), "a gombon a darabszám frissült")
        page.click('#kommentModal .modal-footer .btn-secondary')
        page.wait_for_timeout(500)

        page.click("#uzenetek-tab")
        page.wait_for_timeout(800)
        page.click(".btn-read-msg")
        page.wait_for_timeout(600)
        ok(page.is_visible("#uzenetKommentLista"), "az üzenet-modálban van megjegyzés-blokk")
        page.fill("#uzenetKommentUj", "Üzenet-UI megjegyzés")
        page.click("#btnUzenetKommentMent")
        page.wait_for_timeout(800)
        ok("Üzenet-UI megjegyzés" in page.inner_text("#uzenetKommentLista"),
           "az üzenet-megjegyzés mentődött")

        page.screenshot(path=str(work / "kommentek.png"))
        print("SCREENSHOT:", work / "kommentek.png")
        b.close()
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
