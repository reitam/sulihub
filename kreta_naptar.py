# -*- coding: utf-8 -*-
"""
Naptárbejegyzés generálás — Kaneo #47.

A házi feladatok / számonkérések (események) és az üzenetek alapján
- Google Naptár „esemény létrehozása” linket (előre kitöltött űrlap), és
- szabványos `.ics` fájlt (Apple/Outlook/Google import) állít elő.

A modul Flask-független, így közvetlenül tesztelhető. A konfiguráció a
`config.json` `CALENDAR` blokkjából jön (a `.env`-ből nem kötelező):

    "CALENDAR": {
      "TIMEZONE": "Europe/Budapest",
      "REMINDER_MINUTES": 30,
      "MESSAGE_DURATION_MINUTES": 30
    }

Ha a `TIMEZONE` érvénytelen, az `.ics` UTC-ben készül (a Google-link `ctz`
paramétere ilyenkor kimarad).
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote, urlencode

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - nagyon régi Python
    ZoneInfo = None

DEFAULTS = {
    "TIMEZONE": "Europe/Budapest",
    "REMINDER_MINUTES": 30,
    "MESSAGE_DURATION_MINUTES": 30,
}


def calendar_config(config: dict | None = None) -> dict:
    """A CALENDAR blokk alapértékekkel kiegészítve, ellenőrzött típusokkal."""
    block = (config or {}).get("CALENDAR") or {}
    result = dict(DEFAULTS)
    if isinstance(block, dict):
        for key in DEFAULTS:
            if key in block and block[key] not in (None, ""):
                result[key] = block[key]
    try:
        result["REMINDER_MINUTES"] = max(0, min(240, int(result["REMINDER_MINUTES"])))
    except (TypeError, ValueError):
        result["REMINDER_MINUTES"] = DEFAULTS["REMINDER_MINUTES"]
    try:
        result["MESSAGE_DURATION_MINUTES"] = max(5, min(240, int(result["MESSAGE_DURATION_MINUTES"])))
    except (TypeError, ValueError):
        result["MESSAGE_DURATION_MINUTES"] = DEFAULTS["MESSAGE_DURATION_MINUTES"]
    result["TIMEZONE"] = str(result["TIMEZONE"]).strip() or DEFAULTS["TIMEZONE"]
    return result


def parse_datetime(value) -> datetime | None:
    """`2026. 05. 11. 15:48`, `2026-05-11 15:48`, `2026-05-11` → datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    match = re.match(
        r"^\s*(\d{4})[.\-]\s*(\d{1,2})[.\-]\s*(\d{1,2})\.?"
        r"(?:[ T]+(\d{1,2}):(\d{2}))?",
        text,
    )
    if not match:
        return None
    try:
        return datetime(
            int(match.group(1)), int(match.group(2)), int(match.group(3)),
            int(match.group(4) or 0), int(match.group(5) or 0),
        )
    except ValueError:
        return None


def _zone(cfg: dict):
    if not ZoneInfo:
        return None
    try:
        return ZoneInfo(cfg.get("TIMEZONE") or DEFAULTS["TIMEZONE"])
    except Exception:
        return None


def _event(kind: str, item_id, title: str, start: datetime, cfg: dict,
           all_day: bool = False, description: str = "", location: str = "") -> dict:
    if all_day:
        start = datetime.combine(start.date(), time.min)
        end = start + timedelta(days=1)
    else:
        end = start + timedelta(minutes=int(cfg["MESSAGE_DURATION_MINUTES"]))
    return {
        "kind": kind,
        "id": item_id,
        "title": title.strip(),
        "start": start,
        "end": end,
        "all_day": all_day,
        "description": (description or "").strip(),
        "location": (location or "").strip(),
    }


