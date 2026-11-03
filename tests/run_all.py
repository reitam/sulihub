# -*- coding: utf-8 -*-
"""
Az összes teszt futtatása.

    python tests/run_all.py

Kilépési kód: 0 = minden teszt OK, 1 = valamelyik bukott.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TESTS = ["test_scheduler.py", "test_a_package.py", "test_pdf_fonts.py", "test_paths.py", "test_new_events.py", "test_migration.py", "test_db_bootstrap.py", "test_deploy.py", "test_ntfy_config.py", "test_hianyzasok.py", "test_api_client.py", "test_api_sync.py", "test_sync_mode.py", "test_shadow.py", "test_data_guard.py", "test_db_guard.py", "test_jegy_suly.py", "test_tanev.py", "test_tanev_migration.py", "test_tanev_sync.py", "test_tanev_api.py", "test_tanev_zaro.py", "test_tanev_ui.py", "test_kommentek.py", "test_statisztika.py", "test_oszlop_szelesseg.py", "test_dashboard.py", "test_mobile_layout.py"]
# A tesztek "→" és ékezetes szöveget írnak a kimenetre; cp1250 konzolon ez
# UnicodeEncodeError-ral elszállna, ezért a gyerekeket UTF-8-ra kényszerítjük.
CHILD_ENV = os.environ.copy()
CHILD_ENV["PYTHONIOENCODING"] = "utf-8"
CHILD_ENV["PYTHONUTF8"] = "1"
failed = []
for name in TESTS:
    print("=" * 64)
    print(">>>", name)
    print("=" * 64)
    result = subprocess.run([sys.executable, str(HERE / name)], cwd=str(ROOT), env=CHILD_ENV)
    if result.returncode != 0:
        failed.append(name)
        print(f"!!! {name}: kilépési kód {result.returncode}")

print("=" * 64)
if failed:
    print("EREDMÉNY: BUKOTT ->", ", ".join(failed))
    sys.exit(1)
print("EREDMÉNY: MINDEN TESZT OK")
sys.exit(0)
