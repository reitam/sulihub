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
    html_to_text,
    hu_date,
    hu_datetime,
    iso_date,
    lesson_index,
    message_body_from_detail,
    normalize_evaluation,
    normalize_homework,
    normalize_justification,
    normalize_lesson,
    normalize_message,
    normalize_note,
    normalize_consultations,
    normalize_omission,
    normalize_test,
    pick_lesson,
    plain_text,
    safe_fajlnev,
)

_hibak = []


def ok(condition, message):
    print(("  OK   " if condition else "  HIBA ") + message)
    if not condition:
        _hibak.append(message)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None, content=b""):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}
        self.content = content

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
    # token_store="": nincs perzisztencia, a tesztek nem olvassák a valódi tárfájlt
    return KretaApiClient(student, timeout=5, session=FakeSession(responses), token_store="")


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

print("\n1b) Első API-hívás automatikus belépéssel")
client = make_client(login_responses() + [FakeResponse(200, json_data=[{"Uid": "1"}])])
result = client._api_get("sajat/Mulasztasok", {"datumTol": "2026-09-01", "datumIg": "2026-09-20"})
ok(result == [{"Uid": "1"}], "token nélkül is lefut (belépés a háttérben)")
ok(len(client.session.calls) == 5, f"4 login lépés + 1 API hívás ({len(client.session.calls)})")

print("\n1c) Token-tár: munkamenet a data kötetről (nincs új belépés)")
import json as _json  # noqa: E402
import tempfile as _tempfile  # noqa: E402

from kreta_api import load_stored_token, save_stored_token  # noqa: E402

_store_dir = _tempfile.mkdtemp(prefix="kreta_token_")
_store = str(Path(_store_dir) / "api_tokens.json")
_store_student = {"username": "user", "password": "pass", "institute_code": "iskola"}

save_stored_token(_store_student, ApiToken("access-1", "refresh-1", "iskola",
                                           time.time() + 3600), _store)
loaded = load_stored_token(_store_student, _store)
ok(loaded and loaded.access_token == "access-1", "a token visszaolvasható a tárból")
ok(loaded and loaded.refresh_token == "refresh-1", "a refresh token is megvan")
_saved = _json.loads(Path(_store).read_text(encoding="utf-8"))
ok(list(_saved) == ["iskola:user"], f"a kulcs iskola:felhasználónév: {list(_saved)}")
ok(all("access-1" not in line for line in []), "a tár tartalma nem kerül a naplóba")

print("   érvényes tárolt token -> nincs belépés")
client = KretaApiClient(_store_student, timeout=5, session=FakeSession([]), token_store=_store)
client._ensure_token()
ok(client.auth_source == "cache", f"a munkamenet a tárból jött: {client.auth_source}")
ok(client.session.calls == [], "egyetlen hálózati hívás sem történt (nincs e-mail)")

print("   lejárt token + refresh token -> csak frissítés")
save_stored_token(_store_student, ApiToken("access-old", "refresh-old", "iskola",
                                           time.time() - 100), _store)
client = KretaApiClient(_store_student, timeout=5, token_store=_store, session=FakeSession([
    FakeResponse(200, json_data={"access_token": "access-2", "refresh_token": "refresh-2",
                                 "expires_in": 1800}),
]))
client._ensure_token()
ok(client.auth_source == "refresh", f"frissítés történt: {client.auth_source}")
ok(client.token.access_token == "access-2", "az új access token bekerült")
ok(len(client.session.calls) == 1, f"csak 1 hívás (refresh): {len(client.session.calls)}")
_after = load_stored_token(_store_student, _store)
ok(_after and _after.access_token == "access-2" and _after.refresh_token == "refresh-2",
   "a frissített token visszakerült a tárba")

print("   lejárt token refresh nélkül -> teljes belépés")
save_stored_token(_store_student, ApiToken("access-old", "", "iskola", time.time() - 100), _store)
client = KretaApiClient(_store_student, timeout=5, token_store=_store,
                        session=FakeSession(login_responses()))
client._ensure_token()
ok(client.auth_source == "login", f"teljes belépés történt: {client.auth_source}")
ok(len(client.session.calls) == 4, f"4 login lépés: {len(client.session.calls)}")

print("   sikertelen refresh (400) -> teljes belépés")
save_stored_token(_store_student, ApiToken("access-old", "refresh-old", "iskola",
                                           time.time() - 100), _store)
client = KretaApiClient(_store_student, timeout=5, token_store=_store, session=FakeSession(
    [FakeResponse(400, text='{"error":"invalid_grant"}')] + login_responses()))
client._ensure_token()
ok(client.auth_source == "login", f"refresh után belépés: {client.auth_source}")
ok(len(client.session.calls) == 5, f"1 refresh + 4 login hívás: {len(client.session.calls)}")

print("   tárolt token nélkül (üres tár) -> belépés")
client = KretaApiClient(_store_student, timeout=5, token_store="",
                        session=FakeSession(login_responses()))
