# 🎓 KRÉTA Adatbázis Áttekintő & Zsebpénz Menedzser

Egy központi, Flask és Playwright alapú webes alkalmazás, amely automatikusan lekéri és SQLite adatbázisba szinkronizálja több gyermek KRÉTA rendszerből származó adatait (órarend, osztályzatok, feljegyzések, házi feladatok, bejelentett számonkérések és e-Ügyintézés üzenetek). 

A rendszer emellett átlátható felületet nyújt az órarendek megjelenítéséhez és nyomtatásához, a határidők naptári áttekintéséhez, a házi feladatok ellenőrzéséhez/megoldásához, valamint egy testreszabható tanulmányi zsebpénz-elszámolási modult is biztosít.

---

## 🌟 Főbb Funkciók

- **🤖 Automatikus KRÉTA Szinkronizáció:**
  - Playwright segítségével belép a megadott diákok fiókjába (több gyermek támogatása egyszerre).
  - Kezeli a belépés előtti süti (cookie) elfogadó ablakot.
  - Lekéri az aktuális és a következő hét **heti órarendjét** (tanár, terem, csengetési időpontok).
  - Letölti az osztályzatokat, feljegyzéseket, házi feladatokat és bejelentett számonkéréseket.
  - Bejelentkezik az **e-Ügyintézés** felületre, letölti a beérkezett üzeneteket és az e-mailekhez csatolt dokumentumokat.

- **📅 Heti Órarend Nézet & Nyomtatható PDF Export:**
  - Idősávos FullCalendar heti órarendi nézet egyedi diák színkódolással.
  - **A4 landscape méretű, nyomtatásra kész PDF exportálás** (ReportLab alapon).
  - Gyermekre történő szűrés támogatása:
    - Ha egy konkrét gyermek van kiválasztva, pontosan az ő 1 oldalas heti órarendje kerül exportálásra.
    - Ha az *„-- Összes gyermek --”* lehetőség van kiválasztva, gyermekenként külön-külön oldalra kerül a szóló heti órarend.
  - **Valódi csengetési rend kezelése**: Az adatbázisból beolvasott pontos kezdési és zárási időpontok alapján építi fel a táblázatot.
  - **Téma szerinti színkódolás**: A tantárgyak automatikus tématikus háttérszínt kapnak (reál tárgyak, humán tárgyak/nyelvek, testnevelés, művészeti tárgyak, szünetek/ünnepnapok).
  - **Egész napos események elkülönítése**: Az egész napos rendezvények és szünetek külön fejlécsorba kerülnek a számozott tanórák felett.

- **📊 Iskolai Események Áttekintése:**
  - DataTables alapú, reszponzív, átméretezhető oszlopokkal ellátott táblázat.
  - Összetett szűrés: gyermek, esemény típusa, tantárgy, aktív/lejárt státusz, illetve bejegyzés kelte (-tól -ig) szerint.
  - Gyorsszűrők: *Mai események*, *Tárgyhavi események*, *Előző havi események*, *Aktív események*.
  - Mai napon keletkezett bejegyzések kiemelése pasztellsárga háttérrel és zöld `MA` jelvénnyel.
  - Egységes részletek megtekintése (nagyító gomb) modal ablakban.

- **📝 Házi Feladat Ellenőrzés & Megoldás Kezelés:**
  - A házi feladatoknál megjelölhető, hogy a szülő ellenőrizte / a gyermek elkészítette (`Elkészült`).
  - Elkészültként megjelölve a sor betűszíne és háttere kímélő zöldre vált.
  - Az elkészültségi állapot megőrződik a későbbi KRÉTA szinkronizálások során is.

- **🗓️ Feladatok Naptár Nézet (FullCalendar 6):**
  - Külön fülön jeleníti meg a házi feladatok és bejelentett számonkérések határidejét.
  - Színkódolt csempék: Kék (Házi feladat), Zöld (Elkészített házi feladat), Piros (Bejelentett számonkérés).
  - Saját gyermekszűrő a naptár fejlécében.
  - A naptári elemekre kattintva a felugró ablakból is átkapcsolható a házi feladatok elkészültségi állapota.

