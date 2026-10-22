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

## 📁 Mappa Szerkezet

```text
├── app.py                  # Flask webszerver, API és PDF generáló végpontok
├── kreta_playwright.py     # Playwright scraper script a KRÉTA adatgyűjtéshez
├── config.json             # Konfigurációs fájl (belépési adatok, zsebpénz szabályok)
├── kreta_adatok.db         # SQLite adatbázis (automatikusan jön létre)
├── static/
│   ├── favicon.svg         # Weboldal ikonja
│   └── csatolmanyok/       # Letöltött e-Ügyintézés mellékletek
└── templates/
    └── index.html          # Fő Dashboard nézet (Bootstrap + DataTables + FullCalendar)
```