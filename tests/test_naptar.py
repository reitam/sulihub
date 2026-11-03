# -*- coding: utf-8 -*-
"""
Naptárbejegyzés generálás — Kaneo #47.

A házi feladat / számonkérés és az üzenet alapján készülő Google Naptár-link
és `.ics` tartalom helyességét ellenőrzi, valamint az API végpontokat
(temp adatbázison, valódi hálózati hívás nélkül).
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

work = tempfile.mkdtemp(prefix="kreta_naptar_")
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

import kreta_naptar as naptar  # noqa: E402
import app as kreta  # noqa: E402

_hibak = []


def ok(cond, msg):
    print(("  OK   " if cond else "  HIBA ") + msg)
    if not cond:
        _hibak.append(msg)


print("1) konfiguráció")
cfg = naptar.calendar_config({})
ok(cfg["TIMEZONE"] == "Europe/Budapest" and cfg["REMINDER_MINUTES"] == 30,
   f"alapértékek ({cfg})")
cfg2 = naptar.calendar_config({"CALENDAR": {"REMINDER_MINUTES": 999,
                                            "MESSAGE_DURATION_MINUTES": 60,
                                            "TIMEZONE": "Europe/Vienna"}})
ok(cfg2["REMINDER_MINUTES"] == 240 and cfg2["MESSAGE_DURATION_MINUTES"] == 60
   and cfg2["TIMEZONE"] == "Europe/Vienna", "a config felülírja és korlátozza az értékeket")

print("\n2) dátumformák")
ok(naptar.parse_datetime("2026. 09. 09.").date().isoformat() == "2026-09-09",
   "magyar dátum")
ok(naptar.parse_datetime("2026. 05. 11. 15:48").strftime("%H:%M") == "15:48",
   "magyar dátum + idő")
ok(naptar.parse_datetime("2026-05-11 15:48").strftime("%H:%M") == "15:48",
   "ISO-szerű dátum + idő")
ok(naptar.parse_datetime("-") is None and naptar.parse_datetime("") is None,
   "hiányzó dátum → None")

print("\n3) esemény → Google-link és .ics")
esemeny = {
    "id": 32, "diak_nev": "Teszt Elek", "esemeny_tipus": "Házi feladat",
    "tantargy": "Magyar nyelv", "hatarido": "2026. 09. 09.",
    "tema": "Ismétlés", "cim": "Füzet", "tartalom": "5-6. oldal; gyűjtés",
    "ertekelo": "Minta Gáborné", "mod": "-",
}
ev = naptar.event_from_esemeny(esemeny, cfg)
ok(ev and ev["all_day"] and ev["start"].date().isoformat() == "2026-09-09",
   "a határidő egész napos esemény")
ok("Házi feladat" in ev["title"] and "Magyar nyelv" in ev["title"],
   f"a cím tartalmazza a tantárgyat és a típust ('{ev['title']}')")
url = naptar.google_calendar_url(ev, cfg)
ok("action=TEMPLATE" in url and "dates=20260909%2F20260910" in url,
   "a Google-link előre kitöltött, egész napos (end exkluzív)")
ok("H%C3%A1zi" in url or "H%C3%A1zi%20feladat" in url, "a cím URL-kódolt")
ics = naptar.ics_content(ev, cfg, now=datetime(2026, 11, 4, tzinfo=timezone.utc))
ok(ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n"),
   "az .ics szabványos keret, CRLF")
ok("DTSTART;VALUE=DATE:20260909" in ics and "DTEND;VALUE=DATE:20260910" in ics,
   "az .ics egész napos dátuma helyes")
ok("SUMMARY:" in ics and "Ismétlés" in ics and "\\;" in ics,
   "a leírásban a pontosvessző escape-elve van")
ok("BEGIN:VALARM" in ics and "TRIGGER:-PT30M" in ics, "van 30 perces emlékeztető")

print("\n4) üzenet → időpontos esemény")
uzenet = {
    "id": 1, "diak_nev": "Teszt Elek", "felado": "Iskola", "targy": "Kirándulás",
    "idopont": "2026. 05. 11. 15:48", "szoveg": "Kedves Szülők!",
}
msg = naptar.event_from_uzenet(uzenet, cfg)
ok(msg and not msg["all_day"] and msg["start"].strftime("%H:%M") == "15:48",
   "az üzenet időpontos esemény")
murl = naptar.google_calendar_url(msg, cfg)
ok("dates=20260511T154800%2F20260511T161800" in murl and "ctz=Europe%2FBudapest" in murl,
   "a Google-link időpontos és időzónás")
mics = naptar.ics_content(msg, cfg, now=datetime(2026, 11, 4, tzinfo=timezone.utc))
ok("DTSTART:20260511T134800Z" in mics, "az .ics UTC-re váltja a nyári időt (13:48Z)")

print("\n5) emlékeztető nélkül")
no_alarm = naptar.calendar_config({"CALENDAR": {"REMINDER_MINUTES": 0}})
ok("VALARM" not in naptar.ics_content(ev, no_alarm), "0 percnél nincs VALARM")

print("\n6) API végpontok (temp adatbázis)")
kreta.init_db_extensions()
conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, hatarido, tema, cim, "
    "tartalom, ertekelo, mod, kesz) VALUES (?,?,?,?,?,?,?,?,?,0)",
    ("Teszt Elek", "Házi feladat", "Matematika", "2026. 11. 10.",
     "Törtek", "", "Feladatgyűjtemény", "Tanár", ""),
)
conn.execute(
    "INSERT INTO uzenetek (diak_nev, felado, targy, idopont, szoveg) VALUES (?,?,?,?,?)",
    ("Teszt Elek", "Iskola", "Szülői értekezlet", "2026. 11. 12. 17:30", "Részletek"),
)
conn.commit()
event_id = conn.execute("SELECT id FROM esemenyek").fetchone()[0]
msg_id = conn.execute("SELECT id FROM uzenetek").fetchone()[0]
conn.close()

client = kreta.app.test_client()
res = client.get(f"/api/naptar/esemeny/{event_id}")
body = res.get_json() or {}
ok(res.status_code == 200 and body.get("status") == "ok", "esemény info 200")
ok(body.get("google_url", "").startswith("https://calendar.google.com/")
   and body.get("ics_url", "").endswith(".ics"),
   "az info tartalmaz Google-linket és .ics URL-t")

res = client.get(f"/api/naptar/esemeny/{event_id}.ics")
ok(res.status_code == 200 and "text/calendar" in res.headers.get("Content-Type", ""),
   "az .ics letöltés content-type helyes")
ok("BEGIN:VEVENT" in res.get_data(as_text=True)
   and "attachment" in res.headers.get("Content-Disposition", ""),
   "az .ics letöltés mellékletként jön")

res = client.get(f"/api/naptar/uzenet/{msg_id}")
body = res.get_json() or {}
ok(res.status_code == 200 and body.get("all_day") is False,
   "üzenet info 200, időpontos")

ok(client.get("/api/naptar/esemeny/99999").status_code == 404, "ismeretlen esemény → 404")
ok(client.get("/api/naptar/uzenet/99999").status_code == 404, "ismeretlen üzenet → 404")
ok(client.get("/api/naptar/ismeretlen/1").status_code == 404, "ismeretlen típus → 404")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
