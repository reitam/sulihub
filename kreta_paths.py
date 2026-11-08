# -*- coding: utf-8 -*-
"""
Fájlrendszer-útvonalak (KRÉ-14 #93, #98).

Egyetlen igazságforrás az adat-/log-/csatolmány-útvonalakra. Az értékek
környezeti változókkal írhatók felül.

**Alapértelmezett elrendezés (v2.0.0-tól): minden futásidejű fájl a `data/` alatt.**

| Env | Alapérték |
|---|---|
| `KRETA_DATA_DIR` | `data` |
| `KRETA_DB_FILE` | `<DATA_DIR>/kreta_adatok.db` |
| `KRETA_CONFIG_FILE` | `<DATA_DIR>/config.json` |
| `KRETA_LOG_FILE` | `<DATA_DIR>/sync.log` |
| `KRETA_CSATOLMANYOK_DIR` | `<DATA_DIR>/csatolmanyok` |
| `KRETA_SCHEDULER_STATE_FILE` | `<DATA_DIR>/scheduler_state.json` |
| `KRETA_VERSION_FILE` | `<DATA_DIR>/version.txt` |
| `KRETA_RIPORTKARTYA_DIR` | `<DATA_DIR>/riportkartyak` |

**Visszafelé kompatibilitás:** ha a `KRETA_DATA_DIR` nincs beállítva, a `data/`
alatt még nincs adatbázis, viszont a projekt gyökerében van (`kreta_adatok.db`),
akkor a régi (gyökér) elrendezés marad, és a naplóba figyelmeztetés kerül. A
migráció: `python tools/migrate_local_data.py`. Dockerben a compose explicit
`KRETA_DATA_DIR=/app/data`-t ad, ezért ott ez az ág soha nem lép be.

Fontos: importáláskor **nem hoz létre semmit** (se könyvtárat, se fájlt).
"""
import os

# A projekt gyökere (a scraper gyerekprocessz és az init-db subprocess innen indul).
APP_DIR = os.path.dirname(os.path.abspath(__file__))

_data_env = os.environ.get("KRETA_DATA_DIR")

# Legacy felismerés: nincs data/-beli DB, de a gyökérben van → régi elrendezés.
_legacy_db = os.path.join(APP_DIR, "kreta_adatok.db")
_new_db = os.path.join(APP_DIR, "data", "kreta_adatok.db")
LEGACY_LAYOUT = False
if _data_env:
    DATA_DIR = _data_env
elif os.path.exists(_legacy_db) and not os.path.exists(_new_db):
    DATA_DIR = "."
    LEGACY_LAYOUT = True
else:
    DATA_DIR = "data"

DB_FILE = os.environ.get("KRETA_DB_FILE", os.path.join(DATA_DIR, "kreta_adatok.db"))
CONFIG_FILE = os.environ.get("KRETA_CONFIG_FILE", os.path.join(DATA_DIR, "config.json"))
LOG_FILE = os.environ.get("KRETA_LOG_FILE", os.path.join(DATA_DIR, "sync.log"))
LOG_MAX_BYTES = int(os.environ.get("KRETA_LOG_MAX_BYTES", 1000000))
LOG_BACKUP_COUNT = int(os.environ.get("KRETA_LOG_BACKUP_COUNT", 2))
# Az /api/logs ennyi bájtot ad vissza a napló végéről (a UI-nak elég).
LOG_API_MAX_BYTES = int(os.environ.get("KRETA_LOG_API_MAX_BYTES", 300000))

_csat_env = os.environ.get("KRETA_CSATOLMANYOK_DIR")
if _csat_env:
    CSATOLMANYOK_DIR = _csat_env
elif LEGACY_LAYOUT:
    # Régi elrendezés: a csatolmányok a Flask statikus mappájában vannak.
    CSATOLMANYOK_DIR = os.path.join("static", "csatolmanyok")
else:
    CSATOLMANYOK_DIR = os.path.join(DATA_DIR, "csatolmanyok")

# Az ütemező állapota (legutóbbi futás, eredmény) — a data köteten él, hogy
# konténer-újraindítás/deploy után is megmaradjon a 3 órás ciklus.
SCHEDULER_STATE_FILE = os.environ.get(
    "KRETA_SCHEDULER_STATE_FILE", os.path.join(DATA_DIR, "scheduler_state.json")
)
# A deploy által a data kötetre írt verziószám (a felületen jelenik meg).
VERSION_FILE = os.environ.get("KRETA_VERSION_FILE", os.path.join(DATA_DIR, "version.txt"))
# A generált riportkártya PDF-ek (Kaneo #82) — gyermekenként, visszamenőlegesen.
RIPORTKARTYA_DIR = os.environ.get(
    "KRETA_RIPORTKARTYA_DIR", os.path.join(DATA_DIR, "riportkartyak")
)

if LEGACY_LAYOUT:
    print("[Útvonalak] Régi (gyökér) adatelrendezés — átköltöztetés: "
          "python tools/migrate_local_data.py")


def ensure_data_dir() -> bool:
    """Létrehozza a DATA_DIR-t (ha nem `.`), hogy az első indítás ne hasaljon el.

    Szándékosan **nem** az import mellékhatása: az app indulásakor és a scraper
    indulásakor hívjuk. Friss klónnál / törölt `data/` mappánál ez menti meg a
    „unable to open database file" hibától (KRÉ-14 audit, F2).
    """
    if not DATA_DIR or DATA_DIR == ".":
        return True
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        return True
    except OSError as exc:
        print(f"[Útvonalak] A data könyvtár nem hozható létre ({DATA_DIR}): {exc}")
        return False
