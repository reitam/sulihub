# -*- coding: utf-8 -*-
"""
Exportok (KRÉ-14 #96): PDF órarend, zsebpénz Excel/CSV és a közös számítási mag.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. A `compute_zsebpenz_statisztika`
ugyanazt adja, mint a felület `/api/statisztika` értéke (a #77 követelménye).
Prefix nélküli blueprint — az URL-ek változatlanok.
"""
import csv
import io
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta

import openpyxl
from flask import Response, jsonify, make_response, request
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from kreta_db import get_db_connection
from kreta_paths import DB_FILE
from kreta_settings import load_config
from views_common import _tanev_from_request, make_bp, normalize_date

bp = make_bp("exports")

_PDF_FONT_REG = "KretaHU"
_PDF_FONT_BOLD = "KretaHU-Bold"


def _pdf_font_candidates():
    """(regular, bold) jelölt betűkészlet-párok, preferencia-sorrendben."""
    return [
        # Linux (Debian; a Dockerfile a playwright --with-deps / fonts-liberation miatt ezt tartalmazza)
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/freefont/FreeSans.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
        # Windows (fejlesztés)
        ("C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"),
        ("C:\\Windows\\Fonts\\calibri.ttf", "C:\\Windows\\Fonts\\calibrib.ttf"),
        ("C:\\Windows\\Fonts\\segoeui.ttf", "C:\\Windows\\Fonts\\seguisb.ttf"),
    ]


def _register_pdf_fonts():
    """Regisztrál egy ő/ű-t támogató betűkészletet; True ha sikerült."""
    if _PDF_FONT_REG in pdfmetrics.getRegisteredFontNames():
        return True
    for regular, bold in _pdf_font_candidates():
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont(_PDF_FONT_REG, regular))
                pdfmetrics.registerFont(TTFont(_PDF_FONT_BOLD, bold))
                pdfmetrics.registerFontFamily(
                    _PDF_FONT_REG,
                    normal=_PDF_FONT_REG,
                    bold=_PDF_FONT_BOLD,
                    italic=_PDF_FONT_REG,
                    boldItalic=_PDF_FONT_BOLD,
                )
                return True
            except Exception as e:
                print(f"[PDF] A(z) {regular} betűkészlet regisztrálása sikertelen: {e}")
    print("[PDF] FIGYELEM: nem található Unicode betűkészlet — az ő/ű hibás lehet.")
    return False


def _pdf_font():
    return _PDF_FONT_REG if _PDF_FONT_REG in pdfmetrics.getRegisteredFontNames() else "Helvetica"


def _pdf_font_bold():
    return _PDF_FONT_BOLD if _PDF_FONT_BOLD in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"


