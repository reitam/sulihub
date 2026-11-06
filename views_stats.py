# -*- coding: utf-8 -*-
"""
Statisztika (KRÉ-14 #96): tanévek, dashboard, tantárgyi átlagok.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. Prefix nélküli blueprint —
az URL-ek változatlanok.
"""
import os
import sqlite3

from flask import jsonify, request

import kreta_tanev
from kreta_db import get_db_connection
from kreta_paths import DB_FILE
from kreta_settings import load_config
from views_common import (
    _has_tanev_column, _tanev_from_request, hianyzas_osszesito, make_bp, normalize_date,
)

bp = make_bp("stats")

@bp.route("/api/tanevek")
def api_tanevek():
    """A DB-ben előforduló tanévek, az aktuális tanév és a határok (Kaneo #40)."""
    aktualis = kreta_tanev.current_tanev()
    empty = {"tanevek": [], "aktualis": aktualis, "hatarok": {}, "ismeretlen_db": 0,
             "allapot": {}}
    if not os.path.exists(DB_FILE):
        return jsonify(empty)

    conn = get_db_connection()
    cursor = conn.cursor()
    tanevek = set()
    ismeretlen = 0
    for table in kreta_tanev.TANEV_UI_TABLES:
        if not _has_tanev_column(cursor, table):
            continue
        try:
            rows = cursor.execute(
                f"SELECT tanev, COUNT(*) FROM {table} WHERE tanev IS NOT NULL GROUP BY tanev"
            ).fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            if row[0]:
                tanevek.add(row[0])
            else:
                ismeretlen += row[1]

    hatarok = {}
    for tanev in tanevek:
        kezd, veg = kreta_tanev.tanev_bounds(tanev)
        hatarok[tanev] = {
            "kezdo": kezd.isoformat() if kezd else "",
            "zaro": veg.isoformat() if veg else "",
        }
    # A tanév-állapotot (Kaneo #43) is visszaadjuk: nyitott/le zárt + időpont.
    allapot = kreta_tanev.tanev_allapotok(conn)
    conn.close()
    return jsonify({"tanevek": sorted(tanevek), "aktualis": aktualis,
                    "hatarok": hatarok, "ismeretlen_db": ismeretlen,
                    "allapot": allapot})


