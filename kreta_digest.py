# -*- coding: utf-8 -*-
"""
Esti digest (KRÉ-8): a napi események gyermekenkénti összefoglalója.

A modul **tiszta logika**: adatgyűjtés a meglévő SQLite-ból (csak olvasás),
a szöveg összeállítása, és a „kell-e most küldeni" döntés. A tényleges
ntfy-küldést és az ütemezést az `app.py` végzi (30 mp-es tick).

Tartalom (a szülő kérése szerint): a **ma történt** események — jegyek
(súlyozással), házik, dolgozatok, feljegyzések, hiányzások, igazolások,
üzenetek —, valamint a **holnap esedékes** házik/dolgozatok. Órarend nincs
benne. Ha a nap eseménytelen, akkor is megy egy rövid üzenet.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta

# app_meta kulcsok
DIGEST_SETTINGS_META = "digest_settings"
DIGEST_SENT_PREFIX = "digest_sent:"          # digest_sent:<diák> -> 'YYYY-MM-DD' (napi jelölő)
DIGEST_LAST_AT_PREFIX = "digest_last_at:"    # digest_last_at:<diák> -> 'YYYY-MM-DDTHH:MM:SS'

DEFAULT_TIME = "19:30"
DEFAULT_SETTINGS = {
    "enabled": True,
    "time": DEFAULT_TIME,
    # A címzett a szülő saját eszköze; a gyermek neve a címben/első sorban.
    "include_names": True,
}

_HU_DATE_RE = re.compile(r"^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.")


# ── Dátumok ─────────────────────────────────────────────────────────────────
def parse_date(value) -> date | None:
    """'YYYY. MM. DD.' vagy ISO ('YYYY-MM-DD…') -> date; hibás -> None."""
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
        m = _HU_DATE_RE.match(text)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return None


def _hu_short(day: date | None) -> str:
    return f"{day.month:02d}. {day.day:02d}." if day else "-"


# ── Beállítások ─────────────────────────────────────────────────────────────
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{1,2})$")


def parse_settings(raw, base: dict | None = None) -> tuple[dict, list[str]]:
    """Beállítások normalizálása és validálása (API-hoz és config-hoz is).

    Visszaad: (normalizált dict, hibák listája). A hibák nem dobnak kivételt,
    hogy a config.json hibás értéke ne akassza meg az indulást.
    """
    out = dict(base or DEFAULT_SETTINGS)
    errors: list[str] = []
    if not isinstance(raw, dict):
        if raw not in (None, ""):
            errors.append("A beállítás nem objektum.")
        return out, errors

    if "ENABLED" in raw or "enabled" in raw:
        value = raw.get("ENABLED", raw.get("enabled"))
        out["enabled"] = bool(value)
    if "TIME" in raw or "time" in raw:
        value = str(raw.get("TIME", raw.get("time")) or "").strip()
        m = _TIME_RE.match(value)
        if m and 0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59:
            out["time"] = f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
        else:
            errors.append("Az időpont formátuma ÓÓ:PP legyen (pl. 19:30).")
    if "INCLUDE_NAMES" in raw or "include_names" in raw:
        value = raw.get("INCLUDE_NAMES", raw.get("include_names"))
        out["include_names"] = bool(value)
    return out, errors


def load_settings(config_block, meta_json: str | None = None) -> dict:
    """config.json DIGEST blokk + app_meta felülírás (a felület mentése)."""
    settings, _ = parse_settings(config_block or {})
    if meta_json:
        try:
            meta = json.loads(meta_json)
        except (TypeError, ValueError):
            meta = None
        if isinstance(meta, dict):
            settings, _ = parse_settings(meta, base=settings)
    return settings


def time_of_day(settings: dict) -> tuple[int, int]:
    """A beállított idő (óra, perc); hibás értéknél 19:30."""
    m = _TIME_RE.match(str(settings.get("time") or DEFAULT_TIME))
    if not m:
        return 19, 30
    return int(m.group(1)), int(m.group(2))


def should_send(settings: dict, last_sent: str | None, now: datetime) -> bool:
    """Küldjön-e most? Naponta egyszer, a beállított idő után (max. 23:00-ig)."""
    if not settings.get("enabled"):
        return False
    hour, minute = time_of_day(settings)
    if now.hour >= 23:
        return False
    if (now.hour, now.minute) < (hour, minute):
        return False
    return (last_sent or "") != now.date().isoformat()


# ── Adatgyűjtés ─────────────────────────────────────────────────────────────
def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def collect_day(conn: sqlite3.Connection, diak_nev: str, nap: date) -> dict:
    """Egy diák adott napi eseményei (a `collect_range` rövidítése)."""
    return collect_range(conn, diak_nev, nap, nap)


def collect_range(conn: sqlite3.Connection, diak_nev: str,
                  kezdo: date, vege: date) -> dict:
    """Egy diák eseményei a [kezdo, vege] napokon + a holnapi határidők.

    A manuális „az utolsó automata óta" összefoglaló több napot is átfoghat;
    az automatikus digesnél `kezdo == vege == ma`.
    """
    adat = {
        "jegyek": [], "hazi": [], "dolgozatok": [], "feljegyzesek": [],
        "hianyzasok": [], "igazolasok": [], "uzenetek": [],
        "holnapi_hataridok": [], "olvasatlan_db": 0,
        "kezdo": kezdo, "vege": vege,
    }
    holnap = vege + timedelta(days=1)
    conn.row_factory = sqlite3.Row

    def _in_range(value) -> bool:
        nap = parse_date(value)
        return nap is not None and kezdo <= nap <= vege

    try:
        rows = conn.execute(
            "SELECT * FROM esemenyek WHERE diak_nev = ?", (diak_nev,)
        ).fetchall()
    except sqlite3.Error:
        rows = []

    for row in rows:
        keys = row.keys()
        tipus = _text(row["esemeny_tipus"])
        bej = parse_date(row["bej_datum"])
        hatarido = parse_date(row["hatarido"])
        kesz = _int(row["kesz"]) if "kesz" in keys else 0

        if tipus == "Értékelés" and bej is not None and kezdo <= bej <= vege:
            adat["jegyek"].append({
                "tantargy": _text(row["tantargy"]),
                "ertek": _text(row["ertek"]),
                "szam_ertek": _int(row["szam_ertek"]) if "szam_ertek" in keys else 0,
                "suly": _int(row["suly_szazalek"]) if "suly_szazalek" in keys else 0,
                "mod": _text(row["mod"]),
                "tema": _text(row["tema"]),
                "tanar": _text(row["ertekelo"]),
            })
        elif tipus == "Házi feladat" and bej is not None and kezdo <= bej <= vege:
            adat["hazi"].append({
                "tantargy": _text(row["tantargy"]),
                "szoveg": _text(row["tartalom"]),
                "hatarido": hatarido,
                "kesz": kesz,
            })
        elif tipus == "Bejelentett számonkérés" and bej is not None and kezdo <= bej <= vege:
            adat["dolgozatok"].append({
                "tantargy": _text(row["tantargy"]),
                "mod": _text(row["mod"]),
                "tema": _text(row["tema"]),
                "hatarido": hatarido,
            })
        elif tipus == "Feljegyzés" and bej is not None and kezdo <= bej <= vege:
            adat["feljegyzesek"].append({
                "tipus": _text(row["tipus"]),
                "tartalom": _text(row["tartalom"]),
                "cim": _text(row["cim"]),
                "tanar": _text(row["ertekelo"]),
            })

        # Holnap esedékes házik / dolgozatok (a kész házi nem érdekes).
        if tipus == "Házi feladat" and hatarido == holnap and not kesz:
            adat["holnapi_hataridok"].append({
                "tipus": "házi", "tantargy": _text(row["tantargy"]),
                "szoveg": _text(row["tartalom"]), "hatarido": hatarido,
            })
        elif tipus == "Bejelentett számonkérés" and hatarido == holnap:
            adat["holnapi_hataridok"].append({
                "tipus": "dolgozat", "tantargy": _text(row["tantargy"]),
                "szoveg": _text(row["tema"]) or _text(row["mod"]),
                "hatarido": hatarido,
            })

    try:
        for row in conn.execute(
            "SELECT * FROM hianyzasok WHERE diak_nev = ?", (diak_nev,)
        ):
            if not _in_range(row["mulasztas_datum"]):
                continue
            adat["hianyzasok"].append({
                "ora": _int(row["ora_sorszam"]),
                "tantargy": _text(row["tantargy"]),
                "tipus": _text(row["mulasztas_tipus"]),
                "perc": _int(row["perc"]) if row["perc"] is not None else None,
                "igazolt": _int(row["igazolt"]),
                "igazolas_tipus": _text(row["igazolas_tipus"]),
                "datum": parse_date(row["mulasztas_datum"]),
            })
    except sqlite3.Error:
        pass

    try:
        for row in conn.execute(
            "SELECT * FROM igazolasok WHERE diak_nev = ?", (diak_nev,)
        ):
            if not _in_range(row["kezdete"]):
                continue
            adat["igazolasok"].append({
                "tipus": _text(row["igazolas_tipus"]),
                "kezdete": parse_date(row["kezdete"]),
                "vege": parse_date(row["vege"]),
                "megjegyzes": _text(row["megjegyzes"]),
            })
    except sqlite3.Error:
        pass

    try:
        rows = conn.execute(
            "SELECT felado, targy, idopont, olvasott FROM uzenetek WHERE diak_nev = ?",
            (diak_nev,),
        ).fetchall()
        for row in rows:
            if not _in_range(row["idopont"]):
                continue
            adat["uzenetek"].append({
                "felado": _text(row["felado"]),
                "targy": _text(row["targy"]),
                "olvasott": bool(row["olvasott"]) if "olvasott" in row.keys() else False,
                "idopont": parse_date(row["idopont"]),
            })
        adat["olvasatlan_db"] = int(conn.execute(
            "SELECT COUNT(*) FROM uzenetek WHERE diak_nev = ? "
            "AND COALESCE(olvasott, 0) = 0", (diak_nev,)
        ).fetchone()[0] or 0)
    except sqlite3.Error:
        pass

    adat["jegyek"].sort(key=lambda e: e["tantargy"].casefold())
    adat["hazi"].sort(key=lambda e: (e["hatarido"] or date.max, e["tantargy"].casefold()))
    adat["holnapi_hataridok"].sort(key=lambda e: (e["tipus"], e["tantargy"].casefold()))
    return adat


# ── Szövegépítés ────────────────────────────────────────────────────────────
def _rovid(szoveg, max_hossz: int = 90) -> str:
    text = " ".join(str(szoveg or "").split())
    if len(text) <= max_hossz:
        return text
    return text[: max_hossz - 1].rstrip() + "…"


def _jegy_sor(e: dict) -> str:
    resz = [e["tantargy"] or "?"]
    ertek = e["ertek"] or ("%d" % e["szam_ertek"] if e["szam_ertek"] else "")
    if ertek:
        resz.append(f"— {ertek}")
    if e["suly"]:
        resz.append(f"({e['suly']}%)")
    if e["mod"]:
        resz.append(f"· {e['mod']}")
    if e["tema"]:
        resz.append(f"· „{_rovid(e['tema'], 60)}”")
    if e["tanar"]:
        resz.append(f"· {e['tanar']}")
    return " ".join(resz)


def _hazi_sor(e: dict) -> str:
    sor = [e["tantargy"] or "?"]
    if e["szoveg"]:
        sor.append(f"— {_rovid(e['szoveg'])}")
    sor.append(f"(határidő: {_hu_short(e['hatarido'])})")
    if e.get("kesz"):
        sor.append("· kész")
    return " ".join(sor)


def _dolgozat_sor(e: dict) -> str:
    sor = [e["tantargy"] or "?"]
    if e["mod"]:
        sor.append(f"— {e['mod']}")
    if e["tema"]:
        sor.append(f"· „{_rovid(e['tema'], 60)}”")
    sor.append(f"(dátum: {_hu_short(e['hatarido'])})")
    return " ".join(sor)


def _feljegyzes_sor(e: dict) -> str:
    sor = [e["tipus"] or "Feljegyzés"]
    if e["cim"]:
        sor.append(f"— {_rovid(e['cim'], 60)}")
    if e["tartalom"]:
        sor.append(f"· {_rovid(e['tartalom'])}")
    if e["tanar"]:
        sor.append(f"({e['tanar']})")
    return " ".join(sor)


def _hianyzas_sor(e: dict) -> str:
    sor = []
    if e["ora"]:
        sor.append(f"{e['ora']}. óra")
    sor.append(f"· {e['tantargy'] or '?'}")
    if e["perc"] is not None:
        sor.append(f"— késés {e['perc']} perc")
    else:
        sor.append("— hiányzás")
    sor.append("igazolt" if e["igazolt"] else "IGAZOLATLAN")
    if e["igazolas_tipus"]:
        sor.append(f"({e['igazolas_tipus']})")
    return " ".join(sor)


def _igazolas_sor(e: dict) -> str:
    sor = [e["tipus"] or "Igazolás"]
    if e["kezdete"] or e["vege"]:
        sor[-1] = sor[-1] + f": {_hu_short(e['kezdete'])} – {_hu_short(e['vege'])}"
    if e["megjegyzes"]:
        sor.append(f"· {_rovid(e['megjegyzes'], 60)}")
    return " ".join(sor)


def _holnap_sor(e: dict) -> str:
    nev = "házi" if e["tipus"] == "házi" else "dolgozat"
    sor = [f"{e['tantargy'] or '?'} — {nev}"]
    if e["szoveg"]:
        sor.append(f"· {_rovid(e['szoveg'], 60)}")
    sor.append(f"({_hu_short(e['hatarido'])})")
    return " ".join(sor)


def _szekcio(cim: str, sorok: list[str]) -> list[str]:
    if not sorok:
        return []
    return ["", f"{cim} ({len(sorok)})"] + [f"• {s}" for s in sorok]


def build_message(diak_nev: str, nap: date, adat: dict,
                  include_names: bool = True, kezdo: date | None = None) -> tuple[str, str]:
    """A digest (cím, törzs) szövege. Üres napon is ad rövid üzenetet.

    `kezdo` megadásával több napot átfogó (manuális, „az utolsó automata óta")
    összefoglaló készül; a címben és az első sorban látszik az időszak.
    """
    kezdo = kezdo or nap
    nev = f" – {diak_nev}" if include_names and diak_nev else ""
    if kezdo == nap:
        cim = f"SuliHub{nev} – {nap.year}. {nap.month:02d}. {nap.day:02d}."
    else:
        cim = (f"SuliHub{nev} – {kezdo.year}. {kezdo.month:02d}. {kezdo.day:02d}. – "
               f"{nap.month:02d}. {nap.day:02d}.")

    sorok: list[str] = []
    sorok += _szekcio("📊 Jegyek", [_jegy_sor(e) for e in adat.get("jegyek") or []])
    sorok += _szekcio("📚 Házi feladat", [_hazi_sor(e) for e in adat.get("hazi") or []])
    sorok += _szekcio("📝 Dolgozatok", [_dolgozat_sor(e) for e in adat.get("dolgozatok") or []])
    sorok += _szekcio("📌 Feljegyzés", [_feljegyzes_sor(e) for e in adat.get("feljegyzesek") or []])
    sorok += _szekcio("🚫 Hiányzás", [_hianyzas_sor(e) for e in adat.get("hianyzasok") or []])
    sorok += _szekcio("📄 Igazolás", [_igazolas_sor(e) for e in adat.get("igazolasok") or []])
    sorok += _szekcio("✉️ Üzenetek", [
        f"{e['felado'] or '?'}: {e['targy'] or '(nincs tárgy)'}"
        for e in adat.get("uzenetek") or []
    ])
    sorok += _szekcio("📅 Holnap esedékes",
                      [_holnap_sor(e) for e in adat.get("holnapi_hataridok") or []])

    olvasatlan = int(adat.get("olvasatlan_db") or 0)
    if olvasatlan and not adat.get("uzenetek"):
        sorok += ["", f"✉️ {olvasatlan} olvasatlan üzenet a postaládában."]

    if not sorok:
        if kezdo == nap:
            torzs = "Ma nem történt esemény, holnapra nincs esedékes feladat."
        else:
            torzs = "Az utolsó automatikus összefoglaló óta nem történt esemény."
    else:
        if kezdo != nap:
            sorok.insert(0, f"Időszak: {_hu_short(kezdo)} – {_hu_short(nap)}")
        torzs = "\n".join(sorok).strip()

    return cim, torzs
