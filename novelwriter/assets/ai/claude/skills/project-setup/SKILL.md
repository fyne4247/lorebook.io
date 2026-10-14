---
name: project-setup
description: >
  One-time project setup for creative writing. Interviews you about your project, collects writing samples, proposes kb structure, and creates CLAUDE.md with project conventions.
---

# Project Setup

Guide the author through setting up their creative writing project. The goal
is a working `CLAUDE.md` and directory structure that all agents read for
project-specific conventions, plus initial style files if writing samples are
available.

## Learn About the Project

Ask about:

- What kind of project: novel, short story collection, serial?
- How far along: starting fresh, or existing chapters and worldbuilding?
- Single POV or multiple? Linear or non-linear timeline? How much worldbuilding?
- Where do they keep their writing? What's the existing layout?

## Writing Samples and Style

Ask about writing samples: these are the foundation for style analysis:

- Do they have sample chapters or scenes already written?
- Do they have writing from other projects that captures the voice they want?
- Are there published works they want to draw style inspiration from?
- Voice goals: close third, omniscient, first person? Formal, colloquial?

Collect whatever they have. Save samples to `kb/samples/` so they're available
for future style analysis. If they have enough material, offer to analyze
their style using the `/style-analysis` methodology: read the samples,
identify the voice dimensions, and produce initial style files in `kb/styles/`.

If they're starting fresh with no samples, capture their voice goals in
CLAUDE.md so style files can be created from early drafts.

### Pointing at existing files

The author doesn't need to paste text into chat. If they name a path — a
single file ("my draft is at `~/Drafts/chapter1.txt`") or a whole folder
("everything in `~/Documents/MyNovel/`") — read it directly with Read/Glob
and copy what's relevant into `kb/samples/`. This also works for files
already inside the repo, elsewhere on disk, or a folder mixing chapters,
notes, and outlines together; just ask which parts are actual prose samples
versus reference material.

### Non-plain-text formats

Read only handles plain text (`.md`, `.txt`, and similar). `.docx`, `.rtf`,
and `.odt` (OpenDocument Text) are compressed/binary formats — reading them
directly returns garbage, not prose. Before ingesting a sample, check the
extension and walk this decision tree:

1. **Already plain text** (`.md`, `.txt`): read it directly, done.
2. **Not plain text**: run `which pandoc`.
   - **Pandoc found**: convert with
     `pandoc "<source>" -o "kb/samples/<name>.md"` and read the result. No
     need to ask first — this only touches files inside the project.
   - **Pandoc missing**: run `which brew`.
     - **Homebrew found**: ask the author in plain language — "I can't read
       `.docx` files directly. I can install a small free tool called pandoc
       to convert it (one command, takes a few seconds) — want me to?" Only
       run `brew install pandoc` after they say yes; never install it
       silently. Once installed, convert as above.
     - **Homebrew missing too**: don't try to install Homebrew — that's a
       bigger, riskier step (downloads and runs a script from the internet)
       and not something to do for someone unfamiliar with their own
       machine. Skip straight to the fallback below.
3. **Fallback (no installs, works for anyone)**: ask the author to re-export
   the file as plain text from whatever program made it — Word: File → Save
   As → "Plain Text (.txt)"; Google Docs: File → Download → "Plain Text
   (.txt)"; LibreOffice/OpenOffice (`.odt`): File → Save As → "Text
   (.txt)". Point back at the exported file once it's ready. Don't guess at
   binary content in the meantime.

## Propose and Iterate

Based on what you learn, draft a `CLAUDE.md` section and show it to the
author. Cover:

- **Project overview**: what the project is, one paragraph
- **Author's space**: where the author keeps their writing and how it's
  organized
- **KB structure**: what subdirectories exist under `kb/` and what they're
  for. Suggest based on project complexity:
  - Simple (short story, single POV): `characters/`, `canon/`, `styles/`, root `vocab.md`
  - Medium (novel, few POVs): add `timeline/`
  - Complex (series, large world): add `world/`, `issues/`, and domain vocab files such as `world/vocab.md`
- **Voice and style**: what style files exist, what samples they're derived
  from, voice goals not yet captured
- **Conventions**: anything project-specific: naming patterns, chapter
  numbering, POV tagging, spoiler handling
- **Shared vocabulary**: early canonical terms, aliases, invented words,
  genre terms with project-specific meanings, and terms the author wants
  agents to avoid or distinguish

Present the draft and let the author adjust. Iterate until they're satisfied.

## Create the Files

Once approved:

1. Write or update `CLAUDE.md` with the agreed content
2. Create the `kb/` directories referenced in CLAUDE.md
3. Create `kb/vocab.md` when the project has named concepts agents must use
   consistently; create domain vocab files when a domain already has enough
   distinct terms
4. Create `work/` with standard subdirectories (outline/, drafts/,
   critique-reports/, brainstorm/)
5. Save any writing samples to `kb/samples/`
6. If samples were provided and the author wants style analysis, produce
   initial style files in `kb/styles/`

## Existing Projects

If `CLAUDE.md` already has creative writing conventions, read it first and
suggest updates rather than overwriting.
