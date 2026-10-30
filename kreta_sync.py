# -*- coding: utf-8 -*-
"""
Adatforrás-kezelés a KRÉTA szinkronhoz: `SYNC_MODE` és adatkör-szintű fallback.

A szinkron három üzemmódban futhat (config.json `SYNC_MODE`):

- `playwright` (alap): a régi, bevált DOM-scraper út, API nélkül;
- `api`: kizárólag a mobil API (nincs böngésző); ha egy adatkör elhal, az
  a diák részleges hibának számít, de a többi adatkör és diák megy tovább;
- `api_first`: adatkörönként először az API, hiba/timeout/parse hiba esetén
  ugyanarra az adatkörre Playwright fallback.

Ez a modul csak a döntési logikát és a forrás-követést tartalmazza; nem importál
Playwrightot és nem nyúl az adatbázishoz, ezért önállóan tesztelhető.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

DEFAULT_MODE = "playwright"
MODES = ("playwright", "api", "api_first")

# Az adatkörök sorrendje a szinkronban (a UI és a napló is ezt használja).
DATASETS: tuple[tuple[str, str], ...] = (
    ("orarend", "Órarend"),
    ("jegyek", "Jegyek (értékelések)"),
    ("feljegyzesek", "Feljegyzések"),
    ("hazi", "Házi feladatok"),
    ("szamonkeresek", "Bejelentett számonkérések"),
    ("hianyzasok", "Hiányzások, késések"),
    ("igazolasok", "Igazolások"),
    ("uzenetek", "Üzenetek"),
)
LABELS = dict(DATASETS)
DATASET_KEYS = tuple(key for key, _ in DATASETS)
# Az eseménytáblát használó adatkörök (a Playwright ezeket egy blokkban hozza).
EVENT_DATASETS = ("jegyek", "feljegyzesek", "hazi", "szamonkeresek")


def normalize_mode(value: Any) -> str:
    """Érvénytelen/üres érték esetén az alapértelmezett módot adja."""
    text = str(value or "").strip().lower().replace("-", "_")
    return text if text in MODES else DEFAULT_MODE


def resolve_sync_mode(config: dict | None) -> str:
    """A config.json `SYNC_MODE` értéke, normalizálva."""
    return normalize_mode((config or {}).get("SYNC_MODE"))


def needs_api(mode: str) -> bool:
    return normalize_mode(mode) in ("api", "api_first")


def needs_playwright(mode: str) -> bool:
    return normalize_mode(mode) != "api"


def describe_error(exc: BaseException, limit: int = 200) -> str:
    """Rövid, naplózható hibaüzenet (titok nélkül)."""
    text = " ".join(str(exc).split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


@dataclass
class SourceOutcome:
    """Egy adatkör eredménye egy diákra: melyik forrásból frissült."""

    dataset: str
    source: str  # "api" | "playwright"
    ok: bool = True
    reason: str = ""  # fallback vagy hiba oka

    def as_dict(self) -> dict:
        return {"source": self.source, "ok": self.ok, "reason": self.reason}


@dataclass
class SourceTracker:
    """Diákonkénti forrásnapló (a sync.log-ba és a sync_runs.sources-ba kerül)."""

    diak_nev: str
    outcomes: dict[str, SourceOutcome] = field(default_factory=dict)

    def record(self, dataset: str, source: str, ok: bool = True, reason: str = "") -> None:
        self.outcomes[dataset] = SourceOutcome(dataset, source, ok, reason)

    def get(self, dataset: str) -> SourceOutcome | None:
        return self.outcomes.get(dataset)

    def has(self, dataset: str) -> bool:
        outcome = self.outcomes.get(dataset)
        return bool(outcome and outcome.ok and outcome.source == "api")

    def api_done(self) -> set[str]:
        return {key for key, outcome in self.outcomes.items()
                if outcome.ok and outcome.source == "api"}

    def failures(self) -> dict[str, str]:
        return {key: outcome.reason for key, outcome in self.outcomes.items()
                if not outcome.ok}

    def as_dict(self) -> dict:
        order = {key: i for i, key in enumerate(DATASET_KEYS)}
        return {key: self.outcomes[key].as_dict()
                for key in sorted(self.outcomes, key=lambda k: order.get(k, 99))}

    def summary_line(self) -> str:
        """Tömör összegzés a naplóba, pl. 'API: 5, Playwright: 3'."""
        api = sum(1 for o in self.outcomes.values() if o.ok and o.source == "api")
        pw = sum(1 for o in self.outcomes.values() if o.ok and o.source == "playwright")
        failed = sum(1 for o in self.outcomes.values() if not o.ok)
        parts = [f"API: {api}", f"Playwright: {pw}"]
        if failed:
            parts.append(f"hiba: {failed}")
        return ", ".join(parts)


# Az API-szolgáltató egy diákra: lekér + ment (nincs Playwright). Lehet async.
ApiProvider = Callable[[dict], Awaitable[None] | None]


async def run_api_datasets(diak: dict, providers: dict[str, ApiProvider],
                           tracker: SourceTracker, log_fn: Callable[[str], None]) -> None:
    """Adatkörönként lefuttatja az API-szolgáltatókat, a hibákat naplózza.

    A szolgáltató csak akkor kerül meghívásra, ha regisztrálva van; a hiányzó
    adatköröket egyszerűen kihagyjuk (a Playwright út majd lefedi őket).
    """
    for key in DATASET_KEYS:
        provider = providers.get(key)
        if provider is None:
            continue
        label = LABELS.get(key, key)
        try:
            if asyncio.iscoroutinefunction(provider):
                await provider(diak)
            else:
                # A szolgáltatók szinkron HTTP-t és SQLite-ot használnak; a
                # szálba tesszük, hogy ne blokkolják a Playwright eseményhurkát.
                await asyncio.to_thread(provider, diak)
        except Exception as exc:  # noqa: BLE001 — az API bármit dobhat
            reason = describe_error(exc)
            tracker.record(key, "api", ok=False, reason=reason)
            log_fn(f"    [API HIBA] {label}: {reason}")
        else:
            tracker.record(key, "api", ok=True)
            log_fn(f"    [API OK] {label}: API-ból frissítve")


def mark_playwright(tracker: SourceTracker, key: str, reason: str = "", ok: bool = True) -> None:
    """Playwright-forrás rögzítése; a korábbi API-hiba okát megőrzi (fallback-napló)."""
    prior = tracker.get(key)
    if not reason and prior is not None and prior.reason:
        reason = prior.reason
    tracker.record(key, "playwright", ok=ok, reason=reason)


def log_playwright_plan(tracker: SourceTracker, mode: str,
                        log_fn: Callable[[str], None]) -> None:
    """Naplózza, mely adatkörök mennek Playwrighttal és miért."""
    for key in DATASET_KEYS:
        outcome = tracker.get(key)
        if outcome is not None and outcome.ok and outcome.source == "api":
            continue
        reason = (outcome.reason if outcome is not None and outcome.reason
                  else "nincs API implementáció")
        log_fn(f"    [FORRÁS] {LABELS.get(key, key)}: Playwright ({reason})")
