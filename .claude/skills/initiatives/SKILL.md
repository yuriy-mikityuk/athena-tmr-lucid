---
name: initiatives
description: Drive the uniqueness initiatives of EPIC #1 (the open sub-issues titled "Initiative N: …") autonomously from issue to merged pull request, one worker agent per issue, in the recommended order, and report what only the maintainer can do. Use when asked to work the initiatives, take the next initiative, continue the initiative run, or list what the maintainer still has to do.
---

# Initiatives: issue → PR → merge, without a human in the loop

You are the main agent. You coordinate and verify; worker agents implement. Everything runs on the maintainer's machine, in this checkout, with the maintainer's `gh` login. Read `AGENTS.md` first: its preflight, commit, data and safety rules bind you and every worker, and nothing on this page overrides them.

## What the run covers

The ten initiatives were filed on 2026-10-22 as sub-issues of EPIC #1 with titles that start with `Initiative N:`. Their evidence base is `docs/research/2026-10-uniqueness/report.md` (part 2 ranks them) and the notes next to it; the drafts they were filed from are in `docs/research/2026-10-uniqueness/issues/`. Recommended order, from the report:

5 → 1 → 9 → 8 → 3 and 7 → 4 → 6 → 2 → 10

The "Depends on" section of each issue wins over this list when they disagree.

## Preconditions: check them, never assume them

- `gh auth status` succeeds and `gh api user --jq .login` prints the maintainer's login.
- `git fetch origin --prune && git status -sb` shows a clean checkout on `main`, then the rest of the AGENTS.md preflight.
- `python -m pytest tests/ -q` passes once on `main` before the first worker starts, so a red worker branch is the worker's doing.
- Node 22 (or Node 20 with `--experimental-websocket`) is installed if any ready initiative lists `app/static/` under Files.

If a precondition fails, stop and tell the maintainer exactly which one. Do not work around authentication or permissions.

## The loop

1. List candidates: `gh issue list --state open --search "Initiative in:title" --json number,title,body --limit 50`, keep the issues whose title starts with `Initiative `. An initiative is ready when every issue named in its "Depends on" section is closed (`gh issue view <n> --json state --jq .state`) and it has no `needs-maintainer:` comment from this run that is still unanswered.
2. Pick the ready initiative that comes earliest in the recommended order. Run at most two workers at a time, and two only when their issues' "Files" sections do not overlap.
3. Spawn a worker with the Agent tool (`subagent_type: general-purpose`, `isolation: worktree`), giving it the worker brief below verbatim followed by the full issue body (`gh issue view <n> --json title,body`). Wait for its report. Do not implement in your own context.
4. When a worker reports a merged PR: `git checkout main && git pull --ff-only origin main`, confirm the issue is closed (`gh issue view <n> --json state`), and go back to step 1. When a worker reports a blocker, make sure the issue carries one `needs-maintainer:` comment that states the exact action, and move on to the next ready initiative.
5. Stop when nothing is ready. Then post one comment on EPIC #1 (or edit this run's earlier comment) with, per initiative: the merged PRs, the open blockers with the exact action the maintainer has to take, and any follow-up issues the workers filed. Say the same in chat, in the maintainer's language.

## Worker brief

Give the worker this text verbatim, then the issue title and body.

> You implement exactly one GitHub issue of yuriy-mikityuk/remind-eeg, end to end, without asking anyone. `AGENTS.md` binds you; read it before touching anything.
>
> 1. Run the AGENTS.md preflight. Branch from `origin/main`: `git checkout -b claude/initiative-<n>-<short-slug> origin/main`.
> 2. Implement only the issue's Scope. Keep the diff small and scoped; put engine code in the matching `muse_tmr` subpackage and new commands in `muse_tmr.cli.main`; update `docs/USAGE.md`, the README or the relevant runbook whenever you add a command, a file format or a safety behaviour. Use synthetic fixtures and replay, never live BLE or real audio. Never commit recordings, calibration files, dream reports, device identifiers, generated audio or SDK files.
> 3. Prove the change before you push: `python run_tests.py`, and `python run_tests.py --all` when shared behaviour, binary formats, parser logic, replay or scheduler contracts change; `python scripts/check_forbidden_files.py`; `git diff --check`; for changes under `app/static/`, start `muse-tmr app --source mock --port 8799` and run `node scripts/check_page.mjs http://127.0.0.1:8799/`.
> 4. Commit in small commits with clear messages, then `git push -u origin <branch>`. Open the PR against `main` with `gh pr create`, a title in the imperative, and a body that says what changed, how it was tested, the remaining risks or limitations, and ends with `Closes #<n>`.
> 5. Wait for CI with `gh pr checks <pr> --watch`. If a check is red, read it (`gh run view <run-id> --log-failed`), fix the cause, push, and watch again. Never skip, disable or quarantine a test to get green; never push an empty commit or close and reopen the PR to rerun CI; after a rebase onto `origin/main` push with `--force-with-lease`, never plain `--force`.
> 6. When CI is green and the PR is mergeable, merge it: `gh pr merge <pr> --merge --delete-branch` (the repository keeps merge commits). Confirm `gh issue view <n> --json state --jq .state` prints CLOSED; if it does not, close the issue with a comment that names the PR.
> 7. If an acceptance criterion needs something only the maintainer can provide (a night of recording, paired hardware, a token or account, a dataset agreement, a decision), finish and merge everything else first, then comment on the issue with `gh issue comment <n> --body "needs-maintainer: <exact action>. Why: <reason>. Afterwards run: <command or step>"` and leave the issue open. Never tick a checklist item you did not complete.
> 8. Report back in a few lines: the PR URL, merged or not, how you tested, what remains open and why.

## Rules that are easy to forget

- One issue per PR. Something unrelated that deserves fixing becomes a new issue (`gh issue create`), not part of this PR.
- No code, doc, issue comment or PR text may claim lucid-dreaming, memory or clinical efficacy. Report metrics and their limitations.
- Live BLE and sleep-time audio are maintainer actions, never agent actions; the issues list them under "Needs from the maintainer".
- Cite `docs/research/2026-10-uniqueness/` in PRs instead of re-deriving the evidence.
- If a worker dies or returns nothing, check `gh pr list --head claude/initiative-<n>-*` and the worktree before spawning another one for the same issue, so two workers never push to the same branch.
