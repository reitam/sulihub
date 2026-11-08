#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Heti adatminőség- és integritás-riport (Kaneo #89).

Csak olvas (a DB-hez `mode=ro` URI-n kapcsolódik), nem módosít semmit.
Ellenőrzi: integrity_check, DB-méret, táblák sorszámai, utolsó szinkron,
duplikált jegy/hiányzás, hiányzó csatolmányfájlok, üres kötelező mezők,
árva megjegyzések. Az eredményt kiírja (és opcionálisan ntfy-ra küldi).

Használat (heti cron):
    python3 tools/data_quality_report.py --ntfy-topic https://ntfy.sh/...
"""
import argparse
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TABLAK = ("esemenyek", "uzenetek", "hianyzasok", "igazolasok", "orarend",
          "kifizetesek", "sync_runs", "kommentek")


def _nyit(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tabla_letezik(conn, nev):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nev,)).fetchone() is not None


def check(db, csat_dir=None):
    """Visszaad: (ok, riport dict)."""
    db = Path(db)
    riport = {"db": str(db), "meret_mb": round(db.stat().st_size / 1024 / 1024, 2),
              "tablak": {}, "hibak": [], "figyelmeztetesek": []}
    conn = _nyit(db)
    try:
        integritas = conn.execute("PRAGMA integrity_check").fetchone()[0]
        riport["integritas"] = integritas
        if integritas != "ok":
            riport["hibak"].append(f"integrity_check: {integritas}")

        for t in TABLAK:
            if _tabla_letezik(conn, t):
                riport["tablak"][t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

        # Utolsó szinkron
        if _tabla_letezik(conn, "sync_runs"):
            row = conn.execute(
                "SELECT started_at, status FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
            if row:
                riport["utolso_szinkron"] = {"indult": row["started_at"], "status": row["status"]}

        # Duplikált jegyek / hiányzások
        if _tabla_letezik(conn, "esemenyek"):
            dupl = conn.execute(
                "SELECT COUNT(*) FROM (SELECT diak_nev, esemeny_tipus, tantargy, bej_datum,"
                " ertek, tema, COUNT(*) c FROM esemenyek GROUP BY 1,2,3,4,5,6 HAVING c > 1)"
            ).fetchone()[0]
            riport["duplikalt_esemeny"] = dupl
            if dupl:
                riport["figyelmeztetesek"].append(f"{dupl} duplikált esemény-csoport")
            ures = conn.execute(
                "SELECT COUNT(*) FROM esemenyek WHERE COALESCE(diak_nev,'')=''"
                " OR COALESCE(esemeny_tipus,'')=''").fetchone()[0]
            if ures:
                riport["hibak"].append(f"{ures} esemény hiányzó diák/típus mezővel")
        if _tabla_letezik(conn, "hianyzasok"):
            dupl = conn.execute(
                "SELECT COUNT(*) FROM (SELECT diak_nev, mulasztas_datum, ora_sorszam,"
                " COUNT(*) c FROM hianyzasok GROUP BY 1,2,3 HAVING c > 1)").fetchone()[0]
            riport["duplikalt_hianyzas"] = dupl
            if dupl:
                riport["figyelmeztetesek"].append(f"{dupl} duplikált hiányzás")
            ures = conn.execute(
                "SELECT COUNT(*) FROM hianyzasok WHERE COALESCE(diak_nev,'')=''"
                " OR COALESCE(mulasztas_datum,'')=''").fetchone()[0]
            if ures:
                riport["hibak"].append(f"{ures} hiányzás hiányzó diák/dátum mezővel")
        if _tabla_letezik(conn, "uzenetek"):
            ures = conn.execute(
                "SELECT COUNT(*) FROM uzenetek WHERE COALESCE(diak_nev,'')=''"
                " OR COALESCE(targy,'')=''").fetchone()[0]
            if ures:
                riport["hibak"].append(f"{ures} üzenet hiányzó diák/tárgy mezővel")

        # Hiányzó csatolmányfájlok
        hianyzo = 0
        if _tabla_letezik(conn, "uzenetek"):
            for r in conn.execute(
                    "SELECT diak_nev, csatolmany_nev, csatolmany_utvonal FROM uzenetek"
                    " WHERE COALESCE(csatolmany_utvonal,'') != ''"):
                ut = str(r["csatolmany_utvonal"]).replace("\\", "/")
                jelolt = Path(ut)
                if not jelolt.is_absolute():
                    jelolt = db.parent / ut
                if not jelolt.exists():
                    # A data kötet csatolmány-mappájában a fájlnév is elég.
                    nev = os.path.basename(ut)
                    lehetosegek = []
                    if csat_dir:
                        lehetosegek.append(Path(csat_dir) / nev)
                    lehetosegek.append(db.parent / "csatolmanyok" / nev)
                    if not any(p.exists() for p in lehetosegek):
                        hianyzo += 1
        riport["hianyzo_csatolmany"] = hianyzo
        if hianyzo:
            riport["hibak"].append(f"{hianyzo} hiányzó csatolmányfájl")

        # Árva megjegyzések
        arva = 0
        if _tabla_letezik(conn, "kommentek"):
            from kreta_db import komment_kulcs_esemeny, komment_kulcs_uzenet
            esemeny_kulcsok = set()
            uzenet_kulcsok = set()
            if _tabla_letezik(conn, "esemenyek"):
                esemeny_kulcsok = {komment_kulcs_esemeny(r) for r in conn.execute("SELECT * FROM esemenyek")}
            if _tabla_letezik(conn, "uzenetek"):
                uzenet_kulcsok = {komment_kulcs_uzenet(r) for r in conn.execute("SELECT * FROM uzenetek")}
            for r in conn.execute("SELECT cel_tipus, cel_kulcs FROM kommentek"):
                if r["cel_tipus"] == "esemeny" and r["cel_kulcs"] not in esemeny_kulcsok:
                    arva += 1
                elif r["cel_tipus"] == "uzenet" and r["cel_kulcs"] not in uzenet_kulcsok:
                    arva += 1
        riport["arva_komment"] = arva
        if arva:
            riport["figyelmeztetesek"].append(f"{arva} árva megjegyzés")
    finally:
        conn.close()
    return not riport["hibak"], riport


def _ntfy(topic, uzenet):
    if not topic:
        return
    try:
        req = urllib.request.Request(
            topic, data=uzenet.encode("utf-8"),
            headers={"Title": "KRÉTA adatminőség-riport"}, method="POST")
        urllib.request.urlopen(req, timeout=8)
    except Exception as exc:
        print(f"[ntfy] a riport nem ment el: {exc}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="KRÉTA adatminőség-riport (csak olvas).")
    parser.add_argument("--db", default=os.environ.get("KRETA_DB_FILE", "data/kreta_adatok.db"))
    parser.add_argument("--csat-dir", default=os.environ.get("KRETA_CSATOLMANYOK_DIR", ""))
    parser.add_argument("--ntfy-topic", default=os.environ.get("NTFY_TOPIC", ""))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not os.path.exists(args.db):
        print(f"HIBA: nincs adatbázis: {args.db}", file=sys.stderr)
        return 2
    ok_all, riport = check(args.db, args.csat_dir or None)
    if args.json:
        print(json.dumps(riport, ensure_ascii=False, indent=1))
    else:
        print(f"KRÉTA adatminőség-riport — {riport['db']} ({riport['meret_mb']} MB)")
        print(f"integrity_check: {riport.get('integrity')}")
        print("táblák: " + ", ".join(f"{k}={v}" for k, v in riport["tablak"].items()))
        if riport.get("utolso_szinkron"):
            print(f"utolsó szinkron: {riport['utolso_szinkron']}")
        for h in riport["hibak"]:
            print("HIBA: " + h)
        for f in riport["figyelmeztetesek"]:
            print("FIGYELEM: " + f)
        print("EREDMÉNY: " + ("RENDBEN" if ok_all else "HIBÁK"))
    if riport["hibak"] or riport["figyelmeztetesek"]:
        _ntfy(args.ntfy_topic,
              "KRÉTA adatminőség: " + "; ".join(riport["hibak"] + riport["figyelmeztetesek"]))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
