# Agent rules

The rules for changing this repository, for people and coding agents alike, live in [`AGENTS.md`](../AGENTS.md). This page sums them up and links to the sections, so there is only one copy to keep current.

- No proprietary Muse SDK files and no private data in the repo: no recordings, sleep data, dream reports, calibration files or device identifiers. See [Safety And Data Rules](../AGENTS.md#safety-and-data-rules) and [`sdk_policy.md`](sdk_policy.md).
- Small diffs tied to one issue, after the [git preflight](../AGENTS.md#required-git-preflight), and never a plain `--force` push. See [Commit And Push Rules](../AGENTS.md#commit-and-push-rules).
- Tests with every Python change, synthetic or replay-based before live BLE. See [Testing Expectations](../AGENTS.md#testing-expectations).
- Conservative sleep-time audio: low volume, fades, cooldowns, the arousal guard and an emergency stop, and REM probability never reaches audio without the stable gate. See [Implementation Guidance](../AGENTS.md#implementation-guidance).
- No clinical, medical or lucid-dreaming efficacy claims: report metrics and their limitations.

CI runs `scripts/check_forbidden_files.py` and the test suite on every pull request.

The 2026-10 uniqueness initiatives (sub-issues of EPIC #1 titled `Initiative N: …`) are driven issue → PR → merge by the `initiatives` skill in [`.claude/skills/initiatives/SKILL.md`](../.claude/skills/initiatives/SKILL.md); the research behind them is in [`docs/research/2026-10-uniqueness/`](research/2026-10-uniqueness/report.md).
