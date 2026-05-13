# M8 Pilot 1: Overnight Recording Without Audio

Pilot 1 validates the live overnight recording path only. Do not run cue playback,
TLR training, REM-gated scheduling, or audio calibration during this pilot.

## Goal

- Record at least 6 hours from the Muse source.
- Generate `summary.json`, `metadata.json`, `events.jsonl`, and raw packet output.
- Confirm nonzero EEG, IMU, and PPG modality coverage from `summary.modality_counts`.
- Confirm no audio, cue, scheduler, or TLR sidecar logs were produced in the recording
  directory.

This pilot checks protocol fidelity and technical recording quality. It is not an
effectiveness or lucid-dreaming test.

## Run

Use the discovered Muse address from the M1 live smoke flow:

```bash
cd /path/to/athena-tmr-lucid

MUSE_ADDR="<discovered-address>"
OUTDIR="$PWD/data/recordings/pilot1_no_audio_$(date +%Y%m%d_%H%M%S)"

muse-tmr record \
  --source amused \
  --address "$MUSE_ADDR" \
  --duration-hours 6 \
  --output-dir "$OUTDIR"
```

For the macOS `Python.app` Bluetooth workaround, keep the same `open -W -n ... "$PYAPP"
--args` wrapper from the README and replace only the command after `--args` with the
`record` invocation above.

## Validate

After the recording completes:

```bash
muse-tmr validate-pilot1-recording "$OUTDIR" \
  --output data/reports/pilot1_no_audio_validation.json
```

The command exits `0` only when:

- `summary.json` exists and is valid JSON.
- `duration_seconds >= 21600`.
- `stop_reason == "duration_complete"`.
- raw packet output exists and `raw_packet_count > 0`.
- downtime fraction is at or below the configured target.
- EEG, IMU, and PPG counts are all nonzero.
- no audio, cue, scheduler, or TLR sidecar logs are present in the recording directory.

If the command exits nonzero, inspect `failed_criteria` in the JSON report and treat the
pilot as incomplete rather than interpreting downstream REM or cue metrics.
