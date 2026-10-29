# KRÉTA Adatbázis Áttekintő — Rendszerdokumentáció

| | |
|---|---|
| **Dokumentum verziója** | 1.0 |
| **A rendszer verziója** | v1.4.0 |
| **Utolsó frissítés** | 2026-10-29 |
| **Készítette** | Reiner Tamás (fejlesztés) — OpenCode asszisztens közreműködésével |
| **Karbantartási szabály** | **Minden újabb fejlesztés után frissíteni kell** (lásd a 15. pontot) |

---

## 1. Vezetői összefoglaló

A **KRÉTA Adatbázis Áttekintő** egy saját üzemeltetésű, belső hálózaton futó webalkalmazás,
amely **több gyermek KRÉTA-fiókjából** automatikusan összegyűjti az iskolai információkat,
egy helyen, áttekinthető formában megjeleníti, és **automatikusan értesít** a fontos
változásokról.

**Mit old meg?**

| Probléma a KRÉTA saját felületén | Megoldás ebben az alkalmazásban |
|---|---|
| Gyermekenként külön bejelentkezés, külön felület | Egy felület, mindtöbb gyermek adatai együtt vagy szűrve |
| Nehéz átlátni, „mi történt ma / mi esedékes" | Napi/heti nézetek, határidő-naptár, kiemelések |
| Nincs összesített kép a jegyekről, hiányokról | Statisztika, havi bontás, zsebpénz-elszámolás |
| Nincs értesítés, csak ha belépek | Push értesítés szinkroneredményről és új eseményekről |
| Órarend nyomtatása körülményes | Egy kattintásos, nyomtatható A4 PDF |

**Kinek készült?** Egy szülőnek, aki napi szinten követi több gyermek iskolai életét —
nem intézményi, nem kereskedelmi termék, hanem **családi használatra szabott belső rendszer**.

**Fő jellemzők:** ingyenes és nyílt (saját kód), a KRÉTA adatai a saját szerveren maradnak,
nincs külső felhőszolgáltatás — kivéve az értesítéseket (ntfy), amelyek csak állapotinformációt
továbbítanak.

---

## 2. Funkcionális áttekintés (üzleti nézet)

### 2.1. Automatikus adatgyűjtés (szinkronizáció)

- Az alkalmazás **3 óránként** (6:00–22:00 között) bejelentkezik a gyermekek KRÉTA-fiókjába,
  és lementi az aktuális adatokat.
- **Napirend:** 06:00 → 09:00 → 12:00 → 15:00 → 18:00 → 21:00 (majd másnap 06:00).
  Az éjszakai sávban nem fut.
- Kézzel is indítható a felületi gombbal; a kézi futás **nem tolja el** az automatikus időzítést.
- Egy futás tipikusan **2–2,5 perc**.
- Ha egy gyermek adatai nem jönnek le, a többi **továbbra is frissül** — a futás „részleges hiba"
  állapotba kerül, és az érintett gyermek neve megjelenik.

### 2.2. Mit gyűjt?

| Adatkör | Tartalom |
|---|---|
| **Értékelések** | Tantárgy, érdemjegy, dátum, tanár, típus, témakör |
| **Feljegyzések** | Dicséretek, megrovások, hiányok, egyéb bejegyzések |
| **Házi feladatok** | Tantárgy, tanár, leírás, rögzítés, határidő |
| **Bejelentett számonkérések** | Tantárgy, mód, téma, bejelentés és a számonkérés napja |
| **Heti órarend** | Aktuális és következő hét: tanár, terem, időpont, esetleg egész napos esemény |
| **e-Ügyintézés üzenetek** | Beérkezett üzenetek + csatolt dokumentumok (csak az újak) |

### 2.3. Felület (fő nézetek)

| Fül | Mire való |
|---|---|
| **Iskolai események** | Szűrhető, kereshető táblázat: jegyek, feljegyzések, házik, számonkérések |
| **Heti órarend** | Idősávos heti nézet, gyermekszínekkel; **A4 PDF export** |
| **Feladatok naptár nézet** | Házik és számonkérések határidő szerint, színkódolva |
| **Beérkezett üzenetek** | Üzenetek olvasása, csatolmányok letöltése |
| **Statisztika & Zsebpénz** | Havi jegyeloszlás, átlag, dicséret/hiány mutatók, elszámolás |
| **Rendszernapló** | A szinkronizációk naplója, hibák, előzmények |

