# -*- coding: utf-8 -*-
"""Tanév-állapot: automatikus (UID-alapú) technikai zárás/nyitás (Kaneo #43).

Éles KRÉTA nélkül: a `TanevUid` változását szimuláljuk. A zárás technikai —
nincs adatlekérés; a régi tanév adata érintetlen.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

work = tempfile.mkdtemp(prefix="kreta_tanev_state_")
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
Path(work, "config.json").write_text(json.dumps({
    "SCHEDULER": {"ENABLED": False},
    "STUDENTS": [{"diak_nev": "Teszt Elek", "active": True},
                 {"diak_nev": "Teszt Anna", "active": True}],
}, ensure_ascii=False), encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as kreta  # noqa: E402
import kreta_tanev  # noqa: E402

kreta.init_db_extensions()
_hibak = []


def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)


conn = kreta.get_db_connection()
cur = conn.cursor()
for tanev in ("2024/2025", "2025/2026", "2026/2027", "2027/2028"):
    cur.execute(
        "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg,"
        " csatolmany_nev, csatolmany_utvonal, tanev, tanev_forras)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("Teszt Elek", "U-" + tanev, "Iskola", "Targy " + tanev,
         "2026. 09. 01. 10:00", "Szoveg", "", "", tanev, "szamitott"))
conn.commit()
conn.close()

print("\n1) Séma és kezdeti állapot")
conn = kreta.get_db_connection()
kreta_tanev.ensure_tanev_state_schema(conn)
letrehozott = kreta_tanev.seed_tanev_state(conn, date(2026, 11, 3))
allapot = kreta_tanev.tanev_allapotok(conn)
conn.close()
ok(set(allapot) >= {"2024/2025", "2025/2026", "2026/2027"},
   f"a meglévő tanévek inicializálva: {sorted(allapot)}")
ok(allapot.get("2024/2025", {}).get("allapot") == "lezart", "2024/2025 lezárt")
ok(allapot.get("2025/2026", {}).get("allapot") == "lezart", "2025/2026 lezárt")
ok(allapot.get("2025/2026", {}).get("lezarva_at", "").startswith("2026-08-31"),
   f"a zárás a tanév végének dátuma: {allapot.get('2025/2026', {}).get('lezarva_at')}")
ok(allapot.get("2026/2027", {}).get("allapot") == "nyitott", "2026/2027 nyitott")
ok("2027/2028" not in allapot, "a jövőbeli tanévnek még nincs állapota")

print("\n2) Első UID: nincs zárás, csak rögzítés")
conn = kreta.get_db_connection()
r = kreta_tanev.apply_tanev_uid(conn, "Teszt Elek", "100", date(2026, 11, 3))
conn.close()
ok(not r["lezart_tanev"] and not r["uj_tanev"], f"első látás: nincs zárás ({r})")
conn = kreta.get_db_connection()
uid_row = conn.execute("SELECT tanev_uid, tanev FROM tanulo_tanev_uid WHERE diak_nev = ?",
                       ("Teszt Elek",)).fetchone()
conn.close()
ok(tuple(uid_row) == ("100", "2026/2027"), f"UID rögzítve: {tuple(uid_row) if uid_row else None}")

print("\n3) Változatlan UID: nincs állapotváltás")
conn = kreta.get_db_connection()
r = kreta_tanev.apply_tanev_uid(conn, "Teszt Elek", "100", date(2026, 11, 3))
conn.close()
ok(not r["valtozas"] and not r["lezart_tanev"], "változatlan UID -> nincs zárás")

print("\n3b) A naptári seed eltér a KRÉTA UID-tól: a UID az igazság")
conn = kreta.get_db_connection()
conn.execute("UPDATE tanevek SET allapot = 'lezart', lezarva_at = '2026-08-31T23:59:59'"
             " WHERE tanev = '2026/2027'")
conn.execute("INSERT INTO tanevek (tanev, kezdet, veg, allapot, forras, updated_at)"
             " VALUES ('2027/2028', '2027-09-01', '2028-08-31', 'nyitott', 'szamitott', 'x')"
             " ON CONFLICT(tanev) DO UPDATE SET allapot = 'nyitott', lezarva_at = NULL")
conn.commit()
r = kreta_tanev.apply_tanev_uid(conn, "Teszt Elek", "100", date(2027, 9, 1))
allapot = kreta_tanev.tanev_allapotok(conn)
conn.close()
ok(r["lezart_tanev"] == "2027/2028" and r["uj_tanev"] == "2026/2027",
   f"a UID szerinti tanévre áll vissza: {r['lezart_tanev']} -> {r['uj_tanev']}")
ok(allapot.get("2026/2027", {}).get("allapot") == "nyitott"
   and allapot.get("2027/2028", {}).get("allapot") == "lezart",
   "a KRÉTA által jelzett tanév nyitott")

print("\n4) UID-változás új tanévnél: technikai zárás + nyitás")
conn = kreta.get_db_connection()
r = kreta_tanev.apply_tanev_uid(conn, "Teszt Elek", "101", date(2027, 9, 1))
allapot = kreta_tanev.tanev_allapotok(conn)
conn.close()
ok(r["lezart_tanev"] == "2026/2027" and r["uj_tanev"] == "2027/2028",
   f"zárás/nyitás: {r['lezart_tanev']} -> {r['uj_tanev']}")
ok(allapot.get("2026/2027", {}).get("allapot") == "lezart", "2026/2027 lezárva")
ok(allapot.get("2026/2027", {}).get("forras") == "kreta_uid", "a zárás forrása: kreta_uid")
ok(allapot.get("2027/2028", {}).get("allapot") == "nyitott", "2027/2028 megnyitva")

print("\n5) A második diák később vált: nincs dupla zárás")
conn = kreta.get_db_connection()
kreta_tanev.apply_tanev_uid(conn, "Teszt Anna", "900", date(2026, 11, 3))  # első látás
r = kreta_tanev.apply_tanev_uid(conn, "Teszt Anna", "901", date(2027, 9, 3))
allapot = kreta_tanev.tanev_allapotok(conn)
conn.close()
ok(not r["lezart_tanev"] and r["uj_tanev"] == "2027/2028",
   f"a második diák ugyanarra a tanévre vált, nincs újabb zárás: {r}")
ok(allapot.get("2027/2028", {}).get("allapot") == "nyitott", "a nyitott tanév marad")

print("\n6) UID-változás ugyanabban a tanévben: nincs zárás")
conn = kreta.get_db_connection()
r = kreta_tanev.apply_tanev_uid(conn, "Teszt Elek", "102", date(2027, 10, 1))
allapot = kreta_tanev.tanev_allapotok(conn)
conn.close()
ok(r["valtozas"] and not r["lezart_tanev"], f"csak UID-frissítés: {r}")
ok(allapot.get("2027/2028", {}).get("allapot") == "nyitott", "a nyitott tanév marad")

print("\n7) Üres UID: nincs változás")
conn = kreta.get_db_connection()
r = kreta_tanev.apply_tanev_uid(conn, "Teszt Elek", "", date(2027, 11, 1))
conn.close()
ok(not r["valtozas"] and "nincs TanevUid" in r["megjegyzes"], f"üres UID: {r['megjegyzes']}")

print("\n8) /api/tanevek: az állapot is jön")
cl = kreta.app.test_client()
res = cl.get("/api/tanevek").get_json() or {}
ok("allapot" in res and res["allapot"].get("2027/2028", {}).get("allapot") == "nyitott",
   f"API allapot: {res.get('allapot', {}).get('2027/2028')}")
ok(res["allapot"].get("2026/2027", {}).get("allapot") == "lezart", "a lezárt tanév is látszik")

print("\n9) Futás utáni hook: a KRÉTA UID alapján frissít (fake kliens)")
os.environ["KRETA_TODAY"] = "2028-09-02"
uids = {"Teszt Elek": "200", "Teszt Anna": "900"}


class FakeClient:
    def __init__(self, student):
        self.diak = student.get("diak_nev")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def fetch_tanev_uid(self):
        if self.diak == "Teszt Anna":
            raise RuntimeError("szimulált API hiba")
        return uids[self.diak]


eredeti = kreta.kreta_api.KretaApiClient
kreta.kreta_api.KretaApiClient = FakeClient
try:
    logs = []
    changes = kreta.update_tanev_state_from_api(log_fn=logs.append)
finally:
    kreta.kreta_api.KretaApiClient = eredeti
ok(len(changes) == 1 and changes[0]["lezart_tanev"] == "2027/2028"
   and changes[0]["uj_tanev"] == "2028/2029",
   f"a hook lezárta/nyitotta: {changes}")
ok(any("TANÉV LEZÁRVA" in l for l in logs), f"a napló jelzi a zárást: {logs[-2:]}")
ok(any("Teszt Anna" in l and "nem olvasható" in l for l in logs),
   "a hibás diákot naplózza, de nem áll meg")
os.environ["KRETA_TODAY"] = "2026-11-03"

os.environ.pop("KRETA_TODAY", None)
shutil.rmtree(work, ignore_errors=True)

print("\n" + "=" * 60)
if _hibak:
    print(f"BUKOTT ({len(_hibak)} hiba)")
    sys.exit(1)
print("MINDEN ELLENŐRZÉS OK")
