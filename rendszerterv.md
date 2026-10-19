# 📋 KRÉTA Adatlekérő és Webes Áttekintő – Követelményjegyzék és Rendszerterv

## 1. Rendszerarchitektúra és Infrastruktúra
* **Adatbázis-kezelő:** Központi, helyi **SQLite** adatbázis (`kreta_adatok.db`) használata az adatok tartós tárolására[cite: 9].
* **Scraper keretrendszer:** **Playwright** (Python `async_playwright`) használata a böngésző-automatizációhoz és a Kendo Grid felületek kezeléséhez[cite: 9].
* **Webes keretrendszer:** **Flask** (Python) háttérszerver a REST API-k és a webes felület kiszolgálásához[cite: 9].
* **Verziókövetés:** Git használata **GitHub** tárhellyel (`reitam/kreta_adatlekero`), szigorú `.gitignore` szűréssel (adatbázis és jelszavak kizárása)[cite: 9].
* **Konfigurációkezelés:** Központi `config.json` fájl használata az érzékeny adatok, diákfiókok és beállítások kezelésére[cite: 9].
* **Python Függőségek és Telepítési Követelmények:**[cite: 9]
  * **Python verzió:** Python 3.10+ (a projekt Python 3.14 környezetben lett tesztelve)[cite: 9].
  * **Telepítendő Python csomagok (`pip`):**[cite: 9]
    * `playwright`: A böngésző-automatizációhoz és adatlekéréshez[cite: 9].
    * `flask`: A webes dashboard háttérszerveréhez és a Server-Sent Events (SSE) streameléshez[cite: 9].
  * **Böngésző binárisok:** Playwright Chromium böngészőmotor telepítése (`playwright install chromium`)[cite: 9].
  * **Telepítő parancsok összefoglalva:**[cite: 9]
    ```cmd
    pip install playwright flask
    playwright install chromium
    ```

---

## 2. Többgyermekes / Többintézményes Adatlekérési Logika (Scraper)
* **Többfiókos támogatás (`STUDENTS` tömb):**[cite: 9]
  * Gyerekenként külön paraméterezhető: Diák neve (`diak_nev`), Iskolai azonosító (`institute_code`), Felhasználónév (`username`), Jelszó (`password`), Aktív státusz (`active`)[cite: 9].
  * Támogatnia kell az eltérő KLIK / KRÉTA azonosítójú intézményeket (pl. `klik031847001`, `sztmargittatabanya`)[cite: 9].
* **Szelektív Adatfrissítés:** Frissítéskor ne törölje a teljes adatbázist, hanem csak az éppen feldolgozott diák korábbi adatait cserélje le (`DELETE FROM esemenyek WHERE diak_nev = ?`)[cite: 9].
* **Böngésző láthatóságának vezérlése (Headless mód):** A `config.json`-ban lévő `"HEADLESS": true/false` kapcsolóval konfigurálható, hogy a böngésző láthatóan vagy a háttérben fusson[cite: 9].
* **Moduláris Beállítások:** Szabadon kapcsolható üzenetlekérés a `config.json`-ban (`"SCRAPE_MESSAGES": true/false`).
* **Biztonságos Munkamenet-kezelés (Logout):** Minden diák adatainak kinyerése után kifejezett kijelentkezést kell végrehajtani a `/Home/LogOut` URL navigációval, megelőzve a munkamenetek összeakadását[cite: 9].

---

## 3. Adatkinyerési és Szűrési Szabályok (Scraper Funkciók)
* **Értékelések (Osztályzatok):**[cite: 9]
  * A Kendo Grid hierarchia sorainak automatikus kibontása (`KretaGridHelper.openAllGrid()`)[cite: 9].
  * Tantárgy, érdemjegy (szöveges és számi érték), bejegyzés dátuma, értékelő tanár, értékelés típusa, módja és témájának kinyerése[cite: 9].
* **Feljegyzések (Információk):**[cite: 9]
  * Bejegyzés dátuma, típusa, tanár neve, címe és szöveges tartalma[cite: 9].
* **Házi feladatok:**[cite: 9]
  * Automatikus szűrőkikapcsolás JS-ből (`RegiHaziFeladatokElrejtese = false`), hogy a régi/elmúlt házi feladatok is bekerüljenek[cite: 9].
  * Tantárgy, tanár, szöveg, rögzítés dátuma és határidő kinyerése[cite: 9].
* **Bejelentett számonkérések:**[cite: 9]
  * Automatikus szűrőkikapcsolás (korábbi időszakok betöltése)[cite: 9].
  * Tantárgy, tanár, számonkérés módja, témája, bejelentés dátuma és a számonkérés napjának kinyerése[cite: 9].

---

