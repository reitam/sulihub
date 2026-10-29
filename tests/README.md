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
