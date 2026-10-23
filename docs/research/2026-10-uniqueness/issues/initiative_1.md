# Initiative 1: Replace the saturated eye-movement proxy with a low-pass bipolar AF7-AF8 REM feature, refit the detector and publish the first-cue latency budget

## Why

`eye_movement_proxy` carries 0.25 of the heuristic REM weight (`src/muse_tmr/models/heuristic_rem_detector.py` line 19) and is dead on real data. `_eye_movement_proxy()` (`src/muse_tmr/features/eeg_features.py` lines 305–320) returns `mean|diff(AF7−AF8)|` over unfiltered 256 Hz samples, and its scoring band 0.05–0.20 µV per sample (`heuristic_rem_detector.py` lines 36–37) was fitted to the 1 Hz, 9 µV sine in `tests/test_rem_detector.py` lines 33–42. The first difference is a high-pass dominated by noise and the Athena ≈63.9 Hz optics line; real epochs give 3.4–11.7 µV per sample, so the score is 1.0 everywhere and its AUC against GSSC-REM on `overnight_20260707` was 0.500 (#116). Units are not the cause (docs/research/2026-10-uniqueness/notes/gap_4_the_ocular_channel_on_muse_why_the_eye_m.md, KQ A). #116 agreed zero → redesign → refit → re-grid; nothing landed.

Second, the hop. `--stride-seconds` exists on four commands (`src/muse_tmr/cli/main.py` lines 185, 327, 372, 422), but `src/muse_tmr/validation/pilot3.py` line 230 and `pilot4.py` line 351 pass `epoch.duration_seconds`, the 30 s epoch length (`src/muse_tmr/features/epochs.py` lines 53–54, 110), to `gate.update()`. At a 10 s stride the 60 s stability window and 120 s cooldown (`rem_gate.py` lines 47–49) would elapse three times faster than real time. notes/strategy_judgement.md calls the hop "already implemented"; the code says otherwise and wins. So the ≥60–90 s first-cue latency of #167 cannot be shortened safely, and nothing measures it.

On the closest published montage, ZMax F7−F8 referenced to Fpz, an event detector gave REM counts r = 0.66 and density r = 0.60 against PSG EOG, over-counting ≈1.8× (Esfahani et al. 2023, bioRxiv, https://www.biorxiv.org/content/10.1101/2023.08.18.553744v1); Lanthier et al. 2025, Sleep Advances, aligned Muse-S to PSG by the blinks in its frontal channels (https://pmc.ncbi.nlm.nih.gov/articles/PMC12782022/). No inspected project exposes REM density on a consumer headband: Dreamento, the closest, calls `yasa.rem_detect` only offline, in its BrainProducts PSG branch, on EOG; ezscore-f outputs stages; EazzZyLearn_pc has no ocular feature (notes/gap_4 KQ B). Blinks (wake/N1) and frontal slow waves (N3) share the band and the near-Fpz reference attenuates horizontal EOG, so the feature stays a supporting term, never a trigger, and gains are AUC against an automated proxy, never REM accuracy.

## Scope

Three sub-issues, one PR each, in order: 1a weights, 1b REM-event feature with fixture, 1c hop and latency budget with refit tooling. The refit itself is a separate, conditional PR (1d) that is filed only when the maintainer's nights exist.

- [ ] 1a, weights: `DEFAULT_REM_WEIGHTS["eye_movement_proxy"]` 0.25 → 0.0; renormalise the other five to sum 1.0 so `limited_feature_weight_threshold` 0.40 keeps its meaning. `_weighted_probability` skips zero weights (lines 280–282), so `feature_scores` and `DEFAULT_PERSONAL_REM_FEATURES` (`ml_rem_detector.py` lines 20–32) stay unchanged. The `presets.py` comment gains "p21 thresholds were fitted with the pre-reweighting weights; re-grid pending (#116)", because the 0.90/0.85 `_PRESET_GATE_THRESHOLDS` were fitted with the old weights. Tests in `tests/test_rem_detector.py`: weights sum to 1, `p_rem` ignores the proxy, an EEG+IMU p21 epoch does not trip `limited_feature_support`.
- [ ] 1b, feature: new `src/muse_tmr/features/rem_event_features.py` with `RemEventConfig`, a stateful, causal, deterministic `RemEventTracker` and `detect_rem_events()`: bipolar AF7−AF8, band-pass ≈0.3–5 Hz, deflections of 0.3–1.5 s above `max(k × running MAD, floor_uv)` with a warm-up flag, optional common-mode veto for in-phase blinks. Outputs `rem_event_count`, `rem_density_per_min`, `last_rem_event_age_s`, `rem_burst_active`, `rem_event_times`, `rem_event_threshold_uv` on `EEGFeatureRow`; `eye_movement_proxy` stays as a deprecated column so old CSVs and model artifacts load. Remove the 63.9 Hz line first with `remove_lines()` (`complexity_features.py` line 349) on optics presets, or prove in the fixture test that the band-pass alone leaves a 40 µV line below 0.1 µV.
- [ ] 1b, detector and runners: sub-score `rem_event_density` with reason codes `eeg_rem_events_support`/`eeg_rem_events_low`, thresholds `rem_event_density_min/strong` and weight 0.0 by default, marked UNFITTED, never fitted on synthetic data; `pilot3.py`, `pilot4.py`, the `annotate-template` handler and `scripts/validate_rem_detection.py` run one tracker per session.
- [ ] 1b, fixture: `tests/rem_event_synthetic.py` (seeded 1/f noise 10–20 µV RMS, 40 µV 64 Hz line, biphasic opposite-polarity 20–60 µV deflections, in-phase blinks) and `tests/test_rem_event_features.py`: old proxy scores 1.0 on REM-dense and REM-free epochs, new count within ±20 % of injected events and ≈0 without events, equal counts with and without the line, blinks not counted, missing AF7 or AF8 → NaN. Replace the 1 Hz sine in the three `rem_like_eeg_channels()` fixtures with deflections.
- [ ] 1c, hop and latency (depends on the guard-fix issue 10a, see Initiative 10: without it a `p21` run is guard-paused from the third epoch and `first_play_seconds` never exists): pilots pass the elapsed time between consecutive epoch starts (first epoch: `stride_seconds`) to `gate.update()`, with a test that at stride 10 the gate needs ≥60 s and the cooldown 120 s of real time while stride 30 output is unchanged; Pilot 3 metrics and `pilot4_summary.json` gain `stride_seconds`, `first_gate_open_seconds`, `first_play_seconds`; a synthetic frame-stream test (scripted NREM → REM through `EpochBuilder`, preset `p21`) prints the latency table for strides 30/10/5.
- [ ] 1c, refit tooling in `scripts/validate_rem_detection.py` and `_rem_validation_html.py`: per-feature ROC-AUC, min/max and a `saturated` flag for every `score_*`/`value_*` column, a `--weights name=w,...` override, an enter/exit grid (gate-open fraction, REM recall/precision). Initiative 2 later moves the per-feature AUC into `src/muse_tmr/validation/rem_metrics.py`; do not pre-empt that.
- [ ] Docs: `docs/data_model.md` (line 158, REM predictions, gate section), `docs/USAGE.md` (lines 189, 223, 271–279, 514), `README.md` line 26, `docs/pilot3_replay_cue_simulation.md` (stride semantics, latency table), `docs/validation.md` metrics table, `CHANGELOG.md`.
- [ ] 1d, refit, only if ≥2 REM-bearing overnight `p21` recordings already exist under `data/recordings/`: commit aggregate numbers only, set weights (including `theta_alpha_ratio`) and thresholds, re-grid `_PRESET_GATE_THRESHOLDS` in `src/muse_tmr/presets.py`, and update Initiative 5's `presets.py` wording to "tuned on N nights vs GSSC" (Initiative 5 has already removed "VALIDATED").

## Acceptance criteria

- [ ] `python run_tests.py --all` and the four CI jobs (`policy`, `tests`, `package`, `page`) green on every PR; `tests/test_rem_event_features.py`, the stride test and the latency test exist and pass; nothing skipped or deleted.
- [ ] Pilot 3 `uncued_puzzle_play_count == 0` and Pilot 4 "plays only cued puzzles" still pass; no module under `features/` or `models/` imports `muse_tmr.audio`, so `P_REM` never reaches audio without `StableRemGate` and `ArousalGuard`.
- [ ] PR descriptions report numbers, not promises: fixture old-proxy score and new count vs injected (with and without the line), the stride 30/10/5 latency table labelled "synthetic input, not sleep", and real-night per-feature AUC with gate-open fraction and recall at old and new thresholds, or "refit pending".
- [ ] `rem_event_density` weight stays 0.0 and its thresholds UNFITTED until real-night numbers exist.
- [ ] Older `annotate-template` CSVs and model artifacts still load; a stride-30 replay gives identical scheduler events before and after 1c.
- [ ] `git diff --check` and `python scripts/check_forbidden_files.py` clean; nothing under `data/` committed; no text claims REM accuracy or efficacy of any kind.

## Out of scope

- PSG-anchored validation, BOAS loader, `--labels`, stager version logging (Initiatives 2, 5).
- README line 127 and `docs/USAGE.md` line 279 wording (Initiative 5).
- The synthetic night corpus (Initiative 9).
- Tonic/phasic sub-gate, automatic LRLR detection, `yasa.rem_detect` EOG constants (rejected in notes/strategy_judgement.md).
- New gate semantics, lower thresholds, live-BLE or real-audio runs, the optics-preset re-grid (needs a REM-bearing p1034 night, #116).

## Depends on

- Initiative 5 (merged first; it edits the same `presets.py`, `README.md` and `docs/USAGE.md` wording and removes "VALIDATED").
- 1c only: the guard-fix issue 10a (see Initiative 10), because the latency table and `first_play_seconds` are measured on `p21`.
- Refs #116, #167; the refit PR (1d) closes #116, the latency PR (1c) closes #167; PR descriptions use Refs, not Closes, so that no earlier PR auto-closes either issue while the refit waits on maintainer nights.

## Needs from the maintainer

- Record at least two REM-bearing overnight `p21` nights (Pilot 1, no audio) under `data/recordings/`. Why: no recording is in the checkout or on the machine (#116) and the agent has no headband. Without them the agent merges 1a–1c at weight 0.0, posts `needs-maintainer:` and leaves this issue and #116 open (1d is not filed). Afterwards run `scripts/validate_rem_detection.py <night> --reference gssc --preset p21 --dump-epochs <csv> --output <json>` per night for the refit PR.
- Optional: a real-night latency table via `simulate-replay-cues <night> --preset p21 --stride-seconds 10`.

## Files

`src/muse_tmr/features/{rem_event_features.py (new), eeg_features.py, __init__.py}`, `src/muse_tmr/models/heuristic_rem_detector.py`, `src/muse_tmr/presets.py`, `src/muse_tmr/validation/{pilot3.py, pilot4.py}`, `src/muse_tmr/cli/main.py` (annotate-template handler), `scripts/{validate_rem_detection.py, _rem_validation_html.py}`, `tests/{rem_event_synthetic.py (new), test_rem_event_features.py (new), test_rem_detector.py, test_eeg_features.py, test_rem_gate.py, test_pilot3_replay_simulation.py, test_pilot4_cueing.py, test_presets.py}`, `docs/{data_model.md, USAGE.md, pilot3_replay_cue_simulation.md, validation.md}`, `README.md`, `CHANGELOG.md`.

## Evidence

- docs/research/2026-10-uniqueness/report.md: Part 2 "### 1. Заменить глазной прокси…" and Part 1 "Где собственные заявления репозитория не подкреплены данными".
- docs/research/2026-10-uniqueness/notes/: strategy_judgement.md, strategy_technical.md, strategy_science.md, strategy_community.md, gap_4_the_ocular_channel_on_muse_why_the_eye_m.md, gap_2_the_repo_s_only_accuracy_figures_live_so.md, verify_repo_inventory.md.
- GitHub: #116, #167, PR #115, #154/#155.
- Esfahani 2023 https://www.biorxiv.org/content/10.1101/2023.08.18.553744v1; Lanthier 2025 https://pmc.ncbi.nlm.nih.gov/articles/PMC12782022/; https://yasa-sleep.org/generated/yasa.rem_detect.html; https://github.com/dreamento/dreamento; https://github.com/coonwg1/ezscore; https://github.com/SoftcodingForYou/EazzZyLearn_pc; https://github.com/brainflow-dev/brainflow/pull/856.
