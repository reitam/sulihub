# 📋 KRÉTA Adatlekérő és Webes Áttekintő – Követelményjegyzék és Rendszerterv

> **Megjegyzés (2026-11-02):** ez a dokumentum a **kezdeti követelményjegyzet**
> (Playwright-alapú architektúra). A jelenlegi állapot — **API-first szinkron API-ból,
> Playwright fallbackkel**, Áttekintés dashboard, súlyozott átlagok, tantárgyi bontás,
> statisztika — a **[DOKUMENTACIO.md](DOKUMENTACIO.md)**-ban van leírva; ez a fájl
> történeti referenciának marad.

## 1. Rendszerarchitektúra és Infrastruktúra
* **Adatbázis-kezelő:** Központi, helyi **SQLite** adatbázis (`kreta_adatok.db`) használata az adatok tartós tárolására.
* **Scraper keretrendszer:** **Playwright** (Python `async_playwright`) használata a böngésző-automatizációhoz és a Kendo Grid felületek kezeléséhez.
* **Webes keretrendszer:** **Flask** (Python) háttérszerver a REST API-k és a webes felület kiszolgálásához.
* **Verziókövetés:** Git használata **GitHub** tárhellyel (`reitam/sulihub`, korábban `kreta_adatlekero`), szigorú `.gitignore` szűréssel (adatbázis, jelszavak és letöltött csatolmányok kizárása).
* **Konfigurációkezelés:** Központi `config.json` fájl használata az érzékeny adatok, diákfiókok, egyéni tarifák és beállítások kezelésére.
* **Python Függőségek és Telepítési Követelmények:**
  * **Python verzió:** Python 3.10+ (a projekt Python 3.14 környezetben lett tesztelve).
  * **Telepítendő Python csomagok (`pip`):**
    * `playwright`: A böngésző-automatizációhoz és adatlekéréshez.
    * `flask`: A webes dashboard háttérszerveréhez és a Server-Sent Events (SSE) streameléshez.
  * **Böngésző binárisok:** Playwright Chromium böngészőmotor telepítése (`playwright install chromium`).
  * **Telepítő parancsok összefoglalva:**
    ```cmd
    pip install playwright flask
    playwright install chromium
    ```

---

## 2. Többgyermekes / Többintézményes Adatlekérési Logika (Scraper)
* **Többfiókos támogatás (`STUDENTS` tömb):**
  * Gyerekenként külön paraméterezhető: Diák neve (`diak_nev`), Iskolai azonosító (`institute_code`), Felhasználónév (`username`), Jelszó (`password`), Aktív státusz (`active`).
  * Támogatnia kell az eltérő KLIK / KRÉTA azonosítójú intézményeket (pl. `klik031847001`, `sztmargittatabanya`).
* **Szelektív Adatfrissítés:** Frissítéskor ne törölje a teljes adatbázist, hanem csak az éppen feldolgozott diák korábbi adatait cserélje le (`DELETE FROM esemenyek WHERE diak_nev = ?`).
* **Böngésző láthatóságának vezérlése (Headless mód):** A `config.json`-ban lévő `"HEADLESS": true/false` kapcsolóval konfigurálható, hogy a böngésző láthatóan vagy a háttérben fusson.
* **Granuláris Moduláris Beállítások:** 
  * Globális és diák szintű üzenetlekérési kapcsoló (`"SCRAPE_MESSAGES": true/false` és `"scrape_messages": true/false`).
  * Globális és diák szintű jutalmazási/statisztikai kapcsoló (`"ENABLE_REWARDS": true/false` és `"enable_rewards": true/false`).
* **Biztonságos Munkamenet-kezelés (Logout):** Minden diák adatainak kinyerése után kifejezett kijelentkezést kell végrehajtani a `/Home/LogOut` URL navigációval, megelőzve a munkamenetek összeakadását.

---

## 3. Adatkinyerési és Szűrési Szabályok (Scraper Funkciók)
* **Értékelések (Osztályzatok):**
  * A Kendo Grid hierarchia sorainak automatikus kibontása (`KretaGridHelper.openAllGrid()`).
  * Tantárgy, érdemjegy (szöveges és számi érték), bejegyzés dátuma, értékelő tanár, értékelés típusa, módja és témájának kinyerése.
* **Feljegyzések (Információk):**
  * Bejegyzés dátuma, típusa, tanár neve, címe és szöveges tartalma.
* **Házi feladatok:**
  * Automatikus szűrőkikapcsolás JS-ből (`RegiHaziFeladatokElrejtese = false`), hogy a régi/elmúlt házi feladatok is bekerüljenek.
  * Tantárgy, tanár, szöveg, rögzítés dátuma és határidő kinyerése.
* **Bejelentett számonkérések:**
  * Automatikus szűrőkikapcsolás (korábbi időszakok betöltése).
  * Tantárgy, tanár, számonkérés módja, témája, bejelentés dátuma és a számonkérés napjának kinyerése.

---

