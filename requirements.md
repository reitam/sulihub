# 📋 KRÉTA Adatlekérő és Webes Áttekintő – Követelményjegyzék

## 1. Rendszerarchitektúra és Infrastruktúra
* **Adatbázis-kezelő:** Központi, helyi **SQLite** adatbázis (`kreta_adatok.db`) használata az adatok tartós tárolására.
* **Scraper keretrendszer:** **Playwright** (Python `async_playwright`) használata a böngésző-automatizációhoz és a Kendo Grid felületek kezeléséhez.
* **Webes keretrendszer:** **Flask** (Python) háttérszerver a REST API-k és a webes felület kiszolgálásához.
* **Verziókövetés:** Git használata **GitHub** tárhellyel (`reitam/kreta_adatlekero`), szigorú `.gitignore` szűréssel (adatbázis és jelszavak kizárása).
* **Konfigurációkezelés:** Központi `config.json` fájl használata az érzékeny adatok, diákfiókok és beállítások kezelésére.

---

## 2. Többgyermekes / Többintézményes Adatlekérési Logika (Scraper)
* **Többfiókos támogatás (`STUDENTS` tömb):**
  * Gyerekenként külön paraméterezhető: Diák neve (`diak_nev`), Iskolai azonosító (`institute_code`), Felhasználónév (`username`), Jelszó (`password`), Aktív státusz (`active`).
  * Támogatnia kell az eltérő KLIK / KRÉTA azonosítójú intézményeket (pl. `klik031847001`, `sztmargittatabanya`).
* **Szelektív Adatfrissítés:** Frissítéskor ne törölje a teljes adatbázist, hanem csak az éppen feldolgozott diák korábbi adatait cserélje le (`DELETE FROM esemenyek WHERE diak_nev = ?`).
* **Böngésző láthatóságának vezérlése (Headless mód):** A `config.json`-ban lévő `"HEADLESS": true/false` kapcsolóval konfigurálható, hogy a böngésző láthatóan vagy a háttérben fusson.
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
* **Statisztikai Kártyák:** A lap tetején vizuális összegző kártyák a kinyert modulok darabszámairól (*Értékelések*, *Házi feladatok*, *Számonkérések*, *Feljegyzések*).
* **Dinamikus Szűrők:**
  1. **Gyermek (Diák):** Egyéni szűrés gyermekre vagy összesített nézet.
  2. **Esemény típusa:** Szűrés modulonként (*Értékelés*, *Feljegyzés*, *Házi feladat*, *Bejelentett számonkérés*).
  3. **Tantárgy:** Dinamikusan feltöltött dropdown menü a meglévő tantárgyakból.
  4. **Státusz / Határidő (Aktív / Lejárt):** Szűrési lehetőség a házi feladatoknál és számonkéréseknél arra, hogy a határidő **🟢 Aktív** (mai / jövőbeli) vagy **⚪ Lejárt** (múltbéli).
  5. **Azonnali Keresőmező:** Szabad-szöveges keresés a teljes táblázatban (tanár, téma, leírás).