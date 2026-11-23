# -*- coding: utf-8 -*-
"""
#128: szinkron-push politika.

- hiba / részleges hiba: mindig egy üzenet;
- új információ: egy üzenet, **csak a futás deltájával** (a `letrehozva`
  first-seen időbélyeg és a futás kezdete alapján), a napi digest formájában;
- a nap korábbi tételei és a „Holnap esedékes" blokk **nem** ismétlődnek
  (azok az esti digestben vannak);
- sikeres, változás nélküli futás: nincs üzenet;
- a health-riasztás (token / ismétlődő hiba) ugyanabba az egy üzenetbe kerül.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_push_"))
db = work / "kreta_adatok.db"
config = {
    "STUDENTS": [{"diak_nev": "Teszt Anna", "enable_rewards": True, "active": False}],
    "SCHEDULER": {"ENABLED": False, "INTERVAL_MINUTES": 180},
}
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

subprocess.run([sys.executable, "kreta_playwright.py", "--init-db"], cwd=str(ROOT),
               env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

sys.path.insert(0, str(ROOT))
import app as kreta  # noqa: E402

kreta.init_db_extensions()

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


TODAY = date.today()
HOLNAP = TODAY + timedelta(days=1)

# A futás kezdete (a „since” cutoff) és a hozzá képest új / korábbi sorok.
RUNTIME = datetime.now().replace(microsecond=0)
STAMP_NEW = (RUNTIME + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
STAMP_OLD = (RUNTIME - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")


def hu(d):
    return f"{d.year}. {d.month:02d}. {d.day:02d}."


PUSH = []
kreta.send_notification = lambda title, message, priority=3, tags=None: (
    PUSH.append({"title": title, "message": message, "priority": priority,
                 "tags": tags or []}) or True)
kreta.NTFY_TOPIC = "teszt-topic"
kreta.NTFY_NOTIFY_NEW = True
kreta.NTFY_INCLUDE_NAMES = True

# ── Minta adatok: egy új és egy korábbi sor minden adatkörből ────────────────
conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " suly_szazalek, tanev, letrehozva) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "Értékelés", "Matematika", "Jeles(5)", 5, hu(TODAY), "",
     "Kovács Anna", "Évközi jegy/értékelés", "Írásbeli", "Törtek", "", "", 0,
     100, "2026/2027", STAMP_NEW))
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " suly_szazalek, tanev, letrehozva) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "Értékelés", "Történelem", "Jó(4)", 4, hu(TODAY), "",
     "Kovács Anna", "Évközi jegy/értékelés", "Felelet", "Ókori Egyiptom", "", "", 0,
     50, "2026/2027", STAMP_OLD))
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
    " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz,"
    " suly_szazalek, tanev, letrehozva) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "Házi feladat", "Magyar nyelv", "", 0, hu(TODAY), hu(HOLNAP),
     "Kovács Anna", "", "", "", "",
     "5 ige meghatározása a tanult módon.", 0, 0, "2026/2027", STAMP_NEW))
conn.execute(
    "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg,"
    " csatolmany_nev, csatolmany_utvonal, olvasott, tanev, letrehozva)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "20", "Szülő", "Tankönyv", f"{hu(TODAY)} 8:05",
     "Szöveg", "", "", 0, "2026/2027", STAMP_NEW))
conn.execute(
    "INSERT INTO uzenetek (diak_nev, uzenet_id, felado, targy, idopont, szoveg,"
    " csatolmany_nev, csatolmany_utvonal, olvasott, tanev, letrehozva)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
    ("Teszt Anna", "19", "Szülő", "Régi üzenet", f"{hu(TODAY)} 7:05",
     "Szöveg", "", "", 0, "2026/2027", STAMP_OLD))
conn.commit()
conn.close()

print("1) Új információ -> egy push, csak a futás deltájával")
PUSH.clear()
sent = kreta.notify_sync_result(
    "done", [], "scheduled", 1.2, 3, 3,
    {"Teszt Anna": {"Értékelés": 1, "Házi feladat": 1}}, {"Teszt Anna": 1}, {},
    since=RUNTIME)
ok(sent is True and len(PUSH) == 1, f"egy üzenet ment el ({len(PUSH)})")
if PUSH:
    u = PUSH[0]
    ok("új adatok" in u["title"].lower(), f"cím: {u['title']}")
    ok("ütemezett futás" in u["message"] and "3/3 diák frissült" in u["message"],
       "a futás összegzése benne van")
    ok("Matematika" in u["message"] and "100%" in u["message"]
       and "Törtek" in u["message"],
       "az új jegy minden részlete benne van (tantárgy, súly, téma)")
    ok("Történelem" not in u["message"],
       "a korábbi (nem ebben a futásban beérkezett) jegy NEM ismétlődik")
    ok("Házi feladat" in u["message"] and "Magyar nyelv" in u["message"],
       "az új házi is benne van")
    ok("Holnap esedékes" not in u["message"],
       "a holnapi határidők NEM kerülnek a szinkron-pushba (az esti digesté)")
    ok("Tankönyv" in u["message"], "az új üzenet is benne van")
    ok("Régi üzenet" not in u["message"],
       "a korábbi üzenet nem ismétlődik")
    ok("Ma nem történt esemény" not in u["message"],
       "az üres napi szöveg nem kerül a delta push-ba")

print("\n2) Sikeres futás új információ nélkül -> nincs push")
PUSH.clear()
sent = kreta.notify_sync_result("done", [], "manual", 1.2, 3, 3, {}, {}, {}, since=RUNTIME)
ok(sent is False and not PUSH, "nincs üzenet")

print("\n3) NOTIFY_NEW=false -> új adatról sem küld")
kreta.NTFY_NOTIFY_NEW = False
PUSH.clear()
sent = kreta.notify_sync_result(
    "done", [], "manual", 1.2, 3, 3,
    {"Teszt Anna": {"Értékelés": 1}}, {}, {}, since=RUNTIME)
ok(sent is False and not PUSH, "nincs üzenet")
kreta.NTFY_NOTIFY_NEW = True

print("\n4) Részleges hiba új adattal -> egy üzenet, a delta részletekkel")
PUSH.clear()
sent = kreta.notify_sync_result(
    "done_with_errors", ["Teszt Anna"], "scheduled", 2.3, 2, 3,
    {"Teszt Anna": {"Értékelés": 1}}, {}, {}, since=RUNTIME)
ok(sent is True and len(PUSH) == 1, f"egy üzenet ment el ({len(PUSH)})")
if PUSH:
    u = PUSH[0]
    ok("részleges hiba" in u["title"].lower(), f"cím: {u['title']}")
    ok("Nem frissült: Teszt Anna" in u["message"], "a hibás diák benne van")
    ok("Matematika" in u["message"], "az új adat részlete is benne van")

print("\n5) Végzetes hiba -> egy magas prioritású üzenet")
PUSH.clear()
sent = kreta.notify_sync_result("error", [], "manual", 1.0)
ok(sent is True and len(PUSH) == 1, f"egy üzenet ment el ({len(PUSH)})")
if PUSH:
    ok("HIBA" in PUSH[0]["title"] and PUSH[0]["priority"] == 4,
       f"cím/prioritás: {PUSH[0]['title']} / {PUSH[0]['priority']}")

print("\n6) Health-riasztás ugyanabban az egy üzenetben")
PUSH.clear()
alert = ("KRÉTA: újra be kell jelentkezni",
         "A szinkron tokenje lejárt.", 4, ["key"])
sent = kreta.notify_sync_result("error", [], "manual", 1.0, health_alert=alert)
ok(sent is True and len(PUSH) == 1, f"egy üzenet ment el ({len(PUSH)})")
if PUSH:
    u = PUSH[0]
    ok("jelentkezni" in u["title"].lower(), f"a health-cím: {u['title']}")
    ok("tokenje lejárt" in u["message"] and "hibával ért véget" in u["message"],
       "a health-üzenet és a futás összegzése is benne van")

print("\n7) Név nélküli mód")
kreta.NTFY_INCLUDE_NAMES = False
PUSH.clear()
kreta.notify_sync_result(
    "done", [], "manual", 1.2, 1, 1,
    {"Teszt Anna": {"Értékelés": 1}}, {}, {}, since=RUNTIME)
ok(len(PUSH) == 1 and "1. gyermek" in PUSH[0]["message"]
   and "Teszt Anna" not in PUSH[0]["message"],
   "diáknév nélkül is érthető a delta üzenet")
kreta.NTFY_INCLUDE_NAMES = True

print("\n8) Ha a DB-ből nincs megjeleníthető új sor, a darabszámos összegzés marad")
PUSH.clear()
kreta.notify_sync_result(
    "done", [], "manual", 1.2, 1, 1,
    {"Teszt Béla": {"Értékelés": 1}}, {}, {}, since=RUNTIME)
ok(len(PUSH) == 1 and "Teszt Béla: 1 jegy" in PUSH[0]["message"],
   f"a darabszámos fallback látszik: {PUSH[0]['message'] if PUSH else ''!r}")

print("\n9) Hosszú üzenet a korlát alatt marad")
hosszu = "\n".join("• sor %d" % i for i in range(1000))
limited = kreta._limit_ntfy_message(hosszu)
ok(len(limited.encode("utf-8")) <= kreta.NTFY_MESSAGE_LIMIT
   and limited.endswith("a felületen)"),
   f"a törzs {len(limited.encode('utf-8'))} bájt a {kreta.NTFY_MESSAGE_LIMIT} korlát alatt")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
