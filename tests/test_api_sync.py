# -*- coding: utf-8 -*-
"""
D3 teszt: hiányzások/késések és igazolások API-ból.

1) `kreta_api_sync` tiszta logikája: lekérési ablak, órarendi join (párhuzamos
   csoportokkal), fake kliens.
2) Valódi SQLite-on (külön folyamat): a táboros hiányzás témája megmarad, a
   rendes hiányzás témája az órarendből jön, ismételt futás után nincs új sor
   és a sor-ID-k stabilak; igazolás mentés ID-kulccsal.
"""
import json
import os
import subprocess
import sys
import tempfile
import shutil
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kreta_api_sync import (  # noqa: E402
    DEFAULT_LOOKBACK_DAYS,
    api_window,
    apply_lesson_join,
    fetch_announced_tests,
    fetch_evaluations,
    fetch_homeworks,
    fetch_justifications,
    fetch_omissions,
    parse_stored_date,
)

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


class FakeClient:
    """Csak a D3–D5-höz szükséges végpontokat utánozza (nincs hálózat)."""

    def __init__(self, omissions=None, lessons=None, justifications=None, evaluations=None,
                 homeworks=None, announced_tests=None):
        self._omissions = omissions or []
        self._lessons = lessons or []
        self._justifications = justifications or []
        self._evaluations = evaluations or []
        self._homeworks = homeworks or []
        self._announced_tests = announced_tests or []
        self.calls = []

    def fetch_omissions(self, start, end):
        self.calls.append(("omissions", start, end))
        return list(self._omissions)

    def fetch_lessons(self, start, end):
        self.calls.append(("lessons", start, end))
        return list(self._lessons)

    def fetch_justifications(self):
        self.calls.append(("justifications",))
        return list(self._justifications)

    def fetch_evaluations(self, start, end):
        self.calls.append(("evaluations", start, end))
        return list(self._evaluations)

    def fetch_homeworks(self, start, end):
        self.calls.append(("homeworks", start, end))
        return list(self._homeworks)

    def fetch_announced_tests(self, start, end):
        self.calls.append(("announced_tests", start, end))
        return list(self._announced_tests)


print("1) Lekérési ablak")
today = date(2026, 10, 30)
start, end = api_window(None, today=today)
ok(end == today, "a záró dátum a mai nap")
ok((today - start).days == DEFAULT_LOOKBACK_DAYS, f"alap visszatekintés: {DEFAULT_LOOKBACK_DAYS} nap")
start2, _ = api_window("2025-01-15", today=today)
ok(start2 == date(2025, 1, 15), "a DB legkorábbi sora tágítja az ablakot")
start3, _ = api_window("2026-09-01", today=today)
ok(start3 == start, "a későbbi DB-dátum nem szűkíti az ablakot")
start4, _ = api_window("hibás-dátum", today=today)
ok(start4 == start, "értelmezhetetlen DB-dátum -> alap ablak")
ok(parse_stored_date("2024. 05. 10.") == date(2024, 5, 10), "magyar formátumú dátum olvasása")
ok(parse_stored_date("2026-09-14") == date(2026, 9, 14), "ISO dátum olvasása")
ok(parse_stored_date("2026. 13. 40.") is None, "érvénytelen dátum -> None")
start5, _ = api_window("2024. 05. 10.", today=today)
ok(start5 == date(2024, 5, 10), "a magyar formátumú DB-dátum is tágítja az ablakot")

