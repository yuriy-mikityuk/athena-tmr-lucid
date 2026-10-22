# Initiative 1: Replace the saturated eye-movement proxy with a low-pass bipolar AF7-AF8 REM feature, refit the detector and publish the first-cue latency budget

## Why

`eye_movement_proxy` carries 0.25 of the heuristic REM weight (`src/muse_tmr/models/heuristic_rem_detector.py` line 19) and is dead on real data. `_eye_movement_proxy()` (`src/muse_tmr/features/eeg_features.py` lines 305–320) returns `mean|diff(AF7−AF8)|` over raw 256 Hz samples with no filter, and its scoring band 0.05–0.20 µV per sample (lines 36–37, `_high_score` lines 303–313) was fitted to the 1 Hz, 9 µV sine of the test fixture (`tests/test_rem_detector.py` lines 33–42). A first difference at 256 Hz is a high-pass that weights the Athena ≈63.9 Hz optics line about 64× more than a 1 Hz eye movement; the owner measured 3.4–11.7 µV per sample awake, so the score is 1.0 on every epoch and its AUC against GSSC-REM on `overnight_20260707` was 0.500 (#116). Units are not the cause (docs/research/2026-10-uniqueness/notes/gap_4_the_ocular_channel_on_muse_why_the_eye_m.md, KQ A). The plan agreed in #116 (zero → redesign → refit → re-grid) has not landed.

A second defect sits in the pilots. `--stride-seconds` exists on four commands (`src/muse_tmr/cli/main.py` lines 185, 327, 372, 422), but `src/muse_tmr/validation/pilot3.py` line 230 and `pilot4.py` line 351 pass `epoch.duration_seconds`, the 30 s epoch length (`src/muse_tmr/features/epochs.py` lines 53–54, 110), to `gate.update()`. At a 10 s stride the 60 s stability window and 120 s cooldown (`rem_gate.py` lines 47–49, 161–168, 266) would elapse three times faster than real time. notes/strategy_judgement.md calls the hop "already implemented"; the code says otherwise and wins. So the ≥60–90 s first-cue latency raised in #167 cannot be shortened safely today, and nothing measures it.

The redesign has direct evidence. On the closest published montage, ZMax F7−F8 referenced to Fpz, an event detector gave REM counts r = 0.66 and density r = 0.60 against PSG EOG with ≈1.8× over-counting (Esfahani et al. 2023, bioRxiv preprint, https://www.biorxiv.org/content/10.1101/2023.08.18.553744v1); Lanthier et al. 2025, Sleep Advances, aligned Muse-S to PSG by the blinks visible in its frontal channels (https://pmc.ncbi.nlm.nih.gov/articles/PMC12782022/). No inspected project exposes REM density on a consumer headband: the closest, Dreamento, calls `yasa.rem_detect` only offline in its BrainProducts PSG branch with EOG indices; ezscore-f outputs stages; EazzZyLearn_pc has no ocular feature (notes/gap_4 KQ B, notes/gap_1). Blinks (wake/N1) and frontal slow waves (N3) share the band and the near-Fpz reference attenuates horizontal EOG, so the feature stays a supporting term in the conjunction, never a trigger, and gains are reported as AUC against an automated proxy, never as REM accuracy.

## Scope

Three PRs in this order, each tested on its own:

- [ ] PR 1, weights: `DEFAULT_REM_WEIGHTS["eye_movement_proxy"]` 0.25 → 0.0, renormalise the other five to sum 1.0 (`heuristic_rem_detector.py`) so `limited_feature_weight_threshold` 0.40 keeps its meaning; `_weighted_probability` already skips zero weights (lines 280–282), so `feature_scores` and `DEFAULT_PERSONAL_REM_FEATURES` (`ml_rem_detector.py` lines 20–32) are untouched. Tests in `tests/test_rem_detector.py`: weights sum to 1, `p_rem` ignores the proxy value, an EEG+IMU p21 epoch does not trip `limited_feature_support`.
- [ ] PR 2, feature: new `src/muse_tmr/features/rem_event_features.py` with `RemEventConfig`, a stateful, causal, deterministic `RemEventTracker` and `detect_rem_events()`: bipolar AF7−AF8, band-pass ≈0.3–5 Hz, deflections of 0.3–1.5 s above `max(k × running MAD, floor_uv)` with a warm-up flag, optional common-mode veto for in-phase blinks. Emits `rem_event_count`, `rem_density_per_min`, `last_rem_event_age_s`, `rem_burst_active`, `rem_event_times`, `rem_event_threshold_uv` through `extract_eeg_features()`, `EEGFeatureRow` and `to_dict()`; `eye_movement_proxy` stays as a deprecated diagnostic column so old annotation CSVs and model artifacts load. The 63.9 Hz line: remove it first with `remove_lines()` (`complexity_features.py` line 349) on optics presets, or prove in the fixture test that the band-pass alone leaves a 40 µV line below 0.1 µV.
- [ ] PR 2, detector and runners: sub-score `rem_event_density`, reason codes `eeg_rem_events_support`/`eeg_rem_events_low`, thresholds `rem_event_density_min/strong` and weight 0.0 by default, marked UNFITTED and never fitted on synthetic data (that is the defect being removed); `pilot3.py`, `pilot4.py`, the `annotate-template` handler and `scripts/validate_rem_detection.py` run one `RemEventTracker` per session.
- [ ] PR 2, fixture: `tests/rem_event_synthetic.py` (seeded 1/f noise 10–20 µV RMS per channel, 40 µV 64 Hz line, biphasic opposite-polarity 20–60 µV deflections, in-phase blinks) and `tests/test_rem_event_features.py`: old proxy scores 1.0 on REM-dense and REM-free epochs, new count within ±20 % of injected events and ≈0 on REM-free epochs, min ≠ max across epochs, equal counts with and without the line, blinks not counted, missing AF7 or AF8 → NaN. Replace the 1 Hz sine in `rem_like_eeg_channels()` of `tests/test_rem_detector.py`, `test_pilot3_replay_simulation.py` and `test_pilot4_cueing.py` with deflections.
- [ ] PR 3, hop: pilots pass the elapsed time between consecutive epoch starts (first epoch: `stride_seconds`) to `gate.update()`; a test in `tests/test_pilot3_replay_simulation.py` shows that at stride 10 the gate needs ≥60 s and the cooldown 120 s of real time, and that stride 30 output is unchanged.
- [ ] PR 3, latency: Pilot 3 metrics and `pilot4_summary.json` gain `stride_seconds`, `first_gate_open_seconds`, `first_play_seconds`; a synthetic frame-stream test (scripted NREM → REM through `EpochBuilder`) prints the first-gate-open and first-play table for strides 30/10/5.
- [ ] PR 3, refit tooling in `scripts/validate_rem_detection.py`: per-feature ROC-AUC, min/max and a `saturated` flag for every `score_*`/`value_*` column, a `--weights name=w,...` override and an enter/exit grid (gate-open fraction, REM recall/precision) in the JSON, summary and `_rem_validation_html.py`.
- [ ] Docs: `docs/data_model.md` (line 158, REM predictions, gate section: elapsed time, not epoch length), `docs/USAGE.md` (lines 189, 223, 271–279 refit procedure, 514), `README.md` line 26, `docs/pilot3_replay_cue_simulation.md` (stride semantics, latency table), `docs/validation.md` Technical Quality Metrics, `CHANGELOG.md`.
- [ ] Refit, only if ≥2 REM-bearing overnight `p21` recordings already exist under `data/recordings/` on the machine: run the script against `.venv-gssc`, commit aggregate numbers only, set weights and thresholds, re-grid `_PRESET_GATE_THRESHOLDS` in `src/muse_tmr/presets.py` and reword line 28 "VALIDATED" as "tuned on N nights vs GSSC".

## Acceptance criteria

- [ ] `python run_tests.py --all` and the four CI jobs (`policy`, `tests`, `package`, `page`) are green on every PR.
- [ ] `tests/test_rem_event_features.py`, the stride test and the latency-table test exist and pass; `test_rem_detector.py`, `test_rem_gate.py`, `test_presets.py` are updated, nothing skipped or deleted.
- [ ] Pilot 3 `uncued_puzzle_play_count == 0` and Pilot 4 "plays only cued puzzles" still pass; `TmrCueScheduler` consumes only `scheduled_puzzle_ids`; no module under `features/` or `models/` imports `muse_tmr.audio`, so `P_REM` never reaches audio without `StableRemGate` and `ArousalGuard`.
- [ ] PR descriptions report numbers, not promises: old proxy value and score per epoch, new count vs injected with and without the line, the stride 30/10/5 latency table labelled "synthetic input, not sleep", and either per-night per-feature AUC, gate-open fraction and recall at old and new thresholds or the words "refit pending".
- [ ] `rem_event_density` weight is 0.0 and its thresholds say UNFITTED until a PR carries real-night numbers; no synthetic value becomes a threshold.
- [ ] Older `annotate-template` CSVs and personal model artifacts still load and predict (artifact `feature_names` win); a stride-30 replay gives identical scheduler events before and after PR 3.
- [ ] `git diff --check` and `python scripts/check_forbidden_files.py` are clean; nothing under `data/` is committed; no text claims REM accuracy, lucid-dreaming or memory effects.

## Out of scope

- PSG-anchored validation, the BOAS loader, `--labels`, stager version and flag logging (Initiatives 2 and 5).
- Rewording README line 127 and `docs/USAGE.md` line 279 beyond what the re-grid touches (Initiative 5).
- The synthetic night corpus and `demo` (Initiative 9); the fixture stays in `tests/`.
- Tonic/phasic REM sub-gate, automatic LRLR detection, `yasa.rem_detect` EOG constants (rejected in notes/strategy_judgement.md).
- New gate semantics, lower thresholds, any live-BLE or real-audio run, the optics-preset re-grid (needs a REM-bearing p1034 night, #116).
- Zeroing `theta_alpha_ratio`: the refit data decides.

## Depends on

none. Run after Initiative 5 when possible: both edit `presets.py`, `README.md` and `docs/USAGE.md` wording; if 5 is not merged, do not reintroduce "VALIDATED". Closes #116 and #167.

## Needs from the maintainer

- Record at least two REM-bearing overnight `p21` nights at home (Pilot 1, no audio) under `data/recordings/`. Why: the checkout holds no recording, `overnight_20260707` is not on the machine (#116), and the agent has no headband. Without them the agent merges PRs 1–3 with the feature at weight 0.0, posts `needs-maintainer:` here and leaves the issue open. Afterwards run `scripts/validate_rem_detection.py <night> --reference gssc --preset p21 --dump-epochs <csv> --output <json>` per night (`.venv-gssc` per `docs/USAGE.md`) and hand the JSONs to the refit PR.
- Optional: `muse-tmr simulate-replay-cues <night> --preset p21 --stride-seconds 10` to replace the synthetic latency table with a real one.

## Files

`src/muse_tmr/features/{rem_event_features.py (new), eeg_features.py, __init__.py}`, `src/muse_tmr/models/heuristic_rem_detector.py`, `src/muse_tmr/presets.py`, `src/muse_tmr/validation/{pilot3.py, pilot4.py}`, `src/muse_tmr/cli/main.py` (annotate-template handler), `scripts/{validate_rem_detection.py, _rem_validation_html.py}`, `tests/{rem_event_synthetic.py (new), test_rem_event_features.py (new), test_rem_detector.py, test_eeg_features.py, test_rem_gate.py, test_pilot3_replay_simulation.py, test_pilot4_cueing.py, test_presets.py}`, `docs/{data_model.md, USAGE.md, pilot3_replay_cue_simulation.md, validation.md}`, `README.md`, `CHANGELOG.md`.

## Evidence

- docs/research/2026-10-uniqueness/report.md, section "### 1. Заменить глазной прокси биполярным REM-событийным признаком и опубликовать бюджет задержки" and Part 1 "Где собственные заявления репозитория не подкреплены данными".
- docs/research/2026-10-uniqueness/notes/: strategy_judgement.md, strategy_technical.md (Initiative 1), strategy_science.md (§1 step 2), strategy_community.md (Initiative 3), gap_4_the_ocular_channel_on_muse_why_the_eye_m.md, gap_2_the_repo_s_only_accuracy_figures_live_so.md, verify_repo_inventory.md (A8), repo_inventory.md.
- GitHub: #116, #167, PR #115, #154/#155.
- Esfahani et al. 2023, bioRxiv, https://www.biorxiv.org/content/10.1101/2023.08.18.553744v1; Lanthier et al. 2025, Sleep Advances, https://pmc.ncbi.nlm.nih.gov/articles/PMC12782022/; YASA `rem_detect` https://yasa-sleep.org/generated/yasa.rem_detect.html; Dreamento https://github.com/dreamento/dreamento; ezscore-f https://github.com/coonwg1/ezscore; EazzZyLearn_pc https://github.com/SoftcodingForYou/EazzZyLearn_pc; BrainFlow PR #856 https://github.com/brainflow-dev/brainflow/pull/856.
