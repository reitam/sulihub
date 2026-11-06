# -*- coding: utf-8 -*-
"""
Beállítások (KRÉ-14 #94): config.json, verzió, órarend-színek.

Az `app.py`-ból kiemelve, viselkedésváltozás nélkül. A `config.json` a data
köteten él; hiányzó/hibás fájl esetén üres dict (az app elindul, az ütemező
kikapcsol). **Nem importálhatja az `app`-ot.**
"""
import json
import os
import re

from kreta_db import get_meta
from kreta_paths import CONFIG_FILE, VERSION_FILE


def get_app_version():
    """A deploy által a data kötetre írt verzió (version.txt), pl. 'v1.1.1'."""
    try:
        with open(VERSION_FILE, "r", encoding="utf-8-sig") as f:
            version = f.read().strip()
        return version or "dev"
    except OSError:
        return "dev"


def load_config():
    if os.path.exists(CONFIG_FILE):
        # utf-8-sig: a Windows Notepad/PowerShell által írt BOM-ot is kezeli,
        # különben egy BOM-os config.json-tól nem indulna el az alkalmazás.
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except ValueError as e:
            print(f"[Konfiguráció hiba] A {CONFIG_FILE} nem érvényes JSON: {e}")
            return {}
    return {}


# ── Órarend-színek (Kaneo #56) ────────────────────────────────────────────
_HEX_SZIN = re.compile(r"^#[0-9a-fA-F]{6}$")


def _orarend_szinek() -> dict:
    """A diák→szín térkép: config alap, app_meta felülírással; csak érvényes hex."""
    colors = {}
    cfg = (load_config() or {}).get("ORAREND_SZINEK") or {}
    if isinstance(cfg, dict):
        for name, value in cfg.items():
            if isinstance(value, str) and _HEX_SZIN.match(value.strip()):
                colors[str(name)] = value.strip()
    raw = get_meta("orarend_szinek", "")
    if raw:
        try:
            db_colors = json.loads(raw)
            if isinstance(db_colors, dict):
                for name, value in db_colors.items():
                    if isinstance(value, str) and _HEX_SZIN.match(value.strip()):
                        colors[str(name)] = value.strip()
        except (TypeError, ValueError):
            pass
    return colors
