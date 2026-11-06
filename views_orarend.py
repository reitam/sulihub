# -*- coding: utf-8 -*-
"""
Órarend (KRÉ-14 #95): heti órarend, saját órák, színek, ICS, naptár-nézet.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. Prefix nélküli blueprint —
az URL-ek változatlanok. A PDF export szándékosan az `app.py`-ban maradt (#96).
"""
import json
import os
import re
from datetime import datetime, timedelta

from flask import Response, jsonify, request
from reportlab.lib import colors

import kreta_naptar
import kreta_sajat_orarend
import kreta_tanev
from kreta_db import get_db_connection, set_meta
from kreta_paths import DB_FILE
from kreta_settings import _HEX_SZIN, _orarend_szinek, load_config
from views_common import make_bp

bp = make_bp("orarend")

@bp.route("/api/orarend")
def api_orarend():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "")
    query = "SELECT * FROM orarend WHERE 1=1"
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)

    query += " ORDER BY kezdo_idopont ASC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return jsonify([dict(row) for row in rows])


@bp.route("/api/sajat_orarend", methods=["GET", "POST"])
def api_sajat_orarend():
    if not os.path.exists(DB_FILE):
        if request.method == "GET":
            return jsonify([])
        return jsonify({"status": "error", "message": "Nincs adatbázis"}), 404

    conn = get_db_connection()
    try:
        kreta_sajat_orarend.ensure_schema(conn)
        if request.method == "GET":
            diak = request.args.get("diak", "")
            return jsonify(kreta_sajat_orarend.list_series(conn, diak=diak))

        data = request.get_json(silent=True) or {}
        row = kreta_sajat_orarend.create_series(conn, data)
        return jsonify({"status": "ok", "sajat": row}), 201
    except kreta_sajat_orarend.SajatOrarendError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        print(f"[Saját órarend API] hiba: {e}")
        return jsonify({"status": "error", "message": "Mentés nem sikerült"}), 500
    finally:
        conn.close()


@bp.route("/api/sajat_orarend/<int:series_id>", methods=["DELETE", "PUT"])
def api_sajat_orarend_torles(series_id):
    if not os.path.exists(DB_FILE):
        return jsonify({"status": "error", "message": "Nincs adatbázis"}), 404
    conn = get_db_connection()
    try:
        kreta_sajat_orarend.ensure_schema(conn)
        if request.method == "PUT":
            data = request.get_json(silent=True) or {}
            row = kreta_sajat_orarend.update_series(conn, series_id, data)
            if not row:
                return jsonify({"status": "error", "message": "A tétel nem található"}), 404
            return jsonify({"status": "ok", "sajat": row})
        if not kreta_sajat_orarend.delete_series(conn, series_id):
            return jsonify({"status": "error", "message": "A tétel nem található"}), 404
        return jsonify({"status": "ok"})
    except kreta_sajat_orarend.SajatOrarendError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    finally:
        conn.close()


@bp.route("/api/sajat_orarend/<int:series_id>/kivetel", methods=["POST"])
def api_sajat_orarend_kivetel(series_id):
    if not os.path.exists(DB_FILE):
        return jsonify({"status": "error", "message": "Nincs adatbázis"}), 404
    data = request.get_json(silent=True) or {}
    conn = get_db_connection()
    try:
        kreta_sajat_orarend.ensure_schema(conn)
        if not kreta_sajat_orarend.add_exception(conn, series_id, data.get("datum")):
            return jsonify({"status": "error", "message": "A tétel nem található"}), 404
        return jsonify({"status": "ok"})
    except kreta_sajat_orarend.SajatOrarendError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    finally:
        conn.close()


