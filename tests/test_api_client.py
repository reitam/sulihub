# -*- coding: utf-8 -*-
"""
A termelési KRÉTA API kliens (kreta_api.py) tesztjei.

Minden hálózati hívás fake sessionnel megy, valódi KRÉTA-belépés nélkül.
"""
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kreta_api import (  # noqa: E402
    KretaApiClient,
    KretaAuthError,
    KretaNetworkError,
    KretaResponseError,
    ApiToken,
    chunk_date_range,
    hu_date,
    hu_datetime,
    iso_date,
    lesson_index,
    normalize_evaluation,
    normalize_homework,
    normalize_justification,
    normalize_message,
    normalize_note,
    normalize_omission,
    normalize_test,
    pick_lesson,
    plain_text,
)

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._json is None:
            raise ValueError("nincs JSON")
        return self._json


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.headers = {}

    def _next(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        if not self._responses:
            raise AssertionError("elfogytak a fake válaszok")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, **kwargs):
        return self._next("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._next("POST", url, kwargs)

    def close(self):
        pass


def make_client(responses):
    student = {"username": "user", "password": "pass", "institute_code": "iskola"}
    return KretaApiClient(student, timeout=5, session=FakeSession(responses))


def login_responses():
    page = '<input name="__RequestVerificationToken" type="hidden" value="rvt-123">'
    callback = FakeResponse(302, headers={"location": "https://mobil.e-kreta.hu/cb?code=ABC"})
    token = FakeResponse(200, json_data={
        "access_token": "access-1", "refresh_token": "refresh-1",
        "expires_in": 1800, "token_type": "Bearer",
    })
    return [FakeResponse(200, text=page), FakeResponse(200, text="ok"), callback, token]


print("1) Login flow")
client = make_client(login_responses())
token = client.login()
ok(token.access_token == "access-1", "access token megérkezett")
ok(token.refresh_token == "refresh-1", "refresh token megérkezett")
ok(token.institute_code == "iskola", "iskolakód megmaradt")
ok(len(client.session.calls) == 4, f"4 login lépés történt ({len(client.session.calls)})")
ok("__RequestVerificationToken" in client.session.calls[1][2]["data"], "RVT elküldve a POST-ban")

print("\n2) Tokenfrissítés 401 után")
client = make_client([
    FakeResponse(401, text="unauthorized"),
    FakeResponse(200, json_data={"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 1800}),
    FakeResponse(200, json_data=[]),
])
client.token = ApiToken("access-1", "refresh-1", "iskola", time.time() + 3600)
result = client._api_get("sajat/Mulasztasok", {"datumTol": "2026-09-01", "datumIg": "2026-09-20"})
ok(result == [], "a retry sikeres volt")
ok(client.token.access_token == "access-2", "az access token frissült")
ok(client.token.refresh_token == "refresh-2", "a refresh token frissült")
ok(len(client.session.calls) == 3, "GET 401 -> refresh -> GET")

print("\n3) Hibák típusosak")
client = make_client([FakeResponse(400, text='{"Message":"bad"}')])
client.token = ApiToken("a", "r", "iskola", time.time() + 3600)
try:
    client._api_get("sajat/Mulasztasok")
    ok(False, "400 esetén kivétel kell")
except KretaResponseError:
    ok(True, "400 -> KretaResponseError")

client = make_client([requests.ConnectionError("boom")])
client.token = ApiToken("a", "r", "iskola", time.time() + 3600)
try:
    client._api_get("sajat/Mulasztasok")
    ok(False, "hálózati hiba esetén kivétel kell")
except KretaNetworkError:
    ok(True, "hálózati hiba -> KretaNetworkError")

client = make_client([
    FakeResponse(200, text='<input name="__RequestVerificationToken" value="rvt">'),
    FakeResponse(200),
    FakeResponse(302, headers={"location": "https://mobil.e-kreta.hu/cb"}),
])
try:
    client.login()
    ok(False, "code nélkül hibát kell dobni")
except KretaAuthError:
    ok(True, "code nélküli callback -> KretaAuthError")

print("\n4) Dátumszeletek")
chunks = list(chunk_date_range(date(2026, 9, 1), date(2026, 10, 30)))
ok(len(chunks) == 3, f"45 nap -> 3 szelet ({len(chunks)})")
ok(chunks[0] == (date(2026, 9, 1), date(2026, 9, 20)), "első szelet 20 nap")
ok(chunks[-1][1] == date(2026, 10, 30), "utolsó szelet a záró dátumig tart")
ok(all(chunks[i][1] < chunks[i + 1][0] for i in range(len(chunks) - 1)), "nincs átfedés")

print("\n5) Dátum- és szövegkonverzió")
ok(iso_date("2026-09-13T22:00:00Z") == "2026-09-14", "UTC 22:00 -> helyi másnap")
ok(iso_date("2026-09-14") == "2026-09-14", "ISO dátum változatlan")
ok(hu_date("2026-09-13T22:00:00Z") == "2026. 09. 14.", "magyar dátumformátum")
ok(hu_datetime("2026-09-22T01:33:31") == "2026. 09. 22. 1:33",
   "üzenet helyi ideje nem csúszik el")
ok(plain_text("<p>Első</p><p>Második</p>") == "Első Második", "HTML -> sima szöveg")

print("\n6) Normalizálás")
omission = normalize_omission({
    "Uid": "123", "Datum": "2026-09-13T22:00:00Z",
    "KesesPercben": None, "IgazolasAllapota": "Igazolt",
    "IgazolasTipusa": {"Nev": "orvosi_igazolas", "Leiras": "Orvosi igazolás"},
    "Tipus": {"Nev": "hianyzas", "Leiras": "Hiányzás"},
    "Tantargy": {"Nev": "matematika"},
    "Ora": {"Oraszam": 5, "Tema": None, "TanarNeve": None},
    "KeszitesDatuma": "2026-09-13T22:00:00Z",
    "RogzitoTanarNeve": "Minta Andrea",
})
ok(omission["mulasztas_datum"] == "2026-09-14", "hiányzás helyi dátuma")
ok(omission["ora_sorszam"] == 5, "órasorszám")
ok(omission["mulasztas_tipus"] == "Hiányzás", "típus a Leiras-ból")
ok(omission["igazolt"] == 1, "igazolt")
ok(omission["rogzito"] == "Minta Andrea", "rögzítő tanár")

pending = normalize_omission({
    "Uid": "124", "Datum": "2026-10-21T22:00:00Z", "KesesPercben": None,
    "IgazolasAllapota": "Igazolando", "IgazolasTipusa": None,
    "Tipus": {"Leiras": "Hiányzás"}, "Tantargy": {"Nev": "matematika"},
    "Ora": {"Oraszam": 5}, "KeszitesDatuma": "2026-10-21T22:00:00Z",
})
ok(pending["igazolt"] == 0, "Igazolando -> még nem igazolt")

homework = normalize_homework({
    "Uid": "1", "TantargyNeve": "irodalom", "RogzitoTanarNeve": "Tanár",
    "Szoveg": "<p>Első</p><p>Második</p>",
    "FeladasDatuma": "2026-09-01T22:00:00Z",
    "RogzitesIdopontja": "2026-09-13T22:00:00Z",
    "HataridoDatuma": "2026-09-20T22:00:00Z",
})
ok(homework["bej_datum"] == "2026. 09. 14.", "házi a rögzítés dátumát használja")
ok(homework["hatarido"] == "2026. 09. 21.", "házi határidő helyi dátum")
ok(homework["tartalom"] == "Első Második", "házi szöveg HTML-mentes")

test = normalize_test({
    "Uid": "2", "TantargyNeve": "matematika", "RogzitoTanarNeve": "Tanár",
    "Modja": {"Leiras": "Dolgozat"}, "Temaja": "Halmazok",
    "Datum": "2026-09-29T22:00:00Z", "BejelentesDatuma": "2026-09-22T10:19:39Z",
})
ok(test["hatarido"] == "2026. 09. 30.", "számonkérés napja helyi")
ok(test["bej_datum"] == "2026. 09. 22.", "számonkérés bejelentése helyi")
ok(test["mod"] == "Dolgozat", "számonkérés módja")

note = normalize_note({
    "Uid": "3", "Datum": "2026-10-08T22:00:00Z",
    "Tipus": {"Leiras": "Osztályfőnöki dicséret"}, "KeszitoTanarNeve": "Tanár",
    "Cim": "Rajzpályázat", "Tartalom": "<b>Szép</b> munka",
})
ok(note["bej_datum"] == "2026. 10. 09.", "feljegyzés helyi dátuma")
ok(note["tipus"] == "Osztályfőnöki dicséret", "feljegyzés típusa")
ok(note["tartalom"] == "Szép munka", "feljegyzés HTML-mentes")

justification = normalize_justification({
    "Id": 563578, "Kezdete": "2026-09-13T22:00:00Z", "Vege": "2026-09-16T22:00:00Z",
    "Tipusa": {"Leiras": "Orvosi igazolás"},
    "Megjegyzes": "<p>EESZT</p><p>Megjegyzés</p>",
})
ok(justification["kezdete"] == "2026-09-14", "igazolás kezdete helyi")
ok(justification["vege"] == "2026-09-17", "igazolás vége helyi")
ok(justification["megjegyzes"] == "EESZT Megjegyzés", "igazolás megjegyzés HTML-mentes")

message = normalize_message({
    "azonosito": 10, "isElolvasva": True,
    "uzenet": {
        "azonosito": 20, "feladoNev": "Rendszer", "feladoTitulus": "-",
        "targy": "Teszt", "kuldesDatum": "2026-09-22T01:33:31",
        "szoveg": "<p>Üzenet</p>", "csatolmanyok": [{"nev": "a.pdf"}],
    },
})
ok(message["idopont"] == "2026. 09. 22. 1:33", "üzenet helyi idő")
ok(message["felado"] == "Rendszer (-)", "üzenet feladó + titulus")
ok(message["szoveg"] == "Üzenet", "üzenet HTML-mentes")

print("\n7) Órarend-join párhuzamos csoportokkal")
lessons = [
    {"KezdetIdopont": "2026-09-27T22:00:00Z", "Oraszam": 2,
     "Tantargy": {"Nev": "Tanulási tréning"}, "Tema": "Hétindító", "TanarNeve": "Horváthné"},
    {"KezdetIdopont": "2026-09-27T22:00:00Z", "Oraszam": 2,
     "Tantargy": {"Nev": "Felzárkóztatás"}, "Tema": "Hangos olvasás", "TanarNeve": "Szabó"},
]
index = lesson_index(lessons)
picked = pick_lesson(index, {"mulasztas_datum": "2026-09-28", "ora_sorszam": 2,
                             "tantargy": "Tanulási tréning"})
ok(picked and picked["tema"] == "Hétindító", "a tantárgy alapján választ órát")
ok(picked and picked["tanar"] == "Horváthné", "a helyes tanárt választja")

print("\n8) Üzenetek szűrése (csak beérkezett)")
client = make_client([FakeResponse(200, json_data=[
    {"azonosito": 1, "tipus": {"kod": "BEERKEZETT"}, "uzenet": {"azonosito": 1}},
    {"azonosito": 2, "tipus": {"kod": "ELKULDOTT"}, "uzenet": {"azonosito": 2}},
    {"azonosito": 3, "tipus": {"kod": "BEERKEZETT"}, "isToroltElem": True,
     "uzenet": {"azonosito": 3}},
])])
client.token = ApiToken("a", "r", "iskola", time.time() + 3600)
messages = client.fetch_messages()
ok(len(messages) == 1 and messages[0]["azonosito"] == 1, "küldött/törölt üzenet kiszűrve")
ok("X-Uzenet-Lokalizacio" in client.session.calls[0][2]["headers"], "eAdmin lokalizációs header")

print("\n9) Nincs Playwright-függés")
source = (ROOT / "kreta_api.py").read_text(encoding="utf-8")
ok("import playwright" not in source and "from playwright" not in source,
   "a kreta_api.py nem importál Playwrightot")
ok("from poc" not in source and "import poc" not in source, "nincs POC-függés")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
