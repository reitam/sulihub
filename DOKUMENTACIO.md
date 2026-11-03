# KRÉTA Adatbázis Áttekintő — Rendszerdokumentáció

| | |
|---|---|
| **Dokumentum verziója** | 1.1 |
| **A rendszer verziója** | v1.6.5 (élesítésre vár; élesben v1.6.4) |
| **Utolsó frissítés** | 2026-11-02 |
| **Készítette** | Reiner Tamás (fejlesztés) — OpenCode asszisztens közreműködésével |
| **Karbantartási szabály** | **Minden újabb fejlesztés után frissíteni kell** (lásd a 15. pontot) |

---

## 1. Vezetői összefoglaló

A **KRÉTA Adatbázis Áttekintő** egy saját üzemeltetésű, belső hálózaton futó webalkalmazás,
amely **három gyermek KRÉTA-fiókjából** automatikusan összegyűjti az iskolai információkat,
egy helyen, áttekinthető formában megjeleníti, és **automatikusan értesít** a fontos
változásokról.

**Mit old meg?**

| Probléma a KRÉTA saját felületén | Megoldás ebben az alkalmazásban |
|---|---|
| Gyermekenként külön bejelentkezés, külön felület | Egy felület, mindhárom gyermek adatai együtt vagy szűrve |
| Nehéz átlátni, „mi történt ma / mi esedékes" | Napi/heti nézetek, határidő-naptár, kiemelések |
| Nincs összesített kép a jegyekről, hiányokról | Statisztika, havi bontás, zsebpénz-elszámolás |
| Nincs értesítés, csak ha belépek | Push értesítés szinkroneredményről és új eseményekről |
| Órarend nyomtatása körülményes | Egy kattintásos, nyomtatható A4 PDF |

