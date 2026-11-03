# -*- coding: utf-8 -*-
"""Tanévzáró futás backendje (Kaneo #52) + a futásnapló cél-tanéve.

Éles KRÉTA nélkül: a KRETA_ZARO_TANEV env / a `tanev=` paraméter a teljes
(lezárt) tanév ablakát adja, a `/api/sync/start` csak lezárt tanévet fogad el,
és a `sync_runs` rögzíti a záró tanévet.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

work = tempfile.mkdtemp(prefix="kreta_zaro_")
db_path = os.path.join(work, "kreta_adatok.db")
sqlite3.connect(db_path).close()

os.environ.update({
    "KRETA_DATA_DIR": work,
    "KRETA_DB_FILE": db_path,
    "KRETA_CONFIG_FILE": os.path.join(work, "config.json"),
    "KRETA_LOG_FILE": os.path.join(work, "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csat"),
    "NTFY_TOPIC": "",
    "KRETA_TODAY": "2026-11-03",
})
os.environ.pop("KRETA_ZARO_TANEV", None)
Path(work, "config.json").write_text(json.dumps({
    "HEADLESS": True, "SYNC_MODE": "api",
    "STUDENTS": [{"diak_nev": "Teszt", "active": False}],
}, ensure_ascii=False), encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as kreta  # noqa: E402
import kreta_api_sync  # noqa: E402
import kreta_playwright as k  # noqa: E402
import kreta_tanev  # noqa: E402

kreta.init_db_extensions()
_hibak = []


def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)


print("\n1) zaro_tanev(): a KRETA_ZARO_TANEV értelmezése")
ok(kreta_tanev.zaro_tanev() == "", "alapból nincs záró futás")
os.environ["KRETA_ZARO_TANEV"] = "2025/2026"
ok(kreta_tanev.zaro_tanev() == "2025/2026", "érvényes tanév")
os.environ["KRETA_ZARO_TANEV"] = "2025/2028"
ok(kreta_tanev.zaro_tanev() == "", "hibás tanév (nem egymást követő év) -> üres")
os.environ.pop("KRETA_ZARO_TANEV", None)

print("\n2) tanev_api_window: a lezárt tanév teljes ablaka")
s, e = kreta_api_sync.tanev_api_window(date(2026, 11, 3), tanev="2025/2026")
ok((s, e) == (date(2025, 9, 1), date(2026, 8, 31)),
   f"teljes tanév: {s} .. {e}")
s, e = kreta_api_sync.tanev_api_window(date(2026, 11, 3), tanev="2026/2027")
ok((s, e) == (date(2026, 9, 1), date(2026, 11, 3)),
   f"az aktuális tanév a mai napig: {s} .. {e}")
os.environ["KRETA_ZARO_TANEV"] = "2025/2026"
s, e = kreta_api_sync.tanev_api_window(date(2026, 11, 3))
ok((s, e) == (date(2025, 9, 1), date(2026, 8, 31)),
   f"env-ből is a teljes tanév: {s} .. {e}")
s, e = k.evaluation_api_window("Teszt")
ok((s, e) == (date(2025, 9, 1), date(2026, 8, 31)),
   f"a scraper jegy-ablaka is: {s} .. {e}")
s, e = k.events_api_window("Teszt", "Házi feladat")
ok((s, e) == (date(2025, 9, 1), date(2026, 11, 29)),
   f"a +90 napos előretekintés a záró ablakon is: {e}")
os.environ.pop("KRETA_ZARO_TANEV", None)
s, e = k.hianyzas_api_window("Teszt")
ok((s, e) == (date(2026, 9, 1), date(2026, 11, 3)),
   f"záró env nélkül visszaáll az aktuális tanévre: {s} .. {e}")

print("\n3) A futásnapló rögzíti a záró tanévet")
conn = kreta.get_db_connection()
conn.execute("DELETE FROM sync_runs")
conn.commit()
conn.close()
rid = kreta.record_run_start("manual", "2026-11-03T10:00:00")
kreta.record_run_finish(rid, "done", tanev="2026/2027", tanev_zaro="2025/2026")
conn = kreta.get_db_connection()
row = conn.execute("SELECT tanev, tanev_zaro FROM sync_runs WHERE id = ?", (rid,)).fetchone()
conn.close()
ok(row and row[0] == "2026/2027" and row[1] == "2025/2026",
   f"sync_runs.tanev / tanev_zaro: {tuple(row) if row else None}")

print("\n4) /api/sync/start: érvénytelen és aktuális tanév -> 400")
calls = []
eredeti = kreta.start_sync
# A valódi start_sync szálat indítana (scraper) — itt csak a bekötést ellenőrizzük.
kreta.start_sync = lambda trigger="manual", tanev="": (calls.append((trigger, tanev)) or True)
try:
    cl = kreta.app.test_client()
    r = cl.post("/api/sync/start", json={"tanev": "2025/2028"})
    ok(r.status_code == 400, f"hibás tanév: HTTP {r.status_code}")
    r = cl.post("/api/sync/start", json={"tanev": "2026/2027"})
    ok(r.status_code == 400, f"az aktuális tanév nem zárható le: HTTP {r.status_code}")
    ok(calls == [], f"a hibás kérésre nem indul futás: {calls}")
    r = cl.post("/api/sync/start", json={"tanev": ""})
    ok(r.status_code == 200, f"üres tanév = normál szinkron: HTTP {r.status_code}")
    ok(calls == [("manual", "")], f"a normál futás a régi úton indul: {calls}")

    print("\n5) /api/sync/start: lezárt tanév -> tanévzáró indítás")
    calls.clear()
    r = cl.post("/api/sync/start", json={"tanev": "2025/2026"})
    data = r.get_json() or {}
    ok(r.status_code == 200 and data.get("status") == "started",
       f"a záró futás elindult: HTTP {r.status_code} {data}")
    ok(data.get("tanev") == "2025/2026", f"a válasz jelzi a tanévet: {data.get('tanev')}")
    ok(calls == [("manual", "2025/2026")], f"a start_sync a záró tanévvel hívódik: {calls}")

    print("\n6) /api/sync/status: zaro_tanev mező")
    st = cl.get("/api/sync/status").get_json() or {}
    ok("zaro_tanev" in st, f"a státusz tartalmazza a záró tanévet: {st.get('zaro_tanev')!r}")
finally:
    kreta.start_sync = eredeti

os.environ.pop("KRETA_TODAY", None)
shutil.rmtree(work, ignore_errors=True)

print("\n" + "=" * 60)
if _hibak:
    print(f"BUKOTT ({len(_hibak)} hiba)")
    sys.exit(1)
print("MINDEN ELLENŐRZÉS OK")
