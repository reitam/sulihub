# 🎓 KRÉTA Adatbázis Áttekintő & Zsebpénz Menedzser

> **Teljes rendszerdokumentáció:** [`docs/DOKUMENTACIO.md`](docs/DOKUMENTACIO.md) — üzleti áttekintés,
> architektúra, adatmodell, üzemeltetés, hibaelhárítás, verziótörténet.

Egy központi, **Flask** alapú webes alkalmazás, amely automatikusan lekéri és
SQLite adatbázisba szinkronizálja **több gyermek** KRÉTA-rendszerből származó adatait
(órarend, jegyek, feljegyzések, házi feladatok, bejelentett számonkérések, e-Ügyintézés
üzenetek és csatolmányok). A felület egy helyen, áttekinthetően mutatja mindezt —
**asztali és mobil böngészőn is** —, nyomtatható PDF órarendet készít, és **push
értesítést** küld a változásokról.

**Kinek készült?** Egy szülőnek, aki napi szinten követi a gyermekei iskolai életét.
Nem kereskedelmi termék: saját üzemeltetésű, belső hálózaton futó rendszer, az adatok
a saját szerveren maradnak.

**Jelenlegi verzió:** `v2.4.0` (éles, 2026-11-16); a `v2.6.0` kiadásra kész (2026-11-18)

---

## 🌟 Főbb funkciók

