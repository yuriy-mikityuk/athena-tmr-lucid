# Amused - A Muse S Direct BLE Implementation

**The first open-source BLE protocol implementation for Muse S athena headsets**

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Muse REM-TMR Project Layer

This repository is being extended into a Muse S Athena REM-TMR/TLR research tool for overnight recording, offline replay, REM-gated cue scheduling, puzzle cue assignment, morning dream reports, retests, and cued-vs-uncued analysis.

The project is not a medical device and must not be described as clinical, diagnostic, therapeutic, or guaranteed to induce lucid dreams. The near-term target is protocol fidelity, safety guardrails, structured logging, and measurable validation.

High-level architecture:

```text
Muse S Athena
  -> amused-py BLE source
  -> unified Muse frame stream
  -> recorder and offline replay
  -> EEG/IMU/PPG/HR feature extraction
  -> REM detector and stable REM gate
  -> safety checks and audio cue scheduler
  -> TLR/puzzle cue protocol
  -> morning report, retest, and analysis
```

The new REM-TMR code lives under `src/muse_tmr/`. The existing top-level `muse_*.py` modules remain the forked BLE/data-source layer.

Dependency decision: this repository currently uses a forked-source strategy for `Amused-EEG/amused-py`, pinned to upstream commit `bce20f98ddc7fa2efe3219d1b5d2f7554a55eb97`. The sync and contribution policy is recorded in `docs/dependency_strategy.md` and `pyproject.toml`.

Local development:

```bash
pip install -e .
python -m muse_tmr.cli.main --help
muse-tmr --help
python scripts/check_forbidden_files.py
```

M1 data-source commands:

```bash
muse-tmr discover --source amused
muse-tmr stream --source amused --duration-seconds 3600
muse-tmr record --source amused --duration-hours 8
```

Short smoke-test recordings require `--allow-short`; normal overnight recordings are constrained to 2-8 hours.
Recordings are written to `data/recordings/<timestamp>/` by default. Pass `--output-dir`
to pin a specific session directory.

M7 optional OpenMuse LSL source:

```bash
pip install -e ".[openmuse]"
muse-tmr discover --source openmuse --require-lsl-stream eeg
muse-tmr stream --source openmuse --duration-seconds 60 --require-lsl-stream eeg
```

OpenMuse must run separately and publish LSL streams such as `Muse_EEG` and
`Muse_ACCGYRO`. The adapter reads available LSL modalities into the same `MuseFrame`
contract as the BLE source; `mne_lsl` or `pylsl` plus local `liblsl` remains optional.

M7 official SDK policy:

```bash
muse-tmr stream --source sdk --sdk-path /local/path/to/sdk
```

The SDK source is currently a policy-enforcing stub only. It imports without any SDK
installed, but runtime operations fail until a local-only adapter is explicitly built.
Do not commit official SDK binaries, headers, frameworks, archives, installers, docs,
or copied vendor code. Run `python scripts/check_forbidden_files.py` before publishing
SDK-adjacent changes.

macOS BLE smoke-test note: if direct `python3 -m muse_tmr.cli.main discover --source amused`
or `muse-tmr discover --source amused` aborts before printing Python logs, macOS TCC is
likely blocking CoreBluetooth for the Python bundle. Use a virtual environment and launch
the framework `Python.app` through LaunchServices:

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

After discovery, prefer the discovered BLE address for live checks:

```bash
MUSE_ADDR="<discovered-address>"
muse-tmr stream --source amused --address "$MUSE_ADDR" --duration-seconds 60
muse-tmr record --source amused --address "$MUSE_ADDR" --duration-seconds 60 --allow-short
```

If using the `Python.app` workaround, keep the same `open ... "$PYAPP" --args` wrapper
and replace only the command after `--args` with the `stream` or `record` invocation.

M2 offline replay commands:

```bash
muse-tmr replay data/recordings/<session>
muse-tmr replay data/recordings/<session> --speed 1.0
muse-tmr replay data/recordings/<session> --speed 20 --start-seconds 1800 --end-seconds 3600
```

