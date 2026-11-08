#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Élő füstteszt a futó KRÉTA példányhoz (Kaneo #90).

Ellenőrzi:
- `GET /health` → 200 és `status == "ok"`;
- `GET /api/sync/status` → 200, az utolsó futás státusza nem `error`,
  és az utolsó futás nem régebbi a megadott óraszámnál.

Használat:
    python tools/live_smoke.py --url http://192.168.1.39:8085
    python tools/live_smoke.py --url https://... --user u --password p --max-age-hours 26

A belépési adatok env-ből is jöhetnek: `KRETA_URL`, `KRETA_AUTH_USER`,
`KRETA_AUTH_PASS`. Kilépési kód: 0 = minden OK, 1 = hiba.
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

IDO_FORMATUMOK = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M")


def _get(url, user="", password="", timeout=10):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if user:
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        req.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as err:
        return err.code, {}
    except urllib.error.URLError as err:
        return 0, {"_hiba": str(err.reason)}


def _ido(ertek):
    for fmt in IDO_FORMATUMOK:
        try:
            return datetime.strptime(str(ertek), fmt)
        except (TypeError, ValueError):
            continue
    try:
        return datetime.fromisoformat(str(ertek))
    except (TypeError, ValueError):
        return None


def check(url, user="", password="", max_age_hours=26, timeout=10, allow_never=False):
    """Visszaad: (ok, [(siker, uzenet), ...])."""
    url = url.rstrip("/")
    eredmenyek = []

    status, health = _get(url + "/health", user, password, timeout)
    if status == 200 and (health or {}).get("status") == "ok":
        eredmenyek.append((True, f"/health OK (verzió: {health.get('version', '?')})"))
    else:
        eredmenyek.append((False, f"/health HIBA (HTTP {status}, {health})"))

    status, sync = _get(url + "/api/sync/status", user, password, timeout)
    if status != 200:
        eredmenyek.append((False, f"/api/sync/status HIBA (HTTP {status})"))
        return all(ok for ok, _ in eredmenyek), eredmenyek
    if sync.get("running"):
        eredmenyek.append((True, "szinkron éppen fut"))
        return all(ok for ok, _ in eredmenyek), eredmenyek

    sched = sync.get("scheduler") or {}
    last_status = sched.get("last_status") or sync.get("status")
    if last_status == "error":
        eredmenyek.append((False, "az utolsó szinkron hibára futott (last_status=error)"))
    elif last_status in (None, ""):
        if allow_never:
            eredmenyek.append((True, "még nem volt szinkron (engedélyezve)"))
        else:
            eredmenyek.append((False, "még nem volt szinkron (last_status üres)"))
    else:
        eredmenyek.append((True, f"utolsó szinkron státusza: {last_status}"))

    last_run = sched.get("last_run") or sched.get("last_run_finished")
    if not last_run:
        if not allow_never:
            eredmenyek.append((False, "nincs utolsó futás időpont (last_run üres)"))
    else:
        dt = _ido(last_run)
        if dt is None:
            eredmenyek.append((False, f"az utolsó futás időpontja nem értelmezhető: {last_run}"))
        else:
            kor = datetime.now() - dt
            if kor > timedelta(hours=max_age_hours):
                eredmenyek.append((
                    False,
                    f"az utolsó futás túl régi: {last_run} ({kor.total_seconds() / 3600:.1f} óra)",
                ))
            else:
                eredmenyek.append((True, f"utolsó futás: {last_run} ({kor.total_seconds() / 3600:.1f} óra)"))
    return all(ok for ok, _ in eredmenyek), eredmenyek


def main(argv=None):
    parser = argparse.ArgumentParser(description="Élő KRÉTA füstteszt.")
    parser.add_argument("--url", default=os.environ.get("KRETA_URL", ""))
    parser.add_argument("--user", default=os.environ.get("KRETA_AUTH_USER", ""))
    parser.add_argument("--password", default=os.environ.get("KRETA_AUTH_PASS", ""))
    parser.add_argument("--max-age-hours", type=float, default=26.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--allow-never", action="store_true",
                        help="Első élesítésnél a még nem futott szinkront is elfogadja.")
    args = parser.parse_args(argv)
    if not args.url:
        print("HIBA: nincs --url / KRETA_URL", file=sys.stderr)
        return 2
    ok_osszes, eredmenyek = check(args.url, args.user, args.password,
                                  args.max_age_hours, args.timeout, args.allow_never)
    for ok, uzenet in eredmenyek:
        print(("  OK   " if ok else "  HIBA ") + uzenet)
    print("EREDMÉNY: " + ("MINDEN OK" if ok_osszes else "HIBA"))
    return 0 if ok_osszes else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
