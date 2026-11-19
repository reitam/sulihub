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
import sqlite3
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
#: A tanév-választóhoz (UI) tartozó táblák: az üzenetek tanév-függetlenek,
#: ezért azokból nem származtatunk tanévet a választóhoz/állapot-seedhez.
TANEV_UI_TABLES = ("esemenyek", "hianyzasok", "igazolasok", "kifizetesek")
SYNC_RUN_TABLE = "sync_runs"
TANEV_STATE_TABLE = "tanevek"
TANEV_UID_TABLE = "tanulo_tanev_uid"

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


FIRST_SEEN_TABLES = (
    ("esemenyek", "bej_datum"),
    ("uzenetek", "idopont"),
    ("hianyzasok", "mulasztas_datum"),
    ("igazolasok", "kezdete"),
)
FIRST_SEEN_RECENT_DAYS = 2
FIRST_SEEN_MAX_RECENT_DAYS = 31


def _first_seen_recent_days(value=None) -> int:
    """A first-seen ablak napjai (alap 2, env: KRETA_FIRST_SEEN_RECENT_DAYS)."""
    raw = value if value is not None else os.environ.get(
        "KRETA_FIRST_SEEN_RECENT_DAYS", FIRST_SEEN_RECENT_DAYS)
    try:
        days = int(raw)
    except (TypeError, ValueError):
        days = FIRST_SEEN_RECENT_DAYS
    return max(1, min(days, FIRST_SEEN_MAX_RECENT_DAYS))


def ensure_first_seen_schema(conn, log_fn=print, recent_days=None):
    """`letrehozva` oszlop + backfill a régi sorokra (#147), idempotensen.

    A valódi „mikor került be” időpont a bevezetés előtti soroknál nem ismert.
    Ezért az **első** feltöltésnél (amikor az oszlop most jön létre, vagy még
    minden értéke üres) a legutóbbi ``recent_days`` nap sorai a mostani
    időpontot kapják — ezek a felhasználó számára ténylegesen újak, csak a
    KRÉTA visszamenőleges dátumot adott nekik. A régebbi sorok a KRÉTA-dátumot
    kapják, így nem jelennek meg visszamenőleg „újként”. Későbbi pótlásnál
    (részleges NULL-ok) már csak a KRÉTA-dátum a fallback.

    A ``recent_days`` alapértéke 2 (a tegnap+ma), felülírható a
    ``KRETA_FIRST_SEEN_RECENT_DAYS`` env-vel vagy paraméterrel. A ``KRETA_TODAY``
    env (a modul :func:`today` helperje) a tesztelést szolgálja.
    """
    cur = conn.cursor()
    ref = today()
    now = datetime.now()
    now_stamp = f"{ref.isoformat()} {now.strftime('%H:%M:%S')}"
    days = _first_seen_recent_days(recent_days)
    recent_cutoff = ref - timedelta(days=days - 1)
    for table, date_col in FIRST_SEEN_TABLES:
        try:
            cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})")]
        except sqlite3.Error:
            continue
        if not cols:
            continue
        created = "letrehozva" not in cols
        if created:
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN letrehozva TEXT")
                if log_fn:
                    log_fn(f"[Adatbázis séma frissítve]: '{table}.letrehozva' hozzáadva.")
            except sqlite3.Error as exc:
                # Párhuzamos init_db: a másik folyamat már hozzáadhatta.
                if "duplicate column" not in str(exc).lower():
                    if log_fn:
                        log_fn(f"[Adatbázis séma] {table}.letrehozva hozzáadása kihagyva: {exc}")
                    continue
        try:
            rows = cur.execute(
                f"SELECT id, {date_col} FROM {table}"
                " WHERE letrehozva IS NULL OR letrehozva = ''").fetchall()
            total = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            # Ha a teljes oszlop üres, ez az első feltöltés (pl. megszakadt
            # migráció után is), ilyenkor a friss sorok „most” értéket kapnak.
            initial = created or (total > 0 and len(rows) == total)
            friss = 0
            for rid, value in rows:
                day = parse_date(value)
                if initial and day is not None and day >= recent_cutoff:
                    stamp = now_stamp
                    friss += 1
                else:
                    stamp = (day.isoformat() + " 00:00:00") if day else "1970-01-01 00:00:00"
                cur.execute(f"UPDATE {table} SET letrehozva = ? WHERE id = ?", (stamp, rid))
            if friss and log_fn:
                log_fn(f"[Adatbázis séma] {table}: {friss} friss sor a mostani időpontra állítva."
                       " (A KRÉTA visszamenőleges dátumot adott ezekre.)")
        except sqlite3.Error as exc:
            if log_fn:
                log_fn(f"[Adatbázis séma] {table}.letrehozva backfill kihagyva: {exc}")
        try:
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_letrehozva"
                f" ON {table}(letrehozva)")
        except sqlite3.Error:
            pass
    conn.commit()