## 4. Webes Áttekintő Felület (Dashboard / UI)
* **Design & Keretrendszer:** Responsive **Bootstrap 5**, **DataTables.js** és **FontAwesome** ikonok használata.
* **Statisztikai Kártyák:** A lap tetején vizuális összegző kártyák a kinyert modulok darabszámairól (*Értékelések*, *Házi feladatok*, *Számonkérések*, *Feljegyzések*, *Üzenetek*).
* **Dinamikus Szűrők:**
  1. **Gyermek (Diák):** Egyéni szűrés gyermekre vagy összesített nézet.
  2. **Esemény típusa:** Szűrés modulonként (*Értékelés*, *Feljegyzés*, *Házi feladat*, *Bejelentett számonkérés*).
  3. **Tantárgy:** Dinamikusan feltöltött dropdown menü a meglévő tantárgyakból.
  4. **Státusz / Határidő (Aktív / Lejárt):** Szűrési lehetőség a házi feladatoknál és számonkéréseknél arra, hogy a határidő **🟢 Aktív** (mai / jövőbeli) vagy **⚪ Lejárt** (múltbéli).
  5. **Azonnali Keresőmező:** Szabad-szöveges keresés a teljes táblázatban (tanár, téma, leírás).
* **Szűrők Alaphelyzetbe Állítása:** Egykattintásos piros *„Szűrők törlése”* gomb a szűrőpanel tetején.

---

## 5. Webes Szinkronizálás és Élő Konzol (Live Logging)
* **Indítás Webfelületről:** Egy kattintásos **„Adatok frissítése a KRÉTA-ból”** gomb a webes felületen.
* **Élő Konzol Nézet (Server-Sent Events – SSE):** A szinkronizálás elindításakor megjelenő, valós idejű parancssori log ablak, ami mutatja a `kreta_playwright.py` futási állapotát.
* **Harmonika (Accordion) & Bezárhatóság:**
  * A konzol panel a szinkronizálás végén gombnyomásra felcsukható/kinyitható (Accordion).
  * Egy külön **$\times$ (Bezárás) gombbal** a konzol panel teljesen elrejthető a képernyőről, ha már nincs rá szükség.

---

## 6. e-Ügyintézés (Üzenetek és Csatolmányok) Modul
* **Egyetlen Integrált Scraper:** Az e-Ügyintézés üzeneteinek lekérése a meglévő `kreta_playwright.py` szkriptbe épül be a meglévő bejelentkezési session felhasználásával (`https://eugyintezes.e-kreta.hu/uzenetek`).
* **Inkrementális (Célzott) Szinkronizáció:** Az SQLite adatbázis ellenőrzésével a rendszer kizárólag azokat az üzeneteket nyitja meg és tölti le, amelyek még nem szerepelnek a DB-ben.
* **Csatolt Dokumentumok Mappaszerkezete:** A letöltött fájlok lemezre mentődnek a `static/csatolmanyok/<diak_nev>/` könyvtárba, míg az adatbázisban a relatív útvonal mentődik.
* **Modal Olvasó & Letöltés:** Az üzenet szövege felugró ablakban olvasható, a csatolt dokumentumok pedig közvetlenül letölthetők.

---

## 7. Havi Statisztikai, Feljegyzés-elemző és Zsebpénz-kalkulátor Modul

### 7.1. Célja és Konfigurálhatósága
* **Modul láthatóságának vezérlése (`config.json`):**
  * Globális kapcsoló: `"ENABLE_REWARDS": true/false`
  * Diákonkénti egyedi kapcsoló: `"enable_rewards": true/false`
  * A webes dashboardon a modul lapfüle és kártyái kizárólag akkor jelennek meg, ha az adott diákra/rendszerre engedélyezve van.
* **Konfigurálható Tarifa és Szabályrendszer (`config.json`):**
  * Diákonként megadható forint értékek jegyekre (5, 4, 3, 2, 1) és eseményekre.
  * Szöveges kulcsszótábla a feljegyzések kategóriákba sorolásához.

### 7.2. Feljegyzések Automatikus Szövegelemzése
Mivel a hiányok és elismerések a KRÉTA-ban feljegyzésekként jelennek meg, a háttérszerver a feljegyzés `tartalom` és `cim` mezőiben keress a beállított kulcsszavakat:
1. **Dicséretek:** pl. *„dicséret”*, *„dicséretben”*, *„kiemelkedő”*.
2. **Megrovások / Intők:** pl. *„intő”*, *„megrovás”*, *„figyelmeztetés”*.
3. **Lecke hiányok:** pl. *„házi feladat hiány”*, *„házi hiány”*, *„lecke hiány”*, *„nem készített házi”*.
4. **Felszerelés hiányok:** pl. *„felszerelés hiány”*, *„felszerelése hiányzott”*, *„felszereléshiány”*.

### 7.3. Havi Áttekintés és Pénzügyi Egalizálás (Kalkulátor)
* **Hónap-választó Dropdown:** Szűrési lehetőség az aktuális tanév adott hónapjára (pl. *2026. Október*, *2026. Szeptember*) vagy a teljes tanévre.
* **Havi Osztályzat Eloszlás Mátrix:** Az adott hónapban kapott 5-ösök, 4-esek, 3-asok, 2-esek és 1-esek száma, valamint a havi tanulmányi átlag.
* **Magatartási és Felszerelés Mutatók:** Havi dicséretek, megrovások, lecke- és felszerelésehiányok összesített száma.
* **Havi Zsebpénz / Jutalom Egyenleg:**
  * Kiszámított egyenleg megjelenítése nagy méretű kiemelt kártyán (pozitív esetén 🟢 zöld, negatív esetén 🔴 piros színnel).
  * Részletes pénzügyi bontás (szerzett pluszok a jó jegyekből/dicséretekből vs. levonások a rossz jegyekből/hiányokból).