#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GitHub Release létrehozása/frissítése a docs/releasenotes/<tag>.md alapján.

Használat:
    python tools/github_release.py --tag v2.7.6 --latest
    python tools/github_release.py --tag v2.7.5
    GITHUB_TOKEN=... python tools/github_release.py --tag v2.7.4

A tokent a GITHUB_TOKEN / GH_TOKEN környezeti változóból, vagy a git
credential managerből olvassa (github.com). A repót az origin remote-ból
ismeri fel, vagy a --repo paraméterből.

Csak a Python szabványos könyvtárát használja.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "reitam/sulihub"


def git_repo() -> str | None:
    """Az origin remote-ból owner/repo (GitHub)."""
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=ROOT,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return None
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def get_token() -> str | None:
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key)
        if value:
            return value.strip()
    try:
        out = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            cwd=ROOT, capture_output=True, text=True, timeout=20,
        ).stdout
    except subprocess.TimeoutExpired:
        return None
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return None


def api(repo: str, token: str, method: str, path: str, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{path}", data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "sulihub-release")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:800]


def main() -> int:
    parser = argparse.ArgumentParser(description="GitHub Release a release note Markdownból")
    parser.add_argument("--tag", required=True, help="git tag, pl. v2.7.6")
    parser.add_argument("--repo", default=None, help="owner/repo (alap: origin remote)")
    parser.add_argument("--notes-file", default=None, help="alap: docs/releasenotes/<tag>.md")
    parser.add_argument("--title", default=None, help="alap: SuliHub <tag>")
    parser.add_argument("--draft", action="store_true", help="draft release")
    parser.add_argument("--prerelease", action="store_true", help="prerelease")
    parser.add_argument("--latest", action="store_true", help="ez legyen a legutóbbi release")
    args = parser.parse_args()

    tag = args.tag.strip()
    if not tag.startswith("v"):
        tag = "v" + tag
    repo = args.repo or git_repo() or DEFAULT_REPO
    notes = Path(args.notes_file) if args.notes_file else (
        ROOT / "docs" / "releasenotes" / f"{tag}.md")
    if not notes.exists():
        print(f"HIBA: nincs release note: {notes}", file=sys.stderr)
        return 1
    body = notes.read_text(encoding="utf-8-sig")
    title = args.title or f"SuliHub {tag}"

    token = get_token()
    if not token:
        print("HIBA: nincs GitHub token (GITHUB_TOKEN/GH_TOKEN vagy git credential).",
              file=sys.stderr)
        return 1

    payload = {
        "tag_name": tag,
        "name": title,
        "body": body,
        "draft": bool(args.draft),
        "prerelease": bool(args.prerelease),
        "make_latest": "true" if args.latest else "false",
    }

    status, existing = api(repo, token, "GET", f"/releases/tags/{tag}")
    if status == 200 and isinstance(existing, dict):
        status, result = api(repo, token, "PATCH",
                             f"/releases/{existing['id']}", {
                                 "name": title,
                                 "body": body,
                                 "draft": bool(args.draft),
                                 "prerelease": bool(args.prerelease),
                                 "make_latest": "true" if args.latest else "false",
                             })
        action = "frissítve"
    elif status == 404:
        status, result = api(repo, token, "POST", "/releases", payload)
        action = "létrehozva"
    else:
        print(f"HIBA: release lekérdezés {status}: {existing}", file=sys.stderr)
        return 1

    if status not in (200, 201) or not isinstance(result, dict):
        print(f"HIBA: release {action} {status}: {result}", file=sys.stderr)
        return 1
    print(f"GitHub Release {action}: {result.get('html_url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
