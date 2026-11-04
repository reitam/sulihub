# -*- coding: utf-8 -*-
"""
AI-alapú üzenet-/dokumentumelemzés — Kaneo #61.

OpenAI-kompatibilis chat-completions végpontot használ (helyi **Ollama**
alapértelmezéssel), és az üzenet szövegéből/dokumentumából eseményeket,
határidőket nyer ki. A kimenet szigorúan validált JSON-lista; a modul
Flask-független, így fake HTTP-szerverrel tesztelhető.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import kreta_tanev

DEFAULTS = {
    "ENABLED": True,
    "URL": "http://127.0.0.1:11434",
    "MODEL": "qwen3:0.6b",
    "API_KEY": "",
    "TIMEOUT_SECONDS": 60,
    "MAX_INPUT_CHARS": 6000,
    "ALLOW_CLOUD": False,
}

MAX_ITEMS = 20
_PRIVATE_HOSTS = ("localhost", "127.", "10.", "192.168.", "::1")


class AiError(RuntimeError):
    """AI hiba (a hívó 502/503-at ad rá)."""


class AiNotConfigured(AiError):
    """Nincs bekapcsolva / hiányos a konfiguráció."""


def ai_config(config: dict | None = None) -> dict:
    block = (config or {}).get("AI") or {}
    cfg = dict(DEFAULTS)
    if isinstance(block, dict):
        for key in DEFAULTS:
            if key in block and block[key] not in (None, ""):
                cfg[key] = block[key]
    try:
        cfg["TIMEOUT_SECONDS"] = max(5, min(300, int(cfg["TIMEOUT_SECONDS"])))
    except (TypeError, ValueError):
        cfg["TIMEOUT_SECONDS"] = DEFAULTS["TIMEOUT_SECONDS"]
    try:
        cfg["MAX_INPUT_CHARS"] = max(500, min(50000, int(cfg["MAX_INPUT_CHARS"])))
    except (TypeError, ValueError):
        cfg["MAX_INPUT_CHARS"] = DEFAULTS["MAX_INPUT_CHARS"]
    cfg["URL"] = str(cfg["URL"]).strip().rstrip("/")
    cfg["MODEL"] = str(cfg["MODEL"]).strip()
    cfg["ENABLED"] = bool(cfg["ENABLED"])
    cfg["ALLOW_CLOUD"] = bool(cfg["ALLOW_CLOUD"])
    return cfg


def _is_private_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in ("localhost", "::1"):
        return True
    if any(host.startswith(prefix) for prefix in _PRIVATE_HOSTS):
        return True
    # 172.16.0.0 – 172.31.255.255
    if re.match(r"^172\.(1[6-9]|2\d|3[01])\.", host):
        return True
    return False


def _clean_json(content: str) -> str:
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        raise AiError("Az AI válasza nem tartalmaz JSON-listát.")
    return text[start:end + 1]


def _norm_date(value) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _norm_time(value) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in ("null", "none", "-"):
        return None
    match = re.match(r"^(\d{1,2}):(\d{2})", text)
    if not match:
        return None
    ora, perc = int(match.group(1)), int(match.group(2))
    if ora > 23 or perc > 59:
        return None
    return f"{ora:02d}:{perc:02d}"


def parse_items(content: str, today: date | None = None) -> list[dict]:
    """Az AI válaszából validált eseménylista (maximum 20, dátum nélkül kimarad)."""
    raw = json.loads(_clean_json(content))
    if not isinstance(raw, list):
        raise AiError("Az AI válasza nem lista.")
    today = today or date.today()
    items = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        cim = str(entry.get("cim") or entry.get("title") or "").strip()
        day = _norm_date(entry.get("datum") or entry.get("date"))
        if not cim or not day:
            continue
        ido = _norm_time(entry.get("ido") or entry.get("time"))
        key = (cim.lower(), day.isoformat(), ido or "")
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "cim": cim[:150],
            "datum": day.isoformat(),
            "ido": ido,
            "helyszin": str(entry.get("helyszin") or entry.get("location") or "").strip()[:120],
            "leiras": str(entry.get("leiras") or entry.get("description") or "").strip()[:800],
            "multbeli": day < today,
        })
        if len(items) >= MAX_ITEMS:
            break
    items.sort(key=lambda item: (item["datum"], item["ido"] or "99:99"))
    return items


def analyze_text(text: str, cfg: dict, today: date | None = None) -> list[dict]:
    """A szöveget elküldi az AI-nak, és validált eseménylistát ad vissza."""
    if not cfg.get("ENABLED"):
        raise AiNotConfigured("Az AI-elemzés nincs bekapcsolva (AI.ENABLED=false).")
    if not cfg.get("URL") or not cfg.get("MODEL"):
        raise AiNotConfigured("Hiányzik az AI URL vagy MODEL beállítás.")
    if not cfg.get("ALLOW_CLOUD") and not _is_private_url(cfg["URL"]):
        raise AiNotConfigured(
            "Felhős AI csak ALLOW_CLOUD=true mellett engedett (gyerekadat-védelem).")

    text = (text or "").strip()
    if not text:
        raise AiError("Nincs elemezhető szöveg.")
    text = text[:int(cfg["MAX_INPUT_CHARS"])]
    today = today or date.today()
    prompt = (
        f"Ma: {today.isoformat()}.\n"
        "Elemezd az alábbi üzenetet/dokumentumot, és keresd ki a konkrét "
        "eseményeket és határidőket (dátum, lehetőleg idő is).\n"
        "Csak JSON-tömböt adj vissza, semmilyen más szöveget:\n"
        '[{"cim":"rövid cím","datum":"YYYY-MM-DD","ido":"HH:MM vagy null",'
        '"helyszin":"helyszín vagy üres","leiras":"rövid kivonat"}]\n'
        "Ha nincs esemény/határidő, adj vissza üres listát: [].\n\n"
        "Szöveg:\n" + text
    )
    body = {
        "model": cfg["MODEL"],
        "messages": [
            {"role": "system", "content": "Csak érvényes JSON-t adsz vissza. Magyar nyelvű vagy."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0,
    }
    headers = {"Content-Type": "application/json"}
    if cfg.get("API_KEY"):
        headers["Authorization"] = "Bearer " + str(cfg["API_KEY"])
    req = Request(cfg["URL"] + "/v1/chat/completions",
                  data=json.dumps(body).encode("utf-8"),
                  headers=headers, method="POST")
    try:
        with urlopen(req, timeout=int(cfg["TIMEOUT_SECONDS"])) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except AiError:
        raise
    except Exception as exc:  # noqa: BLE001 — hálózati/időtúllépés
        raise AiError(f"Az AI nem érhető el: {type(exc).__name__}") from exc

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AiError("Az AI válaszának formátuma ismeretlen.")
    try:
        return parse_items(content, today=today)
    except json.JSONDecodeError as exc:
        raise AiError("Az AI válasza nem érvényes JSON.") from exc


def build_text(subject: str, body: str, attachment_text: str = "") -> str:
    parts = []
    if subject:
        parts.append("Tárgy: " + str(subject).strip())
    if body:
        parts.append("Üzenet:\n" + str(body).strip())
    if attachment_text:
        parts.append("Csatolmány szövege:\n" + str(attachment_text).strip())
    return "\n\n".join(parts)


def today_tag() -> str:
    return kreta_tanev.today().isoformat()