print("\n2) Órarendi join (párhuzamos csoportok)")
lessons = [
    {"KezdetIdopont": "2026-10-06T22:00:00Z", "Oraszam": 3,
     "Tantargy": {"Nev": "matematika"}, "Tema": "Halmazok", "TanarNeve": "Minta Andrea"},
    {"KezdetIdopont": "2026-10-06T22:00:00Z", "Oraszam": 3,
     "Tantargy": {"Nev": "német"}, "Tema": "Wiederholung", "TanarNeve": "Német Tanár"},
]
rows = [
    {"mulasztas_datum": "2026-10-07", "ora_sorszam": 3, "tantargy": "matematika",
     "tema": "", "tanar": ""},
    {"mulasztas_datum": "2026-10-07", "ora_sorszam": 3, "tantargy": "német",
     "tema": "", "tanar": ""},
    {"mulasztas_datum": "2026-10-07", "ora_sorszam": 3, "tantargy": "biológia",
     "tema": "", "tanar": ""},
]
apply_lesson_join(rows, lessons)
ok(rows[0]["tema"] == "Halmazok" and rows[0]["tanar"] == "Minta Andrea",
   "a matematika óra témája/tanára")
ok(rows[1]["tema"] == "Wiederholung" and rows[1]["tanar"] == "Német Tanár",
   "a párhuzamos csoport a tantárgy alapján kapja a témát")
ok(rows[2]["tema"] == "" and rows[2]["tanar"] == "", "ismeretlen tantárgy -> üres marad")

kept = [{"mulasztas_datum": "2026-10-07", "ora_sorszam": 3, "tantargy": "matematika",
         "tema": "Saját téma", "tanar": ""}]
apply_lesson_join(kept, lessons)
ok(kept[0]["tema"] == "Saját téma", "a meglévő témát nem írja felül")
ok(kept[0]["tanar"] == "Minta Andrea", "a hiányzó tanárt viszont pótolja")

print("\n3) Fake kliens: hiányzás + join")
omissions = [
    {"Uid": "1", "Datum": "2026-09-08T22:00:00Z", "KesesPercben": None,
     "IgazolasAllapota": "Igazolt", "IgazolasTipusa": {"Leiras": "Orvosi igazolás"},
     "Tipus": {"Leiras": "Hiányzás"}, "Ora": {"Oraszam": 1},
     "Tantargy": {"Nev": "Osztályfőnöki"}, "KeszitesDatuma": "2026-09-08T22:00:00Z"},
    {"Uid": "2", "Datum": "2026-10-06T22:00:00Z", "KesesPercben": None,
     "IgazolasAllapota": "Igazolando", "IgazolasTipusa": None,
     "Tipus": {"Leiras": "Hiányzás"}, "Ora": {"Oraszam": 3},
     "Tantargy": {"Nev": "matematika"}, "KeszitesDatuma": "2026-10-06T22:00:00Z"},
]
client = FakeClient(omissions=omissions, lessons=lessons)
fetched = fetch_omissions(client, today, today)
ok(len(fetched) == 2, f"2 normalizált hiányzás: {len(fetched)}")
ok([c[0] for c in client.calls] == ["omissions", "lessons"], "téma hiányában órarendet is kér")
ok(fetched[1]["tema"] == "Halmazok", "a rendes hiányzás témája az órarendből")
ok(fetched[1]["igazolt"] == 0, "Igazolando -> még nem igazolt")
ok(fetched[0]["tema"] == "", "a táboros sor témája üres az API-ból")