## 4. Webes Áttekintő Felület (Dashboard / UI)
* **Design & Keretrendszer:** Responsive **Bootstrap 5**, **DataTables.js** és **FontAwesome** ikonok használata[cite: 9].
* **Statisztikai Kártyák:** A lap tetején vizuális összegző kártyák a kinyert modulok darabszámairól (*Értékelések*, *Házi feladatok*, *Számonkérések*, *Feljegyzések*)[cite: 9].
* **Dinamikus Szűrők:**[cite: 9]
  1. **Gyermek (Diák):** Egyéni szűrés gyermekre vagy összesített nézet[cite: 9].
  2. **Esemény típusa:** Szűrés modulonként (*Értékelés*, *Feljegyzés*, *Házi feladat*, *Bejelentett számonkérés*)[cite: 9].
  3. **Tantárgy:** Dinamikusan feltöltött dropdown menü a meglévő tantárgyakból[cite: 9].
  4. **Státusz / Határidő (Aktív / Lejárt):** Szűrési lehetőség a házi feladatoknál és számonkéréseknél arra, hogy a határidő **🟢 Aktív** (mai / jövőbeli) vagy **⚪ Lejárt** (múltbéli)[cite: 9].
  5. **Azonnali Keresőmező:** Szabad-szöveges keresés a teljes táblázatban (tanár, téma, leírás)[cite: 9].
* **Szűrők Alaphelyzetbe Állítása:** Egykattintásos piros *„Szűrők törlése”* gomb a szűrőpanel tetején.

---

## 5. Webes Szinkronizálás és Élő Konzol (Live Logging)
* **Indítás Webfelületről:** Egy kattintásos **„Adatok frissítése a KRÉTA-ból”** gomb a webes felületen[cite: 9].
* **Élő Konzol Nézet (Server-Sent Events – SSE):** A szinkronizálás elindításakor megjelenő, valós idejű parancssori log ablak, ami mutatja a `kreta_playwright.py` futási állapotát[cite: 9].
* **Harmonika (Accordion) & Bezárhatóság:**[cite: 9]
  * A konzol panel a szinkronizálás végén gombnyomásra felcsukható/kinyitható (Accordion)[cite: 9].
  * Egy külön **$\times$ (Bezárás) gombbal** a konzol panel teljesen elrejthető a képernyőről, ha már nincs rá szükség[cite: 9].

---

## 6. e-Ügyintézés (Üzenetek és Csatolmányok) Modul Terve

### 6.1. Architektúra és Munkamenet
* **Egyetlen Integrált Scraper:** Az e-Ügyintézés üzeneteinek lekérése a meglévő `kreta_playwright.py` szkriptbe épül be a meglévő bejelentkezési session felhasználásával (`https://eugyintezes.e-kreta.hu/uzenetek`)[cite: 7, 8].
* **Fiókonkénti SSO Navigáció:** A sima KRÉTA modulok lekérése után a böngésző ugyanazon a nyitott munkameneten belül átlép az e-Ügyintézés felületére, elkerülve az ismételt azonosítást.

### 6.2. Inkrementális (Célzott) Szinkronizáció
* **Adatbázis-struktúra (`uzenetek` tábla):**
  * Mezók: `id`, `diak_nev`, `uzenet_id`, `felado`, `targy`, `idopont`, `szoveg`, `csatolmany_nev`, `csatolmany_utvonal`.
* **Csak az Új Üzenetek Megnyitása:**
  * A scraper beolvassa a beérkezett üzenetek listáját (Feladó, Tárgy, Időpont)[cite: 7].
  * Összeveti az SQLite adatbázisban már meglévő rekordokkal.
  * **Kizárólag azokra az üzenetekre kattint rá, amelyek még nem szerepelnek az adatbázisban[cite: 7, 8],** így minimalizálva a hálózati forgalmat és a szinkronizációs időt.

### 6.3. Csatolt Dokumentumok Letöltése és Tárolása
* **Fájlrendszer alapú Tárolás:** A bináris fájlok nem a `.db` adatbázisba, hanem lemezre mentődnek a Flask által kiszolgálható mappába:  
  `static/csatolmanyok/<diak_nev>/<uzenet_id>/<fájlnév>`
* **Automatikus Letöltés:** A Playwright `expect_download()` eseménykezelőjével az üzenet megtekintésekor a rendszer az esetleges csatolt dokumentumokat (PDF, JPG stb.) automatikusan letölti és elmenti[cite: 8].
* **Relatív Útvonal Nyilvántartás:** Az SQLite adatbázisban a csatolt fájl relatív elérési útvonala kerül eltárolásra.

### 6.4. Dashboard Integráció
* **Üzenetek Kártya és Fül:** Külön statisztikai kártya az üzenetek darabszámáról és dedikált fül/nézet az üzenetek böngészéséhez.
* **Modal Olvasó Ablak:** Az üzenetre kattintva felugró ablakban olvasható a teljes üzenet szövege és feladója[cite: 8].
* **Közvetlen Csatolmány Letöltés:** Az üzenet alján lévő linkre kattintva a szülő közvetlenül a webes felületéről töltheti le az iskola által küldött csatolt fájlokat[cite: 8].