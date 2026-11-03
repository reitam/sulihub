# -*- coding: utf-8 -*-
"""Tanév-kezelés a KRÉTA adatokhoz (Kaneo #40).

A tanévet **a rekord saját dátumából számítjuk** (szeptember 1. – augusztus 31.),
mert a KRÉTA mobil API a rekordokhoz nem ad tanévet (csak a `TanuloAdatlap.TanevUid`
belső azonosítót, ami történeti sorokhoz nem rendelhető). A modul ezért:

- tiszta függvényeket ad a tanév számítására (`tanev_of`, `tanev_bounds`,
  `current_tanev`, `row_tanev`), tesztelhető `today=` paraméterrel és
  `KRETA_TODAY` env felülírással;
- séma-migrációt (`ensure_tanev_schema`) és feltöltést (`backfill_tanev`) a
  meglévő adatbázisokhoz — **csak UPDATE**, hogy az ID-k ne változzanak;
- a teljes cserék törlési jogosultságához a `teljesen_lekert` predikátumot.

A tanév kanonikus alakja: ``"2026/2027"``. A ``NULL`` azt jelenti, hogy a mezőt
még nem töltötte ki a migráció; az üres string (``""``) azt, hogy a dátumból nem
lehetett meghatározni (ismeretlen).
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta

#: Tanév-kezdő hónap/nap (a KRÉTA-ban szeptember 1.); env: ``KRETA_TANEV_KEZDO=09-01``
DEFAULT_TANEV_KEZDO = (9, 1)

TANEV_FORRAS_MIGRACIO = "migracio"
TANEV_FORRAS_SZAMITOTT = "szamitott"
TANEV_FORRAS_KRETA = "kreta"

#: Ezeknél a jövőbeli dátum (határidő) dönt a tanévről (Kaneo #40 / K5 döntés).
FUTURE_DATED_EVENT_TYPES = ("Házi feladat", "Bejelentett számonkérés")

#: Melyik tábla melyik dátummezőjéből számoljuk a tanévet (sorrend = első találat).
ROW_DATE_FIELDS = {
    "esemenyek": ("bej_datum", "hatarido"),
    "hianyzasok": ("mulasztas_datum",),
    "igazolasok": ("kezdete", "vege"),
    "uzenetek": ("idopont",),
    "kifizetesek": ("kezdo_datum",),
}

TANEV_TABLES = tuple(ROW_DATE_FIELDS)
SYNC_RUN_TABLE = "sync_runs"

_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
_HU_RE = re.compile(r"^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.")


def tan_ev_kezdo() -> tuple[int, int]:
    """A tanév kezdő (hónap, nap) párja; env: ``KRETA_TANEV_KEZDO`` (pl. ``09-01``)."""
    raw = str(os.environ.get("KRETA_TANEV_KEZDO", "")).strip()
    if not raw:
        return DEFAULT_TANEV_KEZDO
    match = re.match(r"^(\d{1,2})[-.:/](\d{1,2})$", raw)
    if not match:
        return DEFAULT_TANEV_KEZDO
    month, day = int(match.group(1)), int(match.group(2))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return DEFAULT_TANEV_KEZDO
    return month, day


def today() -> date:
    """Az aktuális nap; teszteléshez a ``KRETA_TODAY=YYYY-MM-DD`` env írja felül."""
    raw = str(os.environ.get("KRETA_TODAY", "")).strip()
    if raw:
        parsed = parse_date(raw)
        if parsed:
            return parsed
    return date.today()


def parse_date(value) -> date | None:
    """Dátum értelmezése a projektben előforduló formátumokból.

    Támogatott: ``2026-09-01`` (ISO, opcionális idővel), ``2026. 09. 01.``
    és ``2026. 09. 22. 1:33`` (KRÉTA magyar formátum).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    match = _ISO_RE.match(text) or _HU_RE.match(text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def tanev_of(value) -> str:
    """Egy dátum tanéve (``"2026/2027"``), vagy ``""`` ha nem értelmezhető."""
    d = parse_date(value)
    if d is None:
        return ""
    month, day = tan_ev_kezdo()
    kezdo_ev = d.year if (d.month, d.day) >= (month, day) else d.year - 1
    return f"{kezdo_ev}/{kezdo_ev + 1}"


def tanev_bounds(tanev: str) -> tuple[date | None, date | None]:
    """``"2026/2027"`` -> ``(2026-09-01, 2027-08-31)``; hibás bemenetre ``(None, None)``."""
    text = str(tanev or "").strip()
    match = re.match(r"^(\d{4})\s*/\s*(\d{4})$", text)
    if not match:
        return None, None
    start_year, end_year = int(match.group(1)), int(match.group(2))
    if end_year != start_year + 1:
        return None, None
    month, day = tan_ev_kezdo()
    try:
        start = date(start_year, month, day)
        end = date(end_year, month, day) - timedelta(days=1)
    except ValueError:
        return None, None
    return start, end


def current_tanev(today_value=None) -> str:
    """A naptár szerinti aktuális tanév (nyáron a záruló tanév)."""
    d = parse_date(today_value) if today_value is not None else today()
    return tanev_of(d) if d else ""


def _get(row, key, default=""):
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        keys = row.keys()
    except Exception:
        keys = []
    if key in keys:
        return row[key]
    return default


def row_tanev(table: str, row) -> str:
    """Egy DB-sor tanéve a tábla dátummezőjéből.

    A házi feladatnál és a bejelentett számonkérésnél a **határidő** dönt
    (a nyár végén kiadott, szeptemberi határidejű feladat az új tanévhez tartozik).
    Ha a határidő hiányzik/értelmezhetetlen, a bejegyzés dátuma számít.
    """
    if row is None:
        return ""
    if table == "esemenyek":
        tipus = str(_get(row, "esemeny_tipus"))
        if tipus in FUTURE_DATED_EVENT_TYPES:
            hatarido = tanev_of(_get(row, "hatarido"))
            if hatarido:
                return hatarido
        bej = tanev_of(_get(row, "bej_datum"))
        if bej:
            return bej
        return tanev_of(_get(row, "hatarido"))
    for mezo in ROW_DATE_FIELDS.get(table, ()):
        ertek = tanev_of(_get(row, mezo))
        if ertek:
            return ertek
    return ""


def zaro_tanev() -> str:
    """A tanévzáró futás cél-tanéve (env: ``KRETA_ZARO_TANEV``), vagy ``""``.

    Kézi „Tanév lezárása” (Kaneo #52): ilyenkor a szinkron a megadott (már lezárt)
    tanév **teljes** ablakát kéri le, hogy a pótvizsga/augusztusi jegyek is
    bekerüljenek. Érvénytelen tanévre üres marad.
    """
    raw = str(os.environ.get("KRETA_ZARO_TANEV", "")).strip()
    if not raw:
        return ""
    kezd, veg = tanev_bounds(raw)
    return raw if (kezd and veg) else ""


def teljesen_lekert(tanev: str, start, end, today_value=None) -> bool:
    """Lefedi-e a lekérési ablak a tanévet (a törlés előfeltétele).

    A jövő nem kérhető le, ezért a tanév vége helyett a mai nap a korlát:
    az ablaknak a tanév **elejétől** kell indulnia, és legalább a mai napig
    (vagy a tanév végéig) tartania.
    """
    kezd, veg = tanev_bounds(tanev)
    if kezd is None or veg is None:
        return False
    start_d = parse_date(start)
    end_d = parse_date(end)
    if start_d is None or end_d is None:
        return False
    if start_d > kezd:
        return False
    mai = parse_date(today_value) if today_value is not None else today()
    if mai is None:
        return False
    return end_d >= min(veg, mai)


def _table_columns(conn, table: str) -> list[str]:
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return []


def ensure_tanev_schema(conn, log_fn=print) -> list[str]:
    """A tanév-oszlopok és indexek létrehozása a meglévő adatbázisban.

    Csak hozzáad (ALTER TABLE ADD COLUMN), nem épít újra táblát, és a nem
    létező táblákat kihagyja. Visszaadja a hozzáadott oszlopok listáját
    (pl. ``["esemenyek.tanev", ...]``) — a hívó naplózza.
    """
    added: list[str] = []
    for table in TANEV_TABLES + (SYNC_RUN_TABLE,):
        columns = _table_columns(conn, table)
        if not columns:
            continue  # a táblát más hozza létre (pl. üres DB első indulása)
        wanted = ("tanev",) if table == SYNC_RUN_TABLE else ("tanev", "tanev_forras")
        for column in wanted:
            if column in columns:
                continue
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
                added.append(f"{table}.{column}")
            except Exception as exc:  # zárolt DB / verseny: nem kritikus
                if log_fn:
                    log_fn(f"  [Tanév séma] {table}.{column} hozzáadása nem sikerült: {exc}")
    for table in TANEV_TABLES:
        if not _table_columns(conn, table):
            continue
        try:
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_tanev ON {table}(diak_nev, tanev)")
        except Exception:
            pass
    return added


def backfill_tanev(conn, batch: int = 500, log_fn=print) -> dict:
    """A meglévő sorok tanévének kitöltése (csak UPDATE, ID-stabil).

    Újraindítható: csak a ``tanev IS NULL`` sorokat dolgozza fel, így egy
    megszakadt futás után a következő indulás befejezi. A dátum nélküli sorok
    tanéve ``""`` (ismeretlen) lesz, nem ``NULL`` — így nem indul újra.
    """
    stats: dict[str, dict] = {}
    for table in TANEV_TABLES:
        columns = _table_columns(conn, table)
        if not columns or "tanev" not in columns:
            continue
        if table == "esemenyek":
            fields = [f for f in ("esemeny_tipus", "bej_datum", "hatarido") if f in columns]
        else:
            fields = [f for f in ROW_DATE_FIELDS.get(table, ()) if f in columns]
        select_fields = ", ".join(fields) if fields else "NULL"
        updated = 0
        unknown = 0
        while True:
            try:
                rows = conn.execute(
                    f"SELECT id, {select_fields} FROM {table} WHERE tanev IS NULL LIMIT ?",
                    (batch,),
                ).fetchall()
            except Exception as exc:
                if log_fn:
                    log_fn(f"  [Tanév backfill] {table}: olvasási hiba: {exc}")
                break
            if not rows:
                break
            names = ["id"] + fields
            for row in rows:
                data = dict(zip(names, row))
                tanev = row_tanev(table, data)
                conn.execute(
                    f"UPDATE {table} SET tanev = ?, tanev_forras = ? WHERE id = ?",
                    (tanev, TANEV_FORRAS_MIGRACIO, data["id"]),
                )
                if tanev:
                    updated += 1
                else:
                    unknown += 1
            conn.commit()
        if updated or unknown:
            stats[table] = {"updated": updated, "unknown": unknown}
            if log_fn:
                log_fn(f"  [Tanév backfill] {table}: {updated} sor tanévvel, "
                       f"{unknown} ismeretlen dátumú")
    return stats


def unsynced_rows(conn) -> int:
    """Hány sor vár még tanév-kitöltésre (migráció-ellenőrzéshez)."""
    total = 0
    for table in TANEV_TABLES:
        columns = _table_columns(conn, table)
        if not columns or "tanev" not in columns:
            continue
        try:
            total += conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE tanev IS NULL").fetchone()[0]
        except Exception:
            pass
    return total
