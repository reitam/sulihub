from flask import Flask, render_template, request, jsonify, send_from_directory, make_response
import sqlite3
import os
import subprocess
import json
import threading
import re
import io
from datetime import datetime, timedelta

# ReportLab importok a PDF generáláshoz
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

app = Flask(__name__)
DB_FILE = "kreta_adatok.db"
CONFIG_FILE = "config.json"
LOG_FILE = "sync.log"

sync_state = {
    "running": False,
    "process": None,
    "logs": [],
    "status": "idle"
}
sync_lock = threading.Lock()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db_extensions():
    if os.path.exists(DB_FILE):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Kifizetések tábla
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kifizetesek (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    diak_nev TEXT NOT NULL,
                    kezdo_datum TEXT NOT NULL,
                    zaro_datum TEXT NOT NULL,
                    kifizetve INTEGER DEFAULT 0,
                    osszeg INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(diak_nev, kezdo_datum, zaro_datum)
                )
            """)
            
            # Órarend tábla
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orarend (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    diak_nev TEXT,
                    kezdo_idopont TEXT,
                    zaro_idopont TEXT,
                    nap TEXT,
                    tantargy TEXT,
                    tanar TEXT,
                    terem TEXT
                )
            """)
            
            # Ellenőrizzük, hogy az esemenyek táblában létezik-e a 'kesz' oszlop
            cursor.execute("PRAGMA table_info(esemenyek)")
            columns = [row["name"] for row in cursor.fetchall()]
            if "kesz" not in columns:
                cursor.execute("ALTER TABLE esemenyek ADD COLUMN kesz INTEGER DEFAULT 0")
                print("[Adatbázis séma frissítve]: 'kesz' oszlop hozzáadva az 'esemenyek' táblához.")
                
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Adatbázis inicializálási figyelmeztetés]: {e}")

init_db_extensions()

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def run_scraper_thread():
    global sync_state
    
    with sync_lock:
        sync_state["running"] = True
        sync_state["logs"] = ["> Szinkronizáció indítása a háttérben..."]
        sync_state["status"] = "running"

    try:
        process = subprocess.Popen(
            ["python", "-u", "kreta_playwright.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        with sync_lock:
            sync_state["process"] = process

        for line in iter(process.stdout.readline, ''):
            if line:
                cleaned_line = line.strip()
                with sync_lock:
                    sync_state["logs"].append(cleaned_line)
                    if len(sync_state["logs"]) > 500:
                        sync_state["logs"].pop(0)

        process.stdout.close()
        process.wait()

        with sync_lock:
            if sync_state["status"] != "stopped":
                if process.returncode == 0:
                    sync_state["status"] = "done"
                    sync_state["logs"].append("> SZINKRONIZÁCIÓ SIKERESEN BEFEJEZŐDÖTT!")
                else:
                    sync_state["status"] = "error"
                    sync_state["logs"].append("> HIBA TÖRTÉNT A SZINKRONIZÁCIÓ SORÁN!")

    except Exception as e:
        with sync_lock:
            sync_state["status"] = "error"
            sync_state["logs"].append(f"> Kivétel történt: {str(e)}")
    finally:
        with sync_lock:
            sync_state["running"] = False
            sync_state["process"] = None

@app.route("/")
def index():
    config = load_config()
    global_enable_rewards = config.get("ENABLE_REWARDS", True)

    if not os.path.exists(DB_FILE):
        diakok, tipusok, tantargyak = [], [], []
    else:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT diak_nev FROM esemenyek UNION SELECT DISTINCT diak_nev FROM uzenetek UNION SELECT DISTINCT diak_nev FROM orarend ORDER BY diak_nev")
        diakok = [row["diak_nev"] for row in cursor.fetchall() if row["diak_nev"]]

        cursor.execute("SELECT DISTINCT esemeny_tipus FROM esemenyek ORDER BY esemeny_tipus")
        tipusok = [row["esemeny_tipus"] for row in cursor.fetchall() if row["esemeny_tipus"]]

        cursor.execute("SELECT DISTINCT tantargy FROM esemenyek WHERE tantargy IS NOT NULL AND tantargy != '' ORDER BY tantargy")
        tantargyak = [row["tantargy"] for row in cursor.fetchall()]

        conn.close()

    return render_template(
        "index.html", 
        diakok=diakok, 
        tipusok=tipusok, 
        tantargyak=tantargyak,
        global_enable_rewards=global_enable_rewards
    )

@app.route("/api/esemenyek")
def api_esemenyek():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "")
    tipus = request.args.get("tipus", "")
    tantargy = request.args.get("tantargy", "")

    query = "SELECT * FROM esemenyek WHERE 1=1"
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)
    if tipus:
        query += " AND esemeny_tipus = ?"
        params.append(tipus)
    if tantargy:
        query += " AND tantargy = ?"
        params.append(tantargy)

    query += " ORDER BY id DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    esemenyek = []
    for r in rows:
        keys = r.keys()
        kesz_val = r["kesz"] if "kesz" in keys else 0

        esemenyek.append({
            "id": r["id"],
            "diak_nev": r["diak_nev"],
            "esemeny_tipus": r["esemeny_tipus"],
            "tantargy": r["tantargy"] or "-",
            "ertek": r["ertek"] or "-",
            "szam_ertek": r["szam_ertek"] or 0,
            "bej_datum": r["bej_datum"] or "-",
            "hatarido": r["hatarido"] or "-",
            "ertekelo": r["ertekelo"] or "-",
            "tipus": r["tipus"] or "-",
            "mod": r["mod"] or "-",
            "tema": r["tema"] or "-",
            "cim": r["cim"] or "-",
            "tartalom": r["tartalom"] or "-",
            "kesz": int(kesz_val or 0)
        })

    conn.close()
    return jsonify(esemenyek)

