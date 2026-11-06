# -*- coding: utf-8 -*-
"""Kaneo #11 (B6) tesztek: zsebpénz XLSX/CSV export + üzenet olvasottság és tartalomkeresés."""
import io
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
work = tempfile.mkdtemp(prefix="kreta_b6_")
db = os.path.join(work, "kreta_adatok.db")
os.environ.update({
    "KRETA_DATA_DIR": work,
    "KRETA_DB_FILE": db,
    "KRETA_CONFIG_FILE": os.path.join(work, "config.json"),
    "KRETA_LOG_FILE": os.path.join(work, "sync.log"),
    "KRETA_CSATOLMANYOK_DIR": os.path.join(work, "csat"),
    "KRETA_SCHEDULER_STATE_FILE": os.path.join(work, "scheduler_state.json"),
})
sys.path.insert(0, str(ROOT))
import app as kreta  # noqa: E402

_hibak = []


def ok(cond, msg):
    print(("  OK   " if cond else "  HIBA ") + msg)
    if not cond:
        _hibak.append(msg)


kreta.init_db_extensions()
conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO kifizetesek (diak_nev, kezdo_datum, zaro_datum, kifizetve, osszeg, tanev)"
    " VALUES (?,?,?,?,?,?)",
    ("Teszt Elek", "2026-10-01", "2026-10-31", 1, 500, "2026/2027"),
)
conn.execute(
    "INSERT INTO kifizetesek (diak_nev, kezdo_datum, zaro_datum, kifizetve, osszeg, tanev)"
    " VALUES (?,?,?,?,?,?)",
    ("Másik Diák", "2026-10-01", "2026-10-31", 0, 300, "2026/2027"),
)
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek, bej_datum, mod, tema, tanev)"
    " VALUES (?,?,?,?,?,?,?,?,?)",
    ("Teszt Elek", "Értékelés", "Matematika", "Jeles (5)", 5, "2026.10.15.", "Röpdolgozat", "Törtek", "2026/2027"),
)
conn.execute(
    "INSERT INTO esemenyek (diak_nev, esemeny_tipus, cim, tartalom, bej_datum, tanev)"
    " VALUES (?,?,?,?,?,?)",
    ("Teszt Elek", "Feljegyzés", "Szaktanári dicséret", "Kiemelkedő órai munka", "2026.10.16.", "2026/2027"),
)
conn.execute(
    "INSERT INTO uzenetek (diak_nev, felado, targy, idopont, szoveg, olvasott, tanev, tanev_forras)"
    " VALUES (?,?,?,?,?,?,?,?)",
    ("Teszt Elek", "Igazgató", "Szülői értekezlet", "2026.10.20. 14:00",
     "Tisztelt Szülők! Csütörtökön 17:00-kor szülői értekezlet lesz a 204-es teremben.",
     0, "2026/2027", "szamitott"),
)
conn.execute(
    "INSERT INTO uzenetek (diak_nev, felado, targy, idopont, szoveg, olvasott, tanev, tanev_forras)"
    " VALUES (?,?,?,?,?,?,?,?)",
    ("Teszt Elek", "Osztályfőnök", "Kirándulás", "2026.10.21. 09:00",
     "Erdei iskola befizetési határidő péntek.",
     1, "2026/2027", "szamitott"),
)
conn.commit()
conn.close()

client = kreta.app.test_client()

print("\n1) CSV export (visszafelé kompatibilis végpont)")
res = client.get("/api/kifizetesek/export.csv")
text = res.get_data(as_text=True)
ok(res.status_code == 200, f"a CSV végpont 200 ({res.status_code})")
ok(text.startswith("\ufeff"), "UTF-8 BOM (Excel-kompatibilis)")
ok("diak_nev;kezdo_datum;zaro_datum;osszeg;kifizetve;kategoria;megjegyzes" in text,
   "a fejléc tartalmazza a kért oszlopokat")
ok("Teszt Elek;2026-10-01;2026-10-31;500;igen;zsebpenz" in text,
   "a sor adatai helyesek")
ok("Másik Diák;2026-10-01;2026-10-31;300;nem;zsebpenz" in text,
   "a kifizetetlen sor is exportálódik")
ok("attachment" in res.headers.get("Content-Disposition", ""), "mellékletként jön")

res = client.get("/api/kifizetesek/export.csv?diak=Teszt%20Elek")
text = res.get_data(as_text=True)
ok("Teszt Elek" in text and "Másik Diák" not in text, "a diák-szűrő működik")

print("\n2) Valódi Excel (.xlsx) export (Kaneo #11)")
res_x = client.get("/api/kifizetesek/export.xlsx")
ok(res_x.status_code == 200, f"az XLSX végpont 200 ({res_x.status_code})")
ok("spreadsheetml.sheet" in (res_x.headers.get("Content-Type") or ""),
   f"XLSX MIME-típus ({res_x.headers.get('Content-Type')})")
