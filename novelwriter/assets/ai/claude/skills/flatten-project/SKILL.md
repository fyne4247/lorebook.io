---
name: flatten-project
description: >
  Concatenate every .md file in one subproject into a single combined Markdown
  file in the workspace root (e.g. breakingthebeasts.md), for easy sharing,
  search, or a one-file snapshot of the whole knowledge base.
---

# Flatten Project

Combine all of a subproject's Markdown into one file at the workspace root.
This is a mechanical concat + heading-reflow — no prose is written or changed;
source files are read-only.

## What it produces

For a project folder like `Breaking the Beasts/`, it writes
`exports/breakingthebeasts.md` (in the workspace-root `exports/` folder) with
this structure:

```
# Breaking the Beasts          (project name, once)
## kb/world                    (subdirectory holding .md files)
### glossary.md                (a file)
#### <the file's own H1s, demoted by 3>
...
```

- **Project name** → `#`
- **Subdirectory** (relative path) → `##`; root-level files go under `## (project root)`
- **Filename** → `###`
- Every heading **inside** a source file is demoted by 3 (`#`→`####`,
  `##`→`#####`, …, capped at `######`). Headings inside fenced code blocks
  are left untouched.

Root-level files come first, then subdirectories alphabetically, files
alphabetically within each. `.git`, `.claude`, `node_modules`, and
`__pycache__` are skipped, and every `CLAUDE.md` is excluded. Everything else
(including `kb/samples/`) is included.

## How to run

From the workspace root:

```bash
python3 scripts/flatten_project.py "Breaking the Beasts"
```

Optional custom output name:

```bash
python3 scripts/flatten_project.py "Breaking the Beasts" --output snapshot.md
```

The output is **auto-generated** — to refresh it after editing the KB, just
re-run the command; it overwrites.

## Notes

- Respects the workspace rule that projects are sealed: it only reads inside
  the named project folder and writes a single file to the root.
- The combined file is a snapshot, not a source of truth. The per-file KB
  under the project remains canonical.
