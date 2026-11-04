# -*- coding: utf-8 -*-
"""
Üzenet AI-elemzése — Kaneo #61.

Fake OpenAI-kompatibilis HTTP-szerverrel ellenőrzi a kliens JSON-kezelését,
a validációt, a magánhálózati őrt, az API végpontot és a több eseményes
`.ics` generálást. Valódi AI-modell nem kell hozzá.
"""
import json
import os
import sqlite3
import sys
import tempfile
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODE = {"bad": False, "content": ""}


class FakeAI(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if MODE["bad"]:
            content = "ez nem json"
        else:
            content = MODE["content"] or json.dumps([
                {"cim": "Szülői értekezlet", "datum": "2026-11-12", "ido": "17:30",
                 "helyszin": "Aula", "leiras": "Rövid megbeszélés"},
                {"cim": "Kirándulás befizetése", "datum": "2026-11-20", "ido": None,
                 "helyszin": "", "leiras": "20 000 Ft"},
            ], ensure_ascii=False)
        body = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAI)
threading.Thread(target=server.serve_forever, daemon=True).start()
AI_URL = f"http://127.0.0.1:{server.server_port}"

work = tempfile.mkdtemp(prefix="kreta_ai_")
db = os.path.join(work, "kreta_adatok.db")
config = {
    "AI": {"ENABLED": True, "URL": AI_URL, "MODEL": "test-model",
           "TIMEOUT_SECONDS": 10, "MAX_INPUT_CHARS": 6000, "ALLOW_CLOUD": False},
    "CALENDAR": {"TIMEZONE": "Europe/Budapest", "REMINDER_MINUTES": 30,
                 "MESSAGE_DURATION_MINUTES": 30},
}
config_path = os.path.join(work, "config.json")
with open(config_path, "w", encoding="utf-8") as f:
    json.dump(config, f, ensure_ascii=False)
os.environ.update({
    "KRETA_DATA_DIR": work,
    "KRETA_DB_FILE": db,
    "KRETA_CONFIG_FILE": config_path,
    "KRETA_LOG_FILE": os.path.join(work, "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csat"),
    "KRETA_SCHEDULER_STATE_FILE": os.path.join(work, "scheduler_state.json"),
    "KRETA_TODAY": "2026-11-04",
})

import kreta_ai  # noqa: E402
import app as kreta  # noqa: E402

_hibak = []


def ok(cond, msg):
    print(("  OK   " if cond else "  HIBA ") + msg)
    if not cond:
        _hibak.append(msg)


print("1) konfiguráció és magánhálózati őr")
cfg = kreta_ai.ai_config(config)
ok(cfg["MODEL"] == "test-model" and cfg["ALLOW_CLOUD"] is False, "a config betöltődik")
private_cfg = dict(cfg, URL="https://api.example.com", ALLOW_CLOUD=False)
try:
    kreta_ai.analyze_text("x", private_cfg)
    ok(False, "felhős URL ALLOW_CLOUD nélkül nem mehet")
except kreta_ai.AiNotConfigured:
    ok(True, "felhős URL ALLOW_CLOUD nélkül elutasítva")

print("\n2) JSON-validáció")
items = kreta_ai.parse_items(
    '```json\n[{"cim":"Teszt","datum":"2026-11-10","ido":"8:05"},'
    '{"cim":"Teszt","datum":"2026-11-10","ido":"08:05"},'
    '{"cim":"Rossz dátum","datum":"nem-dátum"},{"cim":"","datum":"2026-11-11"}]\n```',
    today=date(2026, 11, 4))
ok(len(items) == 1 and items[0]["ido"] == "08:05", f"fence + dedup + validáció ({items})")
ok(items and items[0]["multbeli"] is False, "a jövőbeli dátum jelölése")

print("\n3) AI hívás fake szerverrel")
items = kreta_ai.analyze_text("Tisztelt Szülők! November 12-én 17:30-kor értekezlet.",
                               cfg, today=date(2026, 11, 4))
ok(len(items) == 2 and items[0]["cim"] == "Szülői értekezlet",
   f"a fake AI válasza validálva ({items})")

print("\n4) API végpont")
kreta.init_db_extensions()
conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO uzenetek (diak_nev, felado, targy, idopont, szoveg) VALUES (?,?,?,?,?)",
    ("Teszt Elek", "Iskola", "Novemberi programok",
     "2026. 11. 04. 10:00", "November 12-én 17:30 szülői értekezlet, november 20-ig befizetés."),
)
conn.commit()
conn.close()
client = kreta.app.test_client()
res = client.post("/api/uzenet/1/ai")
body = res.get_json() or {}
ok(res.status_code == 200 and len(body.get("items") or []) == 2,
   f"az AI végpont 200, 2 találat ({res.status_code})")
ok((body.get("items") or [{}])[0].get("google_url", "").startswith(
       "https://calendar.google.com/"), "a találathoz Google-link készül")

res = client.post("/api/naptar/ai/ics", json={"items": body.get("items") or []})
ics = res.get_data(as_text=True)
ok(res.status_code == 200 and ics.count("BEGIN:VEVENT") == 2
   and "text/calendar" in res.headers.get("Content-Type", ""),
   "a kijelölt eseményekből több VEVENT-es .ics készül")
ok(client.post("/api/naptar/ai/ics", json={"items": []}).status_code == 400,
   "üres kijelölés → 400")

print("\n5) hibakezelés")
MODE["bad"] = True
res = client.post("/api/uzenet/1/ai")
ok(res.status_code == 502, f"érvénytelen AI-válasz → 502 ({res.status_code})")
MODE["bad"] = False
cfg_off = dict(config)
cfg_off["AI"] = dict(config["AI"], ENABLED=False)
with open(config_path, "w", encoding="utf-8") as f:
    json.dump(cfg_off, f, ensure_ascii=False)
res = client.post("/api/uzenet/1/ai")
ok(res.status_code == 503, f"kikapcsolt AI → 503 ({res.status_code})")
with open(config_path, "w", encoding="utf-8") as f:
    json.dump(config, f, ensure_ascii=False)
ok(client.post("/api/uzenet/99999/ai").status_code == 404, "ismeretlen üzenet → 404")

server.shutdown()
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
