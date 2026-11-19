# -*- coding: utf-8 -*-
"""
A „mikor került be a saját DB-be” időpont (Kaneo #147) tesztjei.

A KRÉTA gyakran visszamenőleges bejegyzés-dátummal adja az új jegyet, ezért a
digest / „új” jelölés a `letrehozva` (first seen) időpontot használja:

1) a migráció a régi sorokat a KRÉTA-dátumból tölti fel (nem lesznek „újak”),
2) a mai `letrehozva` + régi `bej_datum` jegy megjelenik a digestben és a
   `/api/ma` friss jegyei közt,
3) a régi beszúrású sor nem jelenik meg mai újként,
4) a teljes cserés mentés (`save_esemenyek_by_type`) megőrzi a `letrehozva`
   értékét, az új sor viszont mostani időpontot kap,
5) az új üzenet / hiányzás / igazolás sor is kap `letrehozva` értéket.
"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_first_seen_"))
db = work / "kreta_adatok.db"
config = {"STUDENTS": [{"diak_nev": "Teszt", "enable_rewards": True, "active": False}]}
(work / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

env = os.environ.copy()
env.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": str(work / "csat"),
    "KRETA_SCHEDULER_STATE_FILE": str(work / "scheduler_state.json"),
    "KRETA_VERSION_FILE": str(work / "version.txt"),
    "PYTHONIOENCODING": "utf-8",
})
os.environ.update({k: v for k, v in env.items() if k.startswith("KRETA")})

sys.path.insert(0, str(ROOT))
import kreta_digest  # noqa: E402
import kreta_playwright as k  # noqa: E402
import kreta_tanev  # noqa: E402

k.init_db()

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


def egy_sor(sql, params=()):
    conn = sqlite3.connect(str(k.DB_FILE))
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def letrehozva_ertek(tantargy):
    row = egy_sor(
        "SELECT letrehozva FROM esemenyek WHERE diak_nev = 'Teszt' AND"
        " esemeny_tipus = 'Értékelés' AND tantargy = ? ORDER BY id DESC LIMIT 1",
        (tantargy,))
    return (row["letrehozva"] if row else "") or ""


MA = date(2026, 11, 19)
TEGNAP = MA - timedelta(days=1)

print("1) Migráció: a régi sor `letrehozva` értéke a KRÉTA-dátumból jön")
conn = sqlite3.connect(str(k.DB_FILE))
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, tartalom, kesz, tanev, letrehozva)"
    " VALUES ('Teszt', 'Értékelés', 'Történelem', '4', 4, '2025. 03. 04.', '', '', 0,"
    " '2024/2025', NULL)")
conn.commit()
kreta_tanev.ensure_first_seen_schema(conn)
row = conn.execute(
    "SELECT letrehozva FROM esemenyek WHERE diak_nev = 'Teszt' AND tantargy = 'Történelem'"
).fetchone()
conn.close()
ok(row and row[0] == "2025-03-04 00:00:00",
   f"a backfill a bej_datum napja: {row[0] if row else None}")

print("\n2) Régi bej_datum + mai letrehozva -> mai új jegy")
conn = sqlite3.connect(str(k.DB_FILE))
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, tartalom, kesz, tanev, letrehozva)"
    " VALUES ('Teszt', 'Értékelés', 'Angol', '5', 5, '2026. 09. 15.', '', '', 0,"
    " '2026/2027', ?)", (MA.isoformat() + " 07:30:00",))
conn.commit()
adat = kreta_digest.collect_day(conn, "Teszt", MA)
conn.close()
ok(any(j["tantargy"] == "Angol" for j in adat["jegyek"]),
   f"a digestben ott a mai érkezésű jegy: {[j['tantargy'] for j in adat['jegyek']]}")

conn = sqlite3.connect(str(k.DB_FILE))
adat = kreta_digest.collect_day(conn, "Teszt", TEGNAP)
conn.close()
ok(not any(j["tantargy"] == "Angol" for j in adat["jegyek"]),
   "a tegnapi digestben viszont nincs benne")

print("\n3) Régi beszúrású sor nem lesz visszamenőleg „mai”")
conn = sqlite3.connect(str(k.DB_FILE))
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, tartalom, kesz, tanev, letrehozva)"
    " VALUES ('Teszt', 'Értékelés', 'Fizika', '3', 3, '2026. 11. 18.', '', '', 0,"
    " '2026/2027', '2026-10-05 10:00:00')")
conn.commit()
adat = kreta_digest.collect_day(conn, "Teszt", MA)
conn.close()
ok(not any(j["tantargy"] == "Fizika" for j in adat["jegyek"]),
   "a régen beszúrt jegy nem jelenik meg mai újként")

print("\n4) /api/ma: a friss jegy a bekerülés dátuma alapján jön")
import app as kreta  # noqa: E402

client = kreta.app.test_client()
valasz = client.get("/api/ma?datum=2026-11-19").get_json()
tantargyak = [j["tantargy"] for j in (valasz.get("uj_jegyek") or [])]
ok("Angol" in tantargyak, f"az Angol jegy a friss listában: {tantargyak}")
ok("Fizika" not in tantargyak, "a régen beszúrt Fizika nem friss")
angol = next((j for j in valasz["uj_jegyek"] if j["tantargy"] == "Angol"), {})
ok(angol.get("letrehozva") == "2026-11-19", f"a letrehozva mező is jön: {angol}")
ok(angol.get("bej_datum") == "2026-09-15", f"a bej_datum megmarad: {angol}")

print("\n5) Teljes cserés mentés megőrzi a letrehozva értéket")
jegy = {"esemeny_tipus": "Értékelés", "tantargy": "Kémia", "ertek": "5",
        "szam_ertek": 5, "bej_datum": "2026. 09. 01."}
k.save_esemenyek_by_type("Teszt", [jegy], set(), ["Értékelés"])
elso = letrehozva_ertek("Kémia")
ok(bool(elso) and elso[:10] == date.today().isoformat(),
   f"az új sor mostani letrehozva-t kap: {elso}")

conn = sqlite3.connect(str(k.DB_FILE))
conn.execute("UPDATE esemenyek SET letrehozva = '2026-01-02 03:04:05'"
             " WHERE diak_nev = 'Teszt' AND tantargy = 'Kémia'")
conn.commit()
conn.close()

# Ugyanaz a tartalom jön újra a teljes cserében -> az időpont marad.
k.save_esemenyek_by_type("Teszt", [dict(jegy)], set(), ["Értékelés"])
masodik = letrehozva_ertek("Kémia")
ok(masodik == "2026-01-02 03:04:05",
   f"a teljes csere után megmarad: {masodik}")

print("\n6) Új üzenet / hiányzás / igazolás is kap letrehozva-t")
k.save_uzenet_to_db("Teszt", "Osztályfőnök", "Teszt üzenet", "2026. 09. 10.", "Szöveg")
k.save_hianyzasok_to_db("Teszt", [{
    "kreta_id": "H1", "mulasztas_datum": "2026-09-11", "ora_sorszam": 2,
    "tantargy": "Matematika", "mulasztas_tipus": "Hiányzás", "igazolt": 0,
}], window=("2026-09-01", "2026-09-30"))
k.save_igazolasok_to_db("Teszt", [{
    "kreta_id": "I1", "kezdete": "2026-09-10", "vege": "2026-09-12",
    "igazolas_tipus": "Orvosi",
}], window=("2026-09-01", "2026-09-30"))

for tabla, oszlop, ertek in (
    ("uzenetek", "targy", "Teszt üzenet"),
    ("hianyzasok", "kreta_id", "H1"),
    ("igazolasok", "kreta_id", "I1"),
):
    row = egy_sor(
        f"SELECT letrehozva FROM {tabla} WHERE diak_nev = 'Teszt' AND {oszlop} = ?",
        (ertek,))
    ok(bool(row and row["letrehozva"]),
       f"{tabla}.letrehozva kitöltve: {row['letrehozva'] if row else None}")

print()
if _hibak:
    print("HIBAK:", len(_hibak))
    for hiba in _hibak:
        print(" -", hiba)
    sys.exit(1)
print("KÉSZ")
