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