@bp.route("/api/orarend/export_pdf")
def export_orarend_pdf():
    """Órarend PDF generálása teljesen elkülönített 'Egész napos' sor kezelésével."""
    if not os.path.exists(DB_FILE):
        return "Adatbázis nem található!", 404

    # Magyar ő/ű támogatáshoz Unicode betűkészlet regisztrálása (ha még nincs).
    _register_pdf_fonts()

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "").strip()

    # A frontend a naptárban ÉPPEN MEGJELENÍTETT hét kezdőnapját küldi a 'datum'
    # paraméterben — a PDF ahhoz a héthez készül. Üres/hibás paraméternél az
    # aktuális hét marad (visszafelé kompatibilis viselkedés).
    datum_param = request.args.get("datum", "").strip()
    try:
        hetfo = datetime.strptime(datum_param, "%Y-%m-%d")
    except ValueError:
        hetfo = datetime.now()
    hetfo = hetfo - timedelta(days=hetfo.weekday())
    hetfo_str = hetfo.strftime("%Y-%m-%d")
    vasarnap_str = (hetfo + timedelta(days=6)).strftime("%Y-%m-%d")

    if diak:
        diakok = [diak]
    else:
        cursor.execute("SELECT DISTINCT diak_nev FROM orarend WHERE diak_nev IS NOT NULL AND diak_nev != '' ORDER BY diak_nev")
        diakok = [r["diak_nev"] for r in cursor.fetchall()]

    if not diakok:
        conn.close()
        return "Nincs elérhető órarendi adat!", 404

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1.2*cm,
        leftMargin=1.2*cm,
        topMargin=1.0*cm,
        bottomMargin=1.0*cm
    )

    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'HeaderTitle',
        parent=styles['Heading1'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0d6efd'),
        alignment=0,
        spaceAfter=2,
        fontName=_pdf_font_bold()
    )
    
    subtitle_style = ParagraphStyle(
        'HeaderSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#6c757d'),
        alignment=0,
        spaceAfter=8,
        fontName=_pdf_font()
    )

    cell_time_style = ParagraphStyle(
        'CellTime',
        fontSize=8,
        leading=10,
        alignment=1,
        textColor=colors.HexColor('#333333'),
        fontName=_pdf_font()
    )

    cell_header_style = ParagraphStyle(
        'CellHeader',
        fontSize=10,
        leading=12,
        alignment=1,
        textColor=colors.white,
        fontName=_pdf_font_bold()
    )

    story = []

    days = ["hetfo", "kedd", "szerda", "csutortok", "pentek"]
    day_headers = ["Hétfő", "Kedd", "Szerda", "Csütörtök", "Péntek"]

    def get_subject_bg(tantargy_name):
        if not tantargy_name:
            return colors.HexColor('#f8f9fa')
        t = tantargy_name.lower()
        if any(x in t for x in ["szünet", "tanítási szünet", "ünnepnap", "rendkívüli"]):
            return colors.HexColor('#fff3cd')
        if any(x in t for x in ["matematika", "fizika", "kémia", "biológia", "informatika", "digitális"]):
            return colors.HexColor('#e7f1ff')
        if any(x in t for x in ["magyar", "irodalom", "nyelvtan", "történelem", "angol", "német"]):
            return colors.HexColor('#f0fff4')
        if any(x in t for x in ["testnevelés", "tesi"]):
            return colors.HexColor('#e8f5e9')
        if any(x in t for x in ["ének", "rajz", "vizuális", "technika", "dráma"]):
            return colors.HexColor('#f3e8ff')
        return colors.HexColor('#f8f9fa')

    for idx, d_nev in enumerate(diakok):
        if idx > 0:
            story.append(PageBreak())

        cursor.execute("""
            SELECT * FROM orarend 
            WHERE diak_nev = ? 
              AND (kezdo_idopont >= ? AND kezdo_idopont <= ? OR kezdo_idopont IS NULL OR kezdo_idopont = '')
            ORDER BY kezdo_idopont ASC
        """, (d_nev, hetfo_str, vasarnap_str + "T23:59:59"))
        rows = cursor.fetchall()

        all_day_map = {d: None for d in days}
        time_slots_dict = {}
        parsed_lessons = []
        has_all_day_event = False

        for r in rows:
            kezdo = r["kezdo_idopont"] or ""
            zaro = r["zaro_idopont"] or ""
            nap_raw = (r["nap"] or "").lower()

            day_key = None
            if "hétfő" in nap_raw or "hetfo" in nap_raw: day_key = "hetfo"
            elif "kedd" in nap_raw: day_key = "kedd"
            elif "szerda" in nap_raw: day_key = "szerda"
            elif "csütörtök" in nap_raw or "csutortok" in nap_raw: day_key = "csutortok"
            elif "péntek" in nap_raw or "pentek" in nap_raw: day_key = "pentek"
            
            if not day_key and len(kezdo) >= 10:
                try:
                    dt = datetime.strptime(kezdo[:10], "%Y-%m-%d")
                    w = dt.weekday()
                    if w < 5: day_key = days[w]
                except Exception:
                    pass

            if not day_key:
                continue

            k_time = kezdo.split("T")[1][:5] if "T" in kezdo and len(kezdo) >= 16 else ""
            z_time = zaro.split("T")[1][:5] if "T" in zaro and len(zaro) >= 16 else ""

            is_all_day = not k_time or "T" not in kezdo

            if is_all_day:
                has_all_day_event = True
                all_day_map[day_key] = {
                    "tantargy": r["tantargy"] or "",
                    "tanar": r["tanar"] or "",
                    "terem": r["terem"] or ""
                }
            else:
                slot_str = f"{k_time} - {z_time}" if z_time else k_time
                time_slots_dict[k_time] = slot_str

                parsed_lessons.append({
                    "day_key": day_key,
                    "slot_str": slot_str,
                    "k_time": k_time,
                    "tantargy": r["tantargy"] or "",
                    "tanar": r["tanar"] or "",
                    "terem": r["terem"] or ""
                })

        sorted_k_times = sorted(list(time_slots_dict.keys()))

        schedule_map = {time_slots_dict[kt]: {d: None for d in days} for kt in sorted_k_times}

        for item in parsed_lessons:
            slot = item["slot_str"]
            d_key = item["day_key"]
            if slot in schedule_map:
                schedule_map[slot][d_key] = item

        table_data = []
        header_row = [Paragraph("<b>Óra / Idő</b>", cell_header_style)] + [Paragraph(f"<b>{dh}</b>", cell_header_style) for dh in day_headers]
        table_data.append(header_row)

        table_styles = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]

        current_row_idx = 1

        if has_all_day_event:
            row = [Paragraph("<b>Egész napos</b><br/><font size=6.5 color='#666666'>esemény / szünet</font>", cell_time_style)]
            for d_col_idx, d_key in enumerate(days, start=1):
                cell_data = all_day_map.get(d_key)
                if cell_data:
                    tt = cell_data["tantargy"]
                    cell_html = f"<b><font size=8 color='#d97706'>{tt}</font></b>"
                    bg_c = get_subject_bg(tt)
                    table_styles.append(('BACKGROUND', (d_col_idx, current_row_idx), (d_col_idx, current_row_idx), bg_c))
                    p = Paragraph(cell_html, ParagraphStyle('CellContent', fontSize=8, leading=9.5, alignment=1, fontName=_pdf_font()))
                else:
                    p = Paragraph("<font color='#cccccc'>-</font>", cell_time_style)
                row.append(p)
            
            table_data.append(row)
            current_row_idx += 1

        for lesson_num, kt in enumerate(sorted_k_times, start=1):
            slot_name = time_slots_dict[kt]
            row = []
            time_p = Paragraph(f"<b>{lesson_num}. óra</b><br/><font size=7 color='#666666'>{slot_name}</font>", cell_time_style)
            row.append(time_p)

            for d_col_idx, d_key in enumerate(days, start=1):
                cell_data = schedule_map[slot_name].get(d_key)
                if cell_data:
                    tt = cell_data["tantargy"]
                    tr = cell_data["terem"]
                    tn = cell_data["tanar"]

                    cell_html = f"<b><font size=8 color='#0d6efd'>{tt}</font></b>"
                    if tr or tn:
                        sub_info = []
                        if tr: sub_info.append(f"<b>{tr}</b>")
                        if tn: sub_info.append(tn)
                        cell_html += f"<br/><font size=6.5 color='#555555'>{' • '.join(sub_info)}</font>"

                    bg_c = get_subject_bg(tt)
                    table_styles.append(('BACKGROUND', (d_col_idx, current_row_idx), (d_col_idx, current_row_idx), bg_c))
                    p = Paragraph(cell_html, ParagraphStyle('CellContent', fontSize=8, leading=9.5, alignment=1, fontName=_pdf_font()))
                else:
                    p = Paragraph("<font color='#cccccc'>-</font>", cell_time_style)

                row.append(p)

            table_data.append(row)
            current_row_idx += 1

        col_widths = [3.2*cm] + [4.8*cm]*5
        t = Table(table_data, colWidths=col_widths)
        t.setStyle(TableStyle(table_styles))

        header_p = Paragraph(f"Heti Órarend – {d_nev}", title_style)
        sub_p = Paragraph(f"Aktuális hét: {hetfo_str} – {vasarnap_str} | Generálva: {datetime.now().strftime('%Y.%m.%d. %H:%M')}", subtitle_style)

        story.append(header_p)
        story.append(sub_p)
        story.append(Spacer(1, 0.2*cm))
        story.append(t)

    conn.close()
    doc.build(story)

    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    filename = f"orarend_{diak if diak else 'osszes_gyerek'}.pdf"
    response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


