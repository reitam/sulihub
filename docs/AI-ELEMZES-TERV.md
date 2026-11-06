# Üzenetek AI elemzése — terv (Kaneo #61)

**Cél:** egy gombnyomással az üzenet szövegéből (és a csatolmány szövegéből)
kinyerni az **eseményeket és határidőket**, majd azokból egy kattintással
naptárbejegyzést készíteni (Google Naptár-link / `.ics`, mint a #47-nél).

**Státusz:** **API-kész, a felületre nem került ki (2026-11-04)** — a felhasználó kérésére
az „AI elemzés” gomb és az eredménylista kikerült az üzenet modálból; a háttér
(`kreta_ai.py`, `/api/uzenet/<id>/ai`, `/api/naptar/ai/ics`) megmaradt. A részfeladatok
(#65–#69) elvégezve; a teljesen közvetlen Google OAuth írás külön jegy (#70).

---

## 1. Szolgáltató (ingyenes)

| Opció | Előny | Hátrány | Ajánlás |
|---|---|---|---|
| **Helyi Ollama** (HPReiTam, LAN) | ingyenes, nincs adatküldés, offline | modell telepítés + RAM/GPU kell | **első választás** |
| Google Gemini ingyenes tier | jó magyar nyelv | felhőbe megy a gyerekadat, kulcs kell, kvóta | csak külön engedéllyel |
| Hugging Face Inference | ingyenes kvóta | felhő, limit, változó minőség | tartalék |

A kliens **OpenAI-kompatibilis** `POST {URL}/v1/chat/completions` végpontot használ,
így az Ollama (`http://192.168.1.39:11434`) és a felhős szolgáltatók is ugyanazzal a
kóddal mennek. A válasz **csak JSON** legyen; a kliens a ```json fence-t is kezeli.

## 2. Konfiguráció (config.json)

```json
"AI": {
  "ENABLED": true,
  "URL": "http://192.168.1.39:11434",
  "MODEL": "llama3.1:8b",
  "API_KEY": "",
  "TIMEOUT_SECONDS": 60,
  "MAX_INPUT_CHARS": 6000,
  "ALLOW_CLOUD": false
}
```

- `ALLOW_CLOUD=false` esetén csak magánhálózati címre (`127.0.0.1`, `192.168.*`,
  `10.*`, `172.16–31.*`) enged kimenő hívást — így a gyerekadat nem megy ki.
- Kulcs csak a data köteten lévő `config.json`-ban / env-ben, a repóba nem kerül.

## 3. Adatfolyam

1. `POST /api/uzenet/<id>/ai` (a felület „AI elemzés” gombja).
2. A backend betölti az üzenetet (`targy`, `felado`, `idopont`, `szoveg`) és a
   csatolmány szövegét (ha van; PDF → `pypdf`, txt → nyers; egyéb → csak fájlnév).
3. A szöveget a `MAX_INPUT_CHARS`-ra vágja, majd a promptot elküldi.
4. A válaszból **validált** eseménylista lesz:

```json
[
  {
    "cim": "Szülői értekezlet",
    "datum": "2026-11-12",
    "ido": "17:30",
    "helyszin": "Aula",
    "leiras": "Rövid kivonat",
    "bizalom": 0.92
  }
]
```

5. A felület listázza; minden elemnél **Google naptárba** és **ICS** gomb. A linkek
   a meglévő `kreta_naptar.py` segédfüggvényeivel készülnek (a #47 mintájára).

## 4. Hiba- és adatvédelem

- Nincs konfigurálva / `ENABLED=false` → 503, magyar hibaüzenet a felületen.
- Timeout / nem JSON / üres lista → 502, a nyers válasz **nem** kerül a UI-ra.
- Legfeljebb 20 esemény; dátum `YYYY-MM-DD`, idő `HH:MM` vagy null; a múltbeli
  dátumot megtartjuk, de a UI jelzi.
- Naplózás: csak hossz és eseményszám, **a gyerek szövege nem** kerül a sync.log-ba.
- A kimenet mindig emberi jóváhagyással kerül a naptárba (nem automatikus írás).

## 5. Felület

- Az üzenet modáljában új gomb: **„AI elemzés”** (spinner a futás alatt).
- Eredmény: kártyák (cím, dátum/idő, helyszín, bizalom), egyenként naptárgombokkal,
  valamint „Mindet a naptárba” (egymás után megnyitott Google-linkek — a böngésző
  blokkolhatja, ezért inkább egyenként).
- Ha nincs találat: „Nem találtam határidőt/eseményt.”

## 6. Tesztek

- `tests/test_ai_uzenet.py` (fake OpenAI-kompatibilis HTTP-szerverrel):
  - helyes JSON → validált lista,
  - ```json fence → ugyanaz,
  - hiányzó config → 503,
  - timeout → 502,
  - érvénytelen dátum/idő kiszűrése,
  - a kimenetből készült Google-link/ICS.
- A valódi modell **nem** kell a CI-hez (a teszt fake szervert használ).

## 7. Részfeladatok (Kaneo #61 alatt)

1. Config + OpenAI-kompatibilis kliens (Ollama alapértelmezés, `ALLOW_CLOUD` őr).
2. Prompt + szigorú JSON-séma + validáció + hibakezelés.
3. UI: „AI elemzés” gomb, eredménylista, naptárgombok.
4. Csatolmány-szöveg kinyerése (PDF/txt, méretkorlát).
5. Tesztek + dokumentáció + üzemeltetési útmutató (modell letöltése, timeout).

## 8. Nyitott kérdések

- Melyik szolgáltató/modell fusson? (helyi Ollama ajánlott; melyik modell fér el a
  HPReiTam memóriájában?)
- Megengedett-e egyáltalán felhős AI (gyerekadat), vagy maradjon szigorúan LAN-only?
- A csatolmányok közül csak a szöveges/PDF mennyen, vagy a képek OCR-e is kell?