print("\n4) Jegyek normalizálása (Magatartás/Szorgalom)")
grades = FakeClient(evaluations=[
    {"Uid": "1", "Tantargy": {"Nev": "Irodalom"}, "Tema": "Dolgozat",
     "SzovegesErtek": "Jeles(5)", "SzamErtek": 5, "ErtekeloTanarNeve": "Minta Gáborné",
     "Tipus": {"Leiras": "Évközi jegy/értékelés"}, "Mod": {"Leiras": "Órai munka"},
     "RogzitesDatuma": "2026-09-13T22:00:00Z",
     "KeszitesDatuma": "2026-09-14T08:01:56Z"},
    {"Uid": "2", "Tantargy": {"Nev": "Magatartás"}, "Tema": None,
     "SzovegesErtek": "Példás", "SzamErtek": 0, "ErtekeloTanarNeve": "Osztályfőnök",
     "Tipus": {"Leiras": "Évközi jegy/értékelés"}, "RogzitesDatuma": "2026-10-06T22:00:00Z"},
    {"Uid": "3", "Tantargy": {"Nev": "Szorgalom"}, "Tema": None,
     "SzovegesErtek": "Példás", "SzamErtek": 0, "ErtekeloTanarNeve": "Osztályfőnök",
     "Tipus": {"Leiras": "Évközi jegy/értékelés"}, "RogzitesDatuma": "2026-10-06T22:00:00Z"},
])
grows = fetch_evaluations(grades, today, today)
ok(len(grows) == 3, f"3 értékelés: {len(grows)}")
ok(all(g["esemeny_tipus"] == "Értékelés" for g in grows), "mind Értékelés típus")
ok(grows[0]["bej_datum"] == "2026. 09. 14.", f"bej_datum helyi idő: {grows[0]['bej_datum']}")
ok(grows[0]["szam_ertek"] == 5 and grows[0]["ertek"] == "Jeles(5)", "szöveges + szám érték")
ok(grows[0]["ertekelo"] == "Minta Gáborné", "értékelő tanár")
ok(grows[1]["tantargy"] == "Magatartás" and grows[1]["szam_ertek"] == 0,
   "a Magatartás külön sor, 0 számértékkel (nem rontja az átlagot)")
ok(grows[2]["tantargy"] == "Szorgalom" and grows[2]["szam_ertek"] == 0,
   "a Szorgalom külön sor, 0 számértékkel")

print("\n4b) Házi és számonkérés normalizálása")
hw_client = FakeClient(
    homeworks=[{
        "Uid": "1", "TantargyNeve": "Magyar nyelv", "RogzitoTanarNeve": "Minta Gáborné",
        "Szoveg": "<p>Első</p><p>Második</p>",
        "RogzitesIdopontja": "2026-09-13T22:00:00Z",
        "HataridoDatuma": "2026-09-20T22:00:00Z",
    }],
    announced_tests=[{
        "Uid": "2", "TantargyNeve": "Matematika", "RogzitoTanarNeve": "Bagó Orsolya",
        "Modja": {"Leiras": "Írásbeli témazáró dolgozat"}, "Temaja": "Halmazok",
        "Datum": "2026-09-29T22:00:00Z", "BejelentesDatuma": "2026-09-22T10:19:39Z",
    }],
)
hrows = fetch_homeworks(hw_client, today, today)
ok(hrows[0]["bej_datum"] == "2026. 09. 14.", f"házi rögzítés helyi: {hrows[0]['bej_datum']}")
ok(hrows[0]["hatarido"] == "2026. 09. 21.", f"házi határidő helyi: {hrows[0]['hatarido']}")
ok(hrows[0]["tartalom"] == "Első Második", "házi szöveg HTML-mentes")
ok(hrows[0]["ertekelo"] == "Minta Gáborné", "házi rögzítő tanár")
ok(hrows[0]["esemeny_tipus"] == "Házi feladat", "házi típus")

trows = fetch_announced_tests(hw_client, today, today)
ok(trows[0]["hatarido"] == "2026. 09. 30.", f"számonkérés napja helyi: {trows[0]['hatarido']}")
ok(trows[0]["bej_datum"] == "2026. 09. 22.", "számonkérés bejelentése helyi")
ok(trows[0]["mod"] == "Írásbeli témazáró dolgozat", "számonkérés módja")
ok(trows[0]["tema"] == "Halmazok", "számonkérés témája")

print("\n5) Igazolások fake klienssel")
just = FakeClient(justifications=[{
    "Id": 563578, "Kezdete": "2026-09-13T22:00:00Z", "Vege": "2026-09-16T22:00:00Z",
    "Tipusa": {"Leiras": "Orvosi igazolás"}, "Megjegyzes": "<p>EESZT</p>",
}])
jrows = fetch_justifications(just)
ok(len(jrows) == 1 and jrows[0]["kreta_id"] == "563578", "igazolás ID a kulcs")
ok(jrows[0]["megjegyzes"] == "EESZT", "igazolás megjegyzés HTML-mentes")

