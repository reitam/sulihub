# -*- coding: utf-8 -*-
"""Tanév-archívum (Kaneo #139): zárt tanév egyszeri, ellenőrizhető ZIP-je.

A zárt tanév adatai pótolhatatlanok (a KRÉTA a korábbi tanéveket nem adja vissza),
ezért a tanév lezárásakor készül egy ZIP:

- táblánként JSON + CSV (a tanévre szűrve),
- egy kombinált Excel (`adatok.xlsx`),
- diákonként a teljes tanévről szóló PDF-bizonyítvány,
- `manifest.json` (darabszámok, fájlméretek, SHA-256),
- `checksums.sha256` és a ZIP mellé írt `.sha256` ellenőrző fájl.

A záráskor a kanonikus `<év>.zip` készül. A **kézi export** nyitott tanévnél
`<év>_manual_<időbélyeg>.zip` néven jön létre, hogy ne blokkolja a záráskori
végleges archívumot; `--final` a kanonikus név kényszerítéséhez.

A művelet **idempotens**: ha a ZIP már létezik, nem írja felül. A generálás
ideiglenes könyvtárban történik, a kész ZIP atomikusan kerül a helyére.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

import kreta_exports
import kreta_tanev
from kreta_db import get_db_connection
from kreta_paths import DATA_DIR
from kreta_settings import get_app_version

ARCHIVE_FORMAT = "sulihub-tanev-archivum"
ARCHIVE_VERSION = 1
ARCHIVE_DIR_NAME = "tanev_archivum"
ARCHIVE_LOCK = threading.Lock()

TABLES_WITH_TANEV = (
    "esemenyek", "uzenetek", "hianyzasok", "igazolasok", "kifizetesek",
    "sync_runs", "tanevek", "tanulo_tanev_uid",
)
TABLES = TABLES_WITH_TANEV + ("orarend", "sajat_orarend")


def archive_dir() -> Path:
    return Path(DATA_DIR) / ARCHIVE_DIR_NAME


def archive_path(tanev: str, manual: bool = False, stamp: str | None = None) -> Path:
    slug = re.sub(r"[^0-9A-Za-z]+", "-", str(tanev or "")).strip("-") or "ismeretlen"
    if manual:
        stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
        return archive_dir() / (slug + "_manual_" + stamp + ".zip")
    return archive_dir() / (slug + ".zip")


def _year_is_closed(tanev: str) -> bool:
    try:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT allapot FROM tanevek WHERE tanev = ?", (tanev,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return bool(row and str(row[0]) == "lezart")


def checksum_path(zip_path: Path) -> Path:
    return zip_path.with_name(zip_path.name + ".sha256")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_name(name: str, limit: int = 50) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "")).strip("._")
    return (text[:limit] or "diak")


def _cell(value):
    """CSV/Excel cella: None -> üres, dict/list -> JSON szöveg."""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _table_sql(table: str, tanev: str, kezdo: str, zaro: str):
    if table in TABLES_WITH_TANEV:
        return f"SELECT * FROM {table} WHERE tanev = ?", (tanev,)
    if table == "orarend":
        return (
            "SELECT * FROM orarend WHERE substr(kezdo_idopont, 1, 10) >= ?"
            " AND substr(kezdo_idopont, 1, 10) <= ?",
            (kezdo, zaro),
        )
    if table == "sajat_orarend":
        return (
            "SELECT * FROM sajat_orarend WHERE"
            " (ervenyes_tol IS NULL OR ervenyes_tol = '' OR substr(ervenyes_tol, 1, 10) <= ?)"
            " AND (ervenyes_ig IS NULL OR ervenyes_ig = '' OR substr(ervenyes_ig, 1, 10) >= ?)",
            (zaro, kezdo),
        )
    raise ValueError("Ismeretlen tábla: %s" % table)


def _read_table(conn, table: str, tanev: str, kezdo: str, zaro: str):
    sql, params = _table_sql(table, tanev, kezdo, zaro)
    cur = conn.execute(sql, params)
    columns = [d[0] for d in cur.description]
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    return columns, rows


def _write_json(path: Path, rows):
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8")


def _write_csv(path: Path, columns, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";", lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_cell(row.get(c)) for c in columns])


def _write_xlsx(path: Path, table_data):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for table, columns, rows in table_data:
        ws = wb.create_sheet(title=table[:31])
        ws.append(columns)
        for row in rows:
            ws.append([_cell(row.get(c)) for c in columns])
        ws.freeze_panes = "A2"
        for idx, col in enumerate(columns, 1):
            sample = [str(col)] + [str(_cell(r.get(col))) for r in rows[:100]]
            width = min(max(len(s) for s in sample) + 2, 40)
            ws.column_dimensions[get_column_letter(idx)].width = max(10, width)
    buf = io.BytesIO()
    wb.save(buf)
    path.write_bytes(buf.getvalue())


def _students_for_year(conn, tanev: str):
    students = set()
    for table in ("esemenyek", "uzenetek", "hianyzasok", "igazolasok", "kifizetesek"):
        try:
            for (name,) in conn.execute(
                    f"SELECT DISTINCT diak_nev FROM {table}"
                    " WHERE tanev = ? AND diak_nev IS NOT NULL AND diak_nev != ''",
                    (tanev,)):
                students.add(str(name).strip())
        except sqlite3.Error:
            continue
    return sorted(s for s in students if s)


def _write_report_pdfs(conn, out_dir: Path, tanev: str, kezdo, zaro, manifest, warnings):
    """Diákonként a teljes tanév PDF-bizonyítványa (a meglévő riport-generátorral)."""
    report_dir = out_dir / "riportok"
    report_dir.mkdir(parents=True, exist_ok=True)
    for diak in _students_for_year(conn, tanev):
        try:
            adatok = kreta_exports._riport_adatok(diak, tanev, kezdo, zaro)
            pdf = kreta_exports._riport_pdf(diak, tanev, "ev", kezdo, zaro, adatok)
            name = "riportok/riport_%s.pdf" % _safe_name(diak)
            (out_dir / name).write_bytes(pdf)
            manifest["report_pdfs"].append({"diak": diak, "file": name})
        except Exception as exc:  # noqa: BLE001 — egy PDF hibája ne akassza meg a ZIP-et
            warnings.append(f"{diak}: PDF hiba ({type(exc).__name__}: {exc})")


def _file_manifest(root: Path):
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "checksums.sha256":
            continue
        files.append({
            "name": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return files


def _write_checksums(root: Path):
    lines = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "checksums.sha256":
            continue
        lines.append("%s  %s" % (_sha256(path), path.relative_to(root).as_posix()))
    (root / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_archive_info(path: Path, tanev: str, kezdo, zaro, manifest):
    rows = manifest.get("tables", {})
    lines = [
        "SuliHub tanév-archívum",
        "======================",
        "",
        "Tanév: %s" % tanev,
        "Időszak: %s – %s" % (kezdo.isoformat(), zaro.isoformat()),
        "Készült: %s" % manifest.get("created_at", ""),
        "Alkalmazásverzió: %s" % manifest.get("app_version", ""),
        "",
        "Táblák:",
    ]
    for name, info in sorted(rows.items()):
        lines.append("  - %s: %s sor" % (name, info.get("rows", 0)))
    lines += [
        "",
        "Ellenőrzés: checksums.sha256 (és a ZIP melletti .sha256 fájl).",
        "A fájlok a ZIP-ben: adatok/ (JSON + CSV), adatok.xlsx, riportok/ (PDF), manifest.json.",
        "",
    ]
    if manifest.get("warnings"):
        lines += ["Figyelmeztetések:"] + ["  - " + w for w in manifest["warnings"]] + [""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _build_archive(out_dir: Path, tanev: str, kezdo, zaro):
    kezdo_iso, zaro_iso = kezdo.isoformat(), zaro.isoformat()
    manifest = {
        "format": ARCHIVE_FORMAT,
        "version": ARCHIVE_VERSION,
        "tanev": tanev,
        "kezdo": kezdo_iso,
        "zaro": zaro_iso,
        "created_at": datetime.now().replace(microsecond=0).isoformat(),
        "app_version": get_app_version(),
        "tables": {},
        "files": [],
        "report_pdfs": [],
        "warnings": [],
    }
    data_dir = out_dir / "adatok"
    data_dir.mkdir(parents=True, exist_ok=True)

    conn = get_db_connection()
    try:
        table_data = []
        for table in TABLES:
            try:
                columns, rows = _read_table(conn, table, tanev, kezdo_iso, zaro_iso)
            except sqlite3.Error as exc:
                manifest["warnings"].append(f"{table}: {exc}")
                continue
            _write_json(data_dir / (table + ".json"), rows)
            _write_csv(data_dir / (table + ".csv"), columns, rows)
            manifest["tables"][table] = {
                "rows": len(rows),
                "json": "adatok/%s.json" % table,
                "csv": "adatok/%s.csv" % table,
            }
            table_data.append((table, columns, rows))

        _write_xlsx(out_dir / "adatok.xlsx", table_data)
        _write_report_pdfs(conn, out_dir, tanev, kezdo, zaro, manifest, manifest["warnings"])
    finally:
        conn.close()

    _write_archive_info(out_dir / "ARCHIVE_INFO.txt", tanev, kezdo, zaro, manifest)
    manifest["files"] = _file_manifest(out_dir)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8")
    _write_checksums(out_dir)
    return manifest


def create_tanev_archive(tanev: str, force: bool = False, manual: bool = False,
                         output: str | Path | None = None) -> Path:
    """A tanév ZIP-jének elkészítése.

    - `manual=False`: a kanonikus `<év>.zip` (automatikus zárásnál);
    - `manual=True`: külön `<év>_manual_<időbélyeg>.zip`, hogy egy nyitott tanév
      teszt-exportja ne blokkolja a záráskori végleges archívumot.
    Ha a célfájl már létezik és nincs `force`, változatlanul hagyja.
    """
    tanev = str(tanev or "").strip()
    if not re.fullmatch(r"\d{4}/\d{4}", tanev):
        raise ValueError("Érvénytelen tanév: %r" % tanev)
    kezdo, zaro = kreta_tanev.tanev_bounds(tanev)
    if not kezdo or not zaro:
        raise ValueError("A tanév határai nem számíthatók: %s" % tanev)

    if output:
        target = Path(output)
    elif manual:
        target = archive_path(tanev, manual=True)
        base = target
        counter = 1
        while target.exists():
            target = base.with_name(base.stem + "-%d" % counter + base.suffix)
            counter += 1
    else:
        target = archive_path(tanev)
    with ARCHIVE_LOCK:
        if target.exists() and not force:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix=".archive-", dir=str(target.parent)))
        try:
            _build_archive(tmp_dir, tanev, kezdo, zaro)
            tmp_zip = target.with_name(target.name + ".tmp")
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for path in sorted(tmp_dir.rglob("*")):
                    if path.is_file():
                        zf.write(path, path.relative_to(tmp_dir).as_posix())
            os.replace(tmp_zip, target)
            checksum_path(target).write_text(
                "%s  %s\n" % (_sha256(target), target.name), encoding="utf-8")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    return target


def verify_archive(zip_path) -> bool:
    """A ZIP külső és belső SHA-256 ellenőrzése."""
    zip_path = Path(zip_path)
    sidecar = checksum_path(zip_path)
    if not zip_path.exists() or not sidecar.exists():
        return False
    try:
        expected = sidecar.read_text(encoding="utf-8").split()[0].strip()
        if expected != _sha256(zip_path):
            return False
        with zipfile.ZipFile(zip_path) as zf:
            if "checksums.sha256" not in zf.namelist():
                return False
            for line in zf.read("checksums.sha256").decode("utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                digest, name = line.split(None, 1)
                name = name.strip()
                data = zf.read(name)
                if hashlib.sha256(data).hexdigest() != digest:
                    return False
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return False
    return True


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="SuliHub tanév-archívum készítése")
    parser.add_argument("tanev", nargs="+", help="pl. 2025/2026")
    parser.add_argument("--force", action="store_true", help="a kanonikus ZIP felülírása")
    parser.add_argument("--manual", action="store_true",
                        help="külön _manual_ ZIP (nyitott tanév tesztjéhez)")
    parser.add_argument("--final", action="store_true",
                        help="a kanonikus ZIP kényszerítése akkor is, ha a tanév nyitott")
    args = parser.parse_args(argv)
    for tanev in args.tanev:
        closed = _year_is_closed(tanev)
        manual = args.manual or (not args.final and not closed)
        path = create_tanev_archive(tanev, force=args.force, manual=manual)
        print("%s -> %s (%s%s)" % (
            tanev, path, "OK" if verify_archive(path) else "ELLENŐRZÉS HIBA",
            ", manual" if manual else ""))


if __name__ == "__main__":
    main()
