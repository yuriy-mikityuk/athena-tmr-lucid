# M8 Pilot 2: Audio Calibration Only

Pilot 2 validates daytime audio calibration. Do not run REM-gated scheduling, TLR
blocks, puzzle cue scheduling, or overnight cue playback during this pilot.

## Goal

- Find conservative detectable, identifiable, and comfortable cue volumes for the target
  playback device.
- Save a local calibration JSON with the selected playback device name.
- Prove later playback code uses the calibration cap by running a dry-run cap probe.
- Keep generated calibration files and playback logs local; do not commit them.

This pilot checks calibration and safety behavior. It is not a sleep cueing or
effectiveness test.

## Calibrate

Start with low volumes while awake:

```bash
cd /path/to/athena-tmr-lucid

for v in 0.01 0.02 0.03 0.04 0.05 0.06; do
  echo "volume=$v"
  .venv/bin/python -m muse_tmr.cli.main play-test-cue \
    --frequency-hz 440 \
    --duration-seconds 1 \
    --volume "$v" \
    --max-volume 0.20 \
    --backend system
  sleep 3
done
```

Use conservative thresholds:

- `detectable-volume`: the quietest level where the sound is noticed.
- `identifiable-volume`: the quietest level where the cue is recognizable as a tone.
- `comfortable-volume`: the maximum level that still feels safe and non-irritating for
  sleep-time use.

Save the calibration:

```bash
.venv/bin/python -m muse_tmr.cli.main calibrate-volume \
  --device-name "Sleep Headphones" \
  --output data/calibration/volume_calibration.json \
  --detectable-volume 0.01 \
  --identifiable-volume 0.04 \
  --comfortable-volume 0.06 \
  --backend dry-run \
  --notes "Daytime calibration before M8 sleep pilots"
```

## Prove The Cap

Run a dry-run probe that requests a louder volume than the comfortable cap:

```bash
.venv/bin/python -m muse_tmr.cli.main play-test-cue \
  --frequency-hz 440 \
  --duration-seconds 1 \
  --volume 0.10 \
  --max-volume 0.20 \
  --calibration data/calibration/volume_calibration.json \
  --device-name "Sleep Headphones" \
  --backend dry-run \
  --log-path data/calibration/volume_calibration_test.jsonl
```

Expected output includes `volume_capped=True` and an effective volume no higher than the
saved comfortable volume. With `--backend dry-run`, no audible sound should play.

## Validate

Generate the Pilot 2 report:

```bash
.venv/bin/python -m muse_tmr.cli.main validate-pilot2-calibration \
  data/calibration/volume_calibration.json \
  --device-name "Sleep Headphones" \
  --playback-log data/calibration/volume_calibration_test.jsonl \
  --output data/reports/pilot2_audio_calibration_validation.json
```

The command exits `0` only when:

- the calibration store exists and contains the selected device;
- detectable, identifiable, and comfortable volumes are ordered;
- `scheduler_max_volume` equals `comfortable_volume` and is within the hard cap;
- the dry-run cap probe used the selected device;
- the probe requested a volume above the scheduler max and was capped to the
  calibration limit;
- the cap probe used a non-sleep backend such as `dry-run` or `mock`.

If validation fails, inspect `failed_criteria` in the JSON report. Do not use the
calibration for sleep-time cueing until the report passes.