Replay accepts either a recording directory or a `raw_amused.bin` path. `--speed 1.0`
is real time; `--speed 0.0` replays as fast as possible for tests and batch feature
extraction.

M2 epoch building:

```python
from pathlib import Path
from muse_tmr.data.replay import ReplayConfig, ReplaySession
from muse_tmr.features.epochs import EpochBuilder, EpochConfig

session = ReplaySession(ReplayConfig(Path("data/recordings/<session>"), speed=0.0))
builder = EpochBuilder(EpochConfig(epoch_seconds=30, stride_seconds=30))

async for epoch in builder.build(session.stream()):
    print(epoch.index, epoch.coverage, epoch.quality_flags)
```

The same builder accepts live `MuseFrame` streams from `AmusedSource`; missing modalities
are represented as coverage/quality flags instead of errors.

M2 EEG feature extraction:

```python
from pathlib import Path
from muse_tmr.features.eeg_features import (
    export_eeg_feature_rows,
    extract_eeg_feature_rows,
)

rows = extract_eeg_feature_rows(epochs)
export_eeg_feature_rows(rows, Path("data/reports/eeg_features.csv"))
```

EEG rows include band powers for delta/theta/alpha/beta/gamma, relative powers,
theta-alpha and slow-fast ratios, frontal/posterior asymmetry, a frontal
eye-movement proxy, and artifact flags. CSV export is always available; Parquet export
uses the installed pandas Parquet engine when available.

M2 IMU motion/arousal feature extraction:

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

IMU rows include motion level, stillness score, accelerometer and gyroscope peaks,
movement events, arousal proxy counts, arousal guard reason codes, and cue-window
movement logs. CSV export is always available; Parquet export uses the installed pandas
Parquet engine when available.

M2 PPG/HR/HRV feature extraction:

```python
from pathlib import Path
from muse_tmr.features.ppg_features import (
    export_ppg_feature_rows,
    extract_ppg_feature_rows,
)

rows = extract_ppg_feature_rows(epochs)
export_ppg_feature_rows(rows, Path("data/reports/ppg_features.csv"))
```

PPG rows include PPG-derived heart-rate estimates when raw optics are available,
mean/min/max HR from `HeartRateSample`, HR trend, HRV proxy metrics, sudden HR-change
logs, and missing-modality flags. CSV export is always available; Parquet export uses
the installed pandas Parquet engine when available.

M3 heuristic REM baseline:

```python
from muse_tmr.models import HeuristicRemDetector

detector = HeuristicRemDetector()

for epoch in epochs:
    prediction = detector.predict_epoch(epoch)
    print(epoch.index, prediction.probability, prediction.reason_codes)
```

`prediction.probability` is `P_REM` in the 0-1 range. The heuristic detector is a
non-ML baseline over EEG, IMU, and PPG/HR feature rows. It returns reason codes and
feature scores only; it does not play audio or make cue decisions.

M3 manual REM annotation templates:

```bash
muse-tmr annotate-template data/recordings/<session> \
  --output data/annotations/<session>_rem_labels.csv
```

The template overlays each epoch with `P_REM`, reason codes, and feature columns. The
default label is `unknown`; manually edit labels to `wake`, `nrem`, or `probable_rem`
before using them for training.

M3 personal REM classifier:

```bash
muse-tmr train-rem-classifier data/annotations/<session>_rem_labels.csv \
  --output data/models/personal_rem_model.json
```

The trainer skips `unknown` labels, treats `probable_rem` as the positive class, and
treats `wake`/`nrem` as the negative class. The saved JSON artifact is versioned and
includes class-balanced logistic coefficients, calibration metrics, feature importance,
and training metrics. Personal model probabilities still do not trigger audio directly;
stable gates and safety layers decide whether a cue is allowed.

M3 REM stable gate:

```python
from muse_tmr.models import RemGateConfig, StableRemGate

gate = StableRemGate(RemGateConfig(min_stable_seconds=60.0))

for prediction in rem_predictions:
    decision = gate.update(prediction)
    print(decision.gate_open, decision.state, decision.reason_codes)
```

