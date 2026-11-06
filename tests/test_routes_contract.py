# -*- coding: utf-8 -*-
"""
Route-contract teszt (KRÉ-14 #92).

A refaktor (app.py/index.html szétbontása) alatt ez a teszt a gépies bizonyíték
arra, hogy **egyetlen URL sem változott meg**: a Flask `url_map`-jének teljes
listáját (rule + metódusok + endpoint-név) egy fagyasztott konstanshoz méri.

Ha ez a teszt piros lesz, a refaktor véletlenül megváltoztatta a nyilvános
felületet (pl. blueprint-prefix, elgépelt rule, dupla regisztráció, eltűnt
végpont) — nem szabad „tesztet igazítani", hanem a kódot kell visszaállítani.

A lista az app.py 41 explicit route-ja + a Flask beépített `static` végpontja
(összesen 42 rule). A HEAD/OPTIONS metódusokat a Flask automatikusan adja, ezért
a contract csak a deklarált metódusokat rögzíti.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A refaktor kiinduló állapota (v1.9.2, 2026-11-06). Sorrend: rule szerint.
EXPECTED_RULES = [
    ("/", ["GET"], "index"),
    ("/api/atlagok", ["GET"], "api_atlagok"),
    ("/api/dashboard", ["GET"], "api_dashboard"),
    ("/api/esemeny/statusz", ["POST"], "api_esemeny_statusz"),
    ("/api/esemenyek", ["GET"], "api_esemenyek"),
    ("/api/hianyzasok", ["GET"], "api_hianyzasok"),
    ("/api/igazolasok", ["GET"], "api_igazolasok"),
    ("/api/kifizetes", ["POST"], "api_kifizetes_save"),
    ("/api/kifizetesek/export.csv", ["GET"], "api_kifizetesek_csv"),
    ("/api/kifizetesek/export.xlsx", ["GET"], "api_kifizetesek_xlsx"),
    ("/api/kommentek", ["GET"], "api_kommentek_list"),
    ("/api/kommentek", ["POST"], "api_kommentek_add"),
    ("/api/kommentek/<int:komment_id>", ["DELETE"], "api_kommentek_delete"),
    ("/api/logs", ["GET"], "api_get_logs"),
    ("/api/logs/clear", ["POST"], "api_clear_logs"),
    ("/api/naptar/<kind>/<int:item_id>", ["GET"], "api_naptar_info"),
    ("/api/naptar/<kind>/<int:item_id>.ics", ["GET"], "api_naptar_ics"),
    ("/api/naptar/ai/ics", ["POST"], "api_naptar_ai_ics"),
    ("/api/naptar_esemenyek", ["GET"], "api_naptar_esemenyek"),
    ("/api/ntfy/test", ["POST"], "api_ntfy_test"),
    ("/api/orarend", ["GET"], "api_orarend"),
    ("/api/orarend/export_ics", ["GET"], "api_orarend_export_ics"),
    ("/api/orarend/export_pdf", ["GET"], "export_orarend_pdf"),
    ("/api/orarend_naptar", ["GET"], "api_orarend_naptar"),
    ("/api/orarend_szinek", ["GET", "PUT"], "api_orarend_szinek"),
    ("/api/sajat_orarend", ["GET", "POST"], "api_sajat_orarend"),
    ("/api/sajat_orarend/<int:series_id>", ["DELETE", "PUT"], "api_sajat_orarend_torles"),
    ("/api/sajat_orarend/<int:series_id>/kivetel", ["POST"], "api_sajat_orarend_kivetel"),
    ("/api/scheduler/status", ["GET"], "api_scheduler_status"),
    ("/api/statisztika", ["GET"], "api_statisztika"),
    ("/api/sync/start", ["POST"], "api_sync_start"),
    ("/api/sync/status", ["GET"], "api_sync_status"),
    ("/api/sync/stop", ["POST"], "api_sync_stop"),
    ("/api/sync_runs", ["GET"], "api_sync_runs"),
    ("/api/tanevek", ["GET"], "api_tanevek"),
    ("/api/uzenet/<int:uzenet_id>/ai", ["POST"], "api_uzenet_ai"),
    ("/api/uzenetek", ["GET"], "api_uzenetek"),
    ("/api/uzenetek/<int:uzenet_id>/olvasott", ["POST"], "api_uzenet_olvasott"),
    ("/api/uzenetek/olvasott", ["POST"], "api_uzenetek_olvasott_bulk"),
    ("/health", ["GET"], "health"),
    ("/static/<path:filename>", ["GET"], "static"),
    ("/static/csatolmanyok/<path:filename>", ["GET"], "download_csatolmany"),
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

print("\n2) Rule + metódus + endpoint egyezés (a refaktor nem változtathat rajta)")
expected_set = {(rule, tuple(methods), endpoint) for rule, methods, endpoint in EXPECTED_RULES}
actual_set = set(actual)
missing = sorted(expected_set - actual_set)
extra = sorted(actual_set - expected_set)
ok(not missing, f"nincs eltűnt/megváltozott route (hiányzó: {missing or 'nincs'})")
ok(not extra, f"nincs új/váratlan route (többlet: {extra or 'nincs'})")

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
