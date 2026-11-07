# Tesztek

Futtatás (a projekt gyökeréből):

```bash
python tests/run_all.py
```

Kilépési kód: `0` = minden teszt OK, `1` = valamelyik bukott.

| Fájl | Mit ellenőriz |
|---|---|
| `test_scheduler.py` | Ütemező: config-parse/clamp, időablak (átforduló is), `next_run` az ablakon belül, perzisztencia, dupla indítás elleni védelem, API végpontok, `interrupted`/`running`, napló-pótlás, memória-fallback |
| `test_a_package.py` | Részleges hiba (`done_with_errors` + hibás diákok), ntfy payload/throttle, napló-rotáció, `/api/logs` tail; a futás tanéve (`sync_runs.tanev`, `/api/sync/status.tanev`); a tanévváltás utáni **értesítés** (UID-alapú állapot) |
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
| `test_dashboard.py` | Áttekintés dashboard valódi böngészőben, **rögzített böngésző-órával** (`page.clock` — a CI másnapi futás ne csússzon el, #75): csempeszámok (következő házi/számonkérés 10 napra, új jegyek/üzenetek, igazolatlan hiányzás, kifizetetlen zsebpénz), gyermekkártyák, alsó feed (figyelmeztetés + legutóbbi jegyek), csempére kattintás → szűrt eseménylista, **visszalépéskor a szűrés nem tartja üresen a csempét/feedet (#76)**, szűrőpanel láthatósága, zárt átlag-accordion kinyitása, **a kalkulátor jegytáblázata és a több jegy/félévi cél UI (#78/#101)**; tanév-választó (alap = aktuális tanév, „Összes tanév” módban nincs átlag) |
| `test_tanev.py` | Tanév-számítás (Kaneo #40): határnapok, szökőév, KRÉTA magyar és ISO dátumok, `tanev_bounds`, `current_tanev` injektált dátummal, `KRETA_TODAY`/`KRETA_TANEV_KEZDO` env, táblánkénti dátummező (`row_tanev`), `teljesen_lekert` a törlési jogosultsághoz |
| `test_tanev_migration.py` | Tanév-séma migráció régi (oszlop nélküli) DB-n: 5 tábla + `sync_runs` kap oszlopot, az `orarend` nem; backfill két tanévre + ismeretlen dátum; ID-stabilitás; idempotens második futás; **450 soros, többkörös (batch=100) backfill** + `unsynced_rows` |
| `test_tanev_sync.py` | Tanév-tudatos szinkron éles KRÉTA nélkül: az API-ablak a tanév elejétől indul, csak a tanévbe eső sorok cserélődnek, a korábbi tanév érintetlen, az ablakon túli (jövőbeli) sor nem törlődik; **óra-bomba** (08-31 → 09-01 üres válasz → 09-03 új adat); a **hiányzások** korábbi tanévét nem törli, az **igazolás** upsert ID-stabil (módosított megjegyzés) |
| `test_tanev_api.py` | Tanév-szűrés az API-n két tanév adatán: `/api/tanevek`, `?tanev=` az események/átlagok/statisztika/dashboard végpontokon; a korábbi tanév kifizetése nem csökkenti az új egyenlegét; `POST /api/kifizetes` a tanévet is beírja (azonnali levonás); **élek**: `tanev=current/all/osszes/ALL`, ismeretlen tanév, igazolások szűrése, `ismeretlen_db` |
| `test_tanev_state.py` | Tanév-állapot (#43): a `tanevek`/`tanulo_tanev_uid` séma és kezdeti állapot; első UID rögzítés, változatlan UID, UID-változás → technikai zárás + nyitás, dupla zárás kizárása, azonos tanéven belüli UID-frissítés, üres UID; `/api/tanevek` állapot; a futás utáni hook hibakezelése |
| `test_tanev_ui.py` | Tanév-UI valódi böngészőben: #43 a tanév-állapot jelzése (nyitott/lezárt, a kézi gomb megszűnt), #51 a csempék frissülnek késleltetett esemény-válasz mellett is, #53 a dátum-/hónapválasztók a tanév határain belül maradnak |
| `test_kommentek.py` | Saját megjegyzések (#46): a `kommentek` séma/migráció, stabil tartalom-kulcs (az id újraírása után is megmarad), hozzáfűzés eseményhez és üzenethez, validáció, törlés, darabszám a listákban; böngészőben a modál mentés/visszaolvasás |
| `test_oszlop_szelesseg.py` | Oszlopszélesség valódi böngészőben: az átméretezés/húzás nem rendezi át a táblát, a fogantyúk megvannak a hiányzások/igazolások táblán is |
| `test_mobile_layout.py` | Mobil elrendezés valódi böngészőben (393 px): nincs vízszintes túlcsordulás egyik fülön sem, avatar, összecsukott táblázat, hiányzások fül; **az értékeléseknél a jegy (Érték oszlop) alapból látszik** (#110); a szinkron-státusz egy karcsú sor, a technikai részletek koppintásra nyíló ablakban; **a keresőmező nyitáskor azonnal aktív** (#117); **sötét mód** (mentés újratöltés után; kártyacím, hiányzás-összesítő, naptár-cím, táblázat-konténer, státuszsáv, modálfejléc olvashatósága — #112/#118), a **Ma fül** betöltése (#9) és a **nyomtatásbarát órarend** (#86) **gyereket + hetet tartalmazó fejléccel** (#114) |
| `test_karbantartas.py` | Karbantarthatóság (#12, #17): nincs külső CDN-hivatkozás, minden `static/vendor` fájl és a CSS-ek webfontjai léteznek; nincs `SyntaxWarning`, a `config.json.example` érvényes JSON, nincs hivatkozás a törölt `autoSyncAlert` blokkra |
| `test_sajat_orarend.py` | Kézi órarend (#55): tanév/hét/egyedi érvényesség, heti ismétlődés, egy alkalom kivétele, sorozat törlése és **módosítása**, diák-szűrés, saját szín, érvénytelen bemenetek; a szinkron nem érinti a saját táblákat; órarend-színek (#56); **a naptár-események olvasható szövegszíne** (`textColor`, #118) |
| `test_naptar.py` | Naptárbejegyzés (#47): Google-link (egész napos/időpontos, időzóna), `.ics` (CRLF, all-day, UTC, escape, VALARM), config, API 200/404 |
| `test_orarend_ics.py` | Órarend ICS (#73): heti/havi/féléves/tanéves időszak, `RRULE` UNTIL, időzóna, terem/tanár, többgyermekes prefix, üres export |
| `test_sync_runs.py` | Futástörténet (#10): `/api/sync_runs` sorrend, limit, `new_events` összegzés (szótár/lista), hibás diákok parse-olása, a Rendszernapló táblázat/sparkline megléte |
| `test_ai_uzenet.py` | Üzenet-AI (#61): config + magánhálózati őr, JSON-fence/dedup/validáció, fake OpenAI-szerver, API 200/502/503/404, több VEVENT-es `.ics` |
| `test_auth.py` | Opcionális basic auth (#16): kikapcsolva nyitott, bekapcsolva 401/200, `/health` kivétel, statikus védelem, hash és sima jelszó |
| `test_db_indexes.py` | DB-indexek (#15): a gyorsító indexek léteznek, `schema_version`, ismételt init, migráció előtti `.bak` másolat |
| `test_kifizetes_csv.py` | Kaneo #11/#77 (B6): az egyenleg tételeinek Excel exportja — *Elszámolás* összegzés (ebből rendezve, fennálló egyenleg), *Tételes zsebpénz* a kiválasztott **időszakra / teljes tanévre / teljes előzményre**, tételes **rendezettség-jelöléssel** (kifizetett időszak fedi-e a tételt); az egyenleg egyezik a felület `/api/statisztika` értékével; CSV export; üzenetek helyi `olvasott` állapota (`POST /api/uzenetek/<id>/olvasott` és a tömeges `POST /api/uzenetek/olvasott`), a migráció előtti üzenetek olvasottként indulnak, tartalmi kereshetőség |
| `test_routes_contract.py` | **KRÉ-14 refaktor-őr:** a Flask `url_map` teljes listája (43 rule = 42 route + beépített `static`) rule + metódus szerint egy fagyasztott konstanshoz mérve; nincs dupla regisztráció, minden endpoint-név egyedi. Ha ez piros, a refaktor megváltoztatta a nyilvános API-t — a kódot kell visszaállítani, nem a tesztet |
| `test_data_dir.py` | **KRÉ-14 #98:** az útvonal-feloldás alapértéke `data/` (DB, csatolmányok), a legacy (gyökér) elrendezés felismerése és a `data/`-elsőbbség; a `tools/migrate_local_data.py` dry-run → migráció → rollback köre (DB-integrity ellenőrzéssel) |
| `test_jegy_kalkulator.py` | **#78/#101:** „Milyen jegy kell?” — súlyozott átlag, egy jegy/több ötös, elérhetetlen cél, 0%-os súly, hiányzó jegy, tanév-szűrés, érvénytelen bemenet; **több várható jegy** (eltérő súlyok, szükséges összesített átlag, szimulált átlag), **félévi cél** (küszöb + szükséges átlag), **mentett célátlag** (`/api/kalkulator_cel` GET/POST), a meglévő jegyek táblázata, üres alap-választó |
| `test_kereses.py` | **#85:** globális kereső — több adatforrás, üzenet teljes törzs, rendezés/limit, rövid keresés, LIKE-escape, modal és Ctrl+K, navigáció; **a találat sorára kattintva a részletek modálja nyílik** (esemény/hiányzás), fallback navigáció |
| `test_kedvencek.py` | **#86:** `/api/kedvencek` add/remove/toggle, perzisztencia (`app_meta`), érvénytelen kérés; a dashboard-panel és a csillag gomb |
| `test_ma.py` | **#9/#113:** `/api/ma` — mai órák duplikátum nélkül, ma/holnapi határidők, friss jegyek, olvasatlan üzenetek, diák-szűrés, üres/hibás dátum; **önálló „Ma” fül** (a dashboard-kártya elutasítva), **külön Frissítés gomb nélkül** (nyitáskor/gyermekváltáskor frissül) |
| `test_trend.py` | **#80/#111:** tantárgyi trend (utolsó két hónap), **gyermekenkénti** romlás- (≤ -0,5) és javulás-figyelmeztetés (≥ +0,5) az időszakkal, hiányzás-mintázat nap/óra/tantárgy/hónap bontásban, tanév-szűrés; a felületi kötés (romló + javuló sáv) |

## Függőségek

A tesztek a futó alkalmazás függőségein (flask, reportlab) túl **opcionálisan** használják:

- `pypdf` — a PDF szövegének kinyerése (e nélkül a PDF-teszt szövegellenőrzése kimarad),
- `pymupdf` (`fitz`) — a beágyazott betűk listázása (csak diagnosztika).

Ezek nélkül a tesztek lefutnak, csak a kapcsolódó ellenőrzések maradnak ki.

## API-pillanatkép (KRÉ-14)

A `python tools/api_snapshot.py` a 17 olvasó végpont válaszát menti/különbözteti
(az adatbázis másolatán, POST nélkül). A baseline **nem verziózott** (valódi, személyes
adatot tartalmaz, a `.gitignore` kizárja):

```bash
python tools/api_snapshot.py --out tools/snapshots/baseline.json   # refaktor előtt
python tools/api_snapshot.py --diff tools/snapshots/baseline.json  # minden fázis után
```

## Megjegyzés

A tesztek izolált temp könyvtárban dolgoznak (`tempfile`), a valódi adatbázist és
`config.json`-t nem érintik. A `config.json`-t, DB-t és `sync.log`-ot a teszt
környezeti változókkal irányítja át.

## Futtatás és CI

```bash
python tests/run_all.py            # minden teszt (44 csomag, 1272 ell.)
python tests/run_all.py --fast     # böngésző nélkül (39 csomag, 1120 ell.)
python tests/run_all.py --browser  # csak Playwright (5 csomag, 152 ell.)
```

A GitHub Actions (`.github/workflows/ci.yml`) a **gyors** csoportot minden pushra/PR-ra,
a **böngészőst** csak `main` pushra, éjszakánként és kézi indításra futtatja. A böngészős
job hibája esetén a képernyőképek artifactként feltöltődnek.
