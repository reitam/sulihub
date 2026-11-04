# Összefoglaló — 2026-11-04 (éjszakai munkamenet)

**Téma:** a Kaneo To Do-ba tett jegyek megvalósítása a KRÉTA Adatbázis Áttekintő
(SuliHub) alkalmazásban.

**Ág:** `main` (pusholva). **Éles verzió:** `v1.8.0`; a munkamenet eredménye
**`v1.9.0`** néven élesítésre vár.

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

- **1035 automatikus ellenőrzés / 37 csomag — mind zöld.**
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

## 5. Backlog-kör (2026-11-04)

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
- **Lezárt jegyek:** #61 és #65–#69 (AI), #71 (fejléc), #16, #15, #73, #72; a #11 részlegesen.

## 6. Nyitott

- **#61 Üzenetek AI elemzése:** a jegy maga is tervezést igényel; a tervet
  `AI-ELEMZES-TERV.md` tartalmazza, a részfeladatok a Kaneo #61 alatt vannak.
  Szükséges döntés: melyik ingyenes AI-szolgáltatás/model fusson (helyi Ollama vagy
  felhős ingyenes tier), és ehhez kulcs/hozzáférés.
- **Élesítés:** `.\deploy.ps1 -Release v1.9.0` (interaktív SSH-jelszó), utána
  `/health` = v1.9.0 és a mobil/asztali fejléc ellenőrzése.
