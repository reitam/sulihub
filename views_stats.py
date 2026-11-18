# -*- coding: utf-8 -*-
"""
Statisztika (KRÉ-14 #96): tanévek, dashboard, tantárgyi átlagok.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. Prefix nélküli blueprint —
az URL-ek változatlanok.
"""
import json
import math
import os
import sqlite3
from datetime import date, datetime, timedelta

from flask import jsonify, request

import kreta_tanev
from kreta_db import get_db_connection, get_meta, set_meta
from kreta_paths import DB_FILE
from kreta_settings import load_config
from views_common import (
    _date_range_from_request, _has_tanev_column, _tanev_from_request,
    hianyzas_osszesito, legjobb_tantargy_nev, make_bp, normalize_date, tantargy_kulcs,
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
    query = ("SELECT diak_nev, tantargy, ertek, szam_ertek, bej_datum, suly_szazalek,"
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
    # A romlás-/javulás-figyelmeztetéshez gyermekenként külön bontunk (Kaneo #111):
    # „Mind” nézetben a tantárgyak gyerekenként külön trendet kapnak.
    per_diak_tantargy = {}
    per_honap = {}
    honapok = set()
    mind = []
    # Tantárgy-kulcs -> írásmódok (a KRÉTA nem egységes kis/nagybetűben, #127).
    nev_valtozatok = {}

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
        kulcs = tantargy_kulcs(tantargy) or "egyeb"
        nev_valtozatok.setdefault(kulcs, {})
        nev_valtozatok[kulcs][tantargy] = nev_valtozatok[kulcs].get(tantargy, 0) + 1
        item = {
            "val": val,
            "suly": suly,
            "datum": norm or (r["bej_datum"] or ""),
            "ertek": r["ertek"] or "",
            "tema": r["tema"] or "",
            "tanar": r["ertekelo"] or "",
            "mod": r["mod"] or "",
        }
        entry = per_tantargy.setdefault(kulcs, {"honapok": {}, "mind": []})
        entry["honapok"].setdefault(honap, []).append(item)
        entry["mind"].append(item)
        d_nev = (r["diak_nev"] or "").strip()
        dentry = per_diak_tantargy.setdefault(d_nev, {}).setdefault(
            kulcs, {"honapok": {}, "mind": []})
        dentry["honapok"].setdefault(honap, []).append(item)
        dentry["mind"].append(item)
        per_honap.setdefault(honap, []).append(item)
        mind.append(item)

    tantargyak = []
    for kulcs in sorted(per_tantargy):
        entry = per_tantargy[kulcs]
        honap_atlagok = {h: summarize(v) for h, v in entry["honapok"].items()}
        trend = _trend_szamitas(honap_atlagok)
        tantargyak.append({
            "tantargy": legjobb_tantargy_nev(nev_valtozatok.get(kulcs, {})),
            "honapok": honap_atlagok,
            "osszes": summarize(entry["mind"]),
            "trend": trend,
        })

    # Romló (<= -0.5) és javuló (>= +0.5) tantárgyak gyermekenként, az utolsó
    # két jegyes hónap összevetésével. A figyelmeztetés így megmondja, kinél
    # és melyik időszakban történt a változás (Kaneo #111).
    figyelmeztetesek = []
    javulasok = []
    for d_nev in sorted(per_diak_tantargy):
        for kulcs in sorted(per_diak_tantargy[d_nev]):
            tantargy = legjobb_tantargy_nev(nev_valtozatok.get(kulcs, {}))
            honap_atlagok = {h: summarize(v)
                             for h, v in per_diak_tantargy[d_nev][kulcs]["honapok"].items()}
            trend = _trend_szamitas(honap_atlagok)
            valtozas = trend.get("valtozas")
            if valtozas is None:
                continue
            if trend["irany"] == "romlik" and valtozas <= -0.5:
                figyelmeztetesek.append({
                    "diak": d_nev,
                    "tantargy": tantargy,
                    "valtozas": valtozas,
                    "honapok": trend["honapok"][-2:],
                    "atlagok": [honap_atlagok[h]["atlag"] for h in trend["honapok"][-2:]],
                })
            elif trend["irany"] == "javul" and valtozas >= 0.5:
                javulasok.append({
                    "diak": d_nev,
                    "tantargy": tantargy,
                    "valtozas": valtozas,
                    "honapok": trend["honapok"][-2:],
                    "atlagok": [honap_atlagok[h]["atlag"] for h in trend["honapok"][-2:]],
                })
    figyelmeztetesek.sort(key=lambda f: (f["valtozas"], f["diak"], f["tantargy"]))
    javulasok.sort(key=lambda f: (-f["valtozas"], f["diak"], f["tantargy"]))

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
        "figyelmeztetesek": figyelmeztetesek,
        "javulasok": javulasok,
    })