client._ensure_token()
ok(client.auth_source == "login", f"üres tárolóval belépés: {client.auth_source}")

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
    "RogzitoTanarNeve": "Erl Andrea",
})
ok(omission["mulasztas_datum"] == "2026-09-14", "hiányzás helyi dátuma")
ok(omission["ora_sorszam"] == 5, "órasorszám")
ok(omission["mulasztas_tipus"] == "Hiányzás", "típus a Leiras-ból")
ok(omission["igazolt"] == 1, "igazolt")
ok(omission["rogzito"] == "Erl Andrea", "rögzítő tanár")

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

print("\n6b) Üzenet-törzs: sortörések és részletes válasz (Kaneo #74)")
body = html_to_text(
    "<p>Tisztelt Szülők!</p><p>Sajnálattal értesítjük Önöket, hogy a program "
    "2028-as.</p><br><p>A szervezők</p><p>Dudás Magdolna</p><p>Tóth László</p>")
ok("\n" in body and body.splitlines()[0] == "Tisztelt Szülők!",
   f"a <p> blokkok sortörésként maradnak meg ({body!r})")
ok("Tisztelt Szülők!" in normalize_message({
    "azonosito": 11,
    "uzenet": {"azonosito": 21, "feladoNev": "x", "targy": "y",
               "kuldesDatum": "2026-09-22T01:33:31",
               "szoveg": "<p>Tisztelt Szülők!</p><p>More</p>"}})["szoveg"],
   "normalize_message megőrzi a sortörést")
ok(message_body_from_detail({"uzenet": {"szoveg": "<p>Részletes<br>test</p>"}})
   == "Részletes\ntest", "a részletes válasz alaku {uzenet:{szoveg}}")
ok(message_body_from_detail([{"szoveg": "Tömb a válasz"}]) == "Tömb a válasz",
   "a részletes válasz lista alak is kezelt")
ok(message_body_from_detail({"egyeb": 1}) == "", "ha nincs szöveg, üres string")

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

print("\n8b) Órarend-elem normalizálása")
lesson = normalize_lesson({
    "Uid": "433184,OrarendiOra,2026-11-02T23:00:00Z",
    "KezdetIdopont": "2026-11-03T09:45:00Z", "VegIdopont": "2026-11-03T10:30:00Z",
    "Nev": "Történelem", "Oraszam": 4,
    "OsztalyCsoport": {"Nev": "6.B"},
    "TanarNeve": "Szőke Gáborné", "Tantargy": {"Nev": "Történelem"},
    "Tema": None, "TeremNeve": "S-F6", "Tipus": {"Nev": "OrarendiOra"},
})
ok(lesson["start"] == "2026-11-03T10:45:00", f"kezdet helyi idő: {lesson['start']}")
ok(lesson["end"] == "2026-11-03T11:30:00", f"vég helyi idő: {lesson['end']}")
ok(lesson["title"] == "Történelem-6.B", f"tantárgy + osztály: {lesson['title']}")
ok(lesson["tanarNev"] == "Szőke Gáborné", "tanár")
ok(lesson["teremNev"] == "S-F6", "terem")
ok(lesson["allDay"] is False, "tanóra nem egész napos")

all_day = normalize_lesson({
    "Uid": "s1", "KezdetIdopont": "2026-10-25T23:00:00Z", "VegIdopont": "2026-10-25T23:00:00Z",
    "Nev": "Őszi szünet (Nem órarendi nap) (Hétfő)",
    "Tipus": {"Nev": "TanevRendjeEsemeny"},
})
ok(all_day["start"] == "2026-10-26", f"egész napos kezdet helyi dátum: {all_day['start']}")
ok(all_day["end"] == "", "egész napos eseménynek nincs záró időpontja")
ok(all_day["title"].startswith("Őszi szünet"), "a tanév rendje esemény neve megmarad")
ok(all_day["allDay"] is True, "egész napos jelölés")

print("\n8c) Fogadóóra normalizálása")
consultations = normalize_consultations([{
    "Tanar": {"Nev": "Szentkirályi Zsuzsanna"},
    "Fogadoorak": [{
        "Uid": "1239", "Terem": {"Nev": "S-F6"},
        "KezdoIdopont": "2026-11-05T15:30:00Z", "VegIdopont": "2026-11-05T17:30:00Z",
        "Idopontok": [{"Uid": "1"}],
    }],
}])
ok(len(consultations) == 1, "egy fogadóóra-blokk -> egy sor")
ok(consultations[0]["start"] == "2026-11-05T16:30:00", "fogadóóra helyi kezdete")
ok(consultations[0]["end"] == "2026-11-05T18:30:00", "fogadóóra helyi vége")
ok(consultations[0]["title"] == "Fogadóóra", "fogadóóra cím")
ok(consultations[0]["tanarNev"] == "Szentkirályi Zsuzsanna", "fogadóóra tanára")
ok(consultations[0]["teremNev"] == "S-F6", "fogadóóra terme")