def compute_zsebpenz_statisztika(diak="", kezdo_datum="", zaro_datum="", tanev_szuro=None):
    """A zsebpénz/statisztika közös számítása (a `/api/statisztika` és az Excel export).

    Visszaadja a teljes statisztika-diktet (jegyeloszlás, súlyozott átlag,
    tételes lista, összegek, kifizetettség), hiányzó DB esetén `None`.
    """
    config = load_config()
    global_enable = config.get("ENABLE_REWARDS", True)

    # A statisztika akkor is működik, ha a zsebpénz modul ki van kapcsolva:
    # ilyenkor csak a pénz-összegek maradnak 0-n, és a felület jelzi a tényt.
    if not os.path.exists(DB_FILE):
        return None

    student_enable = True
    students = config.get("STUDENTS", [])
    for s in students:
        if s.get("diak_nev") == diak:
            student_enable = s.get("enable_rewards", True)
            break

    rewards_enabled = bool(global_enable) and bool(student_enable)

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

    conn = get_db_connection()
    cursor = conn.cursor()

    # JEGYEK LEKÉRDEZÉSE ÉS TÉTELES LISTÁJA
    jegy_query = "SELECT id, diak_nev, tantargy, ertek, szam_ertek, bej_datum, mod, tema FROM esemenyek WHERE esemeny_tipus = 'Értékelés'"
    params = []
    if diak:
        jegy_query += " AND diak_nev = ?"
        params.append(diak)
    if tanev_szuro:
        jegy_query += " AND tanev = ?"
        params.append(tanev_szuro)

    cursor.execute(jegy_query, params)
    jegy_rows = cursor.fetchall()

    # A súlyszázalék csak az API-s szinkronból van meg; régi DB-ben lehet, hogy
    # még nincs oszlop, ezért a SELECT *-ot nem használjuk, hanem külön kérdezzük.
    # FONTOS: a szűrőfeltételeknek és a paramétereknek pontosan egyezniük kell
    # (a diák + tanév szűrő itt is!), különben a lekérdezés elszáll, és a
    # súlyozott átlag csendben elveszne (KRÉ-14 audit, F1).
    jegy_suly = {}
    try:
        suly_query = ("SELECT id, suly_szazalek FROM esemenyek "
                      "WHERE esemeny_tipus = 'Értékelés'")
        suly_params = []
        if diak:
            suly_query += " AND diak_nev = ?"
            suly_params.append(diak)
        if tanev_szuro:
            suly_query += " AND tanev = ?"
            suly_params.append(tanev_szuro)
        cursor.execute(suly_query, suly_params)
        jegy_suly = {row["id"]: (row["suly_szazalek"] or 0) for row in cursor.fetchall()}
    except sqlite3.Error as exc:
        # Várt eset: régi DB, ahol még nincs suly_szazalek oszlop. Minden más
        # hiba látszódjon a naplóban (ne nyelje el csendben).
        if "suly_szazalek" not in str(exc):
            print(f"[Statisztika] A súlyadatok nem olvashatók: {exc}")
        jegy_suly = {}

    jegy_counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
    jegy_sum = 0
    jegy_total_count = 0
    # Súlyozott átlaghoz (a KRÉTA SulySzazalekErteke / webes "Súly: N%" mezője).
    suly_sum = 0
    sulyozott_sum = 0.0
    sulyozott_db = 0
    teteles_lista = []

    for r in jegy_rows:
        norm_d = normalize_date(r["bej_datum"])
        if norm_d:
            if kezdo_datum and norm_d < kezdo_datum:
                continue
            if zaro_datum and norm_d > zaro_datum:
                continue

        val = r["szam_ertek"]
        if val in jegy_counts:
            jegy_counts[val] += 1
            jegy_sum += val
            jegy_total_count += 1

            suly = jegy_suly.get(r["id"], 0)
            if suly > 0:
                suly_sum += suly
                sulyozott_sum += val * suly
                sulyozott_db += 1

            jutalom = rewards.get(f"jegy_{val}", 0) if rewards_enabled else 0
            reszletek = f"{r['mod'] or ''} {r['tema'] or ''}".strip()
            if suly:
                reszletek = f"{reszletek} ({suly}%)".strip()
            teteles_lista.append({
                "datum": r["bej_datum"],
                "diak_nev": r["diak_nev"] or "",
                "tipus": "Értékelés",
                "megnevezes": f"{r['tantargy']} - {r['ertek']}",
                "reszletek": reszletek,
                "osszeg": jutalom
            })

    # Tanulmányi átlag: ha van súlyszázalék, a KRÉTA logikája szerint súlyozva
    # (súlyozott összeg / súlyösszeg); a 0%-os súlyú jegy nem számít bele. Ha
    # egyetlen jegynek sincs súlya (régi adat / Playwright nélküli súly), akkor
    # a hagyományos egyszerű átlagot adjuk.
    atlag_egyszeru = round(jegy_sum / jegy_total_count, 2) if jegy_total_count > 0 else 0.0
    atlag_sulyozott = round(sulyozott_sum / suly_sum, 2) if suly_sum > 0 else None
    atlag = atlag_sulyozott if atlag_sulyozott is not None else atlag_egyszeru

    # FELJEGYZÉSEK LEKÉRDEZÉSE ÉS TÉTELES LISTÁJA
    felj_query = "SELECT id, diak_nev, bej_datum, tipus, cim, tartalom FROM esemenyek WHERE esemeny_tipus = 'Feljegyzés'"
    f_params = []
    if diak:
        felj_query += " AND diak_nev = ?"
        f_params.append(diak)
    if tanev_szuro:
        felj_query += " AND tanev = ?"
        f_params.append(tanev_szuro)

    cursor.execute(felj_query, f_params)
    felj_rows = cursor.fetchall()

    counts = {
        "dicseret": 0,
        "megrovas": 0,
        "lecke_hiany": 0,
        "felszereles_hiany": 0
    }

    cat_names = {
        "dicseret": "Dicséret",
        "megrovas": "Intő / Megrovás",
        "lecke_hiany": "Lecke hiány",
        "felszereles_hiany": "Felszerelés hiány"
    }

    for r in felj_rows:
        norm_d = normalize_date(r["bej_datum"])
        if norm_d:
            if kezdo_datum and norm_d < kezdo_datum:
                continue
            if zaro_datum and norm_d > zaro_datum:
                continue

        text = f"{r['cim'] or ''} {r['tartalom'] or ''}".lower()

        for cat, kw_list in keywords.items():
            if any(kw in text for kw in kw_list):
                counts[cat] += 1
                jutalom = rewards.get(cat, 0) if rewards_enabled else 0
                teteles_lista.append({
                    "datum": r["bej_datum"],
                    "diak_nev": r["diak_nev"] or "",
                    "tipus": "Feljegyzés",
                    "megnevezes": cat_names.get(cat, "Feljegyzés"),
                    "reszletek": f"{r['cim'] or ''} {r['tartalom'] or ''}".strip(),
                    "osszeg": jutalom
                })

    kifizetve = False
    if diak and kezdo_datum and zaro_datum:
        cursor.execute("""
            SELECT kifizetve FROM kifizetesek 
            WHERE diak_nev = ? AND kezdo_datum = ? AND zaro_datum = ?
        """, (diak, kezdo_datum, zaro_datum))
        k_row = cursor.fetchone()
        if k_row:
            kifizetve = bool(k_row["kifizetve"])

    conn.close()

    teteles_lista.sort(key=lambda x: x["datum"], reverse=True)

    if rewards_enabled:
        jegy_osszeg = (
            jegy_counts[5] * rewards.get("jegy_5", 0) +
            jegy_counts[4] * rewards.get("jegy_4", 0) +
            jegy_counts[3] * rewards.get("jegy_3", 0) +
            jegy_counts[2] * rewards.get("jegy_2", 0) +
            jegy_counts[1] * rewards.get("jegy_1", 0)
        )

        feljegyzes_osszeg = (
            counts["dicseret"] * rewards.get("dicseret", 0) +
            counts["megrovas"] * rewards.get("megrovas", 0) +
            counts["lecke_hiany"] * rewards.get("lecke_hiany", 0) +
            counts["felszereles_hiany"] * rewards.get("felszereles_hiany", 0)
        )
    else:
        jegy_osszeg = 0
        feljegyzes_osszeg = 0

    vegosszeg = jegy_osszeg + feljegyzes_osszeg

    return {
        "enabled": True,
        "rewards_enabled": rewards_enabled,
        "jegy_counts": jegy_counts,
        "atlag": atlag,
        "atlag_egyszeru": atlag_egyszeru,
        "atlag_sulyozott": atlag_sulyozott,
        "sulyozott_db": sulyozott_db,
        "jegy_total_count": jegy_total_count,
        "counts": counts,
        "rewards": rewards,
        "jegy_osszeg": jegy_osszeg,
        "feljegyzes_osszeg": feljegyzes_osszeg,
        "vegosszeg": vegosszeg,
        "kifizetve": kifizetve,
        "teteles_lista": teteles_lista
    }