- **💰 Statisztika & Zsebpénz Elszámolás:**
  - Testreszabható jutalom/levonás mátrix a megszerzett érdemjegyekre (5, 4, 3, 2, 1).
  - Magatartási és szorgalmi bejegyzések automatikus kategorizálása kulcsszavak alapján (*Dicséret*, *Megrovás/Intő*, *Lecke hiány*, *Felszerelés hiány*).
  - Dátumintervallum alapú elszámolás generálása.
  - Kifizetés állapotának rögzítése és mentése az adatbázisban (`KIFIZETVE`).

- **📱 Letisztult UI / UX Design:**
  - A fejlécben a **telepített verzió** is látszik (a deploy által írt `version.txt`-ből).
  - Összecsukható felső statisztikai és szűrőpanel (Accordion), amely automatikusan bezáródik a naptárra, órarendre vagy üzenetekre váltáskor.
  - Az e-Ügyintézés üzeneteinek felesleges halmozott sortöréseit automatikusan letisztítja a jobb olvashatóság érdekében.

---

## 🛠️ Technológiai Stakk

- **Backend:** Python 3.10+, Flask, SQLite3, Subprocess, ReportLab (PDF generálás)
- **Scraper / Automatizáció:** Playwright (Chromium)
- **Frontend:** HTML5, CSS3, JavaScript (ES6+), Bootstrap 5, jQuery
- **Bővítmények:** DataTables, FullCalendar 6, FontAwesome 6

---

## 🚀 Telepítés és Beállítás

### 1. A tárhely klónozása
```bash
git clone https://github.com/felhasznalonev/kreta-adatbazis-manger.git
cd kreta-adatbazis-manger
```

### 2. Virtuális környezet létrehozása és függőségek telepítése
```bash
# Virtuális környezet létrehozása
python -m venv venv

# Aktiválás Windows-on:
venv\Scripts\activate
# Aktiválás Linux/Mac-en:
source venv/bin/activate

# Szükséges csomagok telepítése
pip install flask playwright reportlab
playwright install chromium
```

### 3. Konfigurációs fájl elkészítése (`config.json`)
Hozz létre egy `config.json` fájlt a projekt gyökérmappájában az alábbi minta alapján:

```json
{
  "HEADLESS": true,
  "SCRAPE_MESSAGES": true,
  "ENABLE_REWARDS": true,
  "SCHEDULER": {
    "ENABLED": true,
    "INTERVAL_MINUTES": 180,
    "START_HOUR": 0,
    "END_HOUR": 24
  },
  "REWARDS": {
    "jegy_5": 500,
    "jegy_4": 200,
    "jegy_3": 0,
    "jegy_2": -200,
    "jegy_1": -500,
    "dicseret": 500,
    "megrovas": -500,
    "lecke_hiany": -300,
    "felszereles_hiany": -300
  },
  "KEYWORDS": {
    "dicseret": ["dicséret", "dicséretben", "kiemelkedő", "dicséretet"],
    "megrovas": ["intő", "megrovás", "figyelmeztetés", "elmarasztalás"],
    "lecke_hiany": ["házi feladat hiány", "házi hiány", "lecke hiány", "nem veolt készített házi"],
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

---

## 🖥️ Használat

1. Indítsd el a Flask alkalmazást:
   ```bash
   python app.py
   ```
2. Nyisd meg a böngésződben a következő címet:
   `http://127.0.0.1:5000`
3. Nyomd meg az **"Adatok frissítése a KRÉTA-ból"** gombot az adatok első szinkronizálásához.
4. Navigálj a **Heti Órarend** fülre, válaszd ki a kívánt gyermeket, majd kattints az **"Órarend letöltése PDF-ben"** gombra az A4 nyomtatható órarend előállításához.

---

## ⏱️ Automatikus szinkronizáció (ütemező)

A `config.json` **`SCHEDULER`** blokkja vezérli az időzített futást — az ütemező
az alkalmazáson belül, egy háttérszálban fut, és ugyanazt a szinkront indítja,
mint a felületi gomb (a konzol és a `/api/sync/status` is mutatja).

```json
"SCHEDULER": {
  "ENABLED": true,
  "INTERVAL_MINUTES": 180,
  "START_HOUR": 0,
  "END_HOUR": 24
}
```

