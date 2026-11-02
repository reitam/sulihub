# -*- coding: utf-8 -*-
"""
KRÉTA mobil API kliens (termelési modul).

A POC-ban (`spike/kreta-mobile-api`) bizonyított böngésző nélküli login és a
mobil v3 / eAdmin végpontok termelési változata. Nem használ Playwrightot, és
nem függ a `poc/` könyvtártól.

A modul két réteget ad:
- `KretaApiClient`: hitelesítés, tokenfrissítés, végpontok nyers adatokkal;
- normalizáló függvények: a KRÉTA válaszokból a meglévő DB-sémáknak megfelelő
  sorok (hianyzasok, igazolasok, esemenyek, uzenetek).

Titok (jelszó/token) soha nem kerül naplóba.
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterator
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests

IDP = "https://idp.e-kreta.hu"
CLIENT_ID = "kreta-ellenorzo-student-mobile-ios"
CODE_VERIFIER = "DSpuqj_HhDX4wzQIbtn8lr8NLE5wEi1iVLMtMK0jY6c"
REDIRECT_URI = "https://mobil.e-kreta.hu/ellenorzo-student/prod/oauthredirect"

LOGIN_RETURN_URL = (
    "/connect/authorize/callback?prompt=login&nonce=wylCrqT4oN6PPgQn2yQB0euKei9nJeZ6_ffJ-VpSKZU"
    "&response_type=code&code_challenge_method=S256"
    "&scope=openid%20email%20offline_access%20kreta-ellenorzo-webapi.public"
    "%20kreta-eugyintezes-webapi.public%20kreta-fileservice-webapi.public"
    "%20kreta-mobile-global-webapi.public%20kreta-dkt-webapi.public"
    "%20kreta-ier-webapi.public"
    "&code_challenge=HByZRRnPGb-Ko_wTI7ibIba1HQ6lor0ws4bcgReuYSQ"
    "&redirect_uri=https%3A%2F%2Fmobil.e-kreta.hu%2Fellenorzo-student%2Fprod%2Foauthredirect"
    "&client_id=kreta-ellenorzo-student-mobile-ios"
    "&state=kreten_student_mobile&suppressed_prompt=login"
)

LOGIN_PAGE_URL = (
    "https://idp.e-kreta.hu/Account/Login?ReturnUrl="
    "%2Fconnect%2Fauthorize%2Fcallback%3Fprompt%3Dlogin"
    "%26nonce%3DwylCrqT4oN6PPgQn2yQB0euKei9nJeZ6_ffJ-VpSKZU"
    "%26response_type%3Dcode%26code_challenge_method%3DS256"
    "%26scope%3Dopenid%2520email%2520offline_access"
    "%2520kreta-ellenorzo-webapi.public%2520kreta-eugyintezes-webapi.public"
    "%2520kreta-fileservice-webapi.public%2520kreta-mobile-global-webapi.public"
    "%2520kreta-dkt-webapi.public%2520kreta-ier-webapi.public"
    "%26code_challenge%3DHByZRRnPGb-Ko_wTI7ibIba1HQ6lor0ws4bcgReuYSQ"
    "%26redirect_uri%3Dhttps%253A%252F%252Fmobil.e-kreta.hu"
    "%252Fellenorzo-student%252Fprod%252Foauthredirect"
    "%26client_id%3Dkreta-ellenorzo-student-mobile-ios"
    "%26state%3Dkreten_student_mobile%26suppressed_prompt%3Dlogin"
)

CALLBACK_URL = (
    f"{IDP}/connect/authorize/callback?prompt=login"
    "&nonce=wylCrqT4oN6PPgQn2yQB0euKei9nJeZ6_ffJ-VpSKZU"
    "&response_type=code&code_challenge_method=S256"
    "&scope=openid%20email%20offline_access%20kreta-ellenorzo-webapi.public"
    "%20kreta-eugyintezes-webapi.public%20kreta-fileservice-webapi.public"
    "%20kreta-mobile-global-webapi.public%20kreta-dkt-webapi.public"
    "%20kreta-ier-webapi.public"
    "&code_challenge=HByZRRnPGb-Ko_wTI7ibIba1HQ6lor0ws4bcgReuYSQ"
    "&redirect_uri=https%3A%2F%2Fmobil.e-kreta.hu%2Fellenorzo-student%2Fprod%2Foauthredirect"
    "&client_id=kreta-ellenorzo-student-mobile-ios"
    "&state=kreten_student_mobile&suppressed_prompt=login"
)
LOGIN_POST_URL = f"{IDP}/account/login"
TOKEN_URL = f"{IDP}/connect/token"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MOBILE_UA = "hu.ekreta.tanulo/1.0.5/Android/0/0"
API_KEY = "21ff6c25-d1da-4a68-a811-c881a6057463"
EADMIN_BASE = "https://eugyintezes.e-kreta.hu/api/v1"

LOCAL_TZ = ZoneInfo("Europe/Budapest")
CHUNK_DAYS = 20  # a KRÉTA max. 3 hét / 1 hónap; 20 nap biztonságos

# Csatolmány-letöltés felső korlátja (a KRÉTA fájlok jellemzően < 5 MB).
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
_FAJLNEV_TILTOTT = '<>:"/\\|?*'

# ── Token-tár (munkamenet-gyorsítás, 2026-11-01) ────────────────────────────
# A KRÉTA minden ÚJ belépésről e-mailt küld („Új bejelentkezésről értesítés").
# A Playwright-os megoldásnál ezt a perzisztens böngészőprofil kerülte el; az
# API-nál a refresh tokent tároljuk a data köteten, így egy szinkron sem lép be
# újra, amíg a refresh token él (a hozzáférési token 30 percenként frissül).
_DATA_DIR = os.environ.get("KRETA_DATA_DIR", ".")
TOKEN_STORE_FILE = (os.environ.get("KRETA_API_TOKEN_FILE")
                    or os.path.join(_DATA_DIR, "api_tokens.json"))

_LOG_HOOK = None


def set_log_hook(func) -> None:
    """Naplózó hook (a scraper `log()`-ját állítja be); önálló használatnál néma."""
    global _LOG_HOOK
    _LOG_HOOK = func


def _log(message: str) -> None:
    if not _LOG_HOOK:
        return
    try:
        _LOG_HOOK(message)
    except Exception:  # noqa: BLE001 — a naplózás ne borítsa a futást
        pass


def _token_key(student: dict) -> str:
    return f"{_text(student.get('institute_code'))}:{_text(student.get('username'))}"


def load_stored_token(student: dict, path: str | None = None) -> ApiToken | None:
    """A korábbi futásból eltárolt token (ha van és olvasható)."""
    store_path = TOKEN_STORE_FILE if path is None else path
    if not store_path:
        return None
    try:
        with open(store_path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    entry = (data or {}).get(_token_key(student))
    if not isinstance(entry, dict) or not entry.get("access_token"):
        return None
    return ApiToken(
        access_token=_text(entry.get("access_token")),
        refresh_token=_text(entry.get("refresh_token")),
        institute_code=_text(entry.get("institute_code"))
        or _text(student.get("institute_code")),
        expires_at=float(entry.get("expires_at") or 0),
        token_type=_text(entry.get("token_type")) or "Bearer",
    )


def save_stored_token(student: dict, token: ApiToken, path: str | None = None) -> None:
    """A token mentése (atomikusan, 600-as jogosultsággal, ahol lehet)."""
    store_path = TOKEN_STORE_FILE if path is None else path
    if not store_path or token is None:
        return
    try:
        try:
            with open(store_path, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data[_token_key(student)] = {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
            "institute_code": token.institute_code,
            "expires_at": token.expires_at,
            "token_type": token.token_type,
            "saved_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        }
        directory = os.path.dirname(os.path.abspath(store_path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = f"{store_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass  # Windows: a jogosultság a könyvtárén múlik
        os.replace(tmp_path, store_path)
    except OSError as exc:
        _log(f"    [API] a token mentése nem sikerült: {exc}")

_RVT_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')
_RVT_RE_ALT = re.compile(r'value="([^"]+)"[^>]*name="__RequestVerificationToken"')


class KretaApiError(RuntimeError):
    """Az API-kliens hibáinak közös őse."""


class KretaAuthError(KretaApiError):
    """Sikertelen belépés vagy tokenfrissítés."""


class KretaNetworkError(KretaApiError):
    """Hálózati hiba (timeout, kapcsolat)."""


class KretaResponseError(KretaApiError):
    """Nem 200-as válasz vagy értelmezhetetlen JSON."""


@dataclass
class ApiToken:
    access_token: str
    refresh_token: str
    institute_code: str
    expires_at: float
    token_type: str = "Bearer"

    def is_expired(self, margin: int = 60) -> bool:
        return time.time() >= (self.expires_at - margin)


# ── Segédfüggvények ─────────────────────────────────────────────────────────
def chunk_date_range(start: date, end: date, days: int = CHUNK_DAYS) -> Iterator[tuple[date, date]]:
    """Átfedés nélküli, legfeljebb `days` napos szeletek (a KRÉTA limit miatt)."""
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=days - 1), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _nev(value) -> str:
    if isinstance(value, dict):
        return _text(value.get("Nev"))
    return _text(value)


def _descriptor(value, prefer=("Leiras", "Nev")) -> str:
    if isinstance(value, dict):
        for key in prefer:
            text = _text(value.get(key))
            if text:
                return text
    return _text(value)


def _int_or_zero(value) -> int:
    """Egész szám tűréssel (az API néha számot, néha sztringet ad, néha null-t)."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def plain_text(value) -> str:
    """HTML-ből sima szöveg (blokk-határoknál szóközzel)."""
    text = "" if value is None else str(value)
    text = re.sub(r"</(p|div|li|tr|h[1-6]|td|th)>", " ", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(html_lib.unescape(text).split())


def _local_moment(value) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(LOCAL_TZ)
    return moment


def iso_date(value) -> str:
    """ISO/UTC datetime -> helyi 'YYYY-MM-DD' (a hianyzasok/igazolasok sémához)."""
    if isinstance(value, datetime):
        moment = value
        if moment.tzinfo is not None:
            moment = moment.astimezone(LOCAL_TZ)
        return moment.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _text(value)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-" and "T" not in text:
        return text[:10]
    moment = _local_moment(text)
    return moment.date().isoformat() if moment else text[:10]


def hu_date(value) -> str:
    """Dátum 'YYYY. MM. DD.' alakban (az esemenyek tábla meglévő formátuma)."""
    day = iso_date(value)
    if len(day) == 10 and day[4] == "-" and day[7] == "-":
        return f"{day[:4]}. {day[5:7]}. {day[8:10]}."
    return day


def hu_datetime(value) -> str:
    """Helyi idő 'YYYY. MM. DD. H:MM' alakban (az uzenetek meglévő formátuma).

    Az eAdmin üzenetlista ideje már helyi idő, ezért itt nincs UTC-átváltás.
    """
    text = _text(value)
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return (
        f"{moment.year}. {moment.month:02d}. {moment.day:02d}. "
        f"{moment.hour}:{moment.minute:02d}"
    )


def safe_fajlnev(name, default: str = "csatolmany") -> str:
    """A KRÉTA-ból jövő fájlnév biztonságossá tétele mentés előtt.

    - path traversal és elválasztók (`/`, `\\`) nem maradhatnak benne;
    - Windows-on tiltott karakterek `_`-ra cserélődnek;
    - a vezető pontok/szóközök eltűnnek, a hossz 120 karakterre vágva
      (a kiterjesztés megmarad).
    """
    text = _text(name)
    for char in _FAJLNEV_TILTOTT:
        text = text.replace(char, "_")
    text = " ".join(text.split()).lstrip(". ").strip()
    if not text:
        return default
    if len(text) > 120:
        stem, dot, ext = text.rpartition(".")
        if dot and 0 < len(ext) <= 8:
            text = (stem[: 120 - len(ext) - 1] + "." + ext).strip(" .")
        else:
            text = text[:120].strip(" .")
    return text or default


def _bool_igazolt(igazolas_tipus: str, allapot: str) -> int:
    low = allapot.casefold()
    if "igazolatlan" in low or "igazolando" in low or "nem igazolt" in low:
        return 0
    if "igazolt" in low:
        return 1
    return 1 if igazolas_tipus else 0


# ── Kliens ──────────────────────────────────────────────────────────────────
class KretaApiClient:
    """Egy diák mobil API kliense. Használható context managerként."""

    def __init__(self, student: dict, timeout: int = 30, session: requests.Session | None = None,
                 token_store: str | None = None):
        self.student = student
        self.timeout = timeout
        self.session = session or requests.Session()
        self.token: ApiToken | None = None
        # None = alapértelmezett tár (data kötet); "" = nincs perzisztencia.
        self.token_store = TOKEN_STORE_FILE if token_store is None else token_store
        self.auth_source = "none"  # none | cache | refresh | login

    # -- életciklus --
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        self.session.close()

    # -- hitelesítés --
    def login(self) -> ApiToken:
        username = _text(self.student.get("username"))
        password = _text(self.student.get("password"))
        institute = _text(self.student.get("institute_code"))
        if not username or not password or not institute:
            raise KretaAuthError("Hiányzó username/password/institute_code.")

        self.session.headers.update({"User-Agent": BROWSER_UA})
        try:
            response = self.session.get(LOGIN_PAGE_URL, timeout=self.timeout)
        except requests.RequestException as exc:
            raise KretaNetworkError(f"Login oldal nem érhető el: {exc}") from exc
        if response.status_code != 200:
            raise KretaResponseError(f"Login oldal HTTP {response.status_code}.")

        match = _RVT_RE.search(response.text) or _RVT_RE_ALT.search(response.text)
        if not match:
            raise KretaAuthError("A login oldalon nincs __RequestVerificationToken.")
        rvt = match.group(1)

        time.sleep(0.5)
        try:
            response = self.session.post(
                LOGIN_POST_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "ReturnUrl": LOGIN_RETURN_URL,
                    "IsTemporaryLogin": False,
                    "UserName": username,
                    "Password": password,
                    "InstituteCode": institute,
                    "loginType": "InstituteLogin",
                    "__RequestVerificationToken": rvt,
                },
                allow_redirects=False,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise KretaNetworkError(f"Belépés nem sikerült: {exc}") from exc
        if response.status_code not in (200, 302):
            raise KretaAuthError(f"Belépés HTTP {response.status_code}.")

        try:
            response = self.session.get(CALLBACK_URL, allow_redirects=False, timeout=self.timeout)
        except requests.RequestException as exc:
            raise KretaNetworkError(f"Callback nem érhető el: {exc}") from exc
        location = response.headers.get("location", "")
        code = parse_qs(urlparse(location).query).get("code", [])
        if not code:
            raise KretaAuthError("Nem érkezett authorization code (rossz jelszó?).")

        try:
            response = self.session.post(
                TOKEN_URL,
                data={
                    "code": code[0],
                    "code_verifier": CODE_VERIFIER,
                    "redirect_uri": REDIRECT_URI,
                    "client_id": CLIENT_ID,
                    "grant_type": "authorization_code",
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise KretaNetworkError(f"Token kérése nem sikerült: {exc}") from exc
        if response.status_code != 200:
            raise KretaAuthError(f"Token HTTP {response.status_code}.")

        data = response.json()
        if not data.get("access_token"):
            raise KretaAuthError("A tokenválaszban nincs access_token.")
        self.token = ApiToken(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            institute_code=institute,
            expires_at=time.time() + int(data.get("expires_in", 1800)),
            token_type=data.get("token_type", "Bearer"),
        )
        self.auth_source = "login"
        save_stored_token(self.student, self.token, self.token_store)
        return self.token

    def refresh(self) -> ApiToken:
        if self.token is None or not self.token.refresh_token:
            raise KretaAuthError("Nincs refresh token a frissítéshez.")
        try:
            response = self.session.post(
                TOKEN_URL,
                data={
                    "institute_code": self.token.institute_code,
                    "refresh_token": self.token.refresh_token,
                    "grant_type": "refresh_token",
                    "client_id": CLIENT_ID,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise KretaNetworkError(f"Tokenfrissítés nem sikerült: {exc}") from exc
        if response.status_code != 200:
            raise KretaAuthError(f"Tokenfrissítés HTTP {response.status_code}.")
        data = response.json()
        self.token.access_token = data.get("access_token", self.token.access_token)
        self.token.refresh_token = data.get("refresh_token", self.token.refresh_token)
        self.token.expires_at = time.time() + int(data.get("expires_in", 1800))
        self.auth_source = "refresh"
        save_stored_token(self.student, self.token, self.token_store)
        return self.token

    def _ensure_token(self) -> None:
        if self.token is None:
            self._restore_or_login()
        elif self.token.is_expired():
            self._refresh_or_login()

    def _restore_or_login(self) -> None:
        """Tárolt token → refresh → (ha kell) teljes belépés.

        A KRÉTA minden új belépésről e-mailt küld, ezért a cél, hogy a tárolt
        refresh tokennel menjen a futás; teljes belépés csak akkor, ha nincs
        (vagy lejárt/visszavont) a token.
        """
        stored = load_stored_token(self.student, self.token_store)
        if stored is not None:
            self.token = stored
            if not stored.is_expired():
                self.auth_source = "cache"
                _log("    [API] munkamenet a tárolt tokenből (nincs új belépés)")
                return
            try:
                self.refresh()
                _log("    [API] munkamenet frissítve refresh tokennel (nincs új belépés)")
                return
            except (KretaAuthError, KretaResponseError, KretaNetworkError) as exc:
                _log(f"    [API] tokenfrissítés nem sikerült, új belépés következik "
                     f"({type(exc).__name__})")
                self.token = None
        self.login()
        _log("    [API] új belépés történt (a KRÉTA erről e-mailt küld)")

    def _refresh_or_login(self) -> None:
        if self.token is not None and self.token.refresh_token:
            try:
                self.refresh()
                return
            except (KretaAuthError, KretaResponseError, KretaNetworkError) as exc:
                _log(f"    [API] tokenfrissítés nem sikerült, új belépés "
                     f"({type(exc).__name__})")
                self.token = None
        self.login()

    def _request(self, url: str, *, params: dict | None = None, headers: dict | None = None,
                 retry_auth: bool = True) -> Any:
        self._ensure_token()
        assert self.token is not None
        request_headers = {
            "Authorization": f"{self.token.token_type} {self.token.access_token}",
            "User-Agent": MOBILE_UA,
            **(headers or {}),
        }
        try:
            response = self.session.get(url, params=params, headers=request_headers,
                                        timeout=self.timeout)
        except requests.RequestException as exc:
            raise KretaNetworkError(f"API hívás nem sikerült: {exc}") from exc

        if response.status_code == 401 and retry_auth:
            self._refresh_or_login()
            return self._request(url, params=params, headers=headers, retry_auth=False)
        if response.status_code != 200:
            body = (response.text or "")[:300].replace("\n", " ")
            raise KretaResponseError(f"HTTP {response.status_code}: {body}")
        try:
            return response.json()
        except ValueError as exc:
            raise KretaResponseError("A válasz nem érvényes JSON.") from exc

    def _api_get(self, path: str, params: dict | None = None) -> Any:
        self._ensure_token()  # az első hívásnál belép, később csak frissít
        assert self.token is not None
        url = f"https://{self.token.institute_code}.e-kreta.hu/ellenorzo/v3/{path.lstrip('/')}"
        return self._request(url, params=params, headers={"apiKey": API_KEY})

    def _eadmin_get(self, path: str, params: dict | None = None) -> Any:
        self._ensure_token()
        url = f"{EADMIN_BASE}/{path.lstrip('/')}"
        return self._request(url, params=params,
                             headers={"X-Uzenet-Lokalizacio": "hu-HU"})

    # -- adatkörök --
    def fetch_omissions(self, start: date, end: date) -> list[dict]:
        items: dict[str, dict] = {}
        for chunk_start, chunk_end in chunk_date_range(start, end):
            data = self._api_get("sajat/Mulasztasok", {
                "datumTol": chunk_start.isoformat(), "datumIg": chunk_end.isoformat(),
            })
            for item in data or []:
                key = str(item.get("Uid") or f"{item.get('Datum')}|{item.get('Ora', {}).get('Oraszam')}")
                items[key] = item
        return list(items.values())

    def fetch_lessons(self, start: date, end: date) -> list[dict]:
        # Az OrarendElemek a KezdetIdopont **UTC** dátuma szerint szűr. A helyi
        # nap 00:00-kor kezdődő egész napos események (tanév rendje: szünetek,
        # munkaszüneti napok) viszont előző napi 23:00Z-ként jönnek, ezért az
        # ablak első napjának eseményei kimaradnának (pl. az őszi szünet hétfője).
        # Egy nappal korábbra is kérünk; a normalizálás helyi dátumra vált.
        items: dict[str, dict] = {}
        padded_start = start - timedelta(days=1)
        for chunk_start, chunk_end in chunk_date_range(padded_start, end):
            data = self._api_get("sajat/OrarendElemek", {
                "datumTol": chunk_start.isoformat(), "datumIg": chunk_end.isoformat(),
            })
            for item in data or []:
                key = str(item.get("Uid") or f"{item.get('KezdetIdopont')}|{item.get('Oraszam')}")
                items[key] = item
        return list(items.values())

    def fetch_evaluations(self, start: date, end: date) -> list[dict]:
        items: dict[str, dict] = {}
        for chunk_start, chunk_end in chunk_date_range(start, end):
            data = self._api_get("sajat/Ertekelesek", {
                "datumTol": chunk_start.isoformat(), "datumIg": chunk_end.isoformat(),
            })
            for item in data or []:
                key = str(item.get("Uid") or f"{item.get('Tantargy')}|{item.get('RogzitesDatuma')}")
                items[key] = item
        return list(items.values())

    def fetch_homeworks(self, start: date, end: date) -> list[dict]:
        return self._fetch_chunked("sajat/HaziFeladatok", start, end, "Uid", "HataridoDatuma")

    def fetch_announced_tests(self, start: date, end: date) -> list[dict]:
        return self._fetch_chunked("sajat/BejelentettSzamonkeresek", start, end, "Uid", "Datum")

    def fetch_notes(self, start: date, end: date) -> list[dict]:
        return self._fetch_chunked("sajat/Feljegyzesek", start, end, "Uid", "Datum")

    def _fetch_chunked(self, path: str, start: date, end: date,
                       id_field: str, fallback_field: str) -> list[dict]:
        items: dict[str, dict] = {}
        for chunk_start, chunk_end in chunk_date_range(start, end):
            data = self._api_get(path, {
                "datumTol": chunk_start.isoformat(), "datumIg": chunk_end.isoformat(),
            })
            for item in data or []:
                key = str(item.get(id_field) or f"{item.get('Tantargy')}|{item.get(fallback_field)}")
                items[key] = item
        return list(items.values())

    def fetch_justifications(self) -> list[dict]:
        data = self._api_get("sajat/Igazolasok")
        return list(data or [])

    def fetch_consultations(self, start: date, end: date) -> list[dict]:
        """Fogadóórák tanáronként (a webes naptár is mutatja őket)."""
        data = self._api_get("sajat/Fogadoorak", {
            "datumTol": start.isoformat(), "datumIg": end.isoformat(),
        })
        return list(data or [])

    def fetch_messages(self) -> list[dict]:
        data = self._eadmin_get("kommunikacio/postaladaelemek/sajat")
        return [
            item for item in (data or [])
            if not item.get("isToroltElem")
            and (item.get("tipus") or {}).get("kod") in (None, "BEERKEZETT")
        ]

    def fetch_message_detail(self, mailbox_id: str | int) -> dict:
        return self._eadmin_get(f"kommunikacio/postaladaelemek/{mailbox_id}")

    def download_attachment(self, attachment_id: str | int,
                            max_bytes: int = MAX_ATTACHMENT_BYTES) -> tuple[bytes, str]:
        """Csatolmány tartalma böngésző nélkül: eAdmin dokumentum → files nonce lánc.

        1. `GET {eAdmin}/dokumentumok/uzenetek/{csatolmanyAzonosito}` bearer tokennel
           → **302** a `https://files.e-kreta.hu/fajlok/?nonce=...` címre;
        2. a nonce URL letöltése — a nonce maga az engedély, ehhez nem kell token,
           ezért külön kérésen megy (a bearer nem szivárog a fájlszolgáltatáshoz).

        Visszaad: `(tartalom, content_type)`. A fájlnevet a hívó adja (a
        `csatolmanyok[].fajlNev` mezőből).
        """
        self._ensure_token()
        assert self.token is not None
        url = f"{EADMIN_BASE}/dokumentumok/uzenetek/{attachment_id}"
        headers = {
            "Authorization": f"{self.token.token_type} {self.token.access_token}",
            "User-Agent": MOBILE_UA,
        }
        try:
            response = self.session.get(url, headers=headers, timeout=self.timeout,
                                        allow_redirects=False)
        except requests.RequestException as exc:
            raise KretaNetworkError(f"Csatolmány-hívás nem sikerült: {exc}") from exc

        if response.status_code == 401:
            self.refresh()
            return self.download_attachment(attachment_id, max_bytes)

        location = _text(response.headers.get("Location"))
        if response.status_code == 200 and not location:
            # ha valaha közvetlenül a fájlt adná vissza
            return self._check_size(response.content, max_bytes), \
                response.headers.get("Content-Type", "application/octet-stream")

        if not location:
            body = (getattr(response, "text", "") or "")[:200].replace("\n", " ")
            raise KretaResponseError(
                f"HTTP {response.status_code}: a csatolmány-link nem érkezett meg ({body})")

        file_url = urljoin(f"{EADMIN_BASE}/", location)
        try:
            file_response = self.session.get(file_url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise KretaNetworkError(f"A fájl letöltése nem sikerült: {exc}") from exc
        if file_response.status_code != 200:
            raise KretaResponseError(
                f"HTTP {file_response.status_code}: a fájl nem tölthető le")
        return (self._check_size(file_response.content, max_bytes),
                file_response.headers.get("Content-Type", "application/octet-stream"))

    @staticmethod
    def _check_size(content: bytes, max_bytes: int) -> bytes:
        if max_bytes and len(content) > max_bytes:
            raise KretaResponseError(
                f"A csatolmány túl nagy ({len(content)} B > {max_bytes} B)")
        if not content:
            raise KretaResponseError("A letöltött csatolmány üres.")
        return content


# ── Normalizálás a meglévő DB-sémákra ───────────────────────────────────────
def normalize_omission(item: dict) -> dict:
    ora = item.get("Ora") or {}
    igazolas_tipus = _descriptor(item.get("IgazolasTipusa"))
    allapot = _text(item.get("IgazolasAllapota"))
    perc_raw = item.get("KesesPercben")
    try:
        perc = int(perc_raw) if perc_raw not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        perc = None
    return {
        "kreta_id": _text(item.get("Uid")),
        "mulasztas_datum": iso_date(item.get("Datum") or ora.get("KezdoDatum")),
        "ora_sorszam": int(ora.get("Oraszam") or 0),
        "perc": perc,
        "tantargy": _nev(item.get("Tantargy")),
        "tema": _text(ora.get("Tema")),
        "tanar": _text(ora.get("TanarNeve")),
        "mulasztas_tipus": _descriptor(item.get("Tipus")) or ("Késés" if perc else "Hiányzás"),
        "igazolt": _bool_igazolt(igazolas_tipus, allapot),
        "tanorai_celu": "",
        "igazolas_tipus": igazolas_tipus,
        "rogzites_datum": iso_date(item.get("KeszitesDatuma")),
        "rogzito": _text(item.get("RogzitoTanarNeve")),
    }


def normalize_lesson(item: dict) -> dict:
    """API órarend-elem -> az `orarend` tábla sorformátuma (a webes egyezéssel).

    - tanóra: helyi `YYYY-MM-DDTHH:MM:SS` kezdet/vég, a tantárgy neve az
      osztály/csoport megnevezésével (`Történelem-6.B`, ahogy a webes naptár);
    - egész napos esemény (tanév rendje): kezdet = helyi dátum, vég = üres.
    """
    start_source = _text(item.get("KezdetIdopont") or item.get("Datum"))
    end_source = _text(item.get("VegIdopont"))
    tipus = _descriptor(item.get("Tipus"))
    all_day = tipus == "TanevRendjeEsemeny" or (start_source and start_source == end_source)

    start = _local_moment(start_source)
    end = _local_moment(end_source)
    tantargy = _nev(item.get("Tantargy"))
    osztaly = _nev(item.get("OsztalyCsoport"))
    title = f"{tantargy}-{osztaly}" if tantargy and osztaly else (tantargy or _text(item.get("Nev")))

    if all_day:
        start_text = start.date().isoformat() if start else start_source[:10]
        end_text = ""
    else:
        start_text = start.strftime("%Y-%m-%dT%H:%M:%S") if start else start_source
        end_text = end.strftime("%Y-%m-%dT%H:%M:%S") if end else end_source

    return {
        "start": start_text,
        "end": end_text,
        "title": title,
        "tanarNev": _text(item.get("TanarNeve")),
        "teremNev": _text(item.get("TeremNeve")),
        "allDay": all_day,
    }


def normalize_consultations(blocks: list[dict]) -> list[dict]:
    """Fogadóóra-blokkok -> az `orarend` tábla sorai (egy tanár / blokk = 1 sor).

    A `/sajat/Fogadoorak` tanáronként adja a fogadóóra-időszakot; a webes naptár
    is ezt mutatja „Fogadóóra” címmel. A 7–10 perces jelentkezési slotok nem
    kerülnek a naptárba.
    """
    rows = []
    for block in blocks or []:
        tanar = _nev(block.get("Tanar"))
        for slot in block.get("Fogadoorak") or []:
            start = _local_moment(slot.get("KezdoIdopont"))
            end = _local_moment(slot.get("VegIdopont"))
            if start is None:
                continue
            rows.append({
                "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%S") if end else "",
                "title": "Fogadóóra",
                "tanarNev": tanar,
                "teremNev": _nev(slot.get("Terem")),
                "allDay": False,
            })
    return rows


def lesson_index(lessons: list[dict]) -> dict[tuple[str, int], list[dict]]:
    index: dict[tuple[str, int], list[dict]] = {}
    for item in lessons:
        day = iso_date(item.get("KezdetIdopont") or item.get("Datum"))
        try:
            ora = int(item.get("Oraszam") or 0)
        except (TypeError, ValueError):
            ora = 0
        if not day or not ora:
            continue
        index.setdefault((day, ora), []).append({
            "tema": _text(item.get("Tema")),
            "tanar": _text(item.get("TanarNeve")),
            "tantargy": _nev(item.get("Tantargy")),
        })
    return index


def pick_lesson(index: dict[tuple[str, int], list[dict]], row: dict) -> dict | None:
    candidates = index.get((row.get("mulasztas_datum", ""), int(row.get("ora_sorszam") or 0))) or []
    if not candidates:
        return None
    subject = _text(row.get("tantargy")).casefold()
    for lesson in candidates:
        if _text(lesson.get("tantargy")).casefold() == subject:
            return lesson
    return candidates[0] if len(candidates) == 1 else None


def normalize_evaluation(item: dict) -> dict:
    return {
        "esemeny_tipus": "Értékelés",
        "tantargy": _nev(item.get("Tantargy")),
        "ertek": _text(item.get("SzovegesErtek")),
        "szam_ertek": int(item.get("SzamErtek") or 0),
        # A jegy súlyszázaléka (pl. 100 = 100%-os súllyal számít az átlagba).
        # Csak a mobil API adja; a webes grid nem tartalmazza.
        "suly_szazalek": _int_or_zero(item.get("SulySzazalekErteke")),
        "bej_datum": hu_date(item.get("RogzitesDatuma") or item.get("KeszitesDatuma")),
        "ertekelo": _text(item.get("ErtekeloTanarNeve")),
        "tipus": _descriptor(item.get("Tipus")),
        "mod": _descriptor(item.get("Mod")),
        "tema": _text(item.get("Tema")),
        "cim": "",
        "tartalom": "",
    }


def normalize_homework(item: dict) -> dict:
    return {
        "esemeny_tipus": "Házi feladat",
        "tantargy": _text(item.get("TantargyNeve")) or _nev(item.get("Tantargy")),
        "ertekelo": _text(item.get("RogzitoTanarNeve")),
        "tartalom": plain_text(item.get("Szoveg")),
        "bej_datum": hu_date(item.get("RogzitesIdopontja") or item.get("FeladasDatuma")),
        "hatarido": hu_date(item.get("HataridoDatuma")),
    }


def normalize_test(item: dict) -> dict:
    return {
        "esemeny_tipus": "Bejelentett számonkérés",
        "tantargy": _text(item.get("TantargyNeve")) or _nev(item.get("Tantargy")),
        "ertekelo": _text(item.get("RogzitoTanarNeve")),
        "mod": _descriptor(item.get("Modja")),
        "tema": _text(item.get("Temaja")),
        "hatarido": hu_date(item.get("Datum")),
        "bej_datum": hu_date(item.get("BejelentesDatuma")),
    }


def normalize_note(item: dict) -> dict:
    return {
        "esemeny_tipus": "Feljegyzés",
        "bej_datum": hu_date(item.get("Datum")),
        "tipus": _descriptor(item.get("Tipus")),
        "ertekelo": _text(item.get("KeszitoTanarNeve")),
        "cim": _text(item.get("Cim")),
        "tartalom": plain_text(item.get("Tartalom")),
    }


def normalize_justification(item: dict) -> dict:
    return {
        "kreta_id": _text(item.get("Id")),
        "kezdete": iso_date(item.get("Kezdete")),
        "vege": iso_date(item.get("Vege")),
        "igazolas_tipus": _descriptor(item.get("Tipusa")),
        "megjegyzes": plain_text(item.get("Megjegyzes")),
    }


def normalize_message(item: dict) -> dict:
    message = item.get("uzenet") or {}
    name = _text(message.get("feladoNev"))
    title = _text(message.get("feladoTitulus"))
    sender = f"{name} ({title})" if title else name
    return {
        "uzenet_id": _text(message.get("azonosito") or item.get("azonosito")),
        "felado": sender,
        "targy": _text(message.get("targy")),
        "idopont": hu_datetime(message.get("kuldesDatum")),
        "szoveg": plain_text(message.get("szoveg")),
        "csatolmanyok": message.get("csatolmanyok") or [],
        "olvasott": bool(item.get("isElolvasva")),
    }
