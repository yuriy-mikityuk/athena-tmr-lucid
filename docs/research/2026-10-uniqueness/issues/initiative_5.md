# Initiative 5: Honesty, provenance and positioning pass (VALIDATED wording, dead YAML configs, GSSC description, citations, license line, package name)

## Why

The only accuracy figures come from one EEG-only night, `overnight_20260707`, staged by GSSC with thresholds fitted on that same night, yet `src/muse_tmr/presets.py` line 28 says "VALIDATED against a GSSC reference" (line 57: "validated"); `README.md` line 127 and `docs/USAGE.md` line 279 never say in-sample, and κ 0.30, precision 0.30, 342/959 epochs and the per-feature AUC table exist only in PR #115, #112 and #116 (notes/verify_repo_inventory.md A6, C1). GSSC is called "frontal-trained" (`scripts/validate_rem_detection.py` lines 502, 570; `scripts/_gssc_stage.py` 10) although its README says it "was mostly trained on the EEG channels C3, C4, F3, F4" and nothing evaluates it on forehead-only EEG (notes/gap_2_… Part B). The metrics JSON `reference` block (line 433) holds tool, `eeg` and `eog` only, with no versions, resample rate or command line; `docs/USAGE.md` line 274 installs `gssc` unpinned although `_gssc_stage.py` line 62 depends on 0.0.9's 2-tuple return (GSSC `main` returns three). Code corrects the notes: `_gssc_stage.py` line 34 already defaults `--eog none`, but the harness's `--eog AF8` default (line 558) is forwarded (line 226), so AF8-as-EOG, not recommended by GSSC's README, is effective; TP9/TP10 are never passed.

"Konkoly-like" (`README.md` line 3), "Konkoly-style" (line 115) and `docs/protocol.md` line 18 name a protocol nobody cites (A12) for a one-way 396 Hz TLR without eye-signal verification (`tlr_protocol.py` 25–27). The four `configs/*.yaml` are loaded by no module and drift: 0.7 vs 0.80/0.70, stable window 30 vs 60 s, fades 1.5 vs 0.25 s, cooldown 60 vs 120 s (A7). `LICENSE` line 3 names only "nexon33"; `pyproject.toml` line 126 pins `Amused-EEG/amused-py` while `README.md` line 171 and `docs/amused_upstream.md` lines 3, 41 link `nexon33/amused` (A15); the distribution `athena-tmr-lucid` (`pyproject.toml` line 6) contradicts README line 13's no-lucid-claims stance; `TEST_STATUS.md` is self-reported (A3).