def _trend_szamitas(honap_atlagok):
    """A tantárgy trendje: az utolsó két (nem üres) hónap átlagának különbsége.

    `honap_atlagok`: `{"2026-09": {"atlag": 4.5, "db": 2}, ...}`.
    Visszaad: irány (`javul`/`romlik`/`stabil`/`nincs`), változás és a hónapok.
    """
    pontok = [(h, v.get("atlag")) for h, v in sorted(honap_atlagok.items())
              if v.get("atlag") is not None]
    if len(pontok) < 2:
        return {"irany": "nincs", "valtozas": None, "honapok": [h for h, _v in pontok]}
    valtozas = round(pontok[-1][1] - pontok[-2][1], 2)
    if abs(valtozas) < 0.05:
        irany = "stabil"
    elif valtozas > 0:
        irany = "javul"
    else:
        irany = "romlik"
    return {"irany": irany, "valtozas": valtozas, "honapok": [h for h, _v in pontok]}


# ==============================================================================
# === „Ma” nézet (Kaneo #9) ===================================================
# ==============================================================================
def _ma_orak(cursor, datum, diak):
    """Egy nap órái a Ma fülhöz (az azonos nap+tantárgy duplikátumok nélkül)."""
    orak = []
    try:
        query = ("SELECT diak_nev, kezdo_idopont, zaro_idopont, tantargy, tanar, terem"
                 " FROM orarend WHERE substr(kezdo_idopont, 1, 10) = ?")
        params = [datum]
        if diak:
            query += " AND diak_nev = ?"
            params.append(diak)
        cursor.execute(query + " ORDER BY kezdo_idopont", params)
        latott = set()
        for row in cursor.fetchall():
            kulcs = (str(row["kezdo_idopont"] or "")[11:16], row["tantargy"] or "")
            if kulcs in latott:
                continue
            latott.add(kulcs)
            orak.append({
                "kezdes": str(row["kezdo_idopont"] or "")[11:16],
                "vege": str(row["zaro_idopont"] or "")[11:16],
                "tantargy": row["tantargy"] or "",
                "tanar": row["tanar"] or "",
                "terem": row["terem"] or "",
                "diak_nev": row["diak_nev"] or "",
            })
    except sqlite3.Error as exc:
        print(f"[Ma] órák: {exc}")
    return orak


