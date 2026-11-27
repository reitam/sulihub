# KRÉTA Adatbázis Áttekintő — Rendszerdokumentáció

| | |
|---|---|
| **Dokumentum verziója** | 1.30 |
| **A rendszer verziója** | v2.8.0 |
| **Utolsó frissítés** | 2026-11-27 |

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
| **Értékelések** | Tantárgy, érdemjegy, dátum, tanár, típus, témakör, **súlyszázalék** („100%-os súllyal számít az átlagba”). A súly a **mobil API** `SulySzazalekErteke` mezőjéből jön. A felület a jegy mellett kis `%`-jelvényként mutatja, tooltippel. A **Magatartás** és a **Szorgalom** két külön sor (0 számértékkel), így az átlagot nem befolyásolják |
| **Feljegyzések** | Dicséretek, megrovások, hiányok, egyéb bejegyzések |
| **Házi feladatok** | Tantárgy, tanár, leírás, rögzítés, határidő |
| **Bejelentett számonkérések** | Tantárgy, mód, téma, bejelentés és a számonkérés napja |
| **Hiányzások / késések** | Dátum, **aznap hányadik óra** (1 sor = 1 tanóra), tantárgy, téma, mulasztás típusa (késésnél percek), igazolt/igazolatlan, igazolás típusa, rögzítés dátuma. A „tanórai célú” jelző is tárolva van, de a felületen nem jelenik meg |
| **Igazolások** | Érvényesség kezdete–vége, igazolás típusa, megjegyzés |
| **Heti órarend** | Aktuális és következő hét: tanár, terem, időpont, esetleg egész napos esemény; **fogadóórák** is |
| **e-Ügyintézés üzenetek** | Beérkezett üzenetek (csak az újak) a **teljes szöveggel és bekezdésekkel** — a lista csak előnézetet ad, ezért a mentéskor a `postaladaelemek/<posta_id>` részletes válasz kerül felhasználásra; **a csatolmányokkal együtt** — a fájl API-ból töltődik le (`dokumentumok/uzenetek/{id}` → `files.e-kreta.hu` nonce URL), böngésző nélkül |

### 2.3. Felület (fő nézetek)

| Fül | Mire való |
|---|---|
| **Áttekintés** | Nyitó dashboard: **6 kattintható csempe** — **következő házi feladatok** (10 nap), **következő számonkérések** (10 nap), **új jegyek** (10 nap), **új üzenetek** (10 nap), **igazolatlan hiányzás** (óra), **kifizetetlen zsebpénz** (kiegészítő felirat nélkül) —, valamint **„Tanulmányi átlag”** szekció **gyermekenkénti kártyákkal**: **monogramos avatar**, név, diszkrét jegyszám-badge, nagy tanulmányi átlag és egyenleg. A **gyermekszűrő chipek** és az **„Események listája”** gomb a **fül-sáv alatt, az összes csempe felett** vannak (a szűrő a csempékre is vonatkozik). A tanév/súlyozás magyarázata **egyszer, a szakasz fejlécében** van. **Kompakt, 3×2 elrendezés**, egységes csempesablon, **látható kerettel**; széles kijelzőn a dashboard **középre igazított (max. 1200 px)**, a két szélen szimmetrikus üres sávval. **Színlogika:** 0 értéknél semleges (szürke) vagy „rendben” (zöld), csak > 0 esetén élénk szín. Az alsó sávban **2 hasáb**: **„Figyelmet igénylő bejegyzések”** (utolsó **10** feljegyzés típus-badge-dzsel: piros figyelmeztetés, zöld dicséret, szürke felszereléshiány) és **„Legutóbbi jegyek”** (utolsó **10** jegy színes jegy-körrel). A csempére kattintva a megfelelő (szűrt) nézet nyílik |
| **Iskolai események** | Szűrhető, kereshető táblázat: jegyek (a jegy mellett a **súlyszázalék** jelvénye), feljegyzések, házik, számonkérések. Szűrők: gyermek (chip is), típus, tantárgy, időszak, dátumtartomány — **bejegyzés kelte és határidő** (utóbbit az Áttekintés csempéi is beállítják: következő házik / számonkérések), gyorsszűrők; a **tantárgy-szűrő kis/nagybetű-független** (a KRÉTA írásmódja nem egységes, pl. „Angol nyelv" / „angol nyelv" — ), a választóban tantárgyanként egy tétel; a **szűrőpanel alapból zárva** van, a fejlécére kattintva nyílik; "Vissza az áttekintésre" gomb. **Excel export** a jelenlegi szűrőkkel (Jegyek / Feljegyzések / Házi feladatok — ). Soronként **saját megjegyzés** fűzhető |
| **Hiányzások** | Hiányzások és késések havi bontásban: **5 összesítő kártya** (összes hiányzás óra, igazolt óra, igazolatlan óra, késés db/perc, igazolás db) + részletes tábla és igazolás-lista. Alapból a **teljes előzmény** látszik, a havi bontás hónapválasztóval / „Aktuális hónap" gombbal. **Excel export** (Hiányzások / Igazolások — ) |
| **Heti órarend** | Idősávos heti nézet, gyermekszínekkel; **A4 PDF export**; **kézi „Saját óra”** tételek (szakkör, plusz foglalkozás) tanévre / hétre / egyedi időszakra, egy alkalom vagy a teljes sorozat törlésével; **ICS export** hét / hónap / félév / tanév időszakra |
| **Feladatok naptár nézet** | Házik és számonkérések határidő szerint, színkódolva; a részletek ablakból **közvetlen „Naptárba küldés”** (előre kitöltött Google Naptár esemény, egy kattintásos mentés). A részletek modál **ugyanaz, mint az esemény-táblában** (tagolt hero + meta + leírás) — |
| **Beérkezett üzenetek** | Üzenetek olvasása (a **teljes törzs** a részletes API-válaszból, a sortörések megőrzésével — ), **szöveges keresés a tárgyban, a feladóban és az üzenet tartalmában**, **helyi olvasott/olvasatlan állapot** (olvasatlan számláló a fülön, félkövér + kék pötty a listában, Mind/Olvasatlan/Olvasott gyorsszűrő, megnyitáskor automatikus olvasottnak jelölés + kézi oda-vissza váltás; **checkboxos kijelölés** soronként és „mind” a fejlécben, a kijelölteken vagy a teljes listán **egylépéses olvasott/olvasatlan** váltás; a KRÉTA felé nem ír vissza — ), csatolmányok letöltése; az üzenethez is fűzhető **saját megjegyzés**, valamint **„Naptárba küldés”** Google Naptárba |
| **Statisztika & Zsebpénz** | Havi jegyeloszlás, átlag, dicséret/hiány mutatók, elszámolás; **az egyenleg tételeinek Excel (`.xlsx`) exportja** — *kiválasztott időszakra*, *teljes tanévre* vagy *teljes előzményre*, tételes **pénzügyi rendezettség-jelöléssel**; **aktuális bizonyítvány PDF** félévi/tanévi bontásban, mentés nélkül |
| **Rendszernapló** | A szinkronizációk naplója, hibák, előzmények; **legutóbbi 20 futás** táblázata (indult, futásidő, státusz, új esemény, hibás diák, tanév) és **futásidő-sparkline** |

**Szűrőfüggetlen dashboard:** az Áttekintés a saját, szűrés nélküli
adatforrását tölti be (`/api/esemenyek` csak gyermek- és tanév-szűrővel, `/api/uzenetek`),
ezért az eseménylistán beállított típus/tantárgy szűrő **nem tud kiüresedni** a csempékben
és a feedekben; fülre visszatéréskor a panelek azonnal újraszámolódnak, majd frissülnek —
F5 nem szükséges.

**Fejléc:** bal sarokban az **új SuliHub logó + név + verzióbadge**
(112×52 px embléma, 2,1 rem név, a logó a fejléc hátterével összeolvadva); a jobb oldali
sávban a **tanévválasztó**, a **szinkron
státuszsáv** („Frissítve: tegnap 21:16 (kézi)”) és a **Frissítés** gomb. A technikai
részletek (ütemező, időablak, következő futás, utolsó automatikus futás) koppintásra
nyíló ablakban vannak. Asztalon a fejléc 87 px magas, gradiens háttérrel és finom
árnyékkal; mobilon a brand felül, alatta a státusz, majd a tanév + Frissítés.