@app.route("/api/orarend")
def api_orarend():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "")
    query = "SELECT * FROM orarend WHERE 1=1"
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)

    query += " ORDER BY kezdo_idopont ASC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return jsonify([dict(row) for row in rows])

@app.route("/api/orarend_naptar")
def api_orarend_naptar():
    """Órarend lekérdezése a FullCalendar idősávos nézetéhez egyedi diák színkódolással."""
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT diak_nev FROM orarend ORDER BY diak_nev")
    osszes_diak = [r["diak_nev"] for r in cursor.fetchall() if r["diak_nev"]]

    color_palette = [
        {"bg": "#0d6efd", "border": "#0a58ca"},
        {"bg": "#198754", "border": "#146c43"},
        {"bg": "#6f42c1", "border": "#59359a"},
        {"bg": "#d63384", "border": "#ab296a"},
        {"bg": "#20c997", "border": "#1aa179"},
        {"bg": "#fd7e14", "border": "#ca6510"}
    ]

    diak_color_map = {}
    for idx, d_nev in enumerate(osszes_diak):
        diak_color_map[d_nev] = color_palette[idx % len(color_palette)]

    diak = request.args.get("diak", "")
    query = "SELECT * FROM orarend WHERE 1=1"
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    multi_student = not diak

    events = []
    for r in rows:
        d_nev = r["diak_nev"] or "Ismeretlen"
        kezdo = r["kezdo_idopont"]
        zaro = r["zaro_idopont"]
        tantargy = r["tantargy"] or "Tanóra"
        tanar = r["tanar"] or ""
        terem = r["terem"] or ""

        is_all_day = not zaro or "T" not in kezdo

        student_colors = diak_color_map.get(d_nev, {"bg": "#0d6efd", "border": "#0a58ca"})

        if is_all_day:
            title = f"🔴 {d_nev}: {tantargy}" if multi_student else f"🔴 {tantargy}"
            bg_color = "#fd7e14"
            border_color = "#ca6510"
        else:
            title = f"[{d_nev}] {tantargy}" if multi_student else tantargy
            if terem:
                title += f" ({terem})"
            bg_color = student_colors["bg"]
            border_color = student_colors["border"]

        events.append({
            "id": r["id"],
            "title": title,
            "start": kezdo,
            "end": zaro if zaro else None,
            "allDay": is_all_day,
            "backgroundColor": bg_color,
            "borderColor": border_color,
            "extendedProps": {
                "diak": d_nev,
                "tantargy": tantargy,
                "tanar": tanar,
                "terem": terem,
                "nap": r["nap"] or ""
            }
        })

    return jsonify(events)