def _load_kifizetesek_rows(diak="", tanev_szuro=None):
    """A kifizetés-elszámolások sorai és a tételes zsebpénz-események (exportokhoz)."""
    kif_rows = []
    teteles_rows = []
    if not os.path.exists(DB_FILE):
        return kif_rows, teteles_rows

    config = load_config()
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
    cat_names = {
        "dicseret": "Dicséret",
        "megrovas": "Intő / Megrovás",
        "lecke_hiany": "Lecke hiány",
        "felszereles_hiany": "Felszerelés hiány"
    }

    conn = get_db_connection()
    try:
        query = ("SELECT diak_nev, kezdo_datum, zaro_datum, osszeg, kifizetve, updated_at"
                 " FROM kifizetesek WHERE 1=1")
        params = []
        if diak:
            query += " AND diak_nev = ?"
            params.append(diak)
        if tanev_szuro:
            query += " AND tanev = ?"
            params.append(tanev_szuro)
        query += " ORDER BY kezdo_datum, diak_nev"
        kif_rows = conn.execute(query, params).fetchall()

        # Tételes zsebpénz-tételek (jegyek + feljegyzések).
        j_query = ("SELECT diak_nev, tantargy, ertek, szam_ertek, bej_datum, mod, tema"
                   " FROM esemenyek WHERE esemeny_tipus = 'Értékelés'")
        j_params = []
        if diak:
            j_query += " AND diak_nev = ?"
            j_params.append(diak)
        if tanev_szuro:
            j_query += " AND tanev = ?"
            j_params.append(tanev_szuro)
        for r in conn.execute(j_query, j_params).fetchall():
            val = r["szam_ertek"]
            if val not in (1, 2, 3, 4, 5):
                continue
            jutalom = rewards.get(f"jegy_{val}", 0)
            megj = f"{r['mod'] or ''} {r['tema'] or ''}".strip()
            teteles_rows.append({
                "datum": r["bej_datum"] or "",
                "diak_nev": r["diak_nev"] or "",
                "osszeg": jutalom,
                "kategoria": f"{r['tantargy'] or 'Jegy'} – {r['ertek'] or val}",
                "megjegyzes": megj,
            })

        f_query = ("SELECT diak_nev, bej_datum, cim, tartalom"
                   " FROM esemenyek WHERE esemeny_tipus = 'Feljegyzés'")
        f_params = []
        if diak:
            f_query += " AND diak_nev = ?"
            f_params.append(diak)
        if tanev_szuro:
            f_query += " AND tanev = ?"
            f_params.append(tanev_szuro)
        for r in conn.execute(f_query, f_params).fetchall():
            text = f"{r['cim'] or ''} {r['tartalom'] or ''}".lower()
            for cat, kw_list in keywords.items():
                if any(kw in text for kw in kw_list):
                    teteles_rows.append({
                        "datum": r["bej_datum"] or "",
                        "diak_nev": r["diak_nev"] or "",
                        "osszeg": rewards.get(cat, 0),
                        "kategoria": cat_names.get(cat, "Feljegyzés"),
                        "megjegyzes": f"{r['cim'] or ''} {r['tartalom'] or ''}".strip(),
                    })
        teteles_rows.sort(key=lambda x: (x["datum"], x["diak_nev"]), reverse=True)
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return kif_rows, teteles_rows


