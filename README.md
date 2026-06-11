# athena-tmr-lucid

**REM-gated Targeted Memory Reactivation engine for the Muse S Athena EEG headset — overnight recording, real-time REM detection, and safety-gated audio cueing for a Konkoly-like TLR protocol. Python.**

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/yuriy-mikityuk/athena-tmr-lucid/actions/workflows/guardrails.yml/badge.svg)](https://github.com/yuriy-mikityuk/athena-tmr-lucid/actions)

The system records sleep biosignals all night (EEG, IMU, PPG), detects REM in real time, and plays quiet audio cues only when a stack of safety gates agrees it is safe to do so. Around that core it implements a full single-subject experimental protocol: pre-sleep puzzle sessions with seeded cued/uncued randomization, TLR cue familiarization, REM-gated cueing at night, and morning dream reports with blind retests and cued-vs-uncued analysis.

> **Status & scope:** not a medical device, n=1 research. Personal research software, self-experimentation only. No clinical, diagnostic, therapeutic, or lucid-dreaming claims. The engineering targets are protocol fidelity, safety guardrails, structured logging, and measurable validation.

## Highlights

- **Real-time pipeline:** BLE frames → 30-second epochs → multi-modal features → REM detection → stable gate → arousal guard → cue scheduler → volume-capped audio
- **Multi-modal feature extraction:** EEG band powers (delta–gamma), relative powers, theta–alpha and slow–fast ratios, frontal/posterior asymmetry, an eye-movement proxy; IMU motion/stillness and arousal proxies; PPG heart rate, HR trend, and HRV proxies
- **Trainable personal REM classifier:** class-balanced logistic regression on hand-annotated epochs, saved as a versioned JSON artifact with calibration metrics, feature importance, and training metrics — on top of a transparent non-ML heuristic baseline
- **Safety-first cueing:** model probabilities never reach the audio path directly; a `StableRemGate` (minimum stable time, hysteresis, cooldown) and an `ArousalGuard` (motion, alpha, HR-jump, artifact proxies) decide, with hard volume caps, fade in/out, and emergency-stop artifacts
- **Blind experimental protocol:** seeded randomization into cued/uncued puzzle groups, uncued puzzles are never schedulable, the condition is hidden from the subject during morning retests
- **Pluggable acquisition:** amused-py BLE (default), OpenMuse LSL, and BrainFlow backends, all mapped to one `MuseFrame` contract; plus a local web app for sensor-contact setup before bed
- **Reproducible validation:** five staged pilots, each with a runbook and an automated validator
- **Engineering hygiene:** 28 CLI commands, pytest suite with CI on GitHub Actions, and a privacy-aware gitignore — volume calibration, puzzle content, and dream reports never leave the machine

## Architecture

```
Muse S Athena (BLE)
   │
   ▼
acquisition source ····· amused-py (default) / OpenMuse LSL / BrainFlow
   │                     → unified MuseFrame stream
   ▼
recorder ──► binary session ──► offline replay (0×–20× speed)
   │
   ▼
30-second epoch builder (coverage & quality flags)
   │
   ▼
feature extraction ····· EEG band powers · IMU motion/arousal · PPG HR/HRV
   │
   ▼
REM detection ·········· heuristic baseline + personal classifier (P_REM)
   │
   ▼
StableRemGate ·········· stable-time threshold, hysteresis, cooldown
   │
   ▼
ArousalGuard ··········· motion / alpha / HR-jump / artifact proxies
   │
   ▼
TmrCueScheduler ········ TLR block first, then cued puzzle cues only
   │
   ▼
audio player ··········· calibrated volume cap, fade, JSONL logs
   │
   ▼
morning ················ dream report · blind retest · cued-vs-uncued analysis
```

The engine lives under `src/muse_tmr/`; the top-level `muse_*.py` modules are the forked BLE/data-source layer (see [Attribution](#data-source-layer--attribution)).

## The experiment

A Konkoly-style targeted-lucidity protocol combined with puzzle-based TMR, run end to end by the CLI:

1. **Pre-sleep:** timed puzzle attempts against a private catalog, cue–solution association checks, TLR cue familiarization, and per-device volume calibration (detectable / identifiable / comfortable thresholds — the comfortable level becomes the hard scheduler cap).
2. **Session generation:** a seeded night session of four eligible unsolved puzzles; a second seeded step assigns half to the **cued** group. The scheduler only ever sees the cued IDs, so uncued puzzles physically cannot be played.
3. **Night:** overnight recording (2–8 h) with real-time REM detection. When the stable gate opens and the arousal guard allows it, the scheduler optionally plays a TLR block, then cued puzzle cues — respecting per-cue intervals, cooldowns, and max-per-block limits, and logging structured `play` / `skip` / `pause` / `stop` events.
4. **Morning:** dream report (lucidity, cues heard, confidence, free recall, validated per-puzzle links) and a **blind** puzzle retest where the cued/uncued condition is never revealed to the subject.
5. **Analysis:** cued-vs-uncued solve rates, dream-incorporation rates, retest durations and confidence, and cue timing — intentionally descriptive, with explicit small-sample limitations.

## ML pipeline: personal REM classifier

The REM detector ships in two layers. A transparent **heuristic baseline** (`HeuristicRemDetector`) scores each epoch from EEG/IMU/PPG feature rows and returns `P_REM` with human-readable reason codes — no ML, fully inspectable. On top of it, `annotate-template` exports per-epoch CSVs overlaid with `P_REM` and features for manual labeling (`wake` / `nrem` / `probable_rem`), and `train-rem-classifier` fits a **class-balanced logistic regression** on those labels. The saved artifact is versioned JSON containing the coefficients, **calibration metrics, feature importance, and training metrics** — so every model used at night is auditable. By design, model probabilities never reach the audio path directly; only the stable gate plus arousal guard can authorize a cue.

## Validation pilots

Each stage has a runbook in `docs/` and an automated validator, so a failed precondition is caught before a night is wasted.

| Pilot | Goal | Tooling |
| ----- | ---- | ------- |
| 1 | 6 h+ overnight recording with **no audio** — data quality, uptime, packet capture | `validate-pilot1-recording` · `docs/pilot1_no_audio.md` |
| 2 | Daytime audio volume calibration — ordered thresholds, cap enforcement probe | `validate-pilot2-calibration` · `docs/pilot2_audio_calibration.md` |
| 3 | Replay-only cue simulation with mocked audio — **fails if any uncued puzzle gets a `play` event** | `simulate-replay-cues` · `docs/pilot3_replay_cue_simulation.md` |
| 4 | Low-volume REM-gated cueing (~2 h) with full safety logging | `run-pilot4-cueing` · `docs/pilot4_low_volume_cueing.md` |
| 5 | Full night (~8 h): TLR block + puzzle cueing + morning artifacts | `run-pilot5-full-night` · `docs/pilot5_full_night.md` |

## CLI overview

28 commands under one `muse-tmr` entry point. Full invocations with all flags: [`docs/USAGE.md`](docs/USAGE.md).

| Group | Commands |
| ----- | -------- |
| Acquisition | `discover` · `stream` · `record` · `replay` · `app` |
| Annotation & training | `annotate-template` · `train-rem-classifier` |
| Audio & cue libraries | `play-test-cue` · `calibrate-volume` · `create-cue-library` · `validate-cue-library` · `list-cues` |
| TLR cues | `create-tlr-cue` · `train-tlr-cue` · `plan-tlr-block` |
| Puzzle protocol | `import-puzzles` · `record-puzzle-attempt` · `generate-puzzle-session` · `assign-puzzle-cues` · `record-association-check` |
| Morning & analysis | `record-dream-report` · `record-puzzle-retest` · `analyze-cued-uncued` |
| Pilots & validation | `validate-pilot1-recording` · `validate-pilot2-calibration` · `simulate-replay-cues` · `run-pilot4-cueing` · `run-pilot5-full-night` |

## Quick start

```bash
git clone https://github.com/yuriy-mikityuk/athena-tmr-lucid.git
cd athena-tmr-lucid
pip install -e .

muse-tmr --help
muse-tmr discover --source amused
muse-tmr stream --source amused --duration-seconds 3600
muse-tmr record --source amused --duration-hours 8
muse-tmr replay data/recordings/<session> --speed 20
```

Recordings land in `data/recordings/<timestamp>/`; overnight sessions are constrained to 2–8 hours, and short smoke tests need `--allow-short`. Optional acquisition backends (`pip install -e ".[openmuse]"` / `".[brainflow]"`), the macOS CoreBluetooth workaround, and every protocol command are covered step by step in [`docs/USAGE.md`](docs/USAGE.md).

## Testing

```bash
python run_tests.py
```

Pytest suite under `tests/`, current coverage notes in [`TEST_STATUS.md`](TEST_STATUS.md), CI via GitHub Actions (`.github/workflows/`). Pilot 3 doubles as an end-to-end regression: the whole detection → gating → scheduling chain runs against a recorded night with mocked audio.

## Data source layer & attribution

The BLE protocol layer is based on **[amused-py](https://github.com/nexon33/amused)** by Adrian Tadeusz Belmans — the first open-source BLE implementation for the Muse S Athena. This repository uses a forked-source strategy pinned to upstream commit `bce20f98ddc7fa2efe3219d1b5d2f7554a55eb97`; the sync and contribution policy is recorded in [`docs/dependency_strategy.md`](docs/dependency_strategy.md). The original upstream documentation — including the reverse-engineered BLE protocol details, presets, and packet formats — is preserved in [`docs/amused_upstream.md`](docs/amused_upstream.md).

Optional backends: OpenMuse (LSL) and BrainFlow adapters map into the same `MuseFrame` contract; an official-SDK source exists only as a policy-enforcing stub, and `scripts/check_forbidden_files.py` guards against committing any vendor binaries.

## Safety & privacy

Audio output is capped by per-device calibration and a hard session maximum, always fades in and out, and can be cut by the arousal guard or an emergency stop — every playback attempt is logged as JSONL. Personal artifacts stay local by design: volume calibration files, puzzle catalogs and responses, and dream reports are gitignored. This software does not diagnose, treat, or monitor any medical condition.

## License

MIT — see [LICENSE](LICENSE). If you build on the BLE layer specifically, please also cite upstream amused-py (citation block preserved in [`docs/amused_upstream.md`](docs/amused_upstream.md)).
