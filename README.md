# Freeplane community scripts — catalog (proof of concept)

A single, searchable page listing the Groovy scripts and add-ons that the Freeplane community has shared, each one linking back to where it was published: a forum post, a documentation page or a repository.

It is a proof of concept for the idea in [freeplane discussion #3018](https://github.com/freeplane/freeplane/discussions/3018#discussioncomment-19359968): a simple page on GitHub Pages, with metadata so the list can be filtered and searched, and an AI that scans the new posts every month and feeds the database.

## What is in it

| Part | File | What it does |
|---|---|---|
| The page | `index.html`, `assets/` | Static page, no build step. Search, filters by kind, source and tag, sorting, shareable URLs (the filters live in the `#hash`). |
| The database | `data/catalog.json` | One JSON file, one entry per script. |
| The seed | `tools/seed.py` | Fills the database from the sources listed in the docs page [Finding useful scripts](https://docs.freeplane.org/scripting/Finding_useful_scripts.html). |
| The monthly scan | `tools/scan.py` | Finds the posts of a month, in discussions and issues, that carry code or a script file. |
| The AI step | `tools/classify.py`, `tools/prompt.md` | Asks Claude whether each post really shares a script, and if so for a name, a description and tags. Writes the result to the database and a report to `data/scans/`. |
| The schedule | `.github/workflows/monthly-scan.yml` | Runs scan + classify on the 2nd of each month and opens a pull request. Nothing goes live until someone merges it. |

Current content: 362 entries.

- 87 from the documentation: the scripts collection, text editing, incubator, external libraries and add-on pages, each linked to its own heading.
- 50 from euu2021/freeplane_scripts, linked to the forum thread when the script's header names one.
- 198 from macmarrum/freeplane-scripting.
- 19 from EdoFro's repositories.
- 4 entries for the collections themselves.
- 4 added by the October 2026 scan.

## An entry

```json
{
  "id": "post-discussions-2995",
  "name": "Floating zoom window",
  "description": "A small floating window with two buttons: one cycles the map zoom from 2x to 8x, the other restores the original zoom. ...",
  "kind": "script",
  "author": "Illegit",
  "url": "https://github.com/freeplane/freeplane/discussions/2995",
  "source": "github-discussion",
  "where": "#2995 floating window script for zooming",
  "tags": ["view", "panel-gui"],
  "date": "2026-10-10",
  "reactions": 1,
  "added": "2026-11-02",
  "added_by": "ai-scan:2026-10"
}
```

- `kind`: `script`, `add-on`, `library` or `collection`.
- `source`: `docs`, `github-repo`, `github-discussion` or `github-issue`.
- `url`: where to read about the script. This is the forum thread when there is one.
- `code`: optional. A direct link to the file, when it differs from `url`.
- `tags`: from a fixed list (`TAGS` in `tools/catalog_lib.py`), so a tag means the same thing in every month.
- Optional fields: `version`, `featured`, `stars` (repositories), `reactions` (forum posts).
- `added_by`: which process put the entry there, `seed:<source>` or `ai-scan:<month>`. Re-running a seed replaces only that seed's entries, so scan results and manual edits survive.

## How the monthly feed works

1. **`scan.py`** reads the discussions and issues of `freeplane/freeplane` updated in the month, through the GitHub GraphQL API. It keeps the posts created in that month (opening posts, comments and replies) that contain a Groovy-looking code block of four lines or more, or name a `.groovy` / `.addon.mm` file. This is a cheap filter, and it is meant to let too much through. For October 2026 it kept 7 posts out of 27 threads.
2. **`classify.py`** first sets aside the posts that only link to a script file the catalog already has. The other posts go to Claude one at a time, with the thread's title and opening post for context, under the instructions in `tools/prompt.md`. The answer is constrained by a JSON schema: does the post share a script, plus a name, a description, the kind, the tags and the reason. A bug reproduction, a question or a one-liner answer is rejected.
3. The accepted posts are merged into `catalog.json`. The report (`data/scans/<month>.md`) lists what was added, what was rejected and why, and what was already known. The workflow uses that report as the pull request description, so the review happens on the PR.

See [`data/scans/2026-10.md`](data/scans/2026-10.md) for a real report. In that run, 4 posts were added, 1 was rejected (an autosave bug reproduction) and 2 were recognized as pointers to scripts already listed.

> **About that first run:** this proof of concept was built without an Anthropic API key. The October decisions were made by Claude Code, applying `tools/prompt.md` to each post by hand, and fed in with `classify.py --decisions`; the report says so in its first line. The API path was checked up to authentication: with a dummy key the SDK accepts the request and the API answers 401. It has not been run end to end.

## Running it

```sh
pip install -r tools/requirements.txt

python tools/seed.py                       # rebuild the seeded entries
python tools/scan.py --month 2026-10       # -> work/candidates-2026-10.json
python tools/classify.py work/candidates-2026-10.json     # needs ANTHROPIC_API_KEY
python -m http.server                      # then open http://localhost:8000
```

`scan.py` needs a GitHub token: it uses `GITHUB_TOKEN` if set, otherwise `gh auth token`. In the workflow the default Actions token is enough, because the data is public. The workflow also needs one secret, `ANTHROPIC_API_KEY`.

To publish the page, enable GitHub Pages on the `main` branch, root folder.

## Known limits and next steps

- **Seed tags are guesses.** Seeded entries were tagged by keyword rules, not by the AI, and some tags are wrong (for example, a script that mentions icons in passing gets `images-icons`). Running those entries through `classify.py` once would fix them.
- **Most macmarrum scripts have no description.** Their files rarely start with one, so 180 of the 198 show "No description yet". Giving the AI the code of those files would fill the gap; that is the same call with a different input.
- **Old forum.** The SourceForge forum and the years of GitHub discussions before the first scan are not covered. `scan.py --since 2020-01-01` would cover the GitHub part, at the cost of one classification per candidate.
- **Popularity is a snapshot.** `reactions` is copied when an entry is added and never refreshed. A monthly refresh would make "most reactions" meaningful.
- **Suggestions from users.** There is no form yet. An issue template ("suggest a script: link") could feed the same `classify.py`.
