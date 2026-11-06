# KRÉ-14 refaktor — összefoglaló (2026-11-06)

**Ág:** `refactor/kre14-monolit` (a `main`-ról indítva)
**Kiadás:** v2.0.0 (a felhasználó döntése: élesítés csak a teljesen kész verzióval)
**Cél:** a monolit `app.py` (~4 100 sor) és az egyfájlos frontend (~4 480 sor) szétbontása
**viselkedésváltozás nélkül**.

## Fázisok és commitok

| # | Kaneo | Commit | Mit hozott |
|---|---|---|---|
| 1 | #92 | `918993d` | `tests/test_routes_contract.py` (42 rule rögzítve), `tools/api_snapshot.py` (17 végpont diff) |
| 2 | #93 | `01a9c90` | `kreta_paths.py`, `kreta_db.py`; `app.py` 4 107 → 3 474 sor |
| 3 | #94 | `51dd704` | `kreta_settings.py`, `views_common.py` |
| 4 | #95 | `477d7b9` | `views_pages/events/orarend/messages/absences` blueprintek |
| 5 | #96 | `fc9497d` | `kreta_exports.py`, `views_stats.py`, `views_rewards.py`; `app.py` ~1 180 sor |
| 6 | #97 | `9705da2` | `static/js/core.js` + `static/js/app-main.js`; `index.html` 4 478 → 1 554 sor |
| 7 | #98 | `57f863a` | futásidejű adatok `data/` alá, legacy fallback, `tools/migrate_local_data.py` |
| 8 | — | (docs commit) | dokumentáció + ez az összefoglaló |

## Végeredmény

- **`app.py` ~1 180 sor** (a stateful mag: szinkron, ütemező, ntfy, napló, auth).
- **8 prefix nélküli blueprint** a HTTP-réteghez; az URL-ek bájtazonosak.
- **Közös rétegek:** `kreta_paths`, `kreta_db`, `kreta_settings`, `views_common`.
- **Frontend:** nincs inline script; `core.js` (globális segédek) + `app-main.js`.
- **Adatok:** `data/` (DB, config, napló, tokenek, böngészőprofil, csatolmányok).
- **Tesztek:** 1158 ellenőrzés / 39 csomag (fast 34/1006, browser 5/152).

## Hogyan maradt bizonyítottan változatlan a viselkedés

1. **Route-contract** (`test_routes_contract.py`): a Flask `url_map` rule+metódus listája
   fagyasztva; minden fázis után zöld.
2. **API-pillanatkép** (`tools/api_snapshot.py`): 17 olvasó végpont válasza a valódi DB
   másolatán; minden fázis után `--diff` = „nincs eltérés".
3. **Fast suite** minden fázis után; a frontend-fázis után a **teljes browser suite** is.
4. A PDF/XLSX/ICS exportokat kézi füstteszt is ellenőrizte (méret + magic bytes).

## Adat-migráció (lokálisan)

```bash
# az app álljon le előtte
python tools/migrate_local_data.py --dry-run   # mit tenne
python tools/migrate_local_data.py             # átmozgat a data/ alá
python tools/migrate_local_data.py --rollback  # ha valami nem stimmel
```

A régi (gyökér) elrendezés egy kiadásig még működik — ilyenkor induláskor figyelmeztetés
jelenik meg a naplóban. A Docker érintetlen (`KRETA_DATA_DIR=/app/data` a compose-ban).

## Amit szándékosan NEM mozgattunk

- `sync_state`, `sync_lock`, az ütemező-szál, NTFY és naplózás az `app.py`-ban maradt:
  a tesztek `kreta.<név>` monkeypatch-elést használnak; kiszervezésük csendes
  teszthamisítást okozhat.
- A `tools/snapshots/` (API-baseline) nem verziózott: valódi, személyes adatot tartalmaz.
- Az inline JS tematikus továbbontása (8–11 fájl) külön jegy lehet; a mostani két fájl
  megtartja a globális függvényneveket, amiket a Playwright-tesztek hívnak.

## Nyitott lépések

1. A felhasználó átnézi az ágat (`git log --oneline main..refactor/kre14-monolit`).
2. Merge a `main`-be (a CI a main pushra fast+browser jobot futtat).
3. `.\deploy.ps1 -Release v2.0.0` (SSH jelszó), utána `/health` = `v2.0.0`, 9 fül,
   PDF/XLSX/ICS, és a `data/`-s indulás ellenőrzése.
