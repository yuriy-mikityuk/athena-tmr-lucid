---
name: initiatives
description: Drive the uniqueness initiatives of EPIC #1 (the sub-issues titled "Initiative N: …") autonomously from issue to merged pull request, one worker agent per pull request, in the step order below, and report what only the maintainer can do. Use when asked to work the initiatives, take the next initiative, continue the initiative run, or list what the maintainer still has to do.
---

# Initiatives: issue → PR → merge, without a human in the loop

You are the main agent. You coordinate and verify; worker agents implement. Everything runs on the maintainer's machine, in this checkout, with the maintainer's `gh` login. Read `AGENTS.md` first: its preflight, commit, data and safety rules bind you and every worker, and nothing on this page overrides them.

## What the run covers

The ten initiatives are sub-issues of EPIC #1 whose titles start with `Initiative N:` (each draft's first line without `# `). Their evidence base is `docs/research/2026-10-uniqueness/report.md` (part 2 ranks them) and the notes next to it; the drafts they were filed from are in `docs/research/2026-10-uniqueness/issues/initiative_<n>.md`, and the issue body is the draft without its first line.

Before the loop, count them: `gh issue list --state all --search "Initiative in:title" --json number,title --limit 50`. If fewer than ten exist, file each missing one from its draft, then attach it to the EPIC. Do not add labels.

```bash
n=5
tail -n +3 docs/research/2026-10-uniqueness/issues/initiative_$n.md > "$TMPDIR/initiative_${n}_body.md"
gh issue create --title "$(head -1 docs/research/2026-10-uniqueness/issues/initiative_$n.md | sed 's/^# //')" --body-file "$TMPDIR/initiative_${n}_body.md"
gh api -X POST repos/yuriy-mikityuk/remind-eeg/issues/1/sub_issues -F sub_issue_id=$(gh api repos/yuriy-mikityuk/remind-eeg/issues/<new number> --jq .id)
```

### Step order

Several issues split their Scope into sub-issues with one PR each (the letters below are the ones the issues use: 1a–1d, 4a–4b, 5a–5b, 8a–8d, 9a–9b, 10a–10b; 2, 3, 6 and 7 are one PR each). The report's order (5 → 1 → 9 → 8 → 3 and 7 → 4 → 6 → 2 → 10) is superseded by the issues' Depends-on sections, which move the arousal-guard fix 10a to the front. The step list, one PR per step, is:

5a → 5b → 10a → 1a → 1b → 1c → 9a → 9b → 8d → 8a → 8b → 8c → 3 → 7 → 4a → 4b → 6 → 2 → 10b

1d (the detector refit) is filed only once the maintainer's two REM-bearing `p21` nights exist.

