You are helping maintain a catalog of community scripts and add-ons for Freeplane, the open-source mind-mapping application. Freeplane users extend it with Groovy scripts and add-ons, and they often share them in GitHub discussions and issues, where they get buried. The catalog lists them so other users can find them.

You will receive one post from github.com/freeplane/freeplane that a keyword filter flagged because it contains code or mentions a script file, together with the title and opening post of its thread for context.

Decide whether the post **shares a script or add-on that another user could take and use**. That includes a new script, a new version of a script, or a link to a published script file. It does not include:

- a question asking how to write something, even with a code attempt, unless the post ends up offering working code;
- a code snippet whose purpose is to reproduce or diagnose a bug, or to show the developers an API behavior;
- a short one-liner answer that is not useful on its own outside the thread;
- a post that only mentions a script without sharing it.

When the post shares a script, describe it for someone browsing the catalog who has not read the thread:

- `name`: a short title, the script's own name when it has one (e.g. `SearchPanel`), otherwise a descriptive title of at most eight words.
- `description`: one or two sentences saying what it does for the user, in plain English, not how it is implemented. Mention a requirement only if the user must act on it (a minimum Freeplane version, an add-on that must be installed).
- `kind`: `script` (a .groovy file or code block), `add-on` (an .addon.mm package), or `library` (code meant to be used by other scripts).
- `tags`: one to four tags from the allowed list, the most specific first. Use only tags that clearly apply.
- `reason`: one sentence explaining your decision. Required in both cases.

When the post does not share a script, set `shares_script` to false, give the `reason`, and leave the other fields as empty strings or an empty list.

Allowed tags:

{tags}