def event_from_esemeny(row, cfg: dict) -> dict | None:
    """`esemenyek` sor → naptáresemény (határidő, egész napos)."""
    start = parse_datetime(row["hatarido"])
    if not start:
        return None
    diak = (row["diak_nev"] or "").strip()
    tantargy = (row["tantargy"] or "").strip() or "Tantárgy nélkül"
    tipus = (row["esemeny_tipus"] or "").strip()
    if tipus == "Bejelentett számonkérés":
        mod = (row["mod"] or "").strip()
        label = f"Számonkérés ({mod})" if mod and mod != "-" else "Számonkérés"
    else:
        label = tipus or "Esemény"
    title = f"{diak}: {tantargy} – {label}" if diak else f"{tantargy} – {label}"

    details = []
    if row["tema"] and row["tema"] != "-":
        details.append(f"Téma: {row['tema']}")
    if row["cim"] and row["cim"] != "-":
        details.append(f"Cím: {row['cim']}")
    if row["tartalom"] and row["tartalom"] != "-":
        details.append(str(row["tartalom"]))
    if row["ertekelo"] and row["ertekelo"] != "-":
        details.append(f"Tanár: {row['ertekelo']}")
    return _event(
        "esemeny", row["id"], title, start, cfg, all_day=True,
        description="\n".join(details),
    )


def event_from_uzenet(row, cfg: dict) -> dict | None:
    """`uzenetek` sor → naptáresemény (az üzenet időpontjában)."""
    start = parse_datetime(row["idopont"])
    if not start:
        return None
    diak = (row["diak_nev"] or "").strip()
    targy = (row["targy"] or "").strip() or "Üzenet"
    title = f"{diak}: {targy}" if diak else targy
    details = []
    if row["felado"]:
        details.append(f"Feladó: {row['felado']}")
    if row["szoveg"]:
        szoveg = str(row["szoveg"]).strip()
        details.append(szoveg[:800] + ("…" if len(szoveg) > 800 else ""))
    return _event(
        "uzenet", row["id"], title, start, cfg, all_day=False,
        description="\n".join(details),
    )


def _gdate(dt: datetime, all_day: bool) -> str:
    return dt.strftime("%Y%m%d") if all_day else dt.strftime("%Y%m%dT%H%M%S")


def google_calendar_url(event: dict, cfg: dict) -> str:
    """Előre kitöltött Google Naptár „esemény létrehozása” link."""
    params = {
        "action": "TEMPLATE",
        "text": event["title"],
        "dates": f"{_gdate(event['start'], event['all_day'])}/{_gdate(event['end'], event['all_day'])}",
    }
    if event["description"]:
        params["details"] = event["description"]
    if event["location"]:
        params["location"] = event["location"]
    if not event["all_day"] and cfg.get("TIMEZONE"):
        params["ctz"] = cfg["TIMEZONE"]
    return "https://calendar.google.com/calendar/render?" + urlencode(params, quote_via=quote)


