# Összefoglaló — 2026-11-04 (éjszakai munkamenet)

**Téma:** a Kaneo To Do-ba tett jegyek megvalósítása a KRÉTA Adatbázis Áttekintő
(SuliHub) alkalmazásban.

**Ág:** `main` (pusholva). **Éles verzió: `v1.9.0`** (2026-11-05; `/health` = v1.9.0).
A **#75/#76 javítás a `v1.9.1`** (tag `ddb5321`) részeként megy élesbe.

---

## 1. Elkészült jegyek

| Jegy | Eredmény |
|---|---|
| **#13 C2 – CI** | Megerősítve: a fast/browser job zöld a main-en; egy szándékosan elrontott teszt az átmeneti ágon **piros** futást adott (fast failure, browser skipped), a próbaág törölve. |
| **#55 Saját óra** | `sajat_orarend` + `sajat_orarend_kivetel` táblák; „Saját óra” gomb, tanév/hét/egyedi érvényesség, heti ismétlődés, egy alkalom vagy teljes sorozat törlése; a szinkron nem érinti. |
| **#47 / #60 Naptárbejegyzés** | Házi/számonkérés és üzenet részleteinél Google Naptár-link + `.ics`; `CALENDAR` config (időzóna, emlékeztető, üzenet hossza); időpontos események UTC-re konvertálva. |
| **#59 Üzenet-megjegyzés** | Már a #46-ban (v1.7.0) elkészült: az üzenet ablakban saját megjegyzés fűzhető/olvasható; a #59 ennek a megerősítése. |
| **#10 Futástörténet** | `/api/sync_runs?limit=20` + a Rendszernapló fülön táblázat (indult, futásidő, státusz, új esemény, hibás diák, tanév) és futásidő-sparkline; csak a fül megnyitásakor tölt. |
| **#62 Ikon és név** | **SuliHub** név, saját SVG logó + favicon. |
| **#63 Fejléc** | Egysoros, kompakt navbar: brand + verzió, egy státuszsor („Frissítve: … (kézi)”), a technikai részletek modálban; tanévválasztó + Frissítés gomb egy sorban; asztalon ~60 px. |
| **#56 Órarend-színek** | Gyermekenkénti szín a `ORAREND_SZINEK` configból vagy a „Színek” felületről (app_meta); a naptár azonnal frissül. |
| **#73 Órarend ICS** | `/api/orarend/export_ics?period=het|honap|felev|tanev` — heti ismétlődő VEVENT-ek (RRULE), a kiválasztott gyermekre vagy az összesre; UI dropdown a Heti órarend fülön. |
| **#72 Sötétebb sárga** | A kifizetetlen zsebpénz összege `text-warning-emphasis` (a user elfogadta). |
| **#61 Üzenet-AI** | `kreta_ai.py` (OpenAI-kompatibilis, helyi Ollama) + JSON-validáció + API-végpontok (`/api/uzenet/<id>/ai`, `/api/naptar/ai/ics`); csatolmány-szöveg (txt/pdf). **A felületi „AI elemzés” gombot a felhasználó kérésére kivettük** — a háttér API-ként megmaradt. |
| **#74 Üzenet előnézete** | A KRÉTA üzenetlista csak rövid előnézetet ad, a sortörések nélkül: mentéskor a `postaladaelemek/<posta_id>` **részletes választ** használjuk, és a bekezdések megmaradnak. Új `uzenetek.posta_id` oszlop; a már mentett, rövid szövegű üzenetek utólag feltöltődnek (futásonként max. 20). |

## 2. Döntések

- A saját óra **sorozat** (egy sor = heti ismétlődés); az egy alkalom törlése
  **kivétel** táblába kerül, így a többi alkalom megmarad.
- A „teljes tanév” érvényesség a **szeptember 1. – augusztus 31.** tanévhatárokat
  használja; a „hét” a kiválasztott nap hetének hétfő–vasárnapja.
- A naptárbejegyzés nem igényel API-kulcsot: **Google Naptár template link** (előre
  kitöltött űrlap) + **`.ics`**; így internet/originális OAuth nélkül is működik.
- Az órarend-színeknél a **DB (app_meta) felülírja a configot**, hogy a felületről
  mentett beállítás maradandó legyen; a config csak kezdőérték.
- A fejlécben a részletes szinkron-sor **rejtve** marad, a modál szolgálja ki — így
  mobilon és asztalon ugyanaz az egysoros sáv látszik.

## 3. Tesztek

- **1049 automatikus ellenőrzés / 37 csomag — mind zöld.**
  - fast: **883 ellenőrzés / 32 csomag**
  - browser: **152 ellenőrzés / 5 csomag**
- Új csomagok: `test_sajat_orarend`, `test_naptar`, `test_sync_runs`, `test_ai_uzenet`,
  `test_auth`, `test_db_indexes`, `test_kifizetes_csv`.
- A `test_mobile_layout` a saját óra mentését, a naptárgombokat és az egysoros
  fejlécet is ellenőrzi; a `test_dashboard` dátuma fixálva (determinisztikus).

## 4. Felhasználói visszajelzés utáni finomítás (2026-11-04)

- **#62:** a logó/favicon letisztítva (gradiens kék háttér, fehér könyv, könyvjelző,
  finom árnyék); a fejlécben 40 px-en, mobilon 32 px-en jelenik meg.
