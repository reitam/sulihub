# -*- coding: utf-8 -*-
"""
D8 teszt: árnyék/ellenőrző mód.

1) `kreta_shadow.compare_databases`: két DB összevetése (kulcs + mezők).
2) Valódi DB-n (külön folyamatban): a shadow futás csak a **másolatra** ír, a
   valódi DB érintetlen, a riport jelzi az eltérést, a `NEW_*` számlálók
   visszaállnak.
3) Böngésző nélkül (page=None) a shadow nem fut le.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


work = Path(tempfile.mkdtemp(prefix="kreta_shadow_"))
data = work / "data"
data.mkdir()
(data / "config.json").write_text(
    json.dumps({"HEADLESS": True, "SYNC_MODE": "api_first", "SYNC_SHADOW": True,
                "STUDENTS": [{"diak_nev": "Teszt", "active": False}]}, ensure_ascii=False),
    encoding="utf-8",
)

probe = work / "probe.py"
probe.write_text(
    """# -*- coding: utf-8 -*-
import asyncio, json, sqlite3, sys
sys.path.insert(0, r'{root}')
import kreta_playwright as k
import kreta_shadow

k.init_db()

conn = sqlite3.connect(k.DB_FILE)
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek, bej_datum,"
    " hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz)"
    " VALUES ('Teszt','Értékelés','Matematika','Jeles(5)',5,'2026. 10. 20.','','Tanár','','','','','',0)")
conn.commit(); conn.close()


def count_events(path):
    conn = sqlite3.connect(path)
    value = conn.execute(
        "SELECT COUNT(*) FROM esemenyek WHERE diak_nev='Teszt'").fetchone()[0]
    conn.close()
    return value


async def fake_process_student(page, student, skip=None, tracker=None, **kwargs):
    # A shadow DB-re ír (a DB_FILE ekkor a másolat); teljes cserét szimulál.
    k.save_esemenyek_by_type("Teszt", [{{
        "esemeny_tipus": "Értékelés", "tantargy": "Fizika", "ertek": "Jó(4)",
        "szam_ertek": 4, "bej_datum": "2026. 10. 21.",
    }}], set(), ["Értékelés"])
    k.NEW_EVENT_COUNTS["Teszt"] = {{"Értékelés": 99}}


main_before = count_events(k.DB_FILE)
k.NEW_EVENT_COUNTS["Teszt"] = {{"Értékelés": 1}}
main_db = k.DB_FILE
original = k.process_student
k.process_student = fake_process_student
try:
    no_page = asyncio.run(k.run_shadow_student({{"diak_nev": "Teszt"}}, page=None))
    report = asyncio.run(k.run_shadow_student({{"diak_nev": "Teszt"}}, page=object()))
finally:
    k.process_student = original

main_after = count_events(k.DB_FILE)
lines = kreta_shadow.format_report(report)

print("RESULT=" + json.dumps({{
    "db_restored": k.DB_FILE == main_db,
    "main_before": main_before,
    "main_after": main_after,
    "no_page": no_page,
    "total_diffs": report["total_diffs"],
    "is_match": report["is_match"],
    "tables": report["tables"],
    "lines": lines,
    "counts_restored": k.NEW_EVENT_COUNTS.get("Teszt"),
    "shadow_file_left": __import__("os").path.exists(main_db + ".shadow"),
}}, ensure_ascii=False))
""".replace("{root}", str(ROOT)).replace("{{", "{").replace("}}", "}"),
    encoding="utf-8",
)

env = os.environ.copy()
env["KRETA_DATA_DIR"] = str(data)
env["PYTHONIOENCODING"] = "utf-8"
for key in ("KRETA_CONFIG_FILE", "KRETA_DB_FILE", "KRETA_LOG_FILE"):
    env.pop(key, None)

result = subprocess.run([sys.executable, str(probe)], cwd=str(work), env=env,
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=120)
out = result.stdout
if result.returncode != 0 and not out:
    print(result.stderr[-1200:])

payload = {}
for line in out.splitlines():
    if line.startswith("RESULT="):
        payload = json.loads(line.split("=", 1)[1])

print("1) A riport")
ok(result.returncode == 0, f"a próba lefutott (exit={result.returncode})")
ok(payload.get("is_match") is False, "az eltérést észlelte")
ok(payload.get("total_diffs") == 2, f"2 eltérés (csak API / csak Playwright): {payload.get('total_diffs')}")
tables = payload.get("tables") or {}
events = tables.get("esemenyek") or {}
ok(events.get("primary") == 1 and events.get("shadow") == 1,
   f"1-1 esemény a két DB-ben: {events.get('primary')}/{events.get('shadow')}")
ok(events.get("only_primary") == [["Értékelés", "Matematika", "2026. 10. 20.", "", "Jeles(5)", ""]],
   f"csak az API-ban: {events.get('only_primary')}")
ok(events.get("only_shadow") == [["Értékelés", "Fizika", "2026. 10. 21.", "", "Jó(4)", ""]],
   f"csak a Playwrightban: {events.get('only_shadow')}")
ok(any("ELTÉRÉS" in line for line in payload.get("lines") or []), "a naplósor jelzi az eltérést")
ok(any("csak Playwright" in line for line in payload.get("lines") or []), "a naplósor tartalmazza az eltérő kulcsot")

print("\n2) A valódi DB érintetlen")
ok(payload.get("db_restored") is True, "a DB_FILE visszaállt az eredeti útvonalra")
ok(payload.get("main_before") == payload.get("main_after") == 1,
   f"a valódi DB sora nem változott: {payload.get('main_before')} -> {payload.get('main_after')}")
ok(payload.get("shadow_file_left") is False, "a shadow DB-másolat törlődött")
ok(payload.get("counts_restored") == {"Értékelés": 1}, "a NEW_* számlálók visszaálltak")

print("\n3) Böngésző nélkül nincs shadow")
ok(payload.get("no_page") is None, "page=None -> nincs shadow futás")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
