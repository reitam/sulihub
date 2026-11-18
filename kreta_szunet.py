# -*- coding: utf-8 -*-
"""Szinkron-szünetek (Kaneo #145): config-alapú intervallumok, tiszta logika.

A `config.json` `SYNC_SZUNET` listája, pl.:

    "SYNC_SZUNET": [
      {"nev": "Őszi szünet", "kezdo": "2026-10-26", "vege": "2026-10-30"},
      {"nev": "Téli szünet", "kezdo": "2026-12-21", "vege": "2027-01-02",
       "napi_sync": true, "napi_ido": "10:00"}
    ]

A modul nem nyúl az adatbázishoz és nem indít szinkront: csak a parse-olást,
az aktív intervallum kiválasztását és a napi szinkron esedékességét adja.
A tényleges ütemezést és a felületi sávot az `app.py` végzi.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time

DEFAULT_DAILY_TIME = "10:00"

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{1,2})$")
_DATE_RE = re.compile(r"^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.")


def parse_date(value) -> date | None:
    """'YYYY-MM-DD' vagy 'YYYY. MM. DD.' -> date; hibás -> None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) >= 10 and text[4] == "-":
            return date.fromisoformat(text[:10])
        match = _DATE_RE.match(text)
        if match:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return None


def _normalize_time(value) -> str:
    match = _TIME_RE.match(str(value or "").strip())
    if match and 0 <= int(match.group(1)) <= 23 and 0 <= int(match.group(2)) <= 59:
        return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"
    return DEFAULT_DAILY_TIME


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "on", "igen")


def parse_interval(item) -> dict | None:
    """Egy config-elem normalizálása; érvénytelen -> None."""
    if not isinstance(item, dict):
        return None
    kezdo = parse_date(item.get("kezdo") or item.get("kezdo_datum") or item.get("from"))
    vege = parse_date(item.get("vege") or item.get("vege_datum") or item.get("to"))
    if kezdo is None or vege is None:
        return None
    if vege < kezdo:
        kezdo, vege = vege, kezdo
    return {
        "nev": str(item.get("nev") or item.get("name") or "Szünet").strip() or "Szünet",
        "kezdo": kezdo,
        "vege": vege,
        "napi_sync": _bool(item.get("napi_sync", item.get("napi", False))),
        "napi_ido": _normalize_time(item.get("napi_ido") or item.get("napi_time")),
    }


def parse_intervals(raw) -> list[dict]:
    """A config `SYNC_SZUNET` listája -> normalizált, kezdő dátum szerint rendezett lista."""
    if not isinstance(raw, list):
        return []
    out = [parsed for parsed in (parse_interval(item) for item in raw) if parsed]
    out.sort(key=lambda item: (item["kezdo"], item["vege"]))
    return out


def interval_active_on(interval: dict, nap: date) -> bool:
    return interval["kezdo"] <= nap <= interval["vege"]


def active_interval(intervals: list[dict], nap: date) -> dict | None:
    """Az adott napon aktív szünet (ha több átfed, a legkorábban kezdődő)."""
    for interval in intervals:
        if interval_active_on(interval, nap):
            return interval
    return None


def next_interval(intervals: list[dict], nap: date) -> dict | None:
    """A következő, még nem elkezdődött szünet."""
    for interval in intervals:
        if interval["kezdo"] > nap:
            return interval
    return None


def interval_days(interval: dict) -> int:
    return (interval["vege"] - interval["kezdo"]).days + 1


def daily_time(interval: dict) -> time:
    hour, minute = interval.get("napi_ido", DEFAULT_DAILY_TIME).split(":")
    return time(int(hour), int(minute))


def daily_sync_due(interval: dict, now: datetime, last_daily_iso: str = "") -> bool:
    """A szüneti napi szinkron esedékes-e most (egyszer/nap, a beállított idő után)."""
    if not interval.get("napi_sync"):
        return False
    if not interval_active_on(interval, now.date()):
        return False
    if (last_daily_iso or "") == now.date().isoformat():
        return False
    return now.time() >= daily_time(interval) and now.hour < 23


def _public(interval: dict | None) -> dict | None:
    if not interval:
        return None
    return {
        "nev": interval["nev"],
        "kezdo": interval["kezdo"].isoformat(),
        "vege": interval["vege"].isoformat(),
        "napok": interval_days(interval),
        "napi_sync": bool(interval["napi_sync"]),
        "napi_ido": interval["napi_ido"],
    }


def status(intervals: list[dict], now: datetime) -> dict:
    """A felületi sávhoz: aktív szünet + a következő (ha van)."""
    active = active_interval(intervals, now.date())
    return {
        "active": _public(active),
        "next": _public(next_interval(intervals, now.date())),
    }
