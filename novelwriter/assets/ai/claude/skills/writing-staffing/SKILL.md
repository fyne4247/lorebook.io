---
name: writing-staffing
type: reference
description: >
  Dispatch reference for composing writing teams. Teaches which extra skills
  to attach via --skills, which resources to reference in spawn prompts, and
  when to fan out. Load when staffing a workflow.
model-invocable: false
---

# Writing Staffing

Each agent loads its core skills from its YAML. This skill teaches what
*extra* to attach and reference when spawning.

No agent in this roster generates prose. The author writes; every dispatchable
agent below thinks, plans, evaluates, or organizes.

## Dispatch Reference

### `@critic`

Extra `--skills`: `prose-writing`, `scene-construction`, or `style-analysis`
for prose/voice focus; `shared-dao` for vocabulary checks.

Reference in prompt: assign a focus area (structure, character, voice, prose,
or continuity) from `/prose-critique`. Attach style files via `-f` for voice
critique.

Fan out with different focus areas simultaneously. Scale to stakes:
1–2 for low-stakes, 3 for standard chapters, 4–5 for pivotal scenes with
duplicated coverage on the critical dimension.

### `@editor`

Reference in prompt: name the edit level (editorial review, developmental,
line edit, copyedit, proofreading). Point to `/editorial-review` →
`resources/editorial-review.md` for the holistic pass, or the specific
edit-level resource.

Use when the draft needs a priority order across concerns. For depth on
one dimension, use `@critic`.

### `@continuity-checker`

Attach the draft plus canon files, timeline, character state, and vocab
via `-f`. More expensive than a critic with continuity focus — reads
broadly across the project. Use the critic for routine checks, the
continuity-checker for deep cross-project validation.

### `@brainstormer`

Extra `--skills`: `character-sim` for character arcs.

Reference in prompt: point to `/brainstorming` for capture conventions.
Fan out on different *angles*, not the same angle. Three perspectives
beats five instances of one.

### `@outliner`

Extra `--skills`: `story-architecture` for arc/chapter/scene structure.

Outlining starts after direction is chosen — use `@brainstormer` first.
The outliner's output guides the author's own drafting.

### `@style-creator`

Attach sample chapters or existing style files via `-f`. Point to
`/style-analysis` → resources for the analysis method.

### `@reader-sim`

Extra `--skills`: `character-sim` when the reader persona is a specific
character type.

Reference in prompt: specify the reader persona and knowledge boundary
(what has this reader already read). Attach the draft via `-f`.

Run after the author's revision settles, before the author moves on. A
scene can be technically clean and leave a reader cold.

### `@character-sim`

Attach character state and voice/style files via `-f`. Specify the scenario
or relationship to explore. Fan out for multi-character scenes.

### `@chronicler`

Extra `--skills`: `writing-artifacts`, `writing-issues`, `story-context` for
fact-extraction conventions and kb layout.

Dispatch after the triggering event settles: chapter finalized, brainstorm
concluded, author decision made. Cheap and focused — keep its scope to fact
extraction into the kb.

## Effort Scaling

Scale critic coverage to stakes. Knowledge maintenance (chronicler) waits
until direction or chapters settle. Reader-sim runs after the author's own
revision converges.
