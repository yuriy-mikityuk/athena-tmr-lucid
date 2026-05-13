# Agent Instructions

This repository is the implementation workspace for the Muse S Athena REM-TMR/TLR project tracked under GitHub EPIC #1.

## Project Goal

Build an open-source, home-run Muse S Athena system for overnight recording, offline replay, REM-gated cue scheduling, TLR cues, puzzle cues, morning reporting, and cued-vs-uncued analysis.

The target is protocol fidelity and measurable validation. Do not claim clinical, medical, or guaranteed lucid-dreaming efficacy.

## Current Planning Source

- EPIC: #1
- Milestones: 0 through 9
- Child issues: #3 through #42 are attached to the EPIC as sub-issues.
- Work one GitHub issue at a time unless the user explicitly asks for a cross-cutting change.
- Keep labels minimal. Do not create a large label taxonomy unless requested.

Milestone themes:

- M0: repository and governance
- M1: data source and overnight recording
- M2: replay and feature extraction
- M3: REM detection
- M4: audio cue system
- M5: TMR/TLR protocol
- M6: morning reports and experiment analysis
- M7: OpenMuse and SDK adapters
- M8: validation and effectiveness criteria
- M9: documentation and agent handoff

## Required Git Preflight

Before editing anything:

```bash
git fetch origin --prune
git status -sb
git rev-list --left-right --count origin/main...HEAD
```

If the first number from `rev-list` is greater than 0, run:

```bash
git rebase origin/main
```

If the rebase conflicts, stop and ask the user how to resolve each conflict chunk. Do not guess.

Repeat the same preflight before every commit and before every push.

## Commit And Push Rules

- Keep diffs small and scoped to the active issue.
- Avoid broad formatting, reordering, or unrelated refactors.
- Stage only files that belong to the current task.
- Use normal `git push` unless you rebased; after a rebase, use `git push --force-with-lease`.
- Never use plain `--force`.
- If the worktree contains unrelated changes, leave them alone.

## Repository Shape

The current codebase is a Python BLE/Muse library derived from the amused-py direction:

- Core modules live as top-level `muse_*.py` files.
- Examples live in `examples/`.
- Tests live in `tests/`.
- `run_tests.py` runs the existing unittest suites.
- `pyproject.toml` defines package metadata and dev dependencies.

Prefer the existing simple module style until an issue explicitly introduces a package layout or CLI structure.

## Safety And Data Rules

- Do not commit proprietary Muse SDK binaries, headers, archives, installers, docs, or copied SDK code.
- SDK must be downloaded separately and placed locally; do not commit.
- See `docs/sdk_policy.md` and run `python scripts/check_forbidden_files.py` before publishing SDK-adjacent work.
- Do not commit private overnight recordings, personal sleep data, dream reports, calibration files, or device identifiers.
- Do not commit generated cue audio by default unless the issue explicitly asks for tiny test fixtures.
- Keep raw recordings and session outputs gitignored.
- Do not rotate, print, or modify secrets or tokens.
- Do not add network upload, telemetry, cloud sync, or remote reporting without explicit user approval.

## Implementation Guidance

- Prefer deterministic replay and synthetic fixtures before live BLE tests.
- Separate live device access from offline processing so tests can run without a Muse device.
- Preserve timestamps, sample rates, modality names, units, and source metadata.
- Treat missing modalities as normal. Muse sessions may lack PPG, HR, IMU, or clean EEG for periods.
- Use conservative defaults for sleep-time audio: low volume, fade in/out, cooldowns, arousal guards, and emergency stop.
- Log cue decisions as structured events: play, skip, block reason, pause, stop, volume, and timing.
- Keep REM detection and cue scheduling separate. REM probability must not directly trigger audio without the stable gate and safety checks.
- Keep validation language precise: report metrics and limitations instead of promising effectiveness.
- On macOS, direct Python BLE commands may abort in TCC before Python logs if the launching
  bundle lacks Bluetooth privacy metadata. For live smoke tests, prefer a Homebrew Python
  virtualenv launched through `Python.app` with `open -W -n --env PYTHONPATH=... --args -m muse_tmr.cli.main ...`.
- For live `record` smoke tests, use `--allow-short` and either an explicit `--output-dir`
  under `data/recordings/` or the CLI default. Never commit raw recordings, metadata with
  device identifiers, or generated session summaries.
- M1 live BLE smoke criteria: `discover` finds the Muse, `stream` reports nonzero frames
  across expected modalities, and `record` writes `raw_amused.bin`, `metadata.json`,
  `events.jsonl`, and `summary.json` with `stop_reason=duration_complete`.
- For M2 replay/features, use `muse_tmr.data.replay.ReplaySession` as the offline source.
  It emits the same `MuseFrame` type as live BLE and supports real-time, accelerated,
  fastest-possible, and relative time-range replay. Keep feature tests synthetic or replay-based.
- Use `muse_tmr.features.epochs.EpochBuilder` for 30-second sleep windows. It must accept
  both live source streams and replay streams, tolerate missing modalities, and expose
  coverage plus quality flags for downstream EEG/IMU/PPG feature modules.
- EEG features live in `muse_tmr.features.eeg_features`. Keep band-power tests synthetic
  with known sine waves, and preserve artifact flags rather than dropping noisy epochs.
