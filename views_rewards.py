# -*- coding: utf-8 -*-
"""
Zsebpénz és naptár (KRÉ-14 #96): statisztika, kifizetés, naptár-bejegyzés/ICS, üzenet-AI.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. Prefix nélküli blueprint —
az URL-ek változatlanok.
"""
import os
import re
from datetime import datetime

from flask import jsonify, make_response, request

import kreta_ai
import kreta_naptar
import kreta_tanev
from kreta_db import get_db_connection
from kreta_exports import compute_zsebpenz_statisztika
from kreta_paths import CSATOLMANYOK_DIR, DB_FILE
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


def _csatolmany_szoveg(row) -> str:
    """Az üzenet csatolmányából kinyerhető szöveg (txt/md/csv/pdf), max ~20k."""
    keys = row.keys()
    raw = row["csatolmany_utvonal"] if "csatolmany_utvonal" in keys else ""
    if not raw:
        return ""
    rel = str(raw).replace("\\", "/")
    rel = re.sub(r"^.*?csatolmanyok/", "", rel.lstrip("/"))
    if not rel or ".." in rel.split("/"):
        return ""
    path = os.path.join(CSATOLMANYOK_DIR, rel)
    if not os.path.isfile(path):
        return ""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".txt", ".md", ".csv", ".log"):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read(20000)
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(path)
            chunks = []
            for page in reader.pages[:8]:
                chunks.append(page.extract_text() or "")
            return "\n".join(chunks)[:20000]
    except Exception as exc:  # noqa: BLE001 — a csatolmány hibája ne szakítsa meg
        print(f"[AI] csatolmány-szöveg kinyerés hiba: {exc}")
    return ""


@bp.route("/api/uzenet/<int:uzenet_id>/ai", methods=["POST"])
def api_uzenet_ai(uzenet_id):
    if not os.path.exists(DB_FILE):
        return jsonify({"status": "error", "message": "Nincs adatbázis"}), 404
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM uzenetek WHERE id = ?", (uzenet_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify({"status": "error", "message": "Az üzenet nem található"}), 404

    cfg_ai = kreta_ai.ai_config(load_config())
    if not cfg_ai.get("ENABLED"):
        return jsonify({"status": "error", "message": "Az AI-elemzés nincs bekapcsolva."}), 503
    text = kreta_ai.build_text(
        row["targy"] or "", row["szoveg"] or "", _csatolmany_szoveg(row))
    try:
        items = kreta_ai.analyze_text(text, cfg_ai, today=kreta_tanev.today())
    except kreta_ai.AiNotConfigured as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503
    except kreta_ai.AiError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 502

    cfg_cal = kreta_naptar.calendar_config(load_config())
    enriched = []
    for idx, item in enumerate(items):
        event = kreta_naptar.event_from_ai_item(item, cfg_cal, index=idx)
        enriched.append({
            **item,
            "google_url": kreta_naptar.google_calendar_url(event, cfg_cal) if event else "",
        })
    return jsonify({"status": "ok", "model": cfg_ai.get("MODEL"), "items": enriched})


@bp.route("/api/naptar/ai/ics", methods=["POST"])
def api_naptar_ai_ics():
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    if not isinstance(items, list) or not items:
        return jsonify({"status": "error", "message": "Nincs kijelölt esemény"}), 400
    cfg = kreta_naptar.calendar_config(load_config())
    events = []
    for idx, item in enumerate(items[:20]):
        if isinstance(item, dict):
            event = kreta_naptar.event_from_ai_item(item, cfg, index=idx)
            if event:
                events.append(event)
    if not events:
        return jsonify({"status": "error", "message": "Egyik elem sem érvényes esemény"}), 400
    response = make_response(kreta_naptar.ics_multi(events, cfg))
    response.headers["Content-Type"] = "text/calendar; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=\"kreta_ai_{datetime.now().strftime('%Y%m%d_%H%M')}.ics\""
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
    data = request.json or {}
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
