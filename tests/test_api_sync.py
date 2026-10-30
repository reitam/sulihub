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
    apply_lesson_join,
    fetch_justifications,
    fetch_omissions,
    omission_window,
)

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


class FakeClient:
    """Csak a D3-hoz szükséges végpontokat utánozza (nincs hálózat)."""

    def __init__(self, omissions=None, lessons=None, justifications=None):
        self._omissions = omissions or []
        self._lessons = lessons or []
        self._justifications = justifications or []
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


print("1) Lekérési ablak")
today = date(2026, 10, 30)
start, end = omission_window(None, today=today)
ok(end == today, "a záró dátum a mai nap")
ok((today - start).days == DEFAULT_LOOKBACK_DAYS, f"alap visszatekintés: {DEFAULT_LOOKBACK_DAYS} nap")
start2, _ = omission_window("2025-01-15", today=today)
ok(start2 == date(2025, 1, 15), "a DB legkorábbi sora tágítja az ablakot")
start3, _ = omission_window("2026-09-01", today=today)
ok(start3 == start, "a későbbi DB-dátum nem szűkíti az ablakot")
start4, _ = omission_window("hibás-dátum", today=today)
ok(start4 == start, "értelmezhetetlen DB-dátum -> alap ablak")

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

print("\n4) Igazolások fake klienssel")
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
start, end = k.hianyzas_api_window("Teszt")

print("RESULT=" + json.dumps({{
    "rows_first": first,
    "rows_second": second,
    "same_ids": [r[0] for r in first] == [r[0] for r in second],
    "same_rows": first == second,
    "counts_first": counts_first,
    "just_first": ig1,
    "just_second": ig2,
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

print("\n5) Táboros téma megőrzése (valódi DB)")
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

print("\n6) Inkrementális, stabil ID")
ok(payload.get("same_rows") is True, "ismételt futás után a sorok változatlanok")
ok(payload.get("same_ids") is True, "a sor-ID-k stabilak")
ok((payload.get("counts_first") or {}).get("Teszt", {}).get("db") == 1,
   f"az első futás 1 új hiányzást számol (a táboros sor már a DB-ben volt): "
   f"{payload.get('counts_first')}")
ok((payload.get("counts_first") or {}).get("Teszt", {}).get("igazolatlan_ora") == 1,
   "1 új igazolatlan óra")

print("\n7) Igazolások")
ok(len(payload.get("just_first") or []) == 1, "1 igazolás mentve")
ok(payload.get("just_second") == payload.get("just_first"), "ismételt futás nem duplikál")
ok((payload.get("just_first") or [[None]])[0][0] == "563578", "igazolás ID a kulcs")

print("\n8) Lekérési ablak a DB-ből")
ok(payload.get("window_start") == str(date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)),
   f"ablak kezdete egy évvel korábbra esik: {payload.get('window_start')}")
ok(payload.get("window_end") == str(date.today()), "ablak vége a mai nap")

shutil.rmtree(work, ignore_errors=True)
print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
