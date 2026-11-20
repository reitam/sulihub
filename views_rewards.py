# -*- coding: utf-8 -*-
"""
Zsebpénz és naptár (KRÉ-14 #96): statisztika, kifizetés, naptár-bejegyzés/ICS.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. Prefix nélküli blueprint —
az URL-ek változatlanok.
"""
import os

from flask import jsonify, make_response, request

import kreta_naptar
import kreta_tanev
from kreta_db import get_db_connection
from kreta_exports import compute_zsebpenz_statisztika
from kreta_paths import DB_FILE
from kreta_settings import load_config
from views_common import _tanev_from_request, make_bp

bp = make_bp("rewards")

def _naptar_event(kind: str, item_id: int):
    """A kért esemény/üzenet naptáreseménnyé alakítva, vagy (None, hiba)."""
    if not os.path.exists(DB_FILE):
        return None, (jsonify({"status": "error", "message": "Nincs adatbázis"}), 404)
    conn = get_db_connection()
    try:
        cfg = kreta_naptar.calendar_config(load_config())
        if kind == "esemeny":
            row = conn.execute("SELECT * FROM esemenyek WHERE id = ?", (item_id,)).fetchone()
            event = kreta_naptar.event_from_esemeny(row, cfg) if row else None
        elif kind == "uzenet":
            row = conn.execute("SELECT * FROM uzenetek WHERE id = ?", (item_id,)).fetchone()
            event = kreta_naptar.event_from_uzenet(row, cfg) if row else None
        else:
            return None, (jsonify({"status": "error", "message": "Ismeretlen típus"}), 404)
    finally:
        conn.close()
    if not event:
        return None, (jsonify({"status": "error", "message": "A bejegyzés nem található vagy nincs dátuma"}), 404)
    return event, None


@bp.route("/api/naptar/<kind>/<int:item_id>")
def api_naptar_info(kind, item_id):
    event, error = _naptar_event(kind, item_id)
    if error:
        return error
    cfg = kreta_naptar.calendar_config(load_config())
    return jsonify({
        "status": "ok",
        "kind": event["kind"],
        "id": event["id"],
        "title": event["title"],
        "start": event["start"].isoformat(),
        "all_day": event["all_day"],
        "google_url": kreta_naptar.google_calendar_url(event, cfg),
        "ics_url": f"/api/naptar/{event['kind']}/{event['id']}.ics",
    })


@bp.route("/api/naptar/<kind>/<int:item_id>.ics")
def api_naptar_ics(kind, item_id):
    event, error = _naptar_event(kind, item_id)
    if error:
        return error
    cfg = kreta_naptar.calendar_config(load_config())
    response = make_response(kreta_naptar.ics_content(event, cfg))
    response.headers["Content-Type"] = "text/calendar; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=\"{kreta_naptar.safe_filename(event)}\""
    )
    return response





@bp.route("/api/statisztika")
def api_statisztika():
    data = compute_zsebpenz_statisztika(
        diak=request.args.get("diak", ""),
        kezdo_datum=request.args.get("kezdo_datum", ""),
        zaro_datum=request.args.get("zaro_datum", ""),
        tanev_szuro=_tanev_from_request(),
    )
    if data is None:
        return jsonify({"enabled": False})
    return jsonify(data)


@bp.route("/api/kifizetes", methods=["POST"])
def api_kifizetes_save():
    data = request.get_json(silent=True) or {}
    diak = data.get("diak", "")
    kezdo_datum = data.get("kezdo_datum", "")
    zaro_datum = data.get("zaro_datum", "")
    kifizetve = 1 if data.get("kifizetve") else 0
    osszeg = data.get("osszeg", 0)

    if not diak or not kezdo_datum or not zaro_datum:
        return jsonify({"status": "error", "message": "Hiányzó paraméterek"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    # A kifizetés tanéve az időszak kezdetéből (Kaneo #40): enélkül a
    # `?tanev=` szűrt dashboard nem venné figyelembe a frissen kifizetett összeget.
    tanev = kreta_tanev.tanev_of(kezdo_datum)
    cursor.execute("""
        INSERT INTO kifizetesek (diak_nev, kezdo_datum, zaro_datum, kifizetve, osszeg,
                                 tanev, tanev_forras, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'szamitott', CURRENT_TIMESTAMP)
        ON CONFLICT(diak_nev, kezdo_datum, zaro_datum) DO UPDATE SET
            kifizetve = excluded.kifizetve,
            osszeg = excluded.osszeg,
            tanev = CASE WHEN ? <> '' THEN excluded.tanev ELSE kifizetesek.tanev END,
            tanev_forras = CASE WHEN ? <> '' THEN excluded.tanev_forras
                                ELSE kifizetesek.tanev_forras END,
            updated_at = CURRENT_TIMESTAMP
    """, (diak, kezdo_datum, zaro_datum, kifizetve, osszeg, tanev, tanev, tanev))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "kifizetve": bool(kifizetve)})
