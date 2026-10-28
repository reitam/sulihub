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
| `START_HOUR` / `END_HOUR` | Opcionális időablak. `0`–`24` (vagy a két érték egyenlő) = **egész nap**, nincs korlátozás |

**Működés / védelmek:**

- **Nincs lemaradt futás pótlás.** Ha a konténer/deploy miatt kimarad egy
  időpont, a következő ellenőrzésnél egyszer lefut, majd visszaáll a normál
  ciklusra (30 másodpercenként ellenőriz).
- **Perzisztált állapot:** a legutóbbi futás a data köteten lévő
  `scheduler_state.json`-ban él, így a gyakori deploy **nem** indít azonnal
  szinkront — a 3 órás ciklus újraindítás után is folytatódik.
- **Nincs átfedés:** a kézi gomb és az ütemező ugyanazt az egy belépési pontot
  (`start_sync`) használja, ami a lock alatt foglalja le a futást. Ha épp fut
  valami, az ütemezett indítás a következő tickre csúszik (nincs sorban állás).
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
- a **következő automatikus futás** (`/api/scheduler/status`), illetve ha épp fut,
  hogy kézi vagy ütemezett szinkron zajlik,
- a **legutóbbi frissítés**: mikor, **kézi vagy automatikus** jelvénnyel, és az
  eredménye (sikeres / hiba / leállítva). Ha az utolsó futás kézi volt, külön
  látszik az **utolsó automatikus** futás ideje is (ez az ütemezés alapja).

> Megjegyzés: az ütemező a Flask processzhez kötött, egy processzes futásra
> készült (a Dockerben `python app.py`, `threaded=True`). Ha valaha több
> workerre váltotok (pl. gunicorn), `--workers 1` kell, különben minden worker
> saját ütemezőt indítana.

---

## 📁 Mappa Szerkezet

```text
├── app.py                  # Flask webszerver, API és PDF generáló végpontok
├── kreta_playwright.py     # Playwright scraper script a KRÉTA adatgyűjtéshez
├── config.json             # Konfigurációs fájl (belépési adatok, zsebpénz szabályok)
├── scheduler_state.json    # Ütemező állapota (legutóbbi futás) — automatikusan jön létre
├── kreta_adatok.db         # SQLite adatbázis (automatikusan jön létre)
├── static/
│   ├── favicon.svg         # Weboldal ikonja
│   └── csatolmanyok/       # Letöltött e-Ügyintézés mellékletek
└── templates/
    └── index.html          # Fő Dashboard nézet (Bootstrap + DataTables + FullCalendar)
```

---

## 🐳 Docker élesítés (HPReiTam szerver)

Az éles környezet a HPReiTam Linux szerveren fut Dockerben (a RabbitApp_Svelte
mintájára), **csak belső hálózaton** érhető el: `http://HPReiTam:8085`.
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
# 1. Samba meghajtó (ha még nincs):  net use h: \\HPReiTam\HP_Share /user:reitam
# 2. Élesítés + a lokális adatok (DB, böngészőprofil, csatolmányok, config.json)
#    felmigrálása + a mentő-cron telepítése:
cd c:\ReiTam\AI\Gemini\Kreta
.\deploy.ps1 -Release v1.0.0 -MigrateLocalData -InstallBackup
```

A szkript jelszót kér az SSH-hoz (`reitam@HPReiTam`). Az első `docker compose
up --build` több percig tart (pip + Chromium letöltés) — ez normális.

**Későbbi frissítések:** `.\deploy.ps1 -Release v1.0.1`

**A szerveren (az éles környezetben):**

- Munka: `/mnt/work/Kreta` — Konténer: `kreta-app` — Port: 8085
- Adatkötet (HDD): `/mnt/Maxxel_HDD/app/Kreta/data` — itt a DB, a `config.json`,
  a böngészőprofil (`browser_user_data`), a csatolmányok és a `sync.log`
- Mentések: `/mnt/Maxxel_HDD/ReiTam_BackUp/Kreta_backup`, cron 3:00-kor
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
| `KRETA_SCHEDULER_STATE_FILE` | data-könyvtáron belül `scheduler_state.json` | Az ütemező állapota (legutóbbi futás) |
| `KRETA_HOST` / `KRETA_PORT` / `KRETA_DEBUG` | `127.0.0.1` / `5000` / ki | Flask szerver beállításai |