def _orarend_period_bounds(period: str, ref):
    """Az ICS export időszaka: het / honap / felev / tanev."""
    period = (period or "het").lower()
    if period == "het":
        monday = ref - timedelta(days=ref.weekday())
        return monday, monday + timedelta(days=6)
    if period == "honap":
        first = ref.replace(day=1)
        if first.month == 12:
            last = first.replace(year=first.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            last = first.replace(month=first.month + 1, day=1) - timedelta(days=1)
        return first, last
    if period == "felev":
        if ref.month >= 9:
            return ref.replace(month=9, day=1), ref.replace(year=ref.year + 1, month=1, day=31)
        if ref.month <= 1:
            return ref.replace(year=ref.year - 1, month=9, day=1), ref.replace(month=1, day=31)
        return ref.replace(month=2, day=1), ref.replace(month=8, day=31)
    # tanev (alapértelmezés)
    tanev = kreta_tanev.current_tanev(ref)
    start, end = kreta_tanev.tanev_bounds(tanev)
    if start and end:
        return start, end
    return ref, ref + timedelta(days=365)


@bp.route("/api/orarend/export_ics")
def api_orarend_export_ics():
    if not os.path.exists(DB_FILE):
        return jsonify({"status": "error", "message": "Nincs adatbázis"}), 404
    diak = request.args.get("diak", "")
    period = request.args.get("period", "het")
    try:
        ref = datetime.strptime(request.args.get("datum", ""), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        ref = kreta_tanev.today()
    start, end = _orarend_period_bounds(period, ref)

    conn = get_db_connection()
    try:
        query = "SELECT * FROM orarend"
        params = []
        if diak:
            query += " WHERE diak_nev = ?"
            params.append(diak)
        query += " ORDER BY kezdo_idopont"
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    cfg = kreta_naptar.calendar_config(load_config())
    ics = kreta_naptar.ics_orarend(rows, start, end, cfg, diak_prefix=not diak)
    response = Response(ics, mimetype="text/calendar; charset=utf-8")
    suffix = re.sub(r"[^A-Za-z0-9._-]+", "_", diak)[:40] if diak else "osszes"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=\"orarend_{suffix}_{period}_{start.isoformat()}.ics\""
    )
    return response


@bp.route("/api/orarend_szinek", methods=["GET", "PUT"])
def api_orarend_szinek():
    if not os.path.exists(DB_FILE):
        return jsonify({"diakok": [], "szinek": {}})

    conn = get_db_connection()
    try:
        names = sorted({
            row["diak_nev"] for row in conn.execute(
                "SELECT DISTINCT diak_nev FROM orarend WHERE diak_nev IS NOT NULL AND diak_nev != ''"
            ).fetchall()
        })
        for student in (load_config() or {}).get("STUDENTS", []):
            nev = (student.get("diak_nev") or "").strip()
            if nev and nev not in names:
                names.append(nev)
    finally:
        conn.close()

    if request.method == "GET":
        return jsonify({"diakok": names, "szinek": _orarend_szinek()})

    data = request.get_json(silent=True) or {}
    incoming = data.get("szinek") or {}
    if not isinstance(incoming, dict):
        return jsonify({"status": "error", "message": "Hibás színformátum"}), 400
    colors = {}
    for name, value in incoming.items():
        value = str(value or "").strip()
        if not _HEX_SZIN.match(value):
            return jsonify({"status": "error", "message": f"Érvénytelen szín: {value}"}), 400
        colors[str(name)] = value
    set_meta("orarend_szinek", json.dumps(colors, ensure_ascii=False))
    return jsonify({"status": "ok", "szinek": colors})


@bp.route("/api/orarend_naptar")
def api_orarend_naptar():
    """Órarend lekérdezése a FullCalendar idősávos nézetéhez egyedi diák színkódolással."""
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT diak_nev FROM orarend ORDER BY diak_nev")
    osszes_diak = [r["diak_nev"] for r in cursor.fetchall() if r["diak_nev"]]

    color_palette = [
        {"bg": "#0d6efd", "border": "#0a58ca"},
        {"bg": "#198754", "border": "#146c43"},
        {"bg": "#6f42c1", "border": "#59359a"},
        {"bg": "#d63384", "border": "#ab296a"},
        {"bg": "#20c997", "border": "#1aa179"},
        {"bg": "#fd7e14", "border": "#ca6510"}
    ]

    # Felhasználói színek (Kaneo #56): config + app_meta felülírás.
    sajat_szinek = _orarend_szinek()
    diak_color_map = {}
    for idx, d_nev in enumerate(osszes_diak):
        szin = sajat_szinek.get(d_nev)
        if szin:
            diak_color_map[d_nev] = {"bg": szin, "border": szin}
        else:
            diak_color_map[d_nev] = color_palette[idx % len(color_palette)]

    diak = request.args.get("diak", "")
    query = "SELECT * FROM orarend WHERE 1=1"
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    sajat_alkalmak = kreta_sajat_orarend.expand_occurrences(
        conn,
        diak=diak,
        start=request.args.get("start"),
        end=request.args.get("end"),
    )
    conn.close()

    multi_student = not diak

    events = []
    for r in rows:
        d_nev = r["diak_nev"] or "Ismeretlen"
        kezdo = r["kezdo_idopont"]
        zaro = r["zaro_idopont"]
        tantargy = r["tantargy"] or "Tanóra"
        tanar = r["tanar"] or ""
        terem = r["terem"] or ""

        is_all_day = not zaro or "T" not in kezdo

        student_colors = diak_color_map.get(d_nev, {"bg": "#0d6efd", "border": "#0a58ca"})

        if is_all_day:
            title = f"🔴 {d_nev}: {tantargy}" if multi_student else f"🔴 {tantargy}"
            bg_color = "#fd7e14"
            border_color = "#ca6510"
        else:
            title = f"[{d_nev}] {tantargy}" if multi_student else tantargy
            if terem:
                title += f" ({terem})"
            bg_color = student_colors["bg"]
            border_color = student_colors["border"]

        events.append({
            "id": r["id"],
            "title": title,
            "start": kezdo,
            "end": zaro if zaro else None,
            "allDay": is_all_day,
            "backgroundColor": bg_color,
            "borderColor": border_color,
            "extendedProps": {
                "diak": d_nev,
                "tantargy": tantargy,
                "tanar": tanar,
                "terem": terem,
                "nap": r["nap"] or ""
            }
        })

    # Kézzel rögzített saját órák (Kaneo #55) — a szinkron nem érinti őket.
    for alkalom in sajat_alkalmak:
        d_nev = alkalom["diak_nev"]
        cim = alkalom["cim"]
        title = f"[{d_nev}] {cim}" if multi_student else cim
        if alkalom["terem"]:
            title += f" ({alkalom['terem']})"
        events.append({
            "id": f"sajat-{alkalom['sajat_id']}-{alkalom['datum']}",
            "title": title,
            "start": f"{alkalom['datum']}T{alkalom['kezdes']}:00",
            "end": f"{alkalom['datum']}T{alkalom['vege']}:00",
            "allDay": False,
            "backgroundColor": alkalom.get("szin") or "#6f42c1",
            "borderColor": alkalom.get("szin") or "#6f42c1",
            "extendedProps": {
                "sajat": True,
                "sajat_id": alkalom["sajat_id"],
                "datum": alkalom["datum"],
                "diak": d_nev,
                "tantargy": cim,
                "cim": cim,
                "terem": alkalom["terem"],
                "megjegyzes": alkalom["megjegyzes"],
                "kezdes": alkalom["kezdes"],
                "vege": alkalom["vege"],
                "szin": alkalom.get("szin") or "#6f42c1",
                "nap": alkalom["nap"],
                "ervenyes_tol": alkalom["ervenyes_tol"],
                "ervenyes_ig": alkalom["ervenyes_ig"],
            }
        })

    return jsonify(events)