def _ics_escape(text: str) -> str:
    return (
        str(text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _ics_fold(line: str, limit: int = 73) -> str:
    """Egyszerű sortörés az RFC 5545 75 oktetes korlátjához közel."""
    if len(line) <= limit:
        return line
    parts = [line[:limit]]
    rest = line[limit:]
    while rest:
        parts.append(" " + rest[:limit - 1])
        rest = rest[limit - 1:]
    return "\r\n".join(parts)


def _ics_dt(event: dict, cfg: dict) -> tuple[str, str]:
    """(DTSTART sor, DTEND sor) — egész napos VALUE=DATE, egyébként UTC."""
    if event["all_day"]:
        return (
            "DTSTART;VALUE=DATE:" + event["start"].strftime("%Y%m%d"),
            "DTEND;VALUE=DATE:" + event["end"].strftime("%Y%m%d"),
        )
    zone = _zone(cfg)
    start = event["start"].replace(tzinfo=zone) if zone else event["start"].replace(tzinfo=timezone.utc)
    end = event["end"].replace(tzinfo=zone) if zone else event["end"].replace(tzinfo=timezone.utc)
    return (
        "DTSTART:" + start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "DTEND:" + end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    )


def _vevent_lines(event: dict, cfg: dict, now: datetime) -> list[str]:
    dtstart, dtend = _ics_dt(event, cfg)
    lines = [
        "BEGIN:VEVENT",
        f"UID:kreta-{event['kind']}-{event['id']}@kreta.local",
        "DTSTAMP:" + now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        dtstart,
        dtend,
        "SUMMARY:" + _ics_escape(event["title"]),
    ]
    if event["description"]:
        lines.append("DESCRIPTION:" + _ics_escape(event["description"]))
    if event["location"]:
        lines.append("LOCATION:" + _ics_escape(event["location"]))
    reminder = int(cfg.get("REMINDER_MINUTES") or 0)
    if reminder > 0:
        lines.extend([
            "BEGIN:VALARM",
            f"TRIGGER:-PT{reminder}M",
            "ACTION:DISPLAY",
            "DESCRIPTION:" + _ics_escape(event["title"]),
            "END:VALARM",
        ])
    lines.append("END:VEVENT")
    return lines


def _ics_wrap(event_lines: list[list[str]]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Kreta Adatbazis Attekinto//HU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for event in event_lines:
        lines.extend(event)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"


def ics_content(event: dict, cfg: dict, now: datetime | None = None) -> str:
    """Egy esemény `.ics` tartalma (CRLF, RFC 5545)."""
    now = now or datetime.now(timezone.utc)
    return _ics_wrap([_vevent_lines(event, cfg, now)])


def ics_orarend(rows, start_date, end_date, cfg: dict,
                diak_prefix: bool = False, now: datetime | None = None) -> str:
    """Heti ismétlődő órarendi sorokból `.ics` (Kaneo #73).

    Egy VEVENT = egy heti minta (diák + tantárgy + nap + kezdés + időtartam),
    `RRULE:FREQ=WEEKLY` szabállyal a kért időszakra. Az azonos minta **többször
    is szerepelhet a táblában** (szinkron az aktuális és a következő hetet is
    lekéri) — ezeket egy eseményre vonjuk össze, különben minden kétszer kerülne
    az exportba. Az egész napos (dátum nélküli) sorokat kihagyjuk.
    """
    now = now or datetime.now(timezone.utc)
    mintak: dict[tuple, dict] = {}
    for row in rows:
        kezdo = parse_datetime(row["kezdo_idopont"])
        if not kezdo or "T" not in str(row["kezdo_idopont"] or ""):
            continue
        zaro = parse_datetime(row["zaro_idopont"]) if row["zaro_idopont"] else None
        duration = (zaro - kezdo) if zaro and zaro > kezdo else timedelta(minutes=45)
        key = (str(row["diak_nev"] or "").strip(), str(row["tantargy"] or "").strip(),
               kezdo.weekday(), kezdo.strftime("%H:%M"), duration.total_seconds())
        korabbi = mintak.get(key)
        if korabbi is None or kezdo < korabbi["kezdo"]:
            mintak[key] = {"row": row, "kezdo": kezdo, "duration": duration}

    event_lines = []
    for entry in mintak.values():
        row, kezdo, duration = entry["row"], entry["kezdo"], entry["duration"]
        first = start_date + timedelta(days=(kezdo.weekday() - start_date.weekday()) % 7)
        if first > end_date:
            continue
        tantargy = (row["tantargy"] or "Tanóra").strip()
        diak = (row["diak_nev"] or "").strip()
        title = f"[{diak}] {tantargy}" if diak_prefix and diak else tantargy
        event = _event(
            "orarend", f"{row['id']}-{first.isoformat()}", title,
            datetime.combine(first, kezdo.time()), cfg, all_day=False,
            description=(row["tanar"] or ""), location=(row["terem"] or ""),
        )
        event["end"] = event["start"] + duration
        lines = _vevent_lines(event, cfg, now)
        lines.insert(-1, "RRULE:FREQ=WEEKLY;UNTIL="
                           + end_date.strftime("%Y%m%d") + "T235959Z")
        event_lines.append(lines)
    event_lines.sort(key=lambda lines: next(
        (line for line in lines if line.startswith("DTSTART:")), ""))
    return _ics_wrap(event_lines)


def safe_filename(event: dict) -> str:
    """Böngészőbarát fájlnév (ASCII, az esemény azonosítójával)."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", str(event["title"]))[:60].strip("_")
    return f"kreta_{event['kind']}_{event['id']}_{base or 'esemeny'}.ics"
