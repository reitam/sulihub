from flask import Flask, render_template, request, jsonify, Response
import sqlite3
import os
import subprocess
import json

app = Flask(__name__)
DB_FILE = "kreta_adatok.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

@app.route("/")
def index():
    if not os.path.exists(DB_FILE):
        diakok, tipusok, tantargyak = [], [], []
    else:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT diak_nev FROM esemenyek ORDER BY diak_nev")
        diakok = [row["diak_nev"] for row in cursor.fetchall() if row["diak_nev"]]

        cursor.execute("SELECT DISTINCT esemeny_tipus FROM esemenyek ORDER BY esemeny_tipus")
        tipusok = [row["esemeny_tipus"] for row in cursor.fetchall() if row["esemeny_tipus"]]

        cursor.execute("SELECT DISTINCT tantargy FROM esemenyek WHERE tantargy IS NOT NULL AND tantargy != '' ORDER BY tantargy")
        tantargyak = [row["tantargy"] for row in cursor.fetchall()]

        conn.close()

    return render_template("index.html", diakok=diakok, tipusok=tipusok, tantargyak=tantargyak)

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