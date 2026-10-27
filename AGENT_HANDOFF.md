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

- Luna `formatting_and_ai_test`: `../ci-formatting`, branch `fix/ci-formatting`, commit `baa2e1f53ac7ba67aceb5fae25800b89f80b0038`. Parent reviewed and integrated the three-file change. Offscreen GUI tests: 8 passed, 1 skipped; per-file Ruff formatting/checks and Pyright passed. Policy assertions were strengthened; implementation permission policy unchanged. Analyser attribution checked against bundled NOTICE.
- Luna `config_reference`: `../ci-config-reference`, branch `fix/ci-config-reference`, commit `022feba8637f879b32bc8c8ed7eabd991c745d9e`. Parent reviewed the exact two reference-line changes and integrated them. Targeted config test passed (1 passed). The two trailing spaces are intentional serializer output, not whitespace mistakes.
- Luna `remaining_lint`: `../ci-lint`, branch `fix/ci-lint`, commits `1979b54655f9a06b43c3b04c5e49c7455584d608` and correction `70db7fed23599771253cc09f935ed45898298942`. Parent reviewed and integrated both. Review finding resolved: two test references now match the renamed public panel callback. Agent focused suite: 107 passed; wiring file: 5 passed; owned-file Ruff and full Pyright passed.
- Parent owns this handoff, independent review, integration, and verification.

Acceptance: formatting and lint checks pass; the two reported failing tests pass without weakening manuscript protections or changing config behaviour; run type checks and proportionate offscreen tests, reporting any additional failures. Parent baseline full Ruff check found 99 findings previously masked by formatting; those are now delegated. Baseline full Pyright with the app virtualenv passed (0 errors). Existing historical verification above is not verification of this repair.

Final reviewed implementation integration: `c4bb9f7`. Full Ruff format check: 271 files already formatted; full Ruff check passed; full Pyright passed (0 errors). Parent offscreen suite excluding wiring: 709 passed, 3 skipped, 2 failed; integrated wiring file separately: 5 passed. Both original GitHub test failures pass. Local Python is 3.12, while GitHub MacOS uses 3.14; no remote rerun was triggered. Full coverage was not measured or claimed.

The two remaining failures were independently reproduced by Luna in `../ci-config-reference` at `022feba` (only the reference spacing differs from original baseline): `tests/test_init.py::testBaseInit_Options` expects coloured logging width 17 but receives 8; `tests/tools/test_welcome.py::testToolWelcome_Main` cannot find the sample archive. Neither affected implementation was changed. These local baseline/environment issues are outside this repair; no sample files were edited. `git diff --check` reports only the two intentional serializer spaces in the reference fixture.

All repair changes are committed and reviewed locally. Main remains at the original baseline; no merge to main, push, deployment, or live AI execution occurred. Task worktrees are preserved. The historical publication state above refers to the pre-repair release, not these fixes.

## NEXT ACTION
Await owner approval before merging `fix/github-checks` into main. Push only if explicitly requested, then inspect the new GitHub checks (including Python 3.14). If addressing the two local baseline/environment failures, investigate colour detection and sample asset preparation separately; preserve the current reviewed fixes.