def restamp_first_seen_recent(conn, log_fn=print, recent_days=None):
    """A már v5-ös DB-knél a régi, éjfélre backfillt friss sorok átpecsételése (#149).

    Csak azokat a sorokat érinti, amelyek ``letrehozva`` értéke pontosan a
    KRÉTA-dátum ``00:00:00``-ja, és a KRÉTA-dátum a legutóbbi ``recent_days``
    napban van. A v5 utáni, valódi időbélyeges sorokat nem bántja, így az éles
    DB-n (ahol a 7 napos pecsét már megtörtént) ez a lépés no-op.
    """
    cur = conn.cursor()
    ref = today()
    now = datetime.now()
    stamp = f"{ref.isoformat()} {now.strftime('%H:%M:%S')}"
    days = _first_seen_recent_days(recent_days)
    cutoff = ref - timedelta(days=days - 1)
    for table, date_col in FIRST_SEEN_TABLES:
        try:
            rows = cur.execute(
                f"SELECT id, {date_col}, letrehozva FROM {table}").fetchall()
        except sqlite3.Error:
            continue
        friss = 0
        for rid, value, lh in rows:
            if not lh:
                continue
            day = parse_date(value)
            if day is None or day < cutoff:
                continue
            if not str(lh).endswith("00:00:00") or str(lh)[:10] != day.isoformat():
                continue
            cur.execute(f"UPDATE {table} SET letrehozva = ? WHERE id = ?", (stamp, rid))
            friss += 1
        if friss and log_fn:
            log_fn(f"[Adatbázis séma] {table}: {friss} régi friss sor újrapecsételve (v6).")
    conn.commit()


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


# ── Tanév-állapot: automatikus zárás/nyitás a TanevUid alapján (Kaneo #43) ──
# A KRÉTA mobil API a diák scope-ban csak a nyers `TanevUid`-t adja (a
# `/Sajat/Tanevek` és `/Sajat/Tanulo` 403), ezért a váltást a UID változása
# jelzi, a nevet pedig a dátumból generáljuk a váltás pillanatában.
# A zárás **technikai**: nincs visszamenőleges adatlekérés (az API nem is adja).

def ensure_tanev_state_schema(conn, log_fn=print) -> None:
    """A `tanevek` és `tanulo_tanev_uid` táblák létrehozása (idempotens)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tanevek (
            tanev      TEXT PRIMARY KEY,
            kezdet     TEXT,
            veg        TEXT,
            allapot    TEXT NOT NULL DEFAULT 'nyitott',
            lezarva_at TEXT,
            forras     TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tanulo_tanev_uid (
            diak_nev   TEXT PRIMARY KEY,
            tanev_uid  TEXT,
            tanev      TEXT,
            first_seen TEXT,
            last_seen  TEXT
        )
    """)
    conn.commit()


def _iso_now(now=None) -> str:
    moment = now or datetime.now()
    return moment.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


def _year_bounds_iso(tanev: str) -> tuple[str, str]:
    kezd, veg = tanev_bounds(tanev)
    return (kezd.isoformat() if kezd else "", veg.isoformat() if veg else "")


def tanev_allapotok(conn) -> dict:
    """`{tanev: {"allapot", "lezarva_at", "forras", "kezdet", "veg"}}`."""
    try:
        rows = conn.execute(
            "SELECT tanev, kezdet, veg, allapot, lezarva_at, forras FROM tanevek"
        ).fetchall()
    except Exception:
        return {}
    return {
        row[0]: {"kezdet": row[1] or "", "veg": row[2] or "",
                 "allapot": row[3] or "nyitott", "lezarva_at": row[4] or "",
                 "forras": row[5] or ""}
        for row in rows
    }


def nyitott_tanev(conn) -> str:
    """A jelenleg nyitott tanév (a legutóbbi nyitott sor), vagy ``""``."""
    try:
        row = conn.execute(
            "SELECT tanev FROM tanevek WHERE allapot = 'nyitott'"
            " ORDER BY tanev DESC LIMIT 1").fetchone()
    except Exception:
        return ""
    return (row[0] if row else "") or ""


