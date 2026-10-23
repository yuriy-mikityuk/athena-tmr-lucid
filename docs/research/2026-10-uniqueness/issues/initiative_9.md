# Initiative 9: Versioned, labelled synthetic night corpus in the Athena TAG format and a hardware-free demo command

## Why

Every "synthetic recording" in the test suite is empty. Four test files carry their own copy of the helper (the notes count three): `write_synthetic_recording()` in `tests/test_replay.py` line 19, `tests/test_pilot3_replay_simulation.py` line 134 and `tests/test_rem_annotations.py` line 45, and `write_replay_recording()` in `tests/test_epochs.py` line 71. Each writes three zero-filled packets, `bytes(28)` EEG, `bytes(36)` ACCGYRO and `bytes(60)` for `TAG_OPTICS_8CH`, whose table entry at `muse_athena_protocol.py` line 59 is 40 data bytes. Zero counts decode to −725 µV DC on all four channels (`eeg_counts_to_uv_centered`, lines 222–226): format-valid, physiologically empty, which is why the saturated eye proxy of #116 passed every test. REM-like signal exists only as in-memory sines (`rem_like_eeg_channels()`, `tests/test_pilot3_replay_simulation.py` lines 24–35) and pink noise in `tests/meditation_synthetic.py`, never as TAG packets; the only real bytes are the 28,122-byte awake capture `tests/test_data/muse_20250824_172756.bin`. The app's `--source mock` mocks contact quality only (`src/muse_tmr/app/server.py` lines 425–426). The README quick start (`README.md` lines 35–73) needs a headband at its second command, and no job in `.github/workflows/guardrails.yml` runs replay → detector → gate → scheduler → report.

No public Muse overnight dataset exists on Zenodo, PhysioNet or OpenNeuro as of 2026-10-21 (docs/research/2026-10-uniqueness/notes/verify_wearable_rem_physiology_open_science.md row 18). Realism therefore comes from the repository's own measurements: #108 (23.34 %/h drain on `p1034`, 10.01 %/h on `p21`, death at 2 h 29 min; the completed night: 835,926 notifications over 7.998 h, battery 83.32 → 1.13 %), #160 (43 repeated subpackets in 23 min, 1.0 % lost EEG and 0.4 % lost optics subpackets, ≈257.2 Hz effective rate), #154 (a 63.93–63.95 Hz line up to ≈40 µV on AF7 with optics), and from the ZMax F7/F8-to-Fpz montage, where REM counts against PSG EOG gave r = 0.66 with ≈1.8× over-counting attributed to the near-Fpz reference (Esfahani et al. 2023, bioRxiv, https://www.biorxiv.org/content/10.1101/2023.08.18.553744v1). Synthetic REM morphology is an assumption, not a measurement.

Of the inspected projects none ships a labelled synthetic overnight corpus in device format: southsko/muse-sleep-dashboard, the closest, has a `smoke_test.py` with four unlabelled synthetic CSVs that "prove code paths only, not real sleep quality" (notes/muse_ecosystem.md); Taran-Douley/closed-loop-sleep simulates on Sleep-EDF PSG (notes/verify_cueing_tools_landscape.md row 9); EazzZyLearn_pc re-streams a user's own data over OSC (notes/gap_1_direct_open_source_competitor_softcoding.md). The judgement scores honesty 3/5: synthetic agreement is test infrastructure, never evidence; every artefact must say "synthetic input, not sleep"; nothing here claims REM accuracy or efficacy.

## Scope

PR A, generator and tests:

- [ ] `src/muse_tmr/testing/synthetic.py` (+ `__init__.py`): `script_night(seed, hours=8.0, rem_periods=4–5, wake_bouts)` → 30 s hypnogram with arousals; `SyntheticNightConfig` (preset `p21|p1034`, 1/f background 10–20 µV RMS, N3 delta, REM theta with low alpha plus opposite-polarity AF7/AF8 deflections of 20–60 µV and 0.3–1.5 s, wake alpha and in-phase blinks, IMU bursts at arousals and posture changes, PPG pulse at a scripted HR, 63.9 Hz line at 20–40 µV only when `preset_provides_optics`, BLE gaps, #160-style repeats and losses, battery decay, ≈29 notifications/s bundling); `generate_night(config, output_dir)`. The pink-noise helper of `tests/meditation_synthetic.py` moves here.
- [ ] `src/muse_tmr/testing/tag_encoder.py`: vectorised inverses of `decode_eeg_raw_counts` (14-bit LSB-first, `muse_athena_protocol.py` line 216), `decode_accgyro` (252), `decode_optics` (270), `decode_battery` (`TAG_BATTERY_2`, 295), and notification assembly per `parse_payload` (byte 0 length, byte 9 TAG, byte 10 counter, further `[TAG][4-byte header][data]`). Top-level BLE modules untouched.
- [ ] Recording layout: `raw_amused.bin` via `MuseRawStream.write_packet` (`muse_raw_stream.py` line 98); `metadata.json` with `source.source_name = "synthetic"`, `metadata.preset`, capabilities, `synthetic: true`; `events.jsonl`; `summary.json` with every `RecordingSummary` field (`src/muse_tmr/data/recorder.py` lines 53–82) so `validate_pilot1_recording` runs unchanged; ground truth `hypnogram.csv`, `arousals.csv`, `rem_events.csv`, `generation.json` (generator version, seed, config, sizes, sha256).
- [ ] `src/muse_tmr/testing/scenarios.py`: `clean_night` (`p21`, 8 h), `fragmented_rem`, `no_rem_nap` (`p1034`, 1 h, zero REM), `battery_death_2h29` (`p1034`, 23.34 %/h, `stop_reason = "source_ended"`), `optics_line`, `bad_contact_af7`, `movement_heavy`, `short_allow_short` (10 min, unit-test default); all accept `hours`. Size honesty: 28-byte four-sample EEG subpackets make an 8 h night ≈52 MB of EEG payload, ≈96 MB on `p21`, ≈180 MB on `p1034`, so the notes' "≤10 MB" cannot hold for full nights; scenarios are generated on demand into a temp dir or `data/synthetic/` (gitignored; `*.bin` is forbidden by `scripts/check_forbidden_files.py` line 15), never committed.
- [ ] `src/muse_tmr/testing/agreement.py`: `score_against_hypnogram(rows, hypnogram)` → binary κ, REM recall/precision, gate-open fraction, first-gate-open latency per REM period; output carries `"synthetic": true` and "synthetic input, not sleep".
- [ ] Replace the four helpers with `generate_night(scenario="short_allow_short")`; keep the hand-built repeat test at `tests/test_replay.py` line 108.
- [ ] `tests/test_synthetic_night.py`: same seed → same sha256; encoder round trips within 1 LSB; replay counts match `generation.json` minus scripted losses; decoder stats equal scripted repeats and losses; N3 delta > REM delta and deflections only in R epochs; line only on optics presets; Pilot 1 passes `clean_night` with `--required-modality eeg --required-modality imu` and fails `battery_death_2h29`; `short_allow_short` < 1 MB, < 2 s. Register in `run_tests.py`.

PR B, commands, CI, docs:

- [ ] `muse-tmr synthesize-night --scenario NAME [--list] [--seed] [--hours] --output DIR` and `muse-tmr demo [--scenario clean_night] [--hours 2] [--output DIR] [--no-open]` in `src/muse_tmr/cli/main.py`: generate, build Pilot 3 protocol files with the loaders `_simulate_replay_cues` uses (lines 1975–2000) and generated-tone cues, run `validate_pilot1_recording`, `simulate_replay_cue_plan` (mock audio), the HTML report and the agreement score; print one summary block; open the report unless `--no-open`.
- [ ] Move `build_report` from `scripts/generate_nightly_report.py` line 328 into `src/muse_tmr/reports/nightly_report.py` (script becomes a wrapper) so `demo` works from the wheel; a "Synthetic input, not sleep" callout and title suffix whenever `metadata.json` says `synthetic: true`.
- [ ] `end_to_end` job in `guardrails.yml`: `muse-tmr demo --hours 2 --no-open`, asserting Pilot 1 passed, `uncued_puzzle_play_count == 0`, report exists, agreement within `tests/fixtures/synthetic/agreement_baseline.json`; the `package` job runs `demo --hours 0.25 --no-open` from the wheel.
- [ ] Docs: `docs/synthetic_data.md` (modelled vs not, parameter provenance, ground-truth formats, size table, never-evidence rule, decoder-oracle offer to amused-py, OpenMuse, BrainFlow, muse-rs); `README.md` lines 35–73 (`demo` first after install); `docs/USAGE.md` (new section after line 144; notes at 494, 514); `docs/data_model.md` after line 78; `docs/validation.md` table at line 29 ("Synthetic end-to-end regression", not validity); `docs/pilot3_replay_cue_simulation.md` line 17; `AGENTS.md`; `CHANGELOG.md`.

## Acceptance criteria

- [ ] `tests/test_synthetic_night.py` plus updated `test_replay`, `test_epochs`, `test_rem_annotations`, `test_pilot3_replay_simulation`, `test_cli` pass; `python run_tests.py --all` green; `policy`, `tests`, `package`, `page`, `end_to_end` green; `scripts/check_wheel.py` sees `muse_tmr/testing/*`.
- [ ] Two CI runs of one seed give the same sha256.
- [ ] PR description reports per scenario: MB, generation and replay seconds, decoder repeated/lost vs scripted; for `clean_night` and `fragmented_rem`: κ, REM recall, precision, gate-open fraction, first-gate-open latency per REM period, each labelled "synthetic input, not sleep".
- [ ] `uncued_puzzle_play_count == 0` on every scenario; `demo` asserts `audio_backend == "mock"`; the diff touches nothing under `src/muse_tmr/models/`, `protocol/`, `audio/`, so `P_REM` reaches audio only through `StableRemGate` and `ArousalGuard`; no weight or threshold fitted to synthetic data.
- [ ] Every synthetic artefact (HTML, JSON, stdout) contains "synthetic input, not sleep"; no `*.bin`, hypnogram or report committed; `check_forbidden_files.py` and `git diff --check` clean; no fragment of a real night; no REM-accuracy or efficacy claim.

## Out of scope

- PSG or real-night validation (Initiative 2); refitting on synthetic data and the REM-event feature (1); EDF/BIDS export of synthetic nights (6); cue-locked arousal scoring (3); sham arms (4); preset registry (7); PyPI, releases, Zenodo (8).
- Plugin registry and conformance suites, tonic/phasic sub-gate, cross-platform audio (rejected in notes/strategy_judgement.md); an app `--source synthetic` live stream (follow-up); fNIRS/HbO modelling; any live BLE run.

## Depends on

- Initiative 1 — its `tests/rem_event_synthetic.py` defines the deflection model this generator must share (moved into `muse_tmr.testing.synthetic`), and the agreement baseline is taken against the post-1 detector. Work may start in parallel; merge after 1. If 1 is unmerged, use the fixture spec of notes/gap_4 and port on rebase.
- Coordination only: 8 (`guardrails.yml`), 5 (`README.md`). Related: #108, #154/#155, #160/#182; #116 (fixture that would have caught it; stays open), #167 (synthetic first-cue latency only; stays open).

## Needs from the maintainer

None blocks the merge. Optional: run `muse-tmr demo` once on macOS from a clean venv to confirm the report opens (CI is Linux with `--no-open`); decide whether a pre-rendered `clean_night` archive (~100 MB) goes on a GitHub release as `remind-synthetic-nights-v1`. The agent creates no releases or Zenodo deposits (Initiative 8); without a decision the corpus stays generate-on-demand, the documented default.

## Files

`src/muse_tmr/testing/{__init__.py, synthetic.py, tag_encoder.py, scenarios.py, agreement.py}` (new), `src/muse_tmr/reports/nightly_report.py` (new), `scripts/generate_nightly_report.py`, `src/muse_tmr/cli/main.py`, `.github/workflows/guardrails.yml`, `.gitignore`, `run_tests.py`, `tests/{test_synthetic_night.py (new), test_replay.py, test_epochs.py, test_rem_annotations.py, test_pilot3_replay_simulation.py, test_cli.py, meditation_synthetic.py, fixtures/synthetic/agreement_baseline.json (new)}`, `docs/{synthetic_data.md (new), USAGE.md, data_model.md, validation.md, pilot3_replay_cue_simulation.md}`, `README.md`, `AGENTS.md`, `CHANGELOG.md`.

## Evidence

- docs/research/2026-10-uniqueness/report.md: "### 9. Собрать размеченный синтетический корпус ночей…" and Part 1 "Где собственные заявления репозитория не подкреплены данными".
- docs/research/2026-10-uniqueness/notes/: strategy_judgement.md, strategy_community.md (Initiative 3), strategy_technical.md, verify_repo_inventory.md (A16, B6), gap_2_the_repo_s_only_accuracy_figures_live_so.md (A3a–A3f), gap_4_the_ocular_channel_on_muse_why_the_eye_m.md, verify_wearable_rem_physiology_open_science.md (rows 6, 18), muse_ecosystem.md, verify_cueing_tools_landscape.md (row 9), gap_1_direct_open_source_competitor_softcoding.md.
- GitHub: #108, #116, #154/#155, #160/#182, #167.
- Esfahani et al. 2023, bioRxiv: https://www.biorxiv.org/content/10.1101/2023.08.18.553744v1; Lanthier et al. 2025, Sleep Advances: https://pmc.ncbi.nlm.nih.gov/articles/PMC12782022/.
- https://github.com/southsko/muse-sleep-dashboard; https://github.com/Taran-Douley/closed-loop-sleep; https://github.com/SoftcodingForYou/EazzZyLearn_pc; https://github.com/DominiqueMakowski/OpenMuse; https://github.com/brainflow-dev/brainflow.