# ── 5) Valódi adatbázis, külön folyamatban ──────────────────────────────────
work = Path(tempfile.mkdtemp(prefix="kreta_apisync_"))
data = work / "data"
data.mkdir()
(data / "config.json").write_text(
    json.dumps({"HEADLESS": True, "SYNC_MODE": "api_first",
                "STUDENTS": [{"diak_nev": "Teszt", "active": False}]}, ensure_ascii=False),
    encoding="utf-8",
)

probe = work / "probe.py"
probe.write_text(
    """# -*- coding: utf-8 -*-
import json, sqlite3, sys
sys.path.insert(0, r'{root}')
import kreta_playwright as k

k.init_db()

def ins_existing():
    conn = sqlite3.connect(k.DB_FILE)
    conn.execute(
        "INSERT INTO hianyzasok (kreta_id, mulasztas_datum, ora_sorszam, perc, tantargy,"
        " tema, tanar, mulasztas_tipus, igazolt, tanorai_celu, igazolas_tipus,"
        " rogzites_datum, diak_nev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("11391408", "2026-09-09", 1, None, "Osztályfőnöki", "Minta-tábor",
         "Minta Zsuzsanna", "Hiányzás", 1, "Igen", "Orvosi igazolás",
         "2026-09-09", "Teszt"))
    conn.execute(
        "INSERT INTO esemenyek (diak_nev, esemeny_tipus, tantargy, ertek, szam_ertek,"
        " bej_datum, hatarido, ertekelo, tipus, mod, tema, cim, tartalom, kesz)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("Teszt", "Házi feladat", "Magyar nyelv", "", 0, "2026. 09. 14.",
         "2026. 09. 21.", "Minta Gáborné", "", "", "", "", "Kézzel megjelölt házi", 1))
    conn.commit(); conn.close()

OMISSIONS = [
    {{"Uid": "11391408", "Datum": "2026-09-08T22:00:00Z", "KesesPercben": None,
      "IgazolasAllapota": "Igazolt",
      "IgazolasTipusa": {{"Nev": "orvosi_igazolas", "Leiras": "Orvosi igazolás"}},
      "Tipus": {{"Nev": "hianyzas", "Leiras": "Hiányzás"}},
      "Ora": {{"Oraszam": 1}}, "Tantargy": {{"Nev": "Osztályfőnöki"}},
      "KeszitesDatuma": "2026-09-08T22:00:00Z",
      "RogzitoTanarNeve": "Minta Zsuzsanna"}},
    {{"Uid": "22222", "Datum": "2026-10-06T22:00:00Z", "KesesPercben": None,
      "IgazolasAllapota": "Igazolando", "IgazolasTipusa": None,
      "Tipus": {{"Nev": "hianyzas", "Leiras": "Hiányzás"}},
      "Ora": {{"Oraszam": 3}}, "Tantargy": {{"Nev": "matematika"}},
      "KeszitesDatuma": "2026-10-06T22:00:00Z"}},
]
LESSONS = [
    {{"KezdetIdopont": "2026-10-06T22:00:00Z", "Oraszam": 3,
      "Tantargy": {{"Nev": "matematika"}}, "Tema": "Halmazok", "TanarNeve": "Minta Andrea"}},
]
JUSTIFICATIONS = [
    {{"Id": 563578, "Kezdete": "2026-09-13T22:00:00Z", "Vege": "2026-09-16T22:00:00Z",
      "Tipusa": {{"Leiras": "Orvosi igazolás"}}, "Megjegyzes": "EESZT"}},
]
EVALUATIONS = [
    {{"Uid": "1", "Tantargy": {{"Nev": "Irodalom"}}, "Tema": "Dolgozat",
      "SzovegesErtek": "Jeles(5)", "SzamErtek": 5, "ErtekeloTanarNeve": "Minta Gáborné",
      "Tipus": {{"Leiras": "Évközi jegy/értékelés"}}, "Mod": {{"Leiras": "Órai munka"}},
      "RogzitesDatuma": "2026-09-13T22:00:00Z"}},
    {{"Uid": "2", "Tantargy": {{"Nev": "Magatartás"}}, "Tema": None,
      "SzovegesErtek": "Példás", "SzamErtek": 0, "ErtekeloTanarNeve": "Osztályfőnök",
      "Tipus": {{"Leiras": "Évközi jegy/értékelés"}},
      "RogzitesDatuma": "2026-10-06T22:00:00Z"}},
]
HOMEWORKS = [
    {{"Uid": "1", "TantargyNeve": "Magyar nyelv", "RogzitoTanarNeve": "Minta Gáborné",
      "Szoveg": "API szöveg", "RogzitesIdopontja": "2026-09-13T22:00:00Z",
      "HataridoDatuma": "2026-09-20T22:00:00Z"}},
    {{"Uid": "2", "TantargyNeve": "Történelem", "RogzitoTanarNeve": "Minta Gáborné",
      "Szoveg": "Új házi", "RogzitesIdopontja": "2026-09-20T22:00:00Z",
      "HataridoDatuma": "2026-09-27T22:00:00Z"}},
]
ANNOUNCED = [
    {{"Uid": "10167", "TantargyNeve": "Matematika", "RogzitoTanarNeve": "Bagó Orsolya",
      "Modja": {{"Leiras": "Írásbeli témazáró dolgozat"}}, "Temaja": "Halmazok",
      "Datum": "2026-10-06T22:00:00Z", "BejelentesDatuma": "2026-09-30T10:15:13Z"}},
]


class FakeClient:
    def __init__(self, student):
        self.student = student
        self.calls = 0

    def fetch_omissions(self, start, end):
        self.calls += 1
        return OMISSIONS

    def fetch_lessons(self, start, end):
        return LESSONS

    def fetch_justifications(self):
        return JUSTIFICATIONS

    def fetch_evaluations(self, start, end):
        return EVALUATIONS

    def fetch_homeworks(self, start, end):
        return HOMEWORKS

    def fetch_announced_tests(self, start, end):
        return ANNOUNCED


def grades_snapshot():
    conn = sqlite3.connect(k.DB_FILE)
    rows = conn.execute(
        "SELECT tantargy, ertek, szam_ertek, bej_datum FROM esemenyek"
        " WHERE diak_nev='Teszt' AND esemeny_tipus='Értékelés'"
        " ORDER BY bej_datum, tantargy").fetchall()
    conn.close()
    return rows


def hazi_snapshot():
    conn = sqlite3.connect(k.DB_FILE)
    rows = conn.execute(
        "SELECT tantargy, bej_datum, hatarido, tartalom, kesz FROM esemenyek"
        " WHERE diak_nev='Teszt' AND esemeny_tipus='Házi feladat'"
        " ORDER BY bej_datum, tantargy").fetchall()
    conn.close()
    return rows


def szamonkeres_snapshot():
    conn = sqlite3.connect(k.DB_FILE)
    rows = conn.execute(
        "SELECT tantargy, hatarido, bej_datum, mod, tema FROM esemenyek"
        " WHERE diak_nev='Teszt' AND esemeny_tipus='Bejelentett számonkérés'"
        " ORDER BY hatarido, tantargy").fetchall()
    conn.close()
    return rows


def snapshot():
    conn = sqlite3.connect(k.DB_FILE)
    rows = conn.execute(
        "SELECT id, kreta_id, mulasztas_datum, ora_sorszam, tantargy, tema, tanar,"
        " tanorai_celu, igazolt FROM hianyzasok WHERE diak_nev='Teszt'"
        " ORDER BY mulasztas_datum, ora_sorszam").fetchall()
    ig = conn.execute(
        "SELECT kreta_id, kezdete, vege, igazolas_tipus FROM igazolasok"
        " WHERE diak_nev='Teszt'").fetchall()
    conn.close()
    return rows, ig


ins_existing()
factory = lambda student: FakeClient(student)
k.api_provider_hianyzasok({{"diak_nev": "Teszt"}}, client_factory=factory)
first, _ = snapshot()
counts_first = dict(k.NEW_HIANYZAS_COUNTS)
k.api_provider_hianyzasok({{"diak_nev": "Teszt"}}, client_factory=factory)
second, _ = snapshot()
k.api_provider_igazolasok({{"diak_nev": "Teszt"}}, client_factory=factory)
_, ig1 = snapshot()
k.api_provider_igazolasok({{"diak_nev": "Teszt"}}, client_factory=factory)
_, ig2 = snapshot()
k.api_provider_jegyek({{"diak_nev": "Teszt"}}, client_factory=factory)
grades1 = grades_snapshot()
k.api_provider_jegyek({{"diak_nev": "Teszt"}}, client_factory=factory)
grades2 = grades_snapshot()
k.api_provider_hazi({{"diak_nev": "Teszt"}}, client_factory=factory)
hazi1 = hazi_snapshot()
k.api_provider_hazi({{"diak_nev": "Teszt"}}, client_factory=factory)
hazi2 = hazi_snapshot()
k.api_provider_szamonkeresek({{"diak_nev": "Teszt"}}, client_factory=factory)
szk1 = szamonkeres_snapshot()
k.api_provider_szamonkeresek({{"diak_nev": "Teszt"}}, client_factory=factory)
szk2 = szamonkeres_snapshot()
start, end = k.hianyzas_api_window("Teszt")

print("RESULT=" + json.dumps({{
    "rows_first": first,
    "rows_second": second,
    "same_ids": [r[0] for r in first] == [r[0] for r in second],
    "same_rows": first == second,
    "counts_first": counts_first,
    "just_first": ig1,
    "just_second": ig2,
    "grades_first": grades1,
    "grades_second": grades2,
    "hazi_first": hazi1,
    "hazi_second": hazi2,
    "szk_first": szk1,
    "szk_second": szk2,
    "window_start": str(start),
    "window_end": str(end),
}}, ensure_ascii=False))
""".replace("{root}", str(ROOT)).replace("{{", "{").replace("}}", "}"),
    encoding="utf-8",
)

