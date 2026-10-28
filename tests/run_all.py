# -*- coding: utf-8 -*-
"""
Az összes teszt futtatása.

    python tests/run_all.py

Kilépési kód: 0 = minden teszt OK, 1 = valamelyik bukott.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TESTS = ["test_scheduler.py", "test_a_package.py", "test_pdf_fonts.py", "test_paths.py"]

failed = []
for name in TESTS:
    print("=" * 64)
    print(">>>", name)
    print("=" * 64)
    result = subprocess.run([sys.executable, str(HERE / name)], cwd=str(ROOT))
    if result.returncode != 0:
        failed.append(name)
        print(f"!!! {name}: kilépési kód {result.returncode}")

print("=" * 64)
if failed:
    print("EREDMÉNY: BUKOTT ->", ", ".join(failed))
    sys.exit(1)
print("EREDMÉNY: MINDEN TESZT OK")
sys.exit(0)
