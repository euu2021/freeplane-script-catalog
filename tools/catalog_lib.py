"""Shared helpers for the catalog tools: load/save, merge, tags, GitHub access."""
from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "catalog.json"

# Controlled vocabulary. The page builds its tag filter from this list, and the
# AI step is constrained to it, so tags stay comparable across months.
TAGS = {
    "navigation": "Move the selection, jump around the map",
    "selection": "Select nodes",
    "editing": "Create, move, split, join or modify nodes",
    "text": "Work on the text of nodes: case, words, cleanup",
    "styles": "Styles, colors, edges, themes, formatting",
    "tags": "Node tags and tag categories",
    "attributes": "Node attributes",
    "notes-details": "Notes and details",
    "filter-search": "Filtering and searching",
    "fold-minimize": "Folding and minimizing nodes",
    "view": "Zoom, layout, scrolling, what the map view shows",
    "clipboard": "Clipboard operations",
    "links-connectors": "Hyperlinks, connectors, links between nodes",
    "maps": "Several maps, map files, views",
    "import-export": "Import from or export to other formats",
    "images-icons": "Images and icons",
    "panel-gui": "Panels, dialogs, custom windows",
    "automation": "Listeners, init scripts, scheduled or automatic runs",
    "dates-time": "Dates, timers, reminders, time tracking",
    "tasks-gtd": "Task management, GTD, planning",
    "ai": "Uses an AI / LLM service",
    "dev-tools": "For script and add-on developers",
    "library": "Code meant to be used by other scripts",
}

KINDS = ("script", "add-on", "library", "collection")

# Keyword rules used only to pre-tag seeded entries, which have no AI pass yet.
# Rules in _NAME_ONLY are too ambiguous for prose ("the selected node", "the map")
# and only look at the entry's name.
_NAME_ONLY = {"selection", "maps", "text", "notes-details", "styles", "editing"}
_TAG_RULES = [
    ("navigation", r"navigat|jump|go ?to|bookmark|traversal"),
    ("selection", r"\bselect"),
    ("editing", r"duplicat|split|join|\bmove|insert|create (a )?node|sort child|delete|kill empty|swap|hierarch|branch"),
    ("text", r"\btext\b|case|word|character|line break|transpose|lorem|markdown|latex"),
    ("styles", r"style|colou?r|edge|theme|format"),
    ("tags", r"\btags?\b"),
    ("attributes", r"attribute"),
    ("notes-details", r"\bnotes?\b|details"),
    ("filter-search", r"filter|search|find"),
    ("fold-minimize", r"\bfold|minimi|shorten|collapse"),
    ("view", r"zoom|layout|viewport|scroll|\bcent(er|re)\b|block view|spacing"),
    ("clipboard", r"clipboard|\bcopy|paste"),
    ("links-connectors", r"\blinks?\b|connector|hyperlink"),
    ("maps", r"\bmaps\b|mindmap|map view|sheet|cross-map|other map|new map"),
    ("import-export", r"import|export|csv|opml|bibtex|pptx|\.md\b|to file|pack"),
    ("images-icons", r"image|icon|picture|mermaid|puml|png"),
    ("panel-gui", r"panel|dialog|window|popup|\bgui\b|console|tooltip"),
    ("automation", r"listener|\binit\b|startup|on (map )?open|automatic|monitor"),
    ("dates-time", r"date|time|timer|pomodoro|reminder|clock|timeline"),
    ("tasks-gtd", r"\bgtd\b|task|todo|next action|waiting for|wbs|planner|project"),
    ("ai", r"\bai\b|openai|\bllm\b|chatgpt|gpt"),
    ("dev-tools", r"developer|devtools|debug|logger|api generator|groovy console|shell|translation"),
    ("library", r"\blibrary\b|helper methods|global variables|groovynode"),
]


def guess_tags(name: str, description: str = "", limit: int = 4) -> list[str]:
    name = (name or "").lower()
    prose = name + " " + (description or "").lower()
    return [tag for tag, rx in _TAG_RULES
            if re.search(rx, name if tag in _NAME_ONLY else prose)][:limit]


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def mdbook_anchor(heading: str) -> str:
    """Same id mdbook gives a heading: images dropped, then normalize_id()."""
    heading = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", heading)
    heading = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading).strip()
    out = []
    for ch in heading:
        if ch.isalnum() or ch in "_-":
            out.append(ch.lower())
        elif ch.isspace():
            out.append("-")
    return "".join(out)


def humanize(identifier: str) -> str:
    """camelCase_or_snake file name -> 'Camel case or snake'."""
    s = re.sub(r"\.(groovy|addon\.mm|mm)$", "", identifier)
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s).replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:1].upper() + s[1:].lower() if s else identifier


def load() -> dict:
    if CATALOG.exists():
        return json.loads(CATALOG.read_text(encoding="utf-8"))
    return {"updated": None, "tags": TAGS, "entries": []}


def save(catalog: dict) -> None:
    catalog["updated"] = date.today().isoformat()
    catalog["tags"] = TAGS
    catalog["entries"].sort(key=lambda e: (e["name"].lower(), e["id"]))
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def merge(catalog: dict, new_entries: list[dict], replace_added_by: str | None = None) -> tuple[int, int]:
    """Upsert by id, deduplicating by url. With replace_added_by, entries of that
    origin that are no longer produced are dropped (lets a seed be re-run)."""
    entries = catalog["entries"]
    if replace_added_by:
        keep_ids = {e["id"] for e in new_entries}
        entries[:] = [e for e in entries if e.get("added_by") != replace_added_by or e["id"] in keep_ids]
    by_id = {e["id"]: e for e in entries}
    key = lambda e: e.get("code") or e["url"]  # several scripts may share one thread
    by_url = {key(e): e for e in entries}
    added = updated = 0
    for e in new_entries:
        old = by_id.get(e["id"]) or by_url.get(key(e))
        if old is None:
            e.setdefault("added", date.today().isoformat())
            entries.append(e)
            by_id[e["id"]] = by_url[key(e)] = e
            added += 1
        else:
            e["added"] = old.get("added", date.today().isoformat())
            old.clear()
            old.update(e)
            updated += 1
    return added, updated


def github_token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    for gh in ("gh", r"C:\Program Files\GitHub CLI\gh.exe"):
        try:
            return subprocess.run([gh, "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            continue
    return None


def http_get(url: str, token: str | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "freeplane-script-catalog"})
    if token and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:  # some old docs pages are cp1252
        return raw.decode("cp1252", "replace")


def graphql(query: str, variables: dict, token: str) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "freeplane-script-catalog"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]
