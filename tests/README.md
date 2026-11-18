# Tesztek

Futtatás (a projekt gyökeréből):

```bash
python tests/run_all.py
```

Kilépési kód: `0` = minden teszt OK, `1` = valamelyik bukott.

| Fájl | Mit ellenőriz |
|---|---|
| `test_scheduler.py` | Ütemező: config-parse/clamp, időablak (átforduló is), `next_run` az ablakon belül, perzisztencia, dupla indítás elleni védelem
| `test_szunet.py` | **#145:** `SYNC_SZUNET` intervallum-parse (dátum/idő normalizálás), aktív/következő szünet, az intervallumok összes napja (`all_days`), napi szinkron esedékessége, ütemező viselkedés szünet alatt (nincs normál futás, napi egyszer), `/api/scheduler/status.szunet`, felületi sáv, **`SZUNET_AKTIV` mesterkapcsoló** |, API végpontok, `interrupted`/`running`, napló-pótlás, memória-fallback |
| `test_a_package.py` | Részleges hiba (`done_with_errors` + hibás diákok), ntfy payload/throttle, napló-rotáció, `/api/logs` tail; a futás tanéve (`sync_runs.tanev`, `/api/sync/status.tanev`); a tanévváltás utáni **értesítés** (UID-alapú állapot) |
| `test_pdf_fonts.py` | PDF magyar `ő/Ő/ű/Ű` megjelenítés (a kiszolgált PDF szövegkinyerésével) |
| `test_paths.py` | Adat-/log-/csatolmány-útvonalak feloldása (lokális és Docker-elrendezés) |
| `test_new_events.py` | Új események kimutatása a szinkron előtti/utáni állapot különbségéből |
| `test_migration.py` | Egyszeri migráció: régi `scheduler_state.json` → `sync_runs`/`app_meta` |
| `test_hianyzasok.py` | Hiányzások/igazolások: táblák, mentés + dedupe, új-hiányzás számítás, havi API-összesítő (igazolt/igazolatlan óra, késés), push-szöveg |
| `test_api_client.py` | Termelési API-kliens (`kreta_api.py`): login/refresh/401-retry/implicit belépés fake HTTP-vel, dátumszeletek, dátum/HTML konverzió, normalizálás, órarend-elem és fogadóóra, üzenetszűrés |
| `test_api_sync.py` | API-szinkron adatkörök: lekérési ablak (magyar/ISO dátum), órarend-join párhuzamos csoportokkal, táboros téma megőrzése, jegyek (Magatartás/Szorgalom 0 értékkel), házi `kesz` megőrzés, számonkérés, feljegyzés, órarend + fogadóóra, üzenetek (inkrementális, csatolmány-fallback és **pótlás**), stabil ID-k, igazolások |
| `test_sync_mode.py` | `SYNC_MODE` feloldás (alap: `api`), forrásnapló, hibás adatkör kezelése, duplikációvédelem valódi SQLite-on |
| `test_api_only.py` | **#64:** egyetlen gyökér modul sem importál `playwright`-ot; az örökölt `api_first`/`playwright` értékek `api`-ra váltanak; `init_db()` és `--init-db` böngésző nélkül, a `csatolmany_proba` oszloppal |
| `test_digest.py` | Esti digest: adatgyűjtés (jegy súlyozással, házi, dolgozat, feljegyzés, hiányzás, igazolás, üzenet, holnapi határidők), üres nap szövege, küldési idempotencia, manuális küldés (az automata érintetlen), beállítás-API, fake ntfy; **hétvége/szünetnap üres digest kihagyása (#133), a `SYNC_SZUNET` intervallumai mint szünetnapok, `SZUNET_AKTIV` mesterkapcsoló** |
| `test_tantargy_szuro.py` | Tantárgy-szűrő kis/nagybetű-függetlenül („Angol nyelv" / „angol nyelv"): eseménylista, Excel export, átlagok/trend, jegy-kalkulátor, főoldali választó (Kaneo #127) |
| `test_data_guard.py` | Adatvédelem: üres API-válasz nem töröl, 50%-os küszöb (`KRETA_SYNC_MIN_RATIO`), órarend csak teljes ürülésnél véd, szolgáltatói hiba fallbackhez |
| `test_db_guard.py` | DB-séma őr: zárolt adatbázisnál nincs init-db subprocess, az önjavítás nem kapcsol ki véglegesen, a zárolás után bootstrapol |
| `test_jegy_suly.py` | Jegyek súlyszázaléka: webes tooltip `data-suly` szövegének parse-olása, mobil API `SulySzazalekErteke` normalizálása (szám/sztring/null), DB-oszlop és mentés (0 = nincs adat) |
| `test_statisztika.py` | `/api/statisztika`: súlyozott tanulmányi átlag (0%-os súly kimarad), súlyadat nélküli visszaesés az egyszerű átlagra, kikapcsolt zsebpénz (`rewards_enabled: false`, statisztika él, pénz 0); `/api/atlagok`: tantárgyi átlagok havi bontással; `/api/dashboard`: diákonkénti átlag, kifizetett időszak levonása, igazolatlan óra |
| `test_dashboard.py` | Áttekintés dashboard valódi böngészőben, **rögzített böngésző-órával** (`page.clock` — a CI másnapi futás ne csússzon el, #75): csempeszámok (következő házi/számonkérés 10 napra, új jegyek/üzenetek, igazolatlan hiányzás, kifizetetlen zsebpénz), gyermekkártyák, alsó feed (figyelmeztetés + legutóbbi jegyek), csempére kattintás → szűrt eseménylista (**a szűrőpanel alapból zárva, kattintásra nyílik — #120**), **visszalépéskor a szűrés nem tartja üresen a csempét/feedet (#76)**, szűrőpanel láthatósága, zárt átlag-accordion kinyitása, **a kalkulátor jegytáblázata és a több jegy/félévi cél UI (#78/#101)**; tanév-választó (alap = aktuális tanév, „Összes tanév” módban nincs átlag) |
| `test_tanev.py` | Tanév-számítás (Kaneo #40): határnapok, szökőév, KRÉTA magyar és ISO dátumok, `tanev_bounds`, `current_tanev` injektált dátummal, `KRETA_TODAY`/`KRETA_TANEV_KEZDO` env, táblánkénti dátummező (`row_tanev`), `teljesen_lekert` a törlési jogosultsághoz |
| `test_tanev_migration.py` | Tanév-séma migráció régi (oszlop nélküli) DB-n: 5 tábla + `sync_runs` kap oszlopot, az `orarend` nem; backfill két tanévre + ismeretlen dátum; ID-stabilitás; idempotens második futás; **450 soros, többkörös (batch=100) backfill** + `unsynced_rows` |
| `test_tanev_sync.py` | Tanév-tudatos szinkron éles KRÉTA nélkül: az API-ablak a tanév elejétől indul, csak a tanévbe eső sorok cserélődnek, a korábbi tanév érintetlen, az ablakon túli (jövőbeli) sor nem törlődik; **óra-bomba** (08-31 → 09-01 üres válasz → 09-03 új adat); a **hiányzások** korábbi tanévét nem törli, az **igazolás** upsert ID-stabil (módosított megjegyzés) |
| `test_tanev_api.py` | Tanév-szűrés az API-n két tanév adatán: `/api/tanevek`, `?tanev=` az események/átlagok/statisztika/dashboard végpontokon; a korábbi tanév kifizetése nem csökkenti az új egyenlegét; `POST /api/kifizetes` a tanévet is beírja (azonnali levonás); **élek**: `tanev=current/all/osszes/ALL`, ismeretlen tanév, igazolások szűrése, `ismeretlen_db` |
| `test_tanev_state.py` | Tanév-állapot (#43): a `tanevek`/`tanulo_tanev_uid` séma és kezdeti állapot; első UID rögzítés, változatlan UID, UID-változás → technikai zárás + nyitás, dupla zárás kizárása, azonos tanéven belüli UID-frissítés, üres UID; `/api/tanevek` állapot; a futás utáni hook hibakezelése |
| `test_tanev_ui.py` | Tanév-UI valódi böngészőben: #43 a tanév-állapot jelzése (nyitott/lezárt, a kézi gomb megszűnt), #51 a csempék frissülnek késleltetett esemény-válasz mellett is, #53 a dátum-/hónapválasztók a tanév határain belül maradnak |
| `test_kommentek.py` | Saját megjegyzések (#46): a `kommentek` séma/migráció, stabil tartalom-kulcs (az id újraírása után is megmarad), hozzáfűzés eseményhez és üzenethez, validáció, törlés, darabszám a listákban; böngészőben a modál mentés/visszaolvasás |
| `test_oszlop_szelesseg.py` | Oszlopszélesség valódi böngészőben: az átméretezés/húzás nem rendezi át a táblát, a fogantyúk megvannak a hiányzások/igazolások táblán is |
| `test_mobile_layout.py` | Mobil elrendezés valódi böngészőben (393 px): nincs vízszintes túlcsordulás egyik fülön sem, avatar, összecsukott táblázat, hiányzások fül; **az értékeléseknél a jegy (Érték oszlop) alapból látszik** (#110); a szinkron-státusz egy karcsú sor, a technikai részletek koppintásra nyíló ablakban; **a keresőmező nyitáskor azonnal aktív** (#117); **a Ma fül határidő-sorára (napi és heti nézet) koppintva részletek modál nyílik**; **sötét mód** (mentés újratöltés után; kártyacím, hiányzás-összesítő, naptár-cím, táblázat-konténer, státuszsáv, modálfejléc olvashatósága — #112/#118), a **Ma fül** betöltése (#9) és a **nyomtatásbarát órarend** (#86) **gyereket + hetet tartalmazó fejléccel** (#114) |
| `test_karbantartas.py` | Karbantarthatóság (#12, #17): nincs külső CDN-hivatkozás, minden `static/vendor` fájl és a CSS-ek webfontjai léteznek; nincs `SyntaxWarning`, a `config.json.example` érvényes JSON, nincs hivatkozás a törölt `autoSyncAlert` blokkra |
| `test_sajat_orarend.py` | Kézi órarend (#55): tanév/hét/egyedi érvényesség, heti ismétlődés, egy alkalom kivétele, sorozat törlése és **módosítása**, diák-szűrés, saját szín, érvénytelen bemenetek; a szinkron nem érinti a saját táblákat; órarend-színek (#56); **a naptár-események olvasható szövegszíne** (`textColor`, #118) |
| `test_naptar.py` | Naptárbejegyzés (#47): Google-link (egész napos/időpontos, időzóna), `.ics` (CRLF, all-day, UTC, escape, VALARM), config, API 200/404 |
| `test_orarend_ics.py` | Órarend ICS (#73): heti/havi/féléves/tanéves időszak, `RRULE` UNTIL, időzóna, terem/tanár, többgyermekes prefix, üres export |
| `test_sync_runs.py` | Futástörténet (#10): `/api/sync_runs` sorrend, limit, `new_events` összegzés (szótár/lista), hibás diákok parse-olása, a Rendszernapló táblázat/sparkline megléte |
| `test_ai_uzenet.py` | Üzenet-AI (#61): config + magánhálózati őr, JSON-fence/dedup/validáció, fake OpenAI-szerver, API 200/502/503/404, több VEVENT-es `.ics` |
| `test_auth.py` | Opcionális basic auth (#16): kikapcsolva nyitott, bekapcsolva 401/200, `/health` kivétel, statikus védelem, hash és sima jelszó |
| `test_db_indexes.py` | DB-indexek (#15): a gyorsító indexek léteznek, `schema_version`, ismételt init, migráció előtti `.bak` másolat |
| `test_kifizetes_csv.py` | Kaneo #11/#77 (B6): az egyenleg tételeinek Excel exportja — *Elszámolás* összegzés (ebből rendezve, fennálló egyenleg), *Tételes zsebpénz* a kiválasztott **időszakra / teljes tanévre / teljes előzményre**, tételes **rendezettség-jelöléssel** (kifizetett időszak fedi-e a tételt); az egyenleg egyezik a felület `/api/statisztika` értékével; CSV export; üzenetek helyi `olvasott` állapota (`POST /api/uzenetek/<id>/olvasott` és a tömeges `POST /api/uzenetek/olvasott`), a migráció előtti üzenetek olvasottként indulnak, tartalmi kereshetőség |
| `test_routes_contract.py` | **KRÉ-14 refaktor-őr:** a Flask `url_map` teljes listája (51 rule = 50 route + beépített `static`) rule + metódus szerint egy fagyasztott konstanshoz mérve; nincs dupla regisztráció, minden endpoint-név egyedi. Ha ez piros, a refaktor megváltoztatta a nyilvános API-t — a kódot kell visszaállítani, nem a tesztet |
| `test_data_dir.py` | **KRÉ-14 #98:** az útvonal-feloldás alapértéke `data/` (DB, csatolmányok), a legacy (gyökér) elrendezés felismerése és a `data/`-elsőbbség; a `tools/migrate_local_data.py` dry-run → migráció → rollback köre (DB-integrity ellenőrzéssel) |
| `test_jegy_kalkulator.py` | **#78/#101:** „Milyen jegy kell?” — súlyozott átlag, egy jegy/több ötös, elérhetetlen cél, 0%-os súly, hiányzó jegy, tanév-szűrés, érvénytelen bemenet; **több várható jegy** (eltérő súlyok, szükséges összesített átlag, szimulált átlag), **félévi cél** (küszöb + szükséges átlag), **mentett célátlag** (`/api/kalkulator_cel` GET/POST), a meglévő jegyek táblázata, üres alap-választó |
| `test_kereses.py` | **#85/#102/#107:** globális kereső — több adatforrás, üzenet teljes törzs, rendezés/limit, rövid keresés, LIKE-escape, modal és Ctrl+K, navigáció; **a találat sorára kattintva a részletek modálja nyílik**; **↑/↓/Enter, előzmény (localStorage), találat-kiemelés**; **FTS5 = LIKE** egyezés és idempotens index |
| `test_kedvencek.py` | **#86/#108:** `/api/kedvencek` add/remove/toggle, megjegyzés (`note`) és húzásos sorrend (`order`) perzisztencia, érvénytelen kérés; a dashboard-panel, a csillag gomb és a drag/note UI |
| `test_ma.py` | **#9/#104/#113/#134/#144:** `/api/ma` — mai és holnapi órák duplikátum nélkül, **holnapi tantárgy-lista (API)**, ma/holnapi határidők (**a részletek modál mezőivel**), **igazolandó hiányzások**, friss jegyek, olvasatlan üzenetek, diák-szűrés, üres/hibás dátum; **önálló „Ma” fül** (a dashboard-kártya elutasítva), **Ma/Hét nézetváltó** (kétoszlopos, középre igazított napkártyák, esemény szerinti színek, páratlan darabszámnál középre tett utolsó kártya, havi nézet nélkül), **hétvégi napok is, ha van óra/határidő**, külön Frissítés gomb nélkül; **a határidő-sorra kattintva részletek modál** (napi és heti nézet) |
| `test_trend.py` | **#80/#111:** tantárgyi trend (utolsó két hónap), **gyermekenkénti** romlás- (≤ -0,5) és javulás-figyelmeztetés (≥ +0,5) az időszakkal, hiányzás-mintázat nap/óra/tantárgy/hónap bontásban, tanév-szűrés; a felületi kötés (romló + javuló sáv) |
| `test_riportkartya.py` | **#82:** **aktuális bizonyítvány** PDF **mentés nélkül** (`GET /api/riportkartya/export_pdf`), félév/tanév, a címben a tanév, egyoldalas **dísz-bizonyítvány** (keret/pecsét, „Aktuális bizonyítvány” fejléc), PDF-tartalom (pypdf, ha van): jegyenként összesített Jegyek oszlop dátum nélkül, nincs Db oszlop, magatartás/szorgalom benne, zsebpénz csak engedélyezett modulnál, nincs Feljegyzések szekció, valós hiányzás-óraszám; hibás bemenetek, felületi kártya, nincs mentett előzmény |
| `test_tanulmanyi_export.py` | **#83:** `/api/esemenyek/export.xlsx` (Jegyek/Feljegyzések/Házi feladatok) és `/api/hianyzasok/export.xlsx` (Hiányzások/Igazolások) — munkalapok, sorok, diák/tanév/időszak szűrés, üres export, felületi gombok |
| `test_ops_checks.py` | **#90:** restore-teszt (érvényes/sérült/hiányzó/elavult mentés, manifest-egyezés, izolált visszaállítás) + élő füstteszt (`/health`, `/api/sync/status`, utolsó futás kora, auth) fake HTTP-szerverrel; CI workflow |
| `test_sync_health.py` | **#88:** 3 egymást követő hiba → magas prioritású riasztás, 6 órás throttle, token-lejárat külön üzenet, siker utáni reset, `health` a `/api/scheduler/status`-ban |
| `test_data_quality.py` | **#89:** adatminőség-riport — tiszta DB, duplikált esemény, hiányzó csatolmány, üres kötelező mező, árva megjegyzés, CLI kilépési kód; csak olvas |
| `test_performance.py` | **#109:** 5 000 esemény + 500 üzenet fixture; `/api/ma`, `/api/kereses`, `/api/statisztika`, `/api/atlagok` medián ideje 500 ms alatt, FTS index teljes |

## Függőségek

A tesztek a futó alkalmazás függőségein (flask, reportlab) túl **opcionálisan** használják:

- `pypdf` — a PDF szövegének kinyerése (e nélkül a PDF-teszt szövegellenőrzése kimarad),
- `pymupdf` (`fitz`) — a beágyazott betűk listázása (csak diagnosztika).

A **böngészős UI-tesztekhez** a `requirements-playwright.txt` és a Chromium kell
(`pip install -r requirements-playwright.txt; playwright install chromium`). Ez
**csak a felület teszteléséhez** kell — a KRÉTA-adatlekérés a v2.5.0-tól kizárólag
mobil API-ból fut (Kaneo #64). A gyors tesztek az alap `requirements.txt`-vel
futnak, Playwright nélkül is.

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
python tests/run_all.py            # minden teszt
python tests/run_all.py --fast     # böngésző nélkül (fast csomag)
python tests/run_all.py --browser  # csak a böngészős UI-tesztek (Playwright)
```

A GitHub Actions (`.github/workflows/ci.yml`) a **gyors** csoportot minden pushra/PR-ra,
a **böngészőst** csak `main` pushra, éjszakánként és kézi indításra futtatja. A böngészős
job hibája esetén a képernyőképek artifactként feltöltődnek.
