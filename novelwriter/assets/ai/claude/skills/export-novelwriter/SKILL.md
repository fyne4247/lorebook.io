---
name: export-novelwriter
description: >
  Export a project's kb/, work/, and story/ Markdown files into an existing
  novelWriter project directory, so the author can browse/draft them inside
  the novelWriter app. One-way, opt-in per project, never touches
  novelWriter's own state (writing-time tracking, GUI options).
---

# Export to novelWriter

Runs `scripts/export_novelwriter.py "<Project Folder Name>"` to sync a
project's Markdown into an **existing** [novelWriter](https://novelwriter.io)
project directory (a `nwProject.nwx` + `content/*.nwd` folder the author
already created with the novelWriter app).

This is **not** part of `/save` or the post-commit hook. It only runs when
explicitly invoked, since most projects in this workspace don't use
novelWriter.

## What it does

- Reads every `.md` file under a project's `kb/`, `work/`, and `story/`
  folders and creates or updates a matching document inside the target
  novelWriter project.
- Routes files into folders by source path (see `FOLDER_RULES` in the
  script) — e.g. `kb/characters/*.md` → a `Characters (synced)` folder under
  novelWriter's `CHARACTER` root, `story/**` → `Manuscript (synced)` under
  the `NOVEL` root. Existing roots (Characters, Locations, Plot, Novel,
  Archive, Trash) are reused if the author already has them; missing ones are
  created.
- **Only ever touches items it created.** Every managed item is tracked by
  relative source path in a git-ignored `.novelwriter-handles.json` cache
  inside the project folder. Anything the author built by hand in the app —
  folders, documents, the rest of the tree — is left completely alone, even
  if a name happens to collide (hence the `(synced)` suffix on generated
  folders, so it's visually obvious which parts of the tree this tool owns).
- A source file that's deleted moves its novelWriter item to **Trash**
  (reparented, matching how novelWriter's own delete works) — the `.nwd`
  file is never removed from disk by this script.
- **Never writes to `meta/`** (`sessions.jsonl`, `index.json`,
  `options.json`) — novelWriter's own writing-time tracking and GUI state
  survive every export untouched. novelWriter recomputes its outline cache
  on its own; it doesn't need us to.
- Takes its own timestamped zip safety backup of the whole target directory
  before writing anything, into `~/Backups/<Project Title>/<Project Title>
  pre-export <timestamp>.zip` — independent of whether the author has ever
  used novelWriter's own in-app backup.

## Setup (per project, per machine)

The novelWriter project's location is machine-specific — e.g. synced via
Dropbox, different paths on different computers — so it's **not** committed
to git. On first run for a project, the script prompts for the path and
saves it to a git-ignored `.novelwriter-export.json` inside that project
folder. Anyone using this workspace on their own machine gets prompted once
and points it at wherever their own novelWriter project lives.

## Usage

```
python3 scripts/export_novelwriter.py "Breaking the Beasts"
```

## Known limitations

- **One-way only.** Prose or notes written inside novelWriter don't flow
  back into `kb/`/`work/`/`story/`. Two-way sync is a deliberately deferred,
  harder future piece (conflict handling, etc.).
- Cached per-item word/char/paragraph counts refresh on write, but
  novelWriter's own `<content ... novelWords=...>` project-level totals are
  left stale until the app itself reindexes — cosmetic only, not a
  correctness issue.
- The folder routing (`FOLDER_RULES` in `scripts/export_novelwriter.py`) is a
  reasonable default mirror of this workspace's `kb/`/`work/` layout, not a
  merge into however the author has organized things by hand inside
  novelWriter — edit `FOLDER_RULES` directly if you want different routing.
