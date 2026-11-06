# -*- coding: utf-8 -*-
"""
Közös nézet-segédek (KRÉ-14 #94).

Blueprint-építő (`make_bp`) és a több végponton használt request-feldolgozók
(tanév, dátumtartomány, hónap, hiányzás-összesítő). Az `app.py`-ból kiemelve,
viselkedésváltozás nélkül. **Nem importálhatja az `app`-ot.**
"""
import re
import sqlite3
from datetime import datetime, timedelta

from flask import Blueprint, request

import kreta_tanev


def make_bp(name: str) -> Blueprint:
    """Prefix nélküli blueprint — az URL-ek bájtra azonosak maradnak (KRÉ-14)."""
    return Blueprint(name, __name__)


def _month_bounds(honap):
    """'ÉÉÉÉ-HH' -> (hónap első napja, utolsó napja) ISO alakban."""
    m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})\s*", honap or "")
    if not m:
        return None, None
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None, None
    first = f"{year:04d}-{month:02d}-01"
    next_month = f"{year + 1:04d}-01-01" if month == 12 else f"{year:04d}-{month + 1:02d}-01"
    last = (datetime.strptime(next_month, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    return first, last


def _is_keses(row):
    """Késés: van Perc érték, vagy a típus neve tartalmazza, hogy 'késés'."""
    if row.get("perc") is not None:
        return True
    return "késés" in str(row.get("mulasztas_tipus") or "").lower()


def hianyzas_osszesito(rows):
    """Havi/összesített mutatók a hiányzás-sorokból.

    A KRÉTA egy sora egy tanórát jelent (az 'Óra' oszlop a napon belüli
    órasorszám), ezért az órákat soronként 1-ként számoljuk. A tanórai célú
    jelzőt tároljuk, de a statisztikában nem különböztetjük meg.
    """
    o = {
        "hianyzas_db": 0,
        "igazolt_ora": 0,
        "igazolatlan_ora": 0,
        "keses_db": 0,
        "keses_perc": 0,
        "keses_igazolatlan_db": 0,
    }
    for r in rows:
        if _is_keses(r):
            o["keses_db"] += 1
            o["keses_perc"] += int(r.get("perc") or 0)
            if not int(r.get("igazolt") or 0):
                o["keses_igazolatlan_db"] += 1
            continue
        o["hianyzas_db"] += 1
        if int(r.get("igazolt") or 0):
            o["igazolt_ora"] += 1
        else:
            o["igazolatlan_ora"] += 1
    return o


def _date_range_from_request():
    """kezdo/zaro paraméter, vagy a honap=ÉÉÉÉ-HH paraméterből számolva."""
    kezdo = request.args.get("kezdo", "").strip()
    zaro = request.args.get("zaro", "").strip()
    if not kezdo and not zaro:
        kezdo, zaro = _month_bounds(request.args.get("honap", ""))
    return kezdo or None, zaro or None


def _tanev_from_request() -> str:
    """A `tanev` query param (Kaneo #40).

    Üres / ``all`` = **összes tanév** (visszafelé kompatibilis alap), ``current`` =
    a naptár szerinti aktuális tanév, egyébként a megadott érték (pl. ``2026/2027``).
    """
    raw = (request.args.get("tanev") or "").strip()
    if raw.lower() in ("", "all", "osszes", "összes"):
        return ""
    if raw.lower() == "current":
        return kreta_tanev.current_tanev()
    return raw


def _has_tanev_column(cursor, table: str) -> bool:
    try:
        return any(row[1] == "tanev" for row in cursor.execute(f"PRAGMA table_info({table})"))
    except sqlite3.Error:
        return False


def normalize_date(d_str):
    if not d_str or d_str == "-":
        return None
    clean = d_str.replace(". ", "-").replace(".", "-").strip()
    parts = [p for p in clean.split("-") if p]
    if len(parts) >= 3:
        try:
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        except ValueError:
            return None
    return None
