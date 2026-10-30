# -*- coding: utf-8 -*-
"""
API-alapú adatkör-lekérők (D3–D7).

Csak **lekérés + normalizálás**: a DB-írást a `kreta_playwright.py` végzi a
meglévő `save_*` függvényekkel, így a séma egy helyen marad. A modul nem
importál Playwrightot, önállóan tesztelhető (fake klienssel).

A klienseket diákonként egyszer hozza létre és újrahasználja (`client_for`),
így egy futás alatt nem történik 8 külön belépés ugyanazzal a fiókkal. A token
30 percig él, a futás ennél rövidebb; lejáratkor a kliens magától frissít.
"""
from __future__ import annotations

from datetime import date, timedelta

from kreta_api import (
    KretaApiClient,
    lesson_index,
    normalize_justification,
    normalize_omission,
    pick_lesson,
)

# Az API-lekérés alapablaka: legalább egy tanév (a DB legkorábbi sora ezt tágíthatja).
DEFAULT_LOOKBACK_DAYS = 366

_CLIENTS: dict[tuple[str, str], KretaApiClient] = {}


def client_for(student: dict) -> KretaApiClient:
    """Diákonként újrahasznált API-kliens (a token nem vész el adatkörönként)."""
    key = (str(student.get("institute_code") or ""), str(student.get("username") or ""))
    client = _CLIENTS.get(key)
    if client is None:
        client = KretaApiClient(student)
        _CLIENTS[key] = client
    return client


def close_clients() -> None:
    """A futás végén a megnyitott munkamenetek lezárása."""
    for client in _CLIENTS.values():
        try:
            client.close()
        except Exception:  # noqa: BLE001 — lezárási hiba ne borítsa a futást
            pass
    _CLIENTS.clear()


def omission_window(earliest_stored: str | None, today: date | None = None,
                    lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> tuple[date, date]:
    """Az API-lekérés ablaka: legalább egy tanévnyi, de a DB legkorábbi soráig.

    A KRÉTA a szeleten belül a teljes listát adja; a mentés a szeleten kívüli
    sorokhoz nem nyúl, ezért a kezdő dátumot a DB legkorábbi hiányzásához
    igazítjuk — így nincs adatvesztés és nincs felesleges lekérés.
    """
    today = today or date.today()
    start = today - timedelta(days=lookback_days)
    text = str(earliest_stored or "")[:10]
    if text:
        try:
            stored = date.fromisoformat(text)
        except ValueError:
            stored = None
        if stored is not None and stored < start:
            start = stored
    return start, today


def apply_lesson_join(rows: list[dict], lessons: list[dict]) -> list[dict]:
    """A hiányzás témáját/tanárát az órarendből pótolja.

    A `/sajat/Mulasztasok` nem ad témát, ezért dátum + órasorszám + tantárgy
    alapján párosítunk (`pick_lesson` kezeli a párhuzamos csoportokat). Ha nincs
    órarendi elem (pl. táboros, tanórai célú hiányzás), a mező üres marad — a
    meglévő DB-értéket a hívó őrzi meg.
    """
    if not lessons:
        return rows
    index = lesson_index(lessons)
    for row in rows:
        if row.get("tema") and row.get("tanar"):
            continue
        lesson = pick_lesson(index, row)
        if not lesson:
            continue
        if not row.get("tema"):
            row["tema"] = lesson.get("tema", "")
        if not row.get("tanar"):
            row["tanar"] = lesson.get("tanar", "")
    return rows


def fetch_omissions(client, start: date, end: date) -> list[dict]:
    """Hiányzások/késések normalizált sorai, órarendi témával kiegészítve."""
    rows = [normalize_omission(item) for item in client.fetch_omissions(start, end)]
    if any(not row.get("tema") for row in rows):
        rows = apply_lesson_join(rows, client.fetch_lessons(start, end))
    return rows


def fetch_justifications(client) -> list[dict]:
    """Igazolások normalizált sorai (a KRÉTA ID a kulcs)."""
    return [normalize_justification(item) for item in client.fetch_justifications()]
