# 🎓 KRÉTA Adatbázis Áttekintő & Zsebpénz Menedzser

> **Teljes rendszerdokumentáció:** [`DOKUMENTACIO.md`](DOKUMENTACIO.md) — üzleti áttekintés,
> architektúra, adatmodell, üzemeltetés, hibaelhárítás, verziótörténet.

Egy központi, **Flask + Playwright** alapú webes alkalmazás, amely automatikusan lekéri és
SQLite adatbázisba szinkronizálja **több gyermek** KRÉTA-rendszerből származó adatait
(órarend, jegyek, feljegyzések, házi feladatok, bejelentett számonkérések, e-Ügyintézés
üzenetek és csatolmányok). A felület egy helyen, áttekinthetően mutatja mindezt —
**asztali és mobil böngészőn is** —, nyomtatható PDF órarendet készít, és **push
értesítést** küld a változásokról.

**Kinek készült?** Egy szülőnek, aki napi szinten követi a gyermekei iskolai életét.
Nem kereskedelmi termék: saját üzemeltetésű, belső hálózaton futó rendszer, az adatok
a saját szerveren maradnak.

**Jelenlegi verzió:** `v1.5.1`

---

## 🌟 Főbb funkciók

### 🤖 Automatikus szinkronizáció
- Playwright/Chromiummal belép a diákfiókokba (**több gyermek, több intézmény** egyszerre).
- Kezeli a sütikezelő ablakot; perzisztens böngészőprofilt használ (kevesebb bejelentkezés).
- Lekéri az **aktuális és következő hét** órarendjét (tanár, terem, csengetési időpontok).
- Jegyek, feljegyzések, házik, számonkérések, **hiányzások/késések és igazolások** mentése;
  az e-Ügyintézés üzenetei **inkrementálisan** (csak az újak) töltődnek, **a csatolmányokkal
  együtt — API-ból, böngésző nélkül** (`api`/`api_first` módban).
- **Részleges hiba ≠ siker:** ha egy gyermek adata nem jön le, a többi frissül, a futás
  „részleges hiba" állapotba kerül, és a hibás gyermek neve megjelenik.

### ⏱️ Ütemező (config-vezérelt)
- Alapból **3 óránként, 6:00–22:00 között** fut (06:00 → 09:00 → 12:00 → 15:00 → 18:00 → 21:00).
- A kézi frissítés **nem tolja el** az automatikus időzítést.
- Átfedés-védelem, perzisztált futástörténet, részleges hibakezelés.

### 🔔 Push értesítések (ntfy)
- Sikeres futás, részleges hiba, hiba és elavult adat esetén.
- A sikeres üzenet tartalmazza a **diákonkénti új eseményeket**:
  `Teszt Elek: 2 jegy, 1 házi` · `Teszt Anna: 1 számonkérés, 2 üzenet, 1 hiányzás (2 igazolatlan óra)`.
- Diáknevek alapból **nem** mennek ki (csak darabszám); kapcsolható.

### 📅 Heti/napi órarend + PDF
- Asztali nézetben idősávos **heti** órarend, mobilon **napi naptár** ‹ › lapozással.
- **A4 fekvő, nyomtatásra kész PDF** (ReportLab), gyermekenként külön oldal;
  magyar **ő/ű/Ő/Ű** helyesen (Unicode betűkészlet).
- Tantárgy szerinti színkódolás, egész napos események külön sávban.

### 📊 Iskolai események
- DataTables táblázat: szűrés gyermek, típus, tantárgy, aktív/lejárt, dátumtartomány szerint;
  gyorsszűrők (mai, tárgyhavi, előző havi, aktív), szabad szöveges keresés.
- A mai bejegyzések kiemelése; részletek modal ablakban.

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

### 🗓️ Feladatok naptár
- Házik és számonkérések határidő szerint (FullCalendar 6), színkódolva;
  mobilon listanézet (Havi/Heti lista), a naptári elemből is jelölhető az elkészült.

