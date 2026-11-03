# -*- coding: utf-8 -*-
"""
Saját (kézi) órarendi tételek — Kaneo #55.

Ellenőrzi a sémát, az érvényesség-típusokat (tanév / hét / egyedi), a heti
ismétlődés generálását, az egyetlen alkalom kivételét, a sorozat törlését,
a diák-szűrést és azt, hogy a KRÉTA szinkron nem érinti a saját táblákat.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = tempfile.mkdtemp(prefix="kreta_sajat_")
db = os.path.join(work, "kreta_adatok.db")
os.environ.update({
    "KRETA_DATA_DIR": work,
    "KRETA_DB_FILE": db,
    "KRETA_CONFIG_FILE": os.path.join(work, "config.json"),
    "KRETA_LOG_FILE": os.path.join(work, "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csat"),
    "KRETA_SCHEDULER_STATE_FILE": os.path.join(work, "scheduler_state.json"),
    "KRETA_TODAY": "2026-11-04",
})
sys.path.insert(0, str(ROOT))
import app as kreta  # noqa: E402
import kreta_sajat_orarend as sajat  # noqa: E402

kreta.init_db_extensions()
client = kreta.app.test_client()
_hibak = []


def ok(cond, msg):
    print(("  OK   " if cond else "  HIBA ") + msg)
    if not cond:
        _hibak.append(msg)


def post(payload):
    return client.post("/api/sajat_orarend", json=payload)


def calendar(diak="", start="2026-11-01", end="2026-12-31"):
    res = client.get(f"/api/orarend_naptar?diak={diak}&start={start}&end={end}")
    return res.status_code, res.get_json()


print("1) séma és üres lista")
ok(os.path.exists(db), "az adatbázis létrejött")
conn = sqlite3.connect(db)
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
conn.close()
ok({"sajat_orarend", "sajat_orarend_kivetel"} <= tables,
   f"a saját táblák létrejöttek ({sorted(tables & {'sajat_orarend', 'sajat_orarend_kivetel'})})")
res = client.get("/api/sajat_orarend")
ok(res.status_code == 200 and res.get_json() == [], "kezdetben üres a lista")

print("\n2) teljes tanév (2026/2027: 09-01 – 08-31)")
res = post({
    "diak_nev": "Teszt Elek", "cim": "Sakk szakkör", "nap": 3,
    "kezdes": "16:00", "vege": "17:00", "terem": "12",
    "ervenyesites": "tanev",
})
ok(res.status_code == 201, f"a rögzítés 201 ({res.status_code})")
row = (res.get_json() or {}).get("sajat") or {}
ok(row.get("ervenyes_tol") == "2026-09-01" and row.get("ervenyes_ig") == "2027-08-31",
   f"az érvényesség a tanév ({(row.get('ervenyes_tol'), row.get('ervenyes_ig'))})")
series_id = row.get("id")
ok(bool(series_id), "a sorozat kapott id-t")

print("\n3) heti ismétlődés a naptárban")
code, events = calendar("Teszt Elek", "2026-11-01", "2026-11-30")
sajat_events = [e for e in events if (e.get("extendedProps") or {}).get("sajat")]
datums = [e["extendedProps"]["datum"] for e in sajat_events]
ok(code == 200 and datums == ["2026-11-04", "2026-11-11", "2026-11-18", "2026-11-25"],
   f"szerdánként jelenik meg ({datums})")
ok(all(e["backgroundColor"] == "#6f42c1" for e in sajat_events),
   "a saját óra megkülönböztető színt kap")
ok(sajat_events and sajat_events[0]["title"] == "Sakk szakkör (12)",
   f"a cím és a terem megjelenik ('{sajat_events[0]['title'] if sajat_events else ''}')")

print("\n4) egyetlen alkalom törlése (kivétel)")
res = client.post(f"/api/sajat_orarend/{series_id}/kivetel", json={"datum": "2026-11-11"})
ok(res.status_code == 200, "a kivétel rögzítése 200")
code, events = calendar("Teszt Elek", "2026-11-01", "2026-11-30")
datums = [e["extendedProps"]["datum"] for e in events if (e.get("extendedProps") or {}).get("sajat")]
ok("2026-11-11" not in datums and "2026-11-18" in datums,
   f"csak a kivett alkalom tűnt el ({datums})")
listing = client.get("/api/sajat_orarend?diak=Teszt Elek").get_json()
ok(len(listing) == 1, "a sorozat megmaradt egy kivétel után is")

print("\n5) heti érvényesség")
res = post({
    "diak_nev": "Teszt Elek", "cim": "Angol különóra", "nap": 1,
    "kezdes": "15:00", "vege": "16:00", "ervenyesites": "het",
    "datum": "2026-11-04",
})
ok(res.status_code == 201, "a heti érvényesség menthető")
row = (res.get_json() or {}).get("sajat") or {}
ok(row.get("ervenyes_tol") == "2026-11-02" and row.get("ervenyes_ig") == "2026-11-08",
   f"a hét hétfőtől vasárnapig tart ({(row.get('ervenyes_tol'), row.get('ervenyes_ig'))})")
code, events = calendar("Teszt Elek", "2026-11-01", "2026-11-30")
angol = [e["extendedProps"]["datum"] for e in events
         if (e.get("extendedProps") or {}).get("cim") == "Angol különóra"]
ok(angol == ["2026-11-02"], f"a heti tétel csak egyszer jelenik meg ({angol})")

print("\n6) egyedi időszak")
res = post({
    "diak_nev": "Teszt Elek", "cim": "Úszás", "nap": 1,
    "kezdes": "17:00", "vege": "18:00", "ervenyesites": "egyedi",
    "tol": "2026-12-01", "ig": "2026-12-15",
})
ok(res.status_code == 201, "az egyedi időszak menthető")
code, events = calendar("Teszt Elek", "2026-12-01", "2026-12-31")
uszas = [e["extendedProps"]["datum"] for e in events
         if (e.get("extendedProps") or {}).get("cim") == "Úszás"]
ok(uszas == ["2026-12-07", "2026-12-14"], f"az egyedi időszak napjai helyesek ({uszas})")

print("\n7) érvénytelen bemenetek")
bad_cases = [
    ({"diak_nev": "Teszt Elek", "cim": "", "nap": 1, "kezdes": "16:00", "vege": "17:00"}, "üres cím"),
    ({"diak_nev": "Teszt Elek", "cim": "X", "nap": 9, "kezdes": "16:00", "vege": "17:00"}, "rossz nap"),
    ({"diak_nev": "Teszt Elek", "cim": "X", "nap": 1, "kezdes": "17:00", "vege": "16:00"}, "fordított idő"),
    ({"diak_nev": "Teszt Elek", "cim": "X", "nap": 1, "kezdes": "aa", "vege": "17:00"}, "rossz időformátum"),
    ({"diak_nev": "Teszt Elek", "cim": "X", "nap": 1, "kezdes": "16:00", "vege": "17:00",
      "ervenyesites": "egyedi", "tol": "2026-12-15", "ig": "2026-12-01"}, "fordított időszak"),
    ({"diak_nev": "Teszt Elek", "cim": "X", "nap": 1, "kezdes": "16:00", "vege": "17:00",
      "ervenyesites": "ismeretlen"}, "ismeretlen érvényesség"),
]
for payload, label in bad_cases:
    res = post(payload)
    ok(res.status_code == 400, f"{label}: 400 ({res.status_code})")

print("\n8) diák-szűrés és többgyermekes cím")
res = post({"diak_nev": "Másik Diák", "cim": "Zene", "nap": 2,
            "kezdes": "16:00", "vege": "17:00", "ervenyesites": "tanev"})
ok(res.status_code == 201, "másik diák tétele is menthető")
code, events = calendar("", "2026-11-01", "2026-11-30")
masik = [e for e in events if (e.get("extendedProps") or {}).get("diak") == "Másik Diák"]
ok(masik and masik[0]["title"].startswith("[Másik Diák]"),
   f"összes gyermeknél a cím diák-prefixet kap ('{masik[0]['title'] if masik else ''}')")
code, events = calendar("Teszt Elek", "2026-11-01", "2026-11-30")
ok(not any((e.get("extendedProps") or {}).get("diak") == "Másik Diák" for e in events),
   "a diák-szűrő kizárja a másik gyermeket")

print("\n9) sorozat törlése")
res = client.delete(f"/api/sajat_orarend/{series_id}")
ok(res.status_code == 200, "a sorozat törlése 200")
listing = client.get("/api/sajat_orarend?diak=Teszt Elek").get_json()
ok(all(item["id"] != series_id for item in listing), "a sorozat eltűnt a listából")
code, events = calendar("Teszt Elek", "2026-11-01", "2026-11-30")
ok(not any((e.get("extendedProps") or {}).get("sajat_id") == series_id for e in events),
   "a naptárból is eltűnt")

print("\n10) a szinkron nem érinti a saját táblákat")
ok("sajat_orarend" not in kreta.SCRAPER_TABLES
   and "sajat_orarend_kivetel" not in kreta.SCRAPER_TABLES,
   f"a SCRAPER_TABLES nem tartalmazza őket ({kreta.SCRAPER_TABLES})")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
