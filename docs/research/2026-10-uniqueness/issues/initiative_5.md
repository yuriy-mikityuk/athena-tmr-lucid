# Initiative 5: Honesty, provenance and positioning pass (VALIDATED wording, dead YAML configs, GSSC description, citations, license line, package name)

## Why

The only accuracy figures come from one EEG-only night, `overnight_20260707`, thresholds fitted on that night against GSSC, yet `src/muse_tmr/presets.py` line 28 says "VALIDATED against a GSSC reference"; `README.md` line 127 and `docs/USAGE.md` line 279 never say in-sample, and κ 0.30 and the AUC table exist only in PR #115, #112, #116 (notes/verify_repo_inventory.md A6, C1). GSSC is called "frontal-trained" (`scripts/validate_rem_detection.py` lines 502, 570; `scripts/_gssc_stage.py` 10) although its README says it "was mostly trained on the EEG channels C3, C4, F3, F4" with no forehead-only evaluation. The metrics JSON (line 433) records no versions, resample rate or command line; `docs/USAGE.md` line 274 leaves `gssc` unpinned although `_gssc_stage.py` line 69 relies on 0.0.9's 2-tuple return. Contrary to the notes, `_gssc_stage.py` line 34 already defaults `--eog none`; the harness overrides it with `--eog AF8` (lines 558, 226), which GSSC's README does not recommend, and never passes TP9/TP10.

"Konkoly-like" (`README.md` line 3), "Konkoly-style" (line 115) and `docs/protocol.md` line 18 name a protocol nobody cites (A12) for a one-way 396 Hz TLR without eye-signal verification. The four `configs/*.yaml` are loaded by no module and drift from code (0.7 vs 0.80/0.70, 30 vs 60 s, 1.5 vs 0.25 s, 60 vs 120 s; A7). `LICENSE` line 3 credits only "nexon33"; `pyproject.toml` 126 vs `README.md` 171 and `docs/amused_upstream.md` 3, 41 give two upstream URLs (A15); the distribution `athena-tmr-lucid` (`pyproject.toml` line 6) contradicts README line 13; `TEST_STATUS.md` is self-reported (A3).

