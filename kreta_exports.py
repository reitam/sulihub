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
from datetime import date, datetime, timedelta

import openpyxl
from flask import Response, jsonify, make_response, request
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.graphics.shapes import Circle, Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, Image as RLImage, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

import kreta_tanev
from kreta_db import get_db_connection
from kreta_paths import APP_DIR, DB_FILE
from kreta_settings import load_config
from views_common import _tanev_from_request, hianyzas_osszesito, make_bp, normalize_date

bp = make_bp("exports")

_PDF_FONT_REG = "KretaHU"
_PDF_FONT_BOLD = "KretaHU-Bold"
_PDF_SERIF_REG = "KretaHU-Serif"
_PDF_SERIF_BOLD = "KretaHU-Serif-Bold"


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


def _pdf_serif_candidates():
    """A dísz-bizonyítvány jellegű címekhez használt (regular, bold) talpas betűk."""
    return [
        ("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
        ("/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf"),
        ("C:\\Windows\\Fonts\\times.ttf", "C:\\Windows\\Fonts\\timesbd.ttf"),
        ("C:\\Windows\\Fonts\\georgia.ttf", "C:\\Windows\\Fonts\\georgiab.ttf"),
    ]


def _register_font_pair(reg_name, bold_name, candidates):
    """Egy (regular, bold) pár regisztrálása az első elérhető fájlpárból."""
    for regular, bold in candidates:
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont(reg_name, regular))
                pdfmetrics.registerFont(TTFont(bold_name, bold))
                pdfmetrics.registerFontFamily(
                    reg_name,
                    normal=reg_name,
                    bold=bold_name,
                    italic=reg_name,
                    boldItalic=bold_name,
                )
                return True
            except Exception as e:
                print(f"[PDF] A(z) {regular} betűkészlet regisztrálása sikertelen: {e}")
    return False


def _register_pdf_fonts():
    """Regisztrál egy ő/ű-t támogató betűkészletet; True ha sikerült."""
    van_sans = _PDF_FONT_REG in pdfmetrics.getRegisteredFontNames()
    van_serif = _PDF_SERIF_REG in pdfmetrics.getRegisteredFontNames()
    if van_sans and van_serif:
        return True
    if not van_sans:
        _register_font_pair(_PDF_FONT_REG, _PDF_FONT_BOLD, _pdf_font_candidates())
    if not van_serif:
        # A talpas betű csak a díszítéshez kell; ha nincs, a sans lesz a helyette.
        _register_font_pair(_PDF_SERIF_REG, _PDF_SERIF_BOLD, _pdf_serif_candidates())
    if _PDF_FONT_REG not in pdfmetrics.getRegisteredFontNames():
        print("[PDF] FIGYELEM: nem található Unicode betűkészlet — az ő/ű hibás lehet.")
        return False
    return True


def _pdf_font():
    return _PDF_FONT_REG if _PDF_FONT_REG in pdfmetrics.getRegisteredFontNames() else "Helvetica"


def _pdf_font_bold():
    return _PDF_FONT_BOLD if _PDF_FONT_BOLD in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"


def _pdf_serif():
    return _PDF_SERIF_REG if _PDF_SERIF_REG in pdfmetrics.getRegisteredFontNames() else _pdf_font()


def _pdf_serif_bold():
    return (_PDF_SERIF_BOLD if _PDF_SERIF_BOLD in pdfmetrics.getRegisteredFontNames()
            else _pdf_font_bold())


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


