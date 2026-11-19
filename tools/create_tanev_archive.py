# -*- coding: utf-8 -*-
"""Tanév-archívum készítése parancssorból (Kaneo #139).

Használat:
    python tools/create_tanev_archive.py 2025/2026
    python tools/create_tanev_archive.py 2025/2026 2026/2027
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kreta_archive  # noqa: E402

if __name__ == "__main__":
    kreta_archive.main()