**Fejléc:** ütemező állapota (BE/KI), időablak, következő futás, utolsó futás eredménye
(kézi/ütemezett, sikeres/részleges hiba/hiba), valamint a **telepített verzió**.

### 2.4. Mobil használat (telefon)

A felület **mobilra is optimalizált** (Redmi 12/13/14 méret, ~393 CSS px):

- a fejléc egymás alá rendeződik, a frissítés gomb teljes szélességű,
- a statisztika-kártyák 2 oszlopban, tömören jelennek meg,
- a fülek **2 sorba tördelődnek**, minden fül látszik (nem fut ki a képernyőből),
  a szűrőpanel mobilon alapból csukva van, hogy a fülek rögtön elérhetők legyenek,
- a szűrők teljes szélességűek, a dátumtartomány egymás alatt,
- a **táblázatok összecsukhatók**: csak a legfontosabb 2–3 oszlop látszik,
  a többi a sor kinyitásával (▸) érhető el,
- az **órarend mobilon napi naptárnézet** (időrács), ‹ › gombokkal és „Ma"-val
  lehet napot léptetni; a „Hét" váltóval a heti nézet érhető el,
- a **feladatnaptár mobilon listanézetben** indul (időrendben, napokra bontva),
- a modálok szinte teljes képernyőn nyílnak, a napló pedig tördelve olvasható,
- a koppintható elemek (gombok, mezők) legalább ~40 px magasak.

A mobil elrendezést automatizált teszt ellenőrzi (nincs vízszintes túlcsordulás,
a fő elemek a képernyőn belül vannak, a táblázat összecsukott).

### 2.5. Értesítések (push)

| Esemény | Értesítés |
|---|---|
| Sikeres szinkron | „KRÉTA szinkron: sikeres" + **diákonként az új események** (pl. *„2 jegy, 1 házi"*, *„2 üzenet"*) |
| Részleges hiba | „részleges hiba", darabszámmal (nevek nélkül) |
| Hiba | „HIBA", magas prioritás |
| Elavult adat (12 óránál régebbi) | „elavult adatok", max. 6 óránként egyszer |
| Leállított futás | nincs értesítés (szándékosan) |

Az értesítések az **ntfy** szolgáltatáson keresztül mennek a telefonra. Diáknevek alapból
**nem** kerülnek ki; a részletes bontás a felületen és a naplóban látható.

### 2.6. Zsebpénz / jutalom modul (üzleti szabályok)

A rendszer a jegyekhez és viselkedési bejegyzésekhez **forintértéket** rendel, és havi
elszámolást készít. A jelenlegi tarifa (a `config.json`-ban szabadon állítható):

| Esemény | Érték |
|---|---|
| Jeles (5) | **+500 Ft** |
| Jó (4) | **+300 Ft** |
| Közepes (3) | 0 Ft |
| Elégséges (2) | **−500 Ft** |
| Elégtelen (1) | **−1000 Ft** |
| Dicséret | **+1000 Ft** |
| Megrovás / intő | **−1000 Ft** |
| Leckehiány | **−500 Ft** |
| Felszerelés hiány | **−500 Ft** |

- A feljegyzések **kulcsszó alapján** sorolódnak kategóriába (dicséret, megrovás, leckehiány,
  felszereléshiany) — a kulcsszavak a `config.json`-ban bővíthetők.
