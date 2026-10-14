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

## NEXT ACTION
Published. `main` is on `https://github.com/fyne4247/lorebook.io` and matches this checkout. Leave it unless the owner asks for another change. Do not force-push. Do not restore the old history.