@bp.route("/api/ma")
def api_ma():
    """Napi összefoglaló: mai/holnapi órák, közeli határidők, friss jegyek, olvasatlanok."""
    raw_datum = (request.args.get("datum") or "").strip() or date.today().isoformat()
    try:
        nap = datetime.strptime(raw_datum, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "A dátum formátuma ÉÉÉÉ-HH-NN legyen."}), 400
    holnap = nap + timedelta(days=1)
    datum = nap.isoformat()
    diak = request.args.get("diak", "")

    valasz = {
        "datum": datum,
        "holnapi_datum": holnap.isoformat(),
        "diak": diak,
        "orak": [],
        "holnapi_orak": [],
        "hataridok": [],
        "uj_jegyek": [],
        "olvasatlan_db": 0,
        "uzenetek": [],
        "igazolando": [],
        "igazolando_db": 0,
    }
    if not os.path.exists(DB_FILE):
        return jsonify(valasz)

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1) Mai és holnapi órák (a szinkron két hetet is hozhat -> nap+tantárgy dedupe)
    valasz["orak"] = _ma_orak(cursor, datum, diak)
    valasz["holnapi_orak"] = _ma_orak(cursor, holnap.isoformat(), diak)

    # 2) Ma/holnap esedékes házik és számonkérések (a kész jelzővel).
    # A részletek modálhoz a teljes eseménysor kell (leírás, tanár, dátum stb.).
    try:
        query = ("SELECT * FROM esemenyek WHERE esemeny_tipus IN ('Házi feladat',"
                 " 'Bejelentett számonkérés')")
        params = []
        if diak:
            query += " AND diak_nev = ?"
            params.append(diak)
        cursor.execute(query + " ORDER BY hatarido", params)
        for row in cursor.fetchall():
            hat = normalize_date(row["hatarido"])
            if hat not in (datum, holnap.isoformat()):
                continue
            keys = row.keys()
            valasz["hataridok"].append({
                "id": row["id"],
                "diak_nev": row["diak_nev"] or "",
                "esemeny_tipus": row["esemeny_tipus"] or "",
                "tantargy": row["tantargy"] or "-",
                "megnevezes": row["tema"] or row["cim"] or row["esemeny_tipus"] or "",
                "hatarido": hat,
                "mikor": "ma" if hat == datum else "holnap",
                "kesz": int(row["kesz"] or 0),
                # Részletek a kattintásra nyíló modálhoz (mint az Események fülön).
                "ertek": row["ertek"] or "",
                "suly_szazalek": int(row["suly_szazalek"] or 0) if "suly_szazalek" in keys else 0,
                "bej_datum": row["bej_datum"] or "",
                "ertekelo": row["ertekelo"] or "",
                "tipus": row["tipus"] or "",
                "mod": row["mod"] or "",
                "tema": row["tema"] or "",
                "cim": row["cim"] or "",
                "tartalom": row["tartalom"] or "",
            })
    except sqlite3.Error as exc:
        print(f"[Ma] határidők: {exc}")

    # 3) Friss jegyek (az elmúlt 7 nap)
    try:
        query = ("SELECT id, diak_nev, tantargy, ertek, szam_ertek, bej_datum"
                 " FROM esemenyek WHERE esemeny_tipus = 'Értékelés'")
        params = []
        if diak:
            query += " AND diak_nev = ?"
            params.append(diak)
        cursor.execute(query + " ORDER BY id DESC LIMIT 40", params)
        hatar = (nap - timedelta(days=6)).isoformat()
        for row in cursor.fetchall():
            bej = normalize_date(row["bej_datum"])
            if not bej or not (hatar <= bej <= datum):
                continue
            valasz["uj_jegyek"].append({
                "id": row["id"],
                "diak_nev": row["diak_nev"] or "",
                "tantargy": row["tantargy"] or "-",
                "ertek": row["ertek"] or "-",
                "szam_ertek": row["szam_ertek"] or 0,
                "bej_datum": bej,
            })
            if len(valasz["uj_jegyek"]) >= 8:
                break
    except sqlite3.Error as exc:
        print(f"[Ma] jegyek: {exc}")

    # 4) Olvasatlan üzenetek
    try:
        query = "SELECT id, diak_nev, felado, targy FROM uzenetek WHERE COALESCE(olvasott, 0) = 0"
        params = []
        if diak:
            query += " AND diak_nev = ?"
            params.append(diak)
        cursor.execute("SELECT COUNT(*) FROM (" + query + ")", params)
        valasz["olvasatlan_db"] = int(cursor.fetchone()[0] or 0)
        cursor.execute(query + " ORDER BY id DESC LIMIT 5", params)
        for row in cursor.fetchall():
            valasz["uzenetek"].append({
                "id": row["id"],
                "diak_nev": row["diak_nev"] or "",
                "felado": row["felado"] or "",
                "targy": row["targy"] or "",
            })
    except sqlite3.Error as exc:
        print(f"[Ma] üzenetek: {exc}")

    # 5) Igazolandó hiányzások (Kaneo #134): a még nem igazolt mulasztások.
    try:
        query = ("SELECT id, diak_nev, mulasztas_datum, ora_sorszam, perc, tantargy,"
                 " mulasztas_tipus, tanorai_celu FROM hianyzasok WHERE igazolt = 0")
        params = []
        if diak:
            query += " AND diak_nev = ?"
            params.append(diak)
        cursor.execute("SELECT COUNT(*) FROM (" + query + ")", params)
        valasz["igazolando_db"] = int(cursor.fetchone()[0] or 0)
        cursor.execute(query + " ORDER BY mulasztas_datum DESC, ora_sorszam DESC LIMIT 20",
                       params)
        for row in cursor.fetchall():
            mdatum = str(row["mulasztas_datum"] or "")[:10]
            napok = None
            try:
                napok = max(0, (nap - date.fromisoformat(mdatum)).days)
            except ValueError:
                pass
            valasz["igazolando"].append({
                "id": row["id"],
                "diak_nev": row["diak_nev"] or "",
                "datum": mdatum,
                "ora": int(row["ora_sorszam"] or 0),
                "perc": int(row["perc"]) if row["perc"] is not None else None,
                "tantargy": row["tantargy"] or "",
                "tipus": row["mulasztas_tipus"] or "",
                "tanorai_celu": row["tanorai_celu"] or "",
                "napok": napok,
            })
    except sqlite3.Error as exc:
        print(f"[Ma] igazolandó: {exc}")

    conn.close()
    return jsonify(valasz)


