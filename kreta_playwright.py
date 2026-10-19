import asyncio
import json
import sqlite3
import os
from playwright.async_api import async_playwright

# --- KONFIGURÁCIÓ BEOLVASÁSA ---
CONFIG_FILE = "config.json"

if not os.path.exists(CONFIG_FILE):
    print(f"HIBA: A {CONFIG_FILE} fájl nem található!")
    exit(1)

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

HEADLESS_MODE = config.get("HEADLESS", True)
STUDENTS = config.get("STUDENTS", [])

if not STUDENTS:
    print("HIBA: A config.json nem tartalmaz 'STUDENTS' listát!")
    exit(1)

def init_db():
    """Létrehozza a táblát, ha még nem létezik (NEM törli az egész táblát!)."""
    conn = sqlite3.connect("kreta_adatok.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS esemenyek (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            diak_nev TEXT,
            esemeny_tipus TEXT,   -- 'Értékelés', 'Feljegyzés', 'Házi feladat', 'Bejelentett számonkérés'
            tantargy TEXT,
            ertek TEXT,
            szam_ertek INTEGER,
            bej_datum TEXT,
            hatarido TEXT,
            ertekelo TEXT,
            tipus TEXT,
            mod TEXT,
            tema TEXT,
            cim TEXT,
            tartalom TEXT
        )
    ''')
    conn.commit()
    conn.close()

def clear_student_data(diak_nev):
    """Csak az adott diák korábbi adatait törli az adatbázisból a frissítés előtt."""
    conn = sqlite3.connect("kreta_adatok.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM esemenyek WHERE diak_nev = ?", (diak_nev,))
    conn.commit()
    conn.close()

def save_esemenyek_to_db(diak_nev, esemenyek):
    """Menti az adott diák kinyert eseményeit az adatbázisba."""
    conn = sqlite3.connect("kreta_adatok.db")
    cursor = conn.cursor()
    
    for e in esemenyek:
        cursor.execute('''
            INSERT INTO esemenyek 
            (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek, bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            diak_nev, 
            e.get('esemeny_tipus', ''),
            e.get('tantargy', ''),
            e.get('ertek', ''),
            e.get('szam_ertek', 0),
            e.get('bej_datum', ''),
            e.get('hatarido', ''),
            e.get('ertekelo', ''),
            e.get('tipus', ''),
            e.get('mod', ''),
            e.get('tema', ''),
            e.get('cim', ''),
            e.get('tartalom', '')
        ))
        
    conn.commit()
    conn.close()