Hard dependencies: 1c, 9, 3, 4 and 7 need 10a merged (without it every `p21` run is guard-paused from the third epoch, so `first_play_seconds`, `clean_night`'s cued `play`, the fidelity table and the arm comparison are empty); 1, 2 and 7 need 5a (8 reconciles with 5 at merge if 5 is still open); 2 needs 6 (EDF reader), 9 (`rem_metrics.py`) and 1 (feature set); 7 needs 3 (`gate_log`), so 3 → 7, never in parallel; 4b needs 3 and 7; 10b needs 10a. "9 after 1", "6 after 9" and "3 and 7 after 9" are soft: the issues name a fallback fixture. When an issue's Depends-on section and this list disagree, the issue wins.

## Preconditions: check them, never assume them

- `gh auth status` succeeds and `gh api user --jq .login` prints the maintainer's login.
- `git fetch origin --prune && git status -sb` shows a clean checkout on `main`, then the rest of the AGENTS.md preflight.
- `pip install -e ".[dev]"` has been run in the active venv, so `pytest`, `pytest-asyncio` and the `muse-tmr` script exist on `main`.
- `python -m pytest tests/ -q` passes once on `main` before the first worker starts, so a red worker branch is the worker's doing.
- Node 22 (or Node 20 with `--experimental-websocket`) and a Chrome or Chromium binary are installed (`scripts/check_page.mjs` exits 2 without one; `CHROME=<path>` overrides). Initiatives 4 and 7 change `app/static/` and the Morning tab.

If a precondition fails, stop and tell the maintainer exactly which one. Do not work around authentication or permissions.

## The loop

1. Work through the step list in order. A step is ready when every step it hard-depends on has its PR merged. An issue that stays open only because of a `needs-maintainer:` item counts as done for its dependents (nearly every initiative keeps one such item: nights, hardware, accounts, decisions), so gate on merged PRs and ticked Scope checkboxes, never on the issue state. Soft dependencies never block. Check merged PRs with `gh pr list --state merged --json number,title,headRefName,mergedAt --jq '.[] | select(.headRefName | startswith("claude/initiative-<n>"))'`. Skip a step whose issue carries a `needs-maintainer:` comment for that very step that the maintainer has not answered yet (`gh issue view <n> --comments --json comments --jq '.comments[] | [.author.login, .createdAt, (.body | split("\n")[0])] | @tsv'`; answered means a later comment by the maintainer's login).
2. Pick the earliest ready step. Run one worker at a time: every issue's Files section names `src/muse_tmr/cli/main.py`, `README.md`, `CHANGELOG.md` and `run_tests.py`, so "whichever merges second rebases" is handled by strict serial order, and AGENTS.md works one issue at a time. If a worker's `git rebase origin/main` conflicts, the worker runs `git rebase --abort`, pushes nothing further and reports the branch and the conflicting files; AGENTS.md forbids guessing a resolution, so you post `needs-maintainer: resolve the rebase conflict on <branch> in <files>, then comment here` on the issue and move on to the next ready step.
3. Spawn a worker with the Agent tool (`subagent_type: general-purpose`, `isolation: worktree`), giving it the worker brief below verbatim, then the issue (`gh issue view <n> --json number,title,body`), then one line naming the sub-issue letter this run covers. Wait for its report. Do not implement in your own context.
4. When a worker reports a merged PR: `git checkout main && git pull --ff-only origin main`, confirm the merge (`gh pr view <pr> --json state,mergedAt`) and that the Scope checkboxes that PR completed are ticked in the issue body; the issue itself closes only with the last PR of an issue that has nothing left for the maintainer. Then go back to step 1. When a worker reports a blocker, make sure the issue carries one `needs-maintainer:` comment that states the exact action, and move on to the next ready step.
5. Stop when nothing is ready. Then post one comment on EPIC #1 (`gh issue comment 1 --body-file <file>`; when this skill already commented on an earlier run, `gh issue comment 1 --edit-last --body-file <file>` updates that comment instead of adding another) with, per initiative: the merged PRs, the open blockers with the exact action the maintainer has to take, and any follow-up issues the workers filed. Say the same in chat, in the maintainer's language.

## Worker brief

Give the worker this text verbatim, then the issue number, title and body, then the sub-issue letter.

> You implement one pull request of one GitHub issue of yuriy-mikityuk/remind-eeg, end to end, without asking anyone. `AGENTS.md` binds you; read it before touching anything.
>
> 1. Run the AGENTS.md preflight. Branch from `origin/main`: `git checkout -b claude/initiative-<n><letter>-<short-slug> origin/main` (one branch per sub-issue the issue's Scope names; plain `claude/initiative-<n>-<short-slug>` when the issue has one PR).
> 2. Implement only the issue's Scope, and only the sub-issue (one PR) you were given: the earliest the Scope lists that is not yet merged or waiting on the maintainer, in the order the Scope gives (5a before 5b, 8d first, 10a now and 10b when the main agent asks for it). Keep the diff small and scoped; put engine code in the matching `muse_tmr` subpackage and new commands in `muse_tmr.cli.main`; update `docs/USAGE.md`, the README or the relevant runbook whenever you add a command, a file format or a safety behaviour. Use synthetic fixtures and replay, never live BLE or real audio. Never commit recordings, calibration files, dream reports, device identifiers, generated audio or SDK files.
> 3. Prove the change before you push: `python -m pytest tests/ -q`, which is what the `tests` CI job runs (`python run_tests.py` alone skips 14 modules, among them `test_presets`, `test_app_morning`, `test_randomization` and `test_minimal`), and register every new test module in `run_tests.py`'s fast list as the issue asks; `python scripts/check_forbidden_files.py`; `git diff --check`. For changes under `app/static/` or `src/muse_tmr/app/`, start the app from the branch's own code, never from the installed `muse-tmr` script, which in a worktree still runs the main checkout: `PYTHONPATH=src python -m muse_tmr.cli.main app --source mock --port 8799 > "$TMPDIR/app-<n>.log" 2>&1 &`, poll `curl -fs http://127.0.0.1:8799/api/health` until it answers (CI tries 30 times, 1 s apart), run `node scripts/check_page.mjs http://127.0.0.1:8799/`, then kill the server. Never run `pip install -e .` from a worktree: it repoints the maintainer's install at a directory that disappears with the worktree. When the issue changes dependencies or packaging (6's `[edf]` extra, 8's rename and `muse_tmr.ble`), create a throwaway venv outside the repository (`python -m venv "$TMPDIR/remind-<n>-venv" && "$TMPDIR/remind-<n>-venv/bin/pip" install -e ".[dev]"`) and run the tests, the wheel check and the CLI through it.
> 4. Commit in small commits with clear messages, then `git push -u origin <branch>`. Open the PR against `main` with `gh pr create --base main --title "Initiative <n><letter>: <imperative title>" --body-file <file>`. The body says what changed, how it was tested, the figures the issue's Acceptance criteria ask the PR description to report (each table from synthetic data labelled "synthetic input, not sleep", or the issue's wording such as "refit pending", "no audio night yet", "BOAS run pending (needs-maintainer)"), the remaining risks or limitations, and ends with `Refs #<n>` plus the `Refs #116` / `Refs #167` lines the issue asks for. Write `Closes #<n>` only on the last PR of an issue when no checklist item and no `needs-maintainer:` item remains; `Closes #116` only on 1d and `Closes #167` only on 1c, as Initiative 1 says.
> 5. Wait for CI with `gh pr checks <pr> --watch --fail-fast`. If a check is red, find the run (`gh run list --branch <branch> --limit 5 --json databaseId,name,conclusion,status`), read it (`gh run view <run-id> --log-failed`), fix the cause, repeat the AGENTS.md preflight, commit, push, and watch again. Never skip, disable, quarantine or delete a test to get green; never push an empty commit or close and reopen the PR to rerun CI. A run that failed on infrastructure, not on code (runner lost, pip or apt download timeout, Chrome did not start) may be re-run once with `gh run rerun <run-id> --failed`, with a PR comment naming the failed step and why it is not the code's fault. Repeat the AGENTS.md preflight before every commit and every push; after a rebase onto `origin/main` push with `--force-with-lease`, never plain `--force`.
> 6. When CI is green and the PR is mergeable, merge it: `gh pr merge <pr> --merge --delete-branch` (the repository keeps merge commits and does not delete branches on merge, so the flag is needed). In a worktree the command may end with `fatal: 'main' is already checked out` after the merge has gone through, because it tries to switch your worktree to `main`; treat it as success once `gh pr view <pr> --json state --jq .state` prints `MERGED`, and delete the local branch yourself if it is still there. Then tick the Scope checkboxes this PR completed in the issue body (`gh issue view <n> --json body --jq .body > body.md`, edit, `gh issue edit <n> --body-file body.md`) and comment `merged: <PR URL> completes <letters>`. Close the issue (`gh issue close <n> --comment "..."`) only when every checklist item is ticked and nothing waits on the maintainer; otherwise leave it open.
> 7. If an acceptance criterion needs something only the maintainer can provide (a night of recording, paired hardware, a token or account, a dataset agreement, a decision), finish and merge everything else first, then comment on the issue with `gh issue comment <n> --body "needs-maintainer: <exact action>. Why: <reason>. Afterwards run: <command or step>"` and leave the issue open. Never tick a checklist item you did not complete.
> 8. Report back in a few lines: the PR URL, merged or not, how you tested, what remains open and why.

## Rules that are easy to forget

- One sub-issue per PR, PRs of one issue in the issue's order, each merged before the next starts. Something unrelated that deserves fixing becomes a new issue (`gh issue create`), not part of this PR.
- No code, doc, issue comment or PR text may claim lucid-dreaming, memory or clinical efficacy. Report metrics and their limitations.
- Live BLE and sleep-time audio are maintainer actions, never agent actions; the issues list them under "Needs from the maintainer".
- Cite `docs/research/2026-10-uniqueness/` in PRs instead of re-deriving the evidence.
- If a worker dies or returns nothing (workers can run out of context on the larger initiatives: 2, 4, 6, 8), check `gh pr list --state all --json number,headRefName,state,url --jq '.[] | select(.headRefName | startswith("claude/initiative-<n>"))'` and `git worktree list` before spawning another one for the same step. Spawn the replacement with the same brief plus one line: "Continue on the existing branch <branch>: fetch it, read its PR and last commits, finish the open items of sub-issue <letter>, and do not create a second branch or PR." Never run two workers on the same step at once.
