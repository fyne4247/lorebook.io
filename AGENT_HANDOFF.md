# Agent Handoff

## Objective And Acceptance
Prepare Lorebook for a new public GitHub repository. Acceptance: AI turns cannot overwrite the open document or author-owned project files, setup uses only bundled skills, the README states beta and licence terms, and the Git history published from this checkout is a single new commit with the old history removed. Do not push until the owner asks.

## Repository State
Integration checkout is the `app` folder of this Lorebook project.
Branch after the history rewrite: `main`.
The previous novelWriter history, local feature branches, and tags are removed on purpose. Nothing has been pushed. The old `origin` remote pointed at `fyne4247/novelWriter` and is removed so a push cannot hit that repository by mistake.

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
When the owner asks to publish, create a new empty GitHub repository named `lorebook.io` (or `lorebook-io` if the name is taken) and push this `main` branch to it. Do not push to `fyne4247/novelWriter`. Do not force-push. Do not add the old history back.
