# -*- coding: utf-8 -*-
"""
Fájlrendszer-útvonalak (KRÉ-14 #93).

Egyetlen igazságforrás az adat-/log-/csatolmány-útvonalakra. Az értékek
környezeti változókkal írhatók felül; az alapértékek **változatlanok** (a
lokális Windows-futtatás és a Docker is ugyanazt kapja, mint eddig):

| Env | Alapérték |
|---|---|
| `KRETA_DATA_DIR` | `.` (a projekt könyvtára) |
| `KRETA_DB_FILE` | `<DATA_DIR>/kreta_adatok.db` |
| `KRETA_CONFIG_FILE` | `<DATA_DIR>/config.json` |
| `KRETA_LOG_FILE` | `<DATA_DIR>/sync.log` |
| `KRETA_CSATOLMANYOK_DIR` | `static/csatolmanyok` |
| `KRETA_SCHEDULER_STATE_FILE` | `<DATA_DIR>/scheduler_state.json` |
| `KRETA_VERSION_FILE` | `<DATA_DIR>/version.txt` |

Fontos: importáláskor **nem hoz létre semmit** (se könyvtárat, se fájlt).
"""
import os

# Alapból minden az aktuális könyvtárban él (lokális Windows-futtatás, változatlan
# viselkedés). Dockerben a KRETA_DATA_DIR=/app/data (bind mount) — így az adatbázis,
# a config.json, a sync.log és a csatolmányok a HDD-s adatköteten maradnak.
DATA_DIR = os.environ.get("KRETA_DATA_DIR", ".")
DB_FILE = os.environ.get("KRETA_DB_FILE", os.path.join(DATA_DIR, "kreta_adatok.db"))
CONFIG_FILE = os.environ.get("KRETA_CONFIG_FILE", os.path.join(DATA_DIR, "config.json"))
LOG_FILE = os.environ.get("KRETA_LOG_FILE", os.path.join(DATA_DIR, "sync.log"))
LOG_MAX_BYTES = int(os.environ.get("KRETA_LOG_MAX_BYTES", 1000000))
LOG_BACKUP_COUNT = int(os.environ.get("KRETA_LOG_BACKUP_COUNT", 2))
# Az /api/logs ennyi bájtot ad vissza a napló végéről (a UI-nak elég).
LOG_API_MAX_BYTES = int(os.environ.get("KRETA_LOG_API_MAX_BYTES", 300000))
CSATOLMANYOK_DIR = os.environ.get("KRETA_CSATOLMANYOK_DIR", os.path.join("static", "csatolmanyok"))
# Az ütemező állapota (legutóbbi futás, eredmény) — a data köteten él, hogy
# konténer-újraindítás/deploy után is megmaradjon a 3 órás ciklus.
SCHEDULER_STATE_FILE = os.environ.get(
    "KRETA_SCHEDULER_STATE_FILE", os.path.join(DATA_DIR, "scheduler_state.json")
)
# A deploy által a data kötetre írt verziószám (a felületen jelenik meg).
VERSION_FILE = os.environ.get("KRETA_VERSION_FILE", os.path.join(DATA_DIR, "version.txt"))

# A projekt gyökere (a scraper gyerekprocessz és az init-db subprocess innen indul).
APP_DIR = os.path.dirname(os.path.abspath(__file__))