# ==============================================================================
# Tanulmányi Excel exportok (Kaneo #83)
# ==============================================================================
def _xlsx_fejlec(ws, fejlecek, szelessegek):
    """Fejlécsor + oszlopszélességek + fagyasztás (a zsebpénz-export stílusában)."""
    header_fill = PatternFill(start_color="0D6EFD", end_color="0D6EFD", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    ws.append(fejlecek)
    for idx, width in enumerate(szelessegek, start=1):
        cell = ws.cell(row=1, column=idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"


def _xlsx_valasz(wb, fajlnev):
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = Response(
        buf.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response.headers["Content-Disposition"] = f"attachment; filename=\"{fajlnev}\""
    return response


def _export_szurok():
    """Közös szűrők: diák, tanév, kezdo_datum/zaro_datum (ISO-ra normalizálva)."""
    diak = (request.args.get("diak") or "").strip()
    tanev = _tanev_from_request()
    kezdo = normalize_date(request.args.get("kezdo_datum") or "") or ""
    zaro = normalize_date(request.args.get("zaro_datum") or "") or ""
    return diak, tanev, kezdo, zaro


@bp.route("/api/esemenyek/export.xlsx")
def api_esemenyek_xlsx():
    """Jegyek / feljegyzések / házik Excel exportja (Kaneo #83).

    Szűrők: `diak`, `tanev`, `kezdo_datum`, `zaro_datum` (a bejegyzés dátumára).
    A három munkalap: **Jegyek**, **Feljegyzések**, **Házi feladatok**
    (a bejelentett számonkérésekkel együtt).
    """
    if not os.path.exists(DB_FILE):
        return jsonify({"error": "Nincs adatbázis."}), 404

    diak, tanev, kezdo, zaro = _export_szurok()
    tipus_szuro = (request.args.get("tipus") or "").strip()
    tantargy_szuro = (request.args.get("tantargy") or "").strip()
    status_szuro = (request.args.get("status") or "").strip()
    hat_kezdo = normalize_date(request.args.get("hatarido_kezdo") or "") or ""
    hat_zaro = normalize_date(request.args.get("hatarido_zaro") or "") or ""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = ("SELECT diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
             " suly_szazalek, mod, tipus, tema, cim, tartalom, ertekelo, bej_datum,"
             " hatarido, kesz, tanev FROM esemenyek WHERE 1=1")
    params = []
    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    if tanev:
        query += " AND tanev = ?"
        params.append(tanev)
    if tipus_szuro:
        query += " AND esemeny_tipus = ?"
        params.append(tipus_szuro)
    if tantargy_szuro:
        query += " AND tantargy = ?"
        params.append(tantargy_szuro)
    query += " ORDER BY bej_datum, diak_nev, tantargy"
    try:
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
    except sqlite3.Error as exc:
        conn.close()
        print(f"[Export] események: {exc}")
        return jsonify({"error": "Az adatok nem olvashatók."}), 500
    conn.close()

    mai = date.today().isoformat()

    def datum_benne(ertek):
        if not ertek:
            return True
        d = normalize_date(ertek)
        if not d:
            return True
        if kezdo and d < kezdo:
            return False
        if zaro and d > zaro:
            return False
        return True

    def lathato(r):
        if not datum_benne(r.get("bej_datum")):
            return False
        hat = normalize_date(r.get("hatarido") or "")
        if status_szuro:
            if not hat:
                return False
            if status_szuro == "aktiv" and hat < mai:
                return False
            if status_szuro == "lejart" and hat >= mai:
                return False
        if hat_kezdo or hat_zaro:
            if not hat:
                return False
            if hat_kezdo and hat < hat_kezdo:
                return False
            if hat_zaro and hat > hat_zaro:
                return False
        return True

    rows = [r for r in rows if lathato(r)]

    wb = openpyxl.Workbook()
    ws_lista = wb.active
    ws_lista.title = "Szűrt lista"
    _xlsx_fejlec(ws_lista, ["Diák", "Típus", "Tantárgy", "Érték / Mód",
                            "Bejegyzés dátuma", "Határidő", "Értékelő / Tanár",
                            "Részletek", "Tanév"],
                 [22, 24, 20, 18, 17, 17, 22, 50, 12])
    for r in rows:
        ertek = r.get("ertek") or ""
        if r.get("mod") and r.get("mod") != "-":
            ertek = (ertek + f" ({r['mod']})").strip()
        if int(r.get("suly_szazalek") or 0) > 0 and r.get("esemeny_tipus") == "Értékelés":
            ertek = (ertek + f" - {r['suly_szazalek']}%").strip()
        reszletek = " | ".join(x for x in (r.get("tema"), r.get("cim"),
                                           r.get("tartalom")) if x and x != "-")
        ws_lista.append([
            r.get("diak_nev") or "", r.get("esemeny_tipus") or "",
            r.get("tantargy") or "", ertek, r.get("bej_datum") or "",
            r.get("hatarido") or "", r.get("ertekelo") or "",
            reszletek, r.get("tanev") or "",
        ])

    ws_jegy = wb.create_sheet("Jegyek")
    _xlsx_fejlec(ws_jegy, ["Diák", "Tantárgy", "Jegy", "Súly (%)", "Mód", "Téma",
                           "Tanár", "Bejegyzés dátuma", "Tanév"],
                 [22, 22, 14, 10, 18, 30, 22, 18, 12])
    ws_fel = wb.create_sheet("Feljegyzések")
    _xlsx_fejlec(ws_fel, ["Diák", "Típus", "Téma", "Leírás", "Tanár",
                          "Bejegyzés dátuma", "Tanév"],
                 [22, 26, 30, 46, 22, 18, 12])
    ws_hazi = wb.create_sheet("Házi feladatok")
    _xlsx_fejlec(ws_hazi, ["Diák", "Típus", "Tantárgy", "Téma / Cím", "Bejegyzés",
                           "Határidő", "Állapot", "Tanár", "Tanév"],
                 [22, 24, 20, 34, 16, 16, 14, 22, 12])

    for r in rows:
        tipus = r.get("esemeny_tipus") or ""
        if tipus == "Értékelés":
            ws_jegy.append([
                r.get("diak_nev") or "", r.get("tantargy") or "",
                r.get("ertek") or "", r.get("suly_szazalek") or 0,
                r.get("mod") or "", r.get("tema") or "",
                r.get("ertekelo") or "", r.get("bej_datum") or "",
                r.get("tanev") or "",
            ])
        elif tipus == "Feljegyzés":
            ws_fel.append([
                r.get("diak_nev") or "", r.get("mod") or r.get("tipus") or "Feljegyzés",
                r.get("tema") or "", r.get("tartalom") or r.get("cim") or "",
                r.get("ertekelo") or "", r.get("bej_datum") or "",
                r.get("tanev") or "",
            ])
        elif tipus in ("Házi feladat", "Bejelentett számonkérés"):
            if tipus == "Házi feladat":
                allapot = "Elkészítve" if int(r.get("kesz") or 0) == 1 else "Aktív"
            else:
                allapot = "-"
            ws_hazi.append([
                r.get("diak_nev") or "", tipus, r.get("tantargy") or "",
                r.get("tema") or r.get("cim") or "", r.get("bej_datum") or "",
                r.get("hatarido") or "", allapot, r.get("ertekelo") or "",
                r.get("tanev") or "",
            ])

    suffix = re.sub(r"[^A-Za-z0-9._-]+", "_", diak)[:40] if diak else "osszes"
    if kezdo or zaro:
        suffix += "_" + re.sub(r"[^0-9]", "", kezdo)
        suffix += "_" + re.sub(r"[^0-9]", "", zaro)
    return _xlsx_valasz(wb, f"esemenyek_{suffix}.xlsx")


@bp.route("/api/hianyzasok/export.xlsx")
def api_hianyzasok_xlsx():
    """Hiányzások és igazolások Excel exportja (Kaneo #83).

    Szűrők: `diak`, `tanev`, `kezdo_datum`, `zaro_datum` (a hiányzás dátumára;
    az igazolásoknál az időszakkal átfedő igazolások).
    """
    if not os.path.exists(DB_FILE):
        return jsonify({"error": "Nincs adatbázis."}), 404

    diak, tanev, kezdo, zaro = _export_szurok()
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM hianyzasok WHERE 1=1"
    params = []
    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    if tanev:
        query += " AND tanev = ?"
        params.append(tanev)
    query += " ORDER BY mulasztas_datum, ora_sorszam"
    try:
        cursor.execute(query, params)
        hianyzasok = [dict(r) for r in cursor.fetchall()]
    except sqlite3.Error as exc:
        conn.close()
        print(f"[Export] hiányzások: {exc}")
        return jsonify({"error": "Az adatok nem olvashatók."}), 500

    query = "SELECT * FROM igazolasok WHERE 1=1"
    params = []
    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    if tanev:
        query += " AND tanev = ?"
        params.append(tanev)
    query += " ORDER BY kezdete, diak_nev"
    try:
        cursor.execute(query, params)
        igazolasok = [dict(r) for r in cursor.fetchall()]
    except sqlite3.Error as exc:
        conn.close()
        print(f"[Export] igazolások: {exc}")
        return jsonify({"error": "Az adatok nem olvashatók."}), 500
    conn.close()

    def datum_benne(ertek):
        if not ertek:
            return True
        d = normalize_date(ertek)
        if not d:
            return True
        if kezdo and d < kezdo:
            return False
        if zaro and d > zaro:
            return False
        return True

    hianyzasok = [r for r in hianyzasok if datum_benne(r.get("mulasztas_datum"))]
    if kezdo or zaro:
        def atfed(ig):
            k = normalize_date(ig.get("kezdete") or "")
            v = normalize_date(ig.get("vege") or "") or k
            if not k:
                return True
            if zaro and k > zaro:
                return False
            if kezdo and v and v < kezdo:
                return False
            return True
        igazolasok = [r for r in igazolasok if atfed(r)]

    wb = openpyxl.Workbook()
    ws_h = wb.active
    ws_h.title = "Hiányzások"
    _xlsx_fejlec(ws_h, ["Diák", "Dátum", "Óra", "Tantárgy", "Téma", "Tanár",
                        "Típus", "Igazolt", "Késés (perc)", "Tanév"],
                 [22, 14, 8, 20, 34, 22, 16, 10, 14, 12])
    for r in hianyzasok:
        ws_h.append([
            r.get("diak_nev") or "",
            normalize_date(r.get("mulasztas_datum")) or r.get("mulasztas_datum") or "",
            r.get("ora_sorszam") or 0,
            r.get("tantargy") or "", r.get("tema") or "", r.get("tanar") or "",
            r.get("mulasztas_tipus") or "",
            "Igen" if int(r.get("igazolt") or 0) == 1 else "Nem",
            r.get("perc") or 0, r.get("tanev") or "",
        ])
    ws_i = wb.create_sheet("Igazolások")
    _xlsx_fejlec(ws_i, ["Diák", "Kezdete", "Vége", "Típus", "Megjegyzés", "Tanév"],
                 [22, 14, 14, 30, 46, 12])
    for r in igazolasok:
        ws_i.append([
            r.get("diak_nev") or "",
            normalize_date(r.get("kezdete")) or r.get("kezdete") or "",
            normalize_date(r.get("vege")) or r.get("vege") or "",
            r.get("igazolas_tipus") or "", r.get("megjegyzes") or "",
            r.get("tanev") or "",
        ])

    suffix = re.sub(r"[^A-Za-z0-9._-]+", "_", diak)[:40] if diak else "osszes"
    if kezdo or zaro:
        suffix += "_" + re.sub(r"[^0-9]", "", kezdo)
        suffix += "_" + re.sub(r"[^0-9]", "", zaro)
    return _xlsx_valasz(wb, f"hianyzasok_{suffix}.xlsx")


# ==============================================================================
# Félévi / év végi aktuális bizonyítvány PDF (Kaneo #82)
# ==============================================================================
PERIODUS_NEV = {"felvet": "félév", "ev": "tanév"}


def _riport_idoszak(tanev, periodus):
    """A riport időszaka: félév (tanév kezdete – jan. 31.) vagy teljes tanév."""
    tanev = (tanev or kreta_tanev.current_tanev() or "").strip()
    kezdo, zaro = kreta_tanev.tanev_bounds(tanev) if tanev else (None, None)
    if not kezdo or not zaro:
        return tanev, None, None
    if periodus == "felvet":
        felvet_vege = date(kezdo.year + 1, 1, 31)
        if felvet_vege < zaro:
            zaro = felvet_vege
    return tanev, kezdo, zaro


def _riport_adatok(diak, tanev, kezdo, zaro):
    """A riporthoz szükséges adatok (jegyek, hiányzások, feljegyzések, egyenleg)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT esemeny_tipus, tantargy, ertek, szam_ertek, suly_szazalek, mod,"
        " tipus, tema, cim, tartalom, ertekelo, bej_datum, kesz"
        " FROM esemenyek WHERE diak_nev = ? AND tanev = ?"
        " ORDER BY bej_datum", (diak, tanev))
    esemenyek = [dict(r) for r in cursor.fetchall()]
    adatok = {"tantargyak": {}, "feljegyzesek": [], "egyeb_jegyek": {}}
    for r in esemenyek:
        d = normalize_date(r.get("bej_datum") or "")
        if d and ((kezdo and d < kezdo.isoformat()) or (zaro and d > zaro.isoformat())):
            continue
        tipus = r.get("esemeny_tipus") or ""
        if tipus == "Értékelés":
            tantargy = (r.get("tantargy") or "Egyéb").strip()
            try:
                szam = int(r.get("szam_ertek"))
            except (TypeError, ValueError):
                szam = 0
            if szam in (1, 2, 3, 4, 5):
                entry = adatok["tantargyak"].setdefault(tantargy, [])
                entry.append({"ertek": r.get("ertek") or str(szam), "szam": szam,
                              "suly": int(r.get("suly_szazalek") or 0),
                              "datum": d or ""})
            elif r.get("ertek"):
                adatok["egyeb_jegyek"][tantargy] = r.get("ertek")
        elif tipus == "Feljegyzés":
            adatok["feljegyzesek"].append({
                "datum": d or "", "mod": r.get("mod") or r.get("tipus") or "",
                "tema": r.get("tema") or "", "tartalom": r.get("tartalom") or "",
                "tanar": r.get("ertekelo") or "",
            })

    for tantargy, jegyek in adatok["tantargyak"].items():
        sulyos = [(j["szam"], j["suly"]) for j in jegyek if j["suly"] > 0]
        if sulyos:
            ossz_suly = sum(s for _e, s in sulyos)
            atlag = sum(e * s for e, s in sulyos) / ossz_suly
        else:
            atlag = sum(j["szam"] for j in jegyek) / len(jegyek)
        adatok["tantargyak"][tantargy] = {
            "jegyek": jegyek,
            "atlag": round(atlag, 2),
            "db": len(jegyek),
        }

    try:
        cursor.execute("SELECT * FROM hianyzasok WHERE diak_nev = ? AND tanev = ?",
                       (diak, tanev))
        hianyzasok = [dict(r) for r in cursor.fetchall()]
        hianyzasok = [h for h in hianyzasok
                      if (not kezdo or (normalize_date(h.get("mulasztas_datum")) or "") >= kezdo.isoformat())
                      and (not zaro or (normalize_date(h.get("mulasztas_datum")) or "") <= zaro.isoformat())]
        adatok["hianyzasok"] = hianyzas_osszesito(hianyzasok)
    except sqlite3.Error:
        adatok["hianyzasok"] = hianyzas_osszesito([])
    conn.close()

    stat = compute_zsebpenz_statisztika(
        diak=diak, kezdo_datum=kezdo.isoformat() if kezdo else "",
        zaro_datum=zaro.isoformat() if zaro else "", tanev_szuro=tanev)
    adatok["egyenleg"] = int(stat.get("vegosszeg", 0) or 0) - int(stat.get("kifizetve", 0) or 0)
    adatok["rewards_enabled"] = bool(stat.get("rewards_enabled"))
    return adatok


_ERDEMJEGY_NEV = {5: "Jeles", 4: "Jó", 3: "Közepes", 2: "Elégséges", 1: "Elégtelen"}


def _jegy_osszegzes(jegyek):
    """Jegyenként összesített darabszám, dátum nélkül (pl. „Jeles(5) - 3 db ; Jó(4) - 2 db”)."""
    darab = {}
    for j in jegyek or []:
        darab[j["szam"]] = darab.get(j["szam"], 0) + 1
    reszek = []
    for szam in sorted(darab, reverse=True):
        nev = _ERDEMJEGY_NEV.get(szam)
        cimke = f"{nev}({szam})" if nev else str(szam)
        reszek.append(f"{cimke} - {darab[szam]} db")
    return " ; ".join(reszek)


def _egyeb_jegy_sorrend(nev):
    """A magatartás/szorgalom legyen elöl, utána a többi értékelés ABC-ben."""
    n = (nev or "").lower()
    if "magatart" in n:
        return (0, n)
    if "szorgalom" in n:
        return (1, n)
    return (2, n)


def _riport_pdf(diak, tanev, periodus, kezdo, zaro, adatok):
    """A4-es, dísz-bizonyítvány jellegű aktuális bizonyítvány PDF bytes-ként (1 oldal)."""
    _register_pdf_fonts()
    NAVY = colors.HexColor("#1f3a5f")
    GOLD = colors.HexColor("#b08d3f")
    CREAM = colors.HexColor("#faf6ec")
    INK = colors.HexColor("#2b3440")
    MUTED = colors.HexColor("#6b7683")
    LINE = colors.HexColor("#ddd2b6")
    FEJ = colors.HexColor("#24405f")

    styles = getSampleStyleSheet()
    cim = ParagraphStyle("RiportCim", parent=styles["Heading1"], fontName=_pdf_serif_bold(),
                         fontSize=21, leading=26, textColor=NAVY, alignment=TA_CENTER)
    felirat = ParagraphStyle("RiportFelirat", parent=styles["Normal"], fontName=_pdf_serif(),
                             fontSize=9.5, leading=12, textColor=GOLD, alignment=TA_CENTER)
    alcim = ParagraphStyle("RiportAlcim", parent=styles["Normal"], fontName=_pdf_font(),
                           fontSize=9, leading=13, textColor=MUTED, alignment=TA_CENTER)
    szoveg = ParagraphStyle("RiportSzoveg", parent=styles["Normal"], fontName=_pdf_font(),
                            fontSize=9, leading=12, textColor=INK)
    kicsi = ParagraphStyle("RiportKicsi", parent=szoveg, fontSize=7.5, leading=10,
                           textColor=MUTED, alignment=TA_CENTER)
    kicsi_bal = ParagraphStyle("RiportKicsiBal", parent=szoveg, fontSize=8, leading=10.5)
    cella = ParagraphStyle("RiportCella", parent=szoveg, fontSize=8.5, leading=11)
    cella_nev = ParagraphStyle("RiportCellaNev", parent=cella, fontName=_pdf_font_bold(),
                               textColor=NAVY)
    cella_szam = ParagraphStyle("RiportCellaSzam", parent=cella, alignment=TA_RIGHT)
    cella_sor = ParagraphStyle("RiportCellaSor", parent=szoveg, fontSize=8.2, leading=10)
    cella_sor_nev = ParagraphStyle("RiportCellaSorNev", parent=cella_sor,
                                   fontName=_pdf_font_bold(), textColor=NAVY)
    cella_sor_szam = ParagraphStyle("RiportCellaSorSzam", parent=cella_sor, alignment=TA_RIGHT)
    cella_fej = ParagraphStyle("RiportCellaFej", parent=cella, fontName=_pdf_serif_bold(),
                               fontSize=9, leading=11, textColor=colors.white)
    cella_fej_jobb = ParagraphStyle("RiportCellaFejJobb", parent=cella_fej, alignment=TA_RIGHT)
    h2 = ParagraphStyle("RiportH2", parent=styles["Heading2"], fontName=_pdf_serif_bold(),
                        fontSize=12.5, leading=15, textColor=NAVY)

    def szekcio(szoveg_cim):
        tabla_cim = Table([[Paragraph(szoveg_cim, h2)]], colWidths=[17.0 * cm])
        tabla_cim.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CREAM),
            ("LINEBEFORE", (0, 0), (0, -1), 2.6, GOLD),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return tabla_cim

    def pecsét():
        rajz = Drawing(200, 118)
        rajz.hAlign = "CENTER"
        rajz.add(Circle(100, 58, 52, strokeColor=GOLD, strokeWidth=1.5, fillColor=None))
        rajz.add(Circle(100, 58, 44, strokeColor=GOLD, strokeWidth=0.6, fillColor=None))
        rajz.add(String(100, 64, "SULIHUB", textAnchor="middle",
                        fontName=_pdf_serif_bold(), fontSize=12, fillColor=GOLD))
        rajz.add(String(100, 50, periodus_cimke, textAnchor="middle",
                        fontName=_pdf_font(), fontSize=7.5, fillColor=NAVY))
        rajz.add(String(100, 39, "aktuális bizonyítvány", textAnchor="middle",
                        fontName=_pdf_font(), fontSize=6, fillColor=MUTED))
        return rajz

    periodus_cimke = f"{tanev} 1. félév" if periodus == "felvet" else f"{tanev} év"
    idoszak_szoveg = "1. félév" if periodus == "felvet" else "teljes tanév"
    h = adatok.get("hianyzasok", {})
    if adatok["tantargyak"]:
        jegy_db = sum(t["db"] for t in adatok["tantargyak"].values())
        atlag = f"{sum(t['atlag'] * t['db'] for t in adatok['tantargyak'].values()) / max(1, jegy_db):.2f}"
    else:
        atlag = "–"
    egyeb = {nev: ertek for nev, ertek in (adatok.get("egyeb_jegyek") or {}).items()
             if "magatart" in (nev or "").lower() or "szorgalom" in (nev or "").lower()}

    def epit_story(pecset_kell, logo_kell):
        """A story minden hívásnál új (a flowable-ök nem használhatók újra)."""
        story = []
        if logo_kell:
            logo_ut = os.path.join(APP_DIR, "static", "img", "sulihub-logo.png")
            if os.path.exists(logo_ut):
                kep = RLImage(logo_ut, width=2.3 * cm, height=1.38 * cm)
                kep.hAlign = "CENTER"
                story += [kep, Spacer(1, 0.08 * cm)]
        story += [
            Paragraph("AKTUÁLIS BIZONYÍTVÁNY", felirat),
            Spacer(1, 0.1 * cm),
            Paragraph(f"SuliHub - {diak} - {periodus_cimke}", cim),
            Spacer(1, 0.12 * cm),
            HRFlowable(width="52%", thickness=1.1, color=GOLD,
                       spaceBefore=4, spaceAfter=5, hAlign="CENTER"),
            Paragraph(f"{idoszak_szoveg} · {kezdo.isoformat() if kezdo else '?'} – "
                      f"{zaro.isoformat() if zaro else '?'} · "
                      f"készült: {datetime.now().strftime('%Y-%m-%d %H:%M')}", alcim),
            Spacer(1, 0.35 * cm),
        ]

        ossz = [
            [Paragraph("Tanulmányi átlag", cella_nev), Paragraph(atlag, cella)],
            [Paragraph("Jegyek száma", cella_nev),
             Paragraph(str(sum(t["db"] for t in adatok["tantargyak"].values())), cella)],
            [Paragraph("Hiányzás / igazolatlan", cella_nev),
             Paragraph(f"{h.get('hianyzas_db', 0)} óra / {h.get('igazolatlan_ora', 0)} óra", cella)],
            [Paragraph("Késés", cella_nev),
             Paragraph(f"{h.get('keses_db', 0)} db / {h.get('keses_perc', 0)} perc", cella)],
        ]
        # A zsebpénz sor csak akkor kerül a bizonyítványra, ha a diákra engedélyezett a modul.
        if adatok.get("rewards_enabled"):
            ossz.append([Paragraph("Zsebpénz egyenleg", cella_nev),
                         Paragraph(f"{adatok.get('egyenleg', 0):,} Ft".replace(",", " "), cella)])
        ossz_tabla = Table(ossz, colWidths=[7.0 * cm, 10.0 * cm])
        ossz_tabla.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.9, GOLD),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, CREAM]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story += [szekcio("Összegzés"), Spacer(1, 0.15 * cm), ossz_tabla, Spacer(1, 0.4 * cm)]

        fej = [Paragraph("Tantárgy", cella_fej), Paragraph("Jegyek", cella_fej),
               Paragraph("Átlag", cella_fej_jobb)]
        sorok = [fej]
        for tantargy in sorted(adatok["tantargyak"]):
            t = adatok["tantargyak"][tantargy]
            sorok.append([Paragraph(tantargy, cella_sor_nev),
                          Paragraph(_jegy_osszegzes(t["jegyek"]), cella_sor),
                          Paragraph(f"{t['atlag']:.2f}", cella_sor_szam)])
        if len(sorok) == 1:
            sorok.append([Paragraph("Nincs értékelés az időszakban.", cella_sor), "", ""])
        tabla = Table(sorok, colWidths=[4.4 * cm, 10.8 * cm, 1.8 * cm], repeatRows=1)
        stilus = [
            ("BOX", (0, 0), (-1, -1), 0.9, GOLD),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
            ("BACKGROUND", (0, 0), (-1, 0), FEJ),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CREAM]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if len(sorok) == 2 and sorok[1][1] == "":
            stilus.append(("SPAN", (0, 1), (2, 1)))
        tabla.setStyle(TableStyle(stilus))
        story += [szekcio("Tantárgyi eredmények"), Spacer(1, 0.15 * cm), tabla,
                  Spacer(1, 0.4 * cm)]

        if egyeb:
            mag_sorok = [[Paragraph("Megnevezés", cella_fej),
                          Paragraph("Értékelés", cella_fej)]]
            for nev in sorted(egyeb, key=_egyeb_jegy_sorrend):
                mag_sorok.append([Paragraph(nev, cella_nev), Paragraph(str(egyeb[nev]), cella)])
            mag_tabla = Table(mag_sorok, colWidths=[8.5 * cm, 8.5 * cm], hAlign="CENTER")
            mag_tabla.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.9, GOLD),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("BACKGROUND", (0, 0), (-1, 0), FEJ),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CREAM]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story += [szekcio("Magatartás és szorgalom"), Spacer(1, 0.15 * cm), mag_tabla,
                      Spacer(1, 0.3 * cm)]

        story += [HRFlowable(width="100%", thickness=0.7, color=GOLD,
                             spaceBefore=2, spaceAfter=5),
                  Paragraph(
                      "Az átlagok a KRÉTA súlyozásával (Σ jegy×súly / Σ súly) számoltak; a "
                      "0%-os súlyú jegy kimarad. A hivatalos félévi/év végi osztályzat a KRÉTA "
                      "API-ból nem érhető el, ezért a riport a jegyekből számolt átlagot mutatja.",
                      kicsi)]
        if pecset_kell:
            story += [Spacer(1, 0.5 * cm), pecsét()]
        return story

    def keret(canvas, _doc):
        """Arany duplakeret és sarokdíszek minden oldalon (dísz-bizonyítvány)."""
        canvas.saveState()
        w, hh = A4
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(2.4)
        canvas.rect(1.0 * cm, 1.0 * cm, w - 2.0 * cm, hh - 2.0 * cm)
        canvas.setLineWidth(0.6)
        canvas.rect(1.28 * cm, 1.28 * cm, w - 2.56 * cm, hh - 2.56 * cm)
        for cx, cy in ((1.0 * cm, 1.0 * cm), (w - 1.0 * cm, 1.0 * cm),
                       (1.0 * cm, hh - 1.0 * cm), (w - 1.0 * cm, hh - 1.0 * cm)):
            canvas.setFillColor(GOLD)
            canvas.circle(cx, cy, 0.17 * cm, stroke=0, fill=1)
            canvas.setFillColor(colors.white)
            canvas.circle(cx, cy, 0.075 * cm, stroke=0, fill=1)
        for cy in (1.0 * cm, hh - 1.0 * cm):
            canvas.setFillColor(GOLD)
            p = canvas.beginPath()
            p.moveTo(w / 2, cy + 0.17 * cm)
            p.lineTo(w / 2 + 0.17 * cm, cy)
            p.lineTo(w / 2, cy - 0.17 * cm)
            p.lineTo(w / 2 - 0.17 * cm, cy)
            p.close()
            canvas.drawPath(p, stroke=0, fill=1)
        canvas.setFont(_pdf_font(), 6.8)
        canvas.setFillColor(MUTED)
        canvas.drawCentredString(w / 2, 1.5 * cm,
                                 f"SuliHub · {diak} · {periodus_cimke} · automatikusan generált")
        canvas.restoreState()

    def epites(pecset_kell, logo_kell):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2.0 * cm,
                                rightMargin=2.0 * cm, topMargin=2.0 * cm, bottomMargin=2.0 * cm)
        doc.build(epit_story(pecset_kell, logo_kell), onFirstPage=keret, onLaterPages=keret)
        return buffer.getvalue(), doc.page

    # Díszítés csak addig, amíg 1 oldal marad: először logó + pecsét, aztán logó,
    # végül a kettő nélkül (hosszú tantárgylistánál így sem lesz 2. oldal).
    van_logo = os.path.exists(os.path.join(APP_DIR, "static", "img", "sulihub-logo.png"))
    pdf, oldalak = epites(True, van_logo)
    if oldalak > 1:
        pdf, oldalak = epites(False, van_logo)
    if oldalak > 1:
        pdf, _oldalak = epites(False, False)
    return pdf

@bp.route("/api/riportkartya/export_pdf")
def api_riportkartya_export_pdf():
    """Aktuális bizonyítvány PDF generálása közvetlenül (mentés nélkül, Kaneo #82)."""
    diak = (request.args.get("diak") or "").strip()
    if not diak:
        return jsonify({"error": "Válassz gyermeket."}), 400
    periodus = (request.args.get("periodus") or "ev").strip()
    if periodus not in PERIODUS_NEV:
        return jsonify({"error": "Az időszak 'felvet' vagy 'ev' lehet."}), 400
    tanev, kezdo, zaro = _riport_idoszak(request.args.get("tanev") or "", periodus)
    if not kezdo or not zaro:
        return jsonify({"error": "Érvénytelen tanév."}), 400

    adatok = _riport_adatok(diak, tanev, kezdo, zaro)
    try:
        pdf = _riport_pdf(diak, tanev, periodus, kezdo, zaro, adatok)
    except Exception as exc:  # a PDF hibája ne 500-as nyers stacktrace legyen
        print(f"[Riport] PDF hiba: {exc}")
        return jsonify({"error": "A PDF generálása nem sikerült."}), 500

    biztonsagos = re.sub(r"[^A-Za-z0-9._-]+", "_", diak)[:50] or "diak"
    response = Response(pdf, mimetype="application/pdf")
    response.headers["Content-Disposition"] = (
        f"inline; filename=\"riport_{biztonsagos}_{tanev.replace('/', '-')}_{periodus}.pdf\"")
    return response