- **#63:** a fejléc modernebb: gradiens háttér, lekerekített kontrollcsoport, egységes
  40 px-es vezérlők, a státusz kapszula alakú; asztalon 64 px, mobilon három tömör sor.
  Képernyőképpel ellenőrizve (asztal + 393 px). **Elrendezés:** tanév balra, logó/verzió
  középen hangsúlyosan (1,5× méret: 66 px logó, 2,1 rem név), státusz jobbra, Frissítés a
  jobb szélen.
- **#55:** a saját óra **színe az ablakban választható**; alapból lila, de ha a gyermek
  alap színe épp lila, automatikusan másikat ajánl. A választott szín a sorozathoz
  mentődik (`sajat_orarend.szin`). A létrehozott sorozat **módosítható** (eseményre
  koppintva „Módosítás”), nem csak törölhető.
- **#47/#60:** a felületen már nem ICS-letöltés van, hanem **„Naptárba küldés”**: előre
  kitöltött Google Naptár esemény nyílik, egy kattintással menthető. A valódi, OAuth-os
  közvetlen írás külön fejlesztés; az `.ics` végpont programozottan megmaradt.

## 5. Hibajegyek: #75 (CI) és #76 (dashboard) — 2026-11-05

- **#76 — üres eredmények navigáció után:** az Áttekintés a szűrt eseménylista
  adatsorozatából számolta a csempéket és a feedet, így ha az eseménylistán
  szűrtél (pl. „új jegyek" csempe), és visszaléptél, a dashboard üresen maradt
  (F5 segített csak). **Fix:** a dashboard a saját, szűrő nélküli adatforrását
  tölti be (`/api/esemenyek` csak gyermek- + tanév-szűrővel, `/api/uzenetek`),
  és fülre visszatéréskor azonnal újraszámol, majd frissít.
- **#75 — a CI (GitHub Actions, scheduled) futás elbukott:** a `test_dashboard`
  fix tesztdátummal (2026-11-04) generál adatot, de a dashboard timeablakát a
  böngésző valódi ideje számolja — másnapi futásnál a „mai" házi kicsúszott a
  10 napos ablakból. **Fix:** `page.clock.install(...)` rögzíti a böngésző óráját
  a tesztdátumra (asztali és mobil kontextusban is).
- Erősített tesztek: a `test_dashboard` 4. lépése most azt is ellenőrzi, hogy
  szűrés utáni visszatéréskor a csempék és a feedek újra tele vannak.

## 6. Backlog-kör (2026-11-04)

- **#16 Hitelesítés:** opcionális **basic auth** (`AUTH` config, `PASSWORD_HASH`),
  `/health` kivétel; kikapcsolva változatlan a működés. Élesben HTTPS/reverse proxy javasolt.
- **#15 DB-indexek:** `esemenyek`/`uzenetek`/`kifizetesek`/`sync_runs` gyorsító indexei,
  `app_meta.schema_version`, migráció előtti automatikus `.bak` másolat; idempotens init.
- **#11 (rész):** zsebpénz-elszámolások **CSV exportja** (UTF-8 BOM, `;` elválasztó,
  diák-szűrő) a Zsebpénz fülön. A keresés/olvasottság és a melléklet-dedupe nyitva maradt.
- **#73:** órarend **ICS export** hét/hónap/félév/tanév időszakra, heti ismétlődő
  VEVENT-ekkel (RRULE), a kiválasztott gyermekre vagy az összesre.
- **#72:** a kifizetetlen zsebpénz sárga összege sötétebb (`text-warning-emphasis`),
  hogy fehér háttéren is olvasható legyen.
- **#61 UI:** a felhasználó kérésére az **„AI elemzés” gomb kikerült a felületből**
  (eredménylista, kijelölés, ICS-gombok); a háttér (`/api/uzenet/<id>/ai`,
  `/api/naptar/ai/ics`, `kreta_ai.py`, tesztek) megmaradt.
- **#74 Üzenet előnézete (hibajegy):** a tárolt üzenetszöveg a lista API előnézete volt —
  rövid és a bekezdések nélkül. Most a **részletes API-válasz** kerül mentésre
  (`html_to_text`, sortörések megőrzése), új `uzenetek.posta_id` oszlop, és a már mentett
  rövid szövegű üzenetek **utólag feltöltődnek** (futásonként max. 20).
- **Lezárt jegyek:** #61 és #65–#69 (AI), #71 (fejléc), #16, #15, #73, #72, #58; a #11 részlegesen.

## 7. Nyitott

- **#11:** üzenetek olvasott/olvasatlan jelölés + melléklet-dedupe (a CSV export kész).
- **#70:** Google Calendar OAuth — közvetlen írás configban megadott naptárba.
- **#14 / #8 / #64 / #48 / #49 / #33:** a nagyobb refaktorok/döntések a backlogban
  (felbontás, digest, Playwright-kivezetés, publikálás, felhasználókezelés, licenc).
- **#61:** a felületi gomb kivéve; ha később kell, a UI-t újra be lehet kötni az
  API-végpontokra (`AI-ELEMZES-TERV.md`).
- **Élesítés:** `.\deploy.ps1 -Release v1.9.1` (interaktív SSH-jelszó; a tag már
  létezik: `ddb5321`), utána `/health` = v1.9.1, a dashboard szűrés-csempére kattintás
  után visszatérve is teljes (#76), és a következő napon futó scheduled CI is zöld
  (#75 — ezt követően a #74 miatt a régebbi üzenetek a szinkronokkal fokozatosan
  feltöltődnek).