env = os.environ.copy()
env["KRETA_DATA_DIR"] = str(data)
env["PYTHONIOENCODING"] = "utf-8"
for key in ("KRETA_CONFIG_FILE", "KRETA_DB_FILE", "KRETA_LOG_FILE"):
    env.pop(key, None)

result = subprocess.run([sys.executable, str(probe)], cwd=str(work), env=env,
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=120)
out = result.stdout
if result.returncode != 0:
    print(out[-1500:])
    print(result.stderr[-1500:])

payload = {}
for line in out.splitlines():
    if line.startswith("RESULT="):
        payload = json.loads(line.split("=", 1)[1])

print("\n6) Táboros téma megőrzése (valódi DB)")
ok(result.returncode == 0, f"a próba lefutott (exit={result.returncode})")
rows_first = payload.get("rows_first") or []
ok(len(rows_first) == 2, f"2 hiányzás a mentés után: {len(rows_first)}")
camp = next((r for r in rows_first if r[2] == "2026-09-09"), None)
regular = next((r for r in rows_first if r[2] == "2026-10-07"), None)
ok(camp is not None, "a táboros sor megvan")
ok(camp and camp[5] == "Minta-tábor", f"a táboros téma megmaradt: {camp[5] if camp else None}")
ok(camp and camp[6] == "Minta Zsuzsanna", "a táboros sor tanára megmaradt")
ok(camp and camp[7] == "Igen", "a tanórai cél jelölés megmaradt")
ok(regular is not None, "a rendes hiányzás megvan")
ok(regular and regular[5] == "Halmazok", f"a rendes hiányzás témája az órarendből: {regular[5] if regular else None}")
ok(regular and regular[6] == "Minta Andrea", "a rendes hiányzás tanára az órarendből")
ok(regular and regular[8] == 0, "az Igazolando sor igazolatlan")