@bp.route("/api/dashboard")
def api_dashboard():
    """Dashboard összesítők (Kaneo #38).

    - diákonkénti **tanulmányi átlag** (teljes időszak, súlyozva),
    - **zsebpénz-egyenleg**: a teljes időszak egyenlege mínusz a már kifizetett
      időszakok rögzített összegei (a maradék a „kifizetetlen”),
    - **igazolatlan hiányzás** órában (a hiányzások fül összesítőjével azonos logika).
    """
    empty = {"enabled": True, "diakok": [], "osszes_hatralevo": 0, "igazolatlan_ora": 0}
    if not os.path.exists(DB_FILE):
        return jsonify(empty)

    config = load_config()
    global_enable = config.get("ENABLE_REWARDS", True)
    rewards = config.get("REWARDS", {
        "jegy_5": 500, "jegy_4": 200, "jegy_3": 0, "jegy_2": -200, "jegy_1": -500,
        "dicseret": 500, "megrovas": -500, "lecke_hiany": -300, "felszereles_hiany": -300
    })
    keywords = config.get("KEYWORDS", {
        "dicseret": ["dicséret", "dicséretben", "kiemelkedő"],
        "megrovas": ["intő", "megrovás", "figyelmeztetés"],
        "lecke_hiany": ["házi feladat hiány", "házi hiány", "lecke hiány", "nem készített házi"],
        "felszereles_hiany": ["felszerelés hiány", "felszerelése hiányzott", "felszereléshiány"]
    })
    diak_param = request.args.get("diak", "")
    tanev_szuro = _tanev_from_request()
    tanev_clause = " AND tanev = ?" if tanev_szuro else ""
    tanev_vals = (tanev_szuro,) if tanev_szuro else ()

    conn = get_db_connection()
    cursor = conn.cursor()

    def jegy_atlag(nev):
        try:
            cursor.execute(
                "SELECT szam_ertek, suly_szazalek FROM esemenyek"
                " WHERE diak_nev = ? AND esemeny_tipus = 'Értékelés'" + tanev_clause,
                (nev,) + tanev_vals)
            rows = cursor.fetchall()
            has_suly = True
        except sqlite3.Error:
            cursor.execute(
                "SELECT szam_ertek FROM esemenyek"
                " WHERE diak_nev = ? AND esemeny_tipus = 'Értékelés'" + tanev_clause,
                (nev,) + tanev_vals)
            rows = cursor.fetchall()
            has_suly = False
        osszeg = 0
        db = 0
        suly_sum = 0
        sulyozott = 0.0
        for r in rows:
            val = r["szam_ertek"]
            if val not in (1, 2, 3, 4, 5):
                continue
            db += 1
            osszeg += val
            suly = (r["suly_szazalek"] if has_suly else 0) or 0
            if suly > 0:
                suly_sum += suly
                sulyozott += val * suly
        if not db:
            return None, 0
        return (round(sulyozott / suly_sum, 2) if suly_sum else round(osszeg / db, 2)), db

    def teljes_egyenleg(nev):
        """A teljes időszak zsebpénz-egyenlege (minden jegy és feljegyzés)."""
        total = 0
        cursor.execute(
            "SELECT szam_ertek FROM esemenyek"
            " WHERE diak_nev = ? AND esemeny_tipus = 'Értékelés'" + tanev_clause,
            (nev,) + tanev_vals)
        for r in cursor.fetchall():
            val = r["szam_ertek"]
            if val in (1, 2, 3, 4, 5):
                total += rewards.get(f"jegy_{val}", 0)
        cursor.execute(
            "SELECT cim, tartalom FROM esemenyek"
            " WHERE diak_nev = ? AND esemeny_tipus = 'Feljegyzés'" + tanev_clause,
            (nev,) + tanev_vals)
        for r in cursor.fetchall():
            text = f"{r['cim'] or ''} {r['tartalom'] or ''}".lower()
            for cat, kw_list in keywords.items():
                if any(kw in text for kw in kw_list):
                    total += rewards.get(cat, 0)
        return total

    def kifizetett_osszeg(nev):
        try:
            cursor.execute(
                "SELECT COALESCE(SUM(osszeg), 0) AS s FROM kifizetesek"
                " WHERE diak_nev = ? AND kifizetve = 1" + tanev_clause,
                (nev,) + tanev_vals)
            row = cursor.fetchone()
            return int(row["s"] or 0)
        except sqlite3.Error:
            return 0

    diakok = []
    osszes_hatralevo = 0
    for s in config.get("STUDENTS", []):
        nev = s.get("diak_nev")
        if not nev or (diak_param and nev != diak_param):
            continue
        atlag, jegy_db = jegy_atlag(nev)
        rewards_enabled = bool(global_enable) and bool(s.get("enable_rewards", True))
        teljes = teljes_egyenleg(nev) if rewards_enabled else 0
        fizetve = kifizetett_osszeg(nev) if rewards_enabled else 0
        hatralevo = teljes - fizetve
        osszes_hatralevo += hatralevo
        diakok.append({
            "diak": nev,
            "atlag": atlag,
            "jegy_db": jegy_db,
            "teljes_egyenleg": teljes,
            "kifizetve_osszeg": fizetve,
            "hatralevo": hatralevo,
            "rewards_enabled": rewards_enabled,
        })

    try:
        query = "SELECT * FROM hianyzasok WHERE 1=1"
        params = []
        if diak_param:
            query += " AND diak_nev = ?"
            params.append(diak_param)
        if tanev_szuro:
            query += " AND tanev = ?"
            params.append(tanev_szuro)
        cursor.execute(query, params)
        hianyzas_rows = [dict(r) for r in cursor.fetchall()]
        igazolatlan = hianyzas_osszesito(hianyzas_rows)["igazolatlan_ora"]
    except sqlite3.Error:
        igazolatlan = 0

    conn.close()
    return jsonify({
        "enabled": True,
        "diakok": diakok,
        "osszes_hatralevo": osszes_hatralevo,
        "igazolatlan_ora": igazolatlan,
    })


