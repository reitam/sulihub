# -*- coding: utf-8 -*-
"""
Kaneo jegy felvétel a KRÉTA boardra (parancssorból, agent-barát).

Használat:
    python tools/kaneo_ticket.py --title "Rövid cím" --description "Részletek"
        [--priority low|medium|high|no-priority] [--status planned]
        [--label CodeReview] [--no-label] [--force] [--dry-run]

A belépési adatokat "kulcs: érték" sorokból olvassa (host, e-mail, jelszó):
alapból `c:\\ReiTam\\AI\\AI_users\\kaneo_ai_user.txt`, a fájl útja a
KANEO_CRED_FILE, az értékek a KANEO_URL / KANEO_EMAIL / KANEO_PASSWORD
környezeti változókkal írhatók felül. Jelszó soha nem kerül a kimenetre.

Kilépési kód: 0 = jegy létrejött (vagy már létezett, vagy dry-run),
              1 = hiba (a részletek a stderr-re mennek).
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

WORKSPACE_ID = os.environ.get("KANEO_WORKSPACE_ID", "rMI9uTd73SD6CAXuzaMfeVx935pa0FVQ")
PROJECT_ID = os.environ.get("KANEO_PROJECT_ID", "pfxgro7vduz50v5xbksb48oo")
TICKET_URL = "http://192.168.1.39:5173"  # csak a login hostja; a projekt URL élőben nem használt

PRIORITIES = ("no-priority", "low", "medium", "high")
STATUSES = ("planned", "to-do", "in-progress", "in-review", "done", "archived")
OPEN_STATUSES = ("planned", "to-do", "in-progress", "in-review")
LABEL_CACHE = Path(os.environ.get("TEMP", os.path.expanduser("~"))) / "opencode" / "kaneo_labels.json"


def out(msg):
    print(msg)


def warn(msg):
    print(msg, file=sys.stderr)


def load_credentials():
    """host / e-mail / jelszó beolvasása. Env változó mindig erősebb."""
    values = {}
    path = Path(os.environ.get("KANEO_CRED_FILE", r"c:\ReiTam\AI\AI_users\kaneo_ai_user.txt"))
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if ":" not in line or line.lstrip().startswith("#"):
                continue
            key, val = line.split(":", 1)
            values[key.strip().lower()] = val.strip()
    base = os.environ.get("KANEO_URL") or values.get("host") or values.get("url") or TICKET_URL
    if not base.startswith("http"):
        base = "http://" + base
    cred = {
        "base": base.rstrip("/"),
        "email": os.environ.get("KANEO_EMAIL") or values.get("e-mail") or values.get("email"),
        "password": os.environ.get("KANEO_PASSWORD") or values.get("jelszó") or values.get("jelszo")
        or values.get("password"),
    }
    missing = [k for k in ("email", "password") if not cred[k]]
    if missing:
        raise SystemExit(f"HIBA: hiányzó belépési adat ({', '.join(missing)}) — {path}")
    return cred


def api(cred, method, path, body=None, token=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(cred["base"] + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", "replace")
        try:
            return err.code, json.loads(raw)
        except ValueError:
            return err.code, raw[:400]
    except urllib.error.URLError as err:
        raise SystemExit(f"HIBA: a Kaneo nem érhető el ({cred['base']}): {err.reason}")


def login(cred):
    status, payload = api(cred, "POST", "/api/auth/sign-in/email",
                          {"email": cred["email"], "password": cred["password"]})
    if status != 200 or not isinstance(payload, dict) or "token" not in payload:
        raise SystemExit(f"HIBA: bejelentkezés sikertelen (HTTP {status}) — ellenőrizd a belépési adatokat")
    token = payload["token"]
    # a címke-végpontok a session aktív workspace-ét használják
    api(cred, "POST", "/api/auth/organization/set-active", {"organizationId": WORKSPACE_ID}, token)
    return token


def board_tasks(cred, token):
    """A projekt összes jegyének lapos listája (oszlopok + backlog + archívum)."""
    status, payload = api(cred, "GET", f"/api/task/tasks/{PROJECT_ID}?limit=100", token=token)
    if status != 200 or not isinstance(payload, dict):
        raise SystemExit(f"HIBA: a board nem olvasható (HTTP {status})")
    data = payload.get("data") or {}
    tasks = []
    for column in data.get("columns") or []:
        tasks += column.get("tasks") or []
    tasks += data.get("plannedTasks") or []
    tasks += data.get("archivedTasks") or []
    return tasks


def resolve_label(cred, token, tasks, name):
    """Címke ID feloldása: cache → meglévő jegyeken szereplő címke → létrehozás."""
    key = f"{WORKSPACE_ID}:{name}"
    try:
        cache = json.loads(LABEL_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if cache.get(key):
        return cache[key], False

    for task in tasks:
        for label in task.get("labels") or []:
            if label.get("name") == name and label.get("id"):
                cache[key] = label["id"]
                save_cache(cache)
                return label["id"], False

    status, payload = api(cred, "POST", "/api/label",
                          {"workspaceId": WORKSPACE_ID, "name": name, "color": "orange"}, token)
    if status != 200 or not isinstance(payload, dict) or not payload.get("id"):
        warn(f"FIGYELEM: a(z) „{name}” címke nem hozható létre (HTTP {status}) — jegy címke nélkül")
        return None, False
    cache[key] = payload["id"]
    save_cache(cache)
    return payload["id"], True


def save_cache(cache):
    try:
        LABEL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        LABEL_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # a cache csak kényelmi gyorsítás, hiba nem kritikus


def resolve_parent(tasks, parent):
    """Szülőjegy id-je szám (pl. 40) vagy id alapján; üres, ha nincs szülő."""
    if not parent:
        return ""
    p = str(parent).strip().lstrip("#")
    if p.isdigit():
        for task in tasks:
            if str(task.get("number")) == p:
                return task.get("id", "")
        raise SystemExit(f"HIBA: nincs #{p} számú jegy a boardon (a --parent csak meglévő jegyre mutathat)")
    return p


def find_duplicate(tasks, title):
    norm = " ".join(title.split()).lower()
    for task in tasks:
        if task.get("status") in OPEN_STATUSES:
            if " ".join(str(task.get("title", "")).split()).lower() == norm:
                return task
    return None


def main():
    parser = argparse.ArgumentParser(description="Jegy felvétele a Kaneo boardra.")
    parser.add_argument("--title", required=True, help="A jegy címe (egy sor).")
    parser.add_argument("--description", default="", help="Leírás (markdown; a literális \\n sortörés lesz).")
    parser.add_argument("--priority", default="medium", help=" | ".join(PRIORITIES) + " (alap: medium)")
    parser.add_argument("--status", default="planned", help=" | ".join(STATUSES) + " (alap: planned = backlog)")
    parser.add_argument("--label", default="CodeReview", help="Címke neve (alap: CodeReview).")
    parser.add_argument("--no-label", action="store_true", help="Címke nélkül hozza létre.")
    parser.add_argument("--parent", default="", help="Szülőjegy száma (pl. 40) vagy id-je — a jegy subtask lesz.")
    parser.add_argument("--force", action="store_true", help="Azonos című nyitott jegy ellenére is létrehozza.")
    parser.add_argument("--dry-run", action="store_true", help="Csak kiírja, mit küldene el (nem hoz létre jegyet).")
    args = parser.parse_args()

    title = " ".join(args.title.split())
    if not title:
        raise SystemExit("HIBA: üres cím")
    if args.priority not in PRIORITIES:
        raise SystemExit(f"HIBA: ismeretlen prioritás: {args.priority} ({', '.join(PRIORITIES)})")
    if args.status not in STATUSES:
        raise SystemExit(f"HIBA: ismeretlen státusz: {args.status} ({', '.join(STATUSES)})")
    description = args.description.replace("\\n", "\n").strip() or title

    cred = load_credentials()
    token = login(cred)
    tasks = board_tasks(cred, token)

    duplicate = None if args.force else find_duplicate(tasks, title)
    if duplicate:
        out(f"MAR LETEZIK #{duplicate.get('number')} | id={duplicate.get('id')} | "
            f"status={duplicate.get('status')} | {duplicate.get('title')}")
        return 0

    parent_id = resolve_parent(tasks, args.parent)

    if args.dry_run:
        out(json.dumps({"projectId": PROJECT_ID, "title": title, "description": description,
                        "priority": args.priority, "status": args.status,
                        "parent": parent_id or None,
                        "label": None if args.no_label else args.label}, ensure_ascii=False))
        return 0

    status, task = api(cred, "POST", f"/api/task/{PROJECT_ID}",
                       {"title": title, "description": description,
                        "priority": args.priority, "status": args.status}, token)
    if status != 200 or not isinstance(task, dict) or not task.get("id"):
        raise SystemExit(f"HIBA: a jegy nem jött létre (HTTP {status}): {task}")

    # Subtask: a Kaneo külön kapcsolat-táblában tárolja (POST /api/task-relation),
    # a task body parentId mezőjét figyelmen kívül hagyja.
    parent_note = "-"
    if parent_id:
        rel_status, rel = api(cred, "POST", "/api/task-relation",
                              {"sourceTaskId": parent_id, "targetTaskId": task["id"],
                               "relationType": "subtask"}, token)
        parent_note = "OK" if rel_status == 200 else f"HIBA (HTTP {rel_status})"

    label_note = "-"
    if not args.no_label:
        label_id, created = resolve_label(cred, token, tasks, args.label)
        if label_id:
            lstatus, _ = api(cred, "PUT", f"/api/label/{label_id}/task", {"taskId": task["id"]}, token)
            label_note = args.label if lstatus == 200 else f"{args.label} (osztás sikertelen: HTTP {lstatus})"
            if created:
                label_note += " (új címke)"
        else:
            label_note = "-"

    out(f"OK #{task.get('number')} | id={task.get('id')} | status={task.get('status')} | "
        f"priority={task.get('priority')} | label={label_note} | subtask={parent_note} | {title}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