The gate requires stable REM confidence over time, uses hysteresis for closing, blocks
motion/arousal reasons, and applies cooldown after arousal blocks. It still does not
play audio; M4/M5 cue code must consume `gate_open` plus reason codes.

M4 low-volume test cue player:

```bash
muse-tmr play-test-cue --volume 0.05 --max-volume 0.20
```

`play-test-cue` uses conservative low-volume defaults, applies fade in/out, caps any
requested volume at `--max-volume`, supports backend/device metadata, and can write
JSONL playback logs with `--log-path`. On macOS the `system` backend uses `afplay`
when available; otherwise it falls back to `dry-run`. Use `--backend dry-run` for
non-audible smoke tests and CI.

M4 pre-sleep volume calibration:

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

Volume calibration stores the detectable, identifiable, and comfortable volumes for
one playback device. Scheduler code must use `comfortable_volume` as the calibrated
maximum, still capped by the hard session max. Calibration files under
`data/calibration/` are gitignored because they can reveal personal devices and
sleep setup.

M4 cue library metadata:

```bash
muse-tmr create-cue-library --output data/cues/starter.json
muse-tmr validate-cue-library data/cues/starter.json
muse-tmr list-cues data/cues/starter.json --protocol puzzle
```

Cue libraries are JSON metadata catalogs for `sound`, `generated_tone`, and `silence`
cues. They carry duration, protocol role (`puzzle`, `tlr`, `test`, or `generic`), tags,
optional volume hints, and private sound file paths. Sound cue files under
`cues/private/` or `data/cues/audio/` are gitignored by default; validation detects
missing files before a sleep session.

M5 pre-sleep puzzle session manager:

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

Puzzle catalogs track prompts, solutions, cue IDs, solved/known/retired flags, timed
pre-sleep attempts, and cue-to-solution association checks. Session generation filters
out solved, known, and retired tasks and produces a reproducible night session with
four eligible unsolved puzzles by default. `data/protocol/` is gitignored because it
can contain private puzzle content and responses.

`assign-puzzle-cues` randomizes half of the night-session puzzles into cued and uncued
groups with a seed. Scheduler code must consume `scheduled_puzzle_ids` from the saved
assignment, which contains only cued puzzles, so uncued tasks are never scheduled.

M5 TLR cue module:

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

`create-tlr-cue` writes a default generated TLR cue library. `train-tlr-cue` runs
pre-sleep TLR cue familiarization through the audio player facade and writes structured
JSONL training events. `plan-tlr-block` produces the configurable TLR cue block that
future REM-gated scheduler code should run before puzzle cues.

M5 REM-gated scheduler:

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

The scheduler consumes stable REM gate decisions, optionally emits a TLR block first,
then schedules only cued puzzle cues from `scheduled_puzzle_ids`. It enforces
cue interval, cooldown, and max-per-block limits, and logs structured `play`, `skip`,
`pause`, and `stop` events. `ArousalGuard` consumes EEG/IMU/PPG feature rows and can
allow cueing, lower volume, pause cueing, or stop a session from motion, alpha, HR-jump,
and artifact-quality proxies. Neither layer calls audio playback directly.

M6 morning dream report:

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

Dream reports save local JSON with lucid yes/no, cues-heard yes/no, confidence,
free-text recall, and optional per-puzzle links. Each `--puzzle-link` is validated
against the generated night puzzle session so reports can connect dream content back
to the experimental puzzle IDs without making uncued assumptions.

M6 morning puzzle retest:

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

Retests save one result per generated session puzzle with response, solved/unsolved,
duration, confidence, cue ID, blind order, and `cue_condition` (`cued` or `uncued`)
from the assignment for later analysis. During administration, do not reveal the
cued/uncued condition to the subject.

M6 cued-vs-uncued analysis:

```bash
muse-tmr analyze-cued-uncued data/protocol/night-001_puzzles.json \
  --assignment data/protocol/night-001_assignment.json \
  --retest data/reports/night-001_retest.json \
  --dream-report data/reports/night-001_dream_report.json \
  --scheduler-events data/reports/night-001_scheduler.jsonl \
  --output data/reports/night-001_analysis.json \
  --markdown-output data/reports/night-001_analysis.md
```

