"""Seed the catalog from the sources listed in the Freeplane docs page
"Finding useful scripts" (https://docs.freeplane.org/scripting/Finding_useful_scripts.html).

Re-runnable: each source replaces only the entries it produced before.

    python tools/seed.py            # all sources
    python tools/seed.py docs       # just one
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import catalog_lib as lib

DOCS_RAW = "https://raw.githubusercontent.com/freeplane/docs/main/src/docs/"
DOCS_HTML = "https://docs.freeplane.org/"

# page, heading level that delimits one entry, kind, headings that are not entries
DOCS_PAGES = [
    ("scripting/Scripts_collection", "##", "script", set()),
    ("scripting/Scripting_text_editing", "##", "script", set()),
    ("scripting/Script_incubator", "##", "script", set()),
    ("scripting/Example_scripts_using_external_libraries", "#", "script",
     {"General installation instructions for external Java libraries"}),
    ("getting-started/Add-ons_(install)", "##", "add-on", set()),
]

# Add-on page groups add-ons under "# <category>"; map those to tags.
ADDON_CATEGORY_TAGS = {
    "Edit": ["editing"], "Navigate": ["navigation"], "Problem solving": [],
    "Plan and organize": ["tasks-gtd"], "Images and icons": ["images-icons"],
    "Collaborate": [], "Import and export": ["import-export"], "Others": [],
    "For developers": ["dev-tools"],
}

EUU_TAGS = {
    "navigation": "navigation", "selection": "selection", "tags": "tags", "styles": "styles",
    "filter/search": "filter-search", "panel/GUI": "panel-gui", "maps": "maps",
    "editing": "editing", "fold/minimize": "fold-minimize", "clipboard": "clipboard",
    "listener": "automation", "init": "automation", "connectors": "links-connectors",
}


def clean_md(text: str) -> str:
    link_target = r"\((?:[^()]|\([^)]*\))*\)"  # tolerates one level of (parens) in the URL
    text = re.sub(r"!\[[^\]]*\]" + link_target, "", text)
    text = re.sub(r"\[([^\]]*)\]" + link_target, r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def first_paragraph(lines: list[str]) -> str:
    para, in_code = [], False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if para and para[-1].endswith(":") and not s:
            items = []
            for nxt in lines[i + 1:]:
                m = re.match(r"^\s*[*-]\s+(.*)", nxt)
                if m:
                    items.append(clean_md(m.group(1)).rstrip(".;"))
                elif nxt.strip() or items:
                    break
            if items:
                para.append("; ".join(items) + ".")
            break
        if s.startswith("```"):
            in_code = not in_code
            if para:
                break
            continue
        if in_code or s.startswith("<!--") or s.startswith("#"):
            if para:
                break
            continue
        if not s:
            if para:
                break
            continue
        if re.match(r"^\*\*by |^Author:|^Original author:|^!\[", s):
            continue
        para.append(s)
    desc = clean_md(" ".join(para))
    return desc if len(desc) <= 400 else desc[:397].rsplit(" ", 1)[0] + "..."


def author_of(lines: list[str]) -> str:
    for ln in lines:
        m = re.match(r"^\s*(?:Original author|Author):\s*(.+)$", ln)
        if m:
            return clean_md(m.group(1))
        m = re.match(r"^\s*\*\*by (.+?)\*\*", ln)
        if m:
            return clean_md(m.group(1))
    return ""


def live_ids(page: str) -> set[str]:
    html = lib.http_get(DOCS_HTML + page + ".html")
    return set(re.findall(r'<h[1-6] id="([^"]+)"', html))


def seed_docs() -> list[dict]:
    out = []
    for page, level, kind, skip in DOCS_PAGES:
        md = lib.http_get(DOCS_RAW + page + ".md")
        ids = live_ids(page)
        page_title = page.split("/")[-1].replace("_", " ")
        sections, cur, category = [], None, ""
        in_code = False
        for ln in md.splitlines():
            if ln.strip().startswith("```"):
                in_code = not in_code
            m = None if in_code else re.match(r"^(#{1,6})\s+(.*)$", ln)
            if m and m.group(1) == "#" and level == "##":
                category = clean_md(m.group(2))
            if m and m.group(1) == level:
                cur = {"heading": m.group(2).strip(), "lines": [], "category": category}
                sections.append(cur)
            elif m and len(m.group(1)) < len(level):
                cur = None
            elif cur is not None:
                cur["lines"].append(ln)
        seen = {}
        for s in sections:
            name = clean_md(s["heading"]).rstrip(".")
            if not name or name in skip:
                continue
            if kind == "add-on" and s["category"] not in ADDON_CATEGORY_TAGS:
                continue
            anchor = lib.mdbook_anchor(s["heading"])
            n = seen.get(anchor, 0)
            seen[anchor] = n + 1
            if n:
                anchor = f"{anchor}-{n}"
            if anchor not in ids:
                print(f"  warn: anchor #{anchor} not on live page {page}", file=sys.stderr)
            desc = first_paragraph(s["lines"])
            tags = ADDON_CATEGORY_TAGS.get(s["category"], []) + lib.guess_tags(name, desc)
            out.append({
                "id": "docs-" + lib.slugify(page_title) + "-" + anchor,
                "name": name,
                "description": desc,
                "kind": kind,
                "author": author_of(s["lines"]),
                "url": f"{DOCS_HTML}{page}.html#{anchor}",
                "source": "docs",
                "where": page_title,
                "tags": list(dict.fromkeys(tags))[:4],
                "added_by": "seed:docs",
            })
    return out


def script_header(raw_url: str) -> str:
    try:
        return "\n".join(lib.http_get(raw_url).splitlines()[:40])
    except Exception:
        return ""


def seed_euu2021() -> list[dict]:
    base = "https://github.com/euu2021/freeplane_scripts/blob/main/"
    raw = "https://raw.githubusercontent.com/euu2021/freeplane_scripts/main/"
    readme = lib.http_get(raw + "README.md")
    rows = []
    for ln in readme.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) != 4 or not re.search(r"\(scripts/[^)]+\.groovy\)", cells[1]):
            continue
        star, script_cell, desc, tags_cell = cells
        files = re.findall(r"\(scripts/([^)]+\.groovy)\)", script_cell)
        # Sibling scripts share a row: "name [part](..) · [part](..)" or "[A](..) · [B](..)".
        outside = clean_md(re.sub(r"\[[^\]]*\]\([^)]*\)|·", "", script_cell))
        parts = [t for t in re.findall(r"\[([^\]]+)\]\(", script_cell)
                 if t not in ("Down", "UP", "Up", "Left", "Right", "Bridge")]
        name = outside or " + ".join(parts) or files[0]
        tags = [EUU_TAGS[t] for t in re.findall(r"`([^`]+)`", tags_cell) if t in EUU_TAGS]
        rows.append((name, files, clean_md(desc), list(dict.fromkeys(tags)), "⭐" in star))
    with ThreadPoolExecutor(8) as pool:
        headers = list(pool.map(lambda r: script_header(raw + "scripts/" + r[1][0]), rows))
    out = []
    for (name, files, desc, tags, star), head in zip(rows, headers):
        code = base + "scripts/" + files[0]
        m = re.search(r"Discussion thread:\s*(https?://\S+)", head)
        v = re.search(r"Version:\s*([\d.]+)", head)
        e = {
            "id": "gh-euu2021-" + lib.slugify(files[0]),
            "name": name,
            "description": desc,
            "kind": "script",
            "author": "euu2021",
            "url": m.group(1) if m else code,
            "code": code,
            "source": "github-repo",
            "where": "euu2021/freeplane_scripts",
            "tags": tags or lib.guess_tags(name, desc),
            "added_by": "seed:euu2021",
        }
        if v:
            e["version"] = v.group(1)
        if star:
            e["featured"] = True
        out.append(e)
    return out


def leading_comment(src: str) -> str:
    """First comment lines that say what the script does (skips license and annotations)."""
    src = re.sub(r"/\*.*?\*/", lambda m: "" if re.search(r"copyright|license", m.group(0), re.I) else m.group(0),
                 src, flags=re.S)
    text = []
    for ln in src.splitlines()[:60]:
        s = ln.strip()
        if not s:
            if text:
                break
            continue
        if s.startswith("import ") or s.startswith("package "):
            break
        if not (s.startswith("//") or s.startswith("/*") or s.startswith("*")):
            break
        s = re.sub(r"^(/\*+|\*+/?|//+)\s?", "", s).strip()
        if re.search(r"copyright|license|spdx|warranty|gnu\.org|free software|@ExecutionModes|@CacheScriptContent|^\*?/$",
                     s, re.I):
            continue
        if s:
            text.append(s)
    return clean_md(" ".join(text))[:300]


def seed_macmarrum(token: str | None) -> list[dict]:
    listing = json.loads(lib.http_get(
        "https://api.github.com/repos/macmarrum/freeplane-scripting/contents/src/scripts", token))
    files = [f for f in listing if f["type"] == "file" and f["name"].endswith(".groovy")]
    with ThreadPoolExecutor(12) as pool:
        sources = list(pool.map(lambda f: script_header(f["download_url"]), files))
    out = []
    for f, src in zip(files, sources):
        name = lib.humanize(f["name"])
        desc = leading_comment(src)
        # Many headers open with the forum thread the script answers: that is
        # the page to link to, the code stays one click away.
        thread = re.match(r"(https://github\.com/freeplane/freeplane/(?:discussions|issues)/\S+)\s*", desc)
        if thread:
            desc = desc[thread.end():]
        out.append({
            "id": "gh-macmarrum-" + lib.slugify(f["name"]),
            "name": name,
            "description": desc,
            "kind": "script",
            "author": "macmarrum",
            "url": thread.group(1) if thread else f["html_url"],
            "code": f["html_url"],
            "source": "github-repo",
            "where": "macmarrum/freeplane-scripting",
            "tags": lib.guess_tags(name, desc),
            "added_by": "seed:macmarrum",
        })
    return out


def seed_edofro(token: str | None) -> list[dict]:
    repos = json.loads(lib.http_get("https://api.github.com/users/EdoFro/repos?per_page=100", token))
    out = []
    for r in repos:
        desc = r.get("description") or ""
        if r["fork"] or not re.search(r"freep|wikdshell", r["name"] + " " + desc, re.I):
            continue
        blob = (r["name"] + " " + desc).lower()
        kind = "library" if "library" in blob else "add-on" if re.search(r"add-?on", blob) else "script"
        name = re.sub(r"^Freep?lane[_-]", "", r["name"]).replace("_", " ").replace("-", " ").strip()
        out.append({
            "id": "gh-edofro-" + lib.slugify(r["name"]),
            "name": name,
            "description": desc,
            "kind": kind,
            "author": "EdoFro",
            "url": r["html_url"],
            "code": r["html_url"],
            "source": "github-repo",
            "where": "EdoFro (GitHub)",
            "tags": lib.guess_tags(name, desc),
            "date": r["pushed_at"][:10],
            "stars": r["stargazers_count"],
            "added_by": "seed:edofro",
        })
    return out


def seed_collections() -> list[dict]:
    base = {"kind": "collection", "source": "github-repo", "tags": [], "added_by": "seed:collections"}
    return [dict(base, **e) for e in [
        {"id": "col-macmarrum", "name": "macmarrum's script repository", "author": "macmarrum",
         "description": "Around 200 Groovy scripts for Freeplane, plus libraries and add-ons in other repositories.",
         "url": "https://github.com/macmarrum/freeplane-scripting/tree/main/src/scripts",
         "where": "macmarrum/freeplane-scripting"},
        {"id": "col-edofro", "name": "EdoFro's repositories", "author": "EdoFro",
         "description": "Add-ons and libraries: Markdown Helper, Menu-o-Matic, Map-Drive-Inator, groovyConsole and more.",
         "url": "https://github.com/EdoFro?tab=repositories", "where": "EdoFro (GitHub)"},
        {"id": "col-euu2021", "name": "euu2021's freeplane_scripts", "author": "euu2021",
         "description": "Tagged collection of Groovy scripts: navigation, panels, tags, listeners, view tweaks.",
         "url": "https://github.com/euu2021/freeplane_scripts", "where": "euu2021/freeplane_scripts"},
        {"id": "col-freeplane-addons", "name": "freeplane/addons repository", "author": "Freeplane project",
         "description": "The project's repository for larger scripts and add-ons.",
         "url": "https://github.com/freeplane/addons", "where": "freeplane/addons"},
    ]]


SOURCES = {
    "docs": ("seed:docs", lambda tok: seed_docs()),
    "euu2021": ("seed:euu2021", lambda tok: seed_euu2021()),
    "macmarrum": ("seed:macmarrum", seed_macmarrum),
    "edofro": ("seed:edofro", seed_edofro),
    "collections": ("seed:collections", lambda tok: seed_collections()),
}


def main(argv: list[str]) -> None:
    wanted = argv or list(SOURCES)
    token = lib.github_token()
    catalog = lib.load()
    for name in wanted:
        origin, fn = SOURCES[name]
        entries = fn(token)
        added, updated = lib.merge(catalog, entries, replace_added_by=origin)
        print(f"{name}: {len(entries)} entries ({added} new, {updated} updated)")
    lib.save(catalog)
    print(f"catalog: {len(catalog['entries'])} entries -> {lib.CATALOG}")


if __name__ == "__main__":
    main(sys.argv[1:])
