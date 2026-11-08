# -*- coding: utf-8 -*-
"""
Üzemeltetési ellenőrzések (Kaneo #90).

- `tools/backup_restore_check.py`: a legfrissebb mentés izolált visszaállítása,
  integrity_check, manifest-egyezés, elavult/sérült mentés detektálása.
- `tools/live_smoke.py`: /health + /api/sync/status, utolsó futás kora, hibák.
"""
import base64
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import backup_restore_check as brc  # noqa: E402
import live_smoke  # noqa: E402

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


def keszit_db(path, sorok=3):
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE esemenyek (id INTEGER PRIMARY KEY AUTOINCREMENT, diak_nev TEXT);
    CREATE TABLE uzenetek (id INTEGER PRIMARY KEY AUTOINCREMENT, targy TEXT);
    CREATE TABLE hianyzasok (id INTEGER PRIMARY KEY AUTOINCREMENT, datum TEXT);
    CREATE TABLE igazolasok (id INTEGER PRIMARY KEY AUTOINCREMENT, tipus TEXT);
    CREATE TABLE orarend (id INTEGER PRIMARY KEY AUTOINCREMENT, tantargy TEXT);
    CREATE TABLE kifizetesek (id INTEGER PRIMARY KEY AUTOINCREMENT, osszeg INTEGER);
    CREATE TABLE sync_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT);
    CREATE TABLE kommentek (id INTEGER PRIMARY KEY AUTOINCREMENT, szoveg TEXT);
    CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    for i in range(sorok):
        conn.execute("INSERT INTO esemenyek (diak_nev) VALUES (?)", (f"Diak{i}",))
        conn.execute("INSERT INTO uzenetek (targy) VALUES (?)", (f"Uzenet{i}",))
        conn.execute("INSERT INTO hianyzasok (datum) VALUES (?)", ("2026-10-05",))
        conn.execute("INSERT INTO orarend (tantargy) VALUES (?)", ("Matematika",))
    conn.commit()
    conn.close()


def mentes_keszit(backup_dir, nev, forras, manifest=None):
    cel = Path(backup_dir) / nev
    shutil.copy2(forras, cel)
    if manifest is not None:
        (Path(str(cel).replace(".db", ".counts.json"))).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return cel


