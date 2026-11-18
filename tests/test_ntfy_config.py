# -*- coding: utf-8 -*-
"""
ntfy beállítás: config.json `NTFY` blokk + env elsőbbség + teszt-végpont.

Az app importja külön folyamatban történik (mint a többi app-tesztnél), így a
valódi adatokat és a valódi config.json-t nem érinti.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


def make_env(work, extra=None):
    env = os.environ.copy()
    env.update({
        "KRETA_DATA_DIR": str(work),
        "KRETA_DB_FILE": str(work / "kreta_adatok.db"),
        "KRETA_CONFIG_FILE": str(work / "config.json"),
        "KRETA_LOG_FILE": str(work / "sync.log"),
        "PYTHONIOENCODING": "utf-8",
    })
    for key in ("NTFY_TOPIC", "NTFY_URL", "NTFY_NOTIFY_NEW", "NTFY_NOTIFY_SUCCESS",
                "NTFY_INCLUDE_NAMES",
                "KRETA_SCHEDULER_STATE_FILE", "KRETA_CSATOLMANYOK_DIR"):
        env.pop(key, None)
    env.update(extra or {})
    return env


def write_config(work, ntfy):
    (work / "config.json").write_text(
        json.dumps({"HEADLESS": True, "STUDENTS": [], "NTFY": ntfy}, ensure_ascii=False),
        encoding="utf-8")


def run_probe(work, env_extra, body):
    probe = work / "probe_ntfy.py"
    probe.write_text(
        "import sys\n"
        f"sys.path.insert(0, r'{ROOT}')\n"
        "import app as kreta\n"
        + body,
        encoding="utf-8")
    return subprocess.run([sys.executable, str(probe)], cwd=str(work),
                          env=make_env(work, env_extra), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)


print("1) config.json NTFY blokk (nincs env)")
work = Path(tempfile.mkdtemp(prefix="kreta_ntfy_"))
sqlite3.connect(work / "kreta_adatok.db").close()
write_config(work, {"_comment": "csak akkor él, ha nincs .env",
                    "TOPIC": "kreta-cfg-topic", "URL": "https://ntfy.example",
                    "NOTIFY_NEW": False, "INCLUDE_NAMES": True})
result = run_probe(work, {}, (
    "print('TOPIC=' + kreta.NTFY_TOPIC)\n"
    "print('URL=' + kreta.NTFY_URL)\n"
    "print('NEW=' + str(kreta.NTFY_NOTIFY_NEW))\n"
    "print('NAMES=' + str(kreta.NTFY_INCLUDE_NAMES))\n"
    "print('TARGET=' + repr(kreta._ntfy_target()))\n"
))
ok(result.returncode == 0, f"az app importja lefutott (exit={result.returncode})")
values = {}
for line in result.stdout.splitlines():
    if "=" in line:
        key, val = line.split("=", 1)
        values[key] = val
ok(values.get("TOPIC") == "kreta-cfg-topic", f"topic a configból: {values.get('TOPIC')}")
ok(values.get("URL") == "https://ntfy.example", f"URL a configból: {values.get('URL')}")
ok(values.get("NEW") == "False", f"NOTIFY_NEW a configból: {values.get('NEW')}")
ok(values.get("NAMES") == "True", f"INCLUDE_NAMES a configból: {values.get('NAMES')}")
ok("'https://ntfy.example', 'kreta-cfg-topic'"
   in (values.get("TARGET") or "").replace('"', "'"),
   f"_ntfy_target() a config értékeivel: {values.get('TARGET')}")

# A régi NOTIFY_SUCCESS kulcs visszafelé kompatibilis.
write_config(work, {"TOPIC": "kreta-cfg-topic", "NOTIFY_SUCCESS": False})
result_legacy = run_probe(work, {}, "print('NEW=' + str(kreta.NTFY_NOTIFY_NEW))\n")
ok("NEW=False" in result_legacy.stdout,
   f"a régi NOTIFY_SUCCESS kulcsot is elfogadja: {result_legacy.stdout.strip()}")

print("\n2) Az env változó erősebb a confignál")
result2 = run_probe(work, {"NTFY_TOPIC": "kreta-env-topic", "NTFY_URL": "https://env.example"},
                    "print('TOPIC=' + kreta.NTFY_TOPIC)\nprint('URL=' + kreta.NTFY_URL)\n")
values2 = {}
for line in result2.stdout.splitlines():
    if "=" in line:
        key, val = line.split("=", 1)
        values2[key] = val
ok(values2.get("TOPIC") == "kreta-env-topic", f"env topic nyer: {values2.get('TOPIC')}")
ok(values2.get("URL") == "https://env.example", f"env URL nyer: {values2.get('URL')}")
ok("A .env NTFY_TOPIC-ja él" in result2.stdout,
   "induláskor jelzi, hogy a config.json topicját nem használja")
ok("_comment" not in result2.stdout, "a _comment kulcs nem zavar (nincs benne a topicban)")

print("\n3) Teszt-végpont (POST /api/ntfy/test)")
probe = work / "probe_endpoint.py"
probe.write_text(
    "import sys\n"
    f"sys.path.insert(0, r'{ROOT}')\n"
    "import app as kreta\n"
    "sent = []\n"
    "kreta._http_post_ntfy = lambda url, data, headers, timeout: sent.append((url, data)) or 200\n"
    "client = kreta.app.test_client()\n"
    "r = client.post('/api/ntfy/test')\n"
    "print('STATUS=' + str(r.status_code))\n"
    "print('BODY=' + str(r.get_json()))\n"
    "print('SENT=' + str(len(sent)))\n"
    "kreta.NTFY_TOPIC = ''\n"
    "r2 = client.post('/api/ntfy/test')\n"
    "print('NOSTATUS=' + str(r2.status_code))\n"
    "print('NOBODY=' + str(r2.get_json()))\n",
    encoding="utf-8")
result3 = subprocess.run([sys.executable, str(probe)], cwd=str(work),
                         env=make_env(work, {}), capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=180)
vals3 = {}
for line in result3.stdout.splitlines():
    if "=" in line:
        key, val = line.split("=", 1)
        vals3[key] = val
ok(result3.returncode == 0, f"a végpont-próba lefutott (exit={result3.returncode})")
if result3.returncode != 0:
    print(result3.stdout[-800:], result3.stderr[-800:])
ok(vals3.get("STATUS") == "200", f"topic-kal 200: {vals3.get('STATUS')}")
ok("'ok': True" in (vals3.get("BODY") or ""), f"a válasz ok: {vals3.get('BODY')}")
ok(vals3.get("SENT") == "1", f"egy push ment ki (mock): {vals3.get('SENT')}")
ok(vals3.get("NOSTATUS") == "400", f"topic nélkül 400: {vals3.get('NOSTATUS')}")
ok("configured" in (vals3.get("NOBODY") or ""), "a hibaüzenet megmondja, mi hiányzik")

print("\n4) Teljes URL-es topic (backup-konvenció)")
probe2 = work / "probe_url.py"
probe2.write_text(
    "import sys\n"
    f"sys.path.insert(0, r'{ROOT}')\n"
    "import app as kreta\n"
    "kreta.NTFY_TOPIC = 'https://ntfy.sh/kreta-url-topic'\n"
    "kreta.NTFY_URL = 'https://ntfy.sh'\n"
    "print('TARGET=' + repr(kreta._ntfy_target()))\n",
    encoding="utf-8")
result4 = subprocess.run([sys.executable, str(probe2)], cwd=str(work),
                         env=make_env(work, {}), capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=180)
ok("'https://ntfy.sh', 'kreta-url-topic'"
   in result4.stdout.replace('"', "'"), f"URL-ből topic: {result4.stdout.strip()[-90:]}")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
