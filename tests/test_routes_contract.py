# -*- coding: utf-8 -*-
"""
Route-contract teszt (KRÉ-14 #92).

A refaktor (app.py/index.html szétbontása) alatt ez a teszt a gépies bizonyíték
arra, hogy **egyetlen URL sem változott meg**: a Flask `url_map`-jének teljes
listáját (rule + metódusok) egy fagyasztott konstanshoz méri. Az endpoint-nevek
belső azonosítók (blueprint-prefixet kaphatnak), ezért azokat csak egyediség
szempontjából ellenőrzi — kívülről nem látszanak, és a kód nem használ `url_for`-t
endpoint-névre.

Ha ez a teszt piros lesz, a refaktor véletlenül megváltoztatta a nyilvános
felületet (pl. blueprint-prefix az URL-ben, elgépelt rule, dupla regisztráció,
eltűnt végpont) — nem szabad „tesztet igazítani", hanem a kódot kell visszaállítani.

A lista az app.py explicit route-jai + a Flask beépített `static` végpontja
(a KRÉ-8-cal együtt 44 rule). A HEAD/OPTIONS metódusokat a Flask automatikusan
adja, ezért a contract csak a deklarált metódusokat rögzíti.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A refaktor kiinduló állapota (v1.9.2, 2026-11-06). Sorrend: rule szerint.
EXPECTED_RULES = [
    ("/", ["GET"]),
    ("/api/atlagok", ["GET"]),
    ("/api/dashboard", ["GET"]),
    ("/api/digest/settings", ["GET", "PUT"]),
    ("/api/digest/test", ["POST"]),
    ("/api/esemeny/statusz", ["POST"]),
    ("/api/esemenyek", ["GET"]),
    ("/api/esemenyek/export.xlsx", ["GET"]),
    ("/api/hianyzas-mintazat", ["GET"]),
    ("/api/hianyzasok", ["GET"]),
    ("/api/hianyzasok/export.xlsx", ["GET"]),
    ("/api/igazolasok", ["GET"]),
    ("/api/jegy_kalkulator", ["GET"]),
    ("/api/kalkulator_cel", ["GET", "POST"]),
    ("/api/kedvencek", ["GET", "POST"]),
    ("/api/kereses", ["GET"]),
    ("/api/kifizetes", ["POST"]),
    ("/api/kifizetesek/export.csv", ["GET"]),
    ("/api/kifizetesek/export.xlsx", ["GET"]),
    ("/api/kommentek", ["GET"]),
    ("/api/kommentek", ["POST"]),
    ("/api/kommentek/<int:komment_id>", ["DELETE"]),
    ("/api/logs", ["GET"]),
    ("/api/logs/clear", ["POST"]),
    ("/api/ma", ["GET"]),
    ("/api/naptar/<kind>/<int:item_id>", ["GET"]),
    ("/api/naptar/<kind>/<int:item_id>.ics", ["GET"]),
    ("/api/naptar/ai/ics", ["POST"]),
    ("/api/naptar_esemenyek", ["GET"]),
    ("/api/ntfy/test", ["POST"]),
    ("/api/orarend", ["GET"]),
    ("/api/orarend/export_ics", ["GET"]),
    ("/api/orarend/export_pdf", ["GET"]),
    ("/api/orarend_naptar", ["GET"]),
    ("/api/orarend_szinek", ["GET", "PUT"]),
    ("/api/riportkartya/export_pdf", ["GET"]),
    ("/api/sajat_orarend", ["GET", "POST"]),
    ("/api/sajat_orarend/<int:series_id>", ["DELETE", "PUT"]),
    ("/api/sajat_orarend/<int:series_id>/kivetel", ["POST"]),
    ("/api/scheduler/status", ["GET"]),
    ("/api/statisztika", ["GET"]),
    ("/api/sync/start", ["POST"]),
    ("/api/sync/status", ["GET"]),
    ("/api/sync/stop", ["POST"]),
    ("/api/sync_runs", ["GET"]),
    ("/api/tanevek", ["GET"]),
    ("/api/uzenet/<int:uzenet_id>/ai", ["POST"]),
    ("/api/uzenetek", ["GET"]),
    ("/api/uzenetek/<int:uzenet_id>/olvasott", ["POST"]),
    ("/api/uzenetek/olvasott", ["POST"]),
    ("/health", ["GET"]),
    ("/static/<path:filename>", ["GET"]),
    ("/static/csatolmanyok/<path:filename>", ["GET"]),
]

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


# Izolált környezet: az import ne a valódi DB-hez/confighoz nyúljon.
work = tempfile.mkdtemp(prefix="kreta_routes_")
config_path = os.path.join(work, "config.json")
db_path = os.path.join(work, "kreta_adatok.db")
with open(config_path, "w", encoding="utf-8") as fh:
    fh.write('{"STUDENTS": []}')
sqlite3.connect(db_path).close()
os.environ.update({
    "KRETA_DATA_DIR": work,
    "KRETA_DB_FILE": db_path,
    "KRETA_CONFIG_FILE": config_path,
    "KRETA_LOG_FILE": os.path.join(work, "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csat"),
    "KRETA_SCHEDULER_STATE_FILE": os.path.join(work, "scheduler_state.json"),
    "KRETA_VERSION_FILE": os.path.join(work, "version.txt"),
})
sys.path.insert(0, str(ROOT))
import app as kreta  # noqa: E402

print("1) A route-lista darabszáma")
actual = sorted(
    (rule.rule, tuple(sorted(rule.methods - {"HEAD", "OPTIONS"})), rule.endpoint)
    for rule in kreta.app.url_map.iter_rules()
)
ok(len(actual) == len(EXPECTED_RULES),
   f"route-ok száma: {len(actual)} (elvárt: {len(EXPECTED_RULES)})")
ok(len({(rule, endpoint) for rule, _m, endpoint in actual}) == len(actual),
   "minden rule+endpoint pontosan egyszer szerepel (nincs dupla regisztráció)")

print("\n2) Rule + metódus egyezés (a refaktor nem változtathat rajta)")
expected_set = {(rule, tuple(methods)) for rule, methods in EXPECTED_RULES}
actual_set = {(rule, methods) for rule, methods, _e in actual}
missing = sorted(expected_set - actual_set)
extra = sorted(actual_set - expected_set)
ok(not missing, f"nincs eltűnt/megváltozott URL (hiányzó: {missing or 'nincs'})")
ok(not extra, f"nincs új/váratlan URL (többlet: {extra or 'nincs'})")

print("\n3) Endpoint-nevek egyedisége (blueprint-átállás tipikus hibája)")
endpoint_names = [endpoint for _r, _m, endpoint in actual]
duplikalt = sorted({name for name in endpoint_names if endpoint_names.count(name) > 1})
ok(not duplikalt, f"minden endpoint-név egyedi (duplikált: {duplikalt or 'nincs'})")

print("\n4) Rule + metódus párok egyedisége")
parok = [(rule, method) for rule, methods, _e in actual for method in methods]
duplikalt_par = sorted({par for par in parok if parok.count(par) > 1})
ok(not duplikalt_par, f"nincs azonos rule+metódus páros (duplikált: {duplikalt_par or 'nincs'})")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
