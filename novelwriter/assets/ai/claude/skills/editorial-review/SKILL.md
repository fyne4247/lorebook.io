---
name: editorial-review
type: mode-shift
description: >
  Holistic third-party book-editor pass on existing prose: what kind of revision does this draft need, and in what order? Covers developmental edit, line edit, copyedit, and proofreading as staged levels, plus synthesis of reader-sim signal. Load when diagnosing a draft rather than rewriting it. For adversarial focus-area critique, use `prose-critique` instead.
model-invocable: true
---

# Editorial Review

Analytical review of existing prose, delivered as a professional editor's
memo. This skill is for diagnosis, not rewriting. Keep `/reader-sim` separate
when the task needs a felt first-time reader experience rather than
analytical critique, and use `prose-critique` when the task calls for
adversarial, focus-area-driven fault-finding rather than a holistic pass.

Choose the review level before reading. Start big before small unless the
caller explicitly asks for a late-stage pass. The edit levels move from
structural to surface, and each assumes the levels above it are stable:

- **Editorial review** — holistic third-party book-editor pass. What kind of
  revision does this draft need, and in what order?
- **Developmental edit** — structure, promise, causality, pacing, character
  arc. Is the draft the right shape?
- **Line edit** — voice, rhythm, clarity, texture. Does the prose move well?
- **Copyedit** — grammar, usage, punctuation, consistency. Is it correct?
- **Proofreading** — final surface pass. What slipped through?

Each level has a dedicated resource with method and checklist:

- `resources/editorial-review.md`
- `resources/developmental-edit.md`
- `resources/line-edit.md`
- `resources/copyedit.md`
- `resources/proofreading.md`

When review incorporates reader-sim data:

- `resources/reader-sim-signal.md` — how to interpret and synthesize
  reader-sim output alongside analytical critique.