# ==============================================================================
# === „Milyen jegy kell?” kalkulátor (Kaneo #78) ==============================
# ==============================================================================
def szukseges_jegy(jegyek, cel, uj_suly=100, max_darab=20):
    """Mennyi/osztályzat kell a célátlaghoz a KRÉTA súlyozásával.

    `jegyek`: `(érdemjegy, súlyszázalék)` párok. A 0%-os súlyú jegy nem számít
    bele (mint a KRÉTA és a mi átlagaink); ha egy jegynek sincs súlya, egyszerű
    átlaggal számolunk (régi adat).

    A `cel` eléréséhez vagy **egy** új jegy kell (1–5), vagy több **ötös**;
    ha még az sem elég, a cél nem érhető el.
    """
    def _alap(**kwargs):
        out = {
            "elerheto": False,
            "cel": round(float(cel), 2),
            "uj_suly": uj_suly,
            "aktualis_atlag": None,
            "jegy_db": 0,
            "suly_db": 0,
            "szukseges_jegy": None,
            "szukseges_darab": None,
            "varhato_atlag": None,
            "mod": "sulyozott",
            "uzenet": "",
        }
        out.update(kwargs)
        return out

    parok = []
    for ertek, suly in jegyek:
        try:
            ertek = int(ertek)
            suly = int(suly or 0)
        except (TypeError, ValueError):
            continue
        if ertek in (1, 2, 3, 4, 5):
            parok.append((ertek, suly))
    if not parok:
        return _alap(uzenet="Ehhez a tantárgyhoz még nincs jegy.")

    cel = float(cel)
    sulyos = [(e, s) for e, s in parok if s > 0]
    if sulyos:
        ossz_suly = sum(s for _e, s in sulyos)
        ossz_pont = sum(e * s for e, s in sulyos)
        aktualis = ossz_pont / ossz_suly
        mod = "sulyozott"
    else:
        ossz_suly = 0
        ossz_pont = sum(e for e, _s in parok)
        aktualis = ossz_pont / len(parok)
        mod = "egyszeru"

    kozos = {
        "aktualis_atlag": round(aktualis, 2),
        "jegy_db": len(parok),
        "suly_db": len(sulyos),
        "mod": mod,
    }

    if cel <= aktualis + 1e-9:
        return _alap(elerheto=True, varhato_atlag=round(aktualis, 2),
                     uzenet=f"Már megvan: {aktualis:.2f} (cél {cel:.2f}).", **kozos)

    if mod == "sulyozott":
        if cel >= 5 - 1e-9:
            return _alap(uzenet="Ötös célátlag csak akkor lehet, ha már minden jegy ötös.",
                         **kozos)
        kell = (cel * (ossz_suly + uj_suly) - ossz_pont) / uj_suly
        if kell <= 5 + 1e-9:
            jegy = max(1, min(5, math.ceil(kell - 1e-9)))
            varhato = (ossz_pont + jegy * uj_suly) / (ossz_suly + uj_suly)
            return _alap(
                elerheto=True, szukseges_jegy=jegy, szukseges_darab=1,
                varhato_atlag=round(varhato, 2),
                uzenet=(f"1 db {jegy}-es jegy kell ({aktualis:.2f} → {varhato:.2f})."
                        if jegy != 5 else
                        f"1 db 5-ös jegy kell ({aktualis:.2f} → {varhato:.2f})."),
                **kozos)
        darab = math.ceil((cel * ossz_suly - ossz_pont) / (uj_suly * (5 - cel)) - 1e-9)
        if darab < 1:
            darab = 1
        if darab > max_darab:
            return _alap(uzenet=f"Ebben az időszakban már nem érhető el ({darab} db 5-ös "
                                f"kellene, a cél {cel:.2f}).", **kozos)
        varhato = (ossz_pont + 5 * uj_suly * darab) / (ossz_suly + uj_suly * darab)
        return _alap(
            elerheto=True, szukseges_jegy=5, szukseges_darab=darab,
            varhato_atlag=round(varhato, 2),
            uzenet=f"{darab} db 5-ös jegy kell ({aktualis:.2f} → {varhato:.2f}).",
            **kozos)

    # Súlyadat nélküli (régi) adat: egyszerű átlag.
    if cel >= 5 - 1e-9:
        return _alap(uzenet="Ötös célátlag csak akkor lehet, ha már minden jegy ötös.",
                     **kozos)
    kell = cel * (len(parok) + 1) - ossz_pont
    if kell <= 5 + 1e-9:
        jegy = max(1, min(5, math.ceil(kell - 1e-9)))
        varhato = (ossz_pont + jegy) / (len(parok) + 1)
        return _alap(
            elerheto=True, szukseges_jegy=jegy, szukseges_darab=1,
            varhato_atlag=round(varhato, 2),
            uzenet=f"1 db {jegy}-es jegy kell ({aktualis:.2f} → {varhato:.2f}).",
            **kozos)
    darab = math.ceil((cel * len(parok) - ossz_pont) / (5 - cel) - 1e-9)
    if darab < 1:
        darab = 1
    if darab > max_darab:
        return _alap(uzenet=f"Ebben az időszakban már nem érhető el ({darab} db 5-ös "
                            f"kellene, a cél {cel:.2f}).", **kozos)
    varhato = (ossz_pont + 5 * darab) / (len(parok) + darab)
    return _alap(
        elerheto=True, szukseges_jegy=5, szukseges_darab=darab,
        varhato_atlag=round(varhato, 2),
        uzenet=f"{darab} db 5-ös jegy kell ({aktualis:.2f} → {varhato:.2f}).",
        **kozos)