- IMU motion features live in `muse_tmr.features.imu_features`. Keep movement/arousal
  tests synthetic with known accelerometer or gyroscope bursts, preserve noisy epochs,
  and expose arousal guard reason codes rather than coupling features directly to audio.
- PPG/HR/HRV features live in `muse_tmr.features.ppg_features`. Keep pulse/HR tests
  synthetic and deterministic, treat PPG and heart-rate samples as independently
  optional, and make HRV terminology explicit as a proxy until beat-level validation exists.
- REM predictions live in `muse_tmr.models`. Keep heuristic REM tests synthetic and
  deterministic, expose `P_REM` plus reason codes, and never couple REM probability
  directly to audio playback or cue decisions.
- Manual REM annotations live in `muse_tmr.annotations`. Preserve the supported labels
  `wake`, `nrem`, `probable_rem`, and `unknown`; generated annotation templates should
  default to `unknown`, overlay feature columns, and keep training export separate from
  raw personal recordings.
- Personal REM classifier code lives in `muse_tmr.models.ml_rem_detector`. Train from
  annotation rows, skip `unknown` labels by default, keep artifacts versioned and
  loadable, and report imbalance/calibration/feature-importance metrics. Do not commit
  private trained models or real annotation files unless the user explicitly asks and
  confirms the data is shareable.
- REM confidence and stable gate code lives in `muse_tmr.models.rem_gate`. Keep it
  stateful, deterministic, replay-testable, and separate from audio. Gate decisions may
  expose `gate_open` and block reasons, but must not expose cue playback decisions.
- Low-volume audio playback lives in `muse_tmr.audio.audio_player`. Keep playback
  behind an explicit player facade with volume caps, fade metadata, emergency stop, and
  JSONL logging. Tests must use mock or dry-run backends and must not require speakers.
- Cue library metadata lives in `muse_tmr.audio.cue_library`. Keep catalogs separate
  from private audio files, validate missing files before sessions, and do not commit
  real cue audio or private cue paths unless the user explicitly confirms they are safe.
- Pre-sleep volume calibration lives in `muse_tmr.audio.volume_calibration`. Store
  detectable, identifiable, and comfortable volumes per playback device, keep
  calibration files out of git, and make scheduler code use the calibrated comfortable
  volume as the max while still respecting a hard safety cap. Missing calibration
  should block planned sleep-time cue sessions.
- Pre-sleep puzzle session management lives in `muse_tmr.protocol.puzzle_protocol`.
  Keep puzzle catalogs, timed attempts, solved/known/retired filters, and association
  checks separate from cued-vs-uncued randomization. Do not commit private puzzle
  content, user responses, or generated sessions; `data/protocol/` is gitignored.
- Cued-vs-uncued randomization lives in `muse_tmr.protocol.randomization`. Use seeded
  `PuzzleCueAssignment` records and make scheduler code consume `scheduled_puzzle_ids`
  or `scheduled_cue_ids()`, never all session puzzle IDs, so uncued controls cannot be
  scheduled.
- TLR cue support lives in `muse_tmr.protocol.tlr_protocol`. Keep default cue metadata,
  pre-sleep training events, and REM TLR block planning separate from the final scheduler.
  Training should use `AudioCuePlayer` with mock or dry-run backends in tests and must
  write structured events.
- REM-gated cue scheduling lives in `muse_tmr.protocol.tmr_scheduler`. It should consume
  `RemGateDecision`, optional `TlrBlockPlan`, and `PuzzleCueAssignment.scheduled_puzzle_ids`;
  never schedule uncued puzzles. Keep it deterministic and replay-testable, log
  `play`, `skip`, `pause`, and `stop` events, and do not call real audio playback inside
  the scheduler.
- Arousal guard logic lives in `muse_tmr.protocol.arousal_guard`. Keep it feature-row
  based, configurable, conservative by default, and replay-testable. It may return
  `allow`, `lower_volume`, `pause`, or `stop` decisions from motion, alpha, HR-jump,
  and artifact-quality proxies, but it must not play audio directly.
- Morning dream report capture lives in `muse_tmr.reports.dream_report`. Keep reports
  structured, local-first, and versioned; link dream content to generated session puzzle
  IDs only after validating against `NightPuzzleSession`. Do not commit real dream
  reports, private recall text, or morning session outputs.

## Testing Expectations

For Python changes, run the fastest relevant checks:

```bash
python run_tests.py
```

For targeted changes, prefer focused tests first, for example:

```bash
python -m unittest tests.test_realtime_decoder
python -m unittest tests.test_raw_stream
python -m unittest tests.test_ppg_fnirs_fast
```

Run all tests when shared behavior, binary formats, parser logic, replay, or scheduler contracts change:

```bash
python run_tests.py --all
```

For docs-only changes, at minimum run:

```bash
git diff --check
```

## Documentation Rules

- Update README or project docs when adding a user-visible command, protocol step, file format, or safety behavior.
- Keep setup instructions reproducible from a clean checkout.
- Distinguish required dependencies from optional visualization, OpenMuse, or SDK-related adapters.
- Document any binary output format and generated artifact location before relying on it.

## Issue Handoff

When finishing an issue, leave enough context for the next agent:

- what changed
- how it was tested
- remaining risks or limitations
- any follow-up issue numbers

Prefer small PRs or commits tied to a single issue number.
