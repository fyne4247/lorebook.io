# Agent Handoff

## Objective And Acceptance
Publish Lorebook as a public GitHub repository. Acceptance: AI turns cannot overwrite the open document or author-owned project files, setup uses only bundled skills, the README states beta and licence terms, and the published history does not include the old novelWriter commits. The owner confirmed that rebuilding that history is unnecessary.

## Repository State
Integration checkout is the `app` folder of this Lorebook project.
Branch after the history rewrite: `main`.
The previous novelWriter history, local feature branches, and tags are removed on purpose. Public repository: `https://github.com/fyne4247/lorebook.io`. Branch `main` is the only published history. Do not push to `fyne4247/novelWriter` and do not add the old history back.

## What Landed
- macOS setup checks that Qt can start, and reinstalls it once if that check fails.
- README labels Lorebook as beta, credits novelWriter and the Brainstormer fork, and describes what the AI can read.
- Portable `Setup.command` and `Lorebook.command` are tracked.
- An AI turn locks the open document, stops the AI process before the project closes, and reverts manuscript files the turn changed.
- Refreshing AI skills updates app-owned files and leaves custom or edited project files in place.
- Skill files are loaded from the copy bundled inside the app.

## Verified
Focused AI, chat-panel, and preferences tests: 145 passed, offscreen Qt.
Type check of the AI modules and the touched screens: 0 errors when pointed at the project virtualenv.
Full line and branch coverage of every AI module is not 100 percent. `novelwriter/ai` is about 72 percent line-and-branch after those tests. Chat log and agent modules are fully covered. The Claude process code is the large gap.
Two older full-suite failures were already reported on the upstream baseline (logging width and a missing sample archive). They were not rerun in this pass.

## Active CI Repair (23 October 2026)

Owner requested Luna agents to fix the diagnosed GitHub check failures. This is a bounded repair, without a phase-oriented plan. Do not push, publish, restore old history, or change the AI permission policy.

Baseline: `main`, `fcb0d2df48dbce4cd4d31af2f22ea839ebc44457`; initially clean. Integration branch: `fix/github-checks` in `app`. Nothing merged to main or pushed in this repair.

- Luna `formatting_and_ai_test`: `../ci-formatting`, branch `fix/ci-formatting`, starting at baseline. Fix formatting in the prose-critique analyser, editor header, and GUI AI end-to-end tests; align the stale writer assertion with the restricted permission policy. State: implementing, unreviewed.
- Luna `config_reference`: `../ci-config-reference`, branch `fix/ci-config-reference`, commit `022feba8637f879b32bc8c8ed7eabd991c745d9e`. Parent reviewed the exact two reference-line changes and integrated them. Targeted config test passed (1 passed). The two trailing spaces are intentional serializer output, not whitespace mistakes.
- Luna `remaining_lint`: `../ci-lint`, branch `fix/ci-lint`, starting at baseline. Resolve remaining lint findings outside the first agent's three files. State: implementing, unreviewed.
- Parent owns this handoff, independent review, integration, and verification.

Acceptance: formatting and lint checks pass; the two reported failing tests pass without weakening manuscript protections or changing config behaviour; run type checks and proportionate offscreen tests, reporting any additional failures. Parent baseline full Ruff check found 99 findings previously masked by formatting; those are now delegated. Baseline full Pyright with the app virtualenv passed (0 errors). Existing historical verification above is not verification of this repair.

## NEXT ACTION
Review each Luna agent's committed changes and focused test evidence. Integrate accepted changes into `fix/github-checks`, run the integrated checks, and record exact commits and results here before reporting. Keep the work local; do not push.