def _kalk_parok(jegyek):
    """(jegy, súly) párok szűrése 1–5 közé; súly nélküli adatnál 100%-os becslés."""
    parok = []
    for ertek, suly in jegyek:
        try:
            ertek = int(ertek)
            suly = int(suly or 0)
        except (TypeError, ValueError):
            continue
        if ertek in (1, 2, 3, 4, 5):
            parok.append((ertek, suly))
    return parok


def _kalk_aktualis(parok):
    """A jelenlegi súlyozott átlag (0%-os súly kimarad); súly nélkül 100%-os becslés."""
    sulyos = [(e, s) for e, s in parok if s > 0]
    becsult = False
    if not sulyos:
        sulyos = [(e, 100) for e, _s in parok]
        becsult = True
    ossz_suly = sum(s for _e, s in sulyos)
    ossz_pont = sum(e * s for e, s in sulyos)
    return ossz_suly, ossz_pont, ossz_pont / ossz_suly, len(sulyos), becsult


def tobb_jegy_szamitas(jegyek, cel, sulyok, varhato=None):
    """Több várható jegy (eltérő súlyokkal): szükséges átlag + szimuláció (Kaneo #101).

    `sulyok`: a jövőbeli jegyek súlyszázalékai (pl. [100, 100, 50]).
    `varhato`: opcionális, a jövőbeli jegyek várható érdemjegyei (0/None = ismeretlen).
    A szükséges átlag a hátralévő jegyekre vonatkozik; ha mind ismert, a várható
    félévi/tanév végi átlagot is kiszámoljuk.
    """
    cel = float(cel)
    parok = _kalk_parok(jegyek)
    sulyok = [int(s) for s in (sulyok or []) if int(s or 0) > 0]
    out = {
        "tobb": True,
        "cel": round(cel, 2),
        "elerheto": False,
        "aktualis_atlag": None,
        "jegy_db": len(parok),
        "suly_db": 0,
        "mod": "sulyozott",
        "sulyok": sulyok,
        "suly_osszeg": sum(sulyok),
        "jegyek_szama": len(sulyok),
        "szukseges_atlag": None,
        "szimulalt_atlag": None,
        "cel_teljesul": None,
        "uzenet": "",
    }
    if not parok:
        out["uzenet"] = "Ehhez a tantárgyhoz még nincs jegy."
        return out
    if not sulyok:
        out["uzenet"] = "Adj meg legalább egy várható jegyet (súlyt)."
        return out

    ossz_suly, ossz_pont, aktualis, suly_db, becsult = _kalk_aktualis(parok)
    out.update({
        "aktualis_atlag": round(aktualis, 2),
        "suly_db": suly_db,
        "mod": "becsult" if becsult else "sulyozott",
    })

    if cel <= aktualis + 1e-9:
        out["elerheto"] = True
        out["uzenet"] = f"Már megvan: {aktualis:.2f} (cél {cel:.2f})."
    else:
        uj_suly = sum(sulyok)
        kell_pont = cel * (ossz_suly + uj_suly) - ossz_pont
        kell_atlag = kell_pont / uj_suly
        if kell_atlag > 5 + 1e-9:
            out["uzenet"] = (f"A hátralévő {len(sulyok)} jeggyel már nem érhető el "
                             f"({kell_atlag:.2f}-es átlag kellene, a cél {cel:.2f}).")
        else:
            out["elerheto"] = True
            out["szukseges_atlag"] = round(max(1.0, kell_atlag), 2)
            out["uzenet"] = (f"A {len(sulyok)} várható jegyen összesen "
                             f"{kell_atlag:.2f}-es átlag kell "
                             f"({aktualis:.2f} → {cel:.2f}).")

    # Szimuláció: ha minden jövőbeli jegy ismert, mennyi lesz az átlag?
    v = list(varhato or [])
    if len(v) == len(sulyok) and all(x in (1, 2, 3, 4, 5) for x in v):
        uj_suly = sum(sulyok)
        sim = (ossz_pont + sum(int(x) * s for x, s in zip(v, sulyok))) / (ossz_suly + uj_suly)
        out["szimulalt_atlag"] = round(sim, 2)
        out["cel_teljesul"] = bool(sim >= cel - 1e-9)
        out["uzenet"] += f" A megadott jegyekkel a várható átlag {sim:.2f}."
    return out


