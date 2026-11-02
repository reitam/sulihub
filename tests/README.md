# Tesztek

Futtatás (a projekt gyökeréből):

```bash
python tests/run_all.py
```

Kilépési kód: `0` = minden teszt OK, `1` = valamelyik bukott.

| Fájl | Mit ellenőriz |
|---|---|
| `test_scheduler.py` | Ütemező: config-parse/clamp, időablak (átforduló is), `next_run` az ablakon belül, perzisztencia, dupla indítás elleni védelem, API végpontok, `interrupted`/`running`, napló-pótlás, memória-fallback |
| `test_a_package.py` | Részleges hiba (`done_with_errors` + hibás diákok), ntfy payload/throttle, napló-rotáció, `/api/logs` tail |
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