print("\n7) Inkrementális, stabil ID")
ok(payload.get("same_rows") is True, "ismételt futás után a sorok változatlanok")
ok(payload.get("same_ids") is True, "a sor-ID-k stabilak")
ok((payload.get("counts_first") or {}).get("Teszt", {}).get("db") == 1,
   f"az első futás 1 új hiányzást számol (a táboros sor már a DB-ben volt): "
   f"{payload.get('counts_first')}")
ok((payload.get("counts_first") or {}).get("Teszt", {}).get("igazolatlan_ora") == 1,
   "1 új igazolatlan óra")

print("\n7b) Jegyek a valódi DB-ben")
grades_first = payload.get("grades_first") or []
ok(len(grades_first) == 2, f"2 értékelés mentve: {len(grades_first)}")
by_subject = {g[0]: g for g in grades_first}
ok(by_subject.get("Irodalom", [None, None, None, None])[3] == "2026. 09. 14.",
   "a jegy bej_datum helyi dátum")
ok(by_subject.get("Irodalom", [None] * 4)[2] == 5, "az Irodalom számértéke 5")
ok(by_subject.get("Magatartás", [None] * 4)[2] == 0,
   "a Magatartás 0 számértékkel (nem számít az átlagba)")
ok(payload.get("grades_second") == grades_first, "ismételt futás nem duplikál jegyet")
numeric = [g[2] for g in grades_first if g[2] in (1, 2, 3, 4, 5)]
ok(numeric and round(sum(numeric) / len(numeric), 2) == 5.0,
   f"az átlag csak a numerikus jegyekből: {numeric}")