@bp.route("/api/atlagok")
def api_atlagok():
    """Tantárgyankénti tanulmányi átlagok, havi bontással (Kaneo #39).

    A súlyozás ugyanaz, mint a statisztikában: Σ(jegy×súly)/Σ(súly), a 0%-os
    súlyú jegy kimarad; súlyadat nélkül egyszerű átlag.
    """
    if not os.path.exists(DB_FILE):
        return jsonify({"honapok": [], "tantargyak": [], "osszes": {"atlag": None, "db": 0}})

    diak = request.args.get("diak", "")
    kezdo_datum = request.args.get("kezdo_datum", "")
    zaro_datum = request.args.get("zaro_datum", "")
    tanev_szuro = _tanev_from_request()

    conn = get_db_connection()
    cursor = conn.cursor()
    query = ("SELECT tantargy, ertek, szam_ertek, bej_datum, suly_szazalek,"
             " ertekelo, tema, mod FROM esemenyek WHERE esemeny_tipus = 'Értékelés'")
    params = []
    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    if tanev_szuro:
        query += " AND tanev = ?"
        params.append(tanev_szuro)
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        has_suly = True
    except sqlite3.Error:
        # Régi DB, ahol még nincs suly_szazalek oszlop.
        cursor.execute(query.replace(", suly_szazalek ", " "), params)
        rows = cursor.fetchall()
        has_suly = False
    conn.close()

    def summarize(items):
        """[{val, suly, ...}] -> {atlag, db, jegyek} (súlyozva, ha van súly)."""
        if not items:
            return {"atlag": None, "db": 0, "jegyek": []}
        osszeg = 0
        suly_sum = 0
        sulyozott = 0.0
        jegyek = []
        for it in items:
            val = it["val"]
            suly = it["suly"]
            osszeg += val
            if suly and suly > 0:
                suly_sum += suly
                sulyozott += val * suly
            jegyek.append({
                "datum": it["datum"],
                "ertek": it["ertek"],
                "szam": val,
                "suly": suly,
                "tema": it["tema"],
                "tanar": it["tanar"],
                "mod": it["mod"],
            })
        atlag = round(sulyozott / suly_sum, 2) if suly_sum else round(osszeg / len(items), 2)
        jegyek.sort(key=lambda j: j["datum"], reverse=True)
        return {"atlag": atlag, "db": len(items), "jegyek": jegyek}

    per_tantargy = {}
    per_honap = {}
    honapok = set()
    mind = []

    for r in rows:
        val = r["szam_ertek"]
        if val not in (1, 2, 3, 4, 5):
            continue
        norm = normalize_date(r["bej_datum"])
        if norm:
            if kezdo_datum and norm < kezdo_datum:
                continue
            if zaro_datum and norm > zaro_datum:
                continue
        honap = norm[:7] if norm else "ismeretlen"
        if honap != "ismeretlen":
            honapok.add(honap)
        suly = (r["suly_szazalek"] if has_suly else 0) or 0
        tantargy = (r["tantargy"] or "Egyéb").strip()
        item = {
            "val": val,
            "suly": suly,
            "datum": norm or (r["bej_datum"] or ""),
            "ertek": r["ertek"] or "",
            "tema": r["tema"] or "",
            "tanar": r["ertekelo"] or "",
            "mod": r["mod"] or "",
        }
        entry = per_tantargy.setdefault(tantargy, {"honapok": {}, "mind": []})
        entry["honapok"].setdefault(honap, []).append(item)
        entry["mind"].append(item)
        per_honap.setdefault(honap, []).append(item)
        mind.append(item)

    tantargyak = []
    for tantargy in sorted(per_tantargy):
        entry = per_tantargy[tantargy]
        tantargyak.append({
            "tantargy": tantargy,
            "honapok": {h: summarize(v) for h, v in entry["honapok"].items()},
            "osszes": summarize(entry["mind"]),
        })

    def summarize_light(items):
        """Csak az átlag + darabszám (a havi teljes átlagokhoz, jegyek nélkül)."""
        r = summarize(items)
        return {"atlag": r["atlag"], "db": r["db"]}

    return jsonify({
        "honapok": sorted(honapok),
        "tantargyak": tantargyak,
        # Havi TELJES átlag (minden tantárgy együtt) - a fa középső szintje.
        "honap_osszes": {h: summarize_light(v) for h, v in sorted(per_honap.items())},
        "osszes": summarize_light(mind),
        "tanev": tanev_szuro,
        "aktualis_tanev": kreta_tanev.current_tanev(),
    })
