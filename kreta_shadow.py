# -*- coding: utf-8 -*-
"""
Árnyék (shadow) összehasonlítás: API-s DB vs. Playwrighttal frissített DB-másolat.

A `SYNC_SHADOW` bekapcsolásakor az `api_first` futás után a Playwright is lefut
egy **másolt** adatbázison, majd ez a modul összeveti a kettőt. A valódi DB-hez
csak az API ír, így nincs dupla írás és dupla értesítés; az eltérések a
`sync.log`-ba kerülnek.

Az összehasonlítás a POC logikáját követi: táblánként kulcs + mezők.
"""
from __future__ import annotations

import sqlite3

# tábla -> (mezők, kulcsfüggvény)
_TABLES: dict[str, tuple[tuple[str, ...], callable]] = {
    "esemenyek": (
        ("esemeny_tipus", "tantargy", "bej_datum", "hatarido", "ertek", "szam_ertek", "tema", "cim"),
        lambda row: (row["esemeny_tipus"], row["tantargy"], row["bej_datum"],
                     row["hatarido"], row["ertek"], row["cim"]),
    ),
    "hianyzasok": (
        ("mulasztas_datum", "ora_sorszam", "tantargy", "mulasztas_tipus", "perc", "tema",
         "tanar", "igazolt", "tanorai_celu"),
        lambda row: (row["mulasztas_datum"], row["ora_sorszam"]),
    ),
    "igazolasok": (
        ("kreta_id", "kezdete", "vege", "igazolas_tipus", "megjegyzes"),
        lambda row: (row["kreta_id"] or (row["kezdete"], row["vege"], row["igazolas_tipus"])),
    ),
    "orarend": (
        ("kezdo_idopont", "zaro_idopont", "nap", "tantargy", "tanar", "terem"),
        lambda row: (row["kezdo_idopont"], row["tantargy"]),
    ),
    "uzenetek": (
        ("felado", "targy", "idopont", "szoveg", "csatolmany_nev"),
        lambda row: (row["felado"], row["targy"], row["idopont"]),
    ),
}


def _load(path: str, table: str, columns: tuple[str, ...], diak_nev: str | None) -> list[sqlite3.Row]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        query = f"SELECT {', '.join(columns)} FROM {table}"
        params: tuple = ()
        if diak_nev:
            query += " WHERE diak_nev = ?"
            params = (diak_nev,)
        return list(conn.execute(query, params))
    finally:
        conn.close()


def _text(value) -> str:
    return "" if value is None else str(value)


def compare_databases(primary_db: str, shadow_db: str, diak_nev: str | None = None,
                      sample: int = 5) -> dict:
    """A két adatbázis összevetése táblánként (kulcs + mezők).

    `primary_db`: az API-val frissített valódi DB; `shadow_db`: a Playwrighttal
    frissített másolat. Visszaad egy kompakt riportot; a mező-eltéréseknél csak
    az első `sample` kulcsot sorolja fel (a napló ne hízzon meg).
    """
    report: dict = {"is_match": True, "total_diffs": 0, "tables": {}}
    for table, (columns, keyfunc) in _TABLES.items():
        try:
            primary_rows = _load(primary_db, table, columns, diak_nev)
            shadow_rows = _load(shadow_db, table, columns, diak_nev)
        except sqlite3.Error as exc:
            report["tables"][table] = {"error": str(exc)}
            report["is_match"] = False
            continue

        primary = {keyfunc(row): tuple(_text(row[c]) for c in columns) for row in primary_rows}
        shadow = {keyfunc(row): tuple(_text(row[c]) for c in columns) for row in shadow_rows}

        only_primary = sorted(set(primary) - set(shadow), key=str)
        only_shadow = sorted(set(shadow) - set(primary), key=str)
        field_diffs = sorted(
            (key for key in set(primary) & set(shadow) if primary[key] != shadow[key]), key=str
        )
        diffs = len(only_primary) + len(only_shadow) + len(field_diffs)

        report["tables"][table] = {
            "primary": len(primary),
            "shadow": len(shadow),
            "only_primary": [list(map(str, key)) for key in only_primary[:sample]],
            "only_shadow": [list(map(str, key)) for key in only_shadow[:sample]],
            "field_diffs": [list(map(str, key)) for key in field_diffs[:sample]],
            "diffs": diffs,
        }
        if diffs:
            report["is_match"] = False
            report["total_diffs"] += diffs
    return report


def format_report(report: dict) -> list[str]:
    """A riport naplózható sorai (táblánként egy sor + az első eltérések)."""
    lines = []
    for table, data in report.get("tables", {}).items():
        if "error" in data:
            lines.append(f"  [ÁRNYÉK] {table}: hiba ({data['error']})")
            continue
        status = "egyezik" if not data["diffs"] else f"ELTÉRÉS: {data['diffs']}"
        lines.append(
            f"  [ÁRNYÉK] {table}: API {data['primary']} / Playwright {data['shadow']} — {status}"
        )
        if data["only_primary"]:
            lines.append(f"      csak API: {data['only_primary']}")
        if data["only_shadow"]:
            lines.append(f"      csak Playwright: {data['only_shadow']}")
        if data["field_diffs"]:
            lines.append(f"      mező-eltérés: {data['field_diffs']}")
    return lines
