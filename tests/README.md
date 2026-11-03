# Tesztek

Futtatás (a projekt gyökeréből):

```bash
python tests/run_all.py
```

Kilépési kód: `0` = minden teszt OK, `1` = valamelyik bukott.

| Fájl | Mit ellenőriz |
|---|---|
| `test_scheduler.py` | Ütemező: config-parse/clamp, időablak (átforduló is), `next_run` az ablakon belül, perzisztencia, dupla indítás elleni védelem, API végpontok, `interrupted`/`running`, napló-pótlás, memória-fallback |
| `test_a_package.py` | Részleges hiba (`done_with_errors` + hibás diákok), ntfy payload/throttle, napló-rotáció, `/api/logs` tail; a futás tanéve (`sync_runs.tanev`, tanévváltás jelezhető, `/api/sync/status.tanev`) |
| `test_pdf_fonts.py` | PDF magyar `ő/Ő/ű/Ű` megjelenítés (a kiszolgált PDF szövegkinyerésével) |
| `test_paths.py` | Adat-/log-/csatolmány-útvonalak feloldása (lokális és Docker-elrendezés) |
| `test_new_events.py` | Új események kimutatása a szinkron előtti/utáni állapot különbségéből |
| `test_migration.py` | Egyszeri migráció: régi `scheduler_state.json` → `sync_runs`/`app_meta` |
| `test_hianyzasok.py` | Hiányzások/igazolások: táblák, mentés + dedupe, új-hiányzás számítás, havi API-összesítő (igazolt/igazolatlan óra, késés), push-szöveg |
| `test_api_client.py` | Termelési API-kliens (`kreta_api.py`): login/refresh/401-retry/implicit belépés fake HTTP-vel, dátumszeletek, dátum/HTML konverzió, normalizálás, órarend-elem és fogadóóra, üzenetszűrés |
| `test_api_sync.py` | API-szinkron adatkörök: lekérési ablak (magyar/ISO dátum), órarend-join párhuzamos csoportokkal, táboros téma megőrzése, jegyek (Magatartás/Szorgalom 0 értékkel), házi `kesz` megőrzés, számonkérés, feljegyzés, órarend + fogadóóra, üzenetek (inkrementális, csatolmány-fallback), stabil ID-k, igazolások |
| `test_sync_mode.py` | `SYNC_MODE` feloldás, forrásnapló, API-hiba → Playwright fallback, duplikációvédelem valódi SQLite-on |
| `test_shadow.py` | Árnyék mód: DB-másolat, táblánkénti összehasonlítás (kulcs + mezők), a valódi DB érintetlensége, `NEW_*` visszaállítás |
| `test_data_guard.py` | Adatvédelem: üres API-válasz nem töröl, 50%-os küszöb (`KRETA_SYNC_MIN_RATIO`), órarend csak teljes ürülésnél véd, szolgáltatói hiba fallbackhez |
| `test_db_guard.py` | DB-séma őr: zárolt adatbázisnál nincs init-db subprocess, az önjavítás nem kapcsol ki véglegesen, a zárolás után bootstrapol |
| `test_jegy_suly.py` | Jegyek súlyszázaléka: webes tooltip `data-suly` szövegének parse-olása, mobil API `SulySzazalekErteke` normalizálása (szám/sztring/null), DB-oszlop és mentés (0 = nincs adat) |
| `test_statisztika.py` | `/api/statisztika`: súlyozott tanulmányi átlag (0%-os súly kimarad), súlyadat nélküli visszaesés az egyszerű átlagra, kikapcsolt zsebpénz (`rewards_enabled: false`, statisztika él, pénz 0); `/api/atlagok`: tantárgyi átlagok havi bontással; `/api/dashboard`: diákonkénti átlag, kifizetett időszak levonása, igazolatlan óra |
| `test_dashboard.py` | Áttekintés dashboard valódi böngészőben: csempeszámok (heti határidők, új jegyek/üzenetek, igazolatlan hiányzás, kifizetetlen zsebpénz), gyermekkártyák, csempére kattintás → szűrt eseménylista, visszalépés, szűrőpanel láthatósága, zárt átlag-accordion kinyitása; tanév-választó (alap = aktuális tanév, „Összes tanév" módban nincs átlag) |
| `test_tanev.py` | Tanév-számítás (Kaneo #40): határnapok, szökőév, KRÉTA magyar és ISO dátumok, `tanev_bounds`, `current_tanev` injektált dátummal, `KRETA_TODAY`/`KRETA_TANEV_KEZDO` env, táblánkénti dátummező (`row_tanev`), `teljesen_lekert` a törlési jogosultsághoz |
| `test_tanev_migration.py` | Tanév-séma migráció régi (oszlop nélküli) DB-n: 5 tábla + `sync_runs` kap oszlopot, az `orarend` nem; backfill két tanévre + ismeretlen dátum; ID-stabilitás; idempotens második futás |
| `test_tanev_sync.py` | Tanév-tudatos szinkron éles KRÉTA nélkül: az API-ablak a tanév elejétől indul, csak a tanévbe eső sorok cserélődnek, a korábbi tanév érintetlen, az ablakon túli (jövőbeli) sor nem törlődik; **óra-bomba** (08-31 → 09-01 üres válasz → 09-03 új adat) |
| `test_tanev_api.py` | Tanév-szűrés az API-n két tanév adatán: `/api/tanevek`, `?tanev=` az események/átlagok/statisztika/dashboard végpontokon; a korábbi tanév kifizetése nem csökkenti az új egyenlegét; `POST /api/kifizetes` a tanévet is beírja (azonnali levonás) |
| `test_tanev_zaro.py` | Tanévzáró futás backendje (#52): `KRETA_ZARO_TANEV` / `tanev=` a teljes lezárt tanév ablaka, a +90 napos előretekintés is, `sync_runs.tanev_zaro`, `/api/sync/start` validáció (csak lezárt tanév) és a `start_sync` bekötése |
| `test_tanev_ui.py` | Tanév-UI bugfixek valódi böngészőben: #51 a csempék frissülnek késleltetett esemény-válasz mellett is; #52 „Tanév lezárása" gomb a lezárt tanévvel hívja a `/api/sync/start`-ot; #53 a dátum-/hónapválasztók a tanév határain belül maradnak |
| `test_oszlop_szelesseg.py` | Oszlopszélesség valódi böngészőben: az átméretezés/húzás nem rendezi át a táblát, a fogantyúk megvannak a hiányzások/igazolások táblán is |
| `test_mobile_layout.py` | Mobil elrendezés valódi böngészőben (393 px): nincs vízszintes túlcsordulás egyik fülön sem, avatar, összecsukott táblázat, hiányzások fül |

## Függőségek

A tesztek a futó alkalmazás függőségein (flask, reportlab) túl **opcionálisan** használják:

- `pypdf` — a PDF szövegének kinyerése (e nélkül a PDF-teszt szövegellenőrzése kimarad),
- `pymupdf` (`fitz`) — a beágyazott betűk listázása (csak diagnosztika).

Ezek nélkül a tesztek lefutnak, csak a kapcsolódó ellenőrzések maradnak ki.

## Megjegyzés

A tesztek izolált temp könyvtárban dolgoznak (`tempfile`), a valódi adatbázist és
`config.json`-t nem érintik. A `config.json`-t, DB-t és `sync.log`-ot a teszt
környezeti változókkal irányítja át.