**Fülek:** semleges (sötétszürke) ikonok és feliratok; **csak az aktív fület** emeli ki a
felület (kék szöveg/ikon + alsó kék vonal). A fülek semleges szürkék; csak az aktív fül kék.

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
- a szűrők teljes szélességűek, a dátumtartomány egymás alatt, **felirattal**
 („Bejegyzés kelte” / „Határidő”), mert a beépített címkék mobilon rejtve vannak,
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
| Sikeres szinkron **új információval** | „SuliHub – új adatok" + a futás **deltája**: csak a most beérkezett tételek (jegyek súlyozással, házik, dolgozatok, feljegyzések, hiányzások, igazolások, üzenetek), a napi digesttel azonos formában, diákonként csoportosítva. A nap korábbi eseményei és a „Holnap esedékes" blokk **nem** ismétlődnek (azok az esti összefoglalóban vannak) |
| Sikeres szinkron új információ nélkül | **nincs értesítés** (a fejléc státuszsávja és a Rendszernapló mutatja) |
| Részleges hiba | „részleges hiba", a hibás diák(ok) és az új adatok részletei — egy üzenet |
| Hiba | „HIBA", magas prioritás; token-lejárat / ismétlődő hiba esetén a health-riasztás **ugyanebben az egy** üzenetben |
| Elavult adat (12 óránál régebbi) | „elavult adatok", max. 6 óránként egyszer |
| Leállított futás | nincs értesítés (szándékosan) |

Az értesítések az **ntfy** szolgáltatáson keresztül mennek a telefonra. **Futásonként
legfeljebb egy** üzenet megy ki. Diáknevek alapból **nem** kerülnek ki; a részletes
bontás a felületen és a naplóban látható. Az üzenettörzs max. ~4 KB; hosszabb
tartalomnál a végén „… (a többi részlet a felületen)” áll.

#### 2.5.1. Esti összefoglaló (KRÉ-8)

Minden nap a beállított idő után (**alap: 19:30**) **gyermekenként egy üzenet** megy ki a
szülőnek arról, **mi történt aznap** — órarend nélkül:

| Szekció | Tartalom |
|---|---|
| Jegyek | a ma rögzített értékelések: tantárgy, jegy, **súlyszázalék**, típus/mód, téma, tanár |
| Házi feladat | a ma feladott házik: tantárgy, rövid leírás, **határidő** (és ha kész) |
| Dolgozatok | a ma bejelentett számonkérések: tantárgy, mód, téma, **a dolgozat napja** |
| Feljegyzés | a mai bejegyzések (dicséret/megrovás/hiány), rövid tartalommal |
| Hiányzás | a mai mulasztások: óra, tantárgy, késés vagy hiányzás, **igazolt / IGAZOLATLAN** |
| Igazolás | a ma kezdődő igazolások (típus, érvényesség, megjegyzés) |
| Üzenetek | a ma érkezett üzenetek (feladó + tárgy), és az olvasatlanok száma |
| **Holnap esedékes** | a holnapi határidős házik (a kész kimarad) és dolgozatok |

- **Eseménytelen napon is megy** egy rövid üzenet: „Ma nem történt esemény, holnapra nincs
 esedékes feladat."
- Naponta **legfeljebb egyszer** gyermekenként (`app_meta`: `digest_sent:<diák>`), 23 óra
 után már nem pótolja.
- **A küldés ideje a configban van** (`config.json → DIGEST.TIME`, alap `19:30`), és a
 felületen is állítható (a mentés `app_meta`-ba kerül, ami felülírja a configot).
 A `config.json DIGEST` blokk csak alapérték, így a jelszavakhoz nem nyúlunk.
- **Manuális összefoglaló („Összefoglaló most”):** a fejléc 🔔 ikonjából bármikor kérhető
 egy összefoglaló **az utolsó automatikus digest óta** (a kimaradt napokat is hozza;
 ha még nem volt automata, a mai napot). Ez **nem befolyásolja** az automatikus digest
 időpontját és tartalmát: a napi jelölő (`digest_sent`) és az utolsó automata időpontja
 (`digest_last_at:<diák>`) változatlan marad — elsősorban tesztelési/kérési célra van.
- A beállítás a fejléc **harang** ikonjából nyílik (ki/be, időpont, név az üzenetben,
 **Összefoglaló most**); a modal mutatja az utolsó automatikus küldés idejét is.
 Ha nincs ntfy topic, a modal jelzi, hogy nem tud kimegni.

**Beállítás — két helyen, az env az erősebb:**

```jsonc
// config.json (a data köteten; lokálisan is ez a kényelmes)
"NTFY": {
 "_comment": "CSA K akkor él, ha a.env-ben nincs NTFY_TOPIC (az env erősebb)",
 "TOPIC": "kreta-3f9c1a7b5e2d4c60", // üresen nincs értesítés
 "URL": "https://ntfy.sh", // saját ntfy szerver is lehet
 "NOTIFY_NEW": true, // új információ esetén push (a régi NOTIFY_SUCCESS is elfogadott)
 "INCLUDE_NAMES": false // diáknevek a push-ban (alapból nem)
}
```

> A JSON nem enged megjegyzést, ezért a `_comment` kulcs a „komment” (az app nem
> használja). Ha a `.env`-ben is van `NTFY_TOPIC`, induláskor a konzol kiírja, hogy a
> config.json topicját nem használja.

A szerveren a `NTFY_TOPIC` (stb.) a projekt `.env` fájljában él (a compose a `.env`-et
interpolációhoz betölti); ha ott be van állítva, az **felülírja** a config.json értékét. A topic **neve maga a cím**:
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
- **Tanév-választó a fejlécben (, 5. fázis):** alapból az **aktuális tanév**
 (szept. 1. – aug. 31.) van kiválasztva, „Összes tanév" opcióval. A választó az
 **eseményeket, a hiányzásokat, az átlagokat, a statisztikát és a dashboardot** szűri
 (`?tanev=`); az **üzenetek és az órarend tudatosan tanév-független**. **„Összes tanév"
 módban az átlag nem értelmezhető** — a felület ilyenkor nem mutat átlagot, hanem
 tanévválasztásra kér. Üres tanévnél az adott fül rövid súgót jelenít meg.
- **Dátumválasztók a tanévhez igazítva:** ha egy tanév van kiválasztva, a
 bejegyzés-dátum, a zsebpénz-időszak és a hiányzás-hónap választó `min`/`max` korlátot
 kap a tanév határaira; a tanéven kívüli érték (begépelve is) törlődik. „Összes
 tanévnél" nincs korlát. A gyorsgombok (ma / ez a hónap / előző hónap) intervallumát
 a tanév határai közé vágja.
- **Tanév-állapot: automatikus zárás/nyitás a `TanevUid` alapján:** minden
 szinkronfutás után diákonként ellenőrizzük a `TanuloAdatlap.TanevUid`-t. Ha megváltozik,
 a nyitott tanévet **technikailag lezárjuk** (`tanevek.allapot = 'lezart'`, `lezarva_at`),
 és megnyitjuk az újat — **adatot visszamenőleg nem kérünk le** (a KRÉTA API a korábbi
 tanéveket nem adja vissza). A tanév neve a dátumból generált címke, mert a KRÉTA a diák
 scope-ban csak a nyers `TanevUid`-t adja (a `/Sajat/Tanevek` és `/Sajat/Tanulo` 403);
 a `TanevUid` a `tanulo_tanev_uid` táblában diákonként tárolva. A lezárás **nem tilt le
 semmit** (a régi tanévhez tartozó kifizetés/megjegyzés továbbra is rögzíthető), tisztán
 állapot/audit; a fejlécben állapotjelzés, a tanév-választóban „lezárt” jelölés látszik.
 * **Mérés (2026-11-03, több diák):** a KRÉTA mobil API a **korábbi tanévekre 0 sort ad**
 (jegy/hiányzás/igazolás, teljes tanévre kérve is), csak az **aktuális tanévet**
 szolgálja ki — a dátum-szűrő közben működik (kontroll ablakok). Ezért nincs
 visszamenőleges lekérés; a régi tanévek adata **pótolhatatlan**, ezért a napi backup
 és a „korábbi tanévet soha nem törlünk” szabály kritikus.
 * **Zárt tanév archívuma:** a zárás után egyszeri ZIP készül a data
 köteten (`tanev_archivum/<év>.zip`): táblánként JSON/CSV, Excel, PDF-bizonyítványok,
 manifest + SHA-256; ismételt zárásnál nem duplikál (lásd 3.2.5).
- **A kifizetetlen zsebpénz a dashboardon** a **kiválasztott tanév** egyenlege mínusz a
 `kifizetesek` táblában **kifizetettnek jelölt időszakok** összege (a maradék jelenik meg).
 A `POST /api/kifizetes` a kifizetés tanévét az időszak **kezdő dátumából** írja be, így a
 frissen kifizetett összeg azonnal levonódik. A `GET /api/dashboard` ezt diákonként és
 összesen is visszaadja, a diákonkénti tanulmányi átlaggal és az igazolatlan órák számával együtt.