work = Path(tempfile.mkdtemp(prefix="kreta_ops_"))
try:
    print("1) Restore-ellenőrzés: érvényes mentés + manifest")
    live = work / "live.db"
    keszit_db(live)
    backup_dir = work / "backup"
    backup_dir.mkdir()
    mentes = mentes_keszit(
        backup_dir, "kreta_adatok_2026-11-08_030000.db", live,
        manifest={"esemenyek": 3, "uzenetek": 3, "hianyzasok": 3,
                  "orarend": 3, "sync_runs": 0})
    ok_osszes, uzenetek = brc.check(str(backup_dir), str(live))
    ok(ok_osszes, f"érvényes mentés elfogadva ({uzenetek[-1]})")
    ok(any("integrity_check: ok" in u for u in uzenetek), "integrity_check = ok")
    ok(any("manifest egyezik" in u for u in uzenetek), "a manifest pontosan egyezik")

    print("\n2) Sérült / hiányzó / elavult mentés")
    serult = backup_dir / "kreta_adatok_2026-11-09_030000.db"
    serult.write_bytes(b"nem sqlite adat" * 100)
    ok_osszes, uzenetek = brc.check(str(backup_dir), str(live))
    ok(not ok_osszes and any(("integrity" in u.lower() or "nem nyitható" in u)
                             for u in uzenetek),
       f"sérült mentés -> hiba {uzenetek[-1]}")
    serult.unlink()
    mentes.unlink()
    (Path(str(mentes).replace(".db", ".counts.json"))).unlink()
    ok_osszes, uzenetek = brc.check(str(backup_dir), str(live))
    ok(not ok_osszes and "nincs mentés" in uzenetek[0], "nincs mentés -> hiba")

    mentes = mentes_keszit(backup_dir, "kreta_adatok_2026-11-08_030000.db", live)
    regi = time.time() - 5 * 86400
    os.utime(mentes, (regi, regi))
    ok_osszes, uzenetek = brc.check(str(backup_dir), str(live), max_age_days=2)
    ok(not ok_osszes and any("túl régi" in u for u in uzenetek), "elavult mentés -> hiba")
    os.utime(mentes, None)

    print("\n3) Manifest-eltérés")
    mentes_keszit(backup_dir, "kreta_adatok_2026-11-10_030000.db", live,
                  manifest={"esemenyek": 99})
    ok_osszes, uzenetek = brc.check(str(backup_dir), str(live))
    ok(not ok_osszes and any("sorszám-eltérés" in u for u in uzenetek),
       "manifest-eltérés -> hiba")

    print("\n4) Élő füstteszt (fake HTTP szerver)")
    allapot = {
        "health": {"status": "ok", "version": "v2.1.2"},
        "sync": {"running": False, "scheduler": {"last_status": "done",
                                                 "last_run": "2026-11-08 09:00:00"}},
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.startswith("/health"):
                body = allapot["health"]
            elif self.path.startswith("/api/sync/status"):
                if self.headers.get("Authorization") != "Basic " + base64.b64encode(
                        b"u:p").decode():
                    self.send_response(401)
                    self.end_headers()
                    return
                body = allapot["sync"]
            else:
                self.send_response(404)
                self.end_headers()
                return
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"

    # A "last_run" a valós időhöz képest friss legyen a teszthez.
    from datetime import datetime, timedelta
    allapot["sync"]["scheduler"]["last_run"] = (
        datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    ok_osszes, uzenetek = live_smoke.check(url, "u", "p")
    ok(ok_osszes, f"friss futás + done -> OK ({uzenetek[-1]})")

    allapot["sync"]["scheduler"]["last_status"] = "error"
    ok_osszes, uzenetek = live_smoke.check(url, "u", "p")
    ok(not ok_osszes and any("error" in u[1] for u in uzenetek),
       f"last_status=error -> hiba {uzenetek}")

    allapot["sync"]["scheduler"]["last_status"] = "done"
    allapot["sync"]["scheduler"]["last_run"] = (
        datetime.now() - timedelta(hours=40)).strftime("%Y-%m-%d %H:%M:%S")
    ok_osszes, uzenetek = live_smoke.check(url, "u", "p", max_age_hours=26)
    ok(not ok_osszes and any("túl régi" in u[1] for u in uzenetek),
       f"40 órás futás -> hiba {uzenetek}")

    allapot["health"] = {"status": "hiba"}
    ok_osszes, uzenetek = live_smoke.check(url, "u", "p")
    ok(not ok_osszes and any("/health HIBA" in u[1] for u in uzenetek),
       f"rossz /health -> hiba {uzenetek}")

    allapot["health"] = {"status": "ok", "version": "v2.1.2"}
    allapot["sync"]["scheduler"]["last_run"] = (
        datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    allapot["sync"]["running"] = True
    ok_osszes, uzenetek = live_smoke.check(url, "u", "p")
    ok(ok_osszes and any("éppen fut" in u[1] for u in uzenetek),
       f"futó szinkron -> OK {uzenetek}")

    ok_osszes, uzenetek = live_smoke.check(url, "", "")
    ok(not ok_osszes, f"auth nélkül a védett végpont hibát jelez {uzenetek}")
    srv.shutdown()

    print("\n5) CI workflow és dokumentáció")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    ok("live_smoke.py" in ci and "KRETA_URL" in ci, "a CI éjszakai füsttesztet futtat")
    ok("backup_restore_check.py" in (ROOT / "docs" / "DOKUMENTACIO.md").read_text(
        encoding="utf-8"), "a restore-teszt dokumentálva")
finally:
    shutil.rmtree(work, ignore_errors=True)

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
