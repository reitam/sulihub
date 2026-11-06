# -*- coding: utf-8 -*-
"""
Helyi futásidejű adatok átköltöztetése a `data/` mappába (KRÉ-14 #98).

v2.0.0-tól az app minden futásidejű fájlt a `data/` alatt keres; a régi
(gyökér) elrendezés ideiglenesen még működik (figyelmeztetéssel), de a
következő kiadásban megszűnik.

Használat (a repó gyökeréből; **az app ne fusson közben**):

    python tools/migrate_local_data.py --dry-run   # csak kiírja, mit tenne
    python tools/migrate_local_data.py             # átmozgat
    python tools/migrate_local_data.py --rollback  # visszaállítja a napló alapján

A művelet naplója: `data/.migration_log.json`. A DB-t mozgatás után
megnyitással és `PRAGMA quick_check`-kel ellenőrzi.
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

FILES = [
    "config.json",
    "kreta_adatok.db",
    "kreta_adatok.db-wal",
    "kreta_adatok.db-shm",
    "sync.log",
    "sync.log.1",
    "sync.log.2",
    "api_tokens.json",
    "api_tokens.json.tmp",
    "scheduler_state.json",
    "scheduler_state.json.migrated",
    "version.txt",
]
DIRS = [
    ("browser_user_data", "browser_user_data"),
    (os.path.join("static", "csatolmanyok"), "csatolmanyok"),
]
LOG_NAME = ".migration_log.json"


def source_root(arg_root):
    return Path(arg_root or Path(__file__).resolve().parents[1]).resolve()


def plan(root):
    """(forrás, cél, típus) hármasok — csak a létező forrásokra."""
    target_dir = root / "data"
    items = []
    for name in FILES:
        src = root / name
        if src.exists():
            items.append((src, target_dir / name, "file"))
    for src_rel, dst_rel in DIRS:
        src = root / src_rel
        if src.exists():
            items.append((src, target_dir / dst_rel, "dir"))
    return items


def preflight(items, target_dir):
    problems = []
    if not items:
        problems.append("nincs mit átmozgatni (a gyökérben nem találhatók futásidejű fájlok)")
    for src, dst, _kind in items:
        if dst.exists():
            problems.append(f"a cél már létezik: {dst}")
    return problems


def db_ok(db_path):
    try:
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA quick_check").fetchone()[0]
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
    except sqlite3.Error as exc:
        return False, f"nem nyitható meg: {exc}"
    if str(result).lower() != "ok":
        return False, f"quick_check: {result}"
    if "esemenyek" not in tables:
        return False, "hiányzik az esemenyek tábla"
    return True, "ok"


def write_log(target_dir, items, dry_run):
    if dry_run:
        return
    log_path = target_dir / LOG_NAME
    entries = [{"src": str(src), "dst": str(dst), "type": kind} for src, dst, kind in items]
    log_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def do_migrate(root, dry_run):
    target_dir = root / "data"
    items = plan(root)
    problems = preflight(items, target_dir)
    if problems:
        for problem in problems:
            print(f"HIBA: {problem}")
        return 1

    if dry_run:
        print(f"[dry-run] Cél: {target_dir}")
        for src, dst, kind in items:
            print(f"  {kind}: {src} -> {dst}")
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    try:
        for src, dst, kind in items:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append((src, dst, kind))
            print(f"  átmozgatva: {src.name} -> {dst}")
    except OSError as exc:
        print(f"HIBA a mozgatásnál: {exc}")
        print("     (Ha az app fut, állítsd le — a DB-t nyitva tartja.)")
        # ami már átkerült, azt visszük vissza, hogy ne legyen félállapot
        for src, dst, _kind in reversed(moved):
            try:
                shutil.move(str(dst), str(src))
                print(f"  visszaállítva: {src.name}")
            except OSError as err:
                print(f"  HIBA a visszaállításnál ({src.name}): {err}")
        return 1

    write_log(target_dir, items, dry_run)

    db_path = target_dir / "kreta_adatok.db"
    if db_path.exists():
        good, detail = db_ok(db_path)
        print(("  DB-ellenőrzés: OK" if good else f"  DB-ellenőrzés: HIBA ({detail})"))
        if not good:
            return 1
    print("Kész. A következő indítás már a data/ mappát használja.")
    return 0


def do_rollback(root):
    target_dir = root / "data"
    log_path = target_dir / LOG_NAME
    if not log_path.is_file():
        print(f"HIBA: nincs migrációs napló: {log_path}")
        return 1
    entries = json.loads(log_path.read_text(encoding="utf-8"))
    for entry in reversed(entries):
        src, dst = Path(entry["src"]), Path(entry["dst"])
        if not dst.exists():
            print(f"  kihagyva (nincs a célnál): {dst}")
            continue
        if src.exists():
            print(f"HIBA: a forrás helye foglalt: {src}")
            return 1
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(src))
        print(f"  visszamozgatva: {dst.name} -> {src}")
    log_path.unlink(missing_ok=True)
    print("Kész. Ismét a régi (gyökér) elrendezés él.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Futásidejű adatok költöztetése a data/ alá.")
    parser.add_argument("--root", default="", help="projektgyökér (alap: a szkript melletti repó)")
    parser.add_argument("--dry-run", action="store_true", help="csak kiírja a műveleteket")
    parser.add_argument("--rollback", action="store_true", help="a napló alapján visszaállít")
    args = parser.parse_args()
    root = source_root(args.root)
    if args.rollback:
        return do_rollback(root)
    return do_migrate(root, args.dry_run)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
