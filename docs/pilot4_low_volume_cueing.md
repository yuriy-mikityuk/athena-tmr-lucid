# M8 Pilot 4: Low-Volume REM-Gated Cueing Night

Pilot 4 is the first sleep-time cueing workflow. It uses real audio only when the
operator explicitly selects a playback backend such as `system`, and it requires a
saved Pilot 2 volume calibration before any cue can be played.

## Goal

- Record a normal Muse session while running epochs, REM detection, stable REM gate,
  arousal guard, and TMR scheduler.
- Play only scheduler-approved puzzle cues after stable REM.
- Enforce the calibration comfortable-volume cap and the hard max-volume cap.
- Write auditable logs for scheduler events, arousal guard decisions, audio playback,
  emergency stop, and manual awakenings.
- Preserve raw recording outputs locally; do not commit generated data.

This is still an exploratory pilot. Do not use it to claim effectiveness or lucid
dream induction.

## Preflight

Required before using `--backend system`:

- Pilot 2 calibration exists and passed validation.
- Pilot 3 replay simulation passed on a recent recording.
- macOS output device is set to the intended sleep headphones.
- You know the emergency stop file path for the run.
- Cue metadata uses `generated_tone` puzzle cues with low `volume_hint` values.

Do a dry-run first:

```bash
cd /path/to/remind-eeg

.venv/bin/python -m muse_tmr.cli.main run-pilot4-cueing \
  --source amused \
  --address "$MUSE_ADDR" \
  --duration-seconds 300 \
  --allow-short \
  --output-dir data/recordings/pilot4_dry_run \
  --catalog data/protocol/puzzle_catalog.json \
  --session data/protocol/night-001_puzzles.json \
  --assignment data/protocol/night-001_assignment.json \
  --cue-library data/cues/starter.json \
  --calibration data/calibration/volume_calibration.json \
  --device-name "Sleep Headphones" \
  --backend dry-run
```

## Run With Audio

Use `--backend system` only when you are ready for real low-volume playback:

```bash
OUTDIR="data/recordings/pilot4_low_volume_$(date +%Y%m%d_%H%M%S)"

.venv/bin/python -m muse_tmr.cli.main run-pilot4-cueing \
  --source amused \
  --address "$MUSE_ADDR" \
  --duration-hours 2 \
  --output-dir "$OUTDIR" \
  --catalog data/protocol/puzzle_catalog.json \
  --session data/protocol/night-001_puzzles.json \
  --assignment data/protocol/night-001_assignment.json \
  --cue-library data/cues/starter.json \
  --calibration data/calibration/volume_calibration.json \
  --device-name "Sleep Headphones" \
  --backend system \
  --default-volume 0.02 \
  --hard-max-volume 0.20
```

The default duration rules require 2-8 hours unless `--allow-short` is present.

`--preset` (default `p1034`) is the headband preset and also picks the REM gate
thresholds: 0.80/0.70 on `p1034`, still provisional, and 0.90/0.85 on `p21`, where
the gate does not count the missing PPG against REM confidence. `--enter-threshold`
and `--exit-threshold` override the pair; see `docs/data_model.md`. The same preset
sets the arousal guard's `optics_capable`: on `p21` missing PPG neither lowers volume
nor leads to a `repeated_artifact_quality` pause, the HR rules are skipped, and
`arousal_guard_events.jsonl` records `ppg_absent_by_design` on each decision. Motion,
alpha and EEG artifact rules still apply. Pilot 5 uses the same wiring.

## Emergency Stop

The summary prints an `emergency_stop` path. Creating that file blocks future playback
while allowing the run to keep logging:

```bash
touch "$OUTDIR/EMERGENCY_STOP"
```

The audio player records an emergency-stop event in `audio_playback.jsonl` and future
cue attempts are logged as blocked.

## Manual Awakening Markers

If you wake during or after the pilot and want to mark it:

```bash
.venv/bin/python -m muse_tmr.cli.main log-pilot4-awakening \
  "$OUTDIR/awakening_events.jsonl" \
  --notes "woke briefly; no clear cue recall"
```

Use short factual notes. Keep the file local unless you intentionally sanitize it.

## Outputs

The output directory contains:

- `raw_amused.bin`, `metadata.json`, `events.jsonl`;
- `scheduler_events.jsonl`;
- `arousal_guard_events.jsonl`;
- `audio_playback.jsonl`;
- `awakening_events.jsonl`;
- `pilot4_summary.json`.

The summary passes only when:

- at least one epoch was processed;
- scheduler events were generated;
- every scheduler `play` event contains `rem_gate_open`;
- uncued puzzles received zero scheduler `play` events;
- effective playback volume stayed within calibration and hard caps;
- arousal guard and emergency stop artifacts are available.

An empty cue night can still pass if stable REM or safety conditions were not met.
That means the system refused to cue rather than forcing audio.

## Audio backend preflight

Real audio (`--backend system` or `--backend afplay`) requires an available
`afplay` command. Otherwise playback commands exit with code 2 and explain the
fix. Pilot 4/5 check this before connecting the source or creating recording files.
For intentional testing without sound, add `--allow-dry-run`; explicit
`--backend dry-run` and `--backend mock` also remain supported test modes.
This applies to `play-test-cue`, `train-tlr-cue`, `run-pilot4-cueing` and
`run-pilot5-full-night`.

For example: `muse-tmr play-test-cue --backend system --allow-dry-run` permits
silent fallback when `afplay` is missing. Metadata and reports preserve requested
and actual backend names; see [data_model.md](data_model.md#audio-backend-preflight).

Availability does not establish speaker routing or audibility. On the target Mac
with an available audio device, run `muse-tmr play-test-cue --backend system`
while awake and confirm sound through the intended output. This manual hardware
check remains required; silent testing cannot validate audible cues.