@app.route("/api/orarend/export_pdf")
def export_orarend_pdf():
    """Órarend PDF generálása teljesen elkülönített 'Egész napos' sor kezelésével."""
    if not os.path.exists(DB_FILE):
        return "Adatbázis nem található!", 404

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "").strip()

    mai_nap = datetime.now()
    hetfo = mai_nap - timedelta(days=mai_nap.weekday())
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
        spaceAfter=2
    )
    
    subtitle_style = ParagraphStyle(
        'HeaderSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#6c757d'),
        alignment=0,
        spaceAfter=8
    )

    cell_time_style = ParagraphStyle(
        'CellTime',
        fontSize=8,
        leading=10,
        alignment=1,
        textColor=colors.HexColor('#333333')
    )

    cell_header_style = ParagraphStyle(
        'CellHeader',
        fontSize=10,
        leading=12,
        alignment=1,
        textColor=colors.white,
        fontName='Helvetica-Bold'
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
                    p = Paragraph(cell_html, ParagraphStyle('CellContent', fontSize=8, leading=9.5, alignment=1))
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
                    p = Paragraph(cell_html, ParagraphStyle('CellContent', fontSize=8, leading=9.5, alignment=1))
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

@app.route("/api/naptar_esemenyek")
def api_naptar_esemenyek():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "")
    
    query = """
        SELECT * FROM esemenyek 
        WHERE esemeny_tipus IN ('Házi feladat', 'Bejelentett számonkérés')
          AND hatarido IS NOT NULL AND hatarido != '' AND hatarido != '-'
    """
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    mai_datum_str = datetime.now().strftime("%Y-%m-%d")

    events = []
    for r in rows:
        norm_date = normalize_date(r["hatarido"])
        if not norm_date:
            continue

        es_tipus = r["esemeny_tipus"]
        keys = r.keys()
        is_kesz = bool(r["kesz"]) if "kesz" in keys and r["kesz"] else False

        teljes_nev = r["diak_nev"] or "Ismeretlen"

        title = f"{teljes_nev}: {r['tantargy']} - {es_tipus}"
        if es_tipus == 'Házi feladat' and is_kesz:
            title = f"✔ {title}"

        is_past = norm_date < mai_datum_str

        if es_tipus == 'Bejelentett számonkérés':
            color = "#f18b95" if is_past else "#dc3545"
        elif es_tipus == 'Házi feladat' and is_kesz:
            color = "#75c099" if is_past else "#198754"
        else:
            color = "#8bb9fe" if is_past else "#0d6efd"

        reszletek = []
        if r['tema'] and r['tema'] != '-': reszletek.append(f"Téma: {r['tema']}")
        if r['cim'] and r['cim'] != '-': reszletek.append(f"Cím: {r['cim']}")
        if r['tartalom'] and r['tartalom'] != '-': reszletek.append(f"{r['tartalom']}")
        leiras = " | ".join(reszletek) or "Nincs részletes leírás"

        events.append({
            "id": r["id"],
            "title": title,
            "start": norm_date,
            "color": color,
            "extendedProps": {
                "diak": teljes_nev,
                "tipus": es_tipus,
                "tantargy": r["tantargy"],
                "tanar": r["ertekelo"] or "-",
                "leiras": leiras,
                "kesz": is_kesz
            }
        })

    return jsonify(events)

