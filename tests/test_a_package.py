# -*- coding: utf-8 -*-
"""A-csomag tesztek: részleges hiba, ntfy, napló-rotáció/tail, konzisztencia."""
import os, sys
from pathlib import Path
import json, tempfile, shutil, time, re

work = tempfile.mkdtemp(prefix="kreta_a_")
log_path = os.path.join(work, "sync.log")

os.environ.update({
    "KRETA_DATA_DIR": work,
    "KRETA_DB_FILE": os.path.join(work, "nincs.db"),
    "KRETA_CONFIG_FILE": os.path.join(work, "config.json"),
    "KRETA_LOG_FILE": log_path,
    "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csat"),
    "KRETA_SCHEDULER_STATE_FILE": os.path.join(work, "scheduler_state.json"),
    "NTFY_TOPIC": "",          # alapból nincs értesítés
})
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as kreta

_hibak = []

def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)


# ── A1: részleges hiba ────────────────────────────────────────────────────────
class FakeStdout:
    def __init__(self, lines):
        self._it = iter(lines)
    def readline(self):
        return next(self._it, "")
    def close(self):
        pass


class FakeProc:
    def __init__(self, lines, code):
        self.stdout = FakeStdout(lines)
        self.returncode = code
    def wait(self):
        return self.returncode
    def kill(self):
        pass


def fake_popen(lines, code):
    return lambda *a, **k: FakeProc(lines, code)


print("1) Részleges hiba (A1)")
import subprocess as _sp
_ORIG_POPEN = _sp.Popen          # a monkeypatch-et vissza kell állítani (asyncio import!)
kreta.RESULT_MARKER = "##KRETA_RESULT##"
lines = [
    "> SZINKRONIZÁCIÓ INDÍTÁSA",
    "##KRETA_RESULT##" + json.dumps({"total": 3, "ok": 2, "failed": ["Teszt Elek"]}, ensure_ascii=False),
]
kreta.subprocess.Popen = fake_popen(lines, 2)
kreta.run_scraper_thread("manual")
ok(kreta.sync_state["status"] == "done_with_errors", f"exit 2 -> done_with_errors ({kreta.sync_state['status']})")
ok(kreta.sync_state["failed_students"] == ["Teszt Elek"], f"hibás diák kiolvasva: {kreta.sync_state['failed_students']}")
ok(any("RÉSZBEN SIKERES" in l for l in kreta.sync_state["logs"]), "a konzol jelzi a részleges hibát")
st = kreta.load_scheduler_state()
ok(st.get("last_failed_students") == ["Teszt Elek"], f"állapotfájlban is megvan: {st.get('last_failed_students')}")
ok(st.get("last_status") == "done_with_errors", "állapotfájl last_status is done_with_errors")

kreta.subprocess.Popen = fake_popen(["##KRETA_RESULT##" + '{"total":3,"ok":3,"failed":[]}'], 0)
kreta.run_scraper_thread("manual")
ok(kreta.sync_state["status"] == "done" and kreta.sync_state["failed_students"] == [],
   f"exit 0 -> done, nincs hibás diák ({kreta.sync_state['status']})")

kreta.subprocess.Popen = fake_popen(["valami hiba"], 1)
kreta.run_scraper_thread("manual")
ok(kreta.sync_state["status"] == "error", f"exit 1 -> error ({kreta.sync_state['status']})")

# a két fájlban ugyanaz a marker legyen
src = open(ROOT / "kreta_playwright.py", encoding="utf-8").read()
ok('RESULT_MARKER = "##KRETA_RESULT##"' in src and kreta.RESULT_MARKER == "##KRETA_RESULT##",
   "a scraper és az app ugyanazt a markert használja")
ok("return 0 if not failed else 2" in src, "a scraper a részleges hibánál 2-vel lép ki")
_sp.Popen = _ORIG_POPEN          # monkeypatch visszaállítása


# ── A2: ntfy ──────────────────────────────────────────────────────────────────
print("\n2) ntfy értesítés (A2)")
sent = []
kreta._http_post_ntfy = lambda url, data, headers, timeout: sent.append((url, data, headers, timeout)) or 200

kreta.NTFY_TOPIC = ""
ok(kreta.send_notification("x", "y") is False and not sent, "nincs NTFY_TOPIC -> nem küld semmit")

