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

import re
from datetime import date, timedelta

import kreta_tanev

from kreta_api import (
    KretaApiClient,
    lesson_index,
    message_body_from_detail,
    normalize_consultations,
    normalize_evaluation,
    normalize_homework,
    normalize_justification,
    normalize_lesson,
    normalize_message,
    normalize_note,
    normalize_omission,
    normalize_test,
    pick_lesson,
)

_DATE_HU_RE = re.compile(r"^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.")

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


def parse_stored_date(value) -> date | None:
    """A DB-ben tárolt dátum ('YYYY. MM. DD.' vagy ISO) -> date; hibás -> None."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) >= 10 and text[4] == "-":
            return date.fromisoformat(text[:10])
        match = _DATE_HU_RE.match(text)
        if match:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return None


# A KRÉTA API a `datumTol`–`datumIg` ablakon belül adja vissza a sorokat, és a
# dátum a *esemény* napja. A házi feladat és a bejelentett számonkérés viszont
# **jövőbeli** határidőt hordoz, ezért ezeknél előre is kell kérni — enélkül a
# következő hetek dolgozatai/házijai soha nem jönnének le API-ból.
FUTURE_LOOKAHEAD_DAYS = 90
FUTURE_DATED_EVENT_TYPES = ("Házi feladat", "Bejelentett számonkérés")


def api_window(earliest_stored: str | None, today: date | None = None,
               lookback_days: int = DEFAULT_LOOKBACK_DAYS,
               lookahead_days: int = 0) -> tuple[date, date]:
    """Az API-lekérés ablaka: legalább egy tanévnyi, de a DB legkorábbi soráig.

    A KRÉTA a szeleten belül a teljes listát adja; a mentés a szeleten kívüli
    sorokhoz nem nyúl, ezért a kezdő dátumot a DB legkorábbi sorához igazítjuk —
    így nincs adatvesztés és nincs felesleges lekérés.

    `lookahead_days`: mennyivel nyúljon az ablak a jövőbe (jövőbeli határidős
    eseményekhez, pl. házi feladat és bejelentett számonkérés).
    """
    today = today or date.today()
    start = today - timedelta(days=lookback_days)
    stored = parse_stored_date(earliest_stored)
    if stored is not None and stored < start:
        start = stored
    return start, today + timedelta(days=max(0, lookahead_days))


def tanev_api_window(today: date | None = None,
                     lookahead_days: int = 0) -> tuple[date, date]:
    """Az API-lekérés ablaka: **az aktuális tanév kezdetétől** a mai napig.

    Kaneo #40: a teljes cserék törlése csak akkor engedett, ha az ablak lefedi a
    tanévet — ezért nem a DB legkorábbi sorához igazítunk (az több tanév után
    a teljes történetet kérné le), hanem a tanév elejéhez. A korábbi tanévek
    adatait a szinkron nem érinti.

    `lookahead_days`: mennyivel nyúljon az ablak a jövőbe (jövőbeli határidős
    eseményekhez, pl. házi feladat és bejelentett számonkérés).
    """
    today = today or kreta_tanev.today()
    start, _ = kreta_tanev.tanev_bounds(kreta_tanev.current_tanev(today))
    if start is None:  # elvileg nem fordulhat elő; biztonsági tartalék
        start = today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    return start, today + timedelta(days=max(0, lookahead_days))


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


def fetch_evaluations(client, start: date, end: date) -> list[dict]:
    """Jegyek/értékelések normalizált sorai (a webes oszlopok jelentésével).

    A `bej_datum` a rögzítés napja (helyi idő), így egyezik a webes „Bej. dátum”
    oszloppal. A Magatartás és a Szorgalom az API-ban két külön értékelés
    (0 számértékkel), ezért két sorban tárolódik — az átlagot nem befolyásolja.
    """
    return [normalize_evaluation(item) for item in client.fetch_evaluations(start, end)]


def fetch_homeworks(client, start: date, end: date) -> list[dict]:
    """Házi feladatok: `bej_datum` = rögzítés napja, `hatarido` = határidő (helyi).

    A szöveg HTML-mentes; az API a teljes leírást adja (a webes grid néha
    csonkol, ezért ott külön ablakban kell kinyerni).
    """
    return [normalize_homework(item) for item in client.fetch_homeworks(start, end)]


def fetch_announced_tests(client, start: date, end: date) -> list[dict]:
    """Bejelentett számonkérések (dátumok helyi időben)."""
    return [normalize_test(item) for item in client.fetch_announced_tests(start, end)]


def week_window(today: date | None = None) -> tuple[date, date]:
    """Az aktuális hét + a következő 3 hét: hétfő .. vasárnap (28 nap, helyi idő)."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=27)


def fetch_notes(client, start: date, end: date) -> list[dict]:
    """Feljegyzések normalizált sorai (HTML-mentes tartalom)."""
    return [normalize_note(item) for item in client.fetch_notes(start, end)]


def fetch_lessons(client, start: date, end: date) -> list[dict]:
    """Órarendi elemek az `orarend` tábla sorformátumában (helyi idő)."""
    return [normalize_lesson(item) for item in client.fetch_lessons(start, end)]


def fetch_consultations(client, start: date, end: date) -> list[dict]:
    """Fogadóórák az `orarend` tábla sorformátumában (a webes naptárral egyezően)."""
    return normalize_consultations(client.fetch_consultations(start, end))


def fetch_messages(client) -> list[dict]:
    """Beérkezett üzenetek normalizált sorai.

    **Figyelem:** a lista-válasz `szoveg` mezője előnézet lehet (rövid, a
    sortörések nélkül). A teljes törzsért a `fetch_message_body()` hívható meg
    üzenetenként — csak az új soroknál, hogy ne termeljen felesleges forgalmat.

    A csatolmányok a `csatolmanyok` mezőben `{azonosito, fajlNev}` alakban
    jönnek; a fájl tartalmát a `fetch_attachment` hozza.
    """
    return [normalize_message(item) for item in client.fetch_messages()]


def fetch_message_body(client, mailbox_id) -> str:
    """A teljes üizenszöveg a részletes végpontból; üres string, ha nem elérhető.

    A hiba nem dobás: az üzenet így is elmentődik a lista-elemből származó
    (esetleg rövidke) szöveggel.
    """
    if not mailbox_id:
        return ""
    try:
        return message_body_from_detail(client.fetch_message_detail(mailbox_id))
    except Exception:  # noqa: BLE001 — a részletes válasz hibája nem törölheti az üzenetet
        return ""


def fetch_attachment(client, attachment_id) -> tuple[bytes, str]:
    """Csatolmány tartalma az API-ból: `(bytes, content_type)`, böngésző nélkül.

    A lánc: eAdmin `dokumentumok/uzenetek/{id}` → 302 → `files.e-kreta.hu`
    nonce URL. A kliens kezeli a tokenfrissítést és a méretkorlátot.
    """
    return client.download_attachment(attachment_id)
