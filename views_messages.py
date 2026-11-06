# -*- coding: utf-8 -*-
"""
Üzenetek (KRÉ-14 #95): lista, olvasottság (egyedi + tömeges), saját megjegyzések.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. Prefix nélküli blueprint —
az URL-ek változatlanok.
"""
import json
import os
import re
import sqlite3

from flask import jsonify, request

from kreta_db import (
    KOMMENT_CEL_TIPUSOK, KOMMENT_MAX_HOSSZ, _now_iso, ensure_run_tables,
    get_db_connection, komment_kulcs_uzenet, komment_szamok,
)
from kreta_paths import DB_FILE
from views_common import make_bp

bp = make_bp("messages")

@bp.route("/api/uzenetek")
def api_uzenetek():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "")
    query = "SELECT * FROM uzenetek WHERE 1=1"
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)

    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    komment_db = komment_szamok(cursor, "uzenet")

    uzenetek = []
    for r in rows:
        keys = r.keys()
        cs_nev = r["csatolmany_nev"] if "csatolmany_nev" in keys else ""
        cs_ut = r["csatolmany_utvonal"] if "csatolmany_utvonal" in keys else ""
        
        nyers_szoveg = r["szoveg"] if "szoveg" in keys and r["szoveg"] else ""
        tisztitott_szoveg = re.sub(r'\n{3,}', '\n\n', nyers_szoveg) if nyers_szoveg else ""
        kulcs = komment_kulcs_uzenet(r)

        olvasott = bool(r["olvasott"]) if "olvasott" in keys and r["olvasott"] else False

        uzenetek.append({
            "id": r["id"],
            "diak_nev": r["diak_nev"] if "diak_nev" in keys else "",
            "felado": r["felado"] if "felado" in keys else "-",
            "targy": r["targy"] if "targy" in keys else "-",
            "idopont": r["idopont"] if "idopont" in keys else "-",
            "szoveg": tisztitott_szoveg,
            "csatolmany_nev": cs_nev or "",
            "csatolmany_utvonal": cs_ut or "",
            "olvasott": olvasott,
            "komment_kulcs": kulcs,
            "komment_db": int(komment_db.get(kulcs, 0))
        })

    conn.close()
    return jsonify(uzenetek)


@bp.route("/api/uzenetek/<int:uzenet_id>/olvasott", methods=["POST"])
def api_uzenet_olvasott(uzenet_id):
    """Üzenet helyi olvasott/olvasatlan állapotának mentése (Kaneo #11).

    A KRÉTA felé nem írunk vissza; az állapot kizárólag a helyi `uzenetek.olvasott`
    oszlopban él, és a szinkron nem írja felül a már mentett sorokat.
    """
    if not os.path.exists(DB_FILE):
        return jsonify({"status": "error", "message": "Nincs adatbázis."}), 404
    data = request.get_json(silent=True) or {}
    olvasott = 1 if data.get("olvasott", True) else 0
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "UPDATE uzenetek SET olvasott = ? WHERE id = ?",
            (olvasott, uzenet_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"status": "error", "message": "Az üzenet nem található."}), 404
    except sqlite3.Error as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()
    return jsonify({"status": "ok", "id": uzenet_id, "olvasott": bool(olvasott)})


@bp.route("/api/uzenetek/olvasott", methods=["POST"])
def api_uzenetek_olvasott_bulk():
    """Több üzenet olvasott/olvasatlan állapotának egyidejű mentése (Kaneo #11).

    Body: `{"olvasott": true|false, "ids": [1,2,...]}` — megadott azonosítókra;
    `ids` nélkül (vagy üres listával) a `diak` szűrő szerinti összes üzenetre
    (üres `diak` = minden üzenet). A KRÉTA felé nem írunk vissza.
    """
    if not os.path.exists(DB_FILE):
        return jsonify({"status": "error", "message": "Nincs adatbázis."}), 404
    data = request.get_json(silent=True) or {}
    olvasott = 1 if data.get("olvasott", True) else 0
    diak = (data.get("diak") or "").strip()
    ids = data.get("ids")

    id_list = []
    if isinstance(ids, list):
        for value in ids:
            try:
                id_list.append(int(value))
            except (TypeError, ValueError):
                continue

    conn = get_db_connection()
    try:
        if id_list:
            placeholders = ",".join("?" for _ in id_list)
            cur = conn.execute(
                f"UPDATE uzenetek SET olvasott = ? WHERE id IN ({placeholders})",
                [olvasott, *id_list],
            )
        elif diak:
            cur = conn.execute(
                "UPDATE uzenetek SET olvasott = ? WHERE diak_nev = ?", (olvasott, diak)
            )
        else:
            cur = conn.execute("UPDATE uzenetek SET olvasott = ?", (olvasott,))
        conn.commit()
        updated = cur.rowcount
    except sqlite3.Error as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()
    return jsonify({"status": "ok", "updated": updated, "olvasott": bool(olvasott)})


