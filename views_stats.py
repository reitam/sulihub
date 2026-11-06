# -*- coding: utf-8 -*-
"""
Statisztika (KRÉ-14 #96): tanévek, dashboard, tantárgyi átlagok.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. Prefix nélküli blueprint —
az URL-ek változatlanok.
"""
import math
import os
import sqlite3
from datetime import date, datetime, timedelta

from flask import jsonify, request

import kreta_tanev
from kreta_db import get_db_connection
from kreta_paths import DB_FILE
from kreta_settings import load_config
from views_common import (
    _date_range_from_request, _has_tanev_column, _tanev_from_request,
    hianyzas_osszesito, make_bp, normalize_date,
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
    figyelmeztetesek = []
    for tantargy in sorted(per_tantargy):
        entry = per_tantargy[tantargy]
        honap_atlagok = {h: summarize(v) for h, v in entry["honapok"].items()}
        trend = _trend_szamitas(honap_atlagok)
        if trend["irany"] == "romlik" and (trend["valtozas"] or 0) <= -0.5:
            figyelmeztetesek.append({
                "tantargy": tantargy,
                "valtozas": trend["valtozas"],
                "honapok": trend["honapok"][-2:],
                "atlagok": [honap_atlagok[h]["atlag"] for h in trend["honapok"][-2:]],
            })
        tantargyak.append({
            "tantargy": tantargy,
            "honapok": honap_atlagok,
            "osszes": summarize(entry["mind"]),
            "trend": trend,
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
        "figyelmeztetesek": figyelmeztetesek,
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
@bp.route("/api/ma")
def api_ma():
    """Napi összefoglaló: mai órák, közeli határidők, friss jegyek, olvasatlan üzenetek."""
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
        "diak": diak,
        "orak": [],
        "hataridok": [],
        "uj_jegyek": [],
        "olvasatlan_db": 0,
        "uzenetek": [],
    }
    if not os.path.exists(DB_FILE):
        return jsonify(valasz)

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1) Mai órák (a szinkron két hetet is hozhat -> nap+tantárgy szerint dedupe)
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
            valasz["orak"].append({
                "kezdes": str(row["kezdo_idopont"] or "")[11:16],
                "vege": str(row["zaro_idopont"] or "")[11:16],
                "tantargy": row["tantargy"] or "",
                "tanar": row["tanar"] or "",
                "terem": row["terem"] or "",
                "diak_nev": row["diak_nev"] or "",
            })
    except sqlite3.Error as exc:
        print(f"[Ma] órák: {exc}")

    # 2) Ma/holnap esedékes házik és számonkérések (a kész jelzővel)
    try:
        query = ("SELECT id, diak_nev, esemeny_tipus, tantargy, tema, cim, hatarido, kesz"
                 " FROM esemenyek WHERE esemeny_tipus IN ('Házi feladat',"
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
            valasz["hataridok"].append({
                "id": row["id"],
                "diak_nev": row["diak_nev"] or "",
                "esemeny_tipus": row["esemeny_tipus"] or "",
                "tantargy": row["tantargy"] or "-",
                "megnevezes": row["tema"] or row["cim"] or row["esemeny_tipus"] or "",
                "hatarido": hat,
                "mikor": "ma" if hat == datum else "holnap",
                "kesz": int(row["kesz"] or 0),
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

    diak = request.args.get("diak", "")
    kezdo, zaro = _date_range_from_request()
    tanev_szuro = _tanev_from_request()

    jegyek = []
    if os.path.exists(DB_FILE):
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            query = ("SELECT szam_ertek, suly_szazalek, bej_datum FROM esemenyek"
                     " WHERE esemeny_tipus = 'Értékelés' AND tantargy = ?")
            params = [tantargy]
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
            query = ("SELECT szam_ertek, bej_datum FROM esemenyek"
                     " WHERE esemeny_tipus = 'Értékelés' AND tantargy = ?")
            params = [tantargy]
            if diak:
                query += " AND diak_nev = ?"
                params.append(diak)
            if tanev_szuro:
                query += " AND tanev = ?"
                params.append(tanev_szuro)
            cursor.execute(query, params)
            rows = cursor.fetchall()
        for row in rows:
            dat = normalize_date(row["bej_datum"])
            if dat:
                if kezdo and dat < kezdo:
                    continue
                if zaro and dat > zaro:
                    continue
            jegyek.append((row["szam_ertek"], row["suly_szazalek"] if has_suly else 0))
        conn.close()

    eredmeny = szukseges_jegy(jegyek, cel, uj_suly=uj_suly)
    eredmeny.update({
        "tantargy": tantargy,
        "diak": diak,
        "tanev": tanev_szuro,
        "kezdo_datum": kezdo or "",
        "zaro_datum": zaro or "",
    })
    return jsonify(eredmeny)
