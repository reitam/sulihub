# -*- coding: utf-8 -*-
"""
Főoldal (KRÉ-14 #95): a dashboardot kiszolgáló `/` végpont.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. Prefix nélküli blueprint —
az URL változatlan.
"""
import os

from flask import render_template

from kreta_db import get_db_connection
from kreta_paths import DB_FILE
from kreta_settings import get_app_version, load_config
from views_common import make_bp

bp = make_bp("pages")

@bp.route("/")
def index():
    config = load_config()
    global_enable_rewards = config.get("ENABLE_REWARDS", True)

    if not os.path.exists(DB_FILE):
        diakok, tipusok, tantargyak = [], [], []
    else:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT diak_nev FROM esemenyek UNION SELECT DISTINCT diak_nev FROM uzenetek UNION SELECT DISTINCT diak_nev FROM orarend UNION SELECT DISTINCT diak_nev FROM hianyzasok ORDER BY diak_nev")
        diakok = [row["diak_nev"] for row in cursor.fetchall() if row["diak_nev"]]
        # A config diákjai akkor is választhatók legyenek, ha még nincs szinkronizált sor.
        for student in config.get("STUDENTS", []):
            nev = (student.get("diak_nev") or "").strip()
            if nev and nev not in diakok:
                diakok.append(nev)

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
        global_enable_rewards=global_enable_rewards,
        app_version=get_app_version()
    )