### 💰 Statisztika & zsebpénz
- Testreszabható jutalom/levonás mátrix jegyekre és viselkedésre.
- Feljegyzések automatikus kategorizálása kulcsszavak alapján.
- Havi elszámolás, egyenleg, kifizetés rögzítése (`KIFIZETVE`).

### 📱 Mobilra optimalizált UI
- Redmi 12/13/14 méreten (393 CSS px) ellenőrizve: nincs vízszintes túlcsordulás.
- Összecsukható táblázatok, **monogram-avatar** a diák oszlopban, 2 sorba tördelődő
  fülek, teljes képernyős modálok, teljes szélességű vezérlők.
- A fejlécben: ütemező állapota, időablak, következő és utolsó futás, **telepített verzió**.

### 🛠️ Üzemeltetés
- Futásnapló a DB-ben (`sync_runs`), napló-rotáció, `waitress` produkciós szerver,
  DB-guard indításkor, napi automatikus mentés forgatással.

---

## 🛠️ Technológiai stack

| Réteg | Eszköz |
|---|---|
| Backend | Python 3.12 (Docker) / 3.14 (lokális), Flask, **waitress**, ReportLab |
| Scraper | Playwright (Chromium), asyncio |
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
playwright install chromium
```

Hozz létre `config.json`-t (lásd lent), majd:

```bash
python app.py
# http://127.0.0.1:5000
```

Nyomd meg az **„Adatok frissítése a KRÉTA-ból"** gombot az első szinkronhoz.

---

## ⚙️ Konfiguráció

### `config.json`

A fájl **üzleti és belépési adatokat** tartalmaz, ezért **nincs a repóban** és nem
kerül a Docker image-be (`.gitignore` / `.dockerignore`).

```json
{
  "HEADLESS": true,
  "SCRAPE_MESSAGES": true,
  "SYNC_MODE": "api_first",
  "SYNC_SHADOW": false,
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
| `playwright` | Csak a böngészős scraper fut. **Ha a kulcs hiányzik, ez az alap** (biztonságos visszaesés). |
| `api` | Csak a mobil API (böngésző nélkül); egy adatkör hibája részleges hiba. **Az üzenet-csatolmányokat is letölti** (`files.e-kreta.hu` nonce URL). |
| `api_first` | **Ajánlott éles beállítás:** adatkörönként API, hiba esetén automatikus Playwright fallback. |

**`SYNC_SHADOW`** — `api_first` mellett a Playwright is lefut egy **DB-másolaton**, és a
szinkron csak összehasonlítja a kettőt (a `sync.log`-ban `[ÁRNYÉK]` sorok). A valódi
adatbázishoz csak az API ír, így nincs dupla írás. Élesítés előtt 1–2 hétig érdemes
bekapcsolva hagyni, utána kikapcsolható.

**`NTFY`** — push értesítés (opcionális; enélkül nincs értesítés):

```jsonc
"NTFY": {
  "_comment": "CSA K akkor él, ha a .env-ben nincs NTFY_TOPIC (az env erősebb)",
  "TOPIC": "kreta-3f9c1a7b5e2d4c60",   // üresen nincs értesítés; a név maga a cím
  "URL": "https://ntfy.sh",             // saját ntfy szerver is lehet
  "NOTIFY_SUCCESS": true,               // sikeres futásról is küldjön
  "INCLUDE_NAMES": false                // diáknevek a push-ban (alapból nem)
}
```

A szerveren ugyanezek `NTFY_TOPIC` / `NTFY_URL` / `NTFY_NOTIFY_SUCCESS` /
`NTFY_INCLUDE_NAMES` néven a `.env`-ben is megadhatók — **az env érték erősebb**. Az
ntfy.sh-n nincs regisztráció: a topic nevére kell feliratkozni az appban, ezért használj
hosszú, véletlen nevet. Ellenőrzés a futó appnál: `POST /api/ntfy/test` (teszt-push,
és megmondja, van-e beállított topic).

A forrás és a fallback oka a `sync.log`-ban és a futásnapló `sources` mezőjében látszik
(`DOKUMENTACIO.md` 3.2.1). Amelyik adatkörhöz még nincs API-implementáció, azt a
Playwright fedi le.

### Környezeti változók

Lokálisan nem kötelezők; a Docker-compose állítja be őket.

| Változó | Alapérték | Leírás |
|---|---|---|
| `KRETA_DATA_DIR` | `.` | Adatkönyvtár (DB, config, log, csatolmányok) |
| `KRETA_DB_FILE` / `KRETA_CONFIG_FILE` / `KRETA_LOG_FILE` | data-könyvtáron belül | Egyedi fájlutak |
| `KRETA_CSATOLMANYOK_DIR` | `static/csatolmanyok` | Csatolmányok könyvtára (Dockerben `/app/data/csatolmanyok`) |
| `KRETA_BROWSER_DATA_DIR` | `./browser_user_data` | Chromium profil (sütik, munkamenetek) |
| `KRETA_HOST` / `KRETA_PORT` / `KRETA_DEBUG` | `127.0.0.1` / `5000` / ki | Web szerver |
| `KRETA_SERVER` | `flask` | `waitress` = produkciós WSGI szerver (a compose így indít) |
| `KRETA_WAITRESS_THREADS` | `8` | Kiszolgáló szálak száma |
| `NTFY_TOPIC` | *(üres)* | ntfy topic **vagy teljes URL**; üresen nincs értesítés |
| `NTFY_URL` | `https://ntfy.sh` | ntfy szerver címe |
| `NTFY_TIMEOUT` | `5` | ntfy kérés timeout (mp) |
| `NTFY_INCLUDE_NAMES` | `0` | `1` = diáknevek a részleges hiba push-ban |
| `NTFY_NOTIFY_SUCCESS` | `1` | `0` = sikeres futásról ne küldjön push-t |
| `KRETA_LOG_MAX_BYTES` / `KRETA_LOG_BACKUP_COUNT` | `1000000` / `2` | `sync.log` rotáció |
| `KRETA_LOG_API_MAX_BYTES` | `300000` | Az `/api/logs` ennyi bájtot ad vissza a napló végéről |
| `KRETA_SQLITE_WAL` | `0` | `1` = SQLite WAL mód (FUSE köteten nem ajánlott) |
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
| Sikeres szinkron | `KRÉTA szinkron: sikeres` + diákonkénti új események |
| Részleges hiba | `részleges hiba` + hány diák nem frissült |
| Hiba | `HIBA`, magas prioritás |
| Elavult adat (12 óra) | `elavult adatok` |
| Leállított futás | *nincs* (szándékosan) |

A sikeres push kikapcsolható: `NTFY_NOTIFY_SUCCESS=0`.

---

## 📁 Mappa szerkezet

```text
├── app.py                  # Flask: API, felület, ütemező, futásnapló, PDF export
├── kreta_playwright.py     # Playwright scraper
├── templates/index.html    # Dashboard (Bootstrap + DataTables + FullCalendar)
├── static/                 # favicon, csatolmányok (lokálisan)
├── backup/kreta_backup.sh  # napi mentés (szerver)
├── tests/                  # automatikus tesztek + run_all.py
├── tools/mobile_shot.py    # mobil képernyőkép/túlcsordulás ellenőrző segédeszköz
├── config.json             # üzleti beállítások (NEM verziózott)
├── kreta_adatok.db         # SQLite adatbázis (NEM verziózott)
├── Dockerfile, docker-compose.yml, entrypoint.sh
├── deploy.ps1              # élesítő script (Samba + SSH)
├── DOKUMENTACIO.md         # teljes rendszerdokumentáció
└── README.md
```

---

## 🧪 Tesztelés

```bash
python tests/run_all.py
```

**13 csomag, 448 ellenőrzés**, izolált temp könyvtárban (a valódi adatokat nem érinti):
ütemező, részleges hiba/ntfy/napló, PDF-betűk, útvonalak, új események kimutatása,
migráció, **DB-séma bootstrap** (hiányzó/üres adatbázis), hiányzások/igazolások, **API-kliens** (fake HTTP), **API-szinkron** (mind a 8
adatkör, **csatolmány-letöltés API-ból** és fallback-hiba), **szinkronmód/fallback**, **árnyék mód**,
**mobil elrendezés**.
Részletek: [`tests/README.md`](tests/README.md).

---

## 🐳 Docker élesítés (HPReiTam szerver)

Az éles környezet a HPReiTam Linux szerveren fut Dockerben, **csak belső hálózaton**:
`http://HPReiTam:8085`. A lokális (Windows) példány csak tesztelésre való.

| Fájl | Szerep |
|---|---|
| `Dockerfile` | Python 3.12 + Playwright Chromium, nem-root futás, `fonts-liberation` a PDF-hez |
| `docker-compose.yml` | 8085-es port, data + mentés kötetek, `KRETA_SERVER=waitress`, healthcheck |
| `entrypoint.sh` | DB-guard: HDD-leszakadásnál nem hoz létre üres DB-t, mentésből visszaállít |
| `deploy.ps1` | Élesítő script Windowsról (Samba staging + SSH, tag, mentés) |
| `backup/kreta_backup.sh` | Napi cron-mentés (DB snapshot + fájlok + rotáció + ntfy riasztás) |

**Élesítés:**

```powershell
net use h: \\HPReiTam\HP_Share /user:reitam     # ha még nincs
cd c:\ReiTam\AI\Gemini\Kreta
.\deploy.ps1 -Release v1.5.1
```

A script jelszót kér az SSH-hoz. Hibánál **nem** ír „sikeres"-t (nem-nulla kilépési kód).

**Első telepítés** (egyszeri): `-MigrateLocalData -InstallBackup` kapcsolókkal — ez viszi
fel a lokális DB-t, böngészőprofilt, csatolmányokat és a `config.json`-t, valamint
telepíti a mentő-cront.

**A szerveren:**

- Munka: `/mnt/work/Kreta` — konténer: `kreta-app` — port: 8085
- Adatkötet (HDD): `/mnt/Maxxel_HDD/app/Kreta/data` — DB, `config.json`, böngészőprofil,
  csatolmányok, `sync.log`
- Mentések: `/mnt/Maxxel_HDD/ReiTam_BackUp/Kreta_backup` (cron 3:00, 7 napi + 4 heti DB,
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
| v1.5.x | **Hiányzások / késések modul** (havi összesítő, igazolások, push-ban az igazolatlan órák), v1.5.1: „Összes hiányzás" órában + teljes szövegű igazolás-típus |
| v1.4.x | **Mobilra optimalizált felület** (napi naptárnézet, összecsukható táblázatok, avatárok, tördelődő fülek) |
| v1.3.x | Futásnapló a DB-ben (`sync_runs`), WAL opt-in, teljes `DOKUMENTACIO.md` |
| v1.2.x | Részleges hiba, ntfy, napló-rotáció, waitress, tesztek, új események a push-ban |
| v1.1.x | Automatikus ütemező, PDF ő/ű javítás, verzió a fejlécben |
| v1.0.x | Docker-élesítés, mentés, alapfunkciók |

A teljes lista: [`DOKUMENTACIO.md` 13. fejezet](DOKUMENTACIO.md).

---

## 📚 Kapcsolódó dokumentumok

| Fájl | Tartalom |
|---|---|
| [`DOKUMENTACIO.md`](DOKUMENTACIO.md) | Teljes rendszerdokumentáció (üzleti + technikai) |
| [`rendszerterv.md`](rendszerterv.md) | Eredeti követelményjegyzék |
| [`tests/README.md`](tests/README.md) | A tesztek leírása |
