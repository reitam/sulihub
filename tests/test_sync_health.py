# -*- coding: utf-8 -*-
"""
Szinkron-egészség riasztás (Kaneo #88).

- 3 egymást követő hibás futás -> magas prioritású ntfy, 6 órás throttle;
- token-lejárat/refresh hiba -> külön üzenet;
- siker után reset; a /api/scheduler/status `health` mezőt ad;
- a régi „elavult adat” riasztás (12/24 óra) megmarad.
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="kreta_health_"))
db = work / "kreta_adatok.db"
config = {"STUDENTS": [{"diak_nev": "HealthDiak", "enable_rewards": True, "active": False}],
          "SCHEDULER": {"ENABLED": False, "INTERVAL_MINUTES": 180}}
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

_hibak = []
push = []
kreta.send_notification = lambda title, message, priority=3, tags=None: (
    push.append((title, message, priority)) or True)
kreta.NTFY_TOPIC = "teszt-topic"


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


print("1) Két hiba még nem riaszt, a harmadik igen")
for _ in range(2):
    h = kreta._update_sync_health("error", ["HealthDiak"], "kapcsolódási hiba")
ok(h.get("consecutive_errors") == 2 and not h.get("_alert"),
   f"2 hiba -> nincs riasztás ({h.get('consecutive_errors')})")
h = kreta._update_sync_health("error", ["HealthDiak"], "kapcsolódási hiba")
alert = h.get("_alert")
ok(h.get("consecutive_errors") == 3 and alert is not None,
   f"3. hiba -> riasztás jelölve ({alert is not None})")
ok(alert and alert[2] == 5 and "ismétlődő" in alert[0].lower(),
   f"magas prioritású üzenet: {alert}")
ok(not push, "a health-ellenőrzés nem küld külön push-t (egy üzenet/futás, #128)")

print("\n2) Throttle: 6 órán belül nincs újabb riasztás")
h = kreta._update_sync_health("error", ["HealthDiak"], "kapcsolódási hiba")
ok(h.get("_alert") is None, f"4. hiba throttle alatt: {h.get('_alert')}")
h["last_alert_at"] = (datetime.now() - timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
h.pop("_alert", None)
kreta._sync_health_ment(h)
h = kreta._update_sync_health("error", [], "kapcsolódási hiba")
ok(h.get("_alert") is not None, "7 óra után újra riaszt")

print("\n3) Token-lejárat külön üzenet")
kreta.set_meta(kreta.SYNC_HEALTH_META, "{}")
h = kreta._update_sync_health("error", [], "401 token expired / refresh hiba")
alert = h.get("_alert")
ok(h.get("last_error_type") == "token" and alert is not None,
   f"token hiba -> külön riasztás ({h.get('last_error_type')})")
ok(alert and "jelentkezni" in alert[0].lower(), f"üzenet: {alert}")
h = kreta._update_sync_health("error", [], "token hiba")
ok(h.get("_alert") is None, "token hiba throttle alatt nem spammel")

print("\n4) Siker után reset")
h = kreta._update_sync_health("done", [], "minden rendben")
ok(h.get("consecutive_errors") == 0 and h.get("last_error_type") == ""
   and h.get("_alert") is None, f"siker -> reset: {h}")

print("\n5) A /api/scheduler/status health mezőt ad")
client = kreta.app.test_client()
d = client.get("/api/scheduler/status").get_json()
ok(isinstance(d.get("health"), dict) and "consecutive_errors" in d["health"],
   f"health a státuszban: {d.get('health')}")
ok("_alert" not in (d.get("health") or {}), "a belső _alert nem perzisztálódik")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
