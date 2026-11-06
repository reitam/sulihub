# -*- coding: utf-8 -*-
"""
API-válasz „pillanatkép" a KRÉ-14 refaktorhoz (lokális fejlesztői eszköz).

Cél: a viselkedés-azonosság bizonyítéka a route-contract teszt MELLETT.
A `tests/test_routes_contract.py` az URL-eket rögzíti; ez az eszköz a válaszok
**szerkezetét és tartalmát** hasonlítja össze egy baseline-nal.

Használat (a repó gyökeréből):

    python tools/api_snapshot.py --out tools/snapshots/baseline.json
    python tools/api_snapshot.py --diff tools/snapshots/baseline.json

Kapcsolók:
    --db PATH     a másolandó SQLite (alap: KRETA_DB_FILE, majd kreta_adatok.db)
    --out PATH    ide írja a pillanatképet (JSON)
    --diff PATH   összehasonlítás egy korábbi pillanatképpel; eltérésnél exit 1
    --max-str N   ennél hosszabb szövegek hash-re cserélve (alap: 200)

FONTOS: a valódi DB-t **nem** nyitja meg írásra — másolatot készít egy temp
könyvtárba, és azon fut (SQLite-zárolás/séma-migráció így nem érinti az élő
adatot). A config.json-t (ha van) szintén a temp könyvtárba másolja.
A POST-végpontokat szándékosan nem hívja (mellékhatásuk lenne).
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Csak olvasó (GET) végpontok — a POST-oknak mellékhatásuk van.
ENDPOINTS = [
    ("health", "/health"),
    ("sync_status", "/api/sync/status"),
    ("scheduler_status", "/api/scheduler/status"),
    ("tanevek", "/api/tanevek"),
    ("esemenyek", "/api/esemenyek?kezdo_datum=2026-09-01&zaro_datum=2026-11-30"),
    ("naptar_esemenyek", "/api/naptar_esemenyek?kezdo=2026-09-01&zaro=2026-11-30"),
    ("hianyzasok", "/api/hianyzasok?kezdo=2026-09-01&zaro=2026-11-30"),
    ("igazolasok", "/api/igazolasok?kezdo=2026-09-01&zaro=2026-11-30"),
    ("orarend", "/api/orarend"),
    ("sajat_orarend", "/api/sajat_orarend"),
    ("orarend_szinek", "/api/orarend_szinek"),
    ("dashboard", "/api/dashboard"),
    ("atlagok", "/api/atlagok?kezdo_datum=2026-09-01&zaro_datum=2026-11-30"),
    ("statisztika", "/api/statisztika?kezdo_datum=2026-09-01&zaro_datum=2026-11-30"),
    ("uzenetek", "/api/uzenetek"),
    ("kommentek", "/api/kommentek"),
    ("sync_runs", "/api/sync_runs?limit=20"),
]

# Futásidőben változó mezők (a refaktortól függetlenül eltérnének).
VOLATILE_KEYS = {"uptime", "version", "server_time", "now"}
VOLATILE_PREFIXES = ("next_run", "last_scheduled_run")


def _volatile(key):
    return key in VOLATILE_KEYS or str(key).startswith(VOLATILE_PREFIXES)


def _sha(text):
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def normalize(value, max_str):
    """Rekurzív normalizálás: hosszú szöveg → hash, futásidejű mezők kihagyva."""
    if isinstance(value, dict):
        return {k: normalize(v, max_str) for k, v in value.items() if not _volatile(k)}
    if isinstance(value, list):
        return [normalize(v, max_str) for v in value]
    if isinstance(value, str) and len(value) > max_str:
        return {"__str__": _sha(value), "len": len(value), "prefix": value[:60]}
    return value


def scatter(value, prefix=""):
    """A diffhez lapos {útvonal: érték} nézet (listák index szerint)."""
    out = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(scatter(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.update(scatter(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = value
    return out


def take_snapshot(db_path, max_str):
    work = tempfile.mkdtemp(prefix="kreta_snap_")
    db_copy = os.path.join(work, "kreta_adatok.db")
    if db_path and Path(db_path).is_file():
        shutil.copy2(db_path, db_copy)
    else:
        sqlite3.connect(db_copy).close()
    config_copy = os.path.join(work, "config.json")
    if (ROOT / "config.json").is_file():
        shutil.copy2(ROOT / "config.json", config_copy)

    os.environ.update({
        "KRETA_DATA_DIR": work,
        "KRETA_DB_FILE": db_copy,
        "KRETA_CONFIG_FILE": config_copy,
        "KRETA_LOG_FILE": os.path.join(work, "sync.log"),
        "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csatolmanyok"),
        "KRETA_SCHEDULER_STATE_FILE": os.path.join(work, "scheduler_state.json"),
        "KRETA_VERSION_FILE": os.path.join(work, "version.txt"),
    })
    sys.path.insert(0, str(ROOT))
    import app as kreta  # noqa: E402  — csak a temp környezetben

    client = kreta.app.test_client()
    snapshot = {}
    for name, path in ENDPOINTS:
        try:
            resp = client.get(path)
            body = resp.get_json(silent=True)
        except Exception as exc:  # noqa: BLE001 — egy végpont hibája ne állítsa meg a többit
            snapshot[name] = {"__error__": f"{type(exc).__name__}: {exc}"}
            continue
        entry = {"status": resp.status_code}
        if body is None:
            text = resp.get_data(as_text=True)
            entry["body"] = normalize(text, max_str)
        else:
            entry["json"] = normalize(body, max_str)
        snapshot[name] = entry
    return snapshot


def main():
    parser = argparse.ArgumentParser(description="KRÉ-14 API-pillanatkép.")
    parser.add_argument("--db", default=os.environ.get("KRETA_DB_FILE") or str(ROOT / "kreta_adatok.db"))
    parser.add_argument("--out", default="")
    parser.add_argument("--diff", default="")
    parser.add_argument("--max-str", type=int, default=200)
    args = parser.parse_args()

    snapshot = take_snapshot(args.db, args.max_str)

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True),
                            encoding="utf-8")
        print(f"Pillanatkép kiírva: {out_path} ({len(snapshot)} végpont)")

    if args.diff:
        diff_path = Path(args.diff)
        if not diff_path.is_absolute():
            diff_path = ROOT / diff_path
        baseline = json.loads(diff_path.read_text(encoding="utf-8"))
        base_flat = scatter(baseline)
        new_flat = scatter(snapshot)
        keys = sorted(set(base_flat) | set(new_flat))
        changes = [(k, base_flat.get(k, "<hiányzik>"), new_flat.get(k, "<hiányzik>"))
                   for k in keys if base_flat.get(k, "<hiányzik>") != new_flat.get(k, "<hiányzik>")]
        if not changes:
            print(f"Nincs eltérés a baseline-hoz képest: {diff_path}")
            return 0
        print(f"ELTÉRÉS ({len(changes)} mező) a baseline-hoz képest: {diff_path}")
        for path, old, new in changes[:60]:
            print(f"  {path}: {old!r} -> {new!r}")
        if len(changes) > 60:
            print(f"  … és további {len(changes) - 60} mező")
        return 1

    if not args.out:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)[:4000])
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
