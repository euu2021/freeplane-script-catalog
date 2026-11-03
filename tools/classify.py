# Copyright (C) 2026  euu2021 (Github)
# SPDX-License-Identifier: GPL-2.0-or-later
"""AI step: read the candidates found by scan.py, decide which posts really
share a script, describe and tag those, and merge them into the catalog.

    python tools/classify.py work/candidates-2026-10.json
        Asks Claude through the Anthropic API (needs ANTHROPIC_API_KEY).

    python tools/classify.py work/candidates-2026-10.json --decisions work/decisions-2026-10.json
        Uses decisions made elsewhere (e.g. by Claude Code following tools/prompt.md),
        in the same JSON shape the API returns, keyed by post URL.

Both write data/scans/<label>.md (kept in git as the record of what the AI
decided), which the monthly workflow uses as the
pull request description, so a human reviews every addition before it ships.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import catalog_lib as lib

MODEL = "claude-opus-5-5"

SCHEMA = {
    "type": "object",
    "properties": {
        "shares_script": {"type": "boolean"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "kind": {"type": "string", "enum": ["script", "add-on", "library", "none"]},
        "tags": {"type": "array", "items": {"type": "string", "enum": list(lib.TAGS)}},
        "reason": {"type": "string"},
    },
    "required": ["shares_script", "name", "description", "kind", "tags", "reason"],
    "additionalProperties": False,
}


def system_prompt() -> str:
    template = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
    tags = "\n".join(f"- `{k}`: {v}" for k, v in lib.TAGS.items())
    return template.replace("{tags}", tags)


def user_message(c: dict) -> str:
    opening = ""
    if c["thread_body"]:
        opening = f"<opening_post>\n{c['thread_body']}\n</opening_post>\n"
    return (
        f'<thread title="{c["thread_title"]}" url="{c["thread_url"]}">\n{opening}</thread>\n\n'
        f'<post url="{c["url"]}" kind="{c["post_kind"]}" author="{c["author"]}" created="{c["created"]}">\n'
        f'{c["body"]}\n</post>'
    )


def ask_claude(candidates: list[dict]) -> dict[str, dict]:
    import anthropic

    client = anthropic.Anthropic(max_retries=5)
    system = system_prompt()
    decisions = {}
    for i, c in enumerate(candidates, 1):
        print(f"[{i}/{len(candidates)}] {c['url']}", file=sys.stderr)
        try:
            resp = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                thinking={"type": "adaptive"},
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                system=system,
                messages=[{"role": "user", "content": user_message(c)}],
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            sys.exit(f"Anthropic API rejected the credentials: {e.message}")
        except anthropic.RateLimitError as e:
            sys.exit(f"Rate limited even after retries: {e.message}")
        except anthropic.APIStatusError as e:
            print(f"  skipped: API error {e.status_code}: {e.message}", file=sys.stderr)
            continue
        except anthropic.APIConnectionError as e:
            print(f"  skipped: connection error: {e}", file=sys.stderr)
            continue
        if resp.stop_reason == "refusal":
            print("  skipped: the model declined this post", file=sys.stderr)
            continue
        if resp.stop_reason == "max_tokens":
            print("  skipped: answer was cut off at max_tokens", file=sys.stderr)
            continue
        text = next(b.text for b in resp.content if b.type == "text")
        decisions[c["url"]] = json.loads(text)
    return decisions


def entry_for(c: dict, d: dict, label: str) -> dict:
    m = re.search(r"/(discussions|issues)/(\d+)", c["url"])
    source = "github-discussion" if m and m.group(1) == "discussions" else "github-issue"
    path = re.sub(r"^https://github\.com/freeplane/freeplane/", "", c["url"])
    return {
        "id": "post-" + lib.slugify(path),
        "name": d["name"].strip(),
        "description": d["description"].strip(),
        "kind": d["kind"] if d["kind"] in lib.KINDS else "script",
        "author": c["author"],
        "url": c["url"],
        "source": source,
        "where": f"#{m.group(2)} {c['thread_title']}" if m else c["thread_title"],
        "tags": [t for t in d["tags"] if t in lib.TAGS][:4],
        "date": c["created"],
        "reactions": c["reactions"],
        "added_by": f"ai-scan:{label}",
    }


def report(label: str, candidates: list[dict], decisions: dict, accepted: list[dict],
           known: dict[str, dict], decided_by: str) -> str:
    lines = [f"## Monthly script scan: {label}", "",
             f"Decided by: {decided_by}.", "",
             f"{len(candidates) + len(known)} posts carried code or a script file; "
             f"{len(known)} pointed to scripts already in the catalog; "
             f"{len(accepted)} were judged to share a script and are added below. "
             "Please check names, descriptions and tags before merging.", ""]
    if accepted:
        lines += ["### Added", ""]
        for e in accepted:
            # Plain author names: an @mention in the PR body would ping them every month.
            lines.append(f"- **[{e['name']}]({e['url']})** by {e['author']} ({e['kind']}; "
                         f"{', '.join(e['tags']) or 'no tags'}): {e['description']}")
            lines.append(f"  - why: {decisions[e['url']]['reason']}")
        lines.append("")
    rejected = [c for c in candidates if c["url"] in decisions and not decisions[c["url"]]["shares_script"]]
    if rejected:
        lines += ["### Not added", ""]
        for c in rejected:
            lines.append(f"- [{c['thread_title']}]({c['url']}) by {c['author']}: {decisions[c['url']]['reason']}")
        lines.append("")
    if known:
        lines += ["### Already in the catalog", ""]
        lines += [f"- {url} links to [{e['name']}]({e['url']})" for url, e in known.items()] + [""]
    undecided = [c for c in candidates if c["url"] not in decisions]
    if undecided:
        lines += ["### Not classified (API error, refusal or no decision)", ""]
        lines += [f"- {c['url']}" for c in undecided] + [""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidates")
    ap.add_argument("--decisions", help="JSON file of decisions keyed by post URL, instead of the API")
    ap.add_argument("--decided-by", help="who made the --decisions, for the report")
    ap.add_argument("--report", help="default: data/scans/<label>.md")
    a = ap.parse_args()

    data = json.loads(Path(a.candidates).read_text(encoding="utf-8"))
    label, candidates = data["label"], data["candidates"]
    catalog = lib.load()

    # A post that links to a script file the catalog already has is a pointer,
    # not a new script: report it, don't pay for a classification.
    by_code = {e["code"]: e for e in catalog["entries"] if e.get("code")}
    known = {c["url"]: by_code[link] for c in candidates for link in c.get("code_links", []) if link in by_code}
    candidates = [c for c in candidates if c["url"] not in known]

    if a.decisions:
        decisions = json.loads(Path(a.decisions).read_text(encoding="utf-8"))
        for url, d in decisions.items():
            missing = [k for k in SCHEMA["required"] if k not in d]
            if missing:
                sys.exit(f"decision for {url} lacks {missing}")
        decided_by = a.decided_by or f"decisions file {Path(a.decisions).name}"
    else:
        decisions = ask_claude(candidates)
        decided_by = f"{MODEL} through the Anthropic API, following tools/prompt.md"

    accepted = [entry_for(c, decisions[c["url"]], label)
                for c in candidates if decisions.get(c["url"], {}).get("shares_script")]
    added, updated = lib.merge(catalog, accepted)
    lib.save(catalog)

    out = Path(a.report or lib.ROOT / f"data/scans/{label}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report(label, candidates, decisions, accepted, known, decided_by), encoding="utf-8")
    print(f"{len(accepted)} of {len(candidates)} accepted ({added} new, {updated} updated); report -> {out}")


if __name__ == "__main__":
    main()
