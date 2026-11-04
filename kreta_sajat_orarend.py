# -*- coding: utf-8 -*-
"""
Saját (kézzel rögzített) órarendi tételek — Kaneo #55.

A KRÉTA szinkron csak az `orarend` táblát írja; ez a modul külön táblákban
tárolja a szakköröket, plusz foglalkozásokat. A tételek „sorozatként” élnek:
egy sor = egy heti ismétlődés (nap + időpont) egy érvényességi tartományban.
Egyetlen alkalom törlése kivételként kerül a `sajat_orarend_kivetel` táblába,
a sorozat törlése magát a sort (és a kivételeit) törli.

A modul szándékosan független a Flask-től (tesztelhető), az API a app.py-ban van.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import kreta_tanev

NAPOS_NEVEK = {
    1: "Hétfő",
    2: "Kedd",
    3: "Szerda",
    4: "Csütörtök",
    5: "Péntek",
    6: "Szombat",
    7: "Vasárnap",
}

ERVENYESSEG_MODOK = ("tanev", "het", "egyedi")
DEFAULT_SZIN = "#6f42c1"

_MAX_TEXT = {"cim": 120, "terem": 80, "megjegyzes": 500}


class SajatOrarendError(ValueError):
    """Érvénytelen saját órarendi adat (az API 400-at ad rá)."""


def ensure_schema(conn) -> None:
    """A saját órarend tábláinak létrehozása (idempotens)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sajat_orarend (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            diak_nev TEXT NOT NULL,
            cim TEXT NOT NULL,
            nap INTEGER NOT NULL,
            kezdes TEXT NOT NULL,
            vege TEXT NOT NULL,
            terem TEXT DEFAULT '',
            megjegyzes TEXT DEFAULT '',
            szin TEXT DEFAULT '#6f42c1',
            ervenyes_tol TEXT NOT NULL,
            ervenyes_ig TEXT NOT NULL,
            letrehozva TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Régi DB: a szín oszlop utólag is bekerül (Kaneo #55).
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sajat_orarend)").fetchall()}
    if "szin" not in cols:
        conn.execute("ALTER TABLE sajat_orarend ADD COLUMN szin TEXT DEFAULT '#6f42c1'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sajat_orarend_kivetel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sajat_id INTEGER NOT NULL,
            datum TEXT NOT NULL,
            UNIQUE(sajat_id, datum)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sajat_orarend_diak "
        "ON sajat_orarend(diak_nev, nap)"
    )
    conn.commit()


def _parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    text = text[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _norm_hm(value, mezo: str) -> str:
    match = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(value or ""))
    if not match:
        raise SajatOrarendError(f"A(z) {mezo} formátuma óó:pp legyen (pl. 16:00).")
    ora, perc = int(match.group(1)), int(match.group(2))
    if ora > 23 or perc > 59:
        raise SajatOrarendError(f"A(z) {mezo} nem érvényes időpont.")
    return f"{ora:02d}:{perc:02d}"


def _text(value, mezo: str, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise SajatOrarendError(f"A(z) {mezo} megadása kötelező.")
    limit = _MAX_TEXT.get(mezo)
    if limit and len(text) > limit:
        raise SajatOrarendError(f"A(z) {mezo} legfeljebb {limit} karakter lehet.")
    return text


def _nap(value) -> int:
    try:
        nap = int(value)
    except (TypeError, ValueError):
        raise SajatOrarendError("A nap 1 (hétfő) és 7 (vasárnap) között legyen.")
    if nap not in NAPOS_NEVEK:
        raise SajatOrarendError("A nap 1 (hétfő) és 7 (vasárnap) között legyen.")
    return nap


def week_bounds(ref: date) -> tuple[date, date]:
    """A `ref` napot tartalmazó hét hétfője és vasárnapja."""
    monday = ref - timedelta(days=ref.weekday())
    return monday, monday + timedelta(days=6)


def resolve_validity(payload: dict, today: date | None = None) -> tuple[date, date]:
    """Az érvényesség típusából (tanev/het/egyedi) kiszámolja a dátumtartományt."""
    today = today or date.today()
    mode = str(payload.get("ervenyesites") or "tanev").strip()
    if mode not in ERVENYESSEG_MODOK:
        raise SajatOrarendError("Az érvényesség tanev, het vagy egyedi legyen.")

    if mode == "tanev":
        tanev = kreta_tanev.current_tanev(today)
        start, end = kreta_tanev.tanev_bounds(tanev)
        if not start or not end:
            start, end = today, today + timedelta(days=365)
        return start, end

    if mode == "het":
        ref = _parse_date(payload.get("datum")) or today
        return week_bounds(ref)

    start = _parse_date(payload.get("tol"))
    end = _parse_date(payload.get("ig"))
    if not start or not end:
        raise SajatOrarendError("Egyedi érvényességhez a kezdő és záró dátum kell.")
    if start > end:
        raise SajatOrarendError("Az érvényesség kezdete nem lehet később a végénél.")
    return start, end


def validate_entry(payload: dict, today: date | None = None) -> dict:
    """A bemenet normalizálása/ellenőrzése; hibára `SajatOrarendError`."""
    diak = _text(payload.get("diak_nev"), "diák", required=True)
    cim = _text(payload.get("cim"), "cím", required=True)
    nap = _nap(payload.get("nap"))
    kezdes = _norm_hm(payload.get("kezdes"), "kezdés")
    vege = _norm_hm(payload.get("vege"), "vég")
    if vege <= kezdes:
        raise SajatOrarendError("A vég időpontjának később kell lennie a kezdésnél.")
    start, end = resolve_validity(payload, today=today)
    szin = str(payload.get("szin") or DEFAULT_SZIN).strip()
    if not re.match(r"^#[0-9a-fA-F]{6}$", szin):
        raise SajatOrarendError("A szín #rrggbb formátumú legyen.")
    return {
        "diak_nev": diak,
        "cim": cim,
        "nap": nap,
        "kezdes": kezdes,
        "vege": vege,
        "terem": _text(payload.get("terem"), "terem"),
        "megjegyzes": _text(payload.get("megjegyzes"), "megjegyzés"),
        "szin": szin,
        "ervenyes_tol": start.isoformat(),
        "ervenyes_ig": end.isoformat(),
    }


def list_series(conn, diak: str = "") -> list[dict]:
    query = "SELECT * FROM sajat_orarend WHERE 1=1"
    params: list = []
    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    query += " ORDER BY nap, kezdes, cim"
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def create_series(conn, payload: dict, today: date | None = None) -> dict:
    data = validate_entry(payload, today=today)
    cursor = conn.execute(
        "INSERT INTO sajat_orarend (diak_nev, cim, nap, kezdes, vege, terem, "
        "megjegyzes, szin, ervenyes_tol, ervenyes_ig) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            data["diak_nev"], data["cim"], data["nap"], data["kezdes"], data["vege"],
            data["terem"], data["megjegyzes"], data["szin"], data["ervenyes_tol"], data["ervenyes_ig"],
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM sajat_orarend WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def delete_series(conn, series_id: int) -> bool:
    conn.execute("DELETE FROM sajat_orarend_kivetel WHERE sajat_id = ?", (series_id,))
    cursor = conn.execute("DELETE FROM sajat_orarend WHERE id = ?", (series_id,))
    conn.commit()
    return cursor.rowcount > 0


def add_exception(conn, series_id: int, datum) -> bool:
    """Egyetlen alkalom kivétele; False, ha a sorozat nem létezik."""
    row = conn.execute("SELECT * FROM sajat_orarend WHERE id = ?", (series_id,)).fetchone()
    if not row:
        return False
    day = _parse_date(datum)
    if not day:
        raise SajatOrarendError("A kivétel dátuma éééé-hh-nn formátumú legyen.")
    if day < _parse_date(row["ervenyes_tol"]) or day > _parse_date(row["ervenyes_ig"]):
        raise SajatOrarendError("A kivétel dátuma a sorozat érvényességén kívül esik.")
    conn.execute(
        "INSERT OR IGNORE INTO sajat_orarend_kivetel (sajat_id, datum) VALUES (?, ?)",
        (series_id, day.isoformat()),
    )
    conn.commit()
    return True


def _series_exceptions(conn, series_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT datum FROM sajat_orarend_kivetel WHERE sajat_id = ?", (series_id,)
    ).fetchall()
    return {r["datum"] for r in rows}


def expand_occurrences(conn, diak: str = "", start=None, end=None) -> list[dict]:
    """A sorozatokból konkrét alkalmak generálása a kért időablakban.

    `start`/`end` a FullCalendar ablakhatárai (az `end` EXKLUZÍV, mint a
    FullCalendar esemény-vég). Ha nincs megadva, a sorozat teljes érvényessége.
    """
    req_start = _parse_date(start)
    req_end = _parse_date(end)
    if req_end:
        req_end -= timedelta(days=1)   # FullCalendar end exkluzív
    if req_start and req_end and req_start > req_end:
        return []

    occurrences = []
    for row in list_series(conn, diak=diak):
        tol = _parse_date(row["ervenyes_tol"])
        ig = _parse_date(row["ervenyes_ig"])
        if not tol or not ig:
            continue
        lo = max(tol, req_start) if req_start else tol
        hi = min(ig, req_end) if req_end else ig
        if lo > hi:
            continue
        exceptions = _series_exceptions(conn, row["id"])
        # Az első előfordulás: a kért nap (1=hétfő) a tartományon belül.
        first = lo + timedelta(days=((row["nap"] - 1) - lo.weekday()) % 7)
        current = first
        while current <= hi:
            datum = current.isoformat()
            if datum not in exceptions:
                occurrences.append({
                    "sajat_id": row["id"],
                    "diak_nev": row["diak_nev"],
                    "cim": row["cim"],
                    "nap": row["nap"],
                    "datum": datum,
                    "kezdes": row["kezdes"],
                    "vege": row["vege"],
                    "terem": row["terem"] or "",
                    "megjegyzes": row["megjegyzes"] or "",
                    "szin": row["szin"] or DEFAULT_SZIN,
                    "ervenyes_tol": row["ervenyes_tol"],
                    "ervenyes_ig": row["ervenyes_ig"],
                })
            current += timedelta(days=7)

    occurrences.sort(key=lambda item: (item["datum"], item["kezdes"], item["cim"]))
    return occurrences