def seed_tanev_state(conn, today_value=None, log_fn=print) -> list[str]:
    """A meglévő **iskolai** adatokból a tanév-állapot inicializálása.

    Csak a `TANEV_UI_TABLES` táblákból (jegy/hiányzás/igazolás/kifizetés)
    származó tanéveket veszi figyelembe — az üzenetek tanév-függetlenek, ezért
    azokból nem lesz tanév a választóban/állapotban. A mai napnál korábbi
    tanévek ``lezart`` (a tanév végével), az aktuális ``nyitott``. Csak a
    hiányzó sorokat szúrja be (idempotens).
    """
    current = current_tanev(today_value)
    years = set()
    for table in TANEV_UI_TABLES:
        columns = _table_columns(conn, table)
        if not columns or "tanev" not in columns:
            continue
        try:
            for row in conn.execute(
                    f"SELECT DISTINCT tanev FROM {table} WHERE tanev IS NOT NULL AND tanev <> ''"):
                years.add(row[0])
        except Exception:
            continue
    created = []
    now = _iso_now()
    for year in sorted(years):
        if not tanev_bounds(year)[0]:
            continue
        if year > current:
            # Jövőbeli tanév (pl. jövő tanévi határidős házi): még nincs állapota.
            continue
        kezdet, veg = _year_bounds_iso(year)
        if year < current:
            allapot, lezarva_at = "lezart", veg + "T23:59:59"
        else:
            allapot, lezarva_at = "nyitott", None
        cur = conn.execute(
            "INSERT OR IGNORE INTO tanevek"
            " (tanev, kezdet, veg, allapot, lezarva_at, forras, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 'szamitott', ?)",
            (year, kezdet, veg, allapot, lezarva_at, now))
        if cur.rowcount:
            created.append(year)
    # A választóban nem szereplő, nem nyitott állapotsorok törlése (pl. csak
    # üzenetekből származó évek) — így a DB és a felület konzisztens marad.
    try:
        if years:
            placeholders = ",".join("?" for _ in years)
            conn.execute(
                f"DELETE FROM tanevek WHERE allapot <> 'nyitott'"
                f" AND tanev NOT IN ({placeholders})", tuple(sorted(years)))
        else:
            conn.execute("DELETE FROM tanevek WHERE allapot <> 'nyitott'")
    except Exception:
        pass
    conn.commit()
    if created and log_fn:
        log_fn(f"  [Tanév-állapot] inicializálva: {', '.join(created)}")
    return created