print("\n7c) Házi: kesz megmarad, nincs duplikáció")
hazi_first = payload.get("hazi_first") or []
ok(len(hazi_first) == 2, f"2 házi a mentés után: {len(hazi_first)}")
kept = next((h for h in hazi_first if h[1] == "2026. 09. 14."), None)
new = next((h for h in hazi_first if h[1] == "2026. 09. 21."), None)
ok(kept and kept[4] == 1, f"a kézzel késznek jelölt házi kesz=1 maradt: {kept}")
ok(kept and kept[3] == "Kézzel megjelölt házi", "a meglévő házi szövegét nem írja felül")
ok(new and new[4] == 0, "az új házi kesz=0")
ok(new and new[3] == "Új házi", "az új házi szövege az API-ból jön")
ok(payload.get("hazi_second") == hazi_first, "ismételt futás nem duplikál házit")

print("\n7d) Számonkérés")
szk_first = payload.get("szk_first") or []
ok(len(szk_first) == 1, f"1 számonkérés mentve: {len(szk_first)}")
ok(szk_first and szk_first[0][1] == "2026. 10. 07.", "a számonkérés napja helyi")
ok(szk_first and szk_first[0][3] == "Írásbeli témazáró dolgozat", "a mód az API-ból")
ok(szk_first and szk_first[0][4] == "Halmazok", "a téma az API-ból")
ok(payload.get("szk_second") == szk_first, "ismételt futás nem duplikál számonkérést")

print("\n8) Igazolások")
ok(len(payload.get("just_first") or []) == 1, "1 igazolás mentve")
ok(payload.get("just_second") == payload.get("just_first"), "ismételt futás nem duplikál")
ok((payload.get("just_first") or [[None]])[0][0] == "563578", "igazolás ID a kulcs")

print("\n9) Lekérési ablak a DB-ből")
ok(payload.get("window_start") == str(date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)),
   f"ablak kezdete egy évvel korábbra esik: {payload.get('window_start')}")
ok(payload.get("window_end") == str(date.today()), "ablak vége a mai nap")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