@app.route("/api/esemeny/statusz", methods=["POST"])
def api_esemeny_statusz():
    data = request.json or {}
    esemeny_id = data.get("id")
    kesz = 1 if data.get("kesz") else 0

    if not esemeny_id:
        return jsonify({"status": "error", "message": "Hiányzó azonosító"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE esemenyek SET kesz = ? WHERE id = ?", (kesz, esemeny_id))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "kesz": kesz})

@app.route("/api/uzenetek")
def api_uzenetek():
    if not os.path.exists(DB_FILE):
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    diak = request.args.get("diak", "")
    query = "SELECT * FROM uzenetek WHERE 1=1"
    params = []

    if diak:
        query += " AND diak_nev = ?"
        params.append(diak)

    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()

    uzenetek = []
    for r in rows:
        keys = r.keys()
        cs_nev = r["csatolmany_nev"] if "csatolmany_nev" in keys else ""
        cs_ut = r["csatolmany_utvonal"] if "csatolmany_utvonal" in keys else ""
        
        nyers_szoveg = r["szoveg"] if "szoveg" in keys and r["szoveg"] else ""
        tisztitott_szoveg = re.sub(r'\n{3,}', '\n\n', nyers_szoveg) if nyers_szoveg else ""

        uzenetek.append({
            "id": r["id"],
            "diak_nev": r["diak_nev"] if "diak_nev" in keys else "",
            "felado": r["felado"] if "felado" in keys else "-",
            "targy": r["targy"] if "targy" in keys else "-",
            "idopont": r["idopont"] if "idopont" in keys else "-",
            "szoveg": tisztitott_szoveg,
            "csatolmany_nev": cs_nev or "",
            "csatolmany_utvonal": cs_ut or ""
        })

    conn.close()
    return jsonify(uzenetek)

def normalize_date(d_str):
    if not d_str or d_str == "-":
        return None
    clean = d_str.replace(". ", "-").replace(".", "-").strip()
    parts = [p for p in clean.split("-") if p]
    if len(parts) >= 3:
        try:
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        except ValueError:
            return None
    return None

@app.route("/api/statisztika")
def api_statisztika():
    config = load_config()
    global_enable = config.get("ENABLE_REWARDS", True)
    
    if not global_enable or not os.path.exists(DB_FILE):
        return jsonify({"enabled": False})

    diak = request.args.get("diak", "")
    kezdo_datum = request.args.get("kezdo_datum", "")
    zaro_datum = request.args.get("zaro_datum", "")

    student_enable = True
    students = config.get("STUDENTS", [])
    for s in students:
        if s.get("diak_nev") == diak:
            student_enable = s.get("enable_rewards", True)
            break

    if not student_enable:
        return jsonify({"enabled": False})

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
    jegy_query = "SELECT id, tantargy, ertek, szam_ertek, bej_datum, mod, tema FROM esemenyek WHERE esemeny_tipus = 'Értékelés'"
    params = []
    if diak:
        jegy_query += " AND diak_nev = ?"
        params.append(diak)

    cursor.execute(jegy_query, params)
    jegy_rows = cursor.fetchall()

    jegy_counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
    jegy_sum = 0
    jegy_total_count = 0
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
            
            jutalom = rewards.get(f"jegy_{val}", 0)
            teteles_lista.append({
                "datum": r["bej_datum"],
                "tipus": "Értékelés",
                "megnevezes": f"{r['tantargy']} - {r['ertek']}",
                "reszletek": f"{r['mod'] or ''} {r['tema'] or ''}".strip(),
                "osszeg": jutalom
            })

    atlag = round(jegy_sum / jegy_total_count, 2) if jegy_total_count > 0 else 0.0

    # FELJEGYZÉSEK LEKÉRDEZÉSE ÉS TÉTELES LISTÁJA
    felj_query = "SELECT id, bej_datum, tipus, cim, tartalom FROM esemenyek WHERE esemeny_tipus = 'Feljegyzés'"
    f_params = []
    if diak:
        felj_query += " AND diak_nev = ?"
        f_params.append(diak)

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
                jutalom = rewards.get(cat, 0)
                teteles_lista.append({
                    "datum": r["bej_datum"],
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

    vegosszeg = jegy_osszeg + feljegyzes_osszeg

    return jsonify({
        "enabled": True,
        "jegy_counts": jegy_counts,
        "atlag": atlag,
        "jegy_total_count": jegy_total_count,
        "counts": counts,
        "rewards": rewards,
        "jegy_osszeg": jegy_osszeg,
        "feljegyzes_osszeg": feljegyzes_osszeg,
        "vegosszeg": vegosszeg,
        "kifizetve": kifizetve,
        "teteles_lista": teteles_lista
    })

@app.route("/api/kifizetes", methods=["POST"])
def api_kifizetes_save():
    data = request.json or {}
    diak = data.get("diak", "")
    kezdo_datum = data.get("kezdo_datum", "")
    zaro_datum = data.get("zaro_datum", "")
    kifizetve = 1 if data.get("kifizetve") else 0
    osszeg = data.get("osszeg", 0)

    if not diak or not kezdo_datum or not zaro_datum:
        return jsonify({"status": "error", "message": "Hiányzó paraméterek"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO kifizetesek (diak_nev, kezdo_datum, zaro_datum, kifizetve, osszeg, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(diak_nev, kezdo_datum, zaro_datum) DO UPDATE SET
            kifizetve = excluded.kifizetve,
            osszeg = excluded.osszeg,
            updated_at = CURRENT_TIMESTAMP
    """, (diak, kezdo_datum, zaro_datum, kifizetve, osszeg))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "kifizetve": bool(kifizetve)})

@app.route("/api/sync/start", methods=["POST"])
def api_sync_start():
    global sync_state
    with sync_lock:
        if sync_state["running"]:
            return jsonify({"status": "already_running", "message": "A szinkronizáció már fut!"})
        
        t = threading.Thread(target=run_scraper_thread, daemon=True)
        t.start()
        return jsonify({"status": "started", "message": "Szinkronizáció elindítva."})

@app.route("/api/sync/stop", methods=["POST"])
def api_sync_stop():
    global sync_state
    with sync_lock:
        if not sync_state["running"] or not sync_state["process"]:
            return jsonify({"status": "not_running", "message": "Nincs futó folyamat."})

        try:
            sync_state["process"].kill()
            sync_state["status"] = "stopped"
            sync_state["logs"].append("> SZINKRONIZÁLÁS A FELHASZNÁLÓ ÁLTAL LEÁLLÍTVA!")
            return jsonify({"status": "stopped", "message": "Folyamat leállítva."})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Hiba a leállításkor: {str(e)}"})

@app.route("/api/sync/status")
def api_sync_status():
    with sync_lock:
        return jsonify({
            "running": sync_state["running"],
            "status": sync_state["status"],
            "logs": sync_state["logs"]
        })

# ==============================================================================
# === SYNC.LOG KEZELŐ API VÉGPONTOK ===
# ==============================================================================
@app.route("/api/logs")
def api_get_logs():
    """Visszaadja a sync.log fájl tartalmát."""
    if not os.path.exists(LOG_FILE):
        return jsonify({"status": "ok", "content": "A sync.log fájl még nem létezik."})
    
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"status": "ok", "content": content if content else "A sync.log fájl üres."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/logs/clear", methods=["POST"])
def api_clear_logs():
    """Kiüríti a sync.log fájlt."""
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("")
        return jsonify({"status": "ok", "message": "A sync.log sikeresen kiürítve."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/static/csatolmanyok/<path:filename>")
def download_csatolmany(filename):
    return send_from_directory("static/csatolmanyok", filename)

if __name__ == "__main__":
    print("Flask web szerver indítása: http://127.0.0.1:5000")
    app.run(debug=True, port=5000)