# 🎓 SuliHub – KRÉTA Adatbázis Áttekintő & Zsebpénz Menedzser

[![CI](https://github.com/reitam/sulihub/actions/workflows/ci.yml/badge.svg)](https://github.com/reitam/sulihub/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/reitam/sulihub)](https://github.com/reitam/sulihub/releases)

> **Teljes rendszerdokumentáció:** [`docs/DOKUMENTACIO.md`](docs/DOKUMENTACIO.md) — üzleti áttekintés,
> architektúra, adatmodell, üzemeltetés, hibaelhárítás.

Egy központi, **Flask** alapú webes alkalmazás, amely automatikusan lekéri és
SQLite adatbázisba szinkronizálja **több gyermek** KRÉTA-rendszerből származó adatait
(órarend, jegyek, feljegyzések, házi feladatok, bejelentett számonkérések, e-Ügyintézés
üzenetek és csatolmányok). A felület egy helyen, áttekinthetően mutatja mindezt —
**asztali és mobil böngészőn is** —, nyomtatható PDF órarendet készít, és **push
értesítést** küld a változásokról.

**Kinek készült?** Egy szülőnek, aki napi szinten követi a gyermekei iskolai életét.
Nem kereskedelmi termék: saját üzemeltetésű, belső hálózaton futó rendszer, az adatok
a saját szerveren maradnak.

> **Jogi / adatvédelmi megjegyzés:** Ez egy **nem hivatalos** kliens, amely **nem áll
> kapcsolatban** a KRÉTA/KIFÜ rendszerrel vagy annak üzemeltetőivel. Csak a **saját
> fiókodhoz** és a **saját gyermekeid adataihoz** használd, a KRÉTA használati
> feltételeit betartva. A szoftver **garancia nélkül** („AS IS”) kerül átadásra; az
> üzemeltetésért és az adatokért a felhasználó felel. Kérjük, **ne tegyél közzé
> személyes adatot** (gyermeknév, iskola, KRÉTA-azonosító) issue-ban, képernyőképen
> vagy commitban. A harmadik féltől származó kódok licencei:
> [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). A saját kód **MIT licenc**
> alatt áll: [`LICENSE`](LICENSE).

**Legutóbbi kiadás:** `v2.7.8` (2026-11-23) | [Kiadások](https://github.com/reitam/sulihub/releases)

---

## 🌟 Főbb funkciók

### 🤖 Automatikus szinkronizáció
- A **Kréta mobil API-val** lép be a diákfiókokba (**több gyermek, több intézmény** egyszerre),
 böngésző nélkül.
- A munkamenetet a data köteten tárolja (`api_tokens.json`), így a futások többsége nem lép be újra.
- Lekéri az **aktuális és következő hét** órarendjét (tanár, terem, csengetési időpontok).
- Jegyek, feljegyzések, házik, számonkérések, **hiányzások/késések és igazolások** mentése;
 az e-Ügyintézés üzenetei **inkrementálisan** (csak az újak) töltődnek, **a csatolmányokkal
 együtt — API-ból, böngésző nélkül**.
- **Részleges hiba ≠ siker:** ha egy gyermek adata nem jön le, a többi frissül, a futás
 „részleges hiba" állapotba kerül, és a hibás gyermek neve megjelenik.

### ⏱️ Ütemező (config-vezérelt)
- Alapból **3 óránként, 6:00–22:00 között** fut (06:00 → 09:00 → 12:00 → 15:00 → 18:00 → 21:00).
- A kézi frissítés **nem tolja el** az automatikus időzítést.
- **Szinkron-szünet:** a `config.json` `SYNC_SZUNET` intervallumaiban
 (pl. őszi/téli szünet) az automatikus futás kimarad — a felület tetején bordó sáv
 jelzi; a kézi frissítés mindig elérhető. Opcionálisan a szünet alatt is futhat
 **napi egy** automatikus szinkron megadott időpontban. A `SZUNET_AKTIV` (alap: `true`)
 **mesterkapcsoló**: `false` esetén a szüneteket sem a szinkron, sem a digest nem veszi
 figyelembe. A szüneteket elég **egy helyen** (`SYNC_SZUNET`) megadni — a digest
 automatikusan ugyanezeket használja.
- Átfedés-védelem, perzisztált futástörténet, részleges hibakezelés.

### 🔔 Push értesítések (ntfy)
- **Hiba / részleges hiba:** mindig megy, futásonként **egy** üzenet. Ismétlődő
 hiba vagy token-lejárat esetén a szinkron-egészség riasztása **ugyanebbe az egy**
 üzenetbe kerül.
- **Új információ:** futásonként **egy** üzenet, a **napi összefoglalóval azonos
 részletességgel** (jegyek súlyozással, házik, dolgozatok, feljegyzések,
 hiányzások, igazolások, üzenetek, holnap esedékes), diákonként csoportosítva.
- **Sikeres, változás nélküli futás:** **nincs push** — a fejléc státuszsávja és a
 Rendszernapló mutatja, hogy lefutott.
- `NTFY.NOTIFY_NEW` (alap: `true`): az új adat push kikapcsolása; a hibariasztás
 ettől független. A régi `NOTIFY_SUCCESS` kulcsot is elfogadja.
- Az ntfy üzenettörzs max. ~4 KB; hosszabb tartalomnál a végén
 „… (a többi részlet a felületen)” áll.
- Diáknevek alapból **nem** mennek ki; `NTFY.INCLUDE_NAMES` kapcsolja.
- Elavult adat (12 óránál régebbi) esetén külön riasztás, max. 6 óránként egyszer.
- **Esti összefoglaló (KRÉ-8):** minden nap a beállított idő után (alap **19:30**)
 **gyermekenként egy üzenet** a nap eseményeivel — jegyek súlyozással, ma feladott
 házik, ma bejelentett dolgozatok, feljegyzések, hiányzások, igazolások, üzenetek —,
 valamint a **holnap esedékes** házik/dolgozatok. Órarend nincs benne; eseménytelen
 napon is jön rövid üzenet — **kivéve hétvégén/tanítási szüneten**,
 ahol üres napon nem megy üzenet (a `SYNC_SZUNET` intervallumai, a kiegészítő
 `DIGEST.SZUNET_NAPOK` és az órarendi szünet-sorok alapján; valódi esemény esetén
 igen). A küldés ideje a `config.json`
 `DIGEST.TIME`-ban (alap
 19:30), a felületen is állítható. A fejléc 🔔 ikonjából bármikor kérhető
 **„Összefoglaló most”** az **utolsó automatikus óta** — ez nem írja felül az
 automata időpontját/tartalmát (tesztelési/kérési cél). Naponta max. 1 automata
 üzenet gyermekenként.

### 📅 Heti/napi órarend + PDF
- Asztali nézetben idősávos **heti** órarend, mobilon **napi naptár** ‹ › lapozással.
- **A4 fekvő, nyomtatásra kész PDF** (ReportLab), gyermekenként külön oldal;
 magyar **ő/ű/Ő/Ű** helyesen (Unicode betűkészlet).
- Tantárgy szerinti színkódolás, egész napos események külön sávban.
- A szinkron **4 hétre előre** kéri le az órarendet (aktuális hét + 3), a **múltbeli
 órákat megőrzi** — csak az aktuális ablak cserélődik.

### 🧭 Áttekintés (dashboard)
- Nyitó fül **6 kattintható csempével** (**következő házi feladatok** és **következő
 számonkérések** a következő 10 napra, **új jegyek** / **új üzenetek** az elmúlt 10 napban,
 **igazolatlan hiányzás** órában, **kifizetetlen zsebpénz**) — a csempére kattintva a
 megfelelő nézet nyílik; **gyermekenkénti kártyák** (átlag + egyenleg); gyermekváltás
 egy kattintással. **Kompakt, 3×2 elrendezés**, egységes sablon, **látható kerettel**;
 széles kijelzőn a dashboard **középre igazított (max. 1200 px)**. A 0 érték semleges
 (szürke/zöld), csak > 0 esetén élénk szín; a zsebpénz-csempén nincs kiegészítő felirat.
 A gyermekkártyákon **monogramos avatar**, név, diszkrét jegyszám-badge és nagy átlag;
 a tanév/súlyozás magyarázata a **szakasz fejlécében** van, kikapcsolt zsebpénznél
 diszkrét ikon. A **gyermekszűrő chipek** és az **„Események listája”** gomb a **fül-sáv
 alatt, az összes csempe felett** vannak (a szűrő a csempékre is vonatkozik); a szekció
 neve **„Tanulmányi átlag”**.
- **Alsó feed (2 hasáb):** **„Figyelmet igénylő bejegyzések”** (utolsó 10 feljegyzés,
 típus-badge: piros figyelmeztetés, zöld dicséret, szürke felszereléshiány) és
 **„Legutóbbi jegyek”** (utolsó 10 jegy, színes jegy-körrel).
- **Semleges fülek:** a navigáció ikonjai/feliratai sötétszürkék, csak az aktív fület
 emeli ki a felület (kék szöveg/ikon + alsó kék vonal) — nincs színes ikonkáosz.
- **Tanév-választó a fejlécben:** alapból az aktuális tanév (szept. 1. – aug. 31.);
 az „Összes tanév" opcióval a teljes előzmény látszik (átlag ilyenkor nincs, mert az
 csak tanéven belül értelmezhető). Az üzenetek és az órarend tanév-független.
 A választó csak az **iskolai adatokból** (jegy, hiányzás, igazolás, kifizetés)
 származó tanéveket listázza — az üzenetek évei nem hoznak létre tanév-bejegyzést.
 A dátumválasztók a kiválasztott tanév határain belül maradnak. A tanév **zárása/nyitása
 automatikus**: minden futás után ellenőrizzük a KRÉTA `TanevUid`-t, és ha megváltozik,
 a nyitott tanévet technikailag lezárjuk, az újat megnyitjuk (adatlekérés nélkül; a régi
 tanév adata pótolhatatlan, ezért a szinkron soha nem törli). A fejlécben és a
 választóban látszik a tanév állapota (nyitott/lezárt).
- **Tanév-archívum:** a tanév **lezárásakor** egyszeri ZIP készül a data
 köteten (`data/tanev_archivum/<év>.zip`): táblánként JSON/CSV, kombinált Excel,
 diákonkénti PDF-bizonyítvány, `manifest.json` és SHA-256 ellenőrzés. Ismételt
 zárásnál nem duplikál; kézzel: `python tools/create_tanev_archive.py 2025/2026`.
 Nyitott tanév kézi exportja `<év>_manual_<időbélyeg>.zip` néven készül, hogy ne
 blokkolja a záráskori véglegest; `--final` a kanonikus névhez.
- **Új adat jelölése:** a jegyek/üzenetek/hiányzások/igazolások a saját
 DB-be kerülésük (`letrehozva`) alapján számítanak „mainak” — a KRÉTA visszamenőleges
 bejegyzés-dátuma nem titkolja el a frissen szinkronizált jegyet. Az első migráció a
 legutóbbi 7 nap sorait a migráció időpontjára állítja (ezek a szülőnek ténylegesen
 újak), a régebbieket a KRÉTA-dátumból tölti fel, így azok nem lesznek visszamenőleg újak.
 Az Események táblában a leírás után **közvetlenül** új **Bekerült** oszlop, a
 műveletgombok külön **Műveletek** oszlopban; a részletek modálban is látszik a
 bekerülés időpontja (mai esetén `MA` jelzéssel).

### ☀️ „Ma” nézet
- Önálló fül az Áttekintés után: **mai órák** (időpont, terem, tanár), **ma és holnap
 esedékes** házik és számonkérések pipával (kattintásra készre jelölhető); a **sorra
 kattintva részletek modál** nyílik (téma/leírás, tanár, határidő, állapot), a heti nézet
 határidő-sorain is. **Friss jegyek**
 (7 nap), **olvasatlan üzenetek** (kattintásra megnyílnak). Saját gyermek-chipek; a fül
 megnyitásakor és gyermekváltáskor automatikusan frissül; a fejléc diák-szűrőjét követi.
 **Ma / Hét** szegmentált kapcsoló: a heti nézet **kétoszlopos, középre igazított**
 napkártyákból áll (órák kék, határidők borostyán, vegyes lila színnel; páratlan számnál az
 utolsó kártya középre kerül); a havi nézet nincs.

### 📊 Iskolai események
- DataTables táblázat: szűrés gyermek, típus, tantárgy, aktív/lejárt, dátumtartomány szerint;
 gyorsszűrők (mai, tárgyhavi, előző havi, aktív), szabad szöveges keresés. A **szűrőpanel
 alapból zárva** van, a fejlécére kattintva nyílik ki.
- A mai bejegyzések kiemelése; részletek modal ablakban.
- A jegyeknél a **súlyszázalék** is látszik (pl. `5 (Írásbeli) 100%`), a mobil API
 `SulySzazalekErteke` mezőjéből (Playwright-módban a webes hónap-cella tooltipjének
 `data-suly` attribútumából); tooltip: „Az értékelés 100%-os súllyal számít bele az átlagba."
- **Saját megjegyzés** fűzhető bármelyik sorhoz (jegy, feljegyzés, házi, számonkérés) és
 bármelyik üzenethez — a megjegyzés a szinkronok után is megmarad (tartalom-alapú kulcs).
- **Excel export** a jelenlegi szűrőkkel: **Jegyek / Feljegyzések / Házi feladatok**
 munkalapok (`/api/esemenyek/export.xlsx`).

### 📝 Házi feladat kezelés
- „Elkészült" jelölés, amely **megmarad** a következő szinkronok után is (zöld kiemelés).

### 🚸 Hiányzások és késések
- Saját „Hiányzások" fül: **havi összesítő** (igazolt óra, igazolatlan óra, késések
 darabszáma és percei) gyermek- és hónapválasztóval, „Összes" nézettel.
- Részletes hiányzás-/késés-táblázat (dátum, **aznap hányadik óra**, tantárgy, téma,
 igazolt?, igazolás típusa) és külön **igazolás-lista** (érvényesség, típus, megjegyzés).
 Egy KRÉTA-sor **egy tanórát** jelent (az „Óra” a napon belüli órasorszám).
- Alapból a **teljes előzmény** látszik; a havi bontás a hónapválasztóval vagy az
 „Aktuális hónap” gombbal érhető el.
- A késéseket a KRÉTA „(N perc)” adatából ismeri fel; a havi összesítő külön kezeli őket.
- **Inkrementális mentés:** a rekordot a dátum + órasorszám azonosítja, ezért az
 újraszinkron csak a változásokat írja (a sor-ID stabil, az eltűnt sorok törlődnek).
- **Excel export:** **Hiányzások / Igazolások** munkalapok a jelenlegi szűrőkkel
 (`/api/hianyzasok/export.xlsx`).

### 🗓️ Feladatok naptár
- Házik és számonkérések határidő szerint (FullCalendar 6), színkódolva;
 mobilon listanézet (Havi/Heti lista), a naptári elemből is jelölhető az elkészült.

### 💰 Statisztika & zsebpénz
- Testreszabható jutalom/levonás mátrix jegyekre és viselkedésre.
- Feljegyzések automatikus kategorizálása kulcsszavak alapján.
- Havi elszámolás, egyenleg, kifizetés rögzítése (`KIFIZETVE`).
- **Súlyozott tanulmányi átlag** a jegyek súlyszázaléka szerint (0%-os súly kimarad;
 súlyadat nélkül egyszerű átlag). A statisztika **kikapcsolt zsebpénz mellett is működik** —
 ilyenkor csak a pénz-kártya rejtve, figyelmeztető sávval.
- **Tantárgyi átlagok havi bontással:** alapból zárt accordion a Statisztika fülön.
 Asztalon mátrix (tantárgy × hónap) + „Összes" oszlop + **„Hónapok átlaga" lábléc**;
 mobilon **kapcsoló**: „Havi bontás" (hónap → tantárgy) vagy „Tantárgy szerint"
 (teljes időszak), mindkettő tetején a **teljes átlag**.
- **Trend oszlop** (sparkline + utolsó két hónap különbsége) és **romlás-figyelmeztetés**
 az Áttekintésen (≤ -0,5), **gyermeknévvel és az érintett időszakkal**; alatta zöld sáv a
 **javuló** tantárgyakról (≥ +0,5). A két sáv **lenyitható**: asztalon **helyben**,
 görgethető listává nyílik; mobilon **teljes képernyős**; `Esc`-cel vagy a fejre
 kattintva záródik.
- **„Milyen jegy kell?” kalkulátor:** tantárgy (alapból üres) + célátlag + **várható
 jegyek** (súly + opcionális jegy, akár több, eltérő súllyal) → hányas/os hány ötös kell,
 illetve mennyi a várható átlag; **félévi céljegy** esetén a küszöbhöz szükséges átlag.
 A célátlag/félévi cél **tantárgyanként mentődik**, a kártya a tantárgy **meglévő jegyeit**
 táblázatban listázza, és mindig a **teljes tanév** jegyállományával dolgozik.
- **Aktuális bizonyítvány (PDF, félév / tanév):** A4-es, **dísz-bizonyítvány** kivitelű
 összefoglaló (arany keret, pecsét, serif címek): átlag, jegyek, hiányzás, késés,
 magatartás/szorgalom (ha van); a zsebpénz-egyenleg csak akkor, ha a diákra engedélyezett a
 modul. **Mentés nélkül, közvetlenül generálva** (a böngésző nyitja meg, onnan nyomtatható);
 a felületi kártya és a PDF fejléce is „Aktuális bizonyítvány”, a fő cím a tanévet és az
 időszakot is mutatja. A tantárgyi táblában nincs Db oszlop, a jegyek jegyenként összesítve
 („Jeles(5) - 3 db; Jó(4) - 2 db”), feljegyzés-szekció nincs. A hivatalos félévi jegy a
 KRÉTA API-ból nem érhető el — ezt a PDF jelzi, és a jegyekből számolt átlagot mutatja.

### 🔎 Keresés és UX
- **Globális kereső (Ctrl+K):** jegyek, feljegyzések, házik, üzenetek (teljes törzs) és
 hiányzások; a keresőmező **nyitáskor azonnal aktív**, a találatlistában **↑/↓/Enter**
 navigáció, **Esc** zárás, az utolsó **5 keresés** mentődik; a **találat sorára kattintva
 az adott sor részletei** nyílnak meg, a típus-címkék felirata/színe **egyezik az
 Események füllel**, a megnyitott sor rövid kiemelést kap. Nagyobb adaton **FTS5**
 trigram index gyorsít (LIKE fallbackkel).
- **Sötét mód** (átfogó: kártyacímek, táblázatok, kiemelt sorok, accordion, naptár,
 státuszsáv, modálok; a naptár-események szövegszíne a háttérhez igazodik),
 **nyomtatásbarát heti órarend** (A4 fekvő, a fejlécben „SuliHub – Órarend – gyermek – hét”),
 **kitűzött események** a dashboardon (húzással rendezhető, tételenkénti megjegyzéssel).
- **Hiányzás-mintázat:** nap / órasorszám / tantárgy bontás a Hiányzások fülön (a táblázatok
 alatt, alapból csukva).

### 📱 Mobilra optimalizált UI
- Redmi 12/13/14 méreten (393 CSS px) ellenőrizve: nincs vízszintes túlcsordulás.
- Összecsukható táblázatok, **monogram-avatar** a diák oszlopban, 2 sorba tördelődő
 fülek, teljes képernyős modálok, teljes szélességű vezérlők. Az értékeléseknél mobilon is
 **alapból látszik a jegy** (az „Érték” oszlop megelőzi a típus-badge-et).
- A fejlécben: ütemező állapota, időablak, következő és utolsó futás, **telepített verzió**.

### 🛠️ Üzemeltetés
- Futásnapló a DB-ben (`sync_runs`), napló-rotáció, `waitress` produkciós szerver,
 DB-guard indításkor, napi automatikus mentés forgatással.
- **Havi restore-teszt:** `tools/backup_restore_check.py` — a legfrissebb mentés izolált
 visszaállítása, `integrity_check`, manifest-egyeztetés, ntfy riasztás hibánál.
- **Éjszakai élő füstteszt:** `tools/live_smoke.py` (`/health`, `/api/sync/status`, az
 utolsó futás kora); GitHub Actions job, `KRETA_URL` secret nélkül kimarad.
- **Szinkron-egészség:** 3 egymást követő hiba → magas prioritású ntfy (6 órás throttle),
 token-lejáratnál „KRÉTA belépés lejárt” jelzés; a belépés a `config.json` `STUDENTS`
 adataival **automatikus**, a kézi „Adatok frissítése” azonnal kiváltja, a státuszsáv
 tooltipje/modalja elmagyarázza. A token-hiba csak valódi 401/403/login hiba esetén
 jelenik meg — a napló „tárolt tokenből” info-sora nem téveszti meg.
- **Heti adatminőség-riport:** `tools/data_quality_report.py` (csak olvas; duplikátumok,
 hiányzó csatolmányok, üres mezők, árva megjegyzések, DB-méret, utolsó futás).
- **Teljesítmény-teszt:** 5 000 eseményes fixture a fast csomagban (`test_performance`,
 500 ms küszöb). **DB-migrációk:** verziózott `MIGRATIONS` lánc `.bak`-kal.

---

## 🛠️ Technológiai stack

| Réteg | Eszköz |
|---|---|
| Backend | Python 3.12 (Docker) / 3.14 (lokális), Flask, **waitress**, ReportLab |
| Adatforrás | **Kréta mobil API** — böngésző nélkül |
| Adat | SQLite |
| Frontend | Bootstrap 5.3, jQuery, DataTables (+ Responsive), FullCalendar 6, FontAwesome 6 |
| Konténer | Docker, Docker Compose (Debian slim) |

---

## 🚀 Gyors indítás (lokális)

```bash
git clone https://github.com/reitam/sulihub.git
cd sulihub

python -m venv venv
# Windows: venv\Scripts\activate
# Linux/Mac: source venv/bin/activate

pip install -r requirements.txt
```

Az alkalmazás **API módon** működik, böngésző nélkül. A **böngészős UI-tesztekhez**
(fejlesztés) külön:

```bash
pip install -r requirements-playwright.txt
playwright install chromium
```

Hozz létre `config.json`-t (lásd lent), majd:

```bash
python app.py
# http://127.0.0.1:5000
```

> **Windows-on figyelj a Pythonra:** ha a PATH-ban más Python van (pl. 3.15 a
> függőségek nélkül), az `import flask` hibával elszáll. A `KretaApp_Start.bat`
> automatikusan a projekt venv-jét, majd a `C:\Python314\python.exe`-t választja;
> kézzel ugyanez: `C:\Python314\python.exe app.py`.
>
> A `config.json` helye lokálisan **`data\config.json`**,
> nem a projekt gyökere — a `KretaApp_Start.bat` is ezt ellenőrzi.

Nyomd meg az **„Adatok frissítése a KRÉTA-ból"** gombot az első szinkronhoz.

---

## ⚙️ Konfiguráció

### `config.json`

A fájl **üzleti és belépési adatokat** tartalmaz, ezért **nincs a repóban** és nem
kerül a Docker image-be (`.gitignore` / `.dockerignore`).

```json
{
 "SCRAPE_MESSAGES": true,
 "SYNC_MODE": "api",
 "SZUNET_AKTIV": true,
 "SYNC_SZUNET": [
 {"nev": "Őszi szünet", "kezdo": "2026-10-23", "vege": "2026-11-01", "napi_sync": true, "napi_ido": "18:00"},
 {"nev": "Téli szünet", "kezdo": "2026-12-19", "vege": "2027-01-03", "napi_sync": true, "napi_ido": "18:00"},
 {"nev": "Tavaszi szünet", "kezdo": "2027-03-25", "vege": "2027-04-04", "napi_sync": true, "napi_ido": "18:00"},
 {"nev": "Nyári szünet", "kezdo": "2027-06-19", "vege": "2027-08-31", "napi_sync": true, "napi_ido": "18:00"}
 ],
 "DIGEST": {
 "ENABLED": true,
 "TIME": "19:30",
 "INCLUDE_NAMES": true,
 "SZUNET_NAPOK": []
 },
 "ENABLE_REWARDS": true,
 "SCHEDULER": {
 "ENABLED": true,
 "INTERVAL_MINUTES": 180,
 "START_HOUR": 6,
 "END_HOUR": 22,
 "STALE_ALERT_HOURS": 12
 },
 "REWARDS": {
 "jegy_5": 500,
 "jegy_4": 300,
 "jegy_3": 0,
 "jegy_2": -500,
 "jegy_1": -1000,
 "dicseret": 1000,
 "megrovas": -1000,
 "lecke_hiany": -500,
 "felszereles_hiany": -500
 },
 "KEYWORDS": {
 "dicseret": ["dicséret", "dicséretben", "kiemelkedő", "dicséretet"],
 "megrovas": ["intő", "megrovás", "figyelmeztetés", "elmarasztalás"],
 "lecke_hiany": ["házi feladat hiány", "házi hiány", "lecke hiány", "nem készített házi"],
 "felszereles_hiany": ["felszerelés hiány", "felszerelése hiányzott", "felszereléshiány"]
 },
 "STUDENTS": [
 {
 "diak_nev": "Minta Elemér",
 "institute_code": "iskola_azonosito",
 "username": "FELHASZNÁLÓNÉV",
 "password": "JELSZÓ",
 "active": true,
 "scrape_messages": true,
 "enable_rewards": true
 }
 ]
}
```

> A fájl **UTF-8 BOM**-mal is olvasható (Notepad-barát). A jelszavak sima szövegben
> vannak — a fájl a data köteten, védett könyvtárban él.

**`SYNC_MODE`** — a szinkron forrása:

| Érték | Jelentés |
|---|---|
| `api` | **Alapértelmezés és az egyetlen futó mód.** Csak a mobil API (böngésző nélkül); egy adatkör hibája részleges hiba. **Az üzenet-csatolmányokat is letölti** (`files.e-kreta.hu` nonce URL), a munkamenetet a data köteten tárolja (`api_tokens.json`) — a futások többsége **nem lép be újra**. |

**`NTFY`** — push értesítés (opcionális; enélkül nincs értesítés):

```jsonc
"NTFY": {
 "_comment": "CSA K akkor él, ha a.env-ben nincs NTFY_TOPIC (az env erősebb)",
 "TOPIC": "kreta-3f9c1a7b5e2d4c60", // üresen nincs értesítés; a név maga a cím
 "URL": "https://ntfy.sh", // saját ntfy szerver is lehet
 "NOTIFY_NEW": true, // új információ esetén push (a régi NOTIFY_SUCCESS is elfogadott)
 "INCLUDE_NAMES": false // diáknevek a push-ban (alapból nem)
}
```

A szerveren ugyanezek `NTFY_TOPIC` / `NTFY_URL` / `NTFY_NOTIFY_NEW` /
`NTFY_INCLUDE_NAMES` néven a `.env`-ben is megadhatók — **az env érték erősebb**. Az
ntfy.sh-n nincs regisztráció: a topic nevére kell feliratkozni az appban, ezért használj
hosszú, véletlen nevet. Ellenőrzés a futó appnál: `POST /api/ntfy/test` (teszt-push,
és megmondja, van-e beállított topic).

A forrás és a hibák oka a `sync.log`-ban és a futásnapló `sources` mezőjében látszik
(`docs/DOKUMENTACIO.md` 3.2.1). Mind a 8 adatkör API-ból jön; böngészős út nincs.

### Környezeti változók

Lokálisan nem kötelezők; a Docker-compose állítja be őket.

| Változó | Alapérték | Leírás |
|---|---|---|
| `KRETA_DATA_DIR` | `.` | Adatkönyvtár (DB, config, log, csatolmányok) |
| `KRETA_DB_FILE` / `KRETA_CONFIG_FILE` / `KRETA_LOG_FILE` | data-könyvtáron belül | Egyedi fájlutak |
| `KRETA_CSATOLMANYOK_DIR` | `static/csatolmanyok` | Csatolmányok könyvtára (Dockerben `/app/data/csatolmanyok`) |
| `KRETA_HOST` / `KRETA_PORT` / `KRETA_DEBUG` | `127.0.0.1` / `5000` / ki | Web szerver |
| `KRETA_SERVER` | `flask` | `waitress` = produkciós WSGI szerver (a compose így indít) |
| `KRETA_WAITRESS_THREADS` | `8` | Kiszolgáló szálak száma |
| `NTFY_TOPIC` | *(üres)* | ntfy topic **vagy teljes URL**; üresen nincs értesítés |
| `NTFY_URL` | `https://ntfy.sh` | ntfy szerver címe |
| `NTFY_TIMEOUT` | `5` | ntfy kérés timeout (mp) |
| `NTFY_INCLUDE_NAMES` | `0` | `1` = diáknevek a push-ban |
| `NTFY_NOTIFY_NEW` | `1` | `0` = új adatról ne küldjön push-t (a hiba ettől függetlenül megy); a régi `NTFY_NOTIFY_SUCCESS` is elfogadott |
| `KRETA_LOG_MAX_BYTES` / `KRETA_LOG_BACKUP_COUNT` | `1000000` / `2` | `sync.log` rotáció |
| `KRETA_LOG_API_MAX_BYTES` | `300000` | Az `/api/logs` ennyi bájtot ad vissza a napló végéről |
| `KRETA_SQLITE_WAL` | `0` | `1` = SQLite WAL mód (FUSE köteten nem ajánlott) |
| `KRETA_SYNC_MIN_RATIO` | `0.5` | Adatvédelmi küszöb a teljes cserés mentésnél; `0` = kikapcsolva |
| `KRETA_SCHEDULER_STATE_FILE` | `scheduler_state.json` | **Csak** a régi JSON-állapot egyszeri migrációjához |

---

## ⏱️ Automatikus szinkronizáció (ütemező)

A `SCHEDULER` blokk vezérli; az ütemező az alkalmazáson belül, háttérszálban fut, és
ugyanazt a szinkront indítja, mint a felületi gomb.

| Kulcs | Jelentés |
|---|---|
| `ENABLED` | `false` → nincs automatikus futás (a kézi gomb működik) |
| `INTERVAL_MINUTES` | Két futás közti idő (min. 5 perc; egy futás ~2,2 perc) |
| `START_HOUR` / `END_HOUR` | Opcionális időablak; `0`–`24` = egész nap. Ha az esedékesség az ablakon kívülre esik, a **következő ablaknyitásra** tolódik. |
| `STALE_ALERT_HOURS` | Ennyi óránál régebbi utolsó futás esetén ntfy riasztás (0 = ki; alap 12, max. 6 óránként egyszer) |

**Védelmek / viselkedés:**

- **Nincs lemaradt futás pótlás** — a következő ellenőrzésnél egyszer lefut (30 mp-es tick).
- **A ciklus csak az utolsó ütemezett futáshoz igazodik** — a kézi frissítés nem tolja el.
- **Nincs átfedés** — egyetlen belépési pont (`start_sync`) lock alatt foglalja le.
- **Perzisztált futástörténet** a `sync_runs` táblában; restart után is folytatódik.
- Hibánál nincs újrapróbálkozás-vihar; az első indítás (nincs előzmény) 5 perc múlva.

A fejlécben: `Ütemező: BE/KI`, `időablak`, `következő`, `Utolsó frissítés` (kézi/ütemezett
jelvénnyel és eredménnyel).

**`sync_runs` tábla** (a `kreta_adatok.db`-ben): `trigger`, `started_at`, `finished_at`,
`status` (`running`/`done`/`done_with_errors`/`error`/`stopped`/`interrupted`),
`ok_count`, `total_count`, `failed_students`, `new_events`, `new_messages`, `duration_sec`.

---

## 🔔 Értesítések (ntfy)

Állítsd be a `NTFY_TOPIC`-ot (topic név vagy teljes URL, pl.
`https://ntfy.sh/kreta-reitam-xxxx`), és iratkozz fel rá az ntfy appban.

| Esemény | Értesítés |
|---|---|
| Sikeres szinkron **új információval** | `SuliHub – új adatok` + a futás **deltája**: csak a most beérkezett tételek, a napi digesttel azonos formában, diákonként (a nap korábbi tételei és a „Holnap esedékes" nem ismétlődik) |
| Sikeres szinkron új információ nélkül | *nincs* (a státuszsáv és a napló mutatja) |
| Részleges hiba | `részleges hiba` + a hibás diák(ok) és az új adatok részletei — egy üzenet |
| Hiba | `HIBA`, magas prioritás; token/ismétlődő hiba esetén a health-üzenet ugyanebben az egy üzenetben |
| Elavult adat (12 óra) | `elavult adatok` |
| Leállított futás | *nincs* (szándékosan) |

Futásonként legfeljebb egy push megy ki. Az új adat push kikapcsolható:
`NTFY_NOTIFY_NEW=0` (a hibariasztás ilyenkor is megy).

---

## 📁 Mappa szerkezet

```text
├── app.py # Flask belépő + szinkron/ütemező/ntfy/napló mag
├── views_*.py # HTTP-réteg blueprintekben (pages, events, orarend, messages,
│ # absences, stats, rewards, search) + kreta_exports (PDF/XLSX/CSV)
├── kreta_paths.py # útvonalak (KRETA_* env; alap: data/)
├── kreta_db.py # DB-séma, migrációk, app_meta, futásnapló
├── kreta_settings.py # config.json, verzió, órarend-színek
├── views_common.py # blueprint-építő + közös request-segédek
├── kreta_playwright.py # szinkron futtató: séma + mentők + API-szolgáltatók
├── kreta_archive.py # zárt tanév ZIP-archívuma (JSON/CSV/Excel/PDF + checksum)
├── templates/index.html # Dashboard váza (Bootstrap + DataTables + FullCalendar)
├── static/js/ # core.js + app-main.js (a felület JS-e)
├── static/vendor/ # vendorolt függőségek (offline)
├── tests/ # automatikus tesztek + run_all.py
├── tools/ # api_snapshot, migrate_local_data, mobile_shot, backup_restore_check
├── data/ # futásidejű adatok (NEM verziózott): DB, config.json,
│ # sync.log, api_tokens.json, csatolmányok
├── Dockerfile, docker-compose.yml, entrypoint.sh
├── docs/
│ └── DOKUMENTACIO.md # teljes rendszerdokumentáció
└── README.md
```

---

## 🧪 Tesztelés

```bash
python tests/run_all.py
```

**55 csomag**, izolált temp könyvtárban (a valódi adatokat nem érinti):
ütemező, részleges hiba/ntfy/napló, PDF-betűk, útvonalak, új események kimutatása,
migráció, **DB-séma bootstrap** (hiányzó/üres adatbázis), hiányzások/igazolások, **API-kliens** (fake HTTP), **API-szinkron** (mind a 8
adatkör, **csatolmány-letöltés API-ból**, **token-tár** és fallback-hiba), **szinkronmód/fallback**, **árnyék mód**,
**adatvédelem** (üres válasz nem töröl), **DB-séma őr** (zárolt DB), **esti digest** (tartalom, idempotencia, beállítás-API),
**deploy-konzisztencia** (Dockerfile COPY + requirements), **mobil elrendezés**,
**route-contract** (az 52 Flask-rule rögzítve) és **data/-migráció**.
Részletek: [`tests/README.md`](tests/README.md).

---

## 🐳 Docker élesítés

Az alkalmazás Docker Compose-szal futtatható.

| Fájl | Szerep |
|---|---|
| `Dockerfile` | **Egyetlen image** (`kreta-app:runtime`): Python 3.12, Chromium/playwright nélkül; nem-root futás, `fonts-liberation` a PDF-hez |
| `docker-compose.yml` | 8085-es port, data + mentés kötetek, `KRETA_SERVER=waitress`, healthcheck |
| `entrypoint.sh` | DB-guard: HDD-leszakadásnál nem hoz létre üres DB-t, mentésből visszaállít |
| `.env.example` | Opcionális env-minta (ntfy, `APP_ENVIRONMENT`); a `.env` nem kötelező |
| `config.json.example` | A diákok/tarifák mintája (a valódi a `data/` kötetben) |

```bash
git clone https://github.com/reitam/sulihub.git
cd sulihub
mkdir -p data backup
cp config.json.example data/config.json
# szerkeszd: data/config.json (STUDENTS, AUTH, NTFY...)
docker compose up -d --build
curl http://127.0.0.1:8085/health
```

- A `DATA_DIR` / `BACKUP_DIR` env-ekkel (vagy a compose defaultjaival) állíthatók a kötetek:
 alapból **`./data`** és **`./backup`**. A `.env` csak akkor kell, ha env-ből akarsz
 felülírni (pl. `NTFY_TOPIC`); a Compose a `.env`-et interpolációhoz automatikusan betölti.
- Linuxon, ha a konténer nem tud írni a kötetekbe: `sudo chown -R 1000:1000 data backup`
 (az `APP_UID`/`APP_GID` a compose build args-ban állítható).
- A `config.json`-t a deploy **nem** másolja — a data kötetben kell lennie.
- A szinkron kizárólag a mobil API-ból fut.


---

## 🔒 Biztonság

- Belső hálózaton fut, **nincs bejelentkezés** a felülethez (tudatos kompromisszum).
- A `config.json` (jelszavak) és az adatbázis a data köteten, nem verziózott.
- Az ntfy-re csak állapotinformáció megy; diáknév alapból nem. A topic neve „jelszóként"
 működik — használj hosszú, véletlen nevet.
- Ha a hálózat kiterjed: basic auth vagy reverse proxy javasolt. A óta
 a meglévő, de hibás/olvashatatlan config esetén a védett végpontok 503-at adnak
 (fail-closed); hiányzó confignál az auth nincs beállítva.

---

## 🤝 Hozzájárulás és biztonság

- Hozzájárulás: [`CONTRIBUTING.md`](CONTRIBUTING.md) — feature branch, PR, zöld CI,
 release note, nincs személyes adat/titok.
- Biztonsági bejelentés: [`SECURITY.md`](SECURITY.md) — kérjük, **ne** nyilvános
 issue-ban; használd a GitHub privát sebezhetőség-bejelentését.
- Magatartás: [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

---


## 📚 Kapcsolódó dokumentumok

| Fájl | Tartalom |
|---|---|
| [`docs/DOKUMENTACIO.md`](docs/DOKUMENTACIO.md) | Teljes rendszerdokumentáció (üzleti + technikai) |
| [`tests/README.md`](tests/README.md) | A tesztek leírása |