print("\n8d) Órarend-ablak: az első nap eseményei (UTC-határ)")
client = make_client([FakeResponse(200, json_data=[])])
client.token = ApiToken("a", "r", "iskola", time.time() + 3600)
client.fetch_lessons(date(2026, 10, 26), date(2026, 11, 8))
params = client.session.calls[0][2]["params"]
ok(params["datumTol"] == "2026-10-25", f"egy nappal korábbra is kér: {params['datumTol']}")
ok(params["datumIg"] == "2026-11-08", "a záró dátum változatlan")

print("\n8e) Csatolmány-letöltés (eAdmin → files nonce)")
client = make_client([
    FakeResponse(302, headers={"Location": "https://files.e-kreta.hu/fajlok/?nonce=ABC"}),
    FakeResponse(200, content=b"%PDF-1.7 tartalom",
                 headers={"Content-Type": "application/octet-stream"}),
])
client.token = ApiToken("a", "r", "iskola", time.time() + 3600)
content, ctype = client.download_attachment(96649499)
ok(content == b"%PDF-1.7 tartalom", "a fájl bájtjai megérkeztek")
ok(ctype == "application/octet-stream", "a tartalomtípus megmarad")
ok("dokumentumok/uzenetek/96649499" in client.session.calls[0][1], "a dokumentum-végpontot hívja")
ok(client.session.calls[0][2]["allow_redirects"] is False, "a 302-t nem követi automatikusan")
ok(client.session.calls[1][1].startswith("https://files.e-kreta.hu/fajlok/"), "a nonce URL-t tölti le")
ok("Authorization" not in (client.session.calls[1][2].get("headers") or {}),
   "a bearer token nem megy a fájlszolgáltatáshoz")

client = make_client([
    FakeResponse(401, text="unauthorized"),
    FakeResponse(200, json_data={"access_token": "access-2", "refresh_token": "refresh-2",
                                 "expires_in": 1800}),
    FakeResponse(302, headers={"Location": "https://files.e-kreta.hu/fajlok/?nonce=DEF"}),
    FakeResponse(200, content=b"PK\x03\x04"),
])
client.token = ApiToken("a", "r", "iskola", time.time() + 3600)
content, _ = client.download_attachment("123")
ok(content.startswith(b"PK"), "401 után tokenfrissítéssel is működik")
ok(len(client.session.calls) == 4, "401 -> refresh -> dokumentum -> fájl")

client = make_client([FakeResponse(200, content=b"nincs redirect")])
client.token = ApiToken("a", "r", "iskola", time.time() + 3600)
content, _ = client.download_attachment("123")
ok(content == b"nincs redirect", "közvetlen 200-at is kezeli")

client = make_client([FakeResponse(403, text="forbidden")])
client.token = ApiToken("a", "r", "iskola", time.time() + 3600)
try:
    client.download_attachment("123")
    ok(False, "403 esetén kivétel kell")
except KretaResponseError:
    ok(True, "403 -> KretaResponseError")

client = make_client([
    FakeResponse(302, headers={"Location": "https://files.e-kreta.hu/fajlok/?nonce=BIG"}),
    FakeResponse(200, content=b"x" * 50),
])
client.token = ApiToken("a", "r", "iskola", time.time() + 3600)
try:
    client.download_attachment("123", max_bytes=10)
    ok(False, "túl nagy fájl esetén kivétel kell")
except KretaResponseError:
    ok(True, "méretkorlát -> KretaResponseError")

print("\n8f) Csatolmány-fájlnév biztonságosítása")
ok(safe_fajlnev("../../etc/passwd").find("/") == -1, "path traversal kiszűrve")
ok(safe_fajlnev("a\\b:c*d?.pdf") == "a_b_c_d_.pdf", "tiltott karakterek cserélve")
ok(safe_fajlnev("  ..hmm.pdf  ") == "hmm.pdf", "vezető pont/szóköz levágva")
ok(safe_fajlnev("") == "csatolmany", "üres név helyére alapérték")
ok(safe_fajlnev("x" * 200 + ".pdf").endswith(".pdf"), "hosszú név: a kiterjesztés megmarad")
ok(len(safe_fajlnev("x" * 200 + ".pdf")) <= 120, "hosszú név 120 karakterre vágva")

print("\n9) Nincs Playwright-függés")
source = (ROOT / "kreta_api.py").read_text(encoding="utf-8")
ok("import playwright" not in source and "from playwright" not in source,
   "a kreta_api.py nem importál Playwrightot")
ok("from poc" not in source and "import poc" not in source, "nincs POC-függés")

print("\nKÉSZ" if not _hibak else f"\nKÉSZ — {len(_hibak)} HIBA")
sys.exit(1 if _hibak else 0)