kreta.NTFY_TOPIC = "teszt-topic"
kreta.NTFY_URL = "https://ntfy.example"
ok(kreta.send_notification("Cím ő/ű", "Üzenet Ő/Ű", "high", ["warning"]), "topic beállítva -> küld")
time.sleep(0.4)
ok(len(sent) == 1, f"egy kérés ment el ({len(sent)})")
url, data, headers, timeout = sent[0]
payload = json.loads(data.decode("utf-8"))
ok(url == "https://ntfy.example", f"URL: {url}")
ok(payload["topic"] == "teszt-topic", "payload.topic")
ok(payload["title"] == "Cím ő/ű" and payload["message"] == "Üzenet Ő/Ű", "UTF-8 cím/üzenet helyes")
ok(payload["priority"] == "high" and payload["tags"] == ["warning"], "priority/tags")
ok("application/json" in headers.get("Content-Type", ""), "Content-Type JSON")

sent.clear()
ok(kreta.notify_sync_result("done_with_errors", ["A Bácsi"], "scheduled", 2.3) is True, "részleges hiba -> küld")
time.sleep(0.4)
ok(len(sent) == 1 and "részleges" in json.loads(sent[0][1].decode())["title"].lower(),
   "a cím jelzi a részleges hibát")
sent.clear()
kreta.notify_sync_result("done", [], "manual", 2.0)
time.sleep(0.3)
ok(not sent, "sikeres futás -> nincs értesítés")
sent.clear()
kreta.notify_sync_result("error", [], "manual", 1.0)
time.sleep(0.4)
ok(len(sent) == 1 and "HIBA" in json.loads(sent[0][1].decode())["title"], "hiba -> küld")

# elavult adat riasztás + throttle
sent.clear()
now = kreta._now()
kreta.save_scheduler_state({"last_run_started": (now - kreta.timedelta(hours=13)).strftime(kreta.SCHEDULER_TS_FMT)})
cfg = {"stale_alert_hours": 12}
ok(kreta._maybe_notify_stale(cfg) is True, "13 órás adat + 12 órás küszöb -> riaszt")
time.sleep(0.4)
ok(len(sent) == 1, "riasztás elment")
ok(kreta._maybe_notify_stale(cfg) is False, "6 órán belül nem riaszt újra (throttle)")
ok(kreta.load_scheduler_state().get("last_stale_alert"), "a riasztás ideje perzisztálva")
kreta.save_scheduler_state({"last_run_started": now.strftime(kreta.SCHEDULER_TS_FMT)})
ok(kreta._maybe_notify_stale(cfg) is False, "friss adat -> nincs riaszt")


# ── A3: napló-rotáció + /api/logs tail ────────────────────────────────────────
print("\n3) Napló rotáció és tail (A3)")
kreta.LOG_MAX_BYTES = 1000
kreta.LOG_BACKUP_COUNT = 2
with open(log_path, "w", encoding="utf-8") as f:
    f.write("A" * 1200)
kreta._append_sync_log("uj sor a rotacio utan")
ok(os.path.exists(log_path + ".1"), "rotáció: .1 létrejött")
ok(os.path.getsize(log_path) < 1000, f"a friss napló kicsi ({os.path.getsize(log_path)} bájt)")
ok("uj sor a rotacio utan" in open(log_path, encoding="utf-8").read(), "az új sor a friss fájlban van")
ok(open(log_path + ".1", encoding="utf-8").read().startswith("A" * 10), "a régi tartalom a .1-ben")

kreta.LOG_API_MAX_BYTES = 500
with open(log_path, "w", encoding="utf-8") as f:
    f.write("KEZDET\n" + ("sor " * 400) + "\nVEGSO-SOR")
cl = kreta.app.test_client()
r = cl.get("/api/logs").get_json()
ok(r["status"] == "ok", "API válasz ok")
ok(len(r["content"].encode("utf-8")) < 900, f"a válasz korlátozott ({len(r['content'].encode('utf-8'))} bájt)")
ok("levágva" in r["content"], "jelzi, hogy a napló eleje le van vágva")
ok("VEGSO-SOR" in r["content"], "a napló vége benne van")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