Evaluators penalise this: undisclosed ZLab training data made DreamentoScorer incomparable (Esfahani et al. 2023, bioRxiv, https://www.biorxiv.org/content/10.1101/2023.08.18.553744v1); ezscore-f went unevaluated for "installation incompatibilities" (Parry & Briganti 2026, medRxiv, https://www.medrxiv.org/content/10.64898/2026.06.01.26354591v1.full). κ 0.30 is a binary consistency check between two unvalidated systems, not comparable with five-class κ like the Muse-S vendor's 0.76 (Lanthier et al. 2025, Sleep Advances, https://pmc.ncbi.nlm.nih.gov/articles/PMC12782022/). No inspected repository ships a dated status block, numbers page or comparison table; Dreamento, the closest, documents neither a competitor comparison nor its stimulation–stage coupling.

## Scope

Two sub-issues, one PR each: 5a is wording and documentation (the bullets up to `docs/faq.md`); 5b is harness provenance (the `build_provenance()`, stager-script and provenance-test bullets). 5a merges first.

- [ ] `presets.py` 28, 57; `README.md` 127; `docs/USAGE.md` 279; `docs/data_model.md` 280–281: "tuned in-sample on one EEG-only night (overnight_20260707, n=1) against GSSC, an automated proxy; fitted and reported on the same night; κ and epoch counts only in PR #115 / #116".
- [ ] "frontal-trained" / "fits the Muse montage better" (`validate_rem_detection.py` 502, 570; `_gssc_stage.py` 7–12; `_rem_validation_html.py` 69–83; `docs/USAGE.md` 279) becomes "trained mostly on C3, C4, F3, F4 (NSRR PSG); stages from one EEG channel; no published evaluation on forehead-only EEG".
- [ ] `README.md` 13: dated "Project status" block (one EEG-only night, GSSC proxy, in-sample thresholds, zero audio nights, one-feature detector (#116), first cue ≥60–90 s after REM onset (#167), n = 1, distribution name pending Initiative 8); line 5 adds `athena-tmr-lucid`.
- [ ] `README.md` 3, 115 and `docs/protocol.md` 18: "Konkoly-like/-style" becomes "a one-way, REM-timed cue protocol: a cue paired with a puzzle or lucidity intention before sleep, replayed when the stable REM gate opens; no eye-signal verification". New `docs/references.md` lists the papers under Evidence.
- [ ] Delete the four `configs/*.yaml`; `docs/protocol.md` 18 points at the dataclass defaults by file; `CHANGELOG.md` entry.
- [ ] `LICENSE`: add "Copyright (c) 2026 Yuriy Mikityuk" above the upstream line. One upstream URL, `Amused-EEG/amused-py`, in `README.md` 171 and `docs/amused_upstream.md` 3, 41.
- [ ] `docs/dependency_strategy.md` Contribution Policy: upstream-first for amused-py, BrainFlow and OpenMuse decoders; fixes already upstream (BrainFlow PR #837, 2026-05-21).
- [ ] `docs/compare.md`, dated 2026-10-21, from the notes' tables with `verify_*` corrections, including EazzZyLearn_pc, LucidLink and LucidScribe; superlatives read "of the repositories inspected".
- [ ] `docs/numbers.md`: every figure quoted in README, docs, `TEST_STATUS.md` and the config dataclasses, with source and status; one `AGENTS.md` Documentation Rules bullet: a new quoted figure needs a row. `docs/faq.md` from #108, #112, #160, #167. History rows in both files quote the old wording in backticks or paraphrase it, so the Acceptance grep below stays clean.
- [ ] `gh repo edit --description "REM-gated TMR/TLR research engine for Muse S Athena; n = 1 research software, not a medical device" --add-topic muse,eeg,sleep,targeted-memory-reactivation,lucid-dreaming,research-software`; if refused (admin rights), it moves to Needs from the maintainer.
- [ ] `scripts/validate_rem_detection.py`: `build_provenance()` writes `provenance` {`command_line`, `timestamp_utc`, `muse_tmr_version`, `git_commit`, `python`, `numpy`, `scipy`, `resample_hz`, `epoch_seconds`, `preset`, `enter_threshold`, `exit_threshold`, `eeg`, `eog`, `channels_not_passed`, `stager` {`tool`, `package_version`, `torch_version`, `mne_version`, `returns_probabilities`}}; `--eog` defaults per reference (`none` for GSSC, `AF8` for YASA); `kappa_definition` ("binary REM-vs-not κ against an automated stager; not five-class").
- [ ] `_gssc_stage.py` and `_yasa_stage.py` write package, torch and mne versions into the hypnogram JSON; `_gssc_stage.py` accepts 2- and 3-tuples; `docs/USAGE.md` 274 pins `gssc==0.0.9` and documents both `--eog` runs; `docs/validation.md` Reporting Language bullet on binary versus five-class κ.
- [ ] Tests: `tests/test_rem_validation_provenance.py` (keys, `eog` resolution, tuple unpacking, HTML label; no venv) and `tests/test_docs_wording.py` (the Acceptance grep plus `configs/` and upstream-URL checks), in `run_tests.py`.

## Acceptance criteria

- [ ] `python run_tests.py --all`, `python scripts/check_forbidden_files.py`, `git diff --check` and the four CI jobs pass.
- [ ] `grep -rn "VALIDATED\|frontal-trained\|far better fit\|Konkoly-like\|Konkoly-style\|configs/" README.md docs src scripts --exclude-dir=research` returns nothing outside `docs/numbers.md` and `docs/faq.md`, whose history rows quote the old wording in backticks (`tests/test_docs_wording.py` applies the same exclusion); `configs/` is gone.
- [ ] No behaviour change: detector, gate, scheduler, guard and pilot tests untouched and green; thresholds unchanged; uncued puzzles unschedulable; `P_REM` reaches audio only through `StableRemGate` and `ArousalGuard`; `pyproject.toml` unmodified.
- [ ] Status block and `docs/compare.md` dated, every claim linked; every figure in README, `TEST_STATUS.md` and `docs/*.md` outside research has a `docs/numbers.md` row; a test asserts `provenance` and `kappa_definition` on a fake stager result.
- [ ] PR descriptions report wording sites changed per file and the `--eog none` versus `--eog AF8` metrics or "not re-run: recording unavailable"; text follows `docs/validation.md` Reporting Language; nothing under `data/` committed.

## Out of scope

- Distribution rename, PyPI, `CITATION.cff`, Zenodo, CI matrix, `CONTRIBUTING.md`, `ROADMAP.md` (Initiative 8).
- Preset registry, fidelity report, manipulation check, the 396 Hz default (Initiative 7).
- Features, weights, thresholds, gate, stride, stager set, ezscore-f, BOAS (Initiatives 1, 2).
- Committing hypnograms or metrics of the owner's nights (owner decision, below).
- Documentation site, plugin registry, software paper, second maintainer, tonic/phasic sub-gate (rejected or deferred in notes/strategy_judgement.md).

## Depends on

none. It merges first: Initiatives 1 and 2 touch the same lines of `presets.py` and `validate_rem_detection.py` (2 extends the `provenance` keys defined here), 7 `docs/protocol.md`, 8 `README.md` and `LICENSE`. Related: #116, #167 (stay open; cited in status block and FAQ).

## Needs from the maintainer

- A written decision on committing sanitised per-epoch GSSC hypnograms and metrics JSON of `overnight_20260707` under `data/validation_public/` (AGENTS.md forbids personal sleep data). Without it the agent commits none, marks those figures "GitHub only" in `docs/numbers.md`, merges the rest and leaves a `needs-maintainer:` comment.
- If `overnight_20260707` survives anywhere (#116 says not here), run the updated harness on it with `--eog none` and `--eog AF8` and paste the results into `docs/numbers.md`; the agent has no recording. Otherwise the page says "not re-run".
- Confirm the distribution name for Initiative 8 (`remind-eeg` per the research; keep `muse-tmr`, `muse_tmr`); without it the status block says "pending".
- Set the GitHub About description and topics if the worker's `gh repo edit` (Scope) is refused (admin rights).

## Files

`src/muse_tmr/presets.py`, `scripts/{validate_rem_detection.py, _gssc_stage.py, _yasa_stage.py, _rem_validation_html.py}`, `configs/*.yaml` (deleted), `LICENSE`, `README.md`, `AGENTS.md` (one bullet), `CHANGELOG.md`, `run_tests.py`, `docs/{USAGE.md, data_model.md, protocol.md, dependency_strategy.md, amused_upstream.md, validation.md, references.md, compare.md, numbers.md, faq.md}`, `tests/{test_rem_validation_provenance.py, test_docs_wording.py}`.

## Evidence

- docs/research/2026-10-uniqueness/report.md: Part 2 "### 5. Пройтись по честности, провенансу и позиционированию"; Part 1 "Где собственные заявления репозитория не подкреплены данными".
- docs/research/2026-10-uniqueness/notes/: strategy_judgement.md, strategy_science.md, strategy_community.md, verify_repo_inventory.md, gap_2_…, gap_1_…, cueing_tools_landscape.md, muse_ecosystem.md, verify_muse_ecosystem.md, sleep_staging_tools.md, verify_tmr_tlr_science.md, wearable_rem_physiology_open_science.md.
- GitHub: #116, #167, PR #115, #112, #108, #160; https://github.com/jshanna100/gssc; https://github.com/brainflow-dev/brainflow/pull/837; https://github.com/Amused-EEG/amused-py; https://github.com/dreamento/dreamento; https://github.com/SoftcodingForYou/EazzZyLearn_pc; https://github.com/Venryx/LucidLink; https://github.com/lucidcode/LucidScribe-InteraXon-Muse-EEG.
- Papers: Konkoly 2021 https://doi.org/10.1016/j.cub.2021.01.026; Konkoly 2024 https://pmc.ncbi.nlm.nih.gov/articles/PMC11542932; Konkoly 2026 https://academic.oup.com/nc/article/2026/1/niaf067/8456489; Carr 2020, Psychology of Consciousness 10(4):413–430, https://doi.org/10.1037/cns0000227; Sanders 2019 https://pmc.ncbi.nlm.nih.gov/articles/PMC6843748 (correction Psychol Sci 2020;31(8):1048); Schwartz 2022 https://doi.org/10.1016/j.cub.2022.09.032; Borghese 2022 https://pmc.ncbi.nlm.nih.gov/articles/PMC9281560/; Picard-Deland/Esfahani 2024 v2 https://www.biorxiv.org/content/10.1101/2024.06.21.600133; Hanna & Flöel 2023 https://www.frontiersin.org/articles/10.3389/fninf.2023.1086634/full; Hanif 2025 https://doi.org/10.1111/jsr.70048; Gunter 2026 https://www.medrxiv.org/content/10.64898/2026.07.06.26357378v1.full.
