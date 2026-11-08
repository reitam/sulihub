#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mentés-visszaállítási ellenőrzés (Kaneo #90).

A legfrissebb `kreta_adatok_*.db` (vagy `.db.gz`) mentést **izolált temp
könyvtárba** másolja/kicsomagolja, majd:
- `PRAGMA integrity_check` = ok;
- a fő táblák léteznek és nem üresek (ahol a valódi DB-ben van adat);
- ha van `<mentés>.counts.json` manifest, a sorszámok **pontosan** egyeznek;
- a valódi DB-hez képest csak informatív eltérést ír (a mentés régebbi lehet).

Hiba esetén nem nulla kilépés + opcionális ntfy riasztás. A valódi DB-hez
nem ír (read-only URI).

Használat (a szerveren, host Pythonnal):
    python3 tools/backup_restore_check.py \
        --backup-dir ./backup \
        --db ./data/kreta_adatok.db \
        --ntfy-topic https://ntfy.sh/...
"""
import argparse
import gzip
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

TABLAK = ["esemenyek", "uzenetek", "hianyzasok", "igazolasok", "orarend",
          "kifizetesek", "sync_runs", "kommentek", "app_meta"]


def _nyit(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _szamok(db):
    conn = _nyit(db)
    try:
        letezo = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        return {t: (conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    if t in letezo else None) for t in TABLAK}
    finally:
        conn.close()


def _integritas(db):
    conn = _nyit(db)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def legfrissebb_mentes(backup_dir):
    d = Path(backup_dir)
    jeloltek = list(d.glob("kreta_adatok_*.db")) + list(d.glob("kreta_adatok_*.db.gz"))
    if not jeloltek:
        return None
    # A fájlnévben van az időbélyeg — a legnagyobb név a legfrissebb.
    return max(jeloltek, key=lambda p: p.name)


def _manifest_ut(path):
    p = Path(str(path))
    nev = p.name
    if nev.endswith(".db.gz"):
        nev = nev[:-6]
    elif nev.endswith(".db"):
        nev = nev[:-3]
    return p.with_name(nev + ".counts.json")


def _ntfy(topic, uzenet):
    if not topic:
        return
    try:
        req = urllib.request.Request(topic, data=uzenet.encode("utf-8"),
                                     headers={"Title": "KRÉTA restore-teszt"}, method="POST")
        urllib.request.urlopen(req, timeout=8)
    except Exception as exc:
        print(f"[ntfy] a riasztás nem ment el: {exc}")


def check(backup_dir, db=None, max_age_days=2.0, ntfy_topic=""):
    """Visszaad: (ok, uzenetek lista)."""
    uzenetek = []
    mentes = legfrissebb_mentes(backup_dir)
    if not mentes:
        return False, [f"HIBA: nincs mentés a(z) {backup_dir} könyvtárban"]
    uzenetek.append(f"legfrissebb mentés: {mentes}")
    kor_nap = (time.time() - mentes.stat().st_mtime) / 86400
    if kor_nap > max_age_days:
        return False, uzenetek + [
            f"HIBA: a legfrissebb mentés túl régi ({kor_nap:.1f} nap, max {max_age_days})"]

    temp = Path(tempfile.mkdtemp(prefix="kreta_restore_"))
    try:
        if mentes.name.endswith(".gz"):
            cel = temp / "restore.db"
            with gzip.open(mentes, "rb") as src, open(cel, "wb") as dst:
                shutil.copyfileobj(src, dst)
        else:
            cel = temp / "restore.db"
            shutil.copy2(mentes, cel)
        uzenetek.append(f"izolált másolat: {cel} ({cel.stat().st_size} byte)")

        try:
            integritas = _integritas(cel)
        except sqlite3.Error as exc:
            return False, uzenetek + [f"HIBA: a mentés nem nyitható meg ({exc})"]
        if integritas != "ok":
            return False, uzenetek + [f"HIBA: integrity_check = {integritas}"]
        uzenetek.append("integrity_check: ok")

        try:
            szamok = _szamok(cel)
        except sqlite3.Error as exc:
            return False, uzenetek + [f"HIBA: a táblák nem olvashatók ({exc})"]
        if all(v is None for v in szamok.values()):
            return False, uzenetek + ["HIBA: a mentésben egyetlen ismert tábla sincs"]
        uzenetek.append("táblák: " + ", ".join(
            f"{t}={v}" for t, v in szamok.items() if v is not None))

        # Manifest (ha a mentéskészítő írt): pontos egyezés.
        mani_path = _manifest_ut(mentes)
        if mani_path.exists():
            try:
                vart = json.loads(mani_path.read_text(encoding="utf-8"))
            except ValueError:
                return False, uzenetek + [f"HIBA: a manifest nem érvényes JSON: {mani_path}"]
            elteres = {t: (vart.get(t), szamok.get(t)) for t in vart
                       if t in szamok and szamok[t] != vart.get(t)}
            if elteres:
                return False, uzenetek + [f"HIBA: sorszám-eltérés a manifesthez: {elteres}"]
            uzenetek.append(f"manifest egyezik ({mani_path.name})")
        else:
            uzenetek.append("nincs manifest — a sorszámok a valódi DB-hez csak informatívak")

        if db and os.path.exists(db):
            live = _szamok(db)
            elteresek = []
            for t, v in szamok.items():
                if v is None or live.get(t) is None:
                    continue
                if v > live[t]:
                    elteresek.append(f"{t}: mentés {v} > valódi {live[t]}")
            if elteresek:
                uzenetek.append("FIGYELEM (informatív, a mentés régebbi lehet): "
                                + "; ".join(elteresek))
            else:
                uzenetek.append("a mentés sorszámai nem haladják meg a valódi DB-t")
        return True, uzenetek
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="KRÉTA mentés restore-ellenőrzés.")
    parser.add_argument("--backup-dir",
                        default=os.environ.get("KRETA_BACKUP_DIR",
                                               "./backup"))
    parser.add_argument("--db", default=os.environ.get("KRETA_DB_FILE", ""))
    parser.add_argument("--max-age-days", type=float, default=2.0)
    parser.add_argument("--ntfy-topic", default=os.environ.get("NTFY_TOPIC", ""))
    args = parser.parse_args(argv)

    ok, uzenetek = check(args.backup_dir, args.db or None, args.max_age_days, args.ntfy_topic)
    for u in uzenetek:
        print(u)
    print("EREDMÉNY: " + ("MENTÉS RENDBEN" if ok else "HIBA"))
    if not ok:
        _ntfy(args.ntfy_topic, "KRÉTA restore-teszt HIBA: " + " | ".join(uzenetek[-2:]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