The analysis report compares cued and uncued solve rates, dream incorporation rates,
mean retest duration/confidence, and scheduler cue timing. It is intentionally
descriptive and records limitations such as small sample size or missing cue logs.

M8 validation plan:

```text
docs/validation.md
```

Validation separates protocol fidelity and technical quality from exploratory
behavioral deltas. Metrics are computed from generated session artifacts such as
`summary.json`, feature rows, scheduler JSONL, dream reports, morning retests, and
cued-vs-uncued analysis outputs. Reports should describe observed differences and
limitations; do not claim clinical, medical, or guaranteed lucid-dreaming efficacy.

M8 Pilot 1 no-audio recording validation:

```bash
muse-tmr validate-pilot1-recording data/recordings/<pilot1-session> \
  --output data/reports/pilot1_no_audio_validation.json
```

See `docs/pilot1_no_audio.md` for the 6h+ no-audio recording runbook. The validator
checks that `summary.json` exists, duration meets the target, EEG/IMU/PPG counts are
nonzero, raw packet capture is present, downtime is within target, and no audio or
scheduler sidecar logs were produced.

M8 Pilot 2 audio calibration validation:

```bash
muse-tmr validate-pilot2-calibration data/calibration/volume_calibration.json \
  --device-name "Sleep Headphones" \
  --playback-log data/calibration/volume_calibration_test.jsonl \
  --output data/reports/pilot2_audio_calibration_validation.json
```

See `docs/pilot2_audio_calibration.md` for the daytime calibration runbook. The
validator checks that saved thresholds are ordered, scheduler max volume equals the
comfortable volume, and a dry-run cap probe proves later playback code uses the
calibration cap. Generated calibration files and playback logs stay local.

M8 Pilot 3 replay cue simulation:

```bash
muse-tmr simulate-replay-cues data/recordings/<pilot-session> \
  --catalog data/protocol/puzzle_catalog.json \
  --session data/protocol/night-001_puzzles.json \
  --assignment data/protocol/night-001_assignment.json \
  --cue-library data/cues/starter.json \
  --output data/reports/pilot3_replay_cue_plan.json \
  --scheduler-events-output data/reports/pilot3_scheduler_events.jsonl
```

See `docs/pilot3_replay_cue_simulation.md` for the replay-only runbook. The simulator
runs epochs, REM detection, the stable gate, arousal guard, and scheduler on a
recording with mocked audio. It writes an inspectable cue plan and fails if any uncued
puzzle receives a scheduler `play` event. No real audio is played.

M8 Pilot 4 low-volume REM-gated cueing:

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

See `docs/pilot4_low_volume_cueing.md` before using `--backend system`. Pilot 4
requires volume calibration, enforces the comfortable-volume cap, logs scheduler,
arousal, audio, awakening, and emergency-stop artifacts, and only sends playback
requests for scheduler `play` events after stable REM.

> **Finally!** Direct BLE connection to Muse S without proprietary SDKs. We're quite *amused* that we cracked the protocol nobody else has published online!

## 🎉 The Real Story

We reverse-engineered the BLE communication from scratch to provide researchers with full control over their Muse S devices. 

**Key breakthrough:** The Athena requires a specific init sequence -- `dc001` must be sent TWICE (first with preset `p21`, then after switching to `p1034`/`p1035`). This critical detail is not in any documentation!

## Features

- **EEG Streaming**: 4 channels at 256 Hz (TP9, AF7, AF8, TP10) with 14-bit resolution
- **PPG/fNIRS Optics**: 8 channels at 64 Hz (850nm + 735nm, inner + outer sensors)
- **Heart Rate**: Real-time HR and HRV from PPG optics
- **IMU Motion**: 6-axis accelerometer + gyroscope at 52 Hz
- **Binary Recording**: 10x more efficient than CSV with replay capability
- **Real-time Visualization**: Band powers, heart rate monitor, frequency display
- **No SDK Required**: Pure Python with BLE - no proprietary libraries!

