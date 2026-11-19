# -*- coding: utf-8 -*-
"""
Események (KRÉ-14 #95): eseménylista, kész-jelölés, naptár-események.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. Prefix nélküli blueprint —
az URL-ek változatlanok.
"""
import os
from datetime import datetime

from flask import jsonify, request

from kreta_db import (
    get_db_connection, komment_kulcs_esemeny, komment_szamok,
)
from kreta_paths import DB_FILE
from views_common import _tanev_from_request, contrast_text, make_bp, normalize_date, tantargy_kulcs

bp = make_bp("events")

@bp.route("/api/esemenyek")
def api_esemenyek():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "")
    tipus = request.args.get("tipus", "")
    tantargy = request.args.get("tantargy", "")
    tanev = _tanev_from_request()

    query = "SELECT * FROM esemenyek WHERE 1=1"
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    if tipus:
        query += " AND esemeny_tipus = ?"
        params.append(tipus)
    # A tantárgy-szűrést Pythonban végezzük: a KRÉTA írásmódja nem egységes
    # („Angol nyelv" vs. „angol nyelv"), az SQL `=` viszont kis/nagybetű-érzékeny
    # (Kaneo #127). Így a szűrő mindkét írásmódra ugyanazt adja.
    if tanev:
        query += " AND tanev = ?"
        params.append(tanev)

    query += " ORDER BY id DESC"

    # Opcionális lapozás (Kaneo #125): alapból változatlanul minden sor.
    try:
        limit = int(request.args.get("limit") or 0)
    except ValueError:
        limit = 0
    try:
        offset = int(request.args.get("offset") or 0)
    except ValueError:
        offset = 0

    cursor.execute(query, params)
    rows = cursor.fetchall()
    if tantargy:
        kulcs = tantargy_kulcs(tantargy)
        rows = [r for r in rows if tantargy_kulcs(r["tantargy"]) == kulcs]
    if limit > 0:
        rows = rows[offset:offset + limit]
    elif offset > 0:
        rows = rows[offset:]
    komment_db = komment_szamok(cursor, "esemeny")

    esemenyek = []
    for r in rows:
        keys = r.keys()
        kesz_val = r["kesz"] if "kesz" in keys else 0
        kulcs = komment_kulcs_esemeny(r)

        esemenyek.append({
            "id": r["id"],
            "diak_nev": r["diak_nev"],
            "esemeny_tipus": r["esemeny_tipus"],
            "tantargy": r["tantargy"] or "-",
            "ertek": r["ertek"] or "-",
            "szam_ertek": r["szam_ertek"] or 0,
            "suly_szazalek": (r["suly_szazalek"] or 0) if "suly_szazalek" in keys else 0,
            "tanev": (r["tanev"] or "") if "tanev" in keys else "",
            "bej_datum": r["bej_datum"] or "-",
            "letrehozva": (r["letrehozva"] if "letrehozva" in keys else "") or "",
            "hatarido": r["hatarido"] or "-",
            "ertekelo": r["ertekelo"] or "-",
            "tipus": r["tipus"] or "-",
            "mod": r["mod"] or "-",
            "tema": r["tema"] or "-",
            "cim": r["cim"] or "-",
            "tartalom": r["tartalom"] or "-",
            "kesz": int(kesz_val or 0),
            "komment_kulcs": kulcs,
            "komment_db": int(komment_db.get(kulcs, 0))
        })

    conn.close()
    return jsonify(esemenyek)


@bp.route("/api/naptar_esemenyek")
def api_naptar_esemenyek():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "")
    
    query = """
        SELECT * FROM esemenyek 
        WHERE esemeny_tipus IN ('Házi feladat', 'Bejelentett számonkérés')
          AND hatarido IS NOT NULL AND hatarido != '' AND hatarido != '-'
    """
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    mai_datum_str = datetime.now().strftime("%Y-%m-%d")

    events = []
    for r in rows:
        norm_date = normalize_date(r["hatarido"])
        if not norm_date:
            continue

        es_tipus = r["esemeny_tipus"]
        keys = r.keys()
        is_kesz = bool(r["kesz"]) if "kesz" in keys and r["kesz"] else False

        teljes_nev = r["diak_nev"] or "Ismeretlen"

        # Bejelentett számonkérés esetén a 'mod' mező értékét jelenítjük meg, ha rendelkezésre áll
        megjelenitendo_tipus = r["mod"] if (es_tipus == "Bejelentett számonkérés" and r["mod"] and r["mod"] != "-") else es_tipus

        title = f"{teljes_nev}: {r['tantargy']} - {megjelenitendo_tipus}"
        if es_tipus == 'Házi feladat' and is_kesz:
            title = f"✔ {title}"

        is_past = norm_date < mai_datum_str

        if es_tipus == 'Bejelentett számonkérés':
            color = "#f18b95" if is_past else "#dc3545"
        elif es_tipus == 'Házi feladat' and is_kesz:
            color = "#75c099" if is_past else "#198754"
        else:
            color = "#8bb9fe" if is_past else "#0d6efd"

        reszletek = []
        if r['tema'] and r['tema'] != '-': reszletek.append(f"Téma: {r['tema']}")
        if r['cim'] and r['cim'] != '-': reszletek.append(f"Cím: {r['cim']}")
        if r['tartalom'] and r['tartalom'] != '-': reszletek.append(f"{r['tartalom']}")
        leiras = " | ".join(reszletek) or "Nincs részletes leírás"

        events.append({
            "id": r["id"],
            "title": title,
            "start": norm_date,
            "color": color,
            "textColor": contrast_text(color),
            "extendedProps": {
                "diak": teljes_nev,
                "tipus": es_tipus,
                "mod": r["mod"] or "-",
                "tantargy": r["tantargy"],
                "tanar": r["ertekelo"] or "-",
                "leiras": leiras,
                "kesz": is_kesz,
                # A részletek modál ugyanazokat a mezőket kapja, mint az
                # esemény-táblában (Kaneo #126: egységes megjelenés).
                "diak_nev": teljes_nev,
                "esemeny_tipus": es_tipus,
                "ertek": r["ertek"],
                "bej_datum": r["bej_datum"],
                "hatarido": r["hatarido"],
                "ertekelo": r["ertekelo"],
                "tema": r["tema"],
                "cim": r["cim"],
                "tartalom": r["tartalom"],
                "suly_szazalek": r["suly_szazalek"] if "suly_szazalek" in keys else 0,
            }
        })

    return jsonify(events)


@bp.route("/api/esemeny/statusz", methods=["POST"])
def api_esemeny_statusz():
    data = request.get_json(silent=True) or {}
    esemeny_id = data.get("id")
    kesz = 1 if data.get("kesz") else 0

    if not esemeny_id:
        return jsonify({"status": "error", "message": "Hiányzó azonosító"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE esemenyek SET kesz = ? WHERE id = ?", (kesz, esemeny_id))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "kesz": kesz})


# ==============================================================================