def apply_tanev_uid(conn, diak_nev, tanev_uid, today_value=None, now=None,
                    log_fn=print) -> dict:
    """Egy diák `TanevUid`-jának rögzítése és a tanév-állapot váltása.

    - első látás: rögzítjük az UID-t, a dátumból számított tanévet (ha kell)
      megnyitjuk — **nem zárunk le semmit**;
    - változatlan UID: nincs teendő (a naptári évforduló önmagában nem ok);
    - megváltozott UID: ha a dátum szerinti tanév **újabb**, a nyitott tanévet
      technikailag lezárjuk, és megnyitjuk az újat; ha ugyanaz (pl. újra-
      regisztráció), csak az UID frissül; ha régebbi, csak naplózunk.
    """
    tanev_uid = str(tanev_uid or "").strip()
    result = {"diak_nev": diak_nev, "uid": tanev_uid, "elozo_uid": "",
              "valtozas": False, "lezart_tanev": "", "uj_tanev": "",
              "megjegyzes": ""}
    if not tanev_uid:
        result["megjegyzes"] = "nincs TanevUid (kihagyva)"
        return result

    ensure_tanev_state_schema(conn)
    current = current_tanev(today_value)
    stamp = _iso_now(now)

    row = conn.execute(
        "SELECT tanev_uid, tanev FROM tanulo_tanev_uid WHERE diak_nev = ?",
        (diak_nev,)).fetchone()
    elozo_uid = (row[0] or "") if row else ""
    result["elozo_uid"] = elozo_uid

    if not elozo_uid:
        # Első látás: csak rögzítés + a mai tanév megnyitása.
        conn.execute(
            "INSERT INTO tanulo_tanev_uid (diak_nev, tanev_uid, tanev, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(diak_nev) DO UPDATE SET tanev_uid = excluded.tanev_uid,"
            " tanev = excluded.tanev, last_seen = excluded.last_seen",
            (diak_nev, tanev_uid, current, stamp, stamp))
        conn.execute(
            "INSERT OR IGNORE INTO tanevek"
            " (tanev, kezdet, veg, allapot, lezarva_at, forras, updated_at)"
            " VALUES (?, ?, ?, 'nyitott', NULL, 'szamitott', ?)",
            (current, *_year_bounds_iso(current), stamp))
        conn.commit()
        result["megjegyzes"] = "első UID rögzítés"
        if log_fn:
            log_fn(f"  [Tanév-állapot] {diak_nev}: első TanevUid ({tanev_uid}), "
                   f"aktuális tanév: {current}")
        return result

    if elozo_uid == tanev_uid:
        # A KRÉTA szerint ez az UID a mérvadó. Ha a naptári seed (vagy egy korábbi
        # állapot) más tanévet nyitott, igazodjunk a KRÉTA-hoz — a UID az igazság.
        stored_tanev = (row[1] or "") if row else ""
        nyitott = nyitott_tanev(conn)
        if stored_tanev and nyitott and stored_tanev != nyitott and stored_tanev < nyitott:
            conn.execute(
                "UPDATE tanevek SET allapot = 'lezart', lezarva_at = ?,"
                " forras = 'kreta_uid', updated_at = ? WHERE tanev = ?",
                (stamp, stamp, nyitott))
            conn.execute(
                "INSERT INTO tanevek (tanev, kezdet, veg, allapot, lezarva_at, forras, updated_at)"
                " VALUES (?, ?, ?, 'nyitott', NULL, 'kreta_uid', ?)"
                " ON CONFLICT(tanev) DO UPDATE SET allapot = 'nyitott', lezarva_at = NULL,"
                " forras = 'kreta_uid', updated_at = excluded.updated_at",
                (stored_tanev, *_year_bounds_iso(stored_tanev), stamp))
            result["lezart_tanev"] = nyitott
            result["uj_tanev"] = stored_tanev
            result["megjegyzes"] = "a KRÉTA UID szerint a korábbi tanév az aktív"
            if log_fn:
                log_fn(f"  [Tanév-állapot] {diak_nev}: a KRÉTA UID szerint még a(z) "
                       f"{stored_tanev} tanév az aktív — LEZÁRVA: {nyitott}, "
                       f"MEGNYITVA: {stored_tanev}")
        conn.execute(
            "UPDATE tanulo_tanev_uid SET tanev = ?, last_seen = ? WHERE diak_nev = ?",
            (stored_tanev or current, stamp, diak_nev))
        conn.commit()
        return result

    # Az UID megváltozott.
    result["valtozas"] = True
    nyitott = nyitott_tanev(conn)
    conn.execute(
        "INSERT INTO tanulo_tanev_uid (diak_nev, tanev_uid, tanev, first_seen, last_seen)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(diak_nev) DO UPDATE SET tanev_uid = excluded.tanev_uid,"
        " tanev = excluded.tanev, last_seen = excluded.last_seen",
        (diak_nev, tanev_uid, current, stamp, stamp))

    if nyitott and current > nyitott:
        # Technikai zárás: nincs adatlekérés, csak állapot + időpont.
        conn.execute(
            "UPDATE tanevek SET allapot = 'lezart', lezarva_at = ?, forras = 'kreta_uid',"
            " updated_at = ? WHERE tanev = ?", (stamp, stamp, nyitott))
        conn.execute(
            "INSERT INTO tanevek (tanev, kezdet, veg, allapot, lezarva_at, forras, updated_at)"
            " VALUES (?, ?, ?, 'nyitott', NULL, 'kreta_uid', ?)"
            " ON CONFLICT(tanev) DO UPDATE SET allapot = 'nyitott', lezarva_at = NULL,"
            " forras = 'kreta_uid', updated_at = excluded.updated_at",
            (current, *_year_bounds_iso(current), stamp))
        result["lezart_tanev"] = nyitott
        result["uj_tanev"] = current
        if log_fn:
            log_fn(f"  [Tanév-állapot] {diak_nev}: TanevUid {elozo_uid} -> {tanev_uid}; "
                   f"LEZÁRVA: {nyitott}, MEGNYITVA: {current} (adatlekérés nélkül)")
    elif nyitott and current < nyitott:
        result["megjegyzes"] = f"az UID a korábbi tanévre mutat ({current} < {nyitott})"
        if log_fn:
            log_fn(f"  [Tanév-állapot] {diak_nev}: FIGYELEM — az új TanevUid a korábbi "
                   f"tanévre mutat ({current}); nem zárok le semmit.")
    else:
        result["uj_tanev"] = current
        result["megjegyzes"] = "UID változott, de a tanév ugyanaz"
        if log_fn:
            log_fn(f"  [Tanév-állapot] {diak_nev}: TanevUid {elozo_uid} -> {tanev_uid}, "
                   f"a tanév változatlan ({current})")
    conn.commit()
    return result