async def process_student(page, student):
    diak_nev = student.get("diak_nev", "Ismeretlen")
    institute_code = student.get("institute_code", "")
    username = student.get("username", "")
    password = student.get("password", "")

    print("\n" + "=" * 70)
    print(f"  FELDOLGOZÁS: {diak_nev.upper()} (Iskola: {institute_code})")
    print("=" * 70)

    # --- 1. BELÉPÉS ---
    login_url = f"https://{institute_code}.e-kreta.hu"
    print(f"1. Kapcsolódás: {login_url} ...")
    await page.goto(login_url)

    await page.wait_for_selector('input[name="UserName"]', timeout=15000)
    await page.fill('input[name="UserName"]', username)
    await page.fill('input[name="Password"]', password)
    await page.press('input[name="Password"]', 'Enter')

    await page.wait_for_url(lambda url: "login" not in url.lower(), timeout=30000)
    await page.wait_for_load_state("networkidle")
    print("Sikeres belépés!")

    # --- 2. OSZTÁLYZATOK KINYERÉSE ---
    print("\n2. Navigáció az 'Osztályzatok' oldalra...")
    await page.goto(f"https://{institute_code}.e-kreta.hu/TanuloErtekeles/Osztalyzatok")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector('tr.k-master-row, tbody tr:not(.k-no-data)', timeout=15000)
    await asyncio.sleep(2)

    await page.evaluate('''() => {
        if (typeof KretaGridHelper !== 'undefined' && KretaGridHelper.openAllGrid) {
            KretaGridHelper.openAllGrid();
        } else {
            let links = document.querySelectorAll('.k-hierarchy-cell a, .k-i-expand, td.k-hierarchy-cell');
            links.forEach(l => l.click());
        }
    }''')
    await asyncio.sleep(3)

    js_ertekeles_extractor = """
    () => {
        let lista = [];
        let gridEl = document.querySelector('.k-grid');
        if (!gridEl) return lista;
        let grid = $(gridEl).data("kendoGrid");
        if (!grid) return lista;
        
        let masterRows = grid.tbody.find('> tr.k-master-row');
        masterRows.each(function() {
            let mRow = $(this);
            let dataItem = grid.dataItem(mRow);
            let tantargy = dataItem ? (dataItem.TantargyNev || "") : "";
            
            let dRow = mRow.next('tr.k-detail-row');
            if (dRow.length > 0) {
                let detailRows = dRow.find('tbody tr');
                detailRows.each(function() {
                    let cols = $(this).find('td');
                    if (cols.length >= 5) {
                        let datum = cols.eq(1).text().trim();
                        let ertekelo = cols.eq(2).text().trim();
                        let tipus = cols.eq(3).text().trim();
                        let mod = cols.eq(4).text().trim();
                        let ertekStr = cols.eq(5).text().trim();
                        let tema = cols.eq(6).text().trim();
                        
                        if (datum && datum.length >= 8 && datum !== "Bej. dátum") {
                            let szam = 0;
                            let match = ertekStr.match(/\\((\\d+)\\)/);
                            if (match) {
                                szam = parseInt(match[1]);
                            } else if (!isNaN(parseInt(ertekStr))) {
                                szam = parseInt(ertekStr);
                            }

                            lista.push({
                                esemeny_tipus: 'Értékelés',
                                tantargy: tantargy || "Általános",
                                ertek: ertekStr,
                                szam_ertek: szam,
                                bej_datum: datum,
                                ertekelo: ertekelo,
                                tipus: tipus,
                                mod: mod,
                                tema: tema
                            });
                        }
                    }
                });
            }
        });
        return lista;
    }
    """
    jegyek = await page.evaluate(js_ertekeles_extractor)
    print(f"Siker! Beolvasva {len(jegyek)} db osztályzat.")

    # --- 3. FELJEGYZÉSEK KINYERÉSE ---
    print("\n3. Navigáció a 'Feljegyzések' oldalra...")
    await page.goto(f"https://{institute_code}.e-kreta.hu/TanuloErtekeles/InformaciokFeljegyzesek")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector('#InformaciokFeljegyzesekGrid tbody tr', timeout=15000)
    await asyncio.sleep(2)

    js_feljegyzes_extractor = """
    () => {
        let lista = [];
        let gridEl = document.querySelector('#InformaciokFeljegyzesekGrid');
        if (!gridEl) return lista;
        let grid = $(gridEl).data("kendoGrid");
        if (grid) {
            let dataItems = grid.dataSource.data();
            dataItems.forEach(item => {
                let datumStr = "";
                if (item.Datum) {
                    let d = new Date(item.Datum);
                    if (!isNaN(d.getTime())) {
                        let y = d.getFullYear();
                        let m = String(d.getMonth() + 1).padStart(2, '0');
                        let day = String(d.getDate()).padStart(2, '0');
                        datumStr = `${y}. ${m}. ${day}.`;
                    } else {
                        datumStr = String(item.Datum);
                    }
                }

                lista.push({
                    esemeny_tipus: 'Feljegyzés',
                    bej_datum: datumStr,
                    tipus: item.Tipus_DNAME || "",
                    ertekelo: item.TanarElotagNelkul || item.Tanar || "",
                    cim: item.Cim || "",
                    tartalom: item.Tartalom || ""
                });
            });
        }
        return lista;
    }
    """
    feljegyzesek = await page.evaluate(js_feljegyzes_extractor)
    print(f"Siker! Beolvasva {len(feljegyzesek)} db feljegyzés.")

    # --- 4. HÁZI FELADATOK KINYERÉSE ---
    print("\n4. Navigáció a 'Házi feladatok' oldalra...")
    await page.goto(f"https://{institute_code}.e-kreta.hu/Tanulo/TanuloHaziFeladat")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector('#searchForm', timeout=15000)
    await asyncio.sleep(1)

    await page.evaluate('''() => {
        let cb = document.getElementById('RegiHaziFeladatokElrejtese');
        if (cb) cb.checked = false;
        if (typeof KretaGridHelper !== 'undefined' && KretaGridHelper.refreshGridSearchPanel) {
            KretaGridHelper.refreshGridSearchPanel("TanulotHaziFeladatkGrid", "searchForm");
        } else {
            let btn = document.getElementById('searchPanelBtn');
            if (btn) btn.click();
        }
    }''')
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(3)

    js_hazifeladat_extractor = """
    () => {
        let lista = [];
        let gridEl = document.querySelector('#TanulotHaziFeladatkGrid');
        if (!gridEl) return lista;
        let grid = $(gridEl).data("kendoGrid");
        if (grid) {
            let dataItems = grid.dataSource.data();
            dataItems.forEach(item => {
                let formatDate = (dVal) => {
                    if (!dVal) return "";
                    let d = new Date(dVal);
                    if (isNaN(d.getTime())) return String(dVal);
                    let y = d.getFullYear();
                    let m = String(d.getMonth() + 1).padStart(2, '0');
                    let day = String(d.getDate()).padStart(2, '0');
                    return `${y}. ${m}. ${day}.`;
                };

                lista.push({
                    esemeny_tipus: 'Házi feladat',
                    tantargy: item.TantargyNev || "",
                    ertekelo: item.TanarNeve || "",
                    tartalom: item.HaziFeladatSzoveg || "",
                    bej_datum: formatDate(item.HaziFeladatTenylegesRogzitesDatuma),
                    hatarido: formatDate(item.HaziFeladatHatarido)
                });
            });
        }
        return lista;
    }
    """
    hazifeladatok = await page.evaluate(js_hazifeladat_extractor)
    print(f"Siker! Beolvasva {len(hazifeladatok)} db házi feladat.")

    # --- 5. BEJELENTETT SZÁMONKÉRÉSEK KINYERÉSE ---
    print("\n5. Navigáció a 'Bejelentett számonkérések' oldalra...")
    await page.goto(f"https://{institute_code}.e-kreta.hu/Tanulo/TanuloBejelentettSzamonkeresek")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector('#searchForm, .k-grid', timeout=15000)
    await asyncio.sleep(1)

    await page.evaluate('''() => {
        let checkboxes = document.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => cb.checked = false);
        let gridEl = document.querySelector('.k-grid');
        let gridId = gridEl ? gridEl.id : "";
        if (typeof KretaGridHelper !== 'undefined' && KretaGridHelper.refreshGridSearchPanel && gridId) {
            KretaGridHelper.refreshGridSearchPanel(gridId, "searchForm");
        } else {
            let btn = document.getElementById('searchPanelBtn');
            if (btn) btn.click();
        }
    }''')
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(3)

    js_szamonkeres_extractor = """
    () => {
        let lista = [];
        let gridEl = document.querySelector('.k-grid');
        if (!gridEl) return lista;
        let grid = $(gridEl).data("kendoGrid");
        if (grid) {
            let dataItems = grid.dataSource.data();
            dataItems.forEach(item => {
                let formatDate = (dVal) => {
                    if (!dVal) return "";
                    let d = new Date(dVal);
                    if (isNaN(d.getTime())) return String(dVal);
                    let y = d.getFullYear();
                    let m = String(d.getMonth() + 1).padStart(2, '0');
                    let day = String(d.getDate()).padStart(2, '0');
                    return `${y}. ${m}. ${day}.`;
                };

                lista.push({
                    esemeny_tipus: 'Bejelentett számonkérés',
                    tantargy: item.TantargyNev || item.Tantargy || "",
                    ertekelo: item.TanarNeve || item.Tanar || "",
                    mod: item.SzamonkeresModja || item.Mod || "",
                    tema: item.SzamonkeresTemaja || item.Tema || "",
                    hatarido: formatDate(item.Datum || item.SzamonkeresDatuma),
                    bej_datum: formatDate(item.BejelenteseDatuma || item.BejelentesDatuma)
                });
            });
        }
        return lista;
    }
    """
    szamonkeresek = await page.evaluate(js_szamonkeres_extractor)
    print(f"Siker! Beolvasva {len(szamonkeresek)} db bejelentett számonkérés.")

    # --- 6. MENTÉS AZ ADATBÁZISBA ---
    clear_student_data(diak_nev)
    osszes_esemeny = jegyek + feljegyzesek + hazifeladatok + szamonkeresek

    if len(osszes_esemeny) > 0:
        save_esemenyek_to_db(diak_nev, osszes_esemeny)
        print(f"\n{diak_nev} adataiból {len(osszes_esemeny)} db esemény sikeresen elmentve!")
    else:
        print(f"Figyelem: {diak_nev} fiókjából nem sikerült adatot kinyerni.")

    # --- 7. KIJELENTKEZÉS A FIÓKBÓL ---
    print(f"Kijelentkezés ({diak_nev})...")
    try:
        await page.goto(f"https://{institute_code}.e-kreta.hu/Home/LogOut")
        await page.wait_for_load_state("networkidle")
        print("Sikeres kijelentkezés!")
    except Exception as e:
        print(f"Kijelentkezési figyelmeztetés: {e}")

async def main():
    init_db()
    
    active_students = [s for s in STUDENTS if s.get("active", True)]
    print(f"Készülődés {len(active_students)} diák adatainak lekérésére...")
    print(f"Böngésző üzemmód: {'Háttérben (Headless)' if HEADLESS_MODE else 'Látható (Headed)'}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS_MODE)
        context = await browser.new_context()
        page = await context.new_page()

        for student in active_students:
            try:
                await process_student(page, student)
                await asyncio.sleep(2)
            except Exception as err:
                print(f"\nHIBA történt {student.get('diak_nev')} feldolgozása során: {err}")

        print("\n" + "=" * 70)
        print("MINDEN DIÁK FELDOLGOZÁSA BEFEJEZŐDÖTT!")
        print("=" * 70)
        
        await asyncio.sleep(2)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())