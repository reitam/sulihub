from flask import Flask, render_template, request, jsonify, send_from_directory
import sqlite3
import os
import subprocess
import json
import threading
import re
from datetime import datetime

app = Flask(__name__)
DB_FILE = "kreta_adatok.db"
CONFIG_FILE = "config.json"

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
        
        # Ellenőrizzük, hogy az esemenyek táblában létezik-e a 'kesz' oszlop
        cursor.execute("PRAGMA table_info(esemenyek)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "kesz" not in columns:
            cursor.execute("ALTER TABLE esemenyek ADD COLUMN kesz INTEGER DEFAULT 0")
            print("[Adatbázis séma frissítve]: 'kesz' oszlop hozzáadva az 'esemenyek' táblához.")
            
        conn.commit()
        conn.close()

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

        cursor.execute("SELECT DISTINCT diak_nev FROM esemenyek UNION SELECT DISTINCT diak_nev FROM uzenetek ORDER BY diak_nev")
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

    events = []
    for r in rows:
        norm_date = normalize_date(r["hatarido"])
        if not norm_date:
            continue

        es_tipus = r["esemeny_tipus"]
        keys = r.keys()
        is_kesz = bool(r["kesz"]) if "kesz" in keys and r["kesz"] else False

        # TELJES NÉV HASZNÁLATA (VEZETÉKNÉV + KERESZTNÉV)
        teljes_nev = r["diak_nev"] or "Ismeretlen"

        title = f"{teljes_nev}: {r['tantargy']} - {es_tipus}"
        if es_tipus == 'Házi feladat' and is_kesz:
            title = f"✔ {title}"

        color = "#0d6efd"  # Kék: Házi feladat
        if es_tipus == 'Bejelentett számonkérés':
            color = "#dc3545"  # Piros: Számonkérés
        elif es_tipus == 'Házi feladat' and is_kesz:
            color = "#198754"  # Zöld: Elkészült házi

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

    jegy_query = "SELECT szam_ertek, bej_datum FROM esemenyek WHERE esemeny_tipus = 'Értékelés'"
    params = []
    if diak:
        jegy_query += " AND diak_nev = ?"
        params.append(diak)

    cursor.execute(jegy_query, params)
    jegy_rows = cursor.fetchall()

    jegy_counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
    jegy_sum = 0
    jegy_total_count = 0

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

    atlag = round(jegy_sum / jegy_total_count, 2) if jegy_total_count > 0 else 0.0

    felj_query = "SELECT cim, tartalom, bej_datum FROM esemenyek WHERE esemeny_tipus = 'Feljegyzés'"
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
        "kifizetve": kifizetve
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

@app.route("/static/csatolmanyok/<path:filename>")
def download_csatolmany(filename):
    return send_from_directory("static/csatolmanyok", filename)

if __name__ == "__main__":
    print("Flask web szerver indítása: http://127.0.0.1:5000")
    app.run(debug=True, port=5000)