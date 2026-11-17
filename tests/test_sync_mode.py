# -*- coding: utf-8 -*-
"""
A D2 (SYNC_MODE + forrásnapló) tesztjei.

Két rész:
1) `kreta_sync` tiszta logikája (mód-feloldás, forrásnapló, API-hiba kezelés)
   hálózat és adatbázis nélkül;
2) valódi SQLite-on (külön folyamatban, temp adatkönyvtárral) annak igazolása,
   hogy a hibás adatkör nem hoz létre duplikált sort, és a már frissült
   típusok írását senki nem írja felül. (A böngészős fallback a v2.5.0-ban
   kikerült — a forrásnapló `playwright` címkéje a tracker logikájának maradt.)
"""
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import kreta_sync  # noqa: E402

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


print("1) SYNC_MODE feloldása")
ok(kreta_sync.resolve_sync_mode({}) == "api", "alapértelmezés: api (böngésző nélkül)")
ok(kreta_sync.resolve_sync_mode({"SYNC_MODE": "api"}) == "api", "api mód")
ok(kreta_sync.resolve_sync_mode({"SYNC_MODE": "api_first"}) == "api_first", "api_first mód")
ok(kreta_sync.resolve_sync_mode({"SYNC_MODE": " API-First "}) == "api_first",
   "kis/nagybetű, szóköz és kötőjel kezelve")
ok(kreta_sync.resolve_sync_mode({"SYNC_MODE": "bogus"}) == "api",
   "ismeretlen érték -> api (nem indít böngészőt)")
ok(kreta_sync.resolve_sync_mode(None) == "api", "None config -> api")

ok(kreta_sync.needs_api("api") and kreta_sync.needs_api("api_first"), "api/api_first használ API-t")
ok(not kreta_sync.needs_api("playwright"), "playwright mód nem használ API-t")
ok(kreta_sync.needs_playwright("api_first") and kreta_sync.needs_playwright("playwright"),
   "api_first/playwright használ böngészőt")
ok(not kreta_sync.needs_playwright("api"), "tiszta api mód nem indít böngészőt")

print("\n2) Forrásnapló")
tracker = kreta_sync.SourceTracker("Teszt")
tracker.record("jegyek", "api", ok=True)
tracker.record("hianyzasok", "api", ok=False, reason="KretaNetworkError: timeout")
ok(tracker.api_done() == {"jegyek"}, "csak a sikeres API-adatkör számít késznek")
ok("hianyzasok" in tracker.failures(), "a hiba oka rögzítve")
ok(tracker.has("jegyek") and not tracker.has("hianyzasok"), "has() a forrásra szűr")
ok("API: 1" in tracker.summary_line(), f"összegzés: {tracker.summary_line()}")
kreta_sync.mark_playwright(tracker, "hianyzasok")
outcome = tracker.get("hianyzasok")
ok(outcome.source == "playwright" and outcome.ok, "fallback után a forrás playwright")
ok("timeout" in outcome.reason, "a fallback oka megmarad")
ordered = list(tracker.as_dict())
ok(ordered == ["jegyek", "hianyzasok"], f"a sorrend az adatkör-sorrendet követi: {ordered}")

print("\n3) Hibaszöveg rövidítése")
long_error = RuntimeError("x" * 500)
text = kreta_sync.describe_error(long_error)
ok(text.startswith("RuntimeError: "), "a hiba típusa benne van")
ok(len(text) <= 220, f"a hibaüzenet rövid ({len(text)} karakter)")

# ── 4) Valódi adatbázis, külön folyamatban ──────────────────────────────────
work = Path(tempfile.mkdtemp(prefix="kreta_syncmode_"))
data = work / "data"
data.mkdir()
(data / "config.json").write_text(
    json.dumps({"HEADLESS": True, "SYNC_MODE": "api_first",
                "STUDENTS": [{"diak_nev": "Teszt", "active": False}]}, ensure_ascii=False),
    encoding="utf-8",
)

