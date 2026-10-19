import sqlite3

def list_database():
    conn = sqlite3.connect("kreta_adatok.db")
    cursor = conn.cursor()

    print("=" * 115)
    print("  KRÉTA ADATBÁZIS TARTALMA — REINER BALÁZS")
    print("=" * 115)

    # 1. ÉRTÉKELÉSEK / JEGYEK LEKÉRDEZÉSE
    cursor.execute("""
        SELECT bej_datum, tantargy, ertek, mod, ertekelo, tema 
        FROM esemenyek 
        WHERE esemeny_tipus = 'Értékelés'
        ORDER BY bej_datum DESC
    """)
    jegyek = cursor.fetchall()

    if jegyek:
        print(f"\n ÉRTÉKELÉSEK / JEGYEK ({len(jegyek)} db):\n")
        print(f"{'DÁTUM':<12} | {'TANTÁRGY':<22} | {'ÉRTÉKELÉS':<12} | {'MÓD / TÉMA (TANÁR)'}")
        print("-" * 115)
        
        for datum, tantargy, ertek, mod, tanar, tema in jegyek:
            details = f"{mod}"
            if tema:
                details += f" [{tema}]"
            if tanar:
                details += f" - {tanar}"
            
            print(f"{datum:<12} | {tantargy:<22} | {ertek:<12} | {details}")

    # 2. FELJEGYZÉSEK LEKÉRDEZÉSE
    cursor.execute("""
        SELECT bej_datum, tipus, ertekelo, cim, tartalom 
        FROM esemenyek 
        WHERE esemeny_tipus = 'Feljegyzés'
        ORDER BY bej_datum DESC
    """)
    feljegyzesek = cursor.fetchall()

    if feljegyzesek:
        print("\n" + "=" * 115)
        print(f" FELJEGYZÉSEK / DICSÉRETEK / HIÁNYOK ({len(feljegyzesek)} db):\n")
        print(f"{'DÁTUM':<12} | {'TÍPUS':<22} | {'TANÁR':<20} | {'CÍM ÉS TARTALOM'}")
        print("-" * 115)
        
        for datum, tipus, tanar, cim, tartalom in feljegyzesek:
            text = f"{cim}: {tartalom}" if cim else tartalom
            print(f"{datum:<12} | {tipus:<22} | {tanar:<20} | {text}")

    # 3. TANTÁRGYI ÁTLAGOK SZÁMÍTÁSA
    print("\n" + "=" * 115)
    print("  TANTÁRGYI ÁTLAGOK")
    print("=" * 115)
    
    cursor.execute("""
        SELECT tantargy, AVG(szam_ertek), COUNT(szam_ertek) 
        FROM esemenyek 
        WHERE esemeny_tipus = 'Értékelés' AND szam_ertek > 0
        GROUP BY tantargy
        ORDER BY tantargy ASC
    """)
    atlagok = cursor.fetchall()
    
    print(f"\n{'TANTÁRGY':<25} | {'ÁTLAG':<8} | {'JEGYEK SZÁMA'}")
    print("-" * 55)
    for t_nev, atlag, darab in atlagok:
        print(f"{t_nev:<25} | {atlag:<8.2f} | {darab} db")

    cursor.execute("SELECT AVG(szam_ertek) FROM esemenyek WHERE esemeny_tipus = 'Értékelés' AND szam_ertek > 0")
    osszesitett = cursor.fetchone()[0]
    if osszesitett:
        print("-" * 55)
        print(f"{'ÖSSZESÍTETT ÁTLAG':<25} | {osszesitett:<8.2f} | {len(jegyek)} db jegyből")

    conn.close()

if __name__ == "__main__":
    list_database()