def felevi_szamitas(jegyek, felevi, sulyok):
    """Mi kell a félévi jegyhez (Kaneo #101).

    A félévi jegy a súlyozott átlag kerekítése; a küszöb `félévi jegy - 0,5`
    (pl. 4-eshez 3,50). A hátralévő jegyekre szükséges átlagot is kiszámoljuk.
    """
    felevi = int(felevi)
    kuszob = max(1.0, felevi - 0.5)
    out = {
        "felevi_cel": felevi,
        "felevi_kuszob": round(kuszob, 2),
        "felevi_elerheto": False,
        "felevi_szukseges_atlag": None,
        "felevi_uzenet": "",
    }
    parok = _kalk_parok(jegyek)
    if not parok:
        out["felevi_uzenet"] = "Ehhez a tantárgyhoz még nincs jegy."
        return out
    ossz_suly, ossz_pont, aktualis, _suly_db, _becsult = _kalk_aktualis(parok)
    if aktualis >= kuszob - 1e-9:
        out["felevi_elerheto"] = True
        out["felevi_uzenet"] = (f"A félévi {felevi}-eshez {kuszob:.2f}-es átlag kell; "
                                f"jelenleg {aktualis:.2f} — megvan.")
        return out
    sulyok = [int(s) for s in (sulyok or []) if int(s or 0) > 0]
    if not sulyok:
        out["felevi_uzenet"] = (f"A félévi {felevi}-eshez {kuszob:.2f}-es átlag kell; "
                                f"jelenleg {aktualis:.2f} — adj meg várható jegyet.")
        return out
    uj_suly = sum(sulyok)
    kell_atlag = (kuszob * (ossz_suly + uj_suly) - ossz_pont) / uj_suly
    if kell_atlag > 5 + 1e-9:
        out["felevi_uzenet"] = (f"A félévi {felevi}-eshez már nem elég a hátralévő "
                                f"{len(sulyok)} jegy ({kell_atlag:.2f}-es átlag kellene).")
    else:
        out["felevi_elerheto"] = True
        out["felevi_szukseges_atlag"] = round(max(1.0, kell_atlag), 2)
        out["felevi_uzenet"] = (f"A félévi {felevi}-eshez a hátralévő {len(sulyok)} jegyen "
                                f"{max(1.0, kell_atlag):.2f}-es átlag kell "
                                f"(küszöb {kuszob:.2f}, jelenleg {aktualis:.2f}).")
    return out


def _int_lista(raw, max_items=10):
    """Vesszős egész lista (pl. `100,50,`); üres/rossz elem -> 0."""
    if not raw:
        return []
    out = []
    for part in str(raw).split(",")[:max_items]:
        part = part.strip()
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return out


KALK_CEL_PREFIX = "kalk_cel:"


def _kalk_cel_kulcs(diak, tantargy):
    return f"{KALK_CEL_PREFIX}{diak or '(mind)'}|{tantargy}"


@bp.route("/api/kalkulator_cel", methods=["GET", "POST"])
def api_kalkulator_cel():
    """A kalkulátor mentett célátlaga/félévi célja diákonként és tantárgyanként (Kaneo #101)."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        tantargy = (body.get("tantargy") or "").strip()
        if not tantargy:
            return jsonify({"error": "Válassz tantárgyat."}), 400
        diak = (body.get("diak") or "").strip()
        adat = {}
        cel = body.get("cel")
        if cel not in (None, ""):
            try:
                cel = float(str(cel).replace(",", "."))
            except ValueError:
                return jsonify({"error": "A célátlag nem szám."}), 400
            if not 1 <= cel <= 5:
                return jsonify({"error": "A célátlag 1 és 5 között lehet."}), 400
            adat["cel"] = round(cel, 2)
        felevi = body.get("felevi")
        if felevi not in (None, ""):
            try:
                felevi = int(felevi)
            except (TypeError, ValueError):
                return jsonify({"error": "A félévi céljegy 1 és 5 között lehet."}), 400
            if not 1 <= felevi <= 5:
                return jsonify({"error": "A félévi céljegy 1 és 5 között lehet."}), 400
            adat["felevi"] = felevi
        set_meta(_kalk_cel_kulcs(diak, tantargy),
                 json.dumps(adat, ensure_ascii=False) if adat else "")
        return jsonify({"status": "ok", "diak": diak, "tantargy": tantargy,
                        "cel": adat.get("cel"), "felevi": adat.get("felevi")})

    tantargy = (request.args.get("tantargy") or "").strip()
    if not tantargy:
        return jsonify({"error": "Válassz tantárgyat."}), 400
    diak = (request.args.get("diak") or "").strip()
    raw = get_meta(_kalk_cel_kulcs(diak, tantargy), "")
    adat = {}
    if raw:
        try:
            adat = json.loads(raw)
        except ValueError:
            adat = {}
    return jsonify({"diak": diak, "tantargy": tantargy,
                    "cel": adat.get("cel"), "felevi": adat.get("felevi")})


@bp.route("/api/jegy_kalkulator")
def api_jegy_kalkulator():
    """„Milyen jegy kell?” — tantárgy + célátlag + a következő jegy súlya (Kaneo #78)."""
    tantargy = (request.args.get("tantargy") or "").strip()
    if not tantargy:
        return jsonify({"error": "Válassz tantárgyat."}), 400
    try:
        cel = float((request.args.get("cel") or "4.5").replace(",", "."))
    except ValueError:
        return jsonify({"error": "A célátlag nem szám."}), 400
    if not 1 <= cel <= 5:
        return jsonify({"error": "A célátlag 1 és 5 között lehet."}), 400
    try:
        uj_suly = int(request.args.get("suly") or 100)
    except ValueError:
        return jsonify({"error": "A súly nem szám."}), 400
    if uj_suly <= 0:
        return jsonify({"error": "A súly nagyobb kell legyen 0-nál."}), 400

    # Több várható jegy (Kaneo #101): súlyok vesszős listája és opcionális jegyek.
    sulyok_raw = _int_lista(request.args.get("sulyok"))
    varhato_raw = _int_lista(request.args.get("varhato"))
    sulyok, varhato = [], []
    for i, s in enumerate(sulyok_raw):
        if s > 0:
            sulyok.append(s)
            varhato.append(varhato_raw[i] if i < len(varhato_raw) else 0)
    felevi_raw = (request.args.get("felevi") or "").strip()
    felevi = None
    if felevi_raw:
        try:
            felevi = int(felevi_raw)
        except ValueError:
            return jsonify({"error": "A félévi céljegy 1 és 5 között lehet."}), 400
        if not 1 <= felevi <= 5:
            return jsonify({"error": "A félévi céljegy 1 és 5 között lehet."}), 400

    diak = request.args.get("diak", "")
    kezdo, zaro = _date_range_from_request()
    tanev_szuro = _tanev_from_request()

    jegyek = []
    jegy_lista = []
    if os.path.exists(DB_FILE):
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            query = ("SELECT tantargy, ertek, szam_ertek, suly_szazalek, bej_datum FROM esemenyek"
                     " WHERE esemeny_tipus = 'Értékelés'")
            params = []
            if diak:
                query += " AND diak_nev = ?"
                params.append(diak)
            if tanev_szuro:
                query += " AND tanev = ?"
                params.append(tanev_szuro)
            has_suly = True
            cursor.execute(query, params)
            rows = cursor.fetchall()
        except sqlite3.Error:
            # Régi DB: nincs suly_szazalek oszlop.
            has_suly = False
            query = ("SELECT tantargy, ertek, szam_ertek, bej_datum FROM esemenyek"
                     " WHERE esemeny_tipus = 'Értékelés'")
            params = []
            if diak:
                query += " AND diak_nev = ?"
                params.append(diak)
            if tanev_szuro:
                query += " AND tanev = ?"
                params.append(tanev_szuro)
            cursor.execute(query, params)
            rows = cursor.fetchall()
        # A tantárgy-egyeztetés kis/nagybetű-független (Kaneo #127).
        kulcs = tantargy_kulcs(tantargy)
        rows = [row for row in rows
                if tantargy_kulcs(row["tantargy"] if "tantargy" in row.keys() else "") == kulcs]
        for row in rows:
            dat = normalize_date(row["bej_datum"])
            if dat:
                if kezdo and dat < kezdo:
                    continue
                if zaro and dat > zaro:
                    continue
            suly = row["suly_szazalek"] if has_suly else 0
            jegyek.append((row["szam_ertek"], suly))
            if row["szam_ertek"] in (1, 2, 3, 4, 5):
                jegy_lista.append({
                    "datum": dat or "",
                    "ertek": row["ertek"] or "",
                    "szam": row["szam_ertek"],
                    "suly": suly or 0,
                })
        conn.close()

    # A felületen a tantárgy meglévő jegyeit is kilistázzuk (Kaneo #78) —
    # legfrissebb elöl, ugyanazokkal a súlyokkal, amikkel a számítás megy.
    jegy_lista.sort(key=lambda j: j["datum"], reverse=True)

    if len(sulyok) > 1:
        eredmeny = tobb_jegy_szamitas(jegyek, cel, sulyok, varhato=varhato)
    else:
        egy_suly = sulyok[0] if sulyok else uj_suly
        eredmeny = szukseges_jegy(jegyek, cel, uj_suly=egy_suly)
        eredmeny.update({"tobb": False, "sulyok": [egy_suly], "varhato": [],
                         "szukseges_atlag": None, "szimulalt_atlag": None,
                         "cel_teljesul": None})
        # Egyetlen várható jegy is megadható: mennyi lesz így az átlag?
        if varhato and varhato[0] in (1, 2, 3, 4, 5):
            parok = _kalk_parok(jegyek)
            if parok:
                ossz_suly, ossz_pont, _akt, _db, _b = _kalk_aktualis(parok)
                sim = (ossz_pont + varhato[0] * egy_suly) / (ossz_suly + egy_suly)
                eredmeny["szimulalt_atlag"] = round(sim, 2)
                eredmeny["cel_teljesul"] = bool(sim >= cel - 1e-9)
    if felevi is not None:
        eredmeny.update(felevi_szamitas(
            jegyek, felevi, sulyok or [uj_suly]))
    eredmeny.update({
        "tantargy": tantargy,
        "diak": diak,
        "tanev": tanev_szuro,
        "kezdo_datum": kezdo or "",
        "zaro_datum": zaro or "",
        "jegyek": jegy_lista,
    })
    return jsonify(eredmeny)