Evaluators penalise this: undisclosed ZLab training data made DreamentoScorer incomparable (Esfahani et al. 2023, bioRxiv, https://www.biorxiv.org/content/10.1101/2023.08.18.553744v1); ezscore-f went unevaluated for "installation incompatibilities" (Parry & Briganti 2026, medRxiv, https://www.medrxiv.org/content/10.64898/2026.06.01.26354591v1.full). κ 0.30 is a binary consistency check between two unvalidated systems, never comparable with five-class κ such as the Muse-S vendor's 0.76 (Lanthier et al. 2025, Sleep Advances, https://pmc.ncbi.nlm.nih.gov/articles/PMC12782022/). Of the repositories inspected none ships a dated status block, a numbers-provenance page or a comparison table; Dreamento, the closest (SoftwareX paper, MIT, last push 2024-03-18), documents neither a competitor comparison nor its stimulation–stage coupling. Nothing here claims efficacy.

## Scope

PR 1 is wording and documentation; PR 2 is harness provenance.

- [ ] `presets.py` 28, 57; `README.md` 127; `docs/USAGE.md` 279; `docs/data_model.md` 280–281: "tuned in-sample on one EEG-only night (overnight_20260707, n=1) against GSSC, an automated proxy; fitted and reported on the same night; κ and epoch counts only in PR #115 / #116"; rename `tests/test_presets.py` line 35 accordingly.
- [ ] "frontal-trained" / "fits the Muse montage better" (`validate_rem_detection.py` 502, 570; `_gssc_stage.py` 7–12; `_rem_validation_html.py` 69–83; `docs/USAGE.md` 279) becomes "trained mostly on C3, C4, F3, F4 (NSRR PSG); stages from one EEG channel; no published evaluation on forehead-only EEG".
- [ ] `README.md` 13: dated "Project status" block (one EEG-only night, GSSC proxy, in-sample thresholds, zero audio nights, one-feature detector (#116), first cue ≥60–90 s after REM onset (#167), self-reported test counts, n = 1, distribution name pending Initiative 8); line 5 adds `athena-tmr-lucid`.
- [ ] `README.md` 3, 115 and `docs/protocol.md` 18: "Konkoly-like/-style" becomes "a one-way, REM-timed cue protocol: a cue paired with a puzzle or lucidity intention before sleep, replayed when the stable REM gate opens; no eye-signal verification". New `docs/references.md` listing the papers under Evidence, one line each on what the repository takes from them, linked from README and `docs/protocol.md`.
- [ ] Delete the four `configs/*.yaml`; `docs/protocol.md` 18 points at the dataclass defaults (`RemGateConfig`, `AudioPlaybackConfig`, scheduler config, `TlrCueConfig`) by file; `CHANGELOG.md` entry.
- [ ] `LICENSE`: add "Copyright (c) 2026 Yuriy Mikityuk"; the upstream line stays.
- [ ] One upstream URL, `Amused-EEG/amused-py`, in `README.md` 171 and `docs/amused_upstream.md` 3, 41, noting `nexon33/amused` redirects there; the preserved BibTeX stays.
- [ ] `docs/dependency_strategy.md` Contribution Policy: upstream-first for amused-py, BrainFlow and OpenMuse decoders; fixes already upstream (BrainFlow PR #837, merged 2026-05-21, in 5.22.2); the fork's divergence (midscale centering, PR #131).
- [ ] `docs/compare.md`, dated 2026-10-21, from the notes' tables (cueing_tools_landscape.md 14–27, muse_ecosystem.md 14–27, 78–90, sleep_staging_tools.md 57–69) with `verify_*` corrections; includes EazzZyLearn_pc, LucidLink, the LucidScribe Muse plugin; superlatives read "of the repositories inspected".
- [ ] `docs/numbers.md`: every figure quoted in README, docs, `TEST_STATUS.md` and the config dataclasses, with file/line or issue/PR, date and status (measured / self-reported / in-sample / GitHub-only), plus battery %/h (#108), 257.2 Hz and 1 % lost subpackets (#160). One `AGENTS.md` Documentation Rules bullet: a new quoted figure needs a row.
- [ ] `docs/faq.md` from #108, #112, #160, #167, sanitised, with links.
- [ ] PR 2, `scripts/validate_rem_detection.py`: `build_provenance()` writes `provenance` {`command_line`, `timestamp_utc`, `muse_tmr_version`, `git_commit`, `python`, `numpy`, `scipy`, `resample_hz`, `epoch_seconds`, `preset`, `enter_threshold`, `exit_threshold`, `eeg`, resolved `eog`, `channels_not_passed`, `stager` {`tool`, `package_version`, `torch_version`, `mne_version`, `returns_probabilities`}}; `--eog` defaults per reference (`none` GSSC, `AF8` YASA; `--eog AF8` stays an opt-in GSSC variant); top-level `kappa_definition` ("binary REM-vs-not κ against an automated stager; not five-class") in summary and HTML.
- [ ] `_gssc_stage.py` and `_yasa_stage.py` write package, torch and mne versions into the hypnogram JSON; `_gssc_stage.py` accepts 2- and 3-tuples; `docs/USAGE.md` 274 pins `gssc==0.0.9` and says why.
- [ ] Tests: `tests/test_rem_validation_provenance.py` (load scripts with `importlib.util.spec_from_file_location` as `tests/test_report_style.py` does: provenance keys, `eog` resolution, tuple unpacking on fakes, HTML κ label; no stager venv) and `tests/test_docs_wording.py` (forbidden phrases absent from README, docs minus `docs/research/`, src, scripts; `configs/` unreferenced; one upstream URL); both in `run_tests.py`.
- [ ] `docs/USAGE.md` stager section (two commands, `provenance`, `kappa_definition`); `docs/validation.md` Reporting Language bullet on binary versus five-class κ; `CHANGELOG.md`; try `gh repo edit --description --add-topic`.

## Acceptance criteria

- [ ] `python run_tests.py --all`, `python scripts/check_forbidden_files.py`, `git diff --check` and the four CI jobs pass on both PRs; the two new test files run from `run_tests.py`.
- [ ] `grep -rn "VALIDATED\|frontal-trained\|far better fit\|Konkoly-like\|Konkoly-style\|configs/" README.md docs src scripts --exclude-dir=research` returns nothing; `configs/` is gone.
- [ ] No behaviour change: detector, gate, scheduler, guard and pilot tests untouched and green; thresholds unchanged; uncued puzzles unschedulable; `P_REM` reaches audio only through `StableRemGate` and `ArousalGuard`; `pyproject.toml` unmodified.
- [ ] The status block is dated and each claim links a file, issue or PR; `docs/compare.md` is dated; `docs/numbers.md` has a row for every figure `grep -nE "[0-9]+(\.[0-9]+)? ?%|κ|kappa|Hz|bpm|passing"` finds in README, `TEST_STATUS.md` and `docs/*.md` outside research; a test asserts `provenance` and `kappa_definition` in the metrics JSON on a fake stager result.
- [ ] PR descriptions report wording sites changed per file (grep before and after), files deleted, and either `--eog none` versus `--eog AF8` metrics from a maintainer re-run or "not re-run: recording unavailable"; added text follows `docs/validation.md` Reporting Language; nothing under `data/` committed.

## Out of scope

- Distribution rename, PyPI, `CITATION.cff`, Zenodo, CI matrix, `CONTRIBUTING.md`, `ROADMAP.md` (Initiative 8); this issue only documents current names.
- Preset registry, fidelity report, manipulation check, the 396 Hz default (Initiative 7); only the YAML and dangling pointer go.
- Features, weights, thresholds, gate, stride, stager set, ezscore-f, BOAS (Initiatives 1, 2).
- Committing hypnograms or metrics of the owner's nights (owner decision, below).
- Documentation site, plugin registry, software paper, second maintainer, tonic/phasic sub-gate (rejected or deferred in notes/strategy_judgement.md).

## Depends on

none. It merges first: Initiatives 1 and 2 edit the same lines of `presets.py` and `validate_rem_detection.py` (2 extends the `provenance` keys defined here), 7 edits `docs/protocol.md`, 8 edits `README.md` and `LICENSE`. Related: #116 and #167 stay open, cited in the status block and FAQ.

## Needs from the maintainer

- A written decision on committing sanitised per-epoch GSSC hypnograms and metrics JSON of `overnight_20260707` under `data/validation_public/` (AGENTS.md forbids personal sleep data by default). Without it the agent commits none, marks those figures "GitHub only" in `docs/numbers.md`, merges the rest and leaves a `needs-maintainer:` comment.
- If `overnight_20260707` still exists anywhere (#116 says not on this machine), re-run `scripts/validate_rem_detection.py <night> --reference gssc --preset p21 --output <json>` after PR 2 with `--eog none` and `--eog AF8` and paste `provenance` and metrics into `docs/numbers.md` in a follow-up PR; the agent has no recording or headband. Without it the page says "not re-run".
- Confirm the distribution name for Initiative 8 (`remind-eeg` as the research recommends, keeping `muse-tmr` and `muse_tmr`); without it the status block says "pending".
- Set the GitHub About description and topics if the worker's `gh repo edit` is refused (admin rights).

## Files

`src/muse_tmr/presets.py`, `scripts/{validate_rem_detection.py, _gssc_stage.py, _yasa_stage.py, _rem_validation_html.py}`, `configs/*.yaml` (deleted), `LICENSE`, `README.md`, `AGENTS.md` (one bullet), `CHANGELOG.md`, `run_tests.py`, `docs/{USAGE.md, data_model.md, protocol.md, dependency_strategy.md, amused_upstream.md, validation.md, references.md, compare.md, numbers.md, faq.md}`, `tests/{test_presets.py, test_rem_validation_provenance.py, test_docs_wording.py}`.

## Evidence

- docs/research/2026-10-uniqueness/report.md: Part 2 "### 5. Пройтись по честности, провенансу и позиционированию"; Part 1 "Где собственные заявления репозитория не подкреплены данными".
- docs/research/2026-10-uniqueness/notes/: strategy_judgement.md, strategy_science.md (#2, #7), strategy_community.md (#1, #7), strategy_technical.md (#8), verify_repo_inventory.md, repo_inventory.md, gap_2_… (Part B), gap_1_…, cueing_tools_landscape.md, muse_ecosystem.md, verify_muse_ecosystem.md, sleep_staging_tools.md, tmr_tlr_science.md, verify_tmr_tlr_science.md, wearable_rem_physiology_open_science.md (KQ8).
- GitHub: #116, #167, PR #115, #112, #108, #160; https://github.com/jshanna100/gssc; https://github.com/brainflow-dev/brainflow/pull/837; https://github.com/Amused-EEG/amused-py; https://github.com/dreamento/dreamento; https://github.com/SoftcodingForYou/EazzZyLearn_pc; https://github.com/Venryx/LucidLink; https://github.com/lucidcode/LucidScribe-InteraXon-Muse-EEG.
- Papers: Konkoly 2021 https://doi.org/10.1016/j.cub.2021.01.026; Konkoly 2024 https://pmc.ncbi.nlm.nih.gov/articles/PMC11542932; Konkoly 2026 https://academic.oup.com/nc/article/2026/1/niaf067/8456489; Carr 2020, Psychology of Consciousness 10(4):413–430, https://doi.org/10.1037/cns0000227; Sanders 2019 https://pmc.ncbi.nlm.nih.gov/articles/PMC6843748 (correction Psychol Sci 2020;31(8):1048); Schwartz 2022 https://doi.org/10.1016/j.cub.2022.09.032; Borghese 2022 https://pmc.ncbi.nlm.nih.gov/articles/PMC9281560/; Picard-Deland/Esfahani 2024 v2 https://www.biorxiv.org/content/10.1101/2024.06.21.600133; Hanna & Flöel 2023 https://www.frontiersin.org/articles/10.3389/fninf.2023.1086634/full; Hanif 2025 https://doi.org/10.1111/jsr.70048; Gunter 2026 https://www.medrxiv.org/content/10.64898/2026.07.06.26357378v1.full; Esfahani 2023, Parry & Briganti 2026, Lanthier 2025 as linked above.