### 🤖 Automatikus szinkronizáció
- A **Kréta mobil API-val** lép be a diákfiókokba (**több gyermek, több intézmény** egyszerre),
  böngésző nélkül — a korábbi Playwright/Chromium scraper a v2.5.0-ban kikerült (#64).
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
- **Szinkron-szünet (Kaneo #145):** a `config.json` `SYNC_SZUNET` intervallumaiban
  (pl. őszi/téli szünet) az automatikus futás kimarad — a felület tetején kiemelt sáv
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
  napon is jön rövid üzenet — **kivéve hétvégén/tanítási szüneten** (Kaneo #133),
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
  órákat megőrzi** — csak az aktuális ablak cserélődik (Kaneo #122).

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
  **javuló** tantárgyakról (≥ +0,5).
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
  („Jeles(5) - 3 db ; Jó(4) - 2 db”), feljegyzés-szekció nincs. A hivatalos félévi jegy a
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
| Adatforrás | **Kréta mobil API** — böngésző nélkül (a Playwright scraper a v2.5.0-ban kikerült, #64) |
| Adat | SQLite |
| Frontend | Bootstrap 5.3, jQuery, DataTables (+ Responsive), FullCalendar 6, FontAwesome 6 |
| Konténer | Docker, Docker Compose (Debian slim) |

---

## 🚀 Gyors indítás (lokális)

```bash
git clone https://github.com/reitam/kreta_adatlekero.git
cd kreta_adatlekero

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
> A `config.json` helye lokálisan **`data\config.json`** (a KRÉ-14 átszervezés óta),
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
| `api_first` / `playwright` | **Örökölt értékek** a böngészős korszakból: figyelmeztetés mellett automatikusan `api`-ra válnak (a Playwright scraper a v2.5.0-ban kikerült, #64). |

**`NTFY`** — push értesítés (opcionális; enélkül nincs értesítés):

```jsonc
"NTFY": {
  "_comment": "CSA K akkor él, ha a .env-ben nincs NTFY_TOPIC (az env erősebb)",
  "TOPIC": "kreta-3f9c1a7b5e2d4c60",   // üresen nincs értesítés; a név maga a cím
  "URL": "https://ntfy.sh",             // saját ntfy szerver is lehet
  "NOTIFY_NEW": true,                   // új információ esetén push (a régi NOTIFY_SUCCESS is elfogadott)
  "INCLUDE_NAMES": false                // diáknevek a push-ban (alapból nem)
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
| Sikeres szinkron **új információval** | `SuliHub – új adatok` + a napi összefoglaló teljes részletessége, diákonként |
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
├── app.py                  # Flask belépő + szinkron/ütemező/ntfy/napló mag
├── views_*.py              # HTTP-réteg blueprintekben (pages, events, orarend, messages,
│                           #   absences, stats, rewards, search) + kreta_exports (PDF/XLSX/CSV)
├── kreta_paths.py          # útvonalak (KRETA_* env; alap: data/)
├── kreta_db.py             # DB-séma, migrációk, app_meta, futásnapló
├── kreta_settings.py       # config.json, verzió, órarend-színek
├── views_common.py         # blueprint-építő + közös request-segédek
├── kreta_playwright.py     # szinkron futtató: séma + mentők + API-szolgáltatók
├── templates/index.html    # Dashboard váza (Bootstrap + DataTables + FullCalendar)
├── static/js/              # core.js + app-main.js (a felület JS-e)
├── static/vendor/          # vendorolt függőségek (offline)
├── backup/kreta_backup.sh  # napi mentés (szerver)
├── tests/                  # automatikus tesztek + run_all.py
├── tools/                  # kaneo_ticket, api_snapshot, migrate_local_data, mobile_shot
├── data/                   # futásidejű adatok (NEM verziózott): DB, config.json,
│                           #   sync.log, api_tokens.json, böngészőprofil, csatolmányok
├── Dockerfile, docker-compose.yml, entrypoint.sh
├── deploy.ps1              # élesítő script (Samba + SSH)
├── docs/
│   ├── DOKUMENTACIO.md     # teljes rendszerdokumentáció
│   ├── rendszerterv.md     # eredeti követelményjegyzék (történeti)
│   ├── AI-ELEMZES-TERV.md  # üzenet-AI integráció terve
│   └── osszefoglalo/       # munkamenet-összefoglalók
└── README.md
```

---

## 🧪 Tesztelés

```bash
python tests/run_all.py
```

**53 csomag, 1599 ellenőrzés**, izolált temp könyvtárban (a valódi adatokat nem érinti):
ütemező, részleges hiba/ntfy/napló, PDF-betűk, útvonalak, új események kimutatása,
migráció, **DB-séma bootstrap** (hiányzó/üres adatbázis), hiányzások/igazolások, **API-kliens** (fake HTTP), **API-szinkron** (mind a 8
adatkör, **csatolmány-letöltés API-ból**, **token-tár** és fallback-hiba), **szinkronmód/fallback**, **árnyék mód**,
**adatvédelem** (üres válasz nem töröl), **DB-séma őr** (zárolt DB), **esti digest** (tartalom, idempotencia, beállítás-API),
**deploy-konzisztencia** (Dockerfile COPY + requirements), **mobil elrendezés**,
**route-contract** (az 52 Flask-rule rögzítve) és **data/-migráció**.
Részletek: [`tests/README.md`](tests/README.md).

---

## 🐳 Docker élesítés (saját szerver szerver)

Az éles környezet a saját szerver Linux szerveren fut Dockerben, **csak belső hálózaton**:
`http://saját szerver:8085`. A lokális (Windows) példány csak tesztelésre való.

| Fájl | Szerep |
|---|---|
| `Dockerfile` | **Egyetlen image** (`kreta-app:runtime`): Python 3.12, Chromium/playwright nélkül; nem-root futás, `fonts-liberation` a PDF-hez |
| `docker-compose.yml` | 8085-es port, data + mentés kötetek, `KRETA_SERVER=waitress`, healthcheck |
| `entrypoint.sh` | DB-guard: HDD-leszakadásnál nem hoz létre üres DB-t, mentésből visszaállít |
| `deploy.ps1` | Élesítő script Windowsról (Samba staging + SSH, tag, mentés) |
| `backup/kreta_backup.sh` | Napi cron-mentés (DB snapshot + fájlok + rotáció + ntfy riasztás) |

**Élesítés:**

```powershell
net use h: \\saját szerver\HP_Share /user:reitam     # ha még nincs
cd c:\ReiTam\AI\Gemini\Kreta
.\deploy.ps1 -Release v2.5.0
```

A script jelszót kér az SSH-hoz. Hibánál **nem** ír „sikeres"-t (nem-nulla kilépési kód).
A v2.5.0-tól nincs böngészős fallback — a szinkron kizárólag a mobil API-ból fut (#64).
A törlés előtti (v2.4.0, Playwright-fallbackes) kód a **`playwright-fallback`** ágon
megmarad vész-visszaálláshoz.

**Első telepítés** (egyszeri): `-MigrateLocalData -InstallBackup` kapcsolókkal — ez viszi
fel a lokális DB-t, csatolmányokat és a `config.json`-t, valamint telepíti a mentő-cront.

**A szerveren:**

- Munka: `/opt/sulihub` — konténer: `kreta-app` — port: 8085
- Adatkötet (HDD): `./data` — DB, `config.json`, csatolmányok,
  `sync.log` (a régi `browser_user_data/` a v2.5.0 után törölhető)
- Mentések: `./backup` (cron 3:00, 7 napi + 4 heti DB,
  fájlok 14 nap, konfig 30 nap)
- ⚠ A szerver `.env`-jébe **TILOS** `DATA_DIR` / `BACKUP_DIR` / `KRETA_DATA_DIR` sort írni
  (a RabbitApp 2026-10-27-i „üres db" incidensét okozta)
- ⚠ A `config.json`-t a deploy **nem** másolja — a data köteten kell lennie

---

## 🔒 Biztonság

- Belső hálózaton fut, **nincs bejelentkezés** a felülethez (tudatos kompromisszum).
- A `config.json` (jelszavak) és az adatbázis a data köteten, nem verziózott.
- Az ntfy-re csak állapotinformáció megy; diáknév alapból nem. A topic neve „jelszóként"
  működik — használj hosszú, véletlen nevet.
- Ha a hálózat kiterjed: basic auth vagy reverse proxy javasolt.

---

## 📌 Verziótörténet (kivonat)

| Verzió | Tartalom |
|---|---|
| v2.6.x | **#128 értesítési politika:** üres sikeres futás nem küld push-t; új adat esetén futásonként egy üzenet a napi összefoglaló részletességével; hiba mindig, a health-riasztással egy üzenetben; `NOTIFY_NEW`. **#145 szinkron-szünet:** `SYNC_SZUNET` intervallumok (pl. iskolai szünetek), a szünet alatt nincs normál automatikus futás, a kézi mindig megy, opcionális napi egy szinkron; felül kiemelt sáv; `SZUNET_AKTIV` mesterkapcsoló. **#133:** hétvégén/szünetnapon az üres napi digest kimarad (a szüneteket elég egyszer, a `SYNC_SZUNET`-ben megadni — a digest ugyanazokat használja). **#134:** a Ma fül **Holnap** (csak órák; a határidők a meglévő „Ma és holnap esedékes” kártyán) és **Igazolandó** kártyával bővült; a felesleges API-mezők (`holnapi_taskak`, `holnapi_hataridok`) törölve. **#144:** a heti nézet a hétvégi napokat is mutatja, ha van óra/határidő |
| v2.5.x | **#64 — Playwright teljes kivezetés:** a böngészös scraper, az árnyék-mód (`kreta_shadow.py`) és a `:playwright` Docker target törölve; a szinkron kizárólag a mobil API-ból fut, böngésző nélkül. Az örökölt `api_first`/`playwright` config-értékek figyelmeztetés mellett `api`-ra váltanak. A Playwright csak a **böngészős UI-tesztek** fejlesztői függősége marad. Visszaállás: a `playwright-fallback` git-ág (a v2.4.0 fallbackes kód) |
| v2.4.x | **Playwright opcionális image (#138):** az alap `runtime` image Chromium és `playwright` csomag nélkül (278 MB), a fallback külön `:playwright` tagben; lazy import + `api` alapmód; **csatolmány-pótlás** `api` módban (max. 3 próba) |
| v2.3.x | **KRÉ-8 esti digest** (gyermekenként egy push a nap eseményeivel + holnapi határidők, manuális „Összefoglaló most”), **KRÉ-127 tantárgy-szűrő** kis/nagybetű-függetlenül, **KRÉ-126 naptár → tagolt részletek modál**; v2.3.1 fejléc 1200 px fix |
| v2.2.x | **Ma fül** határidő-részletei, **tagolt részletek modál** minden nézetben, szűrőpanel **határidő-dátumtartomány**, fogadóóra API-szeletelés (nincs Playwright-fallback) |
| v2.1.x | **Globális kereső (Ctrl+K)** (azonnal aktív mező, ↑/↓/Enter, előzmény, találat-kiemelés, **FTS5**), **jegy-kalkulátor** (üres alap-választó, meglévő jegyek táblázata, **több várható jegy eltérő súllyal**, **félévi céljegy**, **mentett célátlag**, teljes tanév), **aktuális bizonyítvány PDF** (félév/tanév, dísz-bizonyítvány kivitel, mentés nélkül közvetlenül generálva), **Excel exportok** (szűrt lista, jegyek/feljegyzések/házik, hiányzások/igazolások), **sötét mód + nyomtatás + kedvencek** (húzásos sorrend, megjegyzés), **tantárgyi trend + hiányzás-mintázat**, **önálló „Ma” fül Ma/Hét nézettel** (kétoszlopos, színezett heti napkártyák), **új SuliHub logó mindenhol** (fejléc, favicon, PDF-bizonyítvány), **alapból zárt szűrőpanel** a menüsor alatt, **órarend 4 hét előre + múlt megőrzése**, **szinkron-egészség riasztás**, **adatminőség-riport**, **teljesítmény-teszt**, **verziózott DB-migrációk**; mobilon a **jegy oszlop alapból látszik** |
| v2.0.x | **KRÉ-14 refaktor:** `app.py` és a frontend szétbontása (8 blueprint + közös rétegek, `static/js/`), **futásidejű adatok a `data/` alatt** migráló szkripttel; a viselkedés (URL-ek, válaszok, DB-séma) változatlan |
| v1.9.x | **Saját órák** (kézi szakkör/pluszfoglalkozás tanévre/hétre/egyedi időszakra, saját színnel, **módosítható**, egy alkalom vagy sorozat törlése), **naptárba küldés** házihoz/számonkéréshez/üzenethez (előre kitöltött Google esemény), **órarend ICS export** (hét/hónap/félév/tanév), **futástörténet**, **órarend-színek**, **SuliHub arculat** (logó/név), **modern egysoros fejléc**, opcionális **basic auth**, **DB-indexek/sémaverzió**, **zsebpénz CSV**, **teljes üzenettörzs** (a lista csak előnézet volt — #74), **dashboard szűrőfüggetlen újratöltése** (#76); az AI-elemzés csak API-ként elérhető |
| v1.8.x | **Offline-képes frontend:** minden CDN-függőség vendorolva a `static/vendor/` alá (Bootstrap, DataTables, FontAwesome, FullCalendar, jQuery), nincs külső hivatkozás; apróságok (#17: `SyntaxWarning`, érvényes `config.json.example`, halott `autoSyncAlert` törlése) |
| v1.7.x | **Tanév-kezelés** (tanév a rekord dátumából, tanév-választó, tanév-tudatos mentés, állapotgép), **dashboard-újratervezés** (6 csempe, tanulmányi átlag kártyák, 2 hasábos feed), **mobil fejléc** (kompakt egysoros szinkron-státusz, részletek koppintásra) + GitHub Actions CI |
| v1.6.x | **API-first szinkron** (böngésző nélküli mobil API, Playwright fallback, token-tár), **Áttekintés dashboard** kattintható csempékkel, **jegy-súlyszázalék** + **súlyozott tanulmányi átlag**, **tantárgyi átlagok havi bontással** (mobilon kapcsoló), adatvédelem a teljes cserés mentésnél, DB-séma őr |
| v1.5.x | **Hiányzások / késések modul** (havi összesítő, igazolások, push-ban az igazolatlan órák), v1.5.1: „Összes hiányzás" órában + teljes szövegű igazolás-típus |
| v1.4.x | **Mobilra optimalizált felület** (napi naptárnézet, összecsukható táblázatok, avatárok, tördelődő fülek) |
| v1.3.x | Futásnapló a DB-ben (`sync_runs`), WAL opt-in, teljes `DOKUMENTACIO.md` |
| v1.2.x | Részleges hiba, ntfy, napló-rotáció, waitress, tesztek, új események a push-ban |
| v1.1.x | Automatikus ütemező, PDF ő/ű javítás, verzió a fejlécben |
| v1.0.x | Docker-élesítés, mentés, alapfunkciók |

A teljes lista: [`DOKUMENTACIO.md` 13. fejezet](docs/DOKUMENTACIO.md).

---

## 📚 Kapcsolódó dokumentumok

| Fájl | Tartalom |
|---|---|
| [`docs/DOKUMENTACIO.md`](docs/DOKUMENTACIO.md) | Teljes rendszerdokumentáció (üzleti + technikai) |
| [`docs/rendszerterv.md`](docs/rendszerterv.md) | Eredeti követelményjegyzék (történeti) |
| [`docs/AI-ELEMZES-TERV.md`](docs/AI-ELEMZES-TERV.md) | Üzenet-AI (LLM) integráció terve |
| [`docs/osszefoglalo/`](docs/osszefoglalo/) | Munkamenet-összefoglalók (naptárazott) |
| [`tests/README.md`](tests/README.md) | A tesztek leírása |