@bp.route("/api/kifizetesek/export.xlsx")
def api_kifizetesek_xlsx():
    """Az egyenleg tételeinek Excel (.xlsx) exportja (Kaneo #11 / #77).

    A kiválasztott gyermek **egyenlegének összetétele** — miből áll össze a
    kifizetendő összeg — három munkalapon:

    1. **Elszámolás** — összegzés: időszak/tanév, tételek összege, **ebből
       rendezve**, **fennálló egyenleg**, a kifizetett időszakok összege, átlag.
    2. **Tételes zsebpénz** — az egyenleg tételei (dátum, gyerek, típus,
       megnevezés, részletek, összeg) **+ „Rendezve” jelölés** (a tétel az
       időszakában kifizetett elszámolásba esik-e), a rendezés időszakával és
       dátumával, a végén „Összesen” sorral. A lista ugyanaz, mint a felületen
       (`/api/statisztika`).
    3. **Kifizetések** — az időszaki elszámolások (kifizetve állapot, összeg).

    Paraméterek: `diak`, `kezdo_datum`, `zaro_datum`, `tanev`.
    - `kezdo_datum`/`zaro_datum` nélkül a **teljes (szűrt) előzmény** megy:
      `tanev=<tanév>` = teljes tanév, `tanev=all` = minden tanév.
    """
    diak = request.args.get("diak", "")
    kezdo_datum = (request.args.get("kezdo_datum") or "").strip()
    zaro_datum = (request.args.get("zaro_datum") or "").strip()
    tanev_szuro = _tanev_from_request()

    stat = compute_zsebpenz_statisztika(
        diak=diak,
        kezdo_datum=kezdo_datum,
        zaro_datum=zaro_datum,
        tanev_szuro=tanev_szuro,
    ) or {}
    teteles_lista = stat.get("teteles_lista", [])
    kif_rows, _ = _load_kifizetesek_rows(diak=diak, tanev_szuro=tanev_szuro)

    # Kifizetett (pénzügyileg rendezett) időszakok — a tételek jelöléséhez.
    fizetett_idoszakok = [r for r in kif_rows if r["kifizetve"]]

    def _rendezo_idoszak(tetel):
        """Melyik kifizetett elszámolás fedi le a tétel dátumát (ha van ilyen)."""
        iso = normalize_date(tetel.get("datum") or "")
        if not iso:
            return None
        for p in fizetett_idoszakok:
            if tetel.get("diak_nev") and p["diak_nev"] and p["diak_nev"] != tetel["diak_nev"]:
                continue
            kezdo = p["kezdo_datum"] or ""
            zaro = p["zaro_datum"] or ""
            if kezdo and iso < kezdo:
                continue
            if zaro and iso > zaro:
                continue
            return p
        return None

    wb = openpyxl.Workbook()
    header_fill = PatternFill(start_color="0D6EFD", end_color="0D6EFD", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    label_font = Font(bold=True)
    total_fill = PatternFill(start_color="EEF3FB", end_color="EEF3FB", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="D0D7DE"),
        right=Side(style="thin", color="D0D7DE"),
        top=Side(style="thin", color="D0D7DE"),
        bottom=Side(style="thin", color="D0D7DE"),
    )

    def _style_sheet(ws, headers, widths):
        ws.append(headers)
        for col_idx, width in enumerate(widths, start=1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            ws.column_dimensions[get_column_letter(col_idx)].width = width
        ws.freeze_panes = "A2"

    # 1. munkalap: Elszámolás (az egyenleg összetétele)
    ws0 = wb.active
    ws0.title = "Elszámolás"
    ws0.append(["Megnevezés", "Érték"])
    for col_idx, width in enumerate([34, 30], start=1):
        cell = ws0.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws0.column_dimensions[get_column_letter(col_idx)].width = width
    ws0.freeze_panes = "A2"

    idoszak = f"{kezdo_datum or 'kezdet'} – {zaro_datum or 'mai nap'}"
    if not kezdo_datum and not zaro_datum:
        idoszak = f"teljes időszak ({tanev_szuro or 'minden tanév'})"

    # Tétel-szintű rendezettség (a kifizetett elszámolási időszakok alapján).
    tetelek = []
    for t in teteles_lista:
        ertek = int(t.get("osszeg") or 0)
        p = _rendezo_idoszak(t)
        tetelek.append({
            "datum": t.get("datum") or "",
            "diak_nev": t.get("diak_nev") or "",
            "tipus": t.get("tipus") or "",
            "megnevezes": t.get("megnevezes") or "",
            "reszletek": t.get("reszletek") or "",
            "osszeg": ertek,
            "rendezo": p,
        })

    ossz = sum(t["osszeg"] for t in tetelek)
    rendezett = sum(t["osszeg"] for t in tetelek if t["rendezo"])
    fennallo = ossz - rendezett
    kifizetett_osszeg = sum(int(r["osszeg"] or 0) for r in fizetett_idoszakok)

    stat_sorok = [
        ("Diák", diak or "Összes gyerek"),
        ("Időszak", idoszak),
        ("Tanév", tanev_szuro or "Összes tanév"),
        ("Tételek száma", len(tetelek)),
        ("Jegyek összege (Ft)", int(stat.get("jegy_osszeg", 0) or 0)),
        ("Feljegyzések összege (Ft)", int(stat.get("feljegyzes_osszeg", 0) or 0)),
        ("Egyenleg (Ft)", ossz),
        ("Ebből rendezve (Ft)", rendezett),
        ("Fennálló egyenleg (Ft)", fennallo),
        ("Rögzített kifizetések összege (Ft)", kifizetett_osszeg),
        ("Rögzített kifizetések száma", len(fizetett_idoszakok)),
        ("Tanulmányi átlag", stat.get("atlag") if stat.get("atlag") is not None else "-"),
        ("Jegyek száma", stat.get("jegy_total_count", 0) or 0),
        ("Zsebpénz modul", "be" if stat.get("rewards_enabled") else "kikapcsolva"),
    ]
    for cimke, ertek in stat_sorok:
        ws0.append([cimke, ertek])
    kiemelt_sorok = []
    for row in ws0.iter_rows(min_row=2):
        row[0].font = label_font
        for cell in row:
            cell.border = thin_border
        if row[0].value in ("Egyenleg (Ft)", "Fennálló egyenleg (Ft)"):
            kiemelt_sorok.append(row[0].row)
        if isinstance(row[1].value, int) and str(row[0].value).endswith("(Ft)"):
            row[1].number_format = "#,##0"
    for sor_idx in kiemelt_sorok:
        for cell in ws0[sor_idx]:
            cell.font = Font(bold=True, size=12)
            cell.fill = total_fill

    # 2. munkalap: Tételes zsebpénz (az egyenleg tételei + rendezettség)
    ws1 = wb.create_sheet(title="Tételes zsebpénz")
    _style_sheet(
        ws1,
        ["Dátum", "Gyerek", "Típus", "Megnevezés", "Részletek", "Összeg (Ft)",
         "Rendezve", "Rendezés időszaka", "Rendezés dátuma"],
        [14, 20, 14, 30, 45, 14, 11, 26, 20],
    )
    for t in tetelek:
        p = t["rendezo"]
        ws1.append([
            t["datum"],
            t["diak_nev"],
            t["tipus"],
            t["megnevezes"],
            t["reszletek"],
            t["osszeg"],
            "igen" if p else "nem",
            f"{p['kezdo_datum']} – {p['zaro_datum']}" if p else "",
            (p["updated_at"] or "") if p else "",
        ])
    if tetelek:
        ws1.append(["", "", "", "", "Összesen", ossz, "", "", ""])
        for cell in ws1[ws1.max_row]:
            cell.font = label_font
            cell.fill = total_fill
        ws1.append(["", "", "", "", "Ebből rendezve", rendezett, "", "", ""])
        ws1.append(["", "", "", "", "Fennálló egyenleg", fennallo, "", "", ""])
        for cell in ws1[ws1.max_row]:
            cell.font = label_font
            cell.fill = total_fill

    # 3. munkalap: Kifizetések (időszaki elszámolások)
    ws2 = wb.create_sheet(title="Kifizetések")
    _style_sheet(
        ws2,
        ["Dátum", "Gyerek", "Összeg (Ft)", "Kategória", "Megjegyzés",
         "Kifizetve", "Kezdő dátum", "Záró dátum", "Frissítve"],
        [14, 22, 14, 18, 28, 12, 14, 14, 20],
    )
    for r in kif_rows:
        kezdo = r["kezdo_datum"] or ""
        zaro = r["zaro_datum"] or ""
        osszeg = int(r["osszeg"]) if r["osszeg"] is not None else 0
        ws2.append([
            zaro or kezdo,
            r["diak_nev"] or "",
            osszeg,
            "Zsebpénz elszámolás",
            f"{kezdo} – {zaro} ({'kifizetve' if r['kifizetve'] else 'kifizetetlen'})",
            "igen" if r["kifizetve"] else "nem",
            kezdo,
            zaro,
            r["updated_at"] or "",
        ])

    for ws, penz_col in ((ws1, 6), (ws2, 3)):
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.border = thin_border
                if cell.column == penz_col and isinstance(cell.value, int):
                    cell.number_format = "#,##0"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    suffix = re.sub(r"[^A-Za-z0-9._-]+", "_", diak)[:40] if diak else "osszes"
    if kezdo_datum or zaro_datum:
        suffix += "_" + re.sub(r"[^0-9]", "", kezdo_datum or "")
        suffix += "_" + re.sub(r"[^0-9]", "", zaro_datum or "")
    response = Response(
        buf.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response.headers["Content-Disposition"] = (
        f"attachment; filename=\"zsebpenz_{suffix}.xlsx\""
    )
    return response


@bp.route("/api/kifizetesek/export.csv")
def api_kifizetesek_csv():
    """Zsebpénz-elszámolások CSV exportja (visszafelé kompatibilis végpont, Kaneo #11)."""
    if not os.path.exists(DB_FILE):
        return Response("\ufeffNincs adatbázis.\n", mimetype="text/csv; charset=utf-8")
    diak = request.args.get("diak", "")
    kif_rows, _ = _load_kifizetesek_rows(diak=diak)

    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(["diak_nev", "kezdo_datum", "zaro_datum", "osszeg",
                     "kifizetve", "kategoria", "megjegyzes", "updated_at"])
    for row in kif_rows:
        writer.writerow([
            row["diak_nev"] or "",
            row["kezdo_datum"] or "",
            row["zaro_datum"] or "",
            row["osszeg"] if row["osszeg"] is not None else 0,
            "igen" if row["kifizetve"] else "nem",
            "zsebpenz",
            "",
            row["updated_at"] or "",
        ])
    data = "\ufeff" + out.getvalue()
    response = Response(data, mimetype="text/csv; charset=utf-8")
    suffix = re.sub(r"[^A-Za-z0-9._-]+", "_", diak)[:40] if diak else "osszes"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=\"kifizetesek_{suffix}.csv\""
    )
    return response
