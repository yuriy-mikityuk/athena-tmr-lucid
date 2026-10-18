# Test Status

## Current Test Results
- **686 tests passing**, 5 skipped ✅
- **0 tests failing** 🎉
- **88% line coverage** on the `muse_tmr` package

Measured on 2026-10-18 with Python 3.12 on macOS. Three skipped tests require an
optional pandas Parquet engine (`pyarrow` or `fastparquet`) for the Parquet export
paths; two cross-check the complexity metrics against `antropy` and `neurokit2` and
run only when those are installed.

## Coverage Overview
Well covered: REM detection (heuristic + personal classifier), the
`StableRemGate` and `ArousalGuard` safety gates, the TMR cue scheduler,
randomization, the staged pilots, audio playback safety branches
(volume caps, fades, backend fallbacks), the ring buffer, the
acquisition sources' error/timeout paths, the recorder, contact quality,
the meditation analysis and report, the calibration protocol, and the
Polar H10 session and cardio-respiratory features (92-98% each). The local
app server is at 87%.

Lower coverage worth improving:
- `cli/main.py` (66%), the largest module
- `data/watchdog.py` no-data timeout / reconnect logic (78%)
- `app/auto_update.py` (79%), `reports/source_diagnostics.py` (80%) and
  `sources/polar_h10.py` (81%)
- Legacy root-level modules (`muse_sleep_parser`, `muse_integrated_parser`,
  `muse_stream_client`, `muse_discovery`) if they remain on the live path

## Running Tests

### Full suite under pytest (matches CI):
```bash
pip install -e ".[dev]"
python -m pytest tests/
```

### With coverage:
```bash
python -m pytest tests/ --cov=muse_tmr --cov-report=term-missing
```

### Legacy unittest runner (no install required):
```bash
PYTHONPATH=src python run_tests.py --all
```

### Specific test file:
```bash
python -m pytest tests/test_rem_gate.py -v
```

## Notes
- A repository-root `conftest.py` puts `src/` on `sys.path` so `pytest` works
  from a checkout without an editable install.
- CI (`.github/workflows/guardrails.yml`) runs the full suite with coverage on
  every push and pull request.