## Installation

```bash
pip install amused
```

Or from source:
```bash
git clone https://github.com/nexon33/amused.git
cd amused
pip install -e .
```

### Visualization Dependencies (Optional)

```bash
# For PyQtGraph visualizations
pip install pyqtgraph PyQt5

# For all visualization features
pip install -r requirements-viz.txt
```

## Quick Start

```python
import asyncio
from muse_stream_client import MuseStreamClient
from muse_discovery import find_muse_devices

async def stream():
    # Find Muse devices
    devices = await find_muse_devices()
    if not devices:
        print("No Muse device found!")
        return
    
    device = devices[0]
    print(f"Found: {device.name}")
    
    # Create streaming client
    client = MuseStreamClient(
        save_raw=True,      # Save to binary file
        decode_realtime=True # Decode in real-time
    )
    
    # Stream for 30 seconds
    await client.connect_and_stream(
        device.address,
        duration_seconds=30,
        preset='p1035'  # Full sensor mode
    )
    
    summary = client.get_summary()
    print(f"Collected {summary['packets_received']} packets")

asyncio.run(stream())
```

## Core Components

### `MuseStreamClient`
The main streaming client for real-time data collection:
- Connects to Muse S via BLE
- Streams all sensor data (EEG, PPG, IMU)
- Optional binary recording
- Real-time callbacks for data processing

### `MuseRawStream`
Binary data storage and retrieval:
- Efficient binary format (10x smaller than CSV)
- Fast read/write operations
- Packet-level access with timestamps

### `MuseRealtimeDecoder`
Real-time packet decoding:
- Decodes BLE packets on-the-fly
- Extracts EEG, PPG, IMU data
- Calculates heart rate from PPG
- Minimal latency

### `MuseReplayPlayer`
Replay recorded sessions:
- Play back binary recordings
- Variable speed playback
- Same callback interface as live streaming

## Usage Examples

### 1. Basic Streaming
```python
# See examples/01_basic_streaming.py
from muse_stream_client import MuseStreamClient
from muse_discovery import find_muse_devices

client = MuseStreamClient(
    save_raw=False,  # Don't save, just stream
    decode_realtime=True,
    verbose=True
)

devices = await find_muse_devices()
if devices:
    await client.connect_and_stream(
        devices[0].address,
        duration_seconds=30,
        preset='p1035'
    )
```

### 2. Recording to Binary
```python
# See examples/02_full_sensors.py
client = MuseStreamClient(
    save_raw=True,  # Enable binary saving
    data_dir="muse_data"
)

# Records all sensors to binary file
await client.connect_and_stream(
    device.address,
    duration_seconds=60,
    preset='p1035'
)
```

### 3. Parsing Recorded Data
```python
# See examples/03_parse_data.py
from muse_raw_stream import MuseRawStream
from muse_realtime_decoder import MuseRealtimeDecoder

stream = MuseRawStream("muse_data/recording.bin")
stream.open_read()

decoder = MuseRealtimeDecoder()
for packet in stream.read_packets():
    decoded = decoder.decode(packet.data, packet.timestamp)
    if decoded.eeg:
        print(f"EEG data: {decoded.eeg}")
    if decoded.heart_rate:
        print(f"Heart rate: {decoded.heart_rate:.0f} BPM")
```

### 4. Real-time Callbacks
```python
# See examples/04_stream_with_callbacks.py
def process_eeg(data):
    channels = data['channels']
    # Process EEG data in real-time
    print(f"Got EEG from {len(channels)} channels")

def process_heart_rate(hr):
    print(f"Heart Rate: {hr:.0f} BPM")

client = MuseStreamClient()
client.on_eeg(process_eeg)
client.on_heart_rate(process_heart_rate)

await client.connect_and_stream(device.address)
```

### 5. Visualization Examples

#### Band Power Visualization
```python
# See examples/07_lsl_style_viz.py
# Shows Delta, Theta, Alpha, Beta, Gamma bands
# Stable bar graphs without jumpy waveforms
```

