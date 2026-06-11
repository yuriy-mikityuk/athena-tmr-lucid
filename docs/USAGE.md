# Usage reference

Complete command and code reference for `muse-tmr`, organized by workflow stage. The [README](../README.md) gives the high-level picture; this page contains every invocation with flags and the embeddable Python APIs.

## Contents

- [Installation & local development](#installation--local-development)
- [Acquisition: discover, stream, record](#acquisition-discover-stream-record)
- [Alternative acquisition backends](#alternative-acquisition-backends)
- [macOS BLE troubleshooting](#macos-ble-troubleshooting)
- [Offline replay](#offline-replay)
- [Epoch building](#epoch-building)
- [Feature extraction: EEG](#feature-extraction-eeg)
- [Feature extraction: IMU](#feature-extraction-imu)
- [Feature extraction: PPG / HR / HRV](#feature-extraction-ppg--hr--hrv)
- [Heuristic REM baseline](#heuristic-rem-baseline)
- [Manual REM annotation templates](#manual-rem-annotation-templates)
- [Personal REM classifier](#personal-rem-classifier)
- [REM stable gate](#rem-stable-gate)
- [Low-volume test cue player](#low-volume-test-cue-player)
- [Pre-sleep volume calibration](#pre-sleep-volume-calibration)
- [Cue library metadata](#cue-library-metadata)
- [Pre-sleep puzzle session manager](#pre-sleep-puzzle-session-manager)
- [TLR cue module](#tlr-cue-module)
- [REM-gated scheduler](#rem-gated-scheduler)
- [Morning dream report](#morning-dream-report)
- [Morning puzzle retest](#morning-puzzle-retest)
- [Cued-vs-uncued analysis](#cued-vs-uncued-analysis)
- [Local Muse contact setup app](#local-muse-contact-setup-app)
- [Validation plan and pilots](#validation-plan-and-pilots)

## Installation & local development

```bash
pip install -e .
python -m muse_tmr.cli.main --help
muse-tmr --help
python scripts/check_forbidden_files.py
```

## Acquisition: discover, stream, record

```bash
muse-tmr discover --source amused
muse-tmr stream --source amused --duration-seconds 3600
muse-tmr record --source amused --duration-hours 8
```

Short smoke-test recordings require `--allow-short`; normal overnight recordings are constrained to 2-8 hours.
Recordings are written to `data/recordings/<timestamp>/` by default. Pass `--output-dir` to pin a specific session directory.

After discovery, prefer the discovered BLE address for live checks:

```bash
MUSE_ADDR="<discovered-address>"
muse-tmr stream --source amused --address "$MUSE_ADDR" --duration-seconds 60
muse-tmr record --source amused --address "$MUSE_ADDR" --duration-seconds 60 --allow-short
```

## Alternative acquisition backends

### OpenMuse LSL source

```bash
pip install -e ".[openmuse]"
muse-tmr discover --source openmuse --require-lsl-stream eeg
muse-tmr stream --source openmuse --duration-seconds 60 --require-lsl-stream eeg
```

OpenMuse must run separately and publish LSL streams such as `Muse_EEG` and `Muse_ACCGYRO`. The adapter reads available LSL modalities into the same `MuseFrame` contract as the BLE source; `mne_lsl` or `pylsl` plus local `liblsl` remains optional.

### BrainFlow source

```bash
pip install -e ".[brainflow]"
muse-tmr discover --source brainflow
muse-tmr stream --source brainflow --address "$MUSE_ADDR" --duration-seconds 60 --debug-stats
```

BrainFlow remains an optional acquisition backend, not the project foundation. The adapter targets `MUSE_S_ATHENA_BOARD`, uses `p1041` with low latency by default, and maps BrainFlow EEG, IMU, optics, and battery rows into the existing `MuseFrame` contract. Keep `amused` as the default until live smoke tests show BrainFlow is more reliable for Muse S Athena.

If BrainFlow connect/reconnect is flaky, keep the process bounded and leave BLE time to settle between attempts:

```bash
muse-tmr stream --source brainflow --address "$MUSE_ADDR" \
  --duration-seconds 10 \
  --brainflow-connect-timeout 20 \
  --brainflow-stream-start-timeout 10 \
  --brainflow-stop-timeout 10 \
  --brainflow-session-cooldown 5 \
  --debug-stats
```

### Official SDK policy

```bash
muse-tmr stream --source sdk --sdk-path /local/path/to/sdk
```

The SDK source is currently a policy-enforcing stub only. It imports without any SDK installed, but runtime operations fail until a local-only adapter is explicitly built. Do not commit official SDK binaries, headers, frameworks, archives, installers, docs, or copied vendor code. Run `python scripts/check_forbidden_files.py` before publishing SDK-adjacent changes.

## macOS BLE troubleshooting

If direct `python3 -m muse_tmr.cli.main discover --source amused` or `muse-tmr discover --source amused` aborts before printing Python logs, macOS TCC is likely blocking CoreBluetooth for the Python bundle. Use a virtual environment and launch the framework `Python.app` through LaunchServices:

```bash
cd /path/to/athena-tmr-lucid
/opt/homebrew/bin/python3 -m venv .venv
.venv/bin/python -m pip install -e .

PYAPP=/opt/homebrew/Cellar/python@3.12/3.12.3/Frameworks/Python.framework/Versions/3.12/Resources/Python.app
PYTHONPATH="$PWD:$PWD/src:$PWD/.venv/lib/python3.12/site-packages"

open -W -n \
  --stdout /tmp/muse-discover.out \
  --stderr /tmp/muse-discover.err \
  --env "PYTHONPATH=$PYTHONPATH" \
  "$PYAPP" \
  --args -m muse_tmr.cli.main discover --source amused

cat /tmp/muse-discover.out
cat /tmp/muse-discover.err
```

If using the `Python.app` workaround, keep the same `open ... "$PYAPP" --args` wrapper and replace only the command after `--args` with the `stream` or `record` invocation.

## Offline replay

```bash
muse-tmr replay data/recordings/<session>
muse-tmr replay data/recordings/<session> --speed 1.0
muse-tmr replay data/recordings/<session> --speed 20 --start-seconds 1800 --end-seconds 3600
```

Replay accepts either a recording directory or a `raw_amused.bin` path. `--speed 1.0` is real time; `--speed 0.0` replays as fast as possible for tests and batch feature extraction.

## Epoch building

```python
from pathlib import Path
from muse_tmr.data.replay import ReplayConfig, ReplaySession
from muse_tmr.features.epochs import EpochBuilder, EpochConfig

session = ReplaySession(ReplayConfig(Path("data/recordings/<session>"), speed=0.0))
builder = EpochBuilder(EpochConfig(epoch_seconds=30, stride_seconds=30))

async for epoch in builder.build(session.stream()):
    print(epoch.index, epoch.coverage, epoch.quality_flags)
```

The same builder accepts live `MuseFrame` streams from `AmusedSource`; missing modalities are represented as coverage/quality flags instead of errors.

## Feature extraction: EEG

```python
from pathlib import Path
from muse_tmr.features.eeg_features import (
    export_eeg_feature_rows,
    extract_eeg_feature_rows,
)

rows = extract_eeg_feature_rows(epochs)
export_eeg_feature_rows(rows, Path("data/reports/eeg_features.csv"))
```

EEG rows include band powers for delta/theta/alpha/beta/gamma, relative powers, theta-alpha and slow-fast ratios, frontal/posterior asymmetry, a frontal eye-movement proxy, and artifact flags. CSV export is always available; Parquet export uses the installed pandas Parquet engine when available.

## Feature extraction: IMU

```python
from pathlib import Path
from muse_tmr.features.imu_features import (
    export_imu_feature_rows,
    extract_imu_feature_rows,
)

rows = extract_imu_feature_rows(
    epochs,
    cue_timestamps_by_epoch={0: [session_start + 1800.0]},
)
export_imu_feature_rows(rows, Path("data/reports/imu_features.csv"))
```

IMU rows include motion level, stillness score, accelerometer and gyroscope peaks, movement events, arousal proxy counts, arousal guard reason codes, and cue-window movement logs. CSV export is always available; Parquet export uses the installed pandas Parquet engine when available.

## Feature extraction: PPG / HR / HRV

```python
from pathlib import Path
from muse_tmr.features.ppg_features import (
    export_ppg_feature_rows,
    extract_ppg_feature_rows,
)

rows = extract_ppg_feature_rows(epochs)
export_ppg_feature_rows(rows, Path("data/reports/ppg_features.csv"))
```

PPG rows include PPG-derived heart-rate estimates when raw optics are available, mean/min/max HR from `HeartRateSample`, HR trend, HRV proxy metrics, sudden HR-change logs, and missing-modality flags. CSV export is always available; Parquet export uses the installed pandas Parquet engine when available.

## Heuristic REM baseline

```python
from muse_tmr.models import HeuristicRemDetector

detector = HeuristicRemDetector()

for epoch in epochs:
    prediction = detector.predict_epoch(epoch)
    print(epoch.index, prediction.probability, prediction.reason_codes)
```

`prediction.probability` is `P_REM` in the 0-1 range. The heuristic detector is a non-ML baseline over EEG, IMU, and PPG/HR feature rows. It returns reason codes and feature scores only; it does not play audio or make cue decisions.

## Manual REM annotation templates

```bash
muse-tmr annotate-template data/recordings/<session> \
  --output data/annotations/<session>_rem_labels.csv
```

The template overlays each epoch with `P_REM`, reason codes, and feature columns. The default label is `unknown`; manually edit labels to `wake`, `nrem`, or `probable_rem` before using them for training.

## Personal REM classifier

```bash
muse-tmr train-rem-classifier data/annotations/<session>_rem_labels.csv \
  --output data/models/personal_rem_model.json
```

The trainer skips `unknown` labels, treats `probable_rem` as the positive class, and treats `wake`/`nrem` as the negative class. The saved JSON artifact is versioned and includes class-balanced logistic coefficients, calibration metrics, feature importance, and training metrics. Personal model probabilities still do not trigger audio directly; stable gates and safety layers decide whether a cue is allowed.

## REM stable gate

```python
from muse_tmr.models import RemGateConfig, StableRemGate

gate = StableRemGate(RemGateConfig(min_stable_seconds=60.0))

for prediction in rem_predictions:
    decision = gate.update(prediction)
    print(decision.gate_open, decision.state, decision.reason_codes)
```

The gate requires stable REM confidence over time, uses hysteresis for closing, blocks motion/arousal reasons, and applies cooldown after arousal blocks. It still does not play audio; cue code must consume `gate_open` plus reason codes.

## Low-volume test cue player

```bash
muse-tmr play-test-cue --volume 0.05 --max-volume 0.20
```

`play-test-cue` uses conservative low-volume defaults, applies fade in/out, caps any requested volume at `--max-volume`, supports backend/device metadata, and can write JSONL playback logs with `--log-path`. On macOS the `system` backend uses `afplay` when available; otherwise it falls back to `dry-run`. Use `--backend dry-run` for non-audible smoke tests and CI.

## Pre-sleep volume calibration

```bash
muse-tmr calibrate-volume \
  --device-name "Bedroom Headphones" \
  --detectable-volume 0.02 \
  --identifiable-volume 0.04 \
  --comfortable-volume 0.08 \
  --output data/calibration/volume.json

muse-tmr play-test-cue \
  --backend dry-run \
  --device-name "Bedroom Headphones" \
  --calibration data/calibration/volume.json \
  --volume 0.20
```

Volume calibration stores the detectable, identifiable, and comfortable volumes for one playback device. Scheduler code must use `comfortable_volume` as the calibrated maximum, still capped by the hard session max. Calibration files under `data/calibration/` are gitignored because they can reveal personal devices and sleep setup.

## Cue library metadata

```bash
muse-tmr create-cue-library --output data/cues/starter.json
muse-tmr validate-cue-library data/cues/starter.json
muse-tmr list-cues data/cues/starter.json --protocol puzzle
```

Cue libraries are JSON metadata catalogs for `sound`, `generated_tone`, and `silence` cues. They carry duration, protocol role (`puzzle`, `tlr`, `test`, or `generic`), tags, optional volume hints, and private sound file paths. Sound cue files under `cues/private/` or `data/cues/audio/` are gitignored by default; validation detects missing files before a sleep session.

## Pre-sleep puzzle session manager

```bash
muse-tmr import-puzzles puzzles.csv --output data/protocol/puzzle_catalog.json

muse-tmr record-puzzle-attempt data/protocol/puzzle_catalog.json \
  --puzzle-id p001 \
  --response "my answer" \
  --duration-seconds 90

muse-tmr generate-puzzle-session data/protocol/puzzle_catalog.json \
  --session-id night-001 \
  --count 4 \
  --seed 17 \
  --output data/protocol/night-001_puzzles.json

muse-tmr assign-puzzle-cues data/protocol/night-001_puzzles.json \
  --seed 23 \
  --output data/protocol/night-001_assignment.json

muse-tmr record-association-check data/protocol/night-001_puzzles.json \
  --catalog data/protocol/puzzle_catalog.json \
  --puzzle-id p001 \
  --response "remembered answer"
```

Puzzle catalogs track prompts, solutions, cue IDs, solved/known/retired flags, timed pre-sleep attempts, and cue-to-solution association checks. Session generation filters out solved, known, and retired tasks and produces a reproducible night session with four eligible unsolved puzzles by default. `data/protocol/` is gitignored because it can contain private puzzle content and responses.

`assign-puzzle-cues` randomizes half of the night-session puzzles into cued and uncued groups with a seed. Scheduler code must consume `scheduled_puzzle_ids` from the saved assignment, which contains only cued puzzles, so uncued tasks are never scheduled.

## TLR cue module

```bash
muse-tmr create-tlr-cue --output data/cues/tlr_default.json

muse-tmr train-tlr-cue data/cues/tlr_default.json \
  --output data/protocol/tlr_training.json \
  --event-log data/protocol/tlr_training.jsonl \
  --backend dry-run \
  --repetitions 3

muse-tmr plan-tlr-block data/cues/tlr_default.json \
  --output data/protocol/tlr_block.json \
  --repetitions 3 \
  --interval-seconds 8 \
  --post-block-pause-seconds 10
```

`create-tlr-cue` writes a default generated TLR cue library. `train-tlr-cue` runs pre-sleep TLR cue familiarization through the audio player facade and writes structured JSONL training events. `plan-tlr-block` produces the configurable TLR cue block that the REM-gated scheduler runs before puzzle cues.

## REM-gated scheduler

```python
from muse_tmr.protocol import ArousalGuard, TmrCueScheduler, TmrSchedulerConfig

guard = ArousalGuard()

scheduler = TmrCueScheduler(
    assignment=puzzle_cue_assignment,
    catalog=puzzle_catalog,
    cue_library=cue_library,
    tlr_block_plan=tlr_block_plan,
    config=TmrSchedulerConfig(max_puzzle_cues_per_block=4),
)

for timestamp_seconds, gate_decision, feature_rows in replayed_gate_decisions:
    guard_decision = guard.evaluate(
        timestamp_seconds=timestamp_seconds,
        eeg=feature_rows.eeg,
        imu=feature_rows.imu,
        ppg=feature_rows.ppg,
    )
    events = scheduler.update(
        gate_decision,
        timestamp_seconds=timestamp_seconds,
        guard_decision=guard_decision,
    )
```

The scheduler consumes stable REM gate decisions, optionally emits a TLR block first, then schedules only cued puzzle cues from `scheduled_puzzle_ids`. It enforces cue interval, cooldown, and max-per-block limits, and logs structured `play`, `skip`, `pause`, and `stop` events. `ArousalGuard` consumes EEG/IMU/PPG feature rows and can allow cueing, lower volume, pause cueing, or stop a session from motion, alpha, HR-jump, and artifact-quality proxies. Neither layer calls audio playback directly.

## Morning dream report

```bash
muse-tmr record-dream-report data/protocol/night-001_puzzles.json \
  --catalog data/protocol/puzzle_catalog.json \
  --output data/reports/night-001_dream_report.json \
  --lucid yes \
  --cues-heard no \
  --confidence 0.7 \
  --dream-text "I found the answer written in a notebook." \
  --puzzle-link "p1=the first puzzle answer appeared in the notebook"
```

Dream reports save local JSON with lucid yes/no, cues-heard yes/no, confidence, free-text recall, and optional per-puzzle links. Each `--puzzle-link` is validated against the generated night puzzle session so reports can connect dream content back to the experimental puzzle IDs without making uncued assumptions.

## Morning puzzle retest

```bash
muse-tmr record-puzzle-retest data/protocol/night-001_puzzles.json \
  --catalog data/protocol/puzzle_catalog.json \
  --assignment data/protocol/night-001_assignment.json \
  --output data/reports/night-001_retest.json \
  --result "p1=Answer from morning" \
  --result "p2=" \
  --solved p1 \
  --duration "p1=42" \
  --duration "p2=30" \
  --confidence "p1=0.8" \
  --confidence "p2=0.2"
```

Retests save one result per generated session puzzle with response, solved/unsolved, duration, confidence, cue ID, blind order, and `cue_condition` (`cued` or `uncued`) from the assignment for later analysis. During administration, do not reveal the cued/uncued condition to the subject.

## Cued-vs-uncued analysis

```bash
muse-tmr analyze-cued-uncued data/protocol/night-001_puzzles.json \
  --assignment data/protocol/night-001_assignment.json \
  --retest data/reports/night-001_retest.json \
  --dream-report data/reports/night-001_dream_report.json \
  --scheduler-events data/reports/night-001_scheduler.jsonl \
  --output data/reports/night-001_analysis.json \
  --markdown-output data/reports/night-001_analysis.md
```

The analysis report compares cued and uncued solve rates, dream incorporation rates, mean retest duration/confidence, and scheduler cue timing. It is intentionally descriptive and records limitations such as small sample size or missing cue logs.

## Local Muse contact setup app

```bash
muse-tmr app --source mock --host 127.0.0.1 --port 8765
muse-tmr app --source amused --address "$MUSE_ADDR" --host 127.0.0.1 --port 8765
muse-tmr stream --source amused --address "$MUSE_ADDR" --duration-seconds 30 --debug-stats
.venv/bin/python scripts/install_macos_launcher.py --address "$MUSE_ADDR"
```

See `docs/contact_setup_local_app.md` before overnight pilot sessions. The setup app is local-only, tracks `TP9`, `AF7`, `AF8`, and `TP10`, and uses a backend-enforced `Start when ready` contact gate before session start. Live app diagnostics are available at `/api/muse/diagnostics`. On macOS, the launcher installer creates `~/Desktop/Muse TMR Setup.app` for one-click local startup.

## Validation plan and pilots

The validation plan lives in `docs/validation.md`. Validation separates protocol fidelity and technical quality from exploratory behavioral deltas. Metrics are computed from generated session artifacts such as `summary.json`, feature rows, scheduler JSONL, dream reports, morning retests, and cued-vs-uncued analysis outputs. Reports should describe observed differences and limitations; do not claim clinical, medical, or guaranteed lucid-dreaming efficacy.

### Pilot 1: no-audio recording validation

```bash
muse-tmr validate-pilot1-recording data/recordings/<pilot1-session> \
  --output data/reports/pilot1_no_audio_validation.json
```

See `docs/pilot1_no_audio.md` for the 6h+ no-audio recording runbook. The validator checks that `summary.json` exists, duration meets the target, EEG/IMU/PPG counts are nonzero, raw packet capture is present, downtime is within target, and no audio or scheduler sidecar logs were produced.

### Pilot 2: audio calibration validation

```bash
muse-tmr validate-pilot2-calibration data/calibration/volume_calibration.json \
  --device-name "Sleep Headphones" \
  --playback-log data/calibration/volume_calibration_test.jsonl \
  --output data/reports/pilot2_audio_calibration_validation.json
```

See `docs/pilot2_audio_calibration.md` for the daytime calibration runbook. The validator checks that saved thresholds are ordered, scheduler max volume equals the comfortable volume, and a dry-run cap probe proves later playback code uses the calibration cap. Generated calibration files and playback logs stay local.

### Pilot 3: replay cue simulation

```bash
muse-tmr simulate-replay-cues data/recordings/<pilot-session> \
  --catalog data/protocol/puzzle_catalog.json \
  --session data/protocol/night-001_puzzles.json \
  --assignment data/protocol/night-001_assignment.json \
  --cue-library data/cues/starter.json \
  --output data/reports/pilot3_replay_cue_plan.json \
  --scheduler-events-output data/reports/pilot3_scheduler_events.jsonl
```

See `docs/pilot3_replay_cue_simulation.md` for the replay-only runbook. The simulator runs epochs, REM detection, the stable gate, arousal guard, and scheduler on a recording with mocked audio. It writes an inspectable cue plan and fails if any uncued puzzle receives a scheduler `play` event. No real audio is played.

### Pilot 4: low-volume REM-gated cueing

```bash
muse-tmr run-pilot4-cueing \
  --source amused \
  --address "$MUSE_ADDR" \
  --duration-hours 2 \
  --output-dir data/recordings/pilot4_low_volume_<timestamp> \
  --catalog data/protocol/puzzle_catalog.json \
  --session data/protocol/night-001_puzzles.json \
  --assignment data/protocol/night-001_assignment.json \
  --cue-library data/cues/starter.json \
  --calibration data/calibration/volume_calibration.json \
  --device-name "Sleep Headphones" \
  --backend system \
  --default-volume 0.02
```

See `docs/pilot4_low_volume_cueing.md` before using `--backend system`. Pilot 4 requires volume calibration, enforces the comfortable-volume cap, logs scheduler, arousal, audio, awakening, and emergency-stop artifacts, and only sends playback requests for scheduler `play` events after stable REM.

### Pilot 5: full-night TLR plus puzzle cueing

```bash
muse-tmr run-pilot5-full-night \
  --source amused \
  --address "$MUSE_ADDR" \
  --duration-hours 8 \
  --output-dir data/recordings/pilot5_full_night_<timestamp> \
  --catalog data/protocol/puzzle_catalog.json \
  --session data/protocol/night-001_puzzles.json \
  --assignment data/protocol/night-001_assignment.json \
  --cue-library data/cues/starter.json \
  --tlr-block data/protocol/night-001_tlr_block.json \
  --calibration data/calibration/volume_calibration.json \
  --device-name "Sleep Headphones" \
  --backend system \
  --default-volume 0.02
```

See `docs/pilot5_full_night.md` for the full runbook. Pilot 5 requires the Pilot 4 safety setup plus a TLR block plan, writes `pilot5_summary.json`, and expects the morning dream report, blind puzzle retest, and cued-vs-uncued analysis before any behavioral interpretation.
