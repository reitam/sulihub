# KRÉTA Adatbázis Áttekintő — Rendszerdokumentáció

| | |
|---|---|
| **Dokumentum verziója** | 1.9 (Kaneo #9, #78, #80, #82, #83, #85, #90, #101, #110–#121) |
| **A rendszer verziója** | v2.1.3 (kiadásra kész — élesítésre vár; élesben v2.1.1) |
| **Utolsó frissítés** | 2026-11-08 |
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
| **Értékelések** | Tantárgy, érdemjegy, dátum, tanár, típus, témakör, **súlyszázalék** („100%-os súllyal számít az átlagba”). A súly a **mobil API** `SulySzazalekErteke` mezőjéből jön, Playwright-módban pedig a webes grid **hónap-cellája tooltipjének** `data-suly` attribútumából („Súly: 100%") — mindkettő ugyanabba az oszlopba kerül. A felület a jegy mellett kis `%`-jelvényként mutatja, tooltippel. Az API-first szinkronban a **Magatartás** és a **Szorgalom** két külön sor (0 számértékkel), így az átlagot nem befolyásolják |
| **Feljegyzések** | Dicséretek, megrovások, hiányok, egyéb bejegyzések |
| **Házi feladatok** | Tantárgy, tanár, leírás, rögzítés, határidő |
| **Bejelentett számonkérések** | Tantárgy, mód, téma, bejelentés és a számonkérés napja |
| **Hiányzások / késések** | Dátum, **aznap hányadik óra** (1 sor = 1 tanóra), tantárgy, téma, mulasztás típusa (késésnél percek), igazolt/igazolatlan, igazolás típusa, rögzítés dátuma. A „tanórai célú” jelző is tárolva van, de a felületen nem jelenik meg |
| **Igazolások** | Érvényesség kezdete–vége, igazolás típusa, megjegyzés |
| **Heti órarend** | Aktuális és következő hét: tanár, terem, időpont, esetleg egész napos esemény; **fogadóórák** is |
| **e-Ügyintézés üzenetek** | Beérkezett üzenetek (csak az újak) a **teljes szöveggel és bekezdésekkel** — a lista csak előnézetet ad, ezért a mentéskor a `postaladaelemek/<posta_id>` részletes válasz kerül felhasználásra (Kaneo #74); **a csatolmányokkal együtt** — a fájl API-ból töltődik le (`dokumentumok/uzenetek/{id}` → `files.e-kreta.hu` nonce URL), böngésző nélkül |

### 2.3. Felület (fő nézetek)

| Fül | Mire való |
|---|---|
| **Áttekintés** | Nyitó dashboard: **6 kattintható csempe** — **következő házi feladatok** (10 nap), **következő számonkérések** (10 nap), **új jegyek** (10 nap), **új üzenetek** (10 nap), **igazolatlan hiányzás** (óra), **kifizetetlen zsebpénz** (kiegészítő felirat nélkül) —, valamint **„Tanulmányi átlag”** szekció **gyermekenkénti kártyákkal**: **monogramos avatar**, név, diszkrét jegyszám-badge, nagy tanulmányi átlag és egyenleg. A **gyermekszűrő chipek** és az **„Események listája”** gomb a **fül-sáv alatt, az összes csempe felett** vannak (a szűrő a csempékre is vonatkozik). A tanév/súlyozás magyarázata **egyszer, a szakasz fejlécében** van. **Kompakt, 3×2 elrendezés**, egységes csempesablon, **látható kerettel**; széles kijelzőn a dashboard **középre igazított (max. 1200 px)**, a két szélen szimmetrikus üres sávval. **Színlogika:** 0 értéknél semleges (szürke) vagy „rendben” (zöld), csak > 0 esetén élénk szín. Az alsó sávban **2 hasáb**: **„Figyelmet igénylő bejegyzések”** (utolsó **10** feljegyzés típus-badge-dzsel: piros figyelmeztetés, zöld dicséret, szürke felszereléshiány) és **„Legutóbbi jegyek”** (utolsó **10** jegy színes jegy-körrel). A csempére kattintva a megfelelő (szűrt) nézet nyílik |
| **Iskolai események** | Szűrhető, kereshető táblázat: jegyek (a jegy mellett a **súlyszázalék** jelvénye), feljegyzések, házik, számonkérések. Szűrők: gyermek (chip is), típus, tantárgy, időszak, dátumtartomány, gyorsszűrők; a **szűrőpanel alapból zárva** van, a fejlécére kattintva nyílik (Kaneo #120); "Vissza az áttekintésre" gomb. **Excel export** a jelenlegi szűrőkkel (Jegyek / Feljegyzések / Házi feladatok — Kaneo #83). Soronként **saját megjegyzés** fűzhető (Kaneo #46) |
| **Hiányzások** | Hiányzások és késések havi bontásban: **5 összesítő kártya** (összes hiányzás óra, igazolt óra, igazolatlan óra, késés db/perc, igazolás db) + részletes tábla és igazolás-lista. Alapból a **teljes előzmény** látszik, a havi bontás hónapválasztóval / „Aktuális hónap" gombbal. **Excel export** (Hiányzások / Igazolások — Kaneo #83) |
| **Heti órarend** | Idősávos heti nézet, gyermekszínekkel; **A4 PDF export**; **kézi „Saját óra”** tételek (szakkör, plusz foglalkozás) tanévre / hétre / egyedi időszakra, egy alkalom vagy a teljes sorozat törlésével (Kaneo #55); **ICS export** hét / hónap / félév / tanév időszakra (Kaneo #73) |
| **Feladatok naptár nézet** | Házik és számonkérések határidő szerint, színkódolva; a részletek ablakból **közvetlen „Naptárba küldés”** (előre kitöltött Google Naptár esemény, egy kattintásos mentés) (Kaneo #47) |
| **Beérkezett üzenetek** | Üzenetek olvasása (a **teljes törzs** a részletes API-válaszból, a sortörések megőrzésével — Kaneo #74), **szöveges keresés a tárgyban, a feladóban és az üzenet tartalmában**, **helyi olvasott/olvasatlan állapot** (olvasatlan számláló a fülön, félkövér + kék pötty a listában, Mind/Olvasatlan/Olvasott gyorsszűrő, megnyitáskor automatikus olvasottnak jelölés + kézi oda-vissza váltás; **checkboxos kijelölés** soronként és „mind” a fejlécben, a kijelölteken vagy a teljes listán **egylépéses olvasott/olvasatlan** váltás; a KRÉTA felé nem ír vissza — Kaneo #11), csatolmányok letöltése; az üzenethez is fűzhető **saját megjegyzés** (Kaneo #46), valamint **„Naptárba küldés”** Google Naptárba (Kaneo #47/#60) |
| **Statisztika & Zsebpénz** | Havi jegyeloszlás, átlag, dicséret/hiány mutatók, elszámolás; **az egyenleg tételeinek Excel (`.xlsx`) exportja** — *kiválasztott időszakra*, *teljes tanévre* vagy *teljes előzményre*, tételes **pénzügyi rendezettség-jelöléssel** (Kaneo #11/#77); **riportkártya PDF** félévi/tanévi bontásban, gyermekenként mentve és visszakereshetően (Kaneo #82) |
| **Rendszernapló** | A szinkronizációk naplója, hibák, előzmények; **legutóbbi 20 futás** táblázata (indult, futásidő, státusz, új esemény, hibás diák, tanév) és **futásidő-sparkline** (Kaneo #10) |

**Szűrőfüggetlen dashboard (Kaneo #76):** az Áttekintés a saját, szűrés nélküli
adatforrását tölti be (`/api/esemenyek` csak gyermek- és tanév-szűrővel, `/api/uzenetek`),
ezért az eseménylistán beállított típus/tantárgy szűrő **nem tud kiüresedni** a csempékben
és a feedekben; fülre visszatéréskor a panelek azonnal újraszámolódnak, majd frissülnek —
F5 nem szükséges.

**Fejléc (Kaneo #62/#63/#71):** bal sarokban a **SuliHub logó + név + verzióbadge**
(66 px logó, 2,1 rem név); a jobb oldali sávban a **tanévválasztó**, a **szinkron
státuszsáv** („Frissítve: tegnap 21:16 (kézi)”) és a **Frissítés** gomb. A technikai
részletek (ütemező, időablak, következő futás, utolsó automatikus futás) koppintásra
nyíló ablakban vannak. Asztalon a fejléc 87 px magas, gradiens háttérrel és finom
árnyékkal; mobilon a brand felül, alatta a státusz, majd a tanév + Frissítés.

**Fülek:** semleges (sötétszürke) ikonok és feliratok; **csak az aktív fület** emeli ki a
felület (kék szöveg/ikon + alsó kék vonal). A korábbi színes fül-ikonok (piros, sárga,
zöld stb.) megszűntek — kevesebb vizuális zaj.

**Oszlopok szélessége:** az *Iskolai események*, *Hiányzások*, *Igazolások* és *Beérkezett
üzenetek* táblázat fejlécében a jobb szélen lévő fogantyúval (egérrel) állítható. Az
átméretezés **nem változtatja meg a sorrendet** (a fogantyú kattintása nem rendez).

### 2.4. Mobil használat (telefon)

A felület **mobilra is optimalizált** (Redmi 12/13/14 méret, ~393 CSS px):

- a fejléc egymás alá rendeződik, a frissítés gomb a tanévválasztó mellett marad,
- a **szinkron állapota minden nézetben egyetlen karcsú sor** (🟢 „Frissítve: ma 21:33
  (kézi)”, futáskor pörgő ikon + „Szinkronizálás folyamatban…”, hiba esetén piros
  „Sikertelen frissítés”); a technikai részletek (ütemező BE/KI, időablak, intervallum,
  következő és utolsó futás) **koppintásra nyíló ablakban** vannak, így nem rabolnak
  vertikális helyet; az ablak tartalma nem csúszik ki, a hosszú „utolsó frissítés /
  utolsó automatikus” sor két sorba tördelve látszik,
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
a fő elemek a képernyőn belül vannak, a táblázat összecsukott, a státuszsáv egy sor
és koppintásra megnyílik a részletek ablaka).

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

A szerveren a `NTFY_TOPIC` (stb.) a `/opt/sulihub/.env`-ben él (a compose `env_file`-ja);
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

### 2.7. Saját órák és naptárbejegyzés (Kaneo #55 / #47)

**Saját óra (Heti órarend fül):** a „Saját óra” gombbal iskolán kívüli elfoglaltság
(szakkör, pluszóra) rögzíthető gyermekenként. Megadható a nap, a kezdés/vége, a terem,
a megjegyzés és a **szín** (a gyermek alap színétől eltérő, alapból lila), valamint az
érvényesség: **teljes tanév**, **aktuális hét** vagy **egyedi időszak**. A tétel
**sorozatként** tárolódik, ezért a naptárban hetente megjelenik; a KRÉTA-szinkron nem
törli. A naptárban a tételre koppintva **módosítható** (a teljes sorozat adatai),
**csak az adott alkalom törölhető** (kivétel) vagy a **teljes sorozat törölhető**.

**Naptárbejegyzés (Feladatok naptár + Üzenetek):** házi feladat / számonkérés
részleteinél, valamint üzeneteknél a **„Naptárba küldés”** gomb egy előre kitöltött
Google Naptár eseményt nyit (cím, dátum, leírás, időzóna) — ott egy kattintással
menthető, letöltés/import nélkül. (A valódi, OAuth-os közvetlen írás a Google
Naptárba külön fejlesztés; a mostani megoldás API-kulcs nélkül működik. Az `.ics`
végpont programozottan továbbra is elérhető.) A viselkedés a `CALENDAR` config-blokkból
állítható (időzóna, emlékeztető, üzenet hossza).

### 2.8. Üzenetek AI-elemzése (Kaneo #61) — **API-only**

A **felületi „AI elemzés” gombot a felhasználó kérésére 2026-11-04-én kivettük**; a
háttér megmaradt és API-ból hívható. Az endpoint az üzenet szövegét és a csatolmány
szövegét (txt/md/csv/pdf, max. ~20 ezer karakter) elküldi egy **OpenAI-kompatibilis**
AI-végpontnak (alapból helyi **Ollama**), a válaszból **validált eseménylista** készül:

- `POST /api/uzenet/<id>/ai` → `{"items":[{cim, datum, ido, helyszin, leiras, google_url}]}`
- `POST /api/naptar/ai/ics` → a kiválasztott elemekből **több VEVENT-es `.ics`**

Adatvédelem: `ALLOW_CLOUD=false` mellett csak magánhálózati AI-URL engedett; a naplóba
nem kerül a gyerek szövege. **Megjegyzés:** a nagyon kicsi modellek (pl. 0.6b) gyengébb
minőséget adnak — API-használatnál érdemes a `AI.MODEL`-ben 3–8B modellt beállítani.

### 2.9. Órarend ICS export (Kaneo #73)

A Heti órarend fülön az **„ICS export”** menüben választható időszak: **aktuális hét,
aktuális hónap, félév, teljes tanév**. A kiválasztott gyermek (vagy az összes) heti
órarendi mintái **ismétlődő VEVENT**-ként (`RRULE:FREQ=WEEKLY`) kerülnek a `.ics`-be,
a megfelelő időszakra szűkítve; a terem `LOCATION`, a tanár `DESCRIPTION` mezőbe kerül.
A fájl Google Naptárba/Apple/Outlookba importálható. A félév szeptember–január,
illetve február–augusztus; a tanév szeptember 1. – augusztus 31. Az azonos heti minta
(diák + tantárgy + nap + kezdés + időtartam) **egyetlen VEVENT** — a szinkron az aktuális
és a következő hetet is leéri, és a tábla sorait nem vonnánk össze, minden kétszer
kerülne az exportba (Kaneo #73).

### 2.10. Globális kereső (Kaneo #85)

**Ctrl+K** (mobilon a nagyító gomb) → kereső ablak; a keresőmező **azonnal aktív**
(oda kerül a fókusz, nem kell külön rákattintani). Egyszerre keres a **jegyekben,
feljegyzésekben, házikban/számonkérésekben, üzenetekben (a teljes törzsben) és
hiányzásokban**. Legfeljebb 20 találat, dátum szerint csökkenő sorrendben. A találat
sorára kattintva **az adott sor részletei nyílnak meg** (esemény → részletek modál,
üzenet → üzenet-ablak, hiányzás → hiányzás részletei); ha az adat időközben elfogyott,
a megfelelő szűrt nézet nyílik. A találat-típusok **felirata és színe ugyanaz, mint az
Események fülön** (Értékelés, Feljegyzés, Házi feladat, Bejelentett számonkérés). A keresés
a `/api/kereses` végponton fut (LIKE, escape-elt speciális karakterekkel), tipikusan <10 ms.

### 2.11. „Milyen jegy kell?” kalkulátor (Kaneo #78, #101)

A Statisztika fülön tantárgy + **célátlag** + a **várható jegyek** (súly + opcionális
jegy) alapján megmondja, **milyen jegy(ek) kellenek**: egy jegy (1–5) vagy több ötös,
illetve hogy a cél már nem érhető el. A tantárgy-választó **alapból üres** (a jegyek
listája és az eredmény csak kiválasztás után jelenik meg), és üres elemre vissza lehet
állni. A kiválasztott tantárgy **meglévő jegyeit** a kártya táblázatban listázza
(dátum, jegy, súly).

**Több várható jegy (Kaneo #101):** a „további jegy” gombbal további sorok adhatók,
eltérő súllyal (50/100/200%). Több jegy esetén a kalkulátor a hátralévő jegyekre
**szükséges összesített átlagot** adja; ha a várható jegyek is meg vannak adva,
**szimulálja a várható átlagot** és jelzi, hogy a cél teljesül-e.

**Félévi cél:** a „Félévi céljegy” (1–5) alapján a `félévi jegy - 0,5` küszöbhöz
szükséges átlagot mutatja a hátralévő jegyeken (pl. 4-eshez 3,50). A **célátlag és a
félévi cél tantárgyanként mentődik** (`app_meta`; `GET/POST /api/kalkulator_cel`), és a
tantárgy kiválasztásakor automatikusan visszatöltődik.

A számítás a KRÉTA súlyozását használja (a 0%-os súlyú jegy kimarad; súlyadat nélkül
100%-os becslés). A kalkulátor **mindig a teljes tanév jegyállományát** veszi figyelembe —
az eseménylista időszak-szűrője nem befolyásolja. A tételes válasz a
`/api/jegy_kalkulator` végponton is elérhető (`tobb`, `sulyok`, `szukseges_atlag`,
`szimulalt_atlag`, `felevi_*`, `jegyek`).

### 2.12. UX csomag: sötét mód, nyomtatás, kedvencek (Kaneo #86)

- **Sötét mód:** fejléc-gomb, Bootstrap 5.3 `data-bs-theme`; a választás `localStorage`-ban marad.
  A körvonalas vezérlők (gyermek-chipek, Nyomtatás) sötét módban is olvasható színt kapnak;
  a dashboard kártyacímek, a táblázat-konténer, a kiemelt sorok (ma/elkészült/olvasatlan),
  az accordion-fejlécek, a státuszsáv, a modálfejlécek és a **naptár (FullCalendar)**
  háttere/szövege is a sötét témához igazodik. A naptár-események szövegszíne a
  háttérszínhez számolódik (`textColor`), így a pasztell és a sötét színeken is olvasható.
- **Nyomtatásbarát heti órarend:** a Heti órarend fülön **„Nyomtatás”** — A4 fekvő, nagy
  betűs, színes táblázat (diákonként, nap × időpont), böngésző-nyomtatással. A nyomtatási
  fejléc (a dokumentum címe) **„SuliHub – Órarend – gyermek – hétfő–vasárnap”** formátumú.
- **Kitűzött események:** az eseménysorban a **csillag** gomb az Áttekintésre tűzi a tételt
  (stabil tartalom-kulccsal, `app_meta`); a dashboardon megjelenő panelről egy kattintással
  a szűrt listára lehet ugrani vagy le lehet venni.

### 2.13. Tantárgyi trend és hiányzás-mintázat (Kaneo #80)

A tantárgyi átlagok táblázat **Trend** oszlopa a havi átlagok **sparkline-ját** és az utolsó
két hónap különbségét mutatja (zöld/javul, piros/romlik). Az Áttekintés tetején
**figyelmeztető sáv** jelzi a **romló** tantárgyakat (≤ -0,5) **gyermeknévenként és az
érintett időszakkal** (pl. „Teszt Elek – Irodalom (2026. szeptember → 2026. október,
-2)”), alatta zöld sáv a **javulókat** (≥ +0,5). A `/api/atlagok` válasza tantárgyanként
`trend`-et, valamint gyermekenkénti `figyelmeztetesek` és `javulasok` listát ad (a `diak` és
a két hónap mezőjével). A Hiányzások fülön a **Hiányzás-mintázat**
kártya (a táblázatok **alatt, alapból csukva**) bontja a hiányzásokat **nap, órasorszám
és tantárgy** szerint (`/api/hianyzas-mintazat`), a tanév- és diák-szűrőt követve.

### 2.14. „Ma” önálló nézet (Kaneo #9)

Az **Áttekintés utáni „Ma” fül** (a dashboard-kártyát a felhasználó elutasította) napi
összefoglalót ad: **mai órák** (időpont, terem, tanár), **ma és holnap esedékes** házik és
számonkérések pipával (kattintás → kész jelölés), **friss jegyek** (7 nap) és **olvasatlan
üzenetek** (kattintás → üzenet-ablak). Saját gyermek-chipek; a fül megnyitásakor és
gyermekváltáskor automatikusan frissül (nincs külön Frissítés gomb), a fejléc
diák-szűrőjét követi. Adatforrás: `/api/ma?diak=&datum=`.

### 2.15. Riportkártya PDF (Kaneo #82)

A Statisztika fülön **gyermek + időszak** (félév / teljes tanév) választással **A4-es PDF
riportkártya** generálható. Tartalma: összegzés (tanulmányi átlag, jegyszám, hiányzás/
igazolatlan, késés, feljegyzésszám, zsebpénz-egyenleg), **tantárgyi táblázat** (jegyek
dátummal, súlyozott átlag, db), viselkedés/magatartás és a feljegyzések. A PDF a
**data köteten, gyermekenként** mentődik (`riportkartyak` tábla + fájl), és a kártya
**korábbi riportjai visszakereshetők, megnyithatók/nyomtathatók**
(`/api/riportkartyak`, `/api/riportkartyak/<id>/pdf`).

A **hivatalos félévi/év végi osztályzat** a KRÉTA API-ból nem érhető el (félévkor sem
kérdezhető le), ezért a riport a jegyekből számolt, KRÉTA-súlyozású átlagot mutatja, és
ezt a PDF láblécében jelzi is. Az időszak: félév = tanév kezdete – jan. 31., tanév =
szept. 1. – aug. 31.

### 2.16. Tanulmányi Excel exportok (Kaneo #83)

- **Iskolai események** fül: **Excel export** a jelenlegi szűrőkkel (diák, tanév,
  bejegyzés-dátumtartomány) → `GET /api/esemenyek/export.xlsx`, munkalapok: **Jegyek**
  (diák, tantárgy, jegy, súly%, mód, téma, tanár, dátum, tanév), **Feljegyzések**,
  **Házi feladatok** (a bejelentett számonkérésekkel; állapot: elkészítve/aktív).
- **Hiányzások** fül: `GET /api/hianyzasok/export.xlsx` → **Hiányzások** (dátum, óra,
  tantárgy, téma, tanár, típus, igazolt, késés perc, tanév) és **Igazolások** (kezdet,
  vég, típus, megjegyzés) munkalapok; az igazolásoknál az időszakkal **átfedő** sorok
  kerülnek bele.
- A számok/sorok a felület szűrőivel egyeznek; a fájlok `.xlsx` formátumúak (openpyxl).

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

Az API-first szinkron bevezetésével a scraper mellett megjelent a **böngésző nélküli út**
is: `kreta_api.py` (mobil v3 / eAdmin végpontok + normalizálás a meglévő DB-sémákra) és
`kreta_sync.py` (forrásmód és adatkör-szintű fallback). A `SYNC_MODE` dönti el, melyik út
fut — lásd 3.2.1.

**Moduláris szerkezet (KRÉ-14, v2.0.0).** A korábbi ~4 100 soros `app.py` és az egyfájlos
frontend szétbontva; a viselkedés (URL-ek, válaszok, DB-séma) változatlan:

| Réteg | Modulok |
|---|---|
| belépő + futásidejű mag | `app.py` (~1 100 sor): Flask app, auth, szinkron/ütemező/ntfy/napló, re-export a tesztekhez |
| útvonalak (prefix nélküli blueprint-ek) | `views_pages`, `views_events`, `views_orarend`, `views_messages`, `views_absences`, `views_stats`, `views_rewards`, `views_search`, `kreta_exports` |
| közös rétegek | `kreta_paths` (útvonalak), `kreta_db` (séma, meta, futásnapló), `kreta_settings` (config, verzió, színek), `views_common` (request-segédek) |
| frontend | `templates/index.html` (váz + modálok), `static/js/core.js` (globális segédek), `static/js/app-main.js` (a `$(document).ready` blokk) |
| futásidejű adatok | `data/` (DB, config.json, napló, tokenek, böngészőprofil, csatolmányok) — lásd 9.2 |

A `tests/test_routes_contract.py` a 42 Flask-rule (41 route + beépített `static`)
rule+metódus listáját rögzíti, a `tools/api_snapshot.py` pedig a válaszok szerkezetét
ellenőrzi a refaktor lépései alatt — így a bontás nem változtathatta meg a nyilvános API-t.

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
| `uzenetek` | e-Ügyintézés üzenetek + csatolmány hivatkozás | Csak az új üzenetek kerülnek be; a `posta_id` a postalada-elem azonosítója — ezzel kérhető le a **teljes szöveg** a részletes API-válaszból (Kaneo #74); az `olvasott` (0/1) a **helyi** olvasott/olvasatlan állapot (a szinkron a már mentett üzenetet nem írja felül, a KRÉTA-ba nem írunk vissza — Kaneo #11). A migráció előtti (történeti) üzenetek **olvasottként** indulnak, hogy ne jelenjen meg minden régi üzenet olvasatlanként |
| `hianyzasok` | Hiányzások és késések (dátum, órasorszám, tantárgy, téma, típus, igazolt, igazolás típusa) | ISO dátum; a rekordot a **dátum + órasorszám** azonosítja; késést a `perc` és/vagy a típus neve jelöli |
| `igazolasok` | Igazolások érvényességi intervalluma + típus + megjegyzés | A hónaphoz a metsző igazolások tartoznak |
| `kifizetesek` | Zsebpénz-elszámolások havi tételei | „KIFIZETVE" állapot, összeg |
| `sync_runs` | **Minden szinkronizáció** egy sora (trigger, időpontok, státusz, darabszámok, új események, futásidő) | Ez adja a „legutóbbi futás" állapotot is |
| `app_meta` | Kulcs–érték technikai állapotok | pl. utolsó elavultsági riasztás ideje |
| `tanevek` | A tanévek állapota: `allapot` (nyitott/lezárt), `lezarva_at`, `forras` (kreta_uid/szamitott) | A zárás/nyitás a `TanevUid` változásához kötött; adatlekérés nélkül |
| `tanulo_tanev_uid` | Diákonként az utoljára látott KRÉTA `TanevUid` + a hozzá tartozó tanév | A váltás-detektálás alapja (a KRÉTA csak ezt adja, nevet nem) |
| `kommentek` | **Saját megjegyzések** eseményhez / üzenethez (szöveg, szerző, időpont) | Nem a KRÉTA-ból jön; a célzás **stabil tartalom-kulccsal** történik (az események id-je a szinkronnál változik) — Kaneo #46 |
| `sajat_orarend` | **Kézi órarendi sorozatok**: diák, megnevezés, nap (1–7), kezdés/vége, terem, megjegyzés, **szín**, érvényesség (`ervenyes_tol`–`ervenyes_ig`) | A KRÉTA szinkron **nem érinti**; egy sor = heti ismétlődő sorozat — Kaneo #55 |
| `sajat_orarend_kivetel` | Egy sorozat kivett alkalmai (`sajat_id`, `datum`, egyedi) | „Csak ezt az alkalmat törli” — a sorozat többi alkalma megmarad — Kaneo #55 |

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
| **KRÉTA** (`<intézmény>.e-kreta.hu`) | Adatgyűjtés böngésző-automatizálással (Playwright) | több iskolai azonosító; a bejelentkezés sütiképre támaszkodik |
| **e-Ügyintézés** (`eugyintezes.e-kreta.hu`) | Üzenetek + csatolmányok | API-ból (mobil token), `X-Uzenet-Lokalizacio` illesztő; a Playwright-út csak fallback |
| **ntfy** (`ntfy.sh`) | Push értesítések | Csak állapotinformáció; diáknév alapból nem megy ki |
| **Docker / Docker Compose** | Futtatás a szerveren | Konténer: `kreta-app`, port **8085** |
| **Samba + SSH** | Deploy Windowsról a szerverre | `deploy.ps1` (staging másolás + SSH parancsok) |
| **cron (host)** | Napi mentés 03:00-kor | `kreta_backup.sh` |

### 5.1. Mentés és üzemeltetési ellenőrzések (Kaneo #90)

- A napi mentés (`backup/kreta_backup.sh`) a DB mellé **sorszám-manifestet** ír
  (`kreta_adatok_*.counts.json`), hogy a visszaállítás ellenőrizhető legyen.
- **Havi restore-teszt:** `python3 tools/backup_restore_check.py --backup-dir ... --db ...`
  — a legfrissebb mentést izolált temp könyvtárba állítja vissza, `PRAGMA integrity_check`,
  manifest-egyezés, elavult/sérült mentés detektálása; hibánál ntfy riasztás, a valódi DB-hez
  nem nyúl. Javasolt cron: `15 4 1 * *`.
- **Éjszakai élő füstteszt:** `python3 tools/live_smoke.py --url ... --max-age-hours 26`
  — `/health` + `/api/sync/status`, az utolsó futás státusza és kora. A GitHub Actions
  `live-smoke` jobja éjszakánként fut; `KRETA_URL` (és opcionálisan `KRETA_AUTH_USER`/
  `KRETA_AUTH_PASS`) secret nélkül kimarad. A szervernek kívülről elérhetőnek kell lennie
  (pl. Tailscale Funnel/Cloudflare Tunnel) vagy self-hosted runner kell hozzá.

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
| `CALENDAR` | Naptárbejegyzés (Kaneo #47): `TIMEZONE` (Europe/Budapest), `REMINDER_MINUTES` (30, 0 = nincs), `MESSAGE_DURATION_MINUTES` (30) |
| `ORAREND_SZINEK` | Gyermekenkénti órarend-szín (Kaneo #56), pl. `{"Teszt Elek": "#0d6efd"}`; a felület „Színek” ablaka felülírja (app_meta) |
| `AI` | Üzenet-AI (Kaneo #61): `ENABLED`, `URL` (OpenAI-kompatibilis, pl. `http://127.0.0.1:11434`), `MODEL`, `API_KEY`, `TIMEOUT_SECONDS`, `MAX_INPUT_CHARS`, `ALLOW_CLOUD` (false = csak magánhálózat) |
| `AUTH` | Opcionális basic auth (Kaneo #16): `ENABLED`, `USERNAME`, `PASSWORD_HASH` (werkzeug `generate_password_hash`); a `PASSWORD` csak teszt/átmeneti |

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
SSH: **előellenőrzés** → munkakönyvtár frissítése → `docker compose up -d --build` → healthcheck.

**Előellenőrzés a szerveren (a másolás előtt):** a script SSH-n ellenőrzi, hogy
a Docker daemon fut, a munkakönyvtár olvasható (nincs I/O hiba), a data köteten
megvan a `config.json`, és van legalább **1 GB szabad hely**. Ha valamelyik nem
teljesül, a deploy **a másolás előtt leáll** érthető hibaüzenettel (90% feletti
kihasználtságnál figyelmeztet). Így egy lemez-/mount-hiba nem a másolás közepén
derül ki.

**A deploy NEM másolja** a `config.json`-t, az adatbázist és a `sync.log`-ot (ezek a data
köteten élnek). A `config.json`-t szükség esetén **kézzel** kell a data kötetre másolni.

**Csak a futásidejű fájlok mennek fel.** A munkakönyvtárba (`/opt/sulihub`) a
következők kerülnek: `app.py`, `kreta_*.py`, `requirements.txt`, `Dockerfile`,
`docker-compose.yml`, `.dockerignore`, `entrypoint.sh`, `templates/`, `static/`
(a csatolmányok nélkül) és `backup/kreta_backup.sh` (a `-InstallBackup` kapcsolóhoz).
**Soha nem kerül fel:** `config.json`, `*.db`, `api_tokens.json`, `.env`, `sync.log`,
`browser_user_data/`, `static/csatolmanyok/`, `tests/`, `.opencode/`, `poc/`,
`tools/`, `docs/` (a dokumentáció), `deploy.ps1`, `KretaApp_Start.bat`. A `.dockerignore`
ugyanezt kizárja a képből is.
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
5. **ntfy ellenőrzés:** `curl -X POST http://saját szerver:8085/api/ntfy/test` → `{"ok":true,
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
| `/api/uzenetek` | üzenetlista (a teljes törzzsel és a helyi `olvasott` állapottal); olvasottság: `POST /api/uzenetek/<id>/olvasott {olvasott}`, tömegesen `POST /api/uzenetek/olvasott {olvasott, ids[]}` vagy `ids` nélkül `{olvasott, diak}` (üres `diak` = minden) |
| `/api/kifizetesek/export.xlsx` | **az egyenleg tételei**: *Elszámolás* (időszak/tanév, tételek összege, **ebből rendezve**, **fennálló egyenleg**, rögzített kifizetések, átlag) + *Tételes zsebpénz* (dátum/gyerek/típus/megnevezés/részletek/összeg + **Rendezve**, rendezés időszaka és dátuma, „Összesen / Ebből rendezve / Fennálló egyenleg” sorok) + *Kifizetések*; `?diak=&kezdo_datum=&zaro_datum=&tanev=` — dátumok nélkül a **teljes tanév** (`tanev=2026/2027`) vagy a **teljes előzmény** (`tanev=all`). A tételes lista ugyanaz, mint a felület `/api/statisztika` válasza. **Rendezett** = a tétel dátuma kifizetettként jelölt elszámolási időszakba esik (a `.csv` végpont visszafelé kompatibilisen megmaradt) |
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
- **Hitelesítés (Kaneo #16):** opcionális **basic auth** a `config.json` `AUTH` blokkjával
  (`ENABLED`, `USERNAME`, `PASSWORD_HASH`; a `/health` kivétel). Kikapcsolva a belső hálózat
  a védelmi vonal. Élesben **HTTPS/reverse proxy** javasolt, mert a basic auth önmagában
  nem titkosít.
- **Személyes adatok:** gyermeknevek, jegyek, üzenetek. Ezek a saját szerveren maradnak.
- **AI (Kaneo #61):** alapból **helyi Ollama**; `ALLOW_CLOUD=false` mellett csak
  magánhálózati AI-URL engedett. Az elemzés gombnyomásra fut, a naplóba nem kerül a
  gyerek szövege.
- **Belépési adatok:** a `config.json`-ban; a fájl a data köteten van,
  a konténerben nem olvasható kívülről, és nem kerül verziókövetésbe.
- **ntfy:** a nyilvános `ntfy.sh`-ra csak állapotinformáció megy; diáknév alapból nem.
  A topic neve működik „jelszóként" — ezért hosszú, véletlen.
- **Javasolt fejlesztés:** reverse proxy + HTTPS, ha a hálózat kiterjed.

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
├── app.py                 # Flask belépő: app, auth, szinkron/ütemező/ntfy/napló + re-export
├── views_pages.py         # / (dashboard)
├── views_events.py        # események, kész-jelölés, naptár-események
├── views_orarend.py       # órarend, saját órák, színek, ICS, naptár-nézet
├── views_messages.py      # üzenetek, olvasottság, saját megjegyzések
├── views_absences.py      # hiányzások / igazolások
├── views_stats.py         # tanévek, dashboard, tantárgyi átlagok
├── views_rewards.py       # zsebpénz-statisztika, kifizetés, naptár/ICS, üzenet-AI
├── kreta_exports.py       # PDF órarend, XLSX/CSV export, zsebpénz-számítási mag
├── kreta_paths.py         # útvonalak (KRETA_* env, data/ alapértelmezés)
├── kreta_db.py            # DB-kapcsolat, séma/migrációk, app_meta, futásnapló
├── kreta_settings.py      # config.json, verzió, órarend-színek
├── views_common.py        # blueprint-építő + közös request-segédek
├── kreta_playwright.py    # scraper
├── kreta_api.py           # mobil KRÉTA API kliens (böngésző nélkül)
├── kreta_api_sync.py      # API adatkör-lekérők, ablakok
├── kreta_sync.py          # SYNC_MODE, forrásnapló, fallback
├── kreta_shadow.py        # árnyék/ellenőrző mód
├── kreta_tanev.py         # tanév-számítás + séma-migráció (Kaneo #40)
├── kreta_sajat_orarend.py # kézi órarendi sorozatok + kivételek (Kaneo #55)
├── kreta_naptar.py        # Google Naptár-link + .ics generálás (Kaneo #47)
├── kreta_ai.py            # üzenet-AI kliens + JSON-validáció (Kaneo #61)
├── templates/index.html   # dashboard váza (modálok, fülek) — inline JS nélkül
├── static/js/core.js      # globális frontend-segédek (avatar, státuszsáv, formázás)
├── static/js/app-main.js  # a felület fő JS-e ($(document).ready blokk)
├── static/vendor/         # vendorolt frontend-függőségek (offline)
├── backup/kreta_backup.sh # napi mentés
├── tests/                 # automatikus tesztek + futtató
├── tools/                 # kaneo_ticket, api_snapshot, migrate_local_data, mobile_shot
├── data/                  # futásidejű adatok (NEM verziózott): DB, config.json, sync.log,
│                          #   api_tokens.json, scheduler_state.json, version.txt,
│                          #   browser_user_data/, csatolmanyok/
├── Dockerfile, docker-compose.yml, entrypoint.sh
├── deploy.ps1             # élesítő script
├── docs/                  # dokumentáció (DOKUMENTACIO, rendszerterv, AI-terv, összefoglalók)
└── README.md
```

A `data/` a v2.0.0-tól az alapértelmezett hely; a korábbi (projektgyökér) elrendezés
egy kiadásig még működik, figyelmeztetéssel. Átköltöztetés (az app álljon le):
`python tools/migrate_local_data.py --dry-run`, majd `python tools/migrate_local_data.py`
(visszaállítás: `--rollback`).

### 9.3. Tesztek

```bash
python tests/run_all.py            # mind (1411 ellenőrzés, 47 csomag)
python tests/run_all.py --fast     # böngésző nélkül (39 csomag, 1120 ell.)
python tests/run_all.py --browser  # Playwrightos (5 csomag, 152 ell.)
```

**CI (GitHub Actions, `.github/workflows/ci.yml`):** a **gyors** job (39 csomag) minden
pushra/PR-ra lefut; a **böngészős** job (5 csomag) csak `main` pushra, éjszakánként és
kézi indításra. A tesztek fixture-ökkel/fake klienssel dolgoznak, valódi KRÉTA-hívás nem
történik; a böngészős job hibája esetén a képernyőképek artifactként feltöltődnek.

**Determinisztikus időzítés (Kaneo #75):** a fix tesztdátumú, de a böngésző aktuális
idejétől függő csempe-ellenőrzéseket tartalmazó tesztek (`test_dashboard`,
`test_tanev_ui`) a Playwright `page.clock.install(time=…)`-ével a tesztdátumra rögzített
óra mellett futnak — így a másnapi (scheduled) CI-futásban nem csúszik ki a 7/10 napos
csempe-ablak. Új, dátumfüggő assertion-t tartalmazó böngészős teszt esetén ezt a mintát kell
követni (a szerver oldali `KRETA_TODAY` mellé a kliens óráját is rögzíteni).

Jelenleg **1272 automatikus ellenőrzés** negyvennégy csomagban: ütemező, részleges hiba/ntfy/napló,
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
visszalépés, gyermekkártyák, zárt accordion), **mobil elrendezés** (valódi böngészőben, 393 px;
a saját óra rögzítése és a naptárgombok is), **kézi órarend** (`sajat_orarend`: tanév/hét/egyedi
érvényesség, heti ismétlődés, kivétel, sorozat-törlés/módosítás, diák-szűrés), **naptárbejegyzés**
(Google-link + `.ics`, időzóna/emlékeztető, API 200/404), **üzenet-AI** (JSON-validáció,
fake HTTP-szerver, magánhálózati őr, 502/503, több VEVENT-es `.ics`), **auth** (basic auth
401/200, `/health` kivétel, statikus védelem), **DB-indexek** (indexlétezés, sémaverzió,
migráció előtti másolat), **zsebpénz CSV** (BOM, fejléc, szűrés). A tesztek izolált temp
könyvtárban futnak, a valódi adatokat nem érintik.

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
| Az üzenetlista csak előnézetet ad | az eAdmin `postaladaelemek/sajat` válasz `szoveg` mezője rövid és a sortörések nélkül | a mentéskor (és utólagos backfill-lel) a `postaladaelemek/<posta_id>` részletes választ használjuk, ami megőrzi a bekezdéseket (Kaneo #74) |
| Chromium az image-ben | nagyobb image | a Playwright fallback miatt szükséges, amíg az API hosszú távon nem bizonyít |
| CDN-függő frontend | internet nélkül nem indulna a felület | **megoldva (Kaneo #12):** minden CDN-fájl a `static/vendor/` alatt, a sablon csak helyi `url_for('static', ...)` hivatkozásokat használ |
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
| B4 | **Mobilos „Ma" nézet** — kompakt napi kártya | **KÉSZ (v2.1.0, Kaneo #9):** önálló **„Ma” fül** (nem dashboard-kártya) — mai órák, ma/holnapi házik és számonkérések pipával, friss jegyek, olvasatlan üzenetek; `/api/ma` | – |
| B5 | **Futástörténet a felületen** (a `sync_runs` már tárolja) | átlátható előzmények | 0,5–1 nap |
| B6 | **Üzenet-keresés (tartalomban is), helyi olvasott/olvasatlan (checkboxes tömeges váltással), zsebpénz Excel (`.xlsx`) export** | **KÉSZ (Kaneo #11 / #77):** `uzenetek.olvasott` + `POST /api/uzenetek/<id>/olvasott` és `POST /api/uzenetek/olvasott` (kijelöltekre vagy a teljes listára), olvasatlan számláló/szűrő, keresés az üzenet szövegében is; a migráció előtti üzenetek olvasottként indulnak; `GET /api/kifizetesek/export.xlsx` — **az egyenleg tételei** időszakra / teljes tanévre / teljes előzményre, tételes **rendezettség-jelöléssel** (*Rendezve*, rendezés időszaka/dátuma) és *Elszámolás* összegzéssel (ebből rendezve, fennálló egyenleg). *(A melléklet-dedupe a felhasználó döntése alapján elhagyva)* | – |

### C) Karbantarthatóság / kockázatok

| # | Lehetőség | Miért fontos | Becsült ráfordítás |
|---|---|---|---|
| C1 | **CDN-ek vendorolása** (`static/` alá) | internet nélkül most nem indul a felület | **KÉSZ (Kaneo #12):** Bootstrap 5.3.0, DataTables 1.13.6 + Responsive 2.5.0, FontAwesome 6.4.0 (webfontokkal), FullCalendar 6.1.8 + hu locale, jQuery 3.7.0 a `static/vendor/` alatt; a `test_karbantartas` ellenőrzi, hogy nincs külső URL és minden fájl megvan |
| C2 | **CI** (GitHub Actions) | automatikus ellenőrzés minden commitnál | **KÉSZ:** fast job minden pushra/PR-ra, browser job main pushra/éjszakánként; 888 ellenőrzés / 29 csomag |
| C3 | `app.py` / `index.html` szétbontása | karbantarthatóság | 3–5 nap |
| C4 | DB-migrációs keret + indexek | hosszú távú stabilitás | 1 nap |
| C5 | **Hitelesítés** (basic auth / reverse proxy) | gyerek-adatok védelme | 0,5–1 nap |
| C6 | Apróságok: `SyntaxWarning`, `config.json.example` vessző, halott `autoSyncAlert` | tisztaság | **KÉSZ (Kaneo #17):** nincs `SyntaxWarning`, a példa-config érvényes JSON, a halott blokk törölve; a `test_karbantartas` ellenőrzi |
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

| **v1.7.0** *(2026-11-03)* | **2026-11-03** | **Tanév-kezelés, 0–6. fázis:** új `kreta_tanev.py` (a tanév a rekord **dátumából** számítva, szept. 1. – aug. 31.; `KRETA_TODAY` / `KRETA_TANEV_KEZDO` env, tesztelhető `today=` paraméter; `teljesen_lekert` a törlési jogosultsághoz), `tanev` + `tanev_forras` oszlop a `esemenyek`/`uzenetek`/`hianyzasok`/`igazolasok`/`kifizetesek` táblán + `sync_runs.tanev` (**az órarend kivétel**), **csak UPDATE** backfill (ID-stabil, újraindítható) mindkét DDL-helyen. **Mentés tanév-tudatosan:** a teljes cserék törlése csak a letöltött tanévekre és az **ablakon belülre** hat, az arányos őr tanévenként számol, **üres batch soha nem töröl**; az igazolások **upsert** `kreta_id` kulcson; az API-ablak a **tanév első napjától** indul (a `MIN(stored)` megszűnt). **API:** `?tanev=` szűrő + `/api/tanevek`. **Felület:** tanév-választó a fejlécben (alap: aktuális tanév, „Összes tanév" opció; összes tanévnél nincs átlag); üres tanév súgó; a dátum-/hónapválasztók a tanév határain belül (#53); a dashboard-csempék tanévváltáskor azonnal frissülnek (#51). **Tanév-állapot (#43):** `tanevek` + `tanulo_tanev_uid` tábla; minden futás után a `TanuloAdatlap.TanevUid` ellenőrzése, változásnál **technikai zárás/nyitás adatlekérés nélkül** (a nevet a dátum adja); a fejlécben állapotjelzés, a választóban „lezárt” jelölés (a kézi záró gomb megszűnt). **Futásnapló:** a futás tanéve a `sync_runs.tanev`-be, tanévváltásnál naplósor + push; a `POST /api/kifizetes` a kifizetés tanévét az időszak kezdetéből írja be. **#42:** az igazolások adatvédelmi őrrel. **#46:** saját megjegyzések eseményhez/üzenethez (`kommentek` tábla, stabil tartalom-kulcs, `/api/kommentek`). Új tesztek: `test_tanev`, `test_tanev_migration`, `test_tanev_sync` (óra-bomba: 08-31 → 09-01 → 09-03), `test_tanev_api`, `test_tanev_state`, `test_tanev_ui`, `test_kommentek`; 867 ellenőrzés / 28 csomag |

| **v1.7.1** | **2026-11-03** | **Élesítés:** a v1.7.0 kódja került élesbe (`.\deploy.ps1 -Release v1.7.1`). A `main` fast-forward merge-dzsel szintre került, majd **GitHub Actions CI** indult: `.github/workflows/ci.yml` — **fast** job minden pushra/PR-ra (23 csomag), **browser** job csak `main` pushra, éjszakánként és kézi indításra (5 csomag); `tests/run_all.py --fast/--browser`; hiba esetén képernyőkép-artifact. Kódbeli funkcióváltozás nincs |
| **v1.7.2** *(2026-11-03, éles)* | **2026-11-03** | **Mobil fejléc:** a hosszú „Utolsó frissítés / Utolsó automatikus” szöveg tördel, nem csúszik ki; a szinkron állapota mobilon **egyetlen karcsú dinamikus sor** (zöld „Szinkronizálva: ma 21:33”, futáskor pörgő ikon, hiba esetén piros), a technikai részletek (ütemező, időablak, intervallum, következő/utolsó futás) **koppintásra nyíló ablakban**; asztali nézet változatlan. A `test_mobile_layout` a státuszsáv magasságát, a rejtett részleteket, a dinamikus állapotokat és a modált is ellenőrzi (a modál tartalma nem csúszik ki, a hosszú utolsó-futás sor tördel); 878 ellenőrzés / 28 csomag |
| **v1.8.0** *(2026-11-04, éles)* | **2026-11-04** | **Külső CDN-ek vendorolása (Kaneo #12):** a 12 külső hivatkozás helyett minden frontend-függőség a `static/vendor/` alatt (Bootstrap 5.3.0 CSS+JS, DataTables 1.13.6 + Responsive 2.5.0 CSS/JS, FontAwesome 6.4.0 CSS + webfontok, FullCalendar 6.1.8 + hu locale, jQuery 3.7.0); a `templates/index.html` csak `url_for('static', ...)` hivatkozásokat használ, így internet nélkül is indul. **Apróságok (Kaneo #17):** `SyntaxWarning` nincs (a modulok figyelmeztetés nélkül fordulnak), a `config.json.example` érvényes JSON (a hiányzó vessző pótolva), a halott `autoSyncAlert` blokk törölve a frontendből. Új `test_karbantartas` (vendor-fájlok + webfontok létezése, nincs külső URL, JSON-példa, nincs halott hivatkozás, nincs SyntaxWarning); **888 ellenőrzés / 29 csomag**. **Éles ellenőrzés (2026-11-04):** `/health` = `v1.8.0`, a vendorolt Bootstrap CSS, FontAwesome webfont és FullCalendar JS 200-at ad, a HTML-ben nincs CDN-hivatkozás |
| **v1.9.0** *(2026-11-05, éles)* | **2026-11-04** | **Saját órák (Kaneo #55):** `sajat_orarend` + `sajat_orarend_kivetel` táblák; a „Saját óra” gombbal gyermekenként rögzíthető szakkör/pluszfoglalkozás (nap, időpont, terem, megjegyzés), **teljes tanév / aktuális hét / egyedi időszak** érvényességgel; heti ismétlődés a naptárban, **egy alkalom** (kivétel) vagy a **teljes sorozat** törlése; a KRÉTA szinkron nem érinti. **Naptárbejegyzés (Kaneo #47/#60):** házi feladat / számonkérés és üzenet részleteinél **„Naptárba küldés”** — előre kitöltött Google Naptár esemény, egy kattintásos mentés, import/letöltés nélkül (az `.ics` végpont programozottan továbbra is elérhető); `CALENDAR` config (időzóna, emlékeztető, üzenet hossza), a timed események UTC-re konvertálva. Új tesztek: `test_sajat_orarend`, `test_naptar`; a mobil teszt a saját óra mentését és a naptárgombokat is ellenőrzi. **Futástörténet (Kaneo #10):** `/api/sync_runs` + a Rendszernapló fülön 20 futás táblázata és futásidő-sparkline. **Órarend-színek (Kaneo #56):** gyermekenkénti szín a configból vagy a „Színek” felületről (app_meta). **SuliHub arculat (Kaneo #62):** logó + favicon + név. **Egysoros fejléc (Kaneo #63):** kompakt navbar, egy státuszsor, tanévválasztó + Frissítés gomb egy sorban. **Finomítás (2026-11-04):** letisztított logó (gradiens + könyvjelző), gradiens hátterű fejléc; **brand bal sarokban (1,5× logó/név), tanév + státusz + Frissítés a jobb oldali sávban**; a saját óra színe az ablakban választható (a gyermek alap színétől eltérő) és a sorozat **módosítható**; a naptárgomb közvetlen **„Naptárba küldés”** (előre kitöltött Google esemény), ICS nélkül; a közvetlen Google API-s írás külön subtask (#70). **Üzenet-AI (Kaneo #61):** `kreta_ai.py` OpenAI-kompatibilis kliens (helyi Ollama), szigorú JSON-validáció, magánhálózati őr, csatolmány-szöveg (txt/pdf), API-végpontok (`/api/uzenet/<id>/ai`, `/api/naptar/ai/ics` — több VEVENT-es `.ics`); fake HTTP-szerveres teszt. **A felületi „AI elemzés” gombot a felhasználó kérésére kivettük, a háttér API-ként megmaradt.** **Backlog-kör (2026-11-04):** opcionális **basic auth** (#16), **DB-indexek + sémaverzió + migráció előtti másolat** (#15), **zsebpénz CSV export** (#11 része), **órarend ICS export** hét/hónap/félév/tanév időszakra (#73), a sárga zsebpénz-összeg sötétebb árnyalata (#72). **Üzenet-előnézet javítás (Kaneo #74):** a teljes szöveg a `postaladaelemek/<posta_id>` részletes válaszából jön, a bekezdések megmaradnak; `uzenetek.posta_id` oszlop + utólagos backfill (futásonként max. 20). **1045 ellenőrzés / 37 csomag** |
| **v1.9.1** *(nem élesedett önállóan — a v1.9.2 tartalmazza)* | **2026-11-05** | **Dashboard-visszatöltés (Kaneo #76):** az Áttekintés saját, szűrés nélküli adatforrást használ (`loadDashboardData`/`dashRaw`), és fülre visszatéréskor azonnal újraszámol — az eseménylistás szűrés után nem maradhat üres csempe/feed (F5 nélkül teljes kép). **CI-determinizmus (Kaneo #75):** a `test_dashboard` a böngésző óráját is rögzíti (`page.clock.install`), így a fix tesztdátum nem csúszik el a másnapi (scheduled) futásban — ez buktatta az éjszakai CI-t. Erősített tesztek (visszatéréskor csempe + feed tele). (A `v1.9.1` tag a `9826e2c` commiton maradt; a felhasználó a **v1.9.2**-vel élesített.) |
| **v1.9.2** *(2026-11-06, éles)* | **2026-11-06** | **ICS-duplikáció javítás (Kaneo #73, a felhasználó visszadobta):** az órarend-exportban minden esemény kétszer szerepelt — a szinkron az aktuális **és** a következő hetet is leéri, a generator pedig soronként csinált heti `RRULE` eseményt. Most az azonos heti minta (diák + tantárgy + nap + kezdés + időtartam) **egyetlen weekly VEVENT**, a legrégebbi előfordulás kezdetével; éles adaton ellenőrizve: 67 sor → 31 esemény. **Éles ellenőrzés (2026-11-06):** `/health` = `v1.9.2`; a tanév ICS exportban 109 egyedi heti minta, **0 duplikáció**. Tartalmazza a v1.9.1-re tervezett #76 dashboard- és #75 CI-fixet is. **1051 ellenőrzés / 37 csomag** |
| **v2.0.0** *(refaktor, kiadásra kész)* | **2026-11-06** | **KRÉ-14 monolit-bontás, viselkedésváltozás nélkül.** `app.py` 4 107 → ~1 180 sor: a DB-réteg (`kreta_db`), az útvonalak (`kreta_paths`), a beállítások (`kreta_settings`) és a közös nézet-segédek (`views_common`) kiemelve; a HTTP-réteg **8 prefix nélküli blueprintbe** (`views_pages/events/orarend/messages/absences/stats/rewards`, `kreta_exports`), a stateful mag (sync/ütemező/ntfy/napló) szándékosan az `app.py`-ban maradt (a tesztek monkeypatch-elik). A frontend inline scriptje `static/js/core.js` + `static/js/app-main.js` alá került (`?v=` cache-busttal). **Futásidejű adatok `data/` alá** (DB, config, napló, tokenek, böngészőprofil, csatolmányok) legacy-fallbackkel és `tools/migrate_local_data.py` migráló/rollback szkripttel. **Az audit után javítva:** a tanév-szűrős súlyozott átlag (F1), a `data/` auto-létrehozás (F2), a Docker-füstteszt teljes modulgráfja (F3). **Új őrök:** `tests/test_routes_contract.py` (42 rule rule+metódus rögzítése), `tools/api_snapshot.py` (17 végpont válasz-diff), `tests/test_data_dir.py` (útvonal-feloldás + migráció). **1177 ellenőrzés / 39 csomag** (fast 34/1025, browser 5/152) |
| **v2.1.0** *(éles 2026-11-07)* | **2026-11-07** | **Öt új funkció (Kaneo #78, #80, #85, #86):** **globális kereső** (Ctrl+K, `/api/kereses` — jegy, feljegyzés, házi, üzenet teljes törzs, hiányzás; találat a megfelelő nézetet nyitja), **„Milyen jegy kell?” kalkulátor** (`/api/jegy_kalkulator`, célátlag + a következő jegy súlya; egy jegy vagy több ötös, elérhetetlen cél), **UX csomag** (sötét mód `data-bs-theme`-tel + localStorage, nyomtatásbarát A4 fekvő heti órarend, kitűzött események a dashboardon `app_meta`-ban), **tantárgyi trend + hiányzás-mintázat** (`/api/atlagok` trend + romlás-figyelmeztetés, sparkline a táblázatban; `/api/hianyzas-mintazat` nap/óra/tantárgy bontás, a táblázatok alatt csukva). **Follow-upok (2026-11-07, Kaneo #9, #78, #85, #101, #110–#114):** **önálló „Ma” fül** (a dashboard-kártya helyett: mai órák, ma/holnapi házik pipával, friss jegyek, olvasatlan üzenetek), a kalkulátor **táblázatban kilistázza a tantárgy meglévő jegyeit**, **alapból üres a tantárgy-választó** (csak kiválasztás után tölt), **több várható jegyet** (eltérő súllyal) és **félévi céljegyet** kezel, a célátlagot **tantárgyanként menti**, és **mindig a teljes tanév** jegyállományát használja; a **kereső találatára kattintva az adott sor részletei** nyílnak meg, a **típus-címkék felirata/színe egyezik az Események füllel**; a **romló tantárgy sáv gyermeknevet és időszakot** is mutat, alatta **javuló tantárgyak** zöld sávja; mobilon az **értékeléseknél a jegy oszlop alapból látszik**; a **Ma fülről a felesleges szürke Frissítés gomb kikerült**; a **nyomtatott órarend fejléce** „SuliHub – Órarend – gyermek – hét”. Új tesztek: `test_jegy_kalkulator`, `test_kereses`, `test_kedvencek`, `test_trend`, `test_ma`; a `test_mobile_layout` a sötét módot, a látható jegy-oszlopot, a Ma fület és a nyomtatási fejlécet, a `test_dashboard` a kalkulátor jegytáblázatát és a több jegy/félévi cél UI-t is ellenőrzi. **1327 ellenőrzés / 44 csomag** (fast 39/1138, browser 5/189) |
| **v2.1.1** *(éles 2026-11-08)* | **2026-11-07** | **#117** a globális kereső (nagyító/Ctrl+K) megnyitásakor a **mező azonnal aktív** (`shown.bs.modal` + tartalék; a régi timer a megjelenés előtt futott). **#118** **átfogó sötét mód**: dashboard kártyacímek, táblázat-konténer, `.text-dark` szövegek, accordion-fejlécek, kiemelt sorok (ma/elkészült/olvasatlan), státuszsáv + verzió-jelvény, **FullCalendar** háttér/rács/cím, modálfejléc, csatolmány-badge/„Olvasás” gomb, Feljegyzés-badge; a **naptár-események szövegszíne** a háttér fényességéhez igazodik (`views_common.contrast_text` → `textColor`), így világos módban is jobb. Számított kontraszt-audit: 50 → **0 valódi** alacsony kontrasztú szöveg (9 fül + 6 modál + űrlapok). **1339 ellenőrzés / 44 csomag** (fast 39/1143, browser 5/196) |
| **v2.1.2** *(kiadásra kész)* | **2026-11-08** | **#120** az Iskolai események **szűrőpanelje alapból zárva** van, a fejlécére kattintva nyílik (a dashboard-csempéről érkezve is zárva marad; a szűrő továbbra is érvényesül). **#115** (Tailscale/WireGuard távoli elérés) és **#119** (SQLite vs MySQL/PostgreSQL) **elemzés** a jegyekben, kódváltozás nélkül. **1340 ellenőrzés / 44 csomag** (fast 39/1143, browser 5/197) |
| **v2.1.3** *(kiadásra kész)* | **2026-11-08** | **#121** a szűrőpanel a felső menüsor **alá** került (a menüsor nem ugrál a fülek között). **#82** A4-es **riportkártya PDF** félévi/tanévi bontásban, gyermekenként mentve (`riportkartyak` tábla + data kötet), visszamenőleges lista/letöltés; a hivatalos félévi jegy hiányát jelzi. **#83** **Excel exportok**: események (Jegyek/Feljegyzések/Házi feladatok) és hiányzások (Hiányzások/Igazolások) a felület szűrőivel. **#90** üzemeltetési ellenőrzések: havi **restore-teszt** (`tools/backup_restore_check.py`, manifest-tel) + éjszakai **élő füstteszt** (`tools/live_smoke.py`, CI job, secret nélkül kimarad). **1411 ellenőrzés / 47 csomag** (fast 42/1212, browser 5/199) |

---

## 14. Kapcsolódó dokumentumok

| Fájl | Tartalom |
|---|---|
| `README.md` | Rövid üzemeltetői útmutató, telepítés, konfiguráció |
| `docs/rendszerterv.md` | Eredeti követelményjegyzék és rendszerterv (történeti) |
| `docs/AI-ELEMZES-TERV.md` | Üzenet-AI (LLM) integráció terve |
| `docs/osszefoglalo/` | Munkamenet-összefoglalók (dátumozott) — pl. a KRÉ-14 refaktoré |
| `tests/README.md` | A tesztek leírása és futtatása |
| `docs/DOKUMENTACIO.md` | **Ez a dokumentum** — teljes rendszerleírás |

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
| Mappa szerkezet / dokumentum-fájlok helye | README „Mappa szerkezet", 9.1. és 14. pont |
| Megszűnő korlát vagy új ismert korlát | 10. pont |

A frissítés a fejlesztő (illetve a fejlesztést végző asszisztens) felelőssége; a
munkamenet-memória (`~/.config/opencode/memory/kreta.md`) is rögzíti ezt a szabályt.
