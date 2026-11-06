# -*- coding: utf-8 -*-
"""Opcionális basic auth (Kaneo #16) — temp konfigurációval."""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = tempfile.mkdtemp(prefix="kreta_auth_")
db = os.path.join(work, "kreta_adatok.db")
config_path = os.path.join(work, "config.json")
os.environ.update({
    "KRETA_DATA_DIR": work,
    "KRETA_DB_FILE": db,
    "KRETA_CONFIG_FILE": config_path,
    "KRETA_LOG_FILE": os.path.join(work, "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csat"),
    "KRETA_SCHEDULER_STATE_FILE": os.path.join(work, "scheduler_state.json"),
})
sys.path.insert(0, str(ROOT))
from werkzeug.security import generate_password_hash  # noqa: E402
import app as kreta  # noqa: E402

_hibak = []


def ok(cond, msg):
    print(("  OK   " if cond else "  HIBA ") + msg)
    if not cond:
        _hibak.append(msg)


def write_config(enabled, password_hash=""):
    cfg = {
        "AUTH": {"ENABLED": enabled, "USERNAME": "teszt", "PASSWORD_HASH": password_hash},
        "STUDENTS": [],
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)


def auth_header(user="teszt", password="jelszo"):
    raw = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": "Basic " + raw}


kreta.init_db_extensions()
client = kreta.app.test_client()

print("1) kikapcsolt auth")
write_config(False)
ok(client.get("/").status_code == 200, "kikapcsolva a felület elérhető")

print("\n2) bekapcsolt auth")
write_config(True, generate_password_hash("jelszo"))
res = client.get("/")
ok(res.status_code == 401, f"bejelentkezés nélkül 401 ({res.status_code})")
ok("Basic" in res.headers.get("WWW-Authenticate", ""), "van WWW-Authenticate fejléc")
ok(client.get("/health").status_code == 200, "a /health auth nélkül is elérhető")
ok(client.get("/static/favicon.svg").status_code == 401, "a statikus fájl is védett")
ok(client.get("/", headers=auth_header()).status_code == 200, "helyes jelszóval 200")
ok(client.get("/", headers=auth_header(password="rossz")).status_code == 401,
   "rossz jelszóval 401")
ok(client.get("/", headers=auth_header(user="mas")).status_code == 401,
   "rossz felhasználóval 401")

print("\n3) sima jelszó (csak teszt/átmeneti)")
write_config(True, "")
cfg = json.load(open(config_path, encoding="utf-8"))
cfg["AUTH"]["PASSWORD"] = "titok"
with open(config_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False)
ok(client.get("/", headers=auth_header(password="titok")).status_code == 200,
   "PASSWORD mezővel is működik")
ok(client.get("/", headers=auth_header(password="jelszo")).status_code == 401,
   "a régi jelszó nem jó")

print("\n4) A blueprint-ek is védettek (KRÉ-14: app-szintű before_request)")
write_config(True, generate_password_hash("jelszo"))
api_checks = ["/api/esemenyek", "/api/statisztika", "/api/orarend", "/api/uzenetek",
              "/api/kifizetesek/export.xlsx"]
for path in api_checks:
    no_auth = client.get(path)
    with_auth = client.get(path, headers=auth_header())
    ok(no_auth.status_code == 401 and with_auth.status_code != 401,
       f"{path}: auth nélkül 401 ({no_auth.status_code}), helyes jelszóval {with_auth.status_code}")
res = client.post("/api/sync/start")
ok(res.status_code == 401, f"POST /api/sync/start auth nélkül 401 ({res.status_code})")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