- Havi bontás: jegyeloszlás, tanulmányi átlag, viselkedési mutatók, egyenleg.
- A kifizetés ténye rögzíthető („KIFIZETVE"), így az elszámolás nyomon követhető.
- A modul **gyermekenként** ki-/bekapcsolható. Jelenleg: Elek és Anna aktív,
  **Bori esetében kikapcsolva**.

---

## 3. Hogyan működik (architektúra)

### 3.1. Komponensek

```
┌─────────────────────────── Docker konténer (saját szerver) ───────────────────────────┐
│                                                                                   │
│   Böngésző (LAN)  ──HTTP:8085──►  Flask alkalmazás (waitress)                     │
│                                     ├─ Webes felület (dashboard)                  │
│                                     ├─ REST API (adatok, PDF, státusz)            │
│                                     ├─ Ütemező (háttérszál, 30 mp-es tick)         │
│                                     └─ Szinkron indítása (gyerekprocessz)         │
│                                              │                                    │
│                                              ▼                                    │
│                                   kreta_playwright.py                             │
│                                   (Playwright + Chromium)                         │
│                                     ├─► KRÉTA (3 fiók)                            │
│                                     └─► e-Ügyintézés (üzenetek, csatolmányok)      │
│                                              │                                    │
│                                              ▼                                    │
│                            SQLite adatbázis  +  csatolmányok (fájlok)              │
│                                                                                   │
└───────────────────────────────────────────────────────────────────────────────────┘
        │                                                    │
        ▼                                                    ▼
   ntfy.sh (push)                                  Host: napi mentés (03:00)
```

### 3.2. Adatfolyam egy futásnál

1. Az ütemező (vagy a gomb) elindítja a szinkront → a DB-ben létrejön egy `sync_runs` sor
   (`running` állapot).
2. A scraper bejelentkezik gyermekenként, kiolvassa az adatokat, menti a DB-be.
3. A scraper a végén gép-olvasható összegzést ír a kimenetére (hány diák, mi hibázott,
   mi az új esemény).
4. Az alkalmazás lezárja a `sync_runs` sort (státusz, darabszámok, új események, futásidő),
   naplózza, és **push értesítést** küld.
5. A felület a következő frissítéskor már az új adatokat mutatja.

### 3.3. Futásállapotok

| Állapot | Jelentés |
|---|---|
| `running` | éppen fut |
| `done` | minden gyermek adata frissült |
| `done_with_errors` | részben sikerült (1+ gyermek hibával) |
| `error` | a folyamat elhalt |
| `stopped` | a felhasználó leállította |
| `interrupted` | a folyamat megszakadt (pl. konténer-újraindítás) |

---

## 4. Adatmodell

Az adatok egyetlen SQLite adatbázisban (`kreta_adatok.db`) vannak, a data köteten.

| Tábla | Mit tartalmaz | Megjegyzés |
|---|---|---|
| `esemenyek` | Jegyek, feljegyzések, házik, számonkérések (közös séma) | `esemeny_tipus` különböztet; a `kesz` jelző a házi „elkészült" állapota |
| `orarend` | Heti órarend sorai (diák, nap, időpont, tantárgy, tanár, terem) | Az aktuális és a következő hét |
| `uzenetek` | e-Ügyintézés üzenetek + csatolmány hivatkozás | Csak az új üzenetek kerülnek be |
| `kifizetesek` | Zsebpénz-elszámolások havi tételei | „KIFIZETVE" állapot, összeg |
| `sync_runs` | **Minden szinkronizáció** egy sora (trigger, időpontok, státusz, darabszámok, új események, futásidő) | Ez adja a „legutóbbi futás" állapotot is |
| `app_meta` | Kulcs–érték technikai állapotok | pl. utolsó elavultsági riasztás ideje |

**Adatmennyiség (2026-10-29):** 165 esemény, 124 órarend-sor, 56 üzenet, 2 elszámolás.

**Fontos üzleti szabályok:**
- A jegyek és feljegyzések futásonként **újratöltődnek** (a KRÉTA az igazság forrása).
- A házik és számonkérések **nem törlődnek**, csak az újak kerülnek be — így megmarad a
  „elkészült" jelölés.
- Az üzenetek **inkrementálisan** töltődnek (csak amit még nem látott).
- A futásnapló megőrzi az előzményeket (napi ~6 sor, évi ~2000 — elhanyagolható méret).

---

## 5. Integrációk

| Integráció | Mire használjuk | Megjegyzés |
|---|---|---|
| **KRÉTA** (`<intézmény>.e-kreta.hu`) | Adatgyűjtés böngésző-automatizálással (Playwright) | több iskolai azonosító; a bejelentkezés sütiképre támaszkodik |
| **e-Ügyintézés** (`eugyintezes.e-kreta.hu`) | Üzenetek + csatolmányok | Csak az új üzeneteket nyitja meg |
| **ntfy** (`ntfy.sh`) | Push értesítések | Csak állapotinformáció; diáknév alapból nem megy ki |
| **Docker / Docker Compose** | Futtatás a szerveren | Konténer: `kreta-app`, port **8085** |
| **Samba + SSH** | Deploy Windowsról a szerverre | `deploy.ps1` (staging másolás + SSH parancsok) |
| **cron (host)** | Napi mentés 03:00-kor | `kreta_backup.sh` |

---

## 6. Konfiguráció

### 6.1. `config.json` — üzleti beállítások

A fájl a **data köteten** él (nem a kód mellett), mert üzleti adatokat és belépési
adatokat tartalmaz. **Nem** kerül a git repóba és a Docker image-be.

| Mező | Jelentés |
|---|---|
| `HEADLESS` | A böngésző háttérben fusson-e (élesben igen) |
| `SCRAPE_MESSAGES` | Üzenetek gyűjtése globálisan |
| `ENABLE_REWARDS` | Zsebpénz modul globálisan |
| `REWARDS` | A 2.5. pont tarifái |
| `KEYWORDS` | A feljegyzések kategorizálásához használt kulcsszavak |
| `SCHEDULER` | `ENABLED`, `INTERVAL_MINUTES` (180), `START_HOUR` (6), `END_HOUR` (22), `STALE_ALERT_HOURS` (12) |
| `STUDENTS[]` | Gyermekenként: név, iskolai azonosító, belépési adatok, aktív, üzenetek, zsebpénz |

### 6.2. Környezeti változók (üzemeltetés)

| Változó | Alapérték | Jelentés |
|---|---|---|
| `KRETA_DATA_DIR` | `.` | Adatkönyvtár (DB, config, log, csatolmányok) |
| `KRETA_DB_FILE` / `KRETA_CONFIG_FILE` / `KRETA_LOG_FILE` | data-könyvtárban | Egyedi útvonalak |
| `KRETA_CSATOLMANYOK_DIR` | `static/csatolmanyok` | Csatolmányok helye (élesben `/app/data/csatolmanyok`) |
| `KRETA_BROWSER_DATA_DIR` | `./browser_user_data` | Chromium profil (sütik) |
| `KRETA_HOST` / `KRETA_PORT` / `KRETA_DEBUG` | `127.0.0.1` / `5000` / ki | Web szerver |
| `KRETA_SERVER` | `flask` | `waitress` = produkciós szerver (a compose így indítja) |
| `KRETA_WAITRESS_THREADS` | `8` | Kiszolgáló szálak |
| `NTFY_TOPIC` | *(üres)* | ntfy topic **vagy teljes URL** — üresen nincs értesítés |
| `NTFY_URL` | `https://ntfy.sh` | ntfy szerver |
| `NTFY_NOTIFY_SUCCESS` | `1` | Sikeres futásról is küldjön-e |
| `NTFY_INCLUDE_NAMES` | `0` | Diáknevek a részleges hiba push-ban |
| `KRETA_LOG_MAX_BYTES` / `_BACKUP_COUNT` | `1000000` / `2` | Napló rotáció |
| `KRETA_SQLITE_WAL` | `0` | WAL mód (a FUSE kötet miatt alapból ki) |

---

## 7. Üzemeltetés

### 7.1. Környezetek

| Környezet | Hely | Cél |
|---|---|---|
| **Éles** | saját szerver szerver, Docker, `http://saját szerver:8085` | napi használat |
| **Fejlesztői** | Windows, `c:\ReiTam\AI\Gemini\Kreta`, `python app.py` | tesztelés, fejlesztés |

### 7.2. Szerver felépítés

| Elem | Útvonal |
|---|---|
| Kód | `/opt/sulihub` |
| Adatkötet (DB, config, napló, csatolmányok, böngészőprofil) | `./data` → konténerben `/app/data` |
| Mentések | `./backup` |
| Szerveroldali elérés Windowsról | `\\server\share\data` (Samba) |

### 7.3. Élesítés (deploy)

```powershell
cd c:\ReiTam\AI\Gemini\Kreta
.\deploy.ps1 -Release vX.Y.Z
```

A folyamat: git tag létrehozása/push → szerveri mentés → staging másolás (Samba) →
SSH: munkakönyvtár frissítése → `docker compose up -d --build` → healthcheck.

**A deploy NEM másolja** a `config.json`-t, az adatbázist és a `sync.log`-ot (ezek a data
köteten élnek). A `config.json`-t szükség esetén **kézzel** kell a data kötetre másolni.

### 7.4. Mentés és visszaállítás

- **Automatikus:** naponta **03:00-kor** (host cron), a konténerből konzisztens
  SQLite-snapshot + fájltömörítés (böngészőprofil, csatolmányok, config).
- **Megőrzés:** 7 napi + 4 heti DB-mentés; fájlok 14 napig; konfiguráció 30 napig.
- **Validálás:** a mentő ellenőrzi az integritást és a minimális méretet; hiba esetén
  **ntfy riasztást** küld.
- **Visszaállítás:** a legfrissebb `kreta_adatok_*.db` visszamásolása a data kötetre
  (konténer leállítása mellett javasolt).

### 7.5. Megfigyelhetőség

| Eszköz | Mit mutat |
|---|---|
| `/health` | állapot + verzió (Docker healthcheck is ezt hívja) |
| `/api/scheduler/status` | ütemező állapota, következő futás, utolsó futás |
| Rendszernapló fül / `sync.log` | részletes futási napló (rotált, max. 1 MB/példány) |
| `sync_runs` tábla | strukturált futástörténet |
| `deploy.log` / `version.txt` | telepített verzió |

### 7.6. Gyakori hibák és teendők

| Tünet | Ok | Teendő |
|---|---|---|
| „A config.json fájl nem található" a futásban | a scraper nem a data könyvtárat nézte (javítva v1.2.1) | verzió ellenőrzése |
| Nincs értesítés | `NTFY_TOPIC` nincs a `.env`-ben, vagy a konténer nem lett újralétrehozva | `.env` + `docker compose up -d --force-recreate` |
| A fejléc „régi" adatot mutat | böngésző-gyorsítótár | Ctrl+F5 |
| Két helyi példány ugyanazon a porton | Windows megengedi (SO_REUSEADDR) | a régi folyamat leállítása |
| DB „malformed" olvasáskor | SMB-n keresztüli olvasás futás közben | nyugalmi állapotban ellenőrizni |

---

## 8. Biztonság és adatvédelem

- **Hálózat:** az alkalmazás **csak belső hálózaton** érhető el (nincs publikus kitettség).
- **Hitelesítés:** jelenleg **nincs** bejelentkezés a felülethez — a belső hálózat a védelmi vonal.
- **Személyes adatok:** gyermeknevek, jegyek, üzenetek. Ezek a saját szerveren maradnak.
- **Belépési adatok:** a `config.json`-ban, egyszerű szövegben; a fájl a data köteten van,
  a konténerben nem olvasható kívülről, és nem kerül verziókövetésbe.
- **ntfy:** a nyilvános `ntfy.sh`-ra csak állapotinformáció megy; diáknév alapból nem.
  A topic neve működik „jelszóként" — ezért hosszú, véletlen.
- **Javasolt fejlesztés:** basic auth vagy reverse proxy, ha a hálózat kiterjed.

---

## 9. Fejlesztés

### 9.1. Technológia

| Réteg | Eszköz |
|---|---|
| Backend | Python 3.12, Flask, waitress, ReportLab (PDF) |
| Scraper | Playwright (Chromium), asyncio |
| Adat | SQLite |
| Frontend | Bootstrap 5.3, jQuery, DataTables, FullCalendar 6, FontAwesome |
| Konténer | Docker, Docker Compose, Debian slim |

### 9.2. Mappaszerkezet

```
Kreta/
├── app.py                 # Flask: API, felület, ütemező, futásnapló, PDF
├── kreta_playwright.py    # scraper
├── templates/index.html   # egyfájlos dashboard
├── static/                # favicon, csatolmányok (lokálisan)
├── backup/kreta_backup.sh # napi mentés
├── tests/                 # automatikus tesztek + futtató
├── config.json            # üzleti beállítások (NEM verziózott)
├── kreta_adatok.db        # adatbázis (NEM verziózott)
├── Dockerfile, docker-compose.yml, entrypoint.sh
├── deploy.ps1             # élesítő script
└── README.md, DOKUMENTACIO.md, rendszerterv.md
```

### 9.3. Tesztek

```bash
python tests/run_all.py
```

Jelenleg **136 automatikus ellenőrzés** hét csomagban: ütemező, részleges hiba/ntfy/napló,
PDF-betűk, útvonalak, új események kimutatása, migráció, **mobil elrendezés** (valódi
böngészőben, 393 px szélességen). A tesztek izolált temp könyvtárban futnak, a valódi
adatokat nem érintik.

### 9.4. Kiadási folyamat

1. Fejlesztés + `python tests/run_all.py` (minden zöld).
2. Commit + push a `main` ágra.
3. `.\deploy.ps1 -Release vX.Y.Z` (a script taget is készít).
4. Ellenőrzés: `/health` verzió, fejléc, szinkron, értesítés.
5. **Dokumentáció frissítése** (lásd 15. pont).

---

## 10. Ismert korlátok

| Korlát | Hatás | Megjegyzés |
|---|---|---|
| Nincs felhasználói hitelesítés | belső hálózaton belül bárki eléri | tudatos kompromisszum |
| Egy processzes ütemező | több worker esetén duplikálódna | Dockerben egy processz fut |
| KRÉTA DOM-scraping | a KRÉTA felületváltása törheti | a JSON API korábban nem bizonyult működőképesnek |
| CDN-függő frontend | internet nélkül nem indul a felület | vendorolás a backlogban |
| `config.json` egyszerű szöveg | jelszavak olvashatók a fájlból | a data kötet védett |
| WAL nem használt | párhuzamos írások ritkák | FUSE kötet miatt biztonságosabb |

---

## 11. Továbbfejlesztési lehetőségek (backlog)

### B) Funkciók

| # | Lehetőség | Üzleti haszon | Becsült ráfordítás |
|---|---|---|---|
| B1 | **Hiányzások / késések modul** (jelenleg nincs ilyen adat) | a legfontosabb hiányzó szülői információ | 3–5 nap |
| B2 | **Órarend-változás figyelés** (terem/tanár/helyettesítés) + értesítés | „mi változott ma" azonnal | 1–2 nap |
| B3 | **Napi/heti digest** összefoglaló | egy üzenetben a nap lényege | 1–2 nap |
| B4 | **Mobilos „Ma" nézet** — kompakt napi kártya | *(a reszponzív mobil elrendezés már elkészült a v1.4.0-ban; ez egy külön napi összefoglaló nézet)* | 1–2 nap |
| B5 | **Futástörténet a felületen** (a `sync_runs` már tárolja) | átlátható előzmények | 0,5–1 nap |
| B6 | Üzenet-keresés, olvasott/olvasatlan, zsebpénz CSV export | kényelem | 1–2 nap |

### C) Karbantarthatóság / kockázatok

| # | Lehetőség | Miért fontos | Becsült ráfordítás |
|---|---|---|---|
| C1 | **CDN-ek vendorolása** (`static/` alá) | internet nélkül most nem indul a felület | 0,5 nap |
| C2 | **CI** (GitHub Actions; a tesztek megvannak, pytest-alakítás) | automatikus ellenőrzés minden commitnál | 0,5–1 nap |
| C3 | `app.py` / `index.html` szétbontása | karbantarthatóság | 3–5 nap |
| C4 | DB-migrációs keret + indexek | hosszú távú stabilitás | 1 nap |
| C5 | **Hitelesítés** (basic auth / reverse proxy) | gyerek-adatok védelme | 0,5–1 nap |
| C6 | Apróságok: `SyntaxWarning`, `config.json.example` vessző, halott `autoSyncAlert` | tisztaság | 2–3 óra |

> **Elvetett irány:** a KRÉTA JSON-végpontok használata a DOM-scraping helyett — a fejlesztés
> során sok helyen kipróbálták és nem működött, ezért marad a Playwright-alapú megoldás.

> A részletes, naprakész lista a munkamemóriában: `~/.config/opencode/memory/kreta.md`
> („Backlog" szakasz).

---

## 12. Fogalomtár

| Fogalom | Jelentés |
|---|---|
| **Szinkron / futás** | Egy teljes adatgyűjtési ciklus (2–2,5 perc) |
| **Ütemező** | Az a háttérfolyamat, ami a 3 órás ciklust vezérli |
| **Részleges hiba** | A futás lefutott, de 1+ gyermek adata nem frissült |
| **Data kötet** | A szerver HDD-jén lévő könyvtár, ahol az adatok élnek |
| **Staging** | A deploy köztes másolási területe (Samba) |
| **ntfy** | Push értesítő szolgáltatás |
| **KRÉTA** | Az iskolai adminisztrációs rendszer |

---

## 13. Verziótörténet

| Verzió | Dátum | Tartalom |
|---|---|---|
| v1.0.x | 2026-10-28 | Docker-élesítés, mentés, alapfunkciók |
| v1.1.0 | 2026-10-28 | Automatikus ütemező (config-vezérelt) |
| v1.1.1 | 2026-10-28 | PDF magyar ő/ű betűk javítása |
| v1.1.2 | 2026-10-28 | Verzió megjelenítése a fejlécben |
| v1.2.0 | 2026-10-29 | Részleges hiba, ntfy, napló-rotáció, waitress, tesztek |
| v1.2.1 | 2026-10-29 | Konténeres útvonalak javítása (config megtalálása) |
| v1.2.2 | 2026-10-29 | ntfy üzenetformátum (JSON → olvasható szöveg) |
| v1.2.3 | 2026-10-29 | Új események a push-üzenetben |
| v1.3.0 | 2026-10-29 | Futásnapló a DB-ben (`sync_runs`, `app_meta`) |
| **v1.3.1** | **2026-10-29** | WAL alapból kikapcsolva (FUSE kötet), induláskori integritás-ellenőrzés, **ez a dokumentum** |
| **v1.4.0** | **2026-10-29** | **Mobilra optimalizált felület** (Redmi 12/13/14): összecsukható táblázatok, **napi naptárnézet lapozással**, 2 sorba tördelődő fülek, teljes szélességű vezérlők + mobil elrendezés-teszt |

---

## 14. Kapcsolódó dokumentumok

| Fájl | Tartalom |
|---|---|
| `README.md` | Rövid üzemeltetői útmutató, telepítés, konfiguráció |
| `rendszerterv.md` | Eredeti követelményjegyzék és rendszerterv |
| `tests/README.md` | A tesztek leírása és futtatása |
| `DOKUMENTACIO.md` | **Ez a dokumentum** — teljes rendszerleírás |

---

## 15. A dokumentáció karbantartása (kötelező szabály)

> **Minden újabb fejlesztés, javítás vagy üzemeltetési változás után ezt a dokumentumot
> frissíteni kell — ugyanabban a commitban, mint a kódváltozást.**

Frissítendő részek:

| Ha ez változik… | Ezt kell frissíteni |
|---|---|
| Új funkció / felület | 2. pont (funkcionális áttekintés), szükség esetén 12. (fogalomtár) |
| Adatmodell / új tábla | 4. pont |
| Konfigurációs mező / env változó | 6. pont |
| Deploy, mentés, üzemeltetés | 7. pont |
| Biztonsági döntés | 8. pont |
| Tesztek száma / eszközök | 9.3. pont |
| Új kiadás | 13. pont (verziótörténet) + a fejléc „A rendszer verziója" |
| Megszűnő korlát vagy új ismert korlát | 10. pont |

A frissítés a fejlesztő (illetve a fejlesztést végző asszisztens) felelőssége; a
munkamenet-memória (`~/.config/opencode/memory/kreta.md`) is rögzíti ezt a szabályt.