**Kinek készült?** Egy szülőnek, aki napi szinten követi három gyermek iskolai életét —
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
| **Értékelések** | Tantárgy, érdemjegy, dátum, tanár, típus, témakör, **súlyszázalék** („100%-os súllyal számít az átlagba”). A súly a **mobil API** `SulySzazalekErteke` mezőjéből jön, Playwright-módban pedig a webes grid **hónap-cellája tooltipjének** `data-suly` attribútumából („Súly: 100%") — mindkettő ugyanabba az oszlopba kerül. A felület a jegy mellett kis `%`-jelvényként mutatja, tooltippel. Az API-first szinkronban a **Magatartás** és a **Szorgalom** két külön sor (0 számértékkel), így az átlagot nem befolyásolják |
| **Feljegyzések** | Dicséretek, megrovások, hiányok, egyéb bejegyzések |
| **Házi feladatok** | Tantárgy, tanár, leírás, rögzítés, határidő |
| **Bejelentett számonkérések** | Tantárgy, mód, téma, bejelentés és a számonkérés napja |
| **Hiányzások / késések** | Dátum, **aznap hányadik óra** (1 sor = 1 tanóra), tantárgy, téma, mulasztás típusa (késésnél percek), igazolt/igazolatlan, igazolás típusa, rögzítés dátuma. A „tanórai célú” jelző is tárolva van, de a felületen nem jelenik meg |
| **Igazolások** | Érvényesség kezdete–vége, igazolás típusa, megjegyzés |
| **Heti órarend** | Aktuális és következő hét: tanár, terem, időpont, esetleg egész napos esemény; **fogadóórák** is |
| **e-Ügyintézés üzenetek** | Beérkezett üzenetek (csak az újak) a teljes szöveggel, **a csatolmányokkal együtt** — a fájl API-ból töltődik le (`dokumentumok/uzenetek/{id}` → `files.e-kreta.hu` nonce URL), böngésző nélkül |

### 2.3. Felület (fő nézetek)

| Fül | Mire való |
|---|---|
| **Áttekintés** | Nyitó dashboard: **6 kattintható csempe** — **következő házi feladatok** (10 nap), **következő számonkérések** (10 nap), **új jegyek** (7 nap), **új üzenetek** (7 nap), **igazolatlan hiányzás** (óra), **kifizetetlen zsebpénz** —, valamint **gyermekenkénti kártyák** (teljes időszaki súlyozott tanulmányi átlag + kifizetetlen egyenleg). **Kompakt, 3×2 elrendezés**, egységes csempesablon (ikon + cím, majd szám + rövid leírás). **Színlogika:** 0 értéknél semleges (szürke) vagy „rendben” (zöld), csak > 0 esetén élénk szín (kék/narancs/piros). Gyermek-chipek; a csempére kattintva a megfelelő (szűrt) nézet nyílik |
| **Iskolai események** | Szűrhető, kereshető táblázat: jegyek (a jegy mellett a **súlyszázalék** jelvénye), feljegyzések, házik, számonkérések. Szűrők: gyermek (chip is), típus, tantárgy, időszak, dátumtartomány, gyorsszűrők; „Vissza az áttekintésre" gomb. Soronként **saját megjegyzés** fűzhető (Kaneo #46) |
| **Hiányzások** | Hiányzások és késések havi bontásban: **5 összesítő kártya** (összes hiányzás óra, igazolt óra, igazolatlan óra, késés db/perc, igazolás db) + részletes tábla és igazolás-lista. Alapból a **teljes előzmény** látszik, a havi bontás hónapválasztóval / „Aktuális hónap" gombbal |
| **Heti órarend** | Idősávos heti nézet, gyermekszínekkel; **A4 PDF export** |
| **Feladatok naptár nézet** | Házik és számonkérések határidő szerint, színkódolva |
| **Beérkezett üzenetek** | Üzenetek olvasása, csatolmányok letöltése; az üzenethez is fűzhető **saját megjegyzés** (Kaneo #46) |
| **Statisztika & Zsebpénz** | Havi jegyeloszlás, átlag, dicséret/hiány mutatók, elszámolás |
| **Rendszernapló** | A szinkronizációk naplója, hibák, előzmények |

**Fejléc:** ütemező állapota (BE/KI), időablak, következő futás, utolsó futás eredménye
(kézi/ütemezett, sikeres/részleges hiba/hiba), valamint a **telepített verzió**.

**Fülek:** semleges (sötétszürke) ikonok és feliratok; **csak az aktív fület** emeli ki a
felület (kék szöveg/ikon + alsó kék vonal). A korábbi színes fül-ikonok (piros, sárga,
zöld stb.) megszűntek — kevesebb vizuális zaj.

**Oszlopok szélessége:** az *Iskolai események*, *Hiányzások*, *Igazolások* és *Beérkezett
üzenetek* táblázat fejlécében a jobb szélen lévő fogantyúval (egérrel) állítható. Az
átméretezés **nem változtatja meg a sorrendet** (a fogantyú kattintása nem rendez).

### 2.4. Mobil használat (telefon)

A felület **mobilra is optimalizált** (Redmi 12/13/14 méret, ~393 CSS px):

- a fejléc egymás alá rendeződik, a frissítés gomb teljes szélességű,
- a statisztika-kártyák 2 oszlopban, tömören jelennek meg,
- a fülek **2 sorba tördelődnek**, minden fül látszik (nem fut ki a képernyőből),
  a szűrőpanel mobilon alapból csukva van, hogy a fülek rögtön elérhetők legyenek,
- a szűrők teljes szélességűek, a dátumtartomány egymás alatt,
- a **táblázatok összecsukhatók**: csak a legfontosabb 2–3 oszlop látszik,
  a többi a sor kinyitásával (▸) érhető el,
- a **diák oszlopban színes monogram-avatar** látszik (pl. `RB`, `RBE`) a teljes név
  helyett — így a **bejegyzés dátuma** is kifér; az avatar színe a gyermekhez kötött,
  a teljes név az avatar fölé húzva (tooltip) jelenik meg,
- az **órarend mobilon napi naptárnézet** (időrács), ‹ › gombokkal és „Ma"-val
  lehet napot léptetni; a „Hét" váltóval a heti nézet érhető el,
- a **feladatnaptár mobilon listanézetben** indul (időrendben, napokra bontva),
- a **hiányzások fül** összesítő kártyái (igazolt/igazolatlan óra, késés) 2 oszlopban,
  a hiányzás- és igazolás-táblázat pedig a többihez hasonlóan összecsukható,
- a modálok szinte teljes képernyőn nyílnak, a napló pedig tördelve olvasható,
- a koppintható elemek (gombok, mezők) legalább ~40 px magasak.

A mobil elrendezést automatizált teszt ellenőrzi (nincs vízszintes túlcsordulás,
a fő elemek a képernyőn belül vannak, a táblázat összecsukott).

### 2.5. Értesítések (push)

| Esemény | Értesítés |
|---|---|
| Sikeres szinkron | „KRÉTA szinkron: sikeres" + **diákonként az új események** (pl. *„2 jegy, 1 házi"*, *„2 üzenet"*, *„1 hiányzás (2 igazolatlan óra)"*) |
| Részleges hiba | „részleges hiba", darabszámmal (nevek nélkül) |
| Hiba | „HIBA", magas prioritás |
| Elavult adat (12 óránál régebbi) | „elavult adatok", max. 6 óránként egyszer |
| Leállított futás | nincs értesítés (szándékosan) |

Az értesítések az **ntfy** szolgáltatáson keresztül mennek a telefonra. Diáknevek alapból
**nem** kerülnek ki; a részletes bontás a felületen és a naplóban látható.

**Beállítás — két helyen, az env az erősebb:**

```jsonc
// config.json (a data köteten; lokálisan is ez a kényelmes)
"NTFY": {
  "_comment": "CSA K akkor él, ha a .env-ben nincs NTFY_TOPIC (az env erősebb)",
  "TOPIC": "kreta-3f9c1a7b5e2d4c60",   // üresen nincs értesítés
  "URL": "https://ntfy.sh",             // saját ntfy szerver is lehet
  "NOTIFY_SUCCESS": true,               // sikeres futásról is küldjön
  "INCLUDE_NAMES": false                // diáknevek a push-ban (alapból nem)
}
```

> A JSON nem enged megjegyzést, ezért a `_comment` kulcs a „komment” (az app nem
> használja). Ha a `.env`-ben is van `NTFY_TOPIC`, induláskor a konzol kiírja, hogy a
> config.json topicját nem használja.

A szerveren a `NTFY_TOPIC` (stb.) a `/mnt/work/Kreta/.env`-ben él (a compose `env_file`-ja);
ha ott be van állítva, az **felülírja** a config.json értékét. A topic **neve maga a cím**:
az ntfy appban (vagy a `ntfy.sh` oldalon) ugyanerre a névre kell feliratkozni — és mivel erre
a névre bárki küldhet/olvashat, **hosszú, véletlen nevet** használj (nincs regisztráció).
A téma a `config.json`-ban a deploy után is szerkeszthető (a deploy nem írja felül).

Beállítás-ellenőrzés (a futó appnál): `POST /api/ntfy/test` — küld egy teszt-push-t, és
megmondja, van-e egyáltalán topic, milyen URL-lel; topic nélkül 400-at ad a hiányzó kulccsal.

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
- A **tanulmányi átlag súlyozott**: a jegyek a KRÉTA súlyszázaléka szerint számítanak
  (Σ jegy×súly / Σ súly); a **0%-os súlyú** jegy nem számít bele. Ha egyetlen jegynek sincs
  súlyadata (régi adat), akkor a hagyományos egyszerű átlag jelenik meg. A felület a
  „Tanulmányi átlag" mellett *(súlyozott)* jelzést mutat, tooltippel az egyszerű átlaggal.
- **Tantárgyi átlagok havi bontással:** a Statisztika fülön **alapból zárt accordion**
  (`GET /api/atlagok?diak=&kezdo_datum=&zaro_datum=&tanev=`; a válaszban tantárgyanként
  hónapok, jegyek és **havi teljes átlagok** is vannak).
  * **Asztali nézet:** mátrix — sorok a tantárgyak, oszlopok a hónapok (csak a **hónap neve**,
    pl. „szept."; az évszám a tooltipben), cella a **havi tantárgyi átlag (db)**; az
    **„Összes" oszlop** a teljes időszak tantárgy szerinti átlaga, a **lábléc-sor**
    („Hónapok átlaga") a havi **teljes** átlag, a jobb alsó sarokban a teljes időszak átlaga.
    A kártya tetején **tanév + időszak** felirat (pl. „2026/2027. tanév · időszak: …").
  * **Mobil nézet:** **kapcsoló** a két bontás között (a „Teljes átlag" mindkét nézet tetején):
    - **Havi bontás:** hónap-accordionok (havi **teljes** átlag · jegy), kinyitva a tantárgyak
      **adott havi** átlaga (zárójelben a jegyszám);
    - **Tantárgy szerint:** tantárgyak a **teljes időszak** átlagával.
    Jegy-részletek nem jelennek meg (azok az *Események* fülön nézhetők meg); vízszintes
    görgetés sehol.
- **Tanév-választó a fejlécben (Kaneo #40, 5. fázis):** alapból az **aktuális tanév**
  (szept. 1. – aug. 31.) van kiválasztva, „Összes tanév" opcióval. A választó az
  **eseményeket, a hiányzásokat, az átlagokat, a statisztikát és a dashboardot** szűri
  (`?tanev=`); az **üzenetek és az órarend tudatosan tanév-független**. **„Összes tanév"
  módban az átlag nem értelmezhető** — a felület ilyenkor nem mutat átlagot, hanem
  tanévválasztásra kér. Üres tanévnél az adott fül rövid súgót jelenít meg.
- **Dátumválasztók a tanévhez igazítva (Kaneo #53):** ha egy tanév van kiválasztva, a
  bejegyzés-dátum, a zsebpénz-időszak és a hiányzás-hónap választó `min`/`max` korlátot
  kap a tanév határaira; a tanéven kívüli érték (begépelve is) törlődik. „Összes
  tanévnél" nincs korlát. A gyorsgombok (ma / ez a hónap / előző hónap) intervallumát
  a tanév határai közé vágja.
- **Tanév-állapot: automatikus zárás/nyitás a `TanevUid` alapján (Kaneo #43):** minden
  szinkronfutás után diákonként ellenőrizzük a `TanuloAdatlap.TanevUid`-t. Ha megváltozik,
  a nyitott tanévet **technikailag lezárjuk** (`tanevek.allapot = 'lezart'`, `lezarva_at`),
  és megnyitjuk az újat — **adatot visszamenőleg nem kérünk le** (a KRÉTA API a korábbi
  tanéveket nem adja vissza). A tanév neve a dátumból generált címke, mert a KRÉTA a diák
  scope-ban csak a nyers `TanevUid`-t adja (a `/Sajat/Tanevek` és `/Sajat/Tanulo` 403);
  a `TanevUid` a `tanulo_tanev_uid` táblában diákonként tárolva. A lezárás **nem tilt le
  semmit** (a régi tanévhez tartozó kifizetés/megjegyzés továbbra is rögzíthető), tisztán
  állapot/audit; a fejlécben állapotjelzés, a tanév-választóban „lezárt” jelölés látszik.
  * **Mérés (2026-11-03, 3 diák):** a KRÉTA mobil API a **korábbi tanévekre 0 sort ad**
    (jegy/hiányzás/igazolás, teljes tanévre kérve is), csak az **aktuális tanévet**
    szolgálja ki — a dátum-szűrő közben működik (kontroll ablakok). Ezért nincs
    visszamenőleges lekérés; a régi tanévek adata **pótolhatatlan**, ezért a napi backup
    és a „korábbi tanévet soha nem törlünk” szabály kritikus.
- **A kifizetetlen zsebpénz a dashboardon** a **kiválasztott tanév** egyenlege mínusz a
  `kifizetesek` táblában **kifizetettnek jelölt időszakok** összege (a maradék jelenik meg).
  A `POST /api/kifizetes` a kifizetés tanévét az időszak **kezdő dátumából** írja be, így a
  frissen kifizetett összeg azonnal levonódik. A `GET /api/dashboard` ezt diákonként és
  összesen is visszaadja, a diákonkénti tanulmányi átlaggal és az igazolatlan órák számával együtt.
- A kifizetés ténye rögzíthető („KIFIZETVE"), így az elszámolás nyomon követhető.
- A modul **gyermekenként** ki-/bekapcsolható. Jelenleg: Elek és Anna aktív,
  **Bori esetében kikapcsolva**. Kikapcsolt diáknál a **statisztika akkor is működik**
  (jegyeloszlás, átlag, viselkedési mutatók), csak a **pénz-kártya rejtve** van, és helyette
  egy figyelmeztető sáv jelzi, hogy a zsebpénz modul nincs engedélyezve.

---

## 3. Hogyan működik (architektúra)

### 3.1. Komponensek

```
┌─────────────────────────── Docker konténer (HPReiTam) ───────────────────────────┐
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

Az API-first szinkron bevezetésével a scraper mellett megjelent a **böngésző nélküli út**
is: `kreta_api.py` (mobil v3 / eAdmin végpontok + normalizálás a meglévő DB-sémákra) és
`kreta_sync.py` (forrásmód és adatkör-szintű fallback). A `SYNC_MODE` dönti el, melyik út
fut — lásd 3.2.1.

**API munkamenet (token-tár).** A KRÉTA minden **új** belépésről e-mailt küld („Új
bejelentkezésről értesítés") — a Playwright-os útnál ezt a perzisztens böngészőprofil
kerülte el. Ezért az API-kliens a tokent a data köteten tárolja
(`api_tokens.json`, alapból `<data>/api_tokens.json`, felülírható a
`KRETA_API_TOKEN_FILE` változóval): a következő futás a **tárolt hozzáférési tokent**
használja, lejárat után pedig **refresh tokennel** frissít — teljes belépés csak akkor
történik, ha nincs/érvénytelen a token (pl. jelszócsere, visszavont session). A naplóban
látszik, melyik út futott: `[API] munkamenet a tárolt tokenből` / `… frissítve refresh
tokennel` / `új belépés történt`. A fájl **titkot tartalmaz** (access + refresh token),
ezért a `.gitignore` kizárja, és a data köteten, védett könyvtárban él; törlésével
kikényszeríthető az új belépés.

### 3.2. Adatfolyam egy futásnál

1. Az ütemező (vagy a gomb) elindítja a szinkront → a DB-ben létrejön egy `sync_runs` sor
   (`running` állapot).
2. A scraper bejelentkezik gyermekenként, kiolvassa az adatokat (jegyek, feljegyzések,
   házik, számonkérések, **hiányzások/késések, igazolások**, órarend, üzenetek), és menti a DB-be.
3. A scraper a végén gép-olvasható összegzést ír a kimenetére (hány diák, mi hibázott,
   mi az új esemény).
4. Az alkalmazás lezárja a `sync_runs` sort (státusz, darabszámok, új események, futásidő),
   naplózza, és **push értesítést** küld.
5. A felület a következő frissítéskor már az új adatokat mutatja.

#### 3.2.1. Forrásmódok (`SYNC_MODE`)

| Mód | Mit jelent |
|---|---|
| `playwright` | **Alapértelmezés.** Csak a DOM-scraper fut (a korábbi viselkedés). |
| `api` | Csak a mobil API; böngésző nem indul. Egy adatkör hibája részleges hiba, a többi adatkör és diák megy tovább. |
| `api_first` | Adatkörönként először az API; hiba/timeout/parse hiba esetén **automatikus Playwright fallback** arra az adatkörre. |

Az adatkörök: órarend, jegyek, feljegyzések, házi feladatok, bejelentett számonkérések,
hiányzások/késések, igazolások, üzenetek. A sikeres API-adatkörök `skip` halmazba kerülnek,
így a Playwright **nem írja felül** őket (nincs dupla írás és dupla „új esemény” értesítés).
A forrás és a fallback oka a `sync.log`-ba, a gép-olvasható összegzés `sources` mezőjébe és
a `sync_runs.sources` oszlopba kerül; a `/api/sync/status` is átadja.

**Árnyék/ellenőrző mód (`SYNC_SHADOW`):** `api_first` mellett a Playwright is lefut — de egy
**másolt** adatbázison, és csak összehasonlítunk (táblánként kulcs + mezők, a POC logikája
szerint). A valódi DB-hez csak az API ír, így nincs dupla írás/értesítés; az eltérések a
`sync.log`-ba kerülnek (`[ÁRNYÉK]` sorok). Élesítés előtt 1–2 hétig érdemes bekapcsolva
hagyni, utána kikapcsolható — a Playwright csak fallback marad.

> A D3–D7-tel a **hiányzások/késések, az igazolások, a jegyek, a házi feladatok, a
> bejelentett számonkérések, a feljegyzések, az órarend** (fogadóórákkal) és az
> **üzenetek** már API-ból jönnek (táboros hiányzásnál a korábbi téma megmarad, a házi
> „kész” jelölése megmarad). **Az üzenet-csatolmányok is API-ból töltődnek** (2026-10-31
> óta): a kliens a `dokumentumok/uzenetek/{csatolmanyAzonosito}` végpontról kapott 302-es
> átirányítást követi a `files.e-kreta.hu/fajlok/?nonce=…` címre, és a bájtokat a
> `csatolmanyok/<diák>/` alá menti. Így **tiszta `api` módban sincs böngésző**; ha egy
> letöltés mégis elhal, `api_first` módban a teljes üzenet-adatkör Playwright-fallbackre
> megy (nincs félkész mentés), `api` módban a fájl kimarad (figyelmeztetés a naplóban).

> **UTC-határ az órarendnél:** az `OrarendElemek` a `KezdetIdopont` **UTC** dátuma
> szerint szűr, a helyi nap 00:00-kor kezdődő egész napos események (szünetek,
> munkaszüneti napok) viszont előző napi `23:00Z`-ként jönnek. Ezért a kliens az
> órarend-ablakot **egy nappal korábbra** is kéri — enélkül az ablak első napjának
> eseményei (pl. az őszi szünet hétfője) kimaradnának a heti nézetből.

> **Jövőbeli határidők:** a KRÉTA az API-ablakon (`datumTol`–`datumIg`) belül adja a
> sorokat, a **házi feladat** és a **bejelentett számonkérés** viszont jövőbeli
> határidőt hordoz. Ezért ennél a két adatkörnél az ablak **90 nappal előre** is nyúlik
> (`kreta_api_sync.FUTURE_LOOKAHEAD_DAYS`) — enélkül a következő hetek dolgozatai és
> házijai nem jönnének le API-ból, csak a Playwright-fallback hozná őket (ami
> `api_first` módban nem fut le, ha az API „sikeres"). A többi adatkör ablaka a mai napig
> tart.

#### 3.2.2. Adatvédelem a teljes cserés mentésnél

A jegyek/feljegyzések és az órarend mentése **teljes cserével** dolgozik (a KRÉTA-ból
eltűnt sor törlődik). Ha a forrás hibásan **üres** (de 200-as) választ ad, a csere
adatvesztést okozna, ezért:

| Adatkör | Védőkorlát |
|---|---|
| Jegyek / feljegyzések | ha az új sorok száma a meglévők **50%-a alá** esik (`KRETA_SYNC_MIN_RATIO`), a törlés kimarad, `[FIGYELEM]` a naplóban; **üres lista soha nem töröl** |
| Órarend | csak **teljes ürülésnél** véd (üres lista + meglévő sorok); a részleges csökkenés megengedett (szünet, év vége) |
| **Igazolások** | **upsert** `kreta_id` kulcson + 50%-os őr: üres vagy részleges lista esetén nem töröl; üres lista `KRETA_SYNC_MIN_RATIO=0` mellett is védett |
| Házi / számonkérés / üzenetek / hiányzások | eleve inkrementális, nincs teljes csere (a hiányzásoknál csak az „eltűnt" sorok törlődnek) |

**Tanév-scope (Kaneo #40):** a teljes cserék törlése csak a **most letöltött tanévekre** és a
**lekérési ablakon belülre** hat - a korábbi tanévek soraihoz a szinkron nem nyúl, akkor sem,
ha az API nem adja vissza őket. Az arányos őr is tanévenként számol. Az API-ablak a **tanév
első napjától** indul (nem a DB legkorábbi sorától), így a kérészáma nem nő a tanévek számával.
A letöltött tanéveken kívülre eső sor nem íródik be (duplikáció ellen), de nem csendben:
`skipped` a visszatérési értékben + `[FIGYELEM]` a naplóban.

A védett mentés után az API-szolgáltató **hibát dob**, így `api_first` módban a Playwright
fallback lefut arra az adatkörre; `api` módban a futás részleges hiba lesz, de a meglévő
adatok megmaradnak. A Playwright-út maga nem dob hibát: a régi adat marad, a napló jelez.
Ha egy valódi, nagyarányú csökkenés lenne hiteles (pl. év eleji törlés a KRÉTA-ban), a
küszöb átmenetileg csökkenthető (`KRETA_SYNC_MIN_RATIO=0.2`), vagy `0`-ra állítva kikapcsolható.

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
| `esemenyek` | Jegyek, feljegyzések, házik, számonkérések (közös séma) | `esemeny_tipus` különböztet; a `kesz` jelző a házi „elkészült" állapota; a `suly_szazalek` a jegy súlyszázaléka (0 = nincs adat / nem API-ból jött) |
| `orarend` | Heti órarend sorai (diák, nap, időpont, tantárgy, tanár, terem) | Az aktuális és a következő hét |
| `uzenetek` | e-Ügyintézés üzenetek + csatolmány hivatkozás | Csak az új üzenetek kerülnek be |
| `hianyzasok` | Hiányzások és késések (dátum, órasorszám, tantárgy, téma, típus, igazolt, igazolás típusa) | ISO dátum; a rekordot a **dátum + órasorszám** azonosítja; késést a `perc` és/vagy a típus neve jelöli |
| `igazolasok` | Igazolások érvényességi intervalluma + típus + megjegyzés | A hónaphoz a metsző igazolások tartoznak |
| `kifizetesek` | Zsebpénz-elszámolások havi tételei | „KIFIZETVE" állapot, összeg |
| `sync_runs` | **Minden szinkronizáció** egy sora (trigger, időpontok, státusz, darabszámok, új események, futásidő) | Ez adja a „legutóbbi futás" állapotot is |
| `app_meta` | Kulcs–érték technikai állapotok | pl. utolsó elavultsági riasztás ideje |
| `tanevek` | A tanévek állapota: `allapot` (nyitott/lezárt), `lezarva_at`, `forras` (kreta_uid/szamitott) | A zárás/nyitás a `TanevUid` változásához kötött; adatlekérés nélkül |
| `tanulo_tanev_uid` | Diákonként az utoljára látott KRÉTA `TanevUid` + a hozzá tartozó tanév | A váltás-detektálás alapja (a KRÉTA csak ezt adja, nevet nem) |
| `kommentek` | **Saját megjegyzések** eseményhez / üzenethez (szöveg, szerző, időpont) | Nem a KRÉTA-ból jön; a célzás **stabil tartalom-kulccsal** történik (az események id-je a szinkronnál változik) — Kaneo #46 |

**Adatmennyiség (2026-10-29):** 165 esemény, 124 órarend-sor, 56 üzenet, 2 elszámolás.

**Tanév-dimenzió (Kaneo #40, 1. fázis):** a `esemenyek`, `uzenetek`, `hianyzasok`,
`igazolasok`, `kifizetesek` táblán `tanev` (`"2026/2027"`) és `tanev_forras`
(`migracio`/`szamitott`/`kreta`) oszlop, a `sync_runs`-on `tanev` (**a futás tanéve**);
az **`orarend` szándékosan nem** kap tanévet (heti órarend). A tanév a rekord **saját
dátumából** számított (szept. 1. – aug. 31.; a házi/számonkérésnél a **határidő** dönt),
mert a KRÉTA csak a `TanuloAdatlap.TanevUid` belső azonosítót adja. A migráció a meglévő
sorokat **csak UPDATE**-tel tölti ki (ID-stabil, újraindítható); a `tanev IS NULL` = még
nem migrált, a `''` = ismeretlen dátum. A teljes cserés mentések (jegyek, feljegyzések,
igazolások) törlése **csak a letöltött tanévekre és az ablakon belülre** hat, az igazolások
`kreta_id` kulcson **upsertelődnek** (stabil ID); az órarend tanév-független marad.
**Tanévváltás-figyelés (6. fázis):** minden szinkronfutás rögzíti a saját tanévét a
`sync_runs.tanev` mezőbe, és ha az előző futás tanévétől eltér, a naplóba egyszeri
„ÚJ TANÉV" sor kerül, valamint ntfy-értesítés megy ki. A `/api/sync/status` is jelzi a
futás tanévét.

**Fontos üzleti szabályok:**
- A jegyek és feljegyzések futásonként **újratöltődnek** (a KRÉTA az igazság forrása).
- A jegyek **súlyszázaléka** mindkét forrásból megvan: a mobil API
  `SulySzazalekErteke` mezőjéből, illetve a webes grid **hónap-cellájának
  tooltipjéből** (`data-suly`, pl. „Súly: 50%"). A részletes sorokban ez nincs,
  ezért **dátum + tanár + mód (+ téma)** kulccsal párosítjuk — így Playwright-fallbacknál
  sem veszik el. A DB-ben 0 = nincs adat (pl. Magatartás/Szorgalom sor vagy régi sor).
- A **hiányzások és igazolások** beolvasása teljes (a KRÉTA mindig a teljes listát adja),
  a DB-be viszont **inkrementálisan** írunk: a rekord azonosítója a **dátum + órasorszám**,
  így a meglévő sor frissül (stabil ID), az új beszúródik, a KRÉTA-ból eltűnt sor törlődik.
- **Egy hiányzás-sor = egy tanóra.** Az `ora_sorszam` a napon belüli órasorszám
  (a KRÉTA „Óra" oszlopa), **nem** óraszám — ezért a havi összesítő a sorokat számolja.
- A **tanórai célú** jelzőt (`tanorai_celu`) a scraper tárolja, de a felület és az
  összesítő nem jeleníti meg (a felhasználó szerint nincs információtartalma).
- A házik és számonkérések **nem törlődnek**, csak az újak kerülnek be — így megmarad a
  „elkészült" jelölés.
- Az üzenetek **inkrementálisan** töltődnek (csak amit még nem látott).
- A futásnapló megőrzi az előzményeket (napi ~6 sor, évi ~2000 — elhanyagolható méret).

---

## 5. Integrációk

| Integráció | Mire használjuk | Megjegyzés |
|---|---|---|
| **KRÉTA** (`<intézmény>.e-kreta.hu`) | Adatgyűjtés böngésző-automatizálással (Playwright) | 3 iskolai azonosító; a bejelentkezés sütiképre támaszkodik |
| **e-Ügyintézés** (`eugyintezes.e-kreta.hu`) | Üzenetek + csatolmányok | API-ból (mobil token), `X-Uzenet-Lokalizacio` illesztő; a Playwright-út csak fallback |
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
| `SYNC_MODE` | A szinkron forrása: `playwright` (alap) / `api` / `api_first` — lásd 3.2.1 |
| `SYNC_SHADOW` | `api_first` mellett a Playwright is lefut egy DB-másolaton, csak összehasonlítás (lásd 3.2.1) |
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
| `KRETA_API_TOKEN_FILE` | `<data>/api_tokens.json` | API munkamenet-tár (access/refresh token, **titok**) |
| `KRETA_HOST` / `KRETA_PORT` / `KRETA_DEBUG` | `127.0.0.1` / `5000` / ki | Web szerver |
| `KRETA_SERVER` | `flask` | `waitress` = produkciós szerver (a compose így indítja) |
| `KRETA_WAITRESS_THREADS` | `8` | Kiszolgáló szálak |
| `NTFY_TOPIC` | *(üres)* | ntfy topic **vagy teljes URL** — üresen nincs értesítés (config.json `NTFY.TOPIC` is lehet, az env erősebb) |
| `NTFY_URL` | `https://ntfy.sh` | ntfy szerver (config.json `NTFY.URL` is lehet) |
| `NTFY_NOTIFY_SUCCESS` | `1` | Sikeres futásról is küldjön-e (config.json `NTFY.NOTIFY_SUCCESS`) |
| `NTFY_INCLUDE_NAMES` | `0` | Diáknevek a részleges hiba push-ban (config.json `NTFY.INCLUDE_NAMES`) |
| `KRETA_LOG_MAX_BYTES` / `_BACKUP_COUNT` | `1000000` / `2` | Napló rotáció |
| `KRETA_SQLITE_WAL` | `0` | WAL mód (a FUSE kötet miatt alapból ki) |
| `KRETA_SYNC_MIN_RATIO` | `0.5` | Adatvédelmi küszöb a teljes cserés mentésnél (lásd 3.2.2); `0` = kikapcsolva |

---

## 7. Üzemeltetés

### 7.1. Környezetek

| Környezet | Hely | Cél |
|---|---|---|
| **Éles** | HPReiTam szerver, Docker, `http://HPReiTam:8085` | napi használat |
| **Fejlesztői** | Windows, `c:\ReiTam\AI\Gemini\Kreta`, `python app.py` | tesztelés, fejlesztés |

### 7.2. Szerver felépítés

| Elem | Útvonal |
|---|---|
| Kód | `/mnt/work/Kreta` |
| Adatkötet (DB, config, napló, csatolmányok, böngészőprofil) | `/mnt/Maxxel_HDD/app/Kreta/data` → konténerben `/app/data` |
| Mentések | `/mnt/Maxxel_HDD/ReiTam_BackUp/Kreta_backup` |
| Szerveroldali elérés Windowsról | `h:\app\Kreta\data` (Samba) |

### 7.3. Élesítés (deploy)

```powershell
cd c:\ReiTam\AI\Gemini\Kreta
.\deploy.ps1 -Release vX.Y.Z
```

A folyamat: git tag létrehozása/push → szerveri mentés → staging másolás (Samba) →
SSH: **előellenőrzés** → munkakönyvtár frissítése → `docker compose up -d --build` → healthcheck.

**Előellenőrzés a szerveren (a másolás előtt):** a script SSH-n ellenőrzi, hogy
a Docker daemon fut, a munkakönyvtár olvasható (nincs I/O hiba), a data köteten
megvan a `config.json`, és van legalább **1 GB szabad hely**. Ha valamelyik nem
teljesül, a deploy **a másolás előtt leáll** érthető hibaüzenettel (90% feletti
kihasználtságnál figyelmeztet). Így egy lemez-/mount-hiba nem a másolás közepén
derül ki.

**A deploy NEM másolja** a `config.json`-t, az adatbázist és a `sync.log`-ot (ezek a data
köteten élnek). A `config.json`-t szükség esetén **kézzel** kell a data kötetre másolni.

**Csak a futásidejű fájlok mennek fel.** A munkakönyvtárba (`/mnt/work/Kreta`) a
következők kerülnek: `app.py`, `kreta_*.py`, `requirements.txt`, `Dockerfile`,
`docker-compose.yml`, `.dockerignore`, `entrypoint.sh`, `templates/`, `static/`
(a csatolmányok nélkül) és `backup/kreta_backup.sh` (a `-InstallBackup` kapcsolóhoz).
**Soha nem kerül fel:** `config.json`, `*.db`, `api_tokens.json`, `.env`, `sync.log`,
`browser_user_data/`, `static/csatolmanyok/`, `tests/`, `.opencode/`, `poc/`,
`tools/`, `OSSZEFOGLALO-*.md`, `README.md`, `DOKUMENTACIO.md`, `rendszerterv.md`,
`deploy.ps1`, `KretaApp_Start.bat`. A `.dockerignore` ugyanezt kizárja a képből is.
A deploy a korábbi futásokból ott maradt fejlesztői fájlokat/mappákat a
szerveroldali tisztító lépésben **törli** (a `cp -rf` nem töröl).

#### 7.3.1. v1.6.0 (API-first) élesítési ellenőrzőlista

1. `.\deploy.ps1 -Release v1.6.0` — a Chromium **benne marad** az image-ben
   (`kreta_playwright.py` fallback), a DB/config érintetlen.
   **Ha a szinkron utána azonnal `error`:** a `/api/sync/status` `logs` mezője megmondja
   (pl. `ModuleNotFoundError: No module named 'kreta_api'` = a képből hiányzó modul,
   javítva a v1.6.1-ben: `COPY *.py ./`; ellenőrzés: `python tests/test_deploy.py`).
2. A data köteten a `config.json`-ba `"SYNC_MODE": "api_first"` (az első API-s futás
   utáni ellenőrzéshez `"SYNC_SHADOW": true` is bekapcsolható). Ugyanitt érdemes az
   `"NTFY": {"TOPIC": "…"}` blokkot is kitölteni (kényelmesebben szerkeszthető, mint a
   szerver `.env`-je; az env érték erősebb).
3. Kézi szinkron indítása a felületről, majd a naplóban ellenőrizni:
   `Szinkron mód: api_first`, adatkörönként `[API OK]`, a diák végén
   `adatforrások: API: 8, Playwright: 0`, illetve `[ÁRNYÉK]` sorok (ha be volt kapcsolva).
4. `/health` a várt verziót adja; a fejlécben is ez látszik.
5. **ntfy ellenőrzés:** `curl -X POST http://HPReiTam:8085/api/ntfy/test` → `{"ok":true,
   "topic":"…","url":"https://ntfy.sh","status":200}`, és a telefonon megjön a teszt-push.
   Ha `configured:false`, a topic nem látszik a konténerben (`.env` a compose mellett van-e,
   illetve `docker compose up -d --force-recreate` kellett-e).
6. Fallback-próba (opcionális): ideiglenesen rossz jelszóval/API-hibával futtatni —
   a naplóban `[API HIBA]` + Playwright-forrás, az adatok nem duplikálódnak.
7. 1–2 hét után a `SYNC_SHADOW` kikapcsolható; a Playwright csak fallback marad.

> **Lokális (DEV) ntfy:** a repóban nincs `.env`, ezért lokálisan nincs push. Ha kell,
> hozz létre `c:\ReiTam\AI\Gemini\Kreta\.env` fájlt az `.env.example` alapján — de
> **más topic névvel**, mint az éles (`kreta-dev-…`), különben a két futás ugyanoda
> küld, és nem tudod megkülönböztetni őket. Az env erősebb a `config.json` `NTFY`
> blokkjánál.

#### 7.3.2. v1.6.3 élesítési ellenőrzőlista

1. `.\deploy.ps1 -Release v1.6.3` (a v1.6.0-s checklist lépései is érvényesek: config
   `SYNC_MODE`, `/health`, ntfy).
2. **Áttekintés fül** (a nyitó oldal): 5 csempe (heti határidők, új jegyek, új üzenetek,
   igazolatlan hiányzás, kifizetetlen zsebpénz) + gyermekenkénti kártyák; a csempére
   kattintva a szűrt nézet nyílik, „Vissza az áttekintésre" gombbal.
3. **Jegyek fül:** a jegy mellett `%`-jelvény, tooltippel („Az értékelés X%-os súllyal…").
4. **Statisztika fül:** alapból zárt „Tantárgyi átlagok" accordion — asztalon mátrix
   (tantárgy × hónap + „Összes") és „Hónapok átlaga" lábléc; mobilon kapcsoló
   (Havi bontás / Tantárgy szerint), mindkettő tetején a „Teljes átlag".
5. **Kikapcsolt zsebpénzű diáknál** (pl. Bori): a statisztika látszik, a pénz-kártya
   rejtve, helyette figyelmeztető sáv.
6. **Oszlopszélesség:** az átméretezés/húzás nem rendezi át a táblát; a Hiányzások fülön is
   van fogantyú.
7. **Adatvédelem:** üres (de 200-as) API-válasz nem törli a jegyeket (napló: `[FIGYELEM]`).

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
| `/api/statisztika` | diákonkénti statisztika (jegyeloszlás, súlyozott átlag, zsebpénz, tételes lista) |
| `/api/atlagok` | tantárgyi és havi átlagok (a Statisztika fül adatforrása) |
| `/api/tanevek` | az **iskolai adatokból** (jegy/hiányzás/igazolás/kifizetés) származó tanévek, az aktuális tanév, a határok, és a tanév-állapot (nyitott/lezárt, lezárva). Az üzenetek tanév-függetlenek, ezért nem hoznak létre tanév-bejegyzést |
| `/api/dashboard` | Áttekintés fül összesítői (diákonkénti átlag, kifizetetlen egyenleg, igazolatlan óra) |
| `/api/kommentek` | saját megjegyzések: `GET ?cel_tipus=&cel_kulcs=`, `POST {cel_tipus, cel_kulcs, szoveg}`, `DELETE /api/kommentek/<id>` |
| Rendszernapló fül / `sync.log` | részletes futási napló (rotált, max. 1 MB/példány) |
| `sync_runs` tábla | strukturált futástörténet (a futás tanévével) |
| `deploy.log` / `version.txt` | telepített verzió |

**Tanév-szűrő (Kaneo #40):** a `/api/esemenyek`, `/api/hianyzasok`, `/api/igazolasok`,
`/api/atlagok`, `/api/statisztika`, `/api/dashboard` végpontok `?tanev=` paramétert fogadnak:
üres vagy `all` = **összes tanév** (visszafelé kompatibilis), `current` = a naptár szerinti
aktuális tanév, egyébként pl. `2026/2027`. A válaszok `tanev` mezőt is tartalmaznak.
A felület a fejléc választójában **mindig explicit** értéket küld. A `/api/sync/status`
`tanev` mezője a futás tanéve.

### 7.6. Gyakori hibák és teendők

| Tünet | Ok | Teendő |
|---|---|---|
| „A config.json fájl nem található" a futásban | a scraper nem a data könyvtárat nézte (javítva v1.2.1) | verzió ellenőrzése |
| A szinkron azonnal „error, 0.0 perc" | a konténerben hiányzó Python-modul (`/api/sync/status` logs: `ModuleNotFoundError`) — a Dockerfile nem másolja be az új modult | **v1.6.1-től** `COPY *.py ./`; ellenőrzés: `python tests/test_deploy.py`, majd újraépítés |
| Nincs értesítés | `NTFY_TOPIC` nincs a `.env`-ben (lokálisan nincs is `.env`, ezért csendben nem küld), vagy a konténer nem lett újralétrehozva | topic a `.env`-be **vagy** a config.json `NTFY.TOPIC`-jába; ellenőrzés: `POST /api/ntfy/test` |
| A fejléc „régi" adatot mutat | böngésző-gyorsítótár | Ctrl+F5 |
| Két helyi példány ugyanazon a porton | Windows megengedi (SO_REUSEADDR) | a régi folyamat leállítása — a v1.6.0-tól az app **indításkor szól**: „a port már foglalt" és kilép |
| DB „malformed" olvasáskor | SMB-n keresztüli olvasás futás közben | nyugalmi állapotban ellenőrizni |
| „Internal Server Error" üres DB-nél | a `kreta_adatok.db`-t kézzel áthelyezték/törölték; a Flask korábban csak a saját tábláit hozta létre, az `esemenyek`/`uzenetek` hiányzott | v1.6.0-tól **önjavító**: induláskor (és kérésnél) a hiányzó séma létrejön (`kreta_playwright.py --init-db`), üres adatbázissal is elindul |
| Nem törölhető/nevezhető át a DB fájl | egy futó példány nyitva tartja (SQLite) | a KRÉTA-példány(ok) leállítása, utána a fájlművelet |

**Nulláról tesztelés:** állítsd le az appot, nevezd át/áthelyezned a `kreta_adatok.db`-t, majd indítsd újra. Az app létrehozza a teljes sémát (a naplóban `[Adatbázis] Séma létrehozva`), és üres felülettel indul; az első (kézi) szinkron tölti fel. A séma önmagában is létrehozható: `python kreta_playwright.py --init-db`.

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
├── kreta_api.py           # mobil KRÉTA API kliens (böngésző nélkül)
├── kreta_api_sync.py      # API adatkör-lekérők, ablakok
├── kreta_sync.py          # SYNC_MODE, forrásnapló, fallback
├── kreta_shadow.py        # árnyék/ellenőrző mód
├── kreta_tanev.py         # tanév-számítás + séma-migráció (Kaneo #40)
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

Jelenleg **864 automatikus ellenőrzés** huszonnyolc csomagban: ütemező, részleges hiba/ntfy/napló,
PDF-betűk, útvonalak, új események kimutatása, migráció, **hiányzások/igazolások**
(mentés, összesítő, API, push), **API-kliens** (fake HTTP, 48+ ellenőrzés),
**API-szinkron** (mind a 8 adatkör, órarend-join, táboros téma és `kesz` megőrzése,
**jegy-súlyszázalék normalizálása és mentése**,
fogadóóra, üzenet-inkrementálás, **csatolmány-letöltés API-ból** és fallback-hiba), **szinkronmód és fallback**
(mód-feloldás + valódi SQLite-on duplikációvédelem), **árnyék mód** (DB-másolat,
összehasonlítás, a valódi DB érintetlensége), **adatvédelem** (üres API-válasz nem töröl,
50%-os küszöb, órarend-ürülés), **DB-séma őr** (zárolt DB → nincs bootstrap),
**statisztika/zsebpénz** (súlyozott átlag, súly nélküli visszaesés, kikapcsolt zsebpénz,
**dashboard-összesítő**: diákonkénti átlag, kifizetett időszak levonása),
**tantárgyi átlagok** (`/api/atlagok`, havi bontás),
**oszlopszélesség** (valódi böngészőben: átméretezés nem rendez át, fogantyúk a
hiányzásokon is), **dashboard** (valódi böngészőben: csempeszámok, csempe → szűrt lista,
visszalépés, gyermekkártyák, zárt accordion), **mobil elrendezés** (valódi böngészőben, 393 px).
A tesztek izolált temp könyvtárban futnak, a valódi adatokat nem érintik.

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
| KRÉTA DOM-scraping | a KRÉTA felületváltása törheti | az API-first út (v1.6.0) ezt kiváltja; a Playwright fallback megmarad |
| Táboros hiányzás témája | az API nem ad rá témát (nincs órarendi elem) | a meglévő DB-érték megmarad; új táboros sornál üres |
| Adatvédelmi küszöb (3.2.2) | valódi, nagy arányú csökkenést is blokkol (a régi adat marad) | a napló `[FIGYELEM]`-et ír; `KRETA_SYNC_MIN_RATIO`-val állítható |
| Órarend-ablak első napja | az `OrarendElemek` a `KezdetIdopont` UTC dátuma szerint szűr, az egész napos események `23:00Z`-ként jönnek | a kliens egy nappal korábbra is kér (`fetch_lessons`), így a hétfői szünet/ünnep nem marad ki |
| Jövőbeli dolgozat/házi kimarad | az API az ablakon belül adja a sorokat, a házi/számonkérés határideje viszont jövőbeli | a `Házi feladat` és `Bejelentett számonkérés` ablaka **+90 nappal** előre nyúlik (`FUTURE_LOOKAHEAD_DAYS`) |
| Üzenet-csatolmány letöltése | az eAdmin API csak fájl-metadatot ad, a fájl egy rövid életű `nonce` URL-en jön | a kliens a `dokumentumok/uzenetek/{id}` 302-jét követi, és a `files.e-kreta.hu/fajlok/?nonce=…` címről tölt (2026-10-31 óta API-ból, böngésző nélkül); hiba esetén `api_first` fallback |
| „Új bejelentkezés" e-mailek | az API-út minden futásnál belépne (a Playwright-nál a profil megjegyezte a munkamenetet) | tokentárolás a data köteten (`api_tokens.json`): a 2. futástól **nincs új belépés**, lejárat után refresh token; teljes belépés csak token nélkül/hibánál |
| Nincs `MESSAGE_LIMIT` | az első API-s futás az összes üzenetet letölti (nálunk ~76 sor), utána már csak az újakat | tudatos döntés: az inkrementális futások így is 1–5 üzenetet hoznak |
| Chromium az image-ben | nagyobb image | a Playwright fallback miatt szükséges, amíg az API hosszú távon nem bizonyít |
| CDN-függő frontend | internet nélkül nem indul a felület | vendorolás a backlogban |
| `config.json` egyszerű szöveg | jelszavak olvashatók a fájlból | a data kötet védett |
| A tanárgyi átlagok forrása | a KRÉTA webes `*_HaviAtlag` mezői üresek/nullák, a `Atlag` (időszaki) viszont súlyozott | a havi bontást a saját számításunk adja a jegyek súlyából; az időszaki átlag **egyezik** a KRÉTA `Atlag` mezőjével (élő ellenőrzés) |
| Tanév forrása (Kaneo #40) | a KRÉTA mobil API rekord-szintű tanévet nem ad (csak `TanuloAdatlap.TanevUid`, a többi tanév-végpont 403) | a tanév a **rekord dátumából számított** (szept. 1.); a `TanevUid` a váltás jelzője (a nevet a dátum adja) |
| KRÉTA API tanév-scope (2026-11-03 mérés) | a mobil API a **korábbi tanévekre 0 sort ad**, csak az aktív tanévet szolgálja ki (dátum-szűrő közben működik) | a régi tanévek adata **pótolhatatlan** → soha nem törlünk korábbi tanévet; a napi backup és a törlésvédelem kritikus; nincs visszamenőleges lekérés |
| Tanév zárása/nyitása (Kaneo #43) | a KRÉTA csak a nyers `TanevUid`-t adja (név nélkül; `/Sajat/Tanevek` 403) | a **váltást a `TanevUid`** jelzi; a zárás **technikai** (állapot + időpont), adatlekérés nélkül; a nevet a dátumból generáljuk, a váltás pillanatában rögzítve |
| Tanév-választó alapértéke | a fejléc-választó az **aktuális tanévet** mutatja | így a napi használatban nem keverednek a tanévek; az „Összes tanév" egy kattintás |
| Átlag „Összes tanév" módban | tanévek közötti átlag nem értelmezhető | a felület ilyenkor **nem mutat átlagot**, tanévválasztásra kér; az API `tanev` nélkül (kompatibilitásból) továbbra is számol |
| Törlési hatókör (Kaneo #40) | a teljes cserék csak a letöltött tanévekre + az ablakon belülre törölnek | üres batch soha nem töröl, ismeretlen tanév soha nem töröl; a korábbi tanév sorai érintetlenek |
| WAL nem használt | párhuzamos írások ritkák | FUSE kötet miatt biztonságosabb |

---

## 11. Továbbfejlesztési lehetőségek (backlog)

### B) Funkciók

| # | Lehetőség | Üzleti haszon | Becsült ráfordítás |
|---|---|---|---|
| B1 | **Hiányzások / késések modul** | **KÉSZ (v1.5.0):** új „Hiányzások" fül havi összesítővel (igazolt/igazolatlan óra, késés), a késések és az igazolások is gyűjtve; a push tartalmazza az új hiányzásokat és az igazolatlan órákat | – |
| B2 | **Órarend-változás figyelés** (terem/tanár/helyettesítés) + értesítés | „mi változott ma" azonnal | 1–2 nap |
| B3 | **Napi/heti digest** összefoglaló | egy üzenetben a nap lényege | 1–2 nap |
| B4 | **Mobilos „Ma" nézet** — kompakt napi kártya | *(a reszponzív mobil elrendezés már elkészült a v1.4.0-ban; ez egy külön napi összefoglaló nézet)* | 1–2 nap |
| B5 | **Futástörténet a felületen** (a `sync_runs` már tárolja) | átlátható előzmények | 0,5–1 nap |
| B6 | Üzenet-keresés, olvasott/olvasatlan, zsebpénz CSV export | kényelem | 1–2 nap |

### C) Karbantarthatóság / kockázatok

| # | Lehetőség | Miért fontos | Becsült ráfordítás |
|---|---|---|---|
| C1 | **CDN-ek vendorolása** (`static/` alá) | internet nélkül most nem indul a felület | 0,5 nap |
| C2 | **CI** (GitHub Actions; a tesztek megvannak — 180 ellenőrzés, 8 csomag, pytest-alakítás) | automatikus ellenőrzés minden commitnál | 0,5–1 nap |
| C3 | `app.py` / `index.html` szétbontása | karbantarthatóság | 3–5 nap |
| C4 | DB-migrációs keret + indexek | hosszú távú stabilitás | 1 nap |
| C5 | **Hitelesítés** (basic auth / reverse proxy) | gyerek-adatok védelme | 0,5–1 nap |
| C6 | Apróságok: `SyntaxWarning`, `config.json.example` vessző, halott `autoSyncAlert` | tisztaság | 2–3 óra |
| C7 | **Deploy előtti szerver-ellenőrzés** — Docker daemon, munkakönyvtár olvashatósága (I/O hiba), `config.json` megléte, szabad hely | **KÉSZ**: a deploy a másolás előtt leáll, ha valami hiányzik; 90% feletti HDD-kihasználtságnál figyelmeztet. A lemez-/Docker-áthelyezés (C7b–d) **elvetve** — a felhasználó szerint monitoring már van rá | – |

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
| **v1.4.1** | **2026-10-29** | Mobil finomítás: **monogram-avatar** a diák oszlopban (szabad hely a **bejegyzés dátumának**), a naptár két lista-gombja külön névvel (Havi/Heti lista), rövidebb mobil fejléc-címkék, **az utolsó frissítés sora mobilon is látszik** (korábban a CSS elrejtette) |
| **v1.5.0** | **2026-10-29** | **Hiányzások / késések modul:** új `hianyzasok` és `igazolasok` tábla, scraper, „Hiányzások" fül havi összesítővel (igazolt/igazolatlan óra, késés db/perc) és igazolás-listával; **inkrementális mentés dátum + órasorszám alapján** (stabil sor-ID); az új hiányzások és igazolatlan órák a push-üzenetben is megjelennek |
| **v1.5.1** | **2026-10-30** | Hiányzások fül finomítás: az összesítő első kártyája **„Összes hiányzás" órában** (nem db); a hosszú igazolás-típus és megjegyzés teljes szöveggel, több sorban látszik (tooltipek a többi hosszú mezőn) |
| **v1.6.0** | **2026-10-31** | **API-first szinkron:** `kreta_api.py` termelési API-kliens (böngésző nélküli login, 8 adatkör, normalizálás), `kreta_sync.py` + `SYNC_MODE` (`playwright`/`api`/`api_first`) adatkör-szintű Playwright fallbackkel, a forrás naplózása a `sync_runs.sources`-ba; **`SYNC_SHADOW` árnyék/ellenőrző mód** (Playwright DB-másolaton, összehasonlítás); **üzenet-csatolmányok letöltése API-ból** (`dokumentumok/uzenetek/{id}` → `files.e-kreta.hu` nonce URL, `safe_fajlnev` + méretkorlát), böngésző nélkül; a scraper kimenete UTF-8-ként olvasva, árva gyerekprocessz nem marad; **DB-séma önjavítás** (hiányzó/üres adatbázis), port-ütközés felismerése induláskor; az órarend-ablak egy nappal korábbra kér (UTC-határ). **D1–D9 kész** |
| **v1.6.1** | **2026-11-02** | **Éles javítás:** a Docker képből hiányoztak az API-modulok (`kreta_api.py`, `kreta_api_sync.py`, `kreta_sync.py`, `kreta_shadow.py`) — a Dockerfile csak az `app.py`-t és a `kreta_playwright.py`-t másolta → minden szinkron azonnal `error` lett (`ModuleNotFoundError`). Most `COPY *.py ./`; a `requests` bekerült a `requirements.txt`-be (a Playwright nem hozza magával). Új `tests/test_deploy.py` (Dockerfile COPY + requirements + dockerignore konzisztencia). Emellett **API token-tár** (`api_tokens.json`): a 2. futástól nincs új belépés, így nincs „új bejelentkezés" e-mail; **ntfy** a `config.json` `NTFY` blokkjából is beállítható (`POST /api/ntfy/test`) |
| **v1.6.2** | **2026-11-02** | **Jövőbeli határidők javítása:** a házi feladat és a bejelentett számonkérés API-ablaka **90 nappal előre** is nyúlik (`FUTURE_LOOKAHEAD_DAYS`), mert a KRÉTA az ablakon kívüli (jövőbeli) sorokat nem adja — enélkül a következő hetek dolgozatai/házijai kimaradtak. Élő mérés: 10 → 14 számonkérés, 22 → 25 házi ugyanarra a diákra |
| **v1.6.3** | **2026-11-02** | **Adatvédelem a teljes cserés mentésnél:** üres (de 200-as) API-válasz nem törli a meglévő jegyeket/feljegyzéseket (50%-os küszöb, `KRETA_SYNC_MIN_RATIO`), az órarend csak teljes ürülésnél véd; védett mentésnél a szolgáltató hibát dob (fallback). **DB-séma őr:** zárolt/bizonytalan adatbázisnál nincs init-db subprocess és nincs végleges önjavítás-kikapcsolás. **Jegyek súlyszázaléka:** az `esemenyek` tábla új `suly_szazalek` oszlopa (ALTER migráció a régi DB-khez), a mobil API `SulySzazalekErteke` mezője (50/100/200%) normalizálva és mentve, Playwright-módban a webes **hónap-cella tooltipjének `data-suly`** attribútuma („Súly: 50%") adja ugyanezt, ezért fallbacknél sem veszik el; a jegyek fülön a jegy mellett kis `%`-jelvény tooltippel („Az értékelés X%-os súllyal számít bele az átlagba."), a zsebpénz-elszámolás részleteinél is látszik. **Oszlopszélesség (Kaneo #35):** az átméretezés nem rendez át (a fogantyú kattintása nem ér fel a fejléchez), és a hiányzások/igazolások táblán is van fogantyú. **Súlyozott tanulmányi átlag (Kaneo #36):** Σ(jegy×súly)/Σ(súly), a 0%-os súlyú jegy kimarad, súlyadat nélkül egyszerű átlag. **Kikapcsolt zsebpénz (Kaneo #37):** a statisztika ilyenkor is működik, csak a pénz-kártya rejtve + figyelmeztető sáv. **Dashboard (Kaneo #38):** új nyitó „Áttekintés" fül kattintható csempékkel (heti határidők, új jegyek / új üzenetek az elmúlt 7 napban, **igazolatlan hiányzás**, **kifizetetlen zsebpénz** — utóbbi a teljes időszak egyenlege mínusz a kifizetett időszakok), **gyermekenkénti kártyák** (teljes időszaki átlag + egyenleg), gyermek-chipek; a szűrőpanel csak az eseménylistán látszik, „Vissza az áttekintésre" gombbal. **Tantárgyi átlagok (Kaneo #39):** `/api/atlagok` végpont (tantárgy × hónap + havi teljes átlag), **alapból zárt accordion** a Statisztika fülön: asztalon mátrix „Összes" oszloppal és „Hónapok átlaga" lábléccel, mobilon **kapcsoló** (Havi bontás / Tantárgy szerint), a „Teljes átlag" mindkettő tetején. **Ellenőrizve:** a számított tantárgyi átlagok a KRÉTA saját értékeivel egyeznek. Emellett a `tests/run_all.py` a gyerekteszteket UTF-8-ra kényszeríti (cp1250 konzolon ne szálljon el). **Ez a kiadás viszi élesbe a v1.6.2 óta felgyűlt minden változást** (a v1.6.4 nem készül el külön) |

| **v1.6.4** | **2026-11-02** | **Dokumentáció-frissítés:** a rendszerleírás naprakésszé tétele (fejléc, új API-végpontok a megfigyelhetőség táblában, v1.6.3 élesítési ellenőrzőlista, ismert korlát a KRÉTA havi átlag-mezőiről), README verziótörténet, `rendszerterv.md` jelölése történeti dokumentumnak. Kódbeli változás nincs |
| **v1.6.5** *(élesítésre vár)* | **2026-11-02** | **Tantárgyi átlagok finomítás:** a mátrix hónap-oszlopai csak a hónap nevét mutatják („szept.", az évszám a tooltipben), a kártya tetején **tanév + időszak** felirat (pl. „2026/2027. tanév · időszak: 2026. 10. 01. – 2026. 11. 30."), a tanévet a hónapokból számolva. Teszt: a fejléc nem tartalmaz évszámot, a felirat látszik |

| **v1.7.0** *(fejlesztés alatt)* | **2026-11-03** | **Tanév-kezelés, 0–6. fázis:** új `kreta_tanev.py` (a tanév a rekord **dátumából** számítva, szept. 1. – aug. 31.; `KRETA_TODAY` / `KRETA_TANEV_KEZDO` env, tesztelhető `today=` paraméter; `teljesen_lekert` a törlési jogosultsághoz), `tanev` + `tanev_forras` oszlop a `esemenyek`/`uzenetek`/`hianyzasok`/`igazolasok`/`kifizetesek` táblán + `sync_runs.tanev` (**az órarend kivétel**), **csak UPDATE** backfill (ID-stabil, újraindítható) mindkét DDL-helyen. **Mentés tanév-tudatosan:** a teljes cserék törlése csak a letöltött tanévekre és az **ablakon belülre** hat, az arányos őr tanévenként számol, **üres batch soha nem töröl**; az igazolások **upsert** `kreta_id` kulcson; az API-ablak a **tanév első napjától** indul (a `MIN(stored)` megszűnt). **API:** `?tanev=` szűrő + `/api/tanevek`. **Felület:** tanév-választó a fejlécben (alap: aktuális tanév, „Összes tanév" opció; összes tanévnél nincs átlag); üres tanév súgó; a dátum-/hónapválasztók a tanév határain belül (#53); a dashboard-csempék tanévváltáskor azonnal frissülnek (#51). **Tanév-állapot (#43):** `tanevek` + `tanulo_tanev_uid` tábla; minden futás után a `TanuloAdatlap.TanevUid` ellenőrzése, változásnál **technikai zárás/nyitás adatlekérés nélkül** (a nevet a dátum adja); a fejlécben állapotjelzés, a választóban „lezárt” jelölés (a kézi záró gomb megszűnt). **Futásnapló:** a futás tanéve a `sync_runs.tanev`-be, tanévváltásnál naplósor + push; a `POST /api/kifizetes` a kifizetés tanévét az időszak kezdetéből írja be. **#42:** az igazolások adatvédelmi őrrel. **#46:** saját megjegyzések eseményhez/üzenethez (`kommentek` tábla, stabil tartalom-kulcs, `/api/kommentek`). Új tesztek: `test_tanev`, `test_tanev_migration`, `test_tanev_sync` (óra-bomba: 08-31 → 09-01 → 09-03), `test_tanev_api`, `test_tanev_state`, `test_tanev_ui`, `test_kommentek`; 864 ellenőrzés / 28 csomag |

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
