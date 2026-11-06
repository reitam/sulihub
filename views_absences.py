# -*- coding: utf-8 -*-
"""
Hiányzások / igazolások (KRÉ-14 #95): havi/összesített lista és igazolások.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. Prefix nélküli blueprint —
az URL-ek változatlanok.
"""
import os
import sqlite3

from flask import jsonify, request

from kreta_db import get_db_connection
from kreta_paths import DB_FILE
from views_common import (
    _date_range_from_request, _has_tanev_column, _is_keses, _tanev_from_request,
    hianyzas_osszesito, make_bp,
)

bp = make_bp("absences")

@bp.route("/api/hianyzasok")
def api_hianyzasok():
    empty = {"rows": [], "osszesito": hianyzas_osszesito([])}
    if not os.path.exists(DB_FILE):
        return jsonify(empty)

    diak = request.args.get("diak", "")
    kezdo, zaro = _date_range_from_request()
    tanev = _tanev_from_request()

    query = "SELECT * FROM hianyzasok WHERE 1=1"
    params = []
    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    if tanev:
        query += " AND tanev = ?"
        params.append(tanev)
    if kezdo:
        query += " AND mulasztas_datum >= ?"
        params.append(kezdo)
    if zaro:
        query += " AND mulasztas_datum <= ?"
        params.append(zaro)
    query += " ORDER BY mulasztas_datum DESC, id DESC"

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
    except sqlite3.Error as e:
        print(f"[Hiányzások API] Olvasás nem sikerült: {e}")
        return jsonify(empty)

    for r in rows:
        r["igazolt"] = int(r.get("igazolt") or 0)
        r["ora_sorszam"] = int(r.get("ora_sorszam") or 0)
        r["keses"] = 1 if _is_keses(r) else 0
    return jsonify({"rows": rows, "osszesito": hianyzas_osszesito(rows)})


@bp.route("/api/igazolasok")
def api_igazolasok():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    diak = request.args.get("diak", "")
    kezdo, zaro = _date_range_from_request()
    tanev = _tanev_from_request()

    query = "SELECT * FROM igazolasok WHERE 1=1"
    params = []
    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    if tanev:
        query += " AND tanev = ?"
        params.append(tanev)
    # A hónaphoz kapcsolódó igazolások: az intervallum metszi a hónapot.
    if kezdo:
        query += " AND (vege IS NULL OR vege = '' OR vege >= ?)"
        params.append(kezdo)
    if zaro:
        query += " AND (kezdete IS NULL OR kezdete = '' OR kezdete <= ?)"
        params.append(zaro)
    query += " ORDER BY kezdete DESC, id DESC"

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
    except sqlite3.Error as e:
        print(f"[Igazolások API] Olvasás nem sikerült: {e}")
        return jsonify([])
    return jsonify(rows)


# ==============================================================================
# === HIÁNYZÁS-MINTÁZAT (Kaneo #80) ============================================
# ==============================================================================
NAP_NEVEK = ["hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap"]


@bp.route("/api/hianyzas-mintazat")
def api_hianyzas_mintazat():
    """Hiányzások/késések bontása: nap, órasorszám, tantárgy, hónap (Kaneo #80)."""
    from collections import Counter
    from datetime import datetime as _dt

    diak = request.args.get("diak", "")
    tanev = _tanev_from_request()
    valasz = {"hetnap": [], "ora": [], "tantargyak": [], "honapok": [], "osszes": 0}
    if not os.path.exists(DB_FILE):
        return jsonify(valasz)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = ("SELECT mulasztas_datum, ora_sorszam, tantargy, perc, igazolt,"
                 " mulasztas_tipus FROM hianyzasok WHERE 1=1")
        params = []
        if diak:
            query += " AND diak_nev = ?"
            params.append(diak)
        if tanev and _has_tanev_column(cursor, "hianyzasok"):
            query += " AND tanev = ?"
            params.append(tanev)
        cursor.execute(query, params)
        rows = cursor.fetchall()
    except sqlite3.Error as e:
        print(f"[Mintázat API] Olvasás nem sikerült: {e}")
        conn.close()
        return jsonify(valasz)
    conn.close()

    napok, orak, tantargyak, honapok = Counter(), Counter(), Counter(), Counter()
    for row in rows:
        datum = str(row["mulasztas_datum"] or "").strip()
        try:
            d = _dt.strptime(datum, "%Y-%m-%d")
        except ValueError:
            continue
        napok[NAP_NEVEK[d.weekday()]] += 1
        honapok[datum[:7]] += 1
        orak[str(row["ora_sorszam"] or 0)] += 1
        if row["tantargy"]:
            tantargyak[str(row["tantargy"])] += 1

    valasz["osszes"] = len(rows)
    valasz["hetnap"] = [{"nev": n, "db": napok.get(n, 0)} for n in NAP_NEVEK]
    valasz["ora"] = [{"ora": int(k), "db": v} for k, v in sorted(orak.items(), key=lambda x: int(x[0]))]
    valasz["tantargyak"] = [{"tantargy": k, "db": v}
                            for k, v in sorted(tantargyak.items(), key=lambda x: (-x[1], x[0]))]
    valasz["honapok"] = [{"honap": k, "db": honapok[k]} for k in sorted(honapok)]
    return jsonify(valasz)