| Kulcs | Jelentés |
|---|---|
| `ENABLED` | `false` esetén nincs automatikus futás (a kézi gomb persze működik) |
| `INTERVAL_MINUTES` | Két futás közti idő az **utolsó futás kezdetétől** (min. 5 perc; egy futás ~2,2 perc) |
| `START_HOUR` / `END_HOUR` | Opcionális időablak. `0`–`24` (vagy a két érték egyenlő) = **egész nap**, nincs korlátozás. Ha az esedékesség időpontja az ablakon kívülre esik (pl. 22:16 + 3 óra = 01:16, de az ablak 6–22), a futás a **következő ablaknyitásra** tolódik (06:00) — a felület is ezt mutatja. |
| `STALE_ALERT_HOURS` | Ennyi óránál régebbi utolsó futás esetén **ntfy riasztás** (0 = kikapcsolva; alapérték 12). Legalább 6 óránként egyszer riaszt. |

> A `STALE_ALERT_HOURS` értéke legyen nagyobb a leghosszabb éjszakai szünetnél
> (6–22 ablaknál 21:00 → 06:00 = 9 óra), különben minden reggel téves riasztás jön.

**Működés / védelmek:**

- **Nincs lemaradt futás pótlás.** Ha a konténer/deploy miatt kimarad egy
  időpont, a következő ellenőrzésnél egyszer lefut, majd visszaáll a normál
  ciklusra (30 másodpercenként ellenőriz).
- **Perzisztált állapot:** minden futás egy sor a `kreta_adatok.db` **`sync_runs`**
  táblájában (trigger, kezdés/vége, státusz, darabszámok, új események). Így van
  **történet** is, és a gyakori deploy **nem** indít azonnal szinkront — a ciklus
  újraindítás után is folytatódik. A régi `scheduler_state.json` egyszeri
  migrációval átkerül (`.migrated` néven megmarad).
- **Nincs átfedés:** a kézi gomb és az ütemező ugyanazt az egy belépési pontot
  (`start_sync`) használja, ami a lock alatt foglalja le a futást. Ha épp fut
  valami, az ütemezett indítás a következő tickre csúszik (nincs sorban állás).