ok(".xlsx" in (res_x.headers.get("Content-Disposition") or ""),
   f".xlsx fájlnév ({res_x.headers.get('Content-Disposition')})")

wb = openpyxl.load_workbook(io.BytesIO(res_x.data))
ok(wb.sheetnames == ["Kifizetések", "Tételes zsebpénz"],
   f"két munkalap: {wb.sheetnames}")

ws1 = wb["Kifizetések"]
headers1 = [c.value for c in ws1[1]]
ok(headers1[:5] == ["Dátum", "Gyerek", "Összeg (Ft)", "Kategória", "Megjegyzés"],
   f"Kifizetések fejléc: {headers1[:5]}")
rows1 = list(ws1.iter_rows(min_row=2, values_only=True))
ok(len(rows1) == 2, f"2 kifizetés-sor ({len(rows1)})")
ok(rows1[0][1] == "Másik Diák" and rows1[0][2] == 300 and rows1[0][5] == "nem",
   f"első sor: {rows1[0][:6]}")
ok(rows1[1][1] == "Teszt Elek" and rows1[1][2] == 500 and rows1[1][5] == "igen",
   f"második sor: {rows1[1][:6]}")

ws2 = wb["Tételes zsebpénz"]
headers2 = [c.value for c in ws2[1]]
ok(headers2 == ["Dátum", "Gyerek", "Összeg (Ft)", "Kategória", "Megjegyzés"],
   f"Tételes fejléc: {headers2}")
rows2 = list(ws2.iter_rows(min_row=2, values_only=True))
ok(len(rows2) == 2, f"2 tételes sor (jegy + dicséret): {len(rows2)}")
kategoriak = {r[3] for r in rows2}
ok("Dicséret" in kategoriak and any("Matematika" in k for k in kategoriak),
   f"tételes kategóriák: {kategoriak}")

res_x_diak = client.get("/api/kifizetesek/export.xlsx?diak=Teszt%20Elek")
wb_d = openpyxl.load_workbook(io.BytesIO(res_x_diak.data))
rows_d = list(wb_d["Kifizetések"].iter_rows(min_row=2, values_only=True))
ok(len(rows_d) == 1 and rows_d[0][1] == "Teszt Elek",
   f"XLSX diák-szűrő működik ({len(rows_d)} sor)")

print("\n3) Üzenetek helyi olvasott/olvasatlan állapota és tartalom (Kaneo #11)")
uz_res = client.get("/api/uzenetek")
uz_list = uz_res.get_json() or []
ok(len(uz_list) == 2, f"2 üzenet a listában ({len(uz_list)})")
by_subj = {u["targy"]: u for u in uz_list}
ok(by_subj["Szülői értekezlet"]["olvasott"] is False,
   "az olvasatlan üzenet olvasott=False")
ok(by_subj["Kirándulás"]["olvasott"] is True,
   "az olvasott üzenet olvasott=True")
ok("204-es teremben" in by_subj["Szülői értekezlet"]["szoveg"],
   "a teljes szöveg benne van az /api/uzenetek válaszban (tartalomkeresés alapja)")

msg_id = by_subj["Szülői értekezlet"]["id"]
post_res = client.post(
    f"/api/uzenetek/{msg_id}/olvasott",
    json={"olvasott": True},
)
ok(post_res.status_code == 200 and post_res.get_json().get("olvasott") is True,
   "POST /api/uzenetek/<id>/olvasott -> olvasott=True")

uz_after = {u["id"]: u for u in (client.get("/api/uzenetek").get_json() or [])}
ok(uz_after[msg_id]["olvasott"] is True, "az olvasott állapot perzisztálódott a DB-ben")

post_unread = client.post(
    f"/api/uzenetek/{msg_id}/olvasott",
    json={"olvasott": False},
)
ok(post_unread.status_code == 200 and post_unread.get_json().get("olvasott") is False,
   "visszajelölés olvasatlannak -> olvasott=False")

not_found = client.post("/api/uzenetek/999999/olvasott", json={"olvasott": True})
ok(not_found.status_code == 404, f"nem létező üzenet 404 ({not_found.status_code})")

print("\n4) UI-elemek a sablonban")
html = client.get("/").get_data(as_text=True)
ok('id="btnExportKifizetesXlsx"' in html and "/api/kifizetesek/export.xlsx" in html,
   "a Zsebpénz fülön az Excel (.xlsx) export gomb szerepel")
ok('id="uzenetOlvasottFilter"' in html and 'id="uzenetekOlvasatlanBadge"' in html,
   "az Üzenetek fülön az olvasottság-szűrő és a jelvény szerepel")
ok('id="btnModalToggleOlvasott"' in html,
   "az üzenet modálban az olvasott/olvasatlan váltógomb szerepel")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