- A kifizetés ténye rögzíthető („KIFIZETVE"), így az elszámolás nyomon követhető.
- A modul **gyermekenként** ki-/bekapcsolható. A példában két gyermek aktív,
 a harmadiknál kikapcsolva. Kikapcsolt diáknál a **statisztika akkor is működik**
 (jegyeloszlás, átlag, viselkedési mutatók), csak a **pénz-kártya rejtve** van, és helyette
 egy figyelmeztető sáv jelzi, hogy a zsebpénz modul nincs engedélyezve.

---

### 2.7. Saját órák és naptárbejegyzés

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


### 2.8. Órarend ICS export

A Heti órarend fülön az **„ICS export”** menüben választható időszak: **aktuális hét,
aktuális hónap, félév, teljes tanév**. A kiválasztott gyermek (vagy az összes) heti
órarendi mintái **ismétlődő VEVENT**-ként (`RRULE:FREQ=WEEKLY`) kerülnek a `.ics`-be,
a megfelelő időszakra szűkítve; a terem `LOCATION`, a tanár `DESCRIPTION` mezőbe kerül.
A fájl Google Naptárba/Apple/Outlookba importálható. A félév szeptember–január,
illetve február–augusztus; a tanév szeptember 1. – augusztus 31. Az azonos heti minta
(diák + tantárgy + nap + kezdés + időtartam) **egyetlen VEVENT** — a szinkron az aktuális
és a következő hetet is leéri, és a tábla sorait nem vonnánk össze, minden kétszer
kerülne az exportba.

### 2.9. Globális kereső

**Ctrl+K** (mobilon a nagyító gomb) → kereső ablak; a keresőmező **azonnal aktív**
(oda kerül a fókusz, nem kell külön rákattintani). Egyszerre keres a **jegyekben,
feljegyzésekben, házikban/számonkérésekben, üzenetekben (a teljes törzsben) és
hiányzásokban**. Legfeljebb 20 találat, dátum szerint csökkenő sorrendben. A találat
sorára kattintva **az adott sor részletei nyílnak meg** (esemény → részletek modál,
üzenet → üzenet-ablak, hiányzás → hiányzás részletei); ha az adat időközben elfogyott,
a megfelelő szűrt nézet nyílik. A találat-típusok **felirata és színe ugyanaz, mint az
Események fülön** (Értékelés, Feljegyzés, Házi feladat, Bejelentett számonkérés). A keresés
a `/api/kereses` végponton fut (LIKE, escape-elt speciális karakterekkel), tipikusan <10 ms.
A találatlista **↑/↓ billentyűkkel** navigálható, **Enter** megnyitja,
**Esc** bezárja; az utolsó **5 keresés** a `localStorage`-ban marad; a megnyitott találat
sora az eseménylistában **rövid sárga kiemelést** kap. Nagyobb adatbázison a keresés
**FTS5 trigram indexet** használ (lásd 2.17), a LIKE marad fallbacknek.

### 2.10. „Milyen jegy kell?” kalkulátor

A Statisztika fülön tantárgy + **célátlag** + a **várható jegyek** (súly + opcionális
jegy) alapján megmondja, **milyen jegy(ek) kellenek**: egy jegy (1–5) vagy több ötös,
illetve hogy a cél már nem érhető el. A tantárgy-választó **alapból üres** (a jegyek
listája és az eredmény csak kiválasztás után jelenik meg), és üres elemre vissza lehet
állni. A kiválasztott tantárgy **meglévő jegyeit** a kártya táblázatban listázza
(dátum, jegy, súly).

**Több várható jegy:** a „további jegy” gombbal további sorok adhatók,
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

### 2.11. UX csomag: sötét mód, nyomtatás

- **Sötét mód:** fejléc-gomb, Bootstrap 5.3 `data-bs-theme`; a választás `localStorage`-ban marad.
 A körvonalas vezérlők (gyermek-chipek, Nyomtatás) sötét módban is olvasható színt kapnak;
 a dashboard kártyacímek, a táblázat-konténer, a kiemelt sorok (ma/elkészült/olvasatlan),
 az accordion-fejlécek, a státuszsáv, a modálfejlécek és a **naptár (FullCalendar)**
 háttere/szövege is a sötét témához igazodik. A naptár-események szövegszíne a
 háttérszínhez számolódik (`textColor`), így a pasztell és a sötét színeken is olvasható.
- **Nyomtatásbarát heti órarend:** a Heti órarend fülön **„Nyomtatás”** — A4 fekvő, nagy
 betűs, színes táblázat (diákonként, nap × időpont), böngésző-nyomtatással. A nyomtatási
 fejléc (a dokumentum címe) **„SuliHub – Órarend – gyermek – hétfő–vasárnap”** formátumú.

### 2.12. Tantárgyi trend és hiányzás-mintázat

A tantárgyi átlagok táblázat **Trend** oszlopa a havi átlagok **sparkline-ját** és az utolsó
két hónap különbségét mutatja (zöld/javul, piros/romlik). Az Áttekintés tetején
**két lenyitható sáv** jelzi a **romló** tantárgyakat (≤ -0,5) és a **javulókat** (≥ +0,5)
**gyermeknévenként és az érintett időszakkal** (pl. „Teszt Elek – Irodalom
(2026. szeptember → 2026. október, -2)”). Összecsukva csak a darabszám és a tantárgynevek
látszanak; a sáv fejlécére kattintva **görgethető lista** nyílik: asztalon **helyben**,
mobilon **teljes képernyőn**; a fejre kattintva vagy `Esc`-cel záródik. A `/api/atlagok`
válasza tantárgyanként `trend`-et, valamint gyermekenkénti `figyelmeztetesek` és
`javulasok` listát ad (a `diak` és a két hónap mezőjével). A Hiányzások fülön a
**Hiányzás-mintázat** kártya (a táblázatok **alatt, alapból csukva**) bontja a
hiányzásokat **nap, órasorszám és tantárgy** szerint (`/api/hianyzas-mintazat`), a
tanév- és diák-szűrőt követve.

### 2.13. „Ma” önálló nézet

Az **Áttekintés utáni „Ma” fül** (a dashboard-kártyát a felhasználó elutasította) napi
összefoglalót ad: **mai órák** (időpont, terem, tanár), **ma és holnap esedékes** házik és
számonkérések pipával (kattintás → kész jelölés); a **sorra kattintva részletek modál**
nyílik (tantárgy, téma/leírás, tanár, határidő, állapot). Ugyanez a heti nézet
határidő-sorain is működik. **Friss jegyek** (7 nap) és **olvasatlan
üzenetek** (kattintás → üzenet-ablak). Saját gyermek-chipek; a fül megnyitásakor és
gyermekváltáskor automatikusan frissül (nincs külön Frissítés gomb), a fejléc
diák-szűrőjét követi. A napi nézet **Holnap** kártyát kap (csak a
holnapi órák; a holnapi határidők a meglévő **„Ma és holnap esedékes”** kártyán vannak),
valamint **Igazolandó**
kártyát (a még nem igazolt hiányzások/késések, „X napja” jelvénnyel). A fülön belüli **Ma / Hét** szegmentált kapcsoló
választja a napi kártyákat vagy a **heti napkártyás nézetet**: hétfő–péntek, **kétoszlopos,
középre igazított rácsban** (max. 780 px, nem a képernyő teljes szélessége), a napkártyák
színe az eseményekhez igazodik (óra = kék, határidő = borostyán, vegyes = lila). Páratlan
számú kártyánál az utolsó a két oszlophoz képest **középre** kerül. Ha a
hétvégére (szombat/vasárnap) is van órarendi óra vagy határidő (pl. munkaszombat), az a
nap is **kártyát kap**, és a fejléc ilyenkor „hétfő–vasárnap". A havi nézet a
felhasználó döntése alapján **nincs**. Adatforrás: `/api/ma?diak=&datum=`.
A **részletek modál** mindenhonnan (naptár, Események táblázat, kereső, Ma fül,
hiányzások) ugyanazt a **tagolt elrendezést** használja: felül a tantárgy + típus- és
állapotjelvény, valamint a diák és a határidő; alatta kétoszlopos, tömör
címke–érték sorok; végül a leírás külön blokkban. Az **aktív** állapot zöld jelvényt kap.
Mobilon az adatsorok egy oszlopra törnek, sötét módban is olvashatók.

### 2.14. Aktuális bizonyítvány PDF

A Statisztika fülön **gyermek + időszak** (félév / teljes tanév) választással **A4-es PDF
bizonyítvány** generálható **közvetlenül, mentés nélkül** (`GET /api/riportkartya/export_pdf`);
a böngésző nyitja meg, onnan nyomtatható/menthető. A felületi kártya és a PDF fejléce is
**„Aktuális bizonyítvány”**; a fő cím a tanévet és az időszakot is mutatja (pl. „SuliHub -
Teszt Elek - 2026/2027 1. félév”). A PDF **dísz-bizonyítvány** kivitelű: arany duplakeret,
sarokdíszek, talpas (serif) címek, pecsét, egységes arany–tengerészkék színvilág. Tartalma:
összegzés (tanulmányi átlag, jegyszám, hiányzás/igazolatlan, késés), **tantárgyi táblázat**
(tantárgy, jegyek, súlyozott átlag) és – ha van ilyen – **magatartás/szorgalom** értékelés.
A **zsebpénz-egyenleg csak akkor szerepel**, ha a diákra engedélyezett a zsebpénz modul
(`enable_rewards`); kikapcsolva a sor kimarad. A „Jegyek” oszlop **jegyenként összesít**,
dátum nélkül (pl. „Jeles(5) - 3 db; Jó(4) - 2 db”), nincs Db oszlop.
**Feljegyzés-szekció nincs**, és nincs mentett bizonyítvány-előzmény (a felhasználó döntése:
mindig újragenerálható).

A **hivatalos félévi/év végi osztályzat** a KRÉTA API-ból nem érhető el (félévkor sem
kérdezhető le), ezért a riport a jegyekből számolt, KRÉTA-súlyozású átlagot mutatja, és
ezt a PDF láblécében jelzi is. Az időszak: félév = tanév kezdete – jan. 31., tanév =
szept. 1. – aug. 31.

### 2.15. Tanulmányi Excel exportok

- **Iskolai események** fül: **Excel export** a jelenlegi szűrőkkel (diák, tanév,
 bejegyzés-dátumtartomány) → `GET /api/esemenyek/export.xlsx`, munkalapok: **Jegyek**
 (diák, tantárgy, jegy, súly%, mód, téma, tanár, dátum, tanév), **Feljegyzések**,
 **Házi feladatok** (a bejelentett számonkérésekkel; állapot: elkészítve/aktív).
- **Hiányzások** fül: `GET /api/hianyzasok/export.xlsx` → **Hiányzások** (dátum, óra,
 tantárgy, téma, tanár, típus, igazolt, késés perc, tanév) és **Igazolások** (kezdet,
 vég, típus, megjegyzés) munkalapok; az igazolásoknál az időszakkal **átfedő** sorok
 kerülnek bele.
- A számok/sorok a felület szűrőivel egyeznek; a fájlok `.xlsx` formátumúak (openpyxl).

### 2.16. Keresés: FTS5 index

A `kreta_db.ensure_fts_schema` **FTS5 virtuális táblákat** hoz létre
(`esemenyek_fts`, `uzenetek_fts`) **trigram tokenizálóval**, hogy a részszöveges
(infix) keresés is működjön; a triggerek az `esemenyek`/`uzenetek` beszúrás/ módosítás/
törlés esetén szinkronban tartják, induláskor szükség esetén **rebuild**. A kereső
3+ karakteres query-nél az FTS jelölteket használja (Unicode-tudatos; a LIKE-ra nem
szűr rá, így a nagybetűs ékezetes találat is megvan), rövid query-nél vagy FTS-hibánál
a LIKE-út marad. A találatok a LIKE-kal egyező halmazt adnak a kisbetűs esetekben
(teszt: `test_kereses` 5b). Az indexelt dokumentumok számát a `_docsize`
alapján ellenőrzi, és ha elavult (pl. a triggerek előtti sorok), **rebuildel**.

### 2.17. Szinkron-egészség riasztás

A szinkron befejezésekor az `app_meta` `sync_health` állapota frissül:
- **3 egymást követő hibás futás** → magas prioritású (5) ntfy riasztás, legfeljebb
 6 óránként egyszer;
- **token-lejárat / refresh hiba** → külön üzenet: „újra be kell jelentkezni”
 (4-es prioritás, 6 órás throttle). A felismerés **a sikertelen adatkörök okából**
 történik (`401`/`403`/`invalid_grant`/login hiba); a napló „tárolt tokenből” /
 „refresh tokennel” info-sorai **nem** számítanak token hibának ( utáni
 javítás, 2026-11-18);
- siker után a számláló nullázódik;
- a `/api/scheduler/status` `health` mezőt ad (`consecutive_errors`, `last_error_type`,
 `last_run_age_hours`), a fejléc státuszsávja is jelzi („Ismétlődő szinkronhiba” /
 „KRÉTA belépés lejárt”). A státuszsáv tooltipje és a részletek modál elmagyarázza,
 hogy a következő szinkron **automatikusan** belép a config.json-ban megadott
 felhasználónévvel/jelszóval. A health-riasztás **nem külön push**, hanem a futás
 egyetlen üzenetébe kerül. A régi „elavult adat” riasztás
 (`STALE_ALERT_HOURS`) változatlanul megmarad.

### 2.18. Adatminőség- és integritás-riport

`tools/data_quality_report.py` — **csak olvas** (`mode=ro`): integrity_check, DB-méret,
tábla-sorszámok, utolsó szinkron, duplikált esemény/hiányzás, hiányzó csatolmányfájlok,
üres kötelező mezők, árva megjegyzések. Heti cronra javasolt; hibánál/figyelmeztetésnél
ntfy-t küld, `--json` gépi kimenet. Nem módosít semmit.

### 2.19. Teljesítmény-mérés

`tests/test_performance.py` 5 000 esemény + 500 üzenet fixture-ön méri a `/api/ma`,
`/api/kereses`, `/api/statisztika`, `/api/atlagok` medián válaszidejét (3 futás);
a küszöb `PERF_THRESHOLD_MS` (alap **500 ms**), a fast csomag része. A mért értékek
a kimenetben látszanak; a küszöb túllépése piros tesztet ad.

### 2.20. DB-migrációs lánc

A `kreta_db`-ben **`MIGRATIONS = [(4, fn), …]`** verziózott lánc fut a
`schema_version` alapján, idempotensen; 0-nál újabb verzióról **`.bak` mentés** készül.
A v4 a FTS5 indexet hozza létre, a **v5** a `letrehozva` (first seen) oszlopokat
(2.23), a **v6** a már v5-ös DB-knél a régi, éjfélre backfillt friss sorok
újrapecsételését végzi. A scraper alap-DDL továbbra
is a bootstrap (a táblák első létrehozása), a **minden további séma-változás a
MIGRATIONS-ba** kerül. Új migrációnál a verziót léptetni kell (`SCHEMA_VERSION`), és a
`test_db_indexes` ellenőrzi a láncot.

### 2.21. Órarend: 4 hét előre, múlt megőrzése

A szinkron az **aktuális hét + 3 hét** (28 nap) órarendjét kéri le (API: `week_window`).
Az API-hívások 20 napos szeletekben mennek: az
`OrarendElemek` és a `Fogadoorak` végpont is így kapja meg a 4 hetes ablakot
(utóbbi legfeljebb 3 hetet enged egy kérésben; a szeletek között az azonos
fogadóóra-slotok Uid/időpont szerint összefésülődnek). A mentés **csak az új ablak kezdetétől** töröl, a korábbi
heteket **megőrzi** (múltbéli adat); üres lista továbbra sem törölhet (adatvédelem).
A régi (2 hetes) ablakhoz képest a naptár előretekerése is négy hétre elegendő.

### 2.22. „Mikor került be” időpont

A KRÉTA gyakran **visszamenőleges bejegyzés-dátummal** adja az új jegyet, ezért a
napi digest, a „SuliHub – új adatok” push, a `/api/ma` friss jegyei és a felületi
„mai” jelölés a `letrehozva` oszlopot használja (fallback: a KRÉTA-dátum).
Az `esemenyek`, `uzenetek`, `hianyzasok` és `igazolasok` táblán a v5 migráció
hozza létre. Az **első** feltöltéskor a legutóbbi **2 nap** sorai a migráció
időpontját kapják (a szülőnek ezek ténylegesen újak, csak a KRÉTA visszamenőleges
dátumot adott nekik), a régebbiek a KRÉTA-dátumot — így a hetek/hónapok óta
meglévő adatok nem lesznek visszamenőleg „újak”. Az ablak a
`KRETA_FIRST_SEEN_RECENT_DAYS` env-vel növelhető (max. 31). A **v6** migráció
a már v5-ös DB-knél a régi, éjfélre backfillt friss sorokat pecsételi át; a
valódi időbélyeges sorokat nem bántja. Az `Értékelés`/`Feljegyzés`
teljes cserés mentése tartalom-kulcs alapján megőrzi a korábbi időpontot. A
felületen az Események táblában a „Részletek / Leírás” után **közvetlenül**
**Bekerült** oszlop mutatja az időpontot (mai esetén `MA` jelzéssel), a
műveletgombok külön **Műveletek** oszlopban vannak, és a részletek modálban is
megjelenik. Teszt: `tests/test_first_seen.py`.

---

## 3. Hogyan működik (architektúra)

### 3.1. Komponensek

```
┌─────────────────────────── Docker konténer (saját szerver) ──────────────────────┐
│ │
│ Böngésző (LAN) ──HTTP:8085──► Flask alkalmazás (waitress) │
│ ├─ Webes felület (dashboard) │
│ ├─ REST API (adatok, PDF, státusz) │
│ ├─ Ütemező (háttérszál, 30 mp-es tick) │
│ └─ Szinkron indítása (gyerekprocessz) │
│ │ │
│ ▼ │
│ kreta_playwright.py (szinkron futtató) │
│ ├─► Kréta mobil API (böngésző nélkül) │
│ └─► e-Ügyintézés (üzenetek, csatolmányok) │
│ │ │
│ ▼ │
│ SQLite adatbázis + csatolmányok (fájlok) │
│ │
└───────────────────────────────────────────────────────────────────────────────────┘
 │ │
 ▼ ▼
 ntfy.sh (push) Host: napi mentés (03:00)
```

Az adatlekérés a **Kréta mobil API**-ból történik (`kreta_api.py`: mobil v3 / eAdmin
végpontok + normalizálás a meglévő DB-sémákra; `kreta_sync.py`: forrásmód és forrásnapló).
A szinkron kizárólag a mobil API-t használja.

**Moduláris szerkezet.** A belépő, az útvonalak, a közös rétegek és a frontend külön modulokban vannak:

| Réteg | Modulok |
|---|---|
| belépő + futásidejű mag | `app.py` (~1 100 sor): Flask app, auth, szinkron/ütemező/ntfy/napló, re-export a tesztekhez |
| útvonalak (prefix nélküli blueprint-ek) | `views_pages`, `views_events`, `views_orarend`, `views_messages`, `views_absences`, `views_stats`, `views_rewards`, `views_search`, `kreta_exports` |
| közös rétegek | `kreta_paths` (útvonalak), `kreta_db` (séma, meta, futásnapló), `kreta_settings` (config, verzió, színek), `views_common` (request-segédek) |
| frontend | `templates/index.html` (váz + modálok), `static/js/core.js` (globális segédek), `static/js/app-main.js` (a `$(document).ready` blokk) |
| futásidejű adatok | `data/` (DB, config.json, napló, tokenek, csatolmányok) — lásd 9.2 |

A `tests/test_routes_contract.py` a Flask-rule-okat, a `tools/api_snapshot.py` a válaszok szerkezetét ellenőrzi.

**API munkamenet (token-tár).** A KRÉTA minden **új** belépésről e-mailt küld („Új
bejelentkezésről értesítés"). Ezért az API-kliens a tokent a data köteten tárolja
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

#### 3.2.1. Forrásmód (`SYNC_MODE`)

| Mód | Mit jelent |
|---|---|
| `api` | **Alapértelmezés és az egyetlen futó mód.** Csak a mobil API; böngésző nem indul. Egy adatkör hibája részleges hiba, a többi adatkör és diák megy tovább. |


Az adatkörök: órarend, jegyek, feljegyzések, házi feladatok, bejelentett számonkérések,
hiányzások/késések, igazolások, üzenetek — mind a mobil API-ból. A forrás és a hibák oka a
`sync.log`-ba, a gép-olvasható összegzés `sources` mezőjébe és a `sync_runs.sources`
oszlopba kerül; a `/api/sync/status` is átadja.

> A D3–D7-tel a **hiányzások/késések, az igazolások, a jegyek, a házi feladatok, a
> bejelentett számonkérések, a feljegyzések, az órarend** (fogadóórákkal) és az
> **üzenetek** API-ból jönnek (táboros hiányzásnál a korábbi téma megmarad, a házi
> „kész” jelölése megmarad). **Az üzenet-csatolmányok is API-ból töltődnek** (2026-10-31
> óta): a kliens a `dokumentumok/uzenetek/{csatolmanyAzonosito}` végpontról kapott 302-es
> átirányítást követi a `files.e-kreta.hu/fajlok/?nonce=…` címre, és a bájtokat a
> `csatolmanyok/<diák>/` alá menti. Ha egy letöltés mégis elhal, a fájl nélkül mentjük az
> üzenetet (figyelmeztetés a naplóban), de a következő futások **pótolják**
> (`csatolmany_proba`, max. 3 próba) — így nincs végleges adatrés.

> **UTC-határ az órarendnél:** az `OrarendElemek` a `KezdetIdopont` **UTC** dátuma
> szerint szűr, a helyi nap 00:00-kor kezdődő egész napos események (szünetek,
> munkaszüneti napok) viszont előző napi `23:00Z`-ként jönnek. Ezért a kliens az
> órarend-ablakot **egy nappal korábbra** is kéri — enélkül az ablak első napjának
> eseményei (pl. az őszi szünet hétfője) kimaradnának a heti nézetből.

> **Jövőbeli határidők:** a KRÉTA az API-ablakon (`datumTol`–`datumIg`) belül adja a
> sorokat, a **házi feladat** és a **bejelentett számonkérés** viszont jövőbeli
> határidőt hordoz. Ezért ennél a két adatkörnél az ablak **90 nappal előre** is nyúlik
> (`kreta_api_sync.FUTURE_LOOKAHEAD_DAYS`) — enélkül a következő hetek dolgozatai és
> házijai nem jönnének le. A többi adatkör ablaka a mai napig tart.

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

**Tanév-scope:** a teljes cserék törlése csak a **most letöltött tanévekre** és a
**lekérési ablakon belülre** hat - a korábbi tanévek soraihoz a szinkron nem nyúl, akkor sem,
ha az API nem adja vissza őket. Az arányos őr is tanévenként számol. Az API-ablak a **tanév
első napjától** indul (nem a DB legkorábbi sorától), így a kérészáma nem nő a tanévek számával.
A letöltött tanéveken kívülre eső sor nem íródik be (duplikáció ellen), de nem csendben:
`skipped` a visszatérési értékben + `[FIGYELEM]` a naplóban.

A védett mentés után az API-szolgáltató **hibát dob**, így az adatkör részleges hibának
számít (riasztás jár vele), de a meglévő adatok megmaradnak. Ha egy valódi, nagyarányú
csökkenés lenne hiteles (pl. év eleji törlés a KRÉTA-ban), a
küszöb átmenetileg csökkenthető (`KRETA_SYNC_MIN_RATIO=0.2`), vagy `0`-ra állítva kikapcsolható.

#### 3.2.3. Szinkron-szünet

A `config.json` `SYNC_SZUNET` listája **intervallumokra** állítja le az automatikus
szinkront (pl. őszi/téli/tavaszi/nyári szünet, egyéb iskolai szünet). A `SZUNET_AKTIV`
**mesterkapcsoló** dönti el, hogy a szüneteket a működés egyáltalán figyelembe vegye-e
(alap: `true`); `false` esetén sem a szinkron-szünet, sem a digest szünetnap-felismerése
nem él.

```json
"SZUNET_AKTIV": true,
"SYNC_SZUNET": [
 {"nev": "Őszi szünet", "kezdo": "2026-10-23", "vege": "2026-11-01",
 "napi_sync": true, "napi_ido": "18:00"},
 {"nev": "Téli szünet", "kezdo": "2026-12-19", "vege": "2027-01-03",
 "napi_sync": true, "napi_ido": "18:00"},
 {"nev": "Tavaszi szünet", "kezdo": "2027-03-25", "vege": "2027-04-04",
 "napi_sync": true, "napi_ido": "18:00"},
 {"nev": "Nyári szünet", "kezdo": "2027-06-19", "vege": "2027-08-31",
 "napi_sync": true, "napi_ido": "18:00"}
]
```

A fenti időszakok a **2026/2027. tanév hivatalos rendje** szerintiek (első tanítási
nap 2026. szeptember 1., utolsó 2027. június 18.).

- A szünet alatt a **normál intervallumos automata futás kimarad**; a **kézi
 „Adatok frissítése” mindig** működik.
- `napi_sync: true` esetén a szünet alatt is fut **napi egy** automatikus szinkron a
 `napi_ido` (alap `10:00`) után; a napot a `sync_szunet_napi` `app_meta` jelölő zárja.
- A fejléc alatt **bordó, fehér szöveges sáv** jelzi: „Szüneti szinkron üzemmód”,
 „A beállított rendszeres szinkron szüneti üzemmódban működik”, valamint
 „Napi egy biztonsági szinkron bekapcsolva, ekkor: <napi_ido>”; a fejléc „következő
 futás” szövege is a szünetet mutatja. Az adat a `/api/scheduler/status` `szunet`
 mezőjében jön.
- **A `SYNC_SZUNET` intervallumait a digest is automatikusan szünetnapnak veszi** —
 így elég egy helyen megadni a tanítási szüneteket.
- Érvénytelen config-elem (rossz dátum) **kihagyva**, a többi intervallum működik.
- A szünetnaplózás naponta egyszer kerül a `sync.log`-ba (`[Szünet] …`), nem minden
 ütemezői ticknél.

#### 3.2.4. Digest: szünet- és hétvégenapok

A napi digest **nem küld „eseménytelen nap” üzenetet** hétvégén és tanítási szünet /
tanév rendje napokon. A szünetnap forrása:

1. **`SYNC_SZUNET` intervallumai** (elsődleges; a szinkron-szünettel közös),
2. `config.json → DIGEST.SZUNET_NAPOK`: ISO dátumok vagy `kezdo..vege` tartományok —
 csak **kiegészítés** a `SYNC_SZUNET`-en kívüli napokra,
3. az órarendi **egész napos** sorok, amelyeknek a nevében „szünet”, „nem órarendi nap”,
 „munkaszüneti” vagy „tanítás nélküli” szerepel.

A `SZUNET_AKTIV: false` mesterkapcsoló a digest szünetnap-felismerését is kikapcsolja
(a hétvégi üres digest kihagyása ettől függetlenül érvényben marad).

Ha a napon **van valódi esemény** (pl. hétvégi óra, beírt jegy, üzenet), a digest megy —
csak az üres „nem történt semmi” üzenet marad el. A kihagyott napot a `digest_sent`
jelölő lezárja (nem próbálja újra), a `digest_last_at` viszont **nem** változik, így a
manuális „Összefoglaló most” a kimaradt napokat is hozza. A manuális digestre a szabály
nem vonatkozik.

#### 3.2.5. Tanév-archívum

A tanév **lezárásakor** (a `TanevUid`-váltás után, a `tanev_changes` alapján) egyszeri,
ellenőrizhető ZIP készül a data köteten:

- `data/tanev_archivum/<év>.zip` (pl. `2025-2026.zip`) + `<év>.zip.sha256`;
- a **záráskor** a kanonikus `<év>.zip` készül; a **kézi export** nyitott tanévnél
 `<év>_manual_<időbélyeg>.zip` néven jön létre, hogy ne blokkolja a záráskori
 végleges archívumot; `--final` a kanonikus név kényszerítéséhez;
- táblánként JSON és CSV a tanévre szűrve (`esemenyek`, `uzenetek`, `hianyzasok`,
 `igazolasok`, `kifizetesek`, `sync_runs`, `tanevek`, `tanulo_tanev_uid`, `orarend`,
 `sajat_orarend`);
- kombinált Excel (`adatok.xlsx`), diákonkénti PDF-bizonyítvány (`riportok/`),
 `manifest.json` és `checksums.sha256`;
- a ZIP külső SHA-256 ellenőrző fájlja a ZIP mellett.

A művelet **idempotens**: ha a ZIP már létezik, nem írja felül; ismételt zárásnál nem
duplikál. A generálás ideiglenes könyvtárban történik, a kész ZIP atomikusan kerül a
helyére. Kézi pótlás/ellenőrzés: `python tools/create_tanev_archive.py 2025/2026`.

**Adatvédelem:** a ZIP a tanév **minden diákjának** adatait tartalmazza, ezért
ugyanúgy bizalmas, mint a DB és a napi backup; a data köteten marad, a napi mentés
viszi. A régi tanév adata pótolhatatlan, ezért a zárás utáni archívum a végső
pillanatkép; a `verify_archive` a belső és külső SHA-256-ot is ellenőrzi.

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
| `uzenetek` | e-Ügyintézés üzenetek + csatolmány hivatkozás | Csak az új üzenetek kerülnek be; a `posta_id` a postalada-elem azonosítója — ezzel kérhető le a **teljes szöveg** a részletes API-válaszból; az `olvasott` (0/1) a **helyi** olvasott/olvasatlan állapot (a szinkron a már mentett üzenetet nem írja felül, a KRÉTA-ba nem írunk vissza). A korábbi üzenetek **olvasottként** indulnak, hogy ne jelenjen meg minden régi üzenet olvasatlanként |
| `hianyzasok` | Hiányzások és késések (dátum, órasorszám, tantárgy, téma, típus, igazolt, igazolás típusa) | ISO dátum; a rekordot a **dátum + órasorszám** azonosítja; késést a `perc` és/vagy a típus neve jelöli |
| `igazolasok` | Igazolások érvényességi intervalluma + típus + megjegyzés | A hónaphoz a metsző igazolások tartoznak |
| `kifizetesek` | Zsebpénz-elszámolások havi tételei | „KIFIZETVE" állapot, összeg |
| `sync_runs` | **Minden szinkronizáció** egy sora (trigger, időpontok, státusz, darabszámok, új események, futásidő) | Ez adja a „legutóbbi futás" állapotot is |
| `app_meta` | Kulcs–érték technikai állapotok | pl. utolsó elavultsági riasztás ideje |
| `tanevek` | A tanévek állapota: `allapot` (nyitott/lezárt), `lezarva_at`, `forras` (kreta_uid/szamitott) | A zárás/nyitás a `TanevUid` változásához kötött; adatlekérés nélkül |
| `tanulo_tanev_uid` | Diákonként az utoljára látott KRÉTA `TanevUid` + a hozzá tartozó tanév | A váltás-detektálás alapja (a KRÉTA csak ezt adja, nevet nem) |
| `kommentek` | **Saját megjegyzések** eseményhez / üzenethez (szöveg, szerző, időpont) | Nem a KRÉTA-ból jön; a célzás **stabil tartalom-kulccsal** történik (az események id-je a szinkronnál változik) — |
| `sajat_orarend` | **Kézi órarendi sorozatok**: diák, megnevezés, nap (1–7), kezdés/vége, terem, megjegyzés, **szín**, érvényesség (`ervenyes_tol`–`ervenyes_ig`) | A KRÉTA szinkron **nem érinti**; egy sor = heti ismétlődő sorozat — |
| `sajat_orarend_kivetel` | Egy sorozat kivett alkalmai (`sajat_id`, `datum`, egyedi) | „Csak ezt az alkalmat törli” — a sorozat többi alkalma megmarad — |

**Adatmennyiség (2026-10-29):** 165 esemény, 124 órarend-sor, 56 üzenet, 2 elszámolás.

**Tanév-dimenzió (, 1. fázis):** a `esemenyek`, `uzenetek`, `hianyzasok`,
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
- A jegyek **súlyszázaléka** a mobil API `SulySzazalekErteke` mezőjéből jön
. A részletes
 sorokban ez nincs, ezért **dátum + tanár + mód (+ téma)** kulccsal párosítjuk.
 A DB-ben 0 = nincs adat (pl. Magatartás/Szorgalom sor vagy régi sor).
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
| **KRÉTA** (`<intézmény>.e-kreta.hu`) | Adatgyűjtés **mobil API-ból** (böngésző nélkül) | több iskolai azonosító; böngészős scraper nincs |
| **e-Ügyintézés** (`eugyintezes.e-kreta.hu`) | Üzenetek + csatolmányok | API-ból (mobil token), `X-Uzenet-Lokalizacio` illesztő |
| **ntfy** (`ntfy.sh`) | Push értesítések | Csak állapotinformáció; diáknév alapból nem megy ki |
| **Docker / Docker Compose** | Futtatás a szerveren | Konténer: `kreta-app`, port **8085** |
| **Privát üzemeltetés** | A karbantartó saját deployja | Nem része a publikus repónak |
| **cron (host)** | Napi mentés 03:00-kor | `kreta_backup.sh` |

### 5.1. Mentés és üzemeltetési ellenőrzések

- A napi mentés (`backup/kreta_backup.sh`) a DB mellé **sorszám-manifestet** ír
 (`kreta_adatok_*.counts.json`), hogy a visszaállítás ellenőrizhető legyen.
- **Havi restore-teszt:** `python3 tools/backup_restore_check.py --backup-dir... --db...`
 — a legfrissebb mentést izolált temp könyvtárba állítja vissza, `PRAGMA integrity_check`,
 manifest-egyezés, elavult/sérült mentés detektálása; hibánál ntfy riasztás, a valódi DB-hez
 nem nyúl. Javasolt cron: `15 4 1 * *`.
- **Éjszakai élő füstteszt:** `python3 tools/live_smoke.py --url... --max-age-hours 26`
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
| `SCRAPE_MESSAGES` | Üzenetek gyűjtése globálisan |
| `SYNC_MODE` | A szinkron forrása; `api` az egyetlen futó mód. |
| `SYNC_SZUNET` | Automatikus szinkron-szünetek: `[{nev, kezdo, vege, napi_sync, napi_ido}]`; a kezdő/vége ISO vagy magyar dátum; a kézi szinkron mindig megy; a digest is használja - lásd 3.2.3 |
| `SZUNET_AKTIV` | Mesterkapcsoló (alap: `true`): `false` esetén a tanítási szüneteket sem a szinkron, sem a digest nem veszi figyelembe |
| `DIGEST` | Esti összefoglaló (KRÉ-8): `ENABLED`, `TIME` (`19:30`), `INCLUDE_NAMES`; a felület beállításai felülírják (`app_meta`); `SZUNET_NAPOK` = kiegészítő szünet/tanév rendje napok a `SYNC_SZUNET` mellett - lásd 3.2.4 |
| `ENABLE_REWARDS` | Zsebpénz modul globálisan |
| `REWARDS` | A 2.5. pont tarifái |
| `KEYWORDS` | A feljegyzések kategorizálásához használt kulcsszavak |
| `SCHEDULER` | `ENABLED`, `INTERVAL_MINUTES` (180), `START_HOUR` (6), `END_HOUR` (22), `STALE_ALERT_HOURS` (12) |
| `STUDENTS[]` | Gyermekenként: név, iskolai azonosító, belépési adatok, aktív, üzenetek, zsebpénz |
| `CALENDAR` | Naptárbejegyzés: `TIMEZONE` (Europe/Budapest), `REMINDER_MINUTES` (30, 0 = nincs), `MESSAGE_DURATION_MINUTES` (30) |
| `ORAREND_SZINEK` | Gyermekenkénti órarend-szín, pl. `{"Teszt Elek": "#0d6efd"}`; a felület „Színek” ablaka felülírja (app_meta) |
| `AUTH` | Opcionális basic auth: `ENABLED`, `USERNAME`, `PASSWORD_HASH` (werkzeug `generate_password_hash`); a `PASSWORD` csak teszt/átmeneti |

### 6.2. Környezeti változók (üzemeltetés)

| Változó | Alapérték | Jelentés |
|---|---|---|
| `KRETA_DATA_DIR` | `.` | Adatkönyvtár (DB, config, log, csatolmányok) |
| `KRETA_DB_FILE` / `KRETA_CONFIG_FILE` / `KRETA_LOG_FILE` | data-könyvtárban | Egyedi útvonalak |
| `KRETA_CSATOLMANYOK_DIR` | `static/csatolmanyok` | Csatolmányok helye (élesben `/app/data/csatolmanyok`) |
| `KRETA_API_TOKEN_FILE` | `<data>/api_tokens.json` | API munkamenet-tár (access/refresh token, **titok**) |
| `KRETA_HOST` / `KRETA_PORT` / `KRETA_DEBUG` | `127.0.0.1` / `5000` / ki | Web szerver |
| `KRETA_SERVER` | `flask` | `waitress` = produkciós szerver (a compose így indítja) |
| `KRETA_WAITRESS_THREADS` | `8` | Kiszolgáló szálak |
| `NTFY_TOPIC` | *(üres)* | ntfy topic **vagy teljes URL** — üresen nincs értesítés (config.json `NTFY.TOPIC` is lehet, az env erősebb) |
| `NTFY_URL` | `https://ntfy.sh` | ntfy szerver (config.json `NTFY.URL` is lehet) |
| `NTFY_NOTIFY_NEW` | `1` | Új információ esetén küldjön-e push-t (config.json `NTFY.NOTIFY_NEW`; a régi `NOTIFY_SUCCESS` is elfogadott). A hibariasztás ettől független |
| `NTFY_INCLUDE_NAMES` | `0` | Diáknevek a push-ban (config.json `NTFY.INCLUDE_NAMES`) |
| `KRETA_LOG_MAX_BYTES` / `_BACKUP_COUNT` | `1000000` / `2` | Napló rotáció |
| `KRETA_SQLITE_WAL` | `0` | WAL mód (a FUSE kötet miatt alapból ki) |
| `KRETA_SYNC_MIN_RATIO` | `0.5` | Adatvédelmi küszöb a teljes cserés mentésnél (lásd 3.2.2); `0` = kikapcsolva |

---

## 7. Üzemeltetés

### 7.1. Telepítés

A nyilvános telepítés Docker Compose-szal történik; a lépések a README
„Docker élesítés” szakaszában vannak. A `data/` és `backup/` kötetek
alapértéke `./data`, illetve `./backup`; a `config.json` a data kötetben van.

### 7.2. Frissítés

1. `git pull` (vagy az új image letöltése).
2. `docker compose up -d --build`.
3. `curl http://127.0.0.1:8085/health` → a várt verzió.


### 7.3. Mentés és visszaállítás

- **Automatikus:** naponta **03:00-kor** (host cron), a konténerből konzisztens
 SQLite-snapshot + fájltömörítés (csatolmányok, config).
- **Megőrzés:** 7 napi + 4 heti DB-mentés; fájlok 14 napig; konfiguráció 30 napig.
- **Validálás:** a mentő ellenőrzi az integritást és a minimális méretet; hiba esetén
 **ntfy riasztást** küld.
- **Visszaállítás:** a legfrissebb `kreta_adatok_*.db` visszamásolása a data kötetre
 (konténer leállítása mellett javasolt).

### 7.4. Megfigyelhetőség

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

**Tanév-szűrő:** a `/api/esemenyek`, `/api/hianyzasok`, `/api/igazolasok`,
`/api/atlagok`, `/api/statisztika`, `/api/dashboard` végpontok `?tanev=` paramétert fogadnak:
üres vagy `all` = **összes tanév** (visszafelé kompatibilis), `current` = a naptár szerinti
aktuális tanév, egyébként pl. `2026/2027`. A válaszok `tanev` mezőt is tartalmaznak.
A felület a fejléc választójában **mindig explicit** értéket küld. A `/api/sync/status`
`tanev` mezője a futás tanéve.

### 7.5. Gyakori hibák és teendők

| Tünet | Ok | Teendő |
|---|---|---|
| „A config.json fájl nem található" a futásban | a config nincs a data könyvtárban | `data/config.json` ellenőrzése |
| A szinkron azonnal „error, 0.0 perc" | a konténerben hiányzó Python-modul (`/api/sync/status` logs: `ModuleNotFoundError`) — a Dockerfile nem másolja be az új modult | a Dockerfile `COPY *.py`-t használ; ellenőrzés: `python tests/test_deploy.py`, majd újraépítés |
| Nincs értesítés | `NTFY_TOPIC` nincs a `.env`-ben (lokálisan nincs is `.env`, ezért csendben nem küld), vagy a konténer nem lett újralétrehozva | topic a `.env`-be **vagy** a config.json `NTFY.TOPIC`-jába; ellenőrzés: `POST /api/ntfy/test` |
| A fejléc „régi" adatot mutat | böngésző-gyorsítótár | Ctrl+F5 |
| Két helyi példány ugyanazon a porton | Windows megengedi (SO_REUSEADDR) | a régi folyamat leállítása — az app **indításkor szól**: „a port már foglalt" és kilép |
| DB „malformed" olvasáskor | SMB-n keresztüli olvasás futás közben | nyugalmi állapotban ellenőrizni |
| „Internal Server Error" üres DB-nél | a `kreta_adatok.db`-t kézzel áthelyezték/törölték; az `esemenyek`/`uzenetek` tábla hiányzott | **önjavító**: induláskor (és kérésnél) a hiányzó séma létrejön (`kreta_playwright.py --init-db`), üres adatbázissal is elindul |
| Nem törölhető/nevezhető át a DB fájl | egy futó példány nyitva tartja (SQLite) | a KRÉTA-példány(ok) leállítása, utána a fájlművelet |

**Nulláról tesztelés:** állítsd le az appot, nevezd át/helyezd át a `kreta_adatok.db`-t, majd indítsd újra. Az app létrehozza a teljes sémát (a naplóban `[Adatbázis] Séma létrehozva`), és üres felülettel indul; az első (kézi) szinkron tölti fel. A séma önmagában is létrehozható: `python kreta_playwright.py --init-db`.

---

## 8. Biztonság és adatvédelem

- **Hálózat:** az alkalmazás **csak belső hálózaton** érhető el (nincs publikus kitettség).
- **Hitelesítés:** opcionális **basic auth** a `config.json` `AUTH` blokkjával
 (`ENABLED`, `USERNAME`, `PASSWORD_HASH`; a `/health` kivétel). Kikapcsolva a belső hálózat
 a védelmi vonal. Élesben **HTTPS/reverse proxy** javasolt, mert a basic auth önmagában
 nem titkosít. Ha a config **meglévő, de olvashatatlan/érvénytelen**, a védett
 végpontok **503**-at adnak (fail-closed); hiányzó confignál az auth nincs beállítva.
- **Személyes adatok:** gyermeknevek, jegyek, üzenetek. Ezek a saját szerveren maradnak.
- **AI:** nincs AI-funkció; a naptárbejegyzés/ICS a meglévő úton működik.
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
| Adatforrás | **Kréta mobil API** — böngésző nélkül |
| Adat | SQLite |
| Frontend | Bootstrap 5.3, jQuery, DataTables, FullCalendar 6, FontAwesome |
| Konténer | Docker, Docker Compose, Debian slim |

### 9.2. Mappaszerkezet

```
Kreta/
├── app.py # Flask belépő: app, auth, szinkron/ütemező/ntfy/napló + re-export
├── views_pages.py # / (dashboard)
├── views_events.py # események, kész-jelölés, naptár-események
├── views_orarend.py # órarend, saját órák, színek, ICS, naptár-nézet
├── views_messages.py # üzenetek, olvasottság, saját megjegyzések
├── views_absences.py # hiányzások / igazolások
├── views_stats.py # tanévek, dashboard, tantárgyi átlagok
├── views_rewards.py # zsebpénz-statisztika, kifizetés, naptár/ICS
├── kreta_exports.py # PDF órarend, XLSX/CSV export, zsebpénz-számítási mag
├── kreta_archive.py # zárt tanév ZIP-archívuma (JSON/CSV/Excel/PDF + checksum)
├── kreta_paths.py # útvonalak (KRETA_* env, data/ alapértelmezés)
├── kreta_db.py # DB-kapcsolat, séma/migrációk, app_meta, futásnapló
├── kreta_settings.py # config.json, verzió, órarend-színek
├── views_common.py # blueprint-építő + közös request-segédek
├── kreta_playwright.py # szinkron futtató: séma + mentők + API-szolgáltatók
├── kreta_api.py # mobil KRÉTA API kliens (böngésző nélkül)
├── kreta_api_sync.py # API adatkör-lekérők, ablakok
├── kreta_sync.py # SYNC_MODE, forrásnapló, fallback
├── kreta_tanev.py # tanév-számítás + séma-migráció
├── kreta_sajat_orarend.py # kézi órarendi sorozatok + kivételek
├── kreta_naptar.py # Google Naptár-link + .ics generálás
├── docs/ # DOKUMENTACIO.md
├── templates/index.html # dashboard váza (modálok, fülek) — inline JS nélkül
├── static/js/core.js # globális frontend-segédek (avatar, státuszsáv, formázás)
├── static/js/app-main.js # a felület fő JS-e ($(document).ready blokk)
├── static/vendor/ # vendorolt frontend-függőségek (offline)
├── tests/ # automatikus tesztek + futtató
├── tools/ # api_snapshot, migrate_local_data, mobile_shot, backup_restore_check
├── data/ # futásidejű adatok (NEM verziózott): DB, config.json, sync.log,
│ # api_tokens.json, scheduler_state.json, version.txt,
│ # csatolmanyok/
├── Dockerfile, docker-compose.yml, entrypoint.sh
└── README.md
```


A `data/` az alapértelmezett adatkönyvtár (DB, config, napló, csatolmányok).

### 9.3. Tesztek

```bash
python tests/run_all.py # mind
python tests/run_all.py --fast # böngésző nélkül
python tests/run_all.py --browser # böngészős UI-tesztek (Playwright)
```

A tesztek izolált temp könyvtárban futnak, valódi KRÉTA-hívást nem végeznek.
A CI a gyors, a böngészős és a `pip-audit` jobot futtatja; a böngészős job
hibája esetén a képernyőképek artifactként feltöltődnek.

### 9.4. Kiadási folyamat

1. Fejlesztés + `python tests/run_all.py` (minden zöld).
2. Commit / pull request a `main` ágra.
3. Release note a `docs/releasenotes/vX.Y.Z.md` alá, tag és GitHub Release.

A telepítés lépései a README-ben.

---

## 10. Ismert korlátok

| Korlát | Hatás | Megjegyzés |
|---|---|---|
| Nincs felhasználói hitelesítés | belső hálózaton belül bárki eléri | tudatos kompromisszum |
| Egy processzes ütemező | több worker esetén duplikálódna | Dockerben egy processz fut |
| KRÉTA API-változás | az API végpontjai változhatnak | a kliens a mobil API-t használja |
| Táboros hiányzás témája | az API nem ad rá témát (nincs órarendi elem) | a meglévő DB-érték megmarad; új táboros sornál üres |
| Adatvédelmi küszöb (3.2.2) | valódi, nagy arányú csökkenést is blokkol (a régi adat marad) | a napló `[FIGYELEM]`-et ír; `KRETA_SYNC_MIN_RATIO`-val állítható |
| Órarend-ablak első napja | az `OrarendElemek` a `KezdetIdopont` UTC dátuma szerint szűr, az egész napos események `23:00Z`-ként jönnek | a kliens egy nappal korábbra is kér (`fetch_lessons`), így a hétfői szünet/ünnep nem marad ki |
| Jövőbeli dolgozat/házi kimarad | az API az ablakon belül adja a sorokat, a házi/számonkérés határideje viszont jövőbeli | a `Házi feladat` és `Bejelentett számonkérés` ablaka **+90 nappal** előre nyúlik (`FUTURE_LOOKAHEAD_DAYS`) |
| Üzenet-csatolmány letöltése | az eAdmin API csak fájl-metadatot ad, a fájl egy rövid életű `nonce` URL-en jön | a kliens a `dokumentumok/uzenetek/{id}` 302-jét követi, és a `files.e-kreta.hu/fajlok/?nonce=…` címről tölt (API-ból, böngésző nélkül); `api` módban max. 3 próbás pótlás |
| „Új bejelentkezés" e-mailek | az API-út minden futásnál belépne | tokentárolás a data köteten (`api_tokens.json`): a 2. futástól **nincs új belépés**, lejárat után refresh token; teljes belépés csak token nélkül/hibánál |
| Nincs `MESSAGE_LIMIT` | az első API-s futás az összes üzenetet letölti , utána már csak az újakat | tudatos döntés: az inkrementális futások így is 1–5 üzenetet hoznak |
| Az üzenetlista csak előnézetet ad | az eAdmin `postaladaelemek/sajat` válasz `szoveg` mezője rövid és a sortörések nélkül | a mentéskor (és utólagos backfill-lel) a `postaladaelemek/<posta_id>` részletes választ használjuk, ami megőrzi a bekezdéseket |
| CDN-függő frontend | internet nélkül nem indulna a felület | minden frontend-függőség a `static/vendor/` alatt van |
| `config.json` egyszerű szöveg | jelszavak olvashatók a fájlból | a data kötet védett |
| A tanárgyi átlagok forrása | a KRÉTA webes `*_HaviAtlag` mezői üresek/nullák, a `Atlag` (időszaki) viszont súlyozott | a havi bontást a saját számításunk adja a jegyek súlyából; az időszaki átlag **egyezik** a KRÉTA `Atlag` mezőjével  |
| Tanév forrása | a KRÉTA mobil API rekord-szintű tanévet nem ad (csak `TanuloAdatlap.TanevUid`, a többi tanév-végpont 403) | a tanév a **rekord dátumából számított** (szept. 1.); a `TanevUid` a váltás jelzője (a nevet a dátum adja) |
| KRÉTA API tanév-scope | a mobil API a **korábbi tanévekre 0 sort ad**, csak az aktív tanévet szolgálja ki (dátum-szűrő közben működik) | a régi tanévek adata **pótolhatatlan** → soha nem törlünk korábbi tanévet; a napi backup és a törlésvédelem kritikus; nincs visszamenőleges lekérés |
| Tanév zárása/nyitása | a KRÉTA csak a nyers `TanevUid`-t adja (név nélkül; `/Sajat/Tanevek` 403) | a **váltást a `TanevUid`** jelzi; a zárás **technikai** (állapot + időpont), adatlekérés nélkül; a nevet a dátumból generáljuk, a váltás pillanatában rögzítve |
| Tanév-választó alapértéke | a fejléc-választó az **aktuális tanévet** mutatja | így a napi használatban nem keverednek a tanévek; az „Összes tanév" egy kattintás |
| Átlag „Összes tanév" módban | tanévek közötti átlag nem értelmezhető | a felület ilyenkor **nem mutat átlagot**, tanévválasztásra kér; az API `tanev` nélkül (kompatibilitásból) továbbra is számol |
| Törlési hatókör | a teljes cserék csak a letöltött tanévekre + az ablakon belülre törölnek | üres batch soha nem töröl, ismeretlen tanév soha nem töröl; a korábbi tanév sorai érintetlenek |
| WAL nem használt | párhuzamos írások ritkák | FUSE kötet miatt biztonságosabb |

---


## 11. Fogalomtár

| Fogalom | Jelentés |
|---|---|
| **Szinkron / futás** | Egy teljes adatgyűjtési ciklus (2–2,5 perc) |
| **Ütemező** | Az a háttérfolyamat, ami a 3 órás ciklust vezérli |
| **Részleges hiba** | A futás lefutott, de 1+ gyermek adata nem frissült |
| **Data kötet** | A szerver HDD-jén lévő könyvtár, ahol az adatok élnek |
| **ntfy** | Push értesítő szolgáltatás |
| **KRÉTA** | Az iskolai adminisztrációs rendszer |

---


## 12. Kapcsolódó dokumentumok

| Fájl | Tartalom |
|---|---|
| `README.md` | Rövid üzemeltetői útmutató, telepítés, konfiguráció |
| `docs/DOKUMENTACIO.md` | A rendszer teljes leírása |
| `tests/README.md` | A tesztek leírása és futtatása |

---
