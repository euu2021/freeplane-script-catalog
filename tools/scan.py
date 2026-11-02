"""Collect posts from freeplane/freeplane that may share a script, for one month.

Looks at the discussions and issues updated since the window opened and keeps the posts
(opening post, comments, replies) *created* in it that carry code or a script
file. No judgement happens here: that is classify.py's job. This step only
narrows hundreds of posts down to the few worth reading.

    python tools/scan.py                     # previous calendar month
    python tools/scan.py --month 2026-10
    python tools/scan.py --since 2026-01-01 --until 2026-10-31
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta

import catalog_lib as lib

REPO = "freeplane/freeplane"

POST = "url createdAt body author { login } reactions { totalCount }"

# Threads are walked newest-updated first through the repository's own
# connections, not through the search API: with the Actions token, issue
# search outside the token's repository returns nothing, and an `updated:`
# range would also miss a thread with a post in the window and a later one.
DISCUSSIONS = f"""
query($owner: String!, $name: String!, $after: String) {{
  repository(owner: $owner, name: $name) {{
    threads: discussions(first: 20, after: $after, orderBy: {{field: UPDATED_AT, direction: DESC}}) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        number title updatedAt {POST} upvoteCount
        comments(first: 100) {{ nodes {{
          {POST} upvoteCount
          replies(first: 50) {{ nodes {{ {POST} }} }}
        }} }}
      }}
    }}
  }}
}}"""

ISSUES = f"""
query($owner: String!, $name: String!, $after: String) {{
  repository(owner: $owner, name: $name) {{
    threads: issues(first: 30, after: $after, orderBy: {{field: UPDATED_AT, direction: DESC}}) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        number title updatedAt {POST}
        comments(first: 100) {{ nodes {{ {POST} }} }}
      }}
    }}
  }}
}}"""

FENCE = re.compile(r"```([\w+-]*)[^\n]*\n(.*?)```", re.S)
GROOVY_HINTS = re.compile(
    r"\bnode\.|\bc\.(select|find|statusInfo|viewRoot)|org\.freeplane|@ExecutionModes|"
    r"\bmenuUtils\b|\bui\.|\btextUtils\b|\bmap\.(root|filter)|\.children\b|\bdef\s+\w+\s*=")
FILE_HINTS = re.compile(r"[\w%-]+\.(?:groovy|addon\.mm)\b", re.I)
CODE_LINK = re.compile(r"https://github\.com/[^\s)\]>\"']+\.(?:groovy|addon\.mm)")


def why_candidate(body: str) -> list[str]:
    """Reasons a post looks like it shares a script; empty list if it doesn't."""
    reasons = []
    for lang, code in FENCE.findall(body or ""):
        lines = [ln for ln in code.splitlines() if ln.strip()]
        if len(lines) < 4:
            continue
        if lang.lower() in ("groovy", "java", "gradle") or GROOVY_HINTS.search(code):
            reasons.append(f"code block ({len(lines)} lines{', ' + lang if lang else ''})")
            break
    files = sorted(set(m.group(0) for m in FILE_HINTS.finditer(body or "")))
    if files:
        reasons.append("script file: " + ", ".join(files[:3]))
    return reasons


def in_window(ts: str, since: date, until: date) -> bool:
    return since.isoformat() <= ts[:10] <= until.isoformat()


def threads(gql: str, since: date, token: str):
    """Threads updated on or after `since`, newest first."""
    owner, name = REPO.split("/")
    after = None
    while True:
        data = lib.graphql(gql, {"owner": owner, "name": name, "after": after}, token)["repository"]["threads"]
        for n in data["nodes"]:
            if n["updatedAt"][:10] < since.isoformat():
                return
            yield n
        if not data["pageInfo"]["hasNextPage"]:
            return
        after = data["pageInfo"]["endCursor"]


def post_record(p: dict, kind: str, thread: dict, since: date, until: date) -> dict | None:
    if not in_window(p["createdAt"], since, until):
        return None
    reasons = why_candidate(p["body"])
    if not reasons:
        return None
    return {
        "url": p["url"],
        "post_kind": kind,
        "thread_title": thread["title"],
        "thread_url": thread["url"],
        "thread_body": thread["body"] if kind not in ("discussion", "issue") else "",
        "author": (p.get("author") or {}).get("login", "ghost"),
        "created": p["createdAt"][:10],
        "reactions": p["reactions"]["totalCount"] + p.get("upvoteCount", 0),
        "reasons": reasons,
        "code_links": sorted(set(CODE_LINK.findall(p["body"]))),
        "body": p["body"],
    }


def scan(since: date, until: date, token: str) -> list[dict]:
    out = []
    for d in threads(DISCUSSIONS, since, token):
        out.append(post_record(d, "discussion", d, since, until))
        for cm in d["comments"]["nodes"]:
            out.append(post_record(cm, "discussion-comment", d, since, until))
            for r in cm["replies"]["nodes"]:
                out.append(post_record(r, "discussion-reply", d, since, until))
    for i in threads(ISSUES, since, token):
        out.append(post_record(i, "issue", i, since, until))
        for cm in i["comments"]["nodes"]:
            out.append(post_record(cm, "issue-comment", i, since, until))
    return [c for c in out if c]


def previous_month(today: date) -> tuple[date, date]:
    last = today.replace(day=1) - timedelta(days=1)
    return last.replace(day=1), last


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--month", help="YYYY-MM")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--out", help="default: work/candidates-<label>.json")
    a = ap.parse_args()
    if a.month:
        y, m = map(int, a.month.split("-"))
        since = date(y, m, 1)
        until = (date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1))
    elif a.since:
        since, until = date.fromisoformat(a.since), date.fromisoformat(a.until or date.today().isoformat())
    else:
        since, until = previous_month(date.today())
    label = a.month or (since.strftime("%Y-%m") if (since.year, since.month) == (until.year, until.month)
                        else f"{since}_{until}")
    token = lib.github_token()
    if not token:
        sys.exit("No GitHub token: set GITHUB_TOKEN or log in with `gh auth login`.")

    known = {e["url"] for e in lib.load()["entries"]}
    found = scan(since, until, token)
    fresh = [c for c in found if c["url"] not in known]
    out = lib.ROOT / (a.out or f"work/candidates-{label}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"label": label, "since": since.isoformat(), "until": until.isoformat(),
                               "candidates": fresh}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{since}..{until}: {len(found)} candidate posts, {len(fresh)} not yet in the catalog -> {out}")


if __name__ == "__main__":
    main()
