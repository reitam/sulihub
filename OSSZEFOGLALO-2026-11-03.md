# Összefoglaló — 2026-11-03 (éjszakai munkamenet)

**Téma:** iskolai tanév kezelése a KRÉTA Adatbázis Áttekintőben (Kaneo #40) + a
köré szervezett hibajavítások, tesztek és dokumentáció.

**Ág:** `feature/tanev-kezeles` (a `main`-re még nincs beolvasztva, a `main` 4
committal előrébb van az `origin/main`-nél). Élesítés: `v1.7.0`.

---

## 1. Ki mit csinált

A munkát a beállított agent-csapat segítette (`.opencode/agents/`, mindegyik
`subagent` és csak olvas, kódot nem módosít):

| Agent | Szerep ebben a munkában |
|---|---|
| `business_analyst` | a #40 követelményeinek tisztázása, elfogadási kritériumok |
| `architect` | tanév-modell, törlési hatókör, API-viselkedés terve |
| `system_analyst` | a KRÉTA API válaszainak és a meglévő DB-viselkedésnek az ellenőrzése |
| `testmanager` | tesztstratégia, a tanévváltás „óra-bomba” forgatókönyve |

A döntéseket a csapat hozta meg (a felhasználó engedélyével, utólag módosíthatóan);
ezek a 6. pontban olvashatók.

---

## 2. Tanév-modell (a munka magja)

- **A tanév a rekord saját dátumából számított**: szeptember 1. – augusztus 31.
  (a házi feladat / bejelentett számonkérés esetén a **határidő** dönt).
- A KRÉTA `TanuloAdatlap.TanevUid` csak **diagnosztika** — rekord-szintű tanévet a
  mobil API nem ad (a tanév-végpontok 403-at adnak).
- Új modul: **`kreta_tanev.py`** — `tanev_of`, `tanev_bounds`, `current_tanev`,
  `row_tanev`, `teljesen_lekert`, `ensure_tanev_schema`, `backfill_tanev`, `today`;
  tesztelhető `today=` paraméterrel és `KRETA_TODAY` / `KRETA_TANEV_KEZDO` env-vel.
- Séma: `tanev` + `tanev_forras` oszlop a `esemenyek`, `uzenetek`, `hianyzasok`,
  `igazolasok`, `kifizetesek` táblán, valamint `sync_runs.tanev`.
  Az **`orarend` szándékosan nem** kap tanévet (heti órarend).
- Migráció: **csak UPDATE**-tel tölti ki a meglévő sorokat (ID-stabil, újraindítható).
  `tanev IS NULL` = még nem migrált, `''` = ismeretlen dátum.

## 3. Szinkron: tanév- és ablak-scope

- A teljes cserés mentések (jegyek, feljegyzések, igazolások) **csak a most letöltött
  tanévekre és a lekérési ablakon belülre** törölnek — a korábbi tanévek soraihoz a
  szinkron nem nyúl.
- Az arányos adatvédelmi őr **tanévenként** számol.
- **Üres batch soha nem töröl**; az ismeretlen tanév soha nem töröl.
- Az igazolások **upsertelnek `kreta_id` kulcson** (stabil ID).
- A letöltött tanéveken kívülre eső sor nem íródik be (duplikáció ellen), de nem
  csendben: `skipped` a visszatérési értékben + `[FIGYELEM]` a naplóban.
- A `POST /api/kifizetes` a kifizetés **tanévét is beírja** (az időszak kezdetéből),
  így a frissen kifizetett összeg a tanévre szűrt dashboardon **azonnal levonódik**.
- Az API-ablak a **tanév első napjától** indul (a régi `MIN(stored)` és a 366 napos
  lookback megszűnt); a házi/számonkérés ablaka **+90 nappal** előre nyúlik.
- A futás tanéve bekerül a `sync_runs.tanev`-be; **tanévváltásnál** a napló egyszeri
  „ÚJ TANÉV: 2025/2026 → 2026/2027” sort ír, és ntfy-értesítés megy ki.
  A `/api/sync/status` is jelzi a tanévet.

## 4. API

- `GET /api/tanevek` — a DB-ben előforduló tanévek, az aktuális tanév, a határok.
- `?tanev=` szűrő: `/api/esemenyek`, `/api/hianyzasok`, `/api/igazolasok`,
  `/api/atlagok`, `/api/statisztika`, `/api/dashboard`.
  - üres / `all` = **összes tanév** (visszafelé kompatibilis),
  - `current` = a naptár szerinti aktuális tanév,
  - egyébként pl. `2026/2027`.
- A válaszok `tanev` mezőt is tartalmaznak.

## 5. Felület

- **Tanév-választó a fejlécben** — alapból az **aktuális tanév**, „Összes tanév”
  opcióval. A választó az eseményeket, hiányzásokat, átlagokat, statisztikát és a
  dashboardot szűri; az **üzenetek és az órarend tanév-független**.
- **„Összes tanév” módban nincs átlag** (tanévek között nem értelmezhető): a
  Statisztika fül a „válassz tanévet” üzenetet mutatja, a dashboard-kártyákon „-”
  szerepel.
- Üres tanévnél rövid súgó a listán / hiányzások fülön.
- A tantárgyi átlagok fejléce a kiválasztott tanévet írja (a régi hónapokból
  számolt becslés helyett).

## 6. Döntések (utólag módosíthatók)

1. A tanév a **rekord dátumából** számít (nem a KRÉTA `TanevUid`-ból).
2. Az **órarend nem kap tanévet**; a házi/számonkérés tanévét a **határidő** dönti el.
3. Törlés csak akkor, ha a tanév a letöltött batchben van, az ablak teljesen lefedi,
   és az arányos őr nem blokkol; üres batch és ismeretlen tanév soha nem töröl.
4. Az API alapértéke továbbra is „összes tanév” (kompatibilitás); a **felület viszont
   mindig explicit** tanévet küld, alapból az aktuálisat.
5. **„Összes tanév” átlag nincs** — az átlag csak tanéven belül értelmezhető.
6. Az üzenetek fül tanév-független marad.
7. A tanévzáró futás **kézi** marad (nem automatikus) — ezt a #43 kezeli majd, a
   #40 2–3. fázisának élesítése után.

## 7. Kaneo-jegyek

| Jegy | Állapot | Megjegyzés |
|---|---|---|
| #32 CodeReview: adatvédelem teljes cserénél | **done** | már a `824720e`-ben (v1.6.3) elkészült, a v1.6.4 élesíti; a jegy eddig tévesen `planned` volt |
| #40 Iskolai tanév kezelése | folyamatban | 0–6. fázis kész a `feature/tanev-kezeles` ágon; hátra: deploy |
| #41 Tanév-információ forrása | done | a döntés: rekord-dátum, `TanevUid` csak diagnosztika |
| #42 Igazolások teljes cseréje | in-review | upsert + arányos őr; a v1.7.0 élesíti |
| #43 Tanévváltás automatizálása | in-review | UID-alapú automatikus állapotváltás (lásd #54) |
| #54 Implementáció: tanév-állapot | in-review | `tanevek`/`tanulo_tanev_uid`, UID-ellenőrzés futás után, technikai zárás/nyitás, UI badge |
| #45 Teszt: tanévkezelés | in-review | 796/27 zöld; hátra: éles E2E a deploy után |
| #51 Dashboard nem frissül tanévváltáskor | in-review | javítva: a csempék a friss adatból számolnak (versenyhelyzet megszüntetve) |
| #52 Hol van az év lezárás gomb? | done | superseded: a kézi gomb helyett automatikus UID-alapú zárás/nyitás |
| #53 Tanév vs. date picker | in-review | javítva: a dátum-/hónapválasztók a tanév határain belül |
| #46 Saját megjegyzés | in-review | új `kommentek` tábla + API + felület (esemény és üzenet) |
| #50 Teszt-lefedettség (P2/P3) | planned | a testmanager független ellenőrzésének nem blokkoló tételei (UI E2E, hiányzás/igazolás hatókör, API élek, tanévváltás-push, többkörös backfill) — a P1 kifizetés-hiba javítva |

A #41, #42, #43, #45, #50 a #40 **subtaskja** (task-relation), nem külön backlog-tétel.

## 8. Tesztek

- **863 automatikus ellenőrzés / 28 csomag — mind zöld** (`python tests/run_all.py`).
- Új csomagok:
  - `test_tanev.py` — számítás, határok, `teljesen_lekert`,
  - `test_tanev_migration.py` — séma + backfill régi DB-n, ID-stabilitás, idempotencia,
  - `test_tanev_sync.py` — ablak a tanév elejétől, tanév-scope, korábbi tanév érintetlen,
    **óra-bomba** (08-31 → 09-01 üres válasz → 09-03 új adat),
  - `test_tanev_api.py` — két tanév szétválasztása, `/api/tanevek`, dashboard-egyenleg.
- Frissített csomagok: `test_data_guard`, `test_hianyzasok`, `test_api_sync`,
  `test_dashboard` (tanév-tudatos fixture + tanév-választó E2E), `test_a_package`
  (futás tanéve).
- A `testmanager` agent független ellenőrzése megtalálta a `POST /api/kifizetes`
  tanév-hiányát (P1) — javítva, tesztelve. A nyitott, nem blokkoló tételeket
  **#50** alatt vette fel a boardra.

## 9. Dokumentáció

- `DOKUMENTACIO.md` — tanév-adatmodell, törlési hatókör, API `?tanev=`, felület
  viselkedése, döntések táblázata, v1.7.0 verziósor.
- `README.md` — verzió és a tanév-választó bemutatása.
- `tests/README.md` — az új tesztek leírása.

## 10. Commitok (`feature/tanev-kezeles`)

| Commit | Tartalom |
|---|---|
| `95bab7e` | 0–1. fázis: `kreta_tanev.py`, séma-migráció + backfill, #42 igazolás-őr |
| `6b52808` | 2–3. fázis: tanév- és ablak-scope, tanévenkénti őr, igazolás upsert, ablak a tanév elejétől |
| `635724a` | 4. fázis: `?tanev=` szűrő + `/api/tanevek` |
| `a3aab64` | 5–6. fázis: fejléc tanév-választó, üres-tanév súgók, `sync_runs.tanev` + tanévváltás napló/push |
| `4273993` | kifizetés tanéve + „Összes tanév” KPI-átlag + kihagyott sor jelzése (testmanager-lelet nyomán) |
| *(bugkör)* | #51 dashboard-frissítés, #52 tanévzáró gomb, #53 dátumkorlátok |
| *(a legutolsó commit)* | #46 saját megjegyzések (esemény + üzenet) |
| `a5e6e8c` | #43 tanév-állapot: UID-alapú automatikus zárás/nyitás, a kézi záró gomb megszüntetése |

Korábbi, `main`-en lévő kapcsolódó commit: `dc22213` (`kaneo_ticket.py --parent`),
`824720e` (adatvédelem, v1.6.3).

## 11. Bug-kör a helyi tesztelés után (Kaneo #51–#53)

A felhasználó helyi tesztelése három hibajegyet vett fel („Bug" címke); mind a
`feature/tanev-kezeles` ágon javítva:

- **#51 – a dashboard nem frissült tanévváltáskor.** Az esemény- és üzenet-válasz
  versenyhelyzete miatt a csempék (heti határidők / új jegyek) a régi adatból
  számoltak, amíg F5 nem jött. Most az események visszaérkezésekor is lefut a
  `updateDashboard()`; a szinkron után a tanév-lista is frissül, megtartva a
  kiválasztást. Teszt: `test_tanev_ui` 2. szakasz (késleltetett esemény-válasz).
- **#52 – hiányzó „év lezárás" gomb.** Először kézi tanévzáró gombként valósult meg, majd
  a mérés (lásd 13. pont) és a felhasználói döntés alapján **átalakult**: a tanév
  zárása/nyitása **automatikus, `TanevUid`-alapú** (Kaneo #43) — a gomb megszűnt, helyette
  állapotjelzés van. Adatot visszamenőleg nem kérünk le.
- **#53 – tanév vs. dátumválasztó.** A bejegyzés-dátum, a zsebpénz-időszak és a
  hiányzás-hónap választó `min`/`max` korlátot kap a tanév határaira, a tanéven
  kívüli érték törlődik, a gyorsgombok intervalluma a tanévre vágódik. Teszt:
  `test_tanev_ui` 3. szakasz.

Új tesztcsomagok: `test_tanev_state` (állapotgép) és `test_tanev_ui` (böngésző) —
összesen **863 ellenőrzés / 28 csomag**.

## 12. Saját megjegyzések (Kaneo #46)

- **Új `kommentek` tábla:** `cel_tipus` (`esemeny`/`uzenet`), `cel_kulcs`, `szoveg`,
  `szerzo`, `letrehozva`. A célzás **stabil tartalom-kulccsal** történik, mert a
  szinkron a jegyek/feljegyzések sorait teljes cserével újraírja (az id-k változnak) —
  így a megjegyzés a szinkronok után is a helyén marad.
- **API:** `GET /api/kommentek?cel_tipus=&cel_kulcs=`, `POST /api/kommentek`,
  `DELETE /api/kommentek/<id>`; az `/api/esemenyek` és `/api/uzenetek` válaszban
  `komment_kulcs` + `komment_db` (darabszám).
- **Felület:** az események sorában megjegyzés-gomb (darabszámmal) → modál lista +
  új megjegyzés + törlés; az üzenet részleteinél külön megjegyzés-blokk.
- **Tesztek:** `test_kommentek` (séma/migráció, kulcs-stabilitás újraírás után,
  validáció, törlés, darabszám, böngészős mentés/visszaolvasás).

## 13. Mérés: a KRÉTA API és a korábbi tanévek (2026-11-03)

Olvasás-only próba 3 diákkal, a valódi KRÉTA API-n:

| Lekérés | 2024/2025 | 2025/2026 | 2026/2027 (kontroll) |
|---|---|---|---|
| jegyek (szept.) | 0 | 0 | 2–4 db |
| jegyek (2026. március) | – | 0 | – |
| hiányzások (szept.) | 0 | 0 | van adat |
| igazolások | – | – | 1–3 db |

A dátum-szűrő működik (az aktuális tanévben a szűk ablakok eltérő darabszámot adnak),
tehát a 0 eredmény nem hibás lekérés: **a mobil API a korábbi tanévekre nem ad adatot**,
csak az aktív tanévet szolgálja ki. Következmények:

- nincs visszamenőleges adatlekérés; a tanév zárása **technikai** (állapot + időpont);
- a **választó** csak az iskolai adatokból (jegy/hiányzás/igazolás/kifizetés) származó
  tanéveket listázza; a helyi DB-ben a 2024/2025 és 2025/2026 eddig csak az
  **üzenetek** miatt látszott — ezért ezek a választóból kikerültek;
- a váltást a KRÉTA `TanevUid`-ja jelzi (a nevet a dátum adja, mert a `/Sajat/Tanevek`
  és `/Sajat/Tanulo` diák-scope-ban **403** — ezt külön is ellenőriztük 2026-11-03-án);
- a #43 „szeptemberi záró futás az előző tanévre" premisszája hibás; helyette
  **UID-alapú automatikus zárás/nyitás** (lásd 15. pont);
- a régi tanévek adata **pótolhatatlan** → a napi backup és a törlésvédelem kritikus;
- a Playwright kivezetése mellett ez további érv (nincs mit „helyettesíteni").

## 14. Tanév-állapot: automatikus zárás/nyitás (Kaneo #43)

A felhasználói döntés és a mérés alapján:

- minden szinkronfutás után diákonként lekérjük a `TanuloAdatlap.TanevUid`-t;
- **ha megváltozik**, a nyitott tanévet technikailag lezárjuk (`tanevek.allapot='lezart'`,
  `lezarva_at`), és megnyitjuk az újat — **adatlekérés nélkül**;
- ha nem változik, nem zárunk (a naptár szerinti évforduló önmagában nem ok);
- a név a dátumból generált címke, a váltás pillanatában rögzítve;
- a lezárás nem tilt le semmit (kifizetés/megjegyzés a régi tanévre is rögzíthető);
- a fejlécben állapotjelzés, a választóban „lezárt” jelölés; a kézi „Tanév lezárása”
  gomb megszűnt.

## 15. Nyitott teendők

1. **Deploy:** `.\deploy.ps1 -Release v1.7.0` (interaktív SSH-jelszót kér, ezért az
   agent nem tudta futtatni). A `v1.6.5` tartalma (hónap-oszlopok évszám nélkül +
   tanév-felirat) már benne van ebben a kiadásban.
2. Deploy után: `/health` = `v1.7.0`, majd az éles E2E (az első futás után a
   `tanevek`/`tanulo_tanev_uid` sorok, a fejléc állapotjelzése, `sync_runs.tanev`).
3. **#43** implementációja ezen az ágon készül (UID-alapú zárás/nyitás); élesítés a
   v1.7.0-val, utána a #43 lezárható.
4. A `main` 4 commitja és a `feature/tanev-kezeles` ág még nincs pusholva.
