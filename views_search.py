# -*- coding: utf-8 -*-
"""
Globális kereső (Kaneo #85): jegyek, feljegyzések, házik, üzenetek, hiányzások.

Egy végpont: `GET /api/kereses?q=...&limit=20`. A találatok a megfelelő nézetet
nyitják a felületen. Prefix nélküli blueprint — az URL a megszokott `/api/...`.
"""
import os
import sqlite3
import time

from flask import jsonify, request

from kreta_db import get_db_connection
from kreta_paths import DB_FILE
from views_common import make_bp, normalize_date

bp = make_bp("search")

MAX_LIMIT = 50
MIN_Q = 2


def _like(q: str) -> str:
    """LIKE-minta a `%`/`_`/`\\` karakterek escape-elésével."""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _snippet(text, q, width=80):
    """Rövid kivonat a találat körül (kis/nagybetűtől függetlenül keres)."""
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    if len(text) <= width:
        return text
    low = text.lower()
    idx = low.find(str(q).lower())
    if idx < 0:
        return text[:width].rstrip() + "…"
    start = max(0, idx - width // 3)
    end = min(len(text), start + width)
    res = text[start:end].strip()
    return ("…" if start > 0 else "") + res + ("…" if end < len(text) else "")


def _fts_azonosítók(cursor, tabla, q, limit):
    """FTS5 jelölt-rowid-ek (Kaneo #107); None, ha nincs FTS vagy rövid a keresés.

    A trigram tokenizáló a 3+ karakteres részszövegeket is megtalálja. Ha nincs
    találat, a hívó a LIKE-útra esik vissza (biztonsági háló).
    """
    if len(q) < 3:
        return None
    try:
        cursor.execute(
            f"SELECT rowid FROM {tabla} WHERE {tabla} MATCH ? LIMIT ?",
            ('"' + q.lower().replace('"', '""') + '"', max(limit * 5, 50)))
        return [r[0] for r in cursor.fetchall()]
    except sqlite3.Error:
        return None


@bp.route("/api/kereses")
def api_kereses():
    started = time.perf_counter()
    q = (request.args.get("q") or "").strip()
    try:
        limit = int(request.args.get("limit") or 20)
    except ValueError:
        limit = 20
    limit = max(1, min(limit, MAX_LIMIT))
    if len(q) < MIN_Q:
        return jsonify({"q": q, "talalatok": [], "count": 0, "ido_ms": 0})
    if not os.path.exists(DB_FILE):
        return jsonify({"q": q, "talalatok": [], "count": 0, "ido_ms": 0})

    like = _like(q)
    talalatok = []
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1) Események: jegy, feljegyzés, házi, számonkérés (téma/cím/tartalom/tantárgy/érték).
    try:
        fts_ids = _fts_azonosítók(cursor, "esemenyek_fts", q, limit)
        if fts_ids:
            # Az FTS Unicode-tudatos (ékezet/kis-nagybetű); a LIKE-ra itt nem
            # szűrünk rá, mert az csak ASCII-nél case-insensitive (Kaneo #125).
            sql = ("SELECT id, diak_nev, esemeny_tipus, tantargy, tema, cim, tartalom, ertek,"
                   " bej_datum, hatarido FROM esemenyek"
                   f" WHERE id IN ({','.join('?' * len(fts_ids))})")
            params = list(fts_ids)
        else:
            sql = ("SELECT id, diak_nev, esemeny_tipus, tantargy, tema, cim, tartalom, ertek,"
                   " bej_datum, hatarido FROM esemenyek"
                   " WHERE (tantargy LIKE ? ESCAPE '\\' OR tema LIKE ? ESCAPE '\\'"
                   " OR cim LIKE ? ESCAPE '\\' OR tartalom LIKE ? ESCAPE '\\'"
                   " OR ertek LIKE ? ESCAPE '\\')")
            params = [like, like, like, like, like]
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cursor.execute(sql, params)
        for row in cursor.fetchall():
            cim = " – ".join(x for x in (row["tantargy"], row["tema"] or row["cim"]) if x)
            if not cim:
                cim = row["ertek"] or row["esemeny_tipus"]
            talalatok.append({
                "tipus": "esemeny",
                "esemeny_tipus": row["esemeny_tipus"] or "",
                "id": row["id"],
                "diak": row["diak_nev"] or "",
                "cim": cim,
                "reszlet": _snippet(" ".join(
                    x for x in (row["tartalom"], row["ertek"], row["tantargy"]) if x), q),
                "datum": normalize_date(row["bej_datum"]) or normalize_date(row["hatarido"]) or "",
                "tantargy": row["tantargy"] or "",
            })
    except sqlite3.Error as exc:
        print(f"[Keresés] események: {exc}")

    # 2) Üzenetek (a teljes törzsben).
    try:
        fts_ids = _fts_azonosítók(cursor, "uzenetek_fts", q, limit)
        if fts_ids:
            sql = ("SELECT id, diak_nev, felado, targy, idopont, szoveg FROM uzenetek"
                   f" WHERE id IN ({','.join('?' * len(fts_ids))})")
            params = list(fts_ids)
        else:
            sql = ("SELECT id, diak_nev, felado, targy, idopont, szoveg FROM uzenetek"
                   " WHERE (targy LIKE ? ESCAPE '\\' OR felado LIKE ? ESCAPE '\\'"
                   " OR szoveg LIKE ? ESCAPE '\\')")
            params = [like, like, like]
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cursor.execute(sql, params)
        for row in cursor.fetchall():
            talalatok.append({
                "tipus": "uzenet",
                "id": row["id"],
                "diak": row["diak_nev"] or "",
                "cim": row["targy"] or "(nincs tárgy)",
                "reszlet": _snippet(row["szoveg"], q),
                "datum": normalize_date((row["idopont"] or "")[:10]) or "",
                "felado": row["felado"] or "",
            })
    except sqlite3.Error as exc:
        print(f"[Keresés] üzenetek: {exc}")

    # 3) Hiányzások / késések.
    try:
        cursor.execute(
            "SELECT id, diak_nev, mulasztas_datum, tantargy, tema, mulasztas_tipus"
            " FROM hianyzasok WHERE tantargy LIKE ? ESCAPE '\\' OR tema LIKE ? ESCAPE '\\'"
            " OR mulasztas_tipus LIKE ? ESCAPE '\\'"
            " ORDER BY id DESC LIMIT ?",
            (like, like, like, limit))
        for row in cursor.fetchall():
            cim = " – ".join(x for x in (row["tantargy"], row["mulasztas_tipus"]) if x)
            talalatok.append({
                "tipus": "hianyzas",
                "id": row["id"],
                "diak": row["diak_nev"] or "",
                "cim": cim or "Hiányzás",
                "reszlet": _snippet(row["tema"], q),
                "datum": normalize_date(row["mulasztas_datum"]) or "",
                "tantargy": row["tantargy"] or "",
            })
    except sqlite3.Error as exc:
        print(f"[Keresés] hiányzások: {exc}")

    conn.close()

    talalatok.sort(key=lambda t: (t.get("datum") or "", t.get("id") or 0), reverse=True)
    talalatok = talalatok[:limit]
    return jsonify({
        "q": q,
        "count": len(talalatok),
        "talalatok": talalatok,
        "ido_ms": int((time.perf_counter() - started) * 1000),
    })
