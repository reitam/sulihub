from flask import Flask, render_template, request, jsonify, Response, send_from_directory
import sqlite3
import os
import subprocess
import json

app = Flask(__name__)
DB_FILE = "kreta_adatok.db"
CONFIG_FILE = "config.json"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

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
            "tartalom": r["tartalom"] or "-"
        })

    conn.close()
    return jsonify(esemenyek)

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

        uzenetek.append({
            "id": r["id"],
            "diak_nev": r["diak_nev"] if "diak_nev" in keys else "",
            "felado": r["felado"] if "felado" in keys else "-",
            "targy": r["targy"] if "targy" in keys else "-",
            "idopont": r["idopont"] if "idopont" in keys else "-",
            "szoveg": r["szoveg"] if "szoveg" in keys else "",
            "csatolmany_nev": cs_nev or "",
            "csatolmany_utvonal": cs_ut or ""
        })

    conn.close()
    return jsonify(uzenetek)

@app.route("/api/statisztika")
def api_statisztika():
    """Havi jegy-, feljegyzés- és zsebpénz-statisztika API."""
    config = load_config()
    global_enable = config.get("ENABLE_REWARDS", True)
    
    if not global_enable or not os.path.exists(DB_FILE):
        return jsonify({"enabled": False})

    diak = request.args.get("diak", "")
    honap = request.args.get("honap", "")  # pl: "2026-10" vagy "2026. 10."

    # Diákonkénti engedélyezés ellenőrzése
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

    # 1. ÉRDEMJEGYEK LEKÉRDEZÉSE
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
        datum_str = r["bej_datum"] or ""
        # Szűrés hónapra (ha meg van adva)
        if honap and honap not in datum_str.replace(". ", "-").replace(".", ""):
            continue

        val = r["szam_ertek"]
        if val in jegy_counts:
            jegy_counts[val] += 1
            jegy_sum += val
            jegy_total_count += 1

    atlag = round(jegy_sum / jegy_total_count, 2) if jegy_total_count > 0 else 0.0

    # 2. FELJEGYZÉSEK SZÖVEGELEMZÉSE
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
        datum_str = r["bej_datum"] or ""
        if honap and honap not in datum_str.replace(". ", "-").replace(".", ""):
            continue

        text = f"{r['cim'] or ''} {r['tartalom'] or ''}".lower()

        for cat, kw_list in keywords.items():
            if any(kw in text for kw in kw_list):
                counts[cat] += 1

    conn.close()

    # 3. PÉNZÜGYI KISZÁMÍTÁS (EGALIZÁLÁS)
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
        "vegosszeg": vegosszeg
    })

@app.route("/static/csatolmanyok/<path:filename>")
def download_csatolmany(filename):
    return send_from_directory("static/csatolmanyok", filename)

@app.route("/api/sync_stream")
def api_sync_stream():
    """Valós idejű konzol-stream a szinkronizáláshoz."""
    def generate():
        process = subprocess.Popen(
            ["python", "-u", "kreta_playwright.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        for line in iter(process.stdout.readline, ''):
            if line:
                yield f"data: {json.dumps({'msg': line.strip()})}\n\n"
        
        process.stdout.close()
        process.wait()
        
        if process.returncode == 0:
            yield f"data: {json.dumps({'status': 'done', 'msg': 'Sikeres szinkronizálás!'})}\n\n"
        else:
            yield f"data: {json.dumps({'status': 'error', 'msg': 'Hiba történt a futtatás során!'})}\n\n"

    return Response(generate(), mimetype="text/event-stream")

if __name__ == "__main__":
    print("Flask web szerver indítása: http://127.0.0.1:5000")
    app.run(debug=True, port=5000)