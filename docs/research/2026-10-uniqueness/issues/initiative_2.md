# Initiative 2: Validate the REM detector and stable gate against PSG consensus on the open BOAS dataset (OpenNeuro ds005555) through an external-labels harness

## Why

The repository's only accuracy figures (κ 0.30, precision 0.30 at recall 0.80, 342/959 gate-open epochs, per-feature AUCs) come from one EEG-only Muse night, `overnight_20260707`, scored against GSSC with thresholds fitted on that same night, and live only in PR #115 and issue #116; the files hold only the paraphrase: `src/muse_tmr/presets.py` lines 28–30 ("VALIDATED ... one full night (n=1)"), `README.md` line 127, `docs/USAGE.md` line 279, `docs/data_model.md` lines 276–283. GSSC was "mostly trained on C3, C4, F3, F4" and has no published evaluation on forehead-only EEG (docs/research/2026-10-uniqueness/notes/gap_2_the_repo_s_only_accuracy_figures_live_so.md Part B), so κ 0.30 is agreement between two unvalidated systems, not a PSG number. `scripts/validate_rem_detection.py` only replays a `raw_amused.bin` directory (`recording_dir`, line 556; `_collect`, line 79) against a YASA or GSSC subprocess (`REFERENCE_SCRIPTS`, line 214; `--reference`, lines 567–568). It takes no external hypnogram; its `reference` field (line 433) records tool, `--eeg`, `--eog` but no package versions, resampling rate or command line; it reports no REM-onset latency, false-open minutes or per-feature AUC.

BOAS (OpenNeuro ds005555) is the one open dataset that puts a PSG-consensus number on the method without a lab: CC0, BIDS, 128 subject folders = 128 nights from 100 participants (linked by `pid`), Bitbrain Ikon headband EEG `HB_1`/`HB_2` ≈ AF7/AF8 at 256 Hz referenced to the mastoids, six IMU channels and `HB_PULSE`, with simultaneous Micromed PSG scored by three AASM scorers plus a tie-breaker (`stage_hum`, with `stage_ai`; codes 0=W, 1–3=N1–N3, 4=REM, 8=disconnection, −2=artifact), files `*_acq-headband_eeg.edf`, v1.1.3, ≈36 GB (notes/verify_sleep_staging_tools.md row 14, verify_wearable_rem_physiology_open_science.md row 12; Esparza-Iaizzo et al. 2026, Comput Biol Med, https://doi.org/10.1016/j.compbiomed.2026.111560). Device-specific training beats architecture: DreamentoScorer κ 0.72 vs vendor 0.60 on 135 ZMax nights (Esfahani et al. 2023, bioRxiv, https://www.biorxiv.org/content/10.1101/2023.08.18.553744v1); generic YASA on home ZMax κ 0.450, REM recall 0.62 (Parry & Briganti 2026, medRxiv, https://www.medrxiv.org/content/10.64898/2026.06.01.26354591v1.full). Frontal headbands over-call REM (Muse-S +6.4 min, Lanthier et al. 2025, Sleep Advances, https://pmc.ncbi.nlm.nih.gov/articles/PMC12782022/), and intra-subject evaluation inflates agreement, so splits must be by participant (notes/wearable_rem_physiology_open_science.md KQ4, preprint not re-verified).

Of the projects inspected, no open REM-gated engine reports its own detector against PSG consensus, and no source reports REM-vs-non-REM metrics for a causal frontal-only model (notes/sleep_staging_tools.md line 160). The closest, ezscore-f (https://github.com/coonwg1/ezscore), is a ZMax-trained offline stager with no Muse loader and no gate, which an independent group could not install. BOAS is an Ikon referenced to the mastoids, not a Muse referenced near Fpz: results are "transfer-validated on a frontal montage", never "Muse-validated", and the current detector is the expected-weak baseline. Nothing here measures cueing efficacy.

## Scope

- [ ] `src/muse_tmr/data/boas.py`: `iter_boas_nights(root)` (BIDS walk, `participants.tsv`, `pid`), `BoasHeadbandSession(BaseMuseSource)` emitting `MuseFrame` with `source="boas"`, `eeg.channels_uv={"AF7","AF8"}` (TP9/TP10 absent), `imu`, `ppg` from `HB_PULSE`; `load_boas_hypnogram()` → `RemAnnotation` rows mapping 0→`wake`, 1–3→`nrem`, 4→`probable_rem`, 8/−2/missing→`unknown`, `stage_ai` kept as `reference_stage_ai`. EDF via Initiative 6's reader and `[edf]` extra, never a second library.
- [ ] `src/muse_tmr/validation/rem_metrics.py`: move `binary_metrics`, `_cohen_kappa`, `roc_auc`, `best_f1_threshold`, `threshold_sweep`, `simulate_gate` out of the script (which imports them unchanged); add `precision_at_recall(y, p, 0.80)`, `rem_onset_latency_seconds` (first reference-REM epoch of each REM period → first gate-open), `false_open_minutes`, `per_feature_auc`.
- [ ] `scripts/validate_rem_detection.py --labels <annotation csv/json | BOAS night dir>`: skips the stager, sets `reference.tool="external"`; combined with `--reference`, also scores that stager against the labels (GSSC and YASA vs consensus). Add `provenance`: command line, `muse_tmr.__version__`, git commit, Python/numpy/scipy/stager/torch versions, resample Hz, epoch and stride seconds, thresholds (extend Initiative 5's keys if present). `scripts/_rem_validation_html.py` must render `tool="external"`.
- [ ] `src/muse_tmr/validation/external_labels.py` + `muse-tmr validate-external --dataset boas --root <path> --splits <splits.json> [--make-splits --seed N] --gate-thresholds {p21,boas_v1} --output-dir <dir>` in `src/muse_tmr/cli/main.py`: participant-grouped `fit`/`report` folds (both nights of a `pid` together), refuses to score a night whose `pid` was fitted on; per-night and pooled metrics JSON.
- [ ] `data/validation_public/boas/splits.json` (seed, `dataset_version` 1.1.3, DOI) and per-night 30-s CSVs (offset, `stage_hum`, `stage_ai`, `p_rem`, `gate_open`, feature scores; no EEG) plus pooled `metrics.json`; add `!data/validation_public/**` to `.gitignore` (line 38 ignores `*.csv`); gzip if the directory exceeds 20 MB.
- [ ] `src/muse_tmr/presets.py`: named threshold set `boas_v1` beside `_PRESET_GATE_THRESHOLDS`, opt-in via `--gate-thresholds`; `preset_gate_thresholds("p21")` unchanged. (The report says "preset"; in code presets are Muse stream names that also decide optics capability, so a BOAS fit cannot be one.)
- [ ] `src/muse_tmr/models/ml_rem_detector.py`: `train-rem-classifier --init <artifact>` warm start (same `feature_names`, else refuse); `training_data` metadata; `PERSONAL_REM_MODEL_VERSION` 2 loading v1; artifact `data/validation_public/boas/boas_v1_personal_rem_model.json` trained on fit folds, per-epoch features only (causal).
- [ ] Docs: `docs/validation_external.md` runbook (DataLad download from https://github.com/OpenNeuroDatasets/ds005555, venvs, run, wording); `docs/USAGE.md` after line 280; README CLI table (42 commands) and ML paragraph; `docs/data_model.md` (annotation mapping, model v2, `boas_v1`); `docs/validation.md` technical-quality rows.
- [ ] Tests: `tests/test_boas_dataset.py` (two-night synthetic BOAS layout in `tmp_path`), `tests/test_rem_metrics.py` (known-answer latency, false-open, precision-at-recall, AUC), `tests/test_external_labels.py` (splits never separate a `pid`; `--labels` run on `write_synthetic_recording`), classifier `--init` and causality tests; all added to `run_tests.py`.

## Acceptance criteria

- [ ] `python run_tests.py --all`, `scripts/check_forbidden_files.py`, `git diff --check` and all four `.github/workflows/guardrails.yml` jobs pass; `tests/test_rem_gate.py` and `tests/test_presets.py` unchanged.
- [ ] `git ls-files data/validation_public` contains no `.edf`, `.bin`, raw EEG or absolute timestamps.
- [ ] PR description reports, for report folds only, per-night and pooled REM κ, F1, precision at recall 0.80, gate-open precision, onset-latency median/IQR, false-open min/night, per-feature AUC — for heuristic+`p21`, heuristic+`boas_v1`, the personal artifact, GSSC and YASA vs consensus — with `splits.json` hash and commit.
- [ ] A test proves predictions for epoch k are identical with and without later epochs; a test proves `validate-external` refuses fit/report overlap by `pid`.
- [ ] No module in scope imports `muse_tmr.audio` or `muse_tmr.protocol`; `RemGateDecision` exposes only `gate_open`, `state`, reasons; `scheduled_puzzle_ids` logic untouched.
- [ ] Added text uses "transfer-validated on a frontal montage (Bitbrain Ikon, mastoid reference)" and never "Muse-validated", "validated", "effective".

## Out of scope

Ocular-feature redesign and `DEFAULT_REM_WEIGHTS` (Initiative 1, #116, #167); wording fixes to "VALIDATED"/"frontal-trained" (Initiative 5); EDF/BIDS export, `import`, `annotate-template --from-hypnogram` (Initiative 6); a public results table, Wearanize+, a Muse+PSG lab night, software paper, tonic/phasic sub-gate (rejected or deferred in notes/strategy_judgement.md); ezscore-f integration (follow-up issue; installability risk); changing live gate defaults.

## Depends on

- Initiative 6 — provides the EDF reader, `[edf]` extra and hypnogram-import path this loader reuses (`pyproject.toml` has no EDF dependency; `*.edf` is forbidden, `scripts/check_forbidden_files.py` line 22).
- Recommended after Initiative 5 (same lines of `presets.py`, `validate_rem_detection.py`) and Initiative 1 (feature set the artifact trains on). Related: #116, #167.

## Needs from the maintainer

- ≈40 GB free disk and an unattended multi-hour download and CPU run (128 nights through the GSSC and YASA venvs). The agent checks `df` and runs it; if space or network is lacking, it merges loader, harness, tests and docs on the synthetic fixture and leaves the 128-night run open with a `needs-maintainer:` comment.
- Decide later whether `boas_v1` becomes the live `p21` default after a Muse re-check; this issue keeps it opt-in.

## Files

`src/muse_tmr/data/boas.py`, `src/muse_tmr/validation/{rem_metrics,external_labels,__init__}.py`, `src/muse_tmr/models/ml_rem_detector.py`, `src/muse_tmr/presets.py`, `src/muse_tmr/cli/main.py`, `scripts/validate_rem_detection.py`, `scripts/_rem_validation_html.py`, `data/validation_public/boas/`, `.gitignore`, `pyproject.toml`, `run_tests.py`, `tests/test_{boas_dataset,rem_metrics,external_labels,personal_rem_classifier,cli}.py`, `docs/{validation_external,USAGE,data_model,validation}.md`, `README.md`.

## Evidence

- Report §2: docs/research/2026-10-uniqueness/report.md ("### 2. Привязать детектор и гейт к PSG-консенсусу"), Part 1 "Где собственные заявления репозитория не подкреплены данными".
- Notes: strategy_judgement.md §2 and "Rejected or deferred"; strategy_science.md §1; strategy_technical.md Initiative 2; strategy_community.md Initiative 8; verify_sleep_staging_tools.md rows 8, 14; verify_wearable_rem_physiology_open_science.md rows 7, 8, 12; gap_2 Part B; verify_repo_inventory.md A6, A13, C1.
- Data: https://github.com/OpenNeuroDatasets/ds005555 (DOI 10.18112/openneuro.ds005555.v1.1.3); GSSC https://github.com/jshanna100/gssc (Hanna & Flöel 2023, Front Neuroinform, https://www.frontiersin.org/articles/10.3389/fninf.2023.1086634/full); ezscore-f paper: Coon et al. 2025, bioRxiv, https://www.biorxiv.org/content/10.1101/2025.06.02.657451.full.