probe = work / "probe.py"
probe.write_text(
    """# -*- coding: utf-8 -*-
import asyncio, json, sqlite3, sys
sys.path.insert(0, r'{root}')
import kreta_playwright as k
import kreta_sync
from kreta_api import KretaNetworkError

k.init_db()

JEGY = {
    "esemeny_tipus": "Értékelés", "tantargy": "Matematika", "ertek": "5",
    "szam_ertek": 5, "bej_datum": "2026. 10. 20.",
}
HAZI = {
    "esemeny_tipus": "Házi feladat", "tantargy": "Matematika",
    "bej_datum": "2026. 10. 20.", "hatarido": "2026. 10. 21.",
    "tartalom": "API házi",
}


async def main():
    tracker = kreta_sync.SourceTracker("Teszt")
    calls = []

    def hazi_provider(diak):
        calls.append("hazi")
        k.save_esemenyek_by_type("Teszt", [HAZI], set(), ["Házi feladat"])

    def jegy_provider(diak):
        calls.append("jegyek")
        raise KretaNetworkError("timeout az Ertekelesek végponton")

    await kreta_sync.run_api_datasets(
        {"diak_nev": "Teszt"},
        {"jegyek": jegy_provider, "hazi": hazi_provider},
        tracker, lambda m: None)

    skip = tracker.api_done()

    # Fallback: a jegyek Playwrightból jönnek (kétszer lefuttatva = nincs duplikáció)
    if "jegyek" not in skip:
        k.save_esemenyek_by_type("Teszt", [JEGY], set(), ["Értékelés"])
        kreta_sync.mark_playwright(tracker, "jegyek")
        k.save_esemenyek_by_type("Teszt", [JEGY], set(), ["Értékelés"])

    conn = sqlite3.connect(k.DB_FILE)
    counts = dict(conn.execute(
        "SELECT esemeny_tipus, COUNT(*) FROM esemenyek WHERE diak_nev='Teszt' "
        "GROUP BY esemeny_tipus"))
    hazi_kesz = conn.execute(
        "SELECT kesz FROM esemenyek WHERE esemeny_tipus='Házi feladat'").fetchone()
    conn.close()

    # Az API-ból frissült házi a Playwright futásában sem íródik felül/duplikálódik.
    k.save_esemenyek_by_type("Teszt", [HAZI], set(), ["Házi feladat"])
    conn = sqlite3.connect(k.DB_FILE)
    hazi_db = conn.execute(
        "SELECT COUNT(*) FROM esemenyek WHERE esemeny_tipus='Házi feladat'").fetchone()[0]
    conn.close()

    print("RESULT=" + json.dumps({
        "skip": sorted(skip),
        "calls": calls,
        "jegy_source": tracker.get("jegyek").source,
        "jegy_reason": tracker.get("jegyek").reason,
        "jegy_ok": tracker.get("jegyek").ok,
        "hazi_source": tracker.get("hazi").source,
        "counts": counts,
        "hazi_kesz": hazi_kesz[0] if hazi_kesz else None,
        "hazi_db": hazi_db,
    }, ensure_ascii=False))


asyncio.run(main())
""".replace("{root}", str(ROOT)),
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
    print(result.stderr[-800:])

payload = {}
for line in out.splitlines():
    if line.startswith("RESULT="):
        payload = json.loads(line.split("=", 1)[1])

print("\n4) API-hiba -> Playwright fallback (valódi DB)")
ok(result.returncode == 0, f"a próba lefutott (exit={result.returncode})")
ok(payload.get("calls") == ["jegyek", "hazi"], f"API-hívások: {payload.get('calls')}")
ok(payload.get("skip") == ["hazi"], f"csak a sikeres adatkör kész: {payload.get('skip')}")
ok(payload.get("jegy_source") == "playwright", "a hibás jegy-adatkör Playwrightra váltott")
ok(payload.get("jegy_ok") is True, "a fallback sikeresnek jelölve")
ok("timeout" in (payload.get("jegy_reason") or ""), "a fallback oka naplózva")
ok(payload.get("hazi_source") == "api", "a sikeres adatkör API-forrású maradt")

print("\n5) Nincs duplikált sor")
counts = payload.get("counts") or {}
ok(counts.get("Értékelés") == 1, f"1 értékelés a kétszeri mentés után: {counts.get('Értékelés')}")
ok(counts.get("Házi feladat") == 1, f"1 házi feladat: {counts.get('Házi feladat')}")
ok(payload.get("hazi_db") == 1, "a házi a Playwright ismételt mentése után sem duplikálódik")
ok(payload.get("hazi_kesz") == 0, "a házi 'kesz' jelölése megmarad (0 = még nincs kész)")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