#### Simple Frequency Display
```python
# See examples/09_frequency_display.py
# Just shows dominant frequency (Hz) for each channel
# Clean, large numbers - no graphs
```

#### Heart Rate Monitor
```python
# See examples/06_heart_monitor.py
# Dedicated heart rate display with zones
# Shows current BPM, trend, and history
```

## Protocol Details

The Muse S Athena (Gen 3, MS_03) uses Bluetooth Low Energy with a custom GATT profile. All sensor data is multiplexed through a single BLE characteristic (`273e0013`) using TAG-based subpackets.

### Connection Sequence (Athena init)
1. Connect to device
2. Enable control notifications on `273e0001`
3. Handshake: `v6` (version), `s` (status), `h` (halt)
4. Set initial preset `p21`
5. Enable sensor notifications on `273e0013`
6. Send `dc001` + `L1` (primes the device)
7. Halt, switch to target preset (`p1034` for full sensors)
8. Send `dc001` + `L1` again (starts actual streaming)

The `dc001` command must be sent **twice** -- once with preset `p21`, then again after switching to the target preset. This is the critical undocumented detail.

### Presets
- `p21`: Basic EEG only
- `p1034`: Full sensors (EEG 4ch + IMU + Optics 8ch) -- recommended
- `p1035`: Alternative full sensor preset

### Subpacket TAGs
All sensor data arrives as subpackets within each BLE notification:

| TAG  | Type    | Channels | Samples/pkt | Rate    | Data bytes |
|------|---------|----------|-------------|---------|------------|
| 0x11 | EEG     | 4        | 4           | 256 Hz  | 28         |
| 0x12 | EEG     | 8        | 2           | 256 Hz  | 28         |
| 0x47 | ACCGYRO | 6        | 3           | 52 Hz   | 36         |
| 0x34 | Optics  | 4        | 3           | 64 Hz   | 30         |
| 0x35 | Optics  | 8        | 2           | 64 Hz   | 40         |
| 0x36 | Optics  | 16       | 1           | 64 Hz   | 40         |

### Data Encoding
- **EEG**: 14-bit unsigned, LSB-first bit packing. Scale: 1450/16383 uV/bit
- **Optics/PPG**: 20-bit unsigned, LSB-first bit packing
- **IMU**: 16-bit signed, little-endian. Accel scale: 0.0000610352 g/bit, Gyro scale: -0.0074768 deg/s/bit

## Troubleshooting

### No data received?
- Ensure `dc001` is sent twice (critical!)
- Check Bluetooth is enabled
- Make sure Muse S is in pairing mode
- Try preset `p1035` for full sensor access

### Heart rate not showing?
- Heart rate requires ~2 seconds of PPG data
- Check PPG sensor contact with skin
- Use preset `p1035` which enables PPG

### Qt/Visualization errors?
- Install PyQt5: `pip install PyQt5 pyqtgraph`
- On Windows, the library handles Qt/asyncio conflicts automatically
- Try examples 06 or 09 for simpler visualizations

## Examples Directory

The `examples/` folder contains working examples:

1. `01_basic_streaming.py` - Simple EEG streaming
2. `02_full_sensors.py` - Record all sensors to binary
3. `03_parse_data.py` - Parse binary recordings
4. `04_stream_with_callbacks.py` - Real-time processing
5. `05_save_and_replay.py` - Record and replay sessions
6. `06_heart_monitor.py` - Clean heart rate display
7. `07_lsl_style_viz.py` - LSL-style band power visualization
8. `09_frequency_display.py` - Simple Hz display for each channel

## Contributing

This is the first open implementation! Areas to explore:
- Additional sensor modes
- Machine learning pipelines
- Mobile apps
- Advanced signal processing

## License

MIT License - see LICENSE file

## Citation

If you use Amused in research:
```
@software{amused2025,
  title = {Amused: A Muse S Direct BLE Implementation},
  author = {Adrian Tadeusz Belmans},
  year = {2025},
  url = {https://github.com/nexon33/amused}
}
```

---

**Note**: Research software for educational purposes. Probably not for medical use.
