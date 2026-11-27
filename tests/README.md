# Tesztek

A tesztek izolált temp könyvtárban futnak, valódi KRÉTA-hívást nem végeznek.

## Futtatás

```bash
python tests/run_all.py            # mind
python tests/run_all.py --fast     # böngésző nélkül
python tests/run_all.py --browser  # böngészős UI-tesztek (Playwright)
```

A CI a gyors, a böngészős és a `pip-audit` jobot futtatja; a böngészős job
hibája esetén a képernyőképek artifactként feltöltődnek.

## Területek

A `tests/` könyvtárban **55 csomag** van. A fő területek:

- **Szinkron és adatkezelés:** ütemező, részleges hiba/ntfy, napló, digest,
  adatvédelem, DB-séma bootstrap/őr, migráció, tanévkezelés, first seen.
- **KRÉTA API:** API-kliens (fake HTTP), API-szinkron, csatolmányok, token-tár,
  tantárgy-szűrés, hiányzások/igazolások.
- **Felület:** dashboard, mobil elrendezés, esemény-részletek, oszlopszélesség,
  kereső, kalkulátor, statisztika, zsebpénz, nyomtatás.
- **Export:** PDF órarend/riportkártya, Excel, CSV, ICS.
- **Üzemeltetés:** deploy-konzisztencia, mentés/restore, élő füstteszt,
  adatminőség, teljesítmény, route-contract.

A fájlok neve és docstringje a pontos lefedettséget írja le.

## Függőségek

A tesztek a futó alkalmazás függőségein (flask, reportlab) túl opcionálisan
használják a `pypdf`-et a PDF-szöveg ellenőrzéséhez. A böngészős UI-tesztekhez
a `requirements-playwright.txt` és a Chromium kell:

```bash
pip install -r requirements-playwright.txt
playwright install chromium
```

A gyors tesztek az alap `requirements.txt`-vel, Playwright nélkül is futnak.

## API-pillanatkép

A `python tools/api_snapshot.py` a 17 olvasó végpont válaszát menti és
különbözteti (az adatbázis másolatán, POST nélkül). A baseline nem verziózott
(valódi adatot tartalmazhat, a `.gitignore` kizárja).
