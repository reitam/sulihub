# -*- coding: utf-8 -*-
"""
KRÉ-8 teszt: esti digest (napi események gyermekenként, 19:30-kor).

1) Adatgyűjtés + szövegépítés (jegy súlyozással, házi, dolgozat, feljegyzés,
   hiányzás, igazolás, üzenet; holnap esedékes tételek; üres nap).
2) Küldési döntés (idempotencia, időpont, kikapcsolás).
3) Integráció: `app._maybe_send_digests` fake ntfy-val + a beállítás API.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_digest_"))
db = work / "kreta_adatok.db"

(work / "config.json").write_text(json.dumps({
    "SCHEDULER": {"ENABLED": False},
    "DIGEST": {"ENABLED": True, "TIME": "19:30", "INCLUDE_NAMES": True},
    "STUDENTS": [
        {"diak_nev": "Teszt Anna", "active": True},
        {"diak_nev": "Teszt Béla", "active": True},
    ],
}, ensure_ascii=False), encoding="utf-8")

os.environ.update({
    "KRETA_DATA_DIR": str(work),
    "KRETA_DB_FILE": str(db),
    "KRETA_CONFIG_FILE": str(work / "config.json"),
    "KRETA_LOG_FILE": str(work / "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": str(work / "csat"),
    "KRETA_SCHEDULER_STATE_FILE": str(work / "scheduler_state.json"),
    "NTFY_TOPIC": "teszt/topic",
    "PYTHONIOENCODING": "utf-8",
})
sys.path.insert(0, str(ROOT))

subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=os.environ.copy(), capture_output=True, timeout=120)

import app  # noqa: E402
import kreta_digest  # noqa: E402

app.init_db_extensions()

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


TODAY = date.today()
HOLNAP = TODAY + timedelta(days=1)
TEGNAP = TODAY - timedelta(days=1)


def hu(d):
    return f"{d.year}. {d.month:02d}. {d.day:02d}."


def iso(d):
    return d.isoformat()


conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " suly_szazalek, tanev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "Értékelés", "Matematika", "Jeles(5)", 5, hu(TODAY), "",
     "Erl Andrea", "Évközi jegy/értékelés", "Írásbeli dolgozat", "Halmazok", "", "", 0,
     100, "2026/2027"))
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " suly_szazalek, tanev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "Értékelés", "Irodalom", "Jó(4)", 4, hu(TEGNAP), "",
     "Szőke Gáborné", "", "Felelet", "", "", "", 0, 0, "2026/2027"))
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " suly_szazalek, tanev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "Házi feladat", "Magyar nyelv", "", 0, hu(TODAY), hu(HOLNAP),
     "Szőke Gáborné", "", "", "", "",
     "5 ige meghatározása a tanult módon: módja, ideje.", 0, 0, "2026/2027"))
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " suly_szazalek, tanev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "Bejelentett számonkérés", "Biológia", "", 0, hu(TODAY),
     hu(TODAY + timedelta(days=4)), "Füzesi Zsanett", "", "Írásbeli",
     "Keringés és immunitás", "", "", 0, 0, "2026/2027"))
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " suly_szazalek, tanev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "Feljegyzés", "", "", 0, hu(TODAY), "", "Szőke Gáborné",
     "Osztályfőnöki dicséret", "", "", "Rajzpályázat", "Szép munka", 0, 0, "2026/2027"))
# Holnap esedékes, korábban feladott házi + dolgozat
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " suly_szazalek, tanev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "Házi feladat", "Történelem", "", 0, hu(TODAY - timedelta(days=2)),
     hu(HOLNAP), "Szőke Gáborné", "", "", "", "", "Tk. 32. o.", 0, 0, "2026/2027"))
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " suly_szazalek, tanev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "Házi feladat", "Fizika", "", 0, hu(TODAY - timedelta(days=3)),
     hu(HOLNAP), "Németh Ildikó", "", "", "", "", "Kész házi", 1, 0, "2026/2027"))
conn.execute(
    "INSERT INTO hianyzasok (diak_nev, kreta_id, mulasztas_datum, ora_sorszam, perc,"
    " tantargy, tema, tanar, mulasztas_tipus, igazolt, tanorai_celu, igazolas_tipus,"
    " rogzites_datum, tanev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "1", iso(TODAY), 3, None, "Matematika", "", "Erl Andrea",
     "Hiányzás", 0, "", "", iso(TODAY), "2026/2027"))
conn.execute(
    "INSERT INTO igazolasok (diak_nev, kreta_id, kezdete, vege, igazolas_tipus, megjegyzes, tanev)"
    " VALUES (?,?,?,?,?,?,?)",
    ("Teszt Anna", "10", iso(TODAY), iso(TODAY), "Orvosi igazolás", "EESZT", "2026/2027"))
conn.execute(
    "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg,"
    " csatolmany_nev, csatolmany_utvonal, olvasott, tanev)"
    " VALUES (?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "20", "Szőke Gáborné (tanár)", "Ünneplő öltözet",
     f"{hu(TODAY)} 8:05", "Szöveg", "", "", 0, "2026/2027"))
conn.commit()
conn.close()


def fake_send(calls):
    def _send(title, message, priority=3, tags=None):
        calls.append({"title": title, "message": message})
        return True
    return _send


print("1) Adatgyűjtés és szöveg")
conn = app.get_db_connection()
adat = kreta_digest.collect_day(conn, "Teszt Anna", TODAY)
conn.close()
ok(len(adat["jegyek"]) == 1, f"csak a mai jegy (a tegnapi nem): {len(adat['jegyek'])}")
ok(adat["jegyek"][0]["suly"] == 100, "a jegy súlyszázaléka megvan")
ok(len(adat["hazi"]) == 1, f"a ma feladott házi: {len(adat['hazi'])}")
ok(len(adat["dolgozatok"]) == 1, "a ma bejelentett dolgozat megvan")
ok(len(adat["feljegyzesek"]) == 1, "a mai feljegyzés megvan")
ok(len(adat["hianyzasok"]) == 1 and adat["hianyzasok"][0]["igazolt"] == 0,
   "a mai igazolatlan hiányzás megvan")
ok(len(adat["igazolasok"]) == 1, "a mai igazolás megvan")
ok(len(adat["uzenetek"]) == 1, "a mai üzenet megvan")
ok(adat["olvasatlan_db"] == 1, "1 olvasatlan üzenet")
ok(len(adat["holnapi_hataridok"]) == 2,
   f"holnapra 2 tétel (házi + dolgozat, a kész házi nélkül): {len(adat['holnapi_hataridok'])}")

cim, torzs = kreta_digest.build_message("Teszt Anna", TODAY, adat, True)
ok("Teszt Anna" in cim and TODAY.strftime("%Y") in cim, f"cím: {cim}")
ok("📊 Jegyek (1)" in torzs, "jegy-szekció")
ok("Matematika — Jeles(5) (100%)" in torzs, f"jegy súlyozással: {torzs[:80]!r}")
ok("📚 Házi feladat (1)" in torzs, "házi-szekció (csak a mai)")
ok("határidő: " in torzs, "házi határidővel")
ok("📝 Dolgozatok (1)" in torzs and "Biológia" in torzs, "dolgozat-szekció")
ok("📌 Feljegyzés (1)" in torzs, "feljegyzés-szekció")
ok("IGAZOLATLAN" in torzs, "igazolatlan hiányzás kiemelve")
ok("📄 Igazolás (1)" in torzs, "igazolás-szekció")
ok("✉️ Üzenetek (1)" in torzs and "Ünneplő öltözet" in torzs, "üzenet-szekció")
ok("📅 Holnap esedékes (2)" in torzs, "holnapi határidők szekció")
ok("Fizika" not in torzs, "a kész házi nem szerepel a holnapi listában")

cim2, torzs2 = kreta_digest.build_message("Teszt Béla", TODAY,
                                          {"jegyek": [], "hazi": [], "dolgozatok": [],
                                           "feljegyzesek": [], "hianyzasok": [],
                                           "igazolasok": [], "uzenetek": [],
                                           "holnapi_hataridok": [], "olvasatlan_db": 0},
                                          True)
ok(torzs2 == "Ma nem történt esemény, holnapra nincs esedékes feladat.",
   f"üres nap szövege: {torzs2!r}")
cim3, _ = kreta_digest.build_message("Teszt Béla", TODAY, {}, False)
ok("Teszt Béla" not in cim3, f"név nélküli cím: {cim3!r}")

# Több napot átfogó (manuális) összefoglaló
conn = app.get_db_connection()
adat_multi = kreta_digest.collect_range(conn, "Teszt Anna", TEGNAP, TODAY)
conn.close()
ok(len(adat_multi["jegyek"]) == 2,
   f"a tegnapi + mai jegy együtt: {len(adat_multi['jegyek'])}")
cim_r, torzs_r = kreta_digest.build_message("Teszt Anna", TODAY, adat_multi, True,
                                            kezdo=TEGNAP)
ok(TEGNAP.strftime("%Y") in cim_r and " – " in cim_r, f"időszakos cím: {cim_r}")
ok(torzs_r.startswith("Időszak:"), f"az időszak a törzs elején: {torzs_r.splitlines()[0]!r}")
_, torzs_ures = kreta_digest.build_message("Teszt Anna", TODAY, {}, True, kezdo=TEGNAP)
ok(torzs_ures == "Az utolsó automatikus összefoglaló óta nem történt esemény.",
   f"üres időszak szövege: {torzs_ures!r}")

print("\n2) Küldési döntés")
settings = {"enabled": True, "time": "19:30", "include_names": True}
ok(not kreta_digest.should_send(settings, "", datetime(2026, 11, 11, 19, 0)), "19:00-kor még nem")
ok(kreta_digest.should_send(settings, "", datetime(2026, 11, 11, 19, 30)), "19:30-kor igen")
ok(not kreta_digest.should_send(settings, "2026-11-11", datetime(2026, 11, 11, 20, 0)),
   "ugyanazon a napon nem ismétel")
ok(kreta_digest.should_send(settings, "2026-11-10", datetime(2026, 11, 11, 19, 30)),
   "másnap újra megy")
ok(not kreta_digest.should_send({"enabled": False}, "", datetime(2026, 11, 11, 20, 0)),
   "kikapcsolva nem megy")
ok(not kreta_digest.should_send(settings, "", datetime(2026, 11, 11, 23, 10)),
   "23 óra után nem megy")

parsed, errors = kreta_digest.parse_settings({"TIME": "25:99"})
ok(errors and parsed["time"] == "19:30", "hibás idő -> hiba + alapérték")
parsed, errors = kreta_digest.parse_settings({"time": "7:5", "enabled": False})
ok(not errors and parsed["time"] == "07:05" and parsed["enabled"] is False,
   f"idő normalizálása: {parsed}")
merged = kreta_digest.load_settings({"ENABLED": True, "TIME": "19:30"},
                                    json.dumps({"time": "20:15"}))
ok(merged["time"] == "20:15" and merged["enabled"] is True,
   "app_meta felülírja a configot, a többi érték megmarad")

print("\n3) Integráció: esti küldés (fake ntfy)")
calls = []
app.send_notification = fake_send(calls)
app.NTFY_TOPIC = "teszt/topic"

n = app._maybe_send_digests(now=datetime(TODAY.year, TODAY.month, TODAY.day, 19, 0))
ok(n == 0 and not calls, "19:00 előtt nincs küldés")

n = app._maybe_send_digests(now=datetime(TODAY.year, TODAY.month, TODAY.day, 19, 30))
ok(n == 2, f"19:30-kor 2 gyermek -> 2 üzenet: {n}")
ok(len(calls) == 2, f"2 push ment ki: {len(calls)}")
last_auto = app.get_meta(kreta_digest.DIGEST_LAST_AT_PREFIX + "Teszt Anna", "")
ok(last_auto.startswith(TODAY.isoformat()), f"az automata időpontja mentve: {last_auto}")
anna = next((c for c in calls if "Teszt Anna" in c["title"]), {})
bela = next((c for c in calls if "Teszt Béla" in c["title"]), {})
ok("📊 Jegyek (1)" in anna.get("message", ""), "Anna üzenetében ott a mai jegy")
ok(bela.get("message") == "Ma nem történt esemény, holnapra nincs esedékes feladat.",
   f"Béla üres napja is megjön: {bela.get('message')!r}")

n = app._maybe_send_digests(now=datetime(TODAY.year, TODAY.month, TODAY.day, 21, 0))
ok(n == 0 and len(calls) == 2, "ugyanazon a napon nem megy ki újra")

MASNAP = TODAY + timedelta(days=1)
n = app._maybe_send_digests(now=datetime(MASNAP.year, MASNAP.month, MASNAP.day, 19, 30))
ok(n == 2 and len(calls) == 4, f"másnap újra 2 üzenet: {n}")

app.set_meta(kreta_digest.DIGEST_SETTINGS_META, json.dumps({"enabled": False}))
n = app._maybe_send_digests(now=datetime(MASNAP.year, MASNAP.month, MASNAP.day, 20, 0))
ok(n == 0, "kikapcsolt állapotban nincs küldés")
app.set_meta(kreta_digest.DIGEST_SETTINGS_META, json.dumps({"enabled": True, "time": "19:30"}))
app.NTFY_TOPIC = ""
n = app._maybe_send_digests(now=datetime(MASNAP.year, MASNAP.month, MASNAP.day, 20, 0))
ok(n == 0, "ntfy topic nélkül nincs küldés")
app.NTFY_TOPIC = "teszt/topic"

print("\n4) Manuális összefoglaló (az utolsó automata óta)")
client = app.app.test_client()
sent_key = kreta_digest.DIGEST_SENT_PREFIX + "Teszt Anna"
last_key = kreta_digest.DIGEST_LAST_AT_PREFIX + "Teszt Anna"
before_sent = app.get_meta(sent_key, "")
before_last = app.get_meta(last_key, "")

calls.clear()
res = client.post("/api/digest/run", json={})
ok(res.status_code == 200, f"POST /api/digest/run: {res.status_code}")
results = (res.get_json() or {}).get("results") or []
ok(len(results) == 2 and len(calls) == 2, f"2 diák -> 2 push: {len(results)}")
anna = next((r for r in results if r["diak"] == "Teszt Anna"), {})
ok(anna.get("kezdo") == TODAY.isoformat(),
   f"az automata napja után: mai naptól: {anna.get('kezdo')}")
ok(app.get_meta(sent_key, "") == before_sent, "a napi jelölő nem változott")
ok(app.get_meta(last_key, "") == before_last, "az automata időpontja nem változott")

# Ha régebben ment ki az automata, a hiányzó napokat is hozza.
app.set_meta(last_key, (TODAY - timedelta(days=3)).isoformat() + "T19:30:00")
calls.clear()
res = client.post("/api/digest/run", json={"diak": "Teszt Anna"})
r = ((res.get_json() or {}).get("results") or [{}])[0]
ok(r.get("kezdo") == (TODAY - timedelta(days=2)).isoformat(),
   f"3 nappal korábbi automata -> 2 nappal korábbi kezdet: {r.get('kezdo')}")
ok(len(calls) == 1, "csak a kért diák")
app.set_meta(last_key, before_last)
res = client.post("/api/digest/run", json={"diak": "Nincs Ilyen"})
ok(res.status_code == 400, "ismeretlen diák -> 400")

print("\n5) Beállítás API")
res = client.get("/api/digest/settings")
ok(res.status_code == 200, f"GET settings: {res.status_code}")
data = res.get_json()
ok(data["settings"]["time"] == "19:30" and data["ntfy_configured"] is True,
   f"alap beállítások: {data}")
ok("last_auto" in data, f"a válaszban ott az utolsó automata időpontja: {data.get('last_auto')}")

res = client.put("/api/digest/settings", json={"time": "25:99"})
ok(res.status_code == 400 and res.get_json().get("errors"), "hibás idő -> 400")

res = client.put("/api/digest/settings",
                 json={"enabled": True, "time": "20:15", "include_names": False})
ok(res.status_code == 200, f"PUT settings: {res.status_code}")
res = client.get("/api/digest/settings")
data = res.get_json()["settings"]
ok(data["time"] == "20:15" and data["include_names"] is False,
   f"a mentett beállítás visszaolvasható: {data}")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