- **Részleges hiba nem siker:** ha egy diák feldolgozása elhasal, a többi adata
  továbbra is mentődik, de a futás állapota **`done_with_errors`** lesz (a felületen
  „részleges hiba", a hibás diák nevével; a naplóban is látszik). A scraper ehhez
  `##KRETA_RESULT##{...}` összegzést ír a kimenetére és 2-es kilépési kóddal tér vissza.
- **ntfy értesítés** hiba / részleges hiba / elavult adat esetén (lásd `NTFY_TOPIC`),
  valamint **sikeres futásnál** is (`NTFY_NOTIFY_SUCCESS`, alapból be). A futás utáni
  push tartalmazza a **diákonkénti új eseményeket** is (jegy / házi / számonkérés /
  feljegyzés / üzenet darabszám), pl. `Teszt Elek: 2 jegy, 1 házi`.
- **Hibánál nincs újrapróbálkozás-vihar:** a következő kísérlet a normál
  intervallum után lesz.
- **Első indítás:** ha még sosem futott (nincs állapotfájl), 5 perc múlva indul.
- **A ciklus KIZÁRÓLAG az utolsó ütemezett futáshoz igazodik.** Egy kézi
  „Adatok frissítése" **nem** tolja el az automatikus időzítést: ha az automata
  22:49-kor esedékes, egy 22:15-ös kézi frissítés után is 22:49-kor fut.
  (A felület ilyenkor külön kiírja az „utolsó automatikus" időpontját is.)
- A naplóban a `sync.log` külön sort kap minden futás elejére és végére:
  `KÉZI SZINKRONIZÁCIÓ INDÍTÁSA (felületi gomb)`,
  `ÜTEMEZETT SZINKRONIZÁCIÓ INDÍTÁSA (ütemező: 180 percenként)`,
  `SZINKRONIZÁCIÓ VÉGE (ütemezett): done, 2.3 perc`.

A fejlécben a gomb alatt látszik:

- **`Ütemező: BE` / `Ütemező: KI`** jelvény (a `SCHEDULER.ENABLED` állapota),
- az **időablak** a configból: `időablak: 06:00–22:00` (vagy `egész nap`),
- a **következő automatikus futás** (`/api/scheduler/status`), illetve ha épp fut,
  hogy kézi vagy ütemezett szinkron zajlik; mellette az intervallum az
  időszakra vonatkoztatva: *(az időszakban 180 percenként)*,
- a **legutóbbi frissítés**: mikor, **kézi vagy automatikus** jelvénnyel, és az
  **adott futás eredménye** (sikeres / hiba / leállítva / folyamatban / megszakadt).
  Ha az utolsó futás kézi volt, külön — szintén saját eredménnyel — látszik az
  **utolsó automatikus** futás is (ez az ütemezés alapja).

> Megjegyzés: az ütemező a Flask processzhez kötött, egy processzes futásra
> készült (a Dockerben `python app.py`, `threaded=True`). Ha valaha több
> workerre váltotok (pl. gunicorn), `--workers 1` kell, különben minden worker
> saját ütemezőt indítana.

**Futásnapló — `sync_runs` tábla (a `kreta_adatok.db`-ben):**

| Oszlop | Tartalom |
|---|---|
| `trigger` | `manual` / `scheduled` |
| `started_at`, `finished_at` | ISO időpontok |
| `status` | `running`, `done`, `done_with_errors`, `error`, `stopped`, `interrupted` |
| `ok_count` / `total_count` | hány diák frissült |
| `failed_students` | JSON lista |
| `new_events` / `new_messages` | JSON: diákonkénti új események / üzenetek |
| `duration_sec` | futásidő |

A „legutóbbi futás" és „legutóbbi ütemezett futás" állapot ebből **levezethető**
(nincs külön állapotfájl). Induláskor a beragadt `running` sorok `interrupted`-ra
váltanak. Az adatbázis **WAL módban** fut, hogy az app és a scraper párhuzamos
írása ne akadjon össze.

---

## 📁 Mappa Szerkezet

```text
├── app.py                  # Flask webszerver, API és PDF generáló végpontok
├── kreta_playwright.py     # Playwright scraper script a KRÉTA adatgyűjtéshez
├── config.json             # Konfigurációs fájl (belépési adatok, zsebpénz szabályok)
├── scheduler_state.json    # CSAK migrációhoz: a régi állapot (.migrated néven marad meg)
├── kreta_adatok.db         # SQLite adatbázis (automatikusan jön létre)
├── static/
│   ├── favicon.svg         # Weboldal ikonja
│   └── csatolmanyok/       # Letöltött e-Ügyintézés mellékletek
└── templates/
    └── index.html          # Fő Dashboard nézet (Bootstrap + DataTables + FullCalendar)
```

---

## 🧪 Tesztelés

```bash
python tests/run_all.py
```

Három teszt-csomag (ütemező, A-csomag: részleges hiba/ntfy/napló, PDF-betűk), izolált
temp könyvtárban — a valódi adatbázist és `config.json`-t nem érintik.
Részletek: [`tests/README.md`](tests/README.md).

---

## 🐳 Docker élesítés (saját szerver szerver)

Az éles környezet a saját szerver Linux szerveren fut Dockerben (a RabbitApp_Svelte
mintájára), **csak belső hálózaton** érhető el: `http://saját szerver:8085`.
A lokális (Windows) példány ezentúl csak tesztelésre való.

**Fájlok:**

| Fájl | Szerep |
|---|---|
| `Dockerfile` | Python 3.12 + Playwright Chromium kép, nem-root futás |
| `docker-compose.yml` | 8085-ös port, data + mentés kötetek, healthcheck |
| `entrypoint.sh` | DB-guard: HDD-leszakadásnál nem hoz létre üres DB-t, mentésből visszaállít |
| `.env.example` | Szerveroldali `.env` minta (csak `APP_ENVIRONMENT=PROD`) |
| `deploy.ps1` | Élesítő script Windowsról (Samba staging + SSH) |
| `backup/kreta_backup.sh` | Napi cron-mentés (DB snapshot + fájlok + forgatás) |

**Első élesítés (egyszeri):**

```powershell
# 0. Zárd be a lokális KRETA appot! (a DB-t nem szabad futás közben másolni)
# 1. Samba meghajtó (ha még nincs):  net use h: \\saját szerver\HP_Share /user:reitam
# 2. Élesítés + a lokális adatok (DB, böngészőprofil, csatolmányok, config.json)
#    felmigrálása + a mentő-cron telepítése:
cd c:\ReiTam\AI\Gemini\Kreta
.\deploy.ps1 -Release v1.0.0 -MigrateLocalData -InstallBackup
```

A szkript jelszót kér az SSH-hoz (`reitam@saját szerver`). Az első `docker compose
up --build` több percig tart (pip + Chromium letöltés) — ez normális.

**Későbbi frissítések:** `.\deploy.ps1 -Release v1.0.1`

**A szerveren (az éles környezetben):**

- Munka: `/opt/sulihub` — Konténer: `kreta-app` — Port: 8085
- Adatkötet (HDD): `./data` — itt a DB, a `config.json`,
  a böngészőprofil (`browser_user_data`), a csatolmányok és a `sync.log`
- Mentések: `./backup`, cron 3:00-kor
  (`/home/reitam/docker-backup/kreta_backup.sh`, log: `kretabackup.log`)
- ⚠ A szerver `.env`-jébe **TILOS** `DATA_DIR` / `BACKUP_DIR` / `KRETA_DATA_DIR`
  sort írni (a RabbitApp 2026-10-27-i „üres db” incidensét okozta) — a
  kötet-útvonalakat a `docker-compose.yml` defaultjai tartalmazzák.

**Környezeti változók** (lokális futtatásnál nem kötelezők, a Docker-compose beállítja):

| Változó | Alapérték | Leírás |
|---|---|---|
| `KRETA_DATA_DIR` | `.` | Adatkönyvtár (DB, config, log, csatolmányok) |
| `KRETA_DB_FILE` / `KRETA_CONFIG_FILE` / `KRETA_LOG_FILE` | data-könyvtáron belül | Egyedi fájlutak |
| `KRETA_CSATOLMANYOK_DIR` | `static/csatolmanyok` | Csatolmányok könyvtára |
| `KRETA_BROWSER_DATA_DIR` | `./browser_user_data` | Chromium profil (sütik, munkamenetek) |
| `KRETA_SCHEDULER_STATE_FILE` | data-könyvtáron belül `scheduler_state.json` | **Csak kompatibilitás:** a régi JSON-állapot egyszeri migrációjához (utána `.migrated`) |
| `KRETA_HOST` / `KRETA_PORT` / `KRETA_DEBUG` | `127.0.0.1` / `5000` / ki | Flask szerver beállításai |
| `KRETA_SERVER` | `flask` | `waitress` = produkciós WSGI szerver (a compose így indítja); `flask` = dev szerver |
| `KRETA_WAITRESS_THREADS` | `8` | A waitress szálainak száma |
| `NTFY_TOPIC` | *(üres)* | ntfy push topic **vagy teljes URL** (pl. `https://ntfy.sh/kreta-xyz`, mint a mentő-scriptnél); üresen hagyva nincs értesítés |
| `NTFY_URL` | `https://ntfy.sh` | ntfy szerver címe (csak ha a `NTFY_TOPIC` nem teljes URL) |
| `NTFY_TIMEOUT` | `5` | ntfy kérés timeout (mp) |
| `NTFY_INCLUDE_NAMES` | `0` | `1` = a részleges hiba push-ban szerepeljenek a diáknevek (alapból csak darabszám) |
| `NTFY_NOTIFY_SUCCESS` | `1` | `0` = sikeres futásról ne küldjön push-t (alapból küld) |
| `KRETA_LOG_MAX_BYTES` / `KRETA_LOG_BACKUP_COUNT` | `1000000` / `2` | `sync.log` rotáció (méret / mentett példányok) |
| `KRETA_LOG_API_MAX_BYTES` | `300000` | Az `/api/logs` ennyi bájtot ad vissza a napló végéről |