@bp.route("/api/kommentek")
def api_kommentek_list():
    """Egy esemény/üzenet saját megjegyzései (legrégebbi elöl)."""
    cel_tipus = (request.args.get("cel_tipus") or "").strip()
    cel_kulcs = (request.args.get("cel_kulcs") or "").strip()
    if cel_tipus not in KOMMENT_CEL_TIPUSOK or not cel_kulcs:
        return jsonify({"status": "error", "message": "Hiányzó vagy hibás cél."}), 400
    if not os.path.exists(DB_FILE):
        return jsonify([])
    try:
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, cel_tipus, cel_kulcs, diak_nev, szoveg, szerzo, letrehozva, modositva"
            " FROM kommentek WHERE cel_tipus = ? AND cel_kulcs = ? ORDER BY id",
            (cel_tipus, cel_kulcs),
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify([dict(r) for r in rows])


@bp.route("/api/kommentek", methods=["POST"])
def api_kommentek_add():
    """Új saját megjegyzés hozzáfűzése."""
    data = request.get_json(silent=True) or {}
    cel_tipus = str(data.get("cel_tipus") or "").strip()
    cel_kulcs = str(data.get("cel_kulcs") or "").strip()
    szoveg = str(data.get("szoveg") or "").strip()
    diak_nev = str(data.get("diak_nev") or "").strip()[:120]
    szerzo = str(data.get("szerzo") or "").strip()[:60] or "Szülő"

    if cel_tipus not in KOMMENT_CEL_TIPUSOK:
        return jsonify({"status": "error", "message": "Ismeretlen cél-típus."}), 400
    if not cel_kulcs or len(cel_kulcs) > 80:
        return jsonify({"status": "error", "message": "Hiányzó vagy hibás cél-azonosító."}), 400
    if not szoveg:
        return jsonify({"status": "error", "message": "A megjegyzés nem lehet üres."}), 400
    if len(szoveg) > KOMMENT_MAX_HOSSZ:
        return jsonify({"status": "error",
                        "message": f"A megjegyzés legfeljebb {KOMMENT_MAX_HOSSZ} karakter lehet."}), 400
    if not os.path.exists(DB_FILE):
        return jsonify({"status": "error", "message": "Az adatbázis még nem létezik."}), 503
    try:
        conn = get_db_connection()
        ensure_run_tables(conn)   # a kommentek tábla migrációja (idempotens)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO kommentek (cel_tipus, cel_kulcs, diak_nev, szoveg, szerzo, letrehozva)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (cel_tipus, cel_kulcs, diak_nev or None, szoveg, szerzo, _now_iso()),
        )
        conn.commit()
        uj_id = cur.lastrowid
        conn.close()
    except sqlite3.Error as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "ok", "id": uj_id})


@bp.route("/api/kommentek/<int:komment_id>", methods=["DELETE"])
def api_kommentek_delete(komment_id):
    """Saját megjegyzés törlése."""
    if not os.path.exists(DB_FILE):
        return jsonify({"status": "error", "message": "Nincs adatbázis."}), 404
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM kommentek WHERE id = ?", (komment_id,))
        torolve = cur.rowcount
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    if not torolve:
        return jsonify({"status": "error", "message": "Nincs ilyen megjegyzés."}), 404
    return jsonify({"status": "ok"})
