# Initiative 8: Install, cite, govern: PyPI release as remind-eeg, CITATION.cff and DOI, CI matrix, package namespace and a loud audio preflight

## Why

Nobody can install, cite or reproduce REMind without cloning it. `pyproject.toml` line 6 still names the distribution `athena-tmr-lucid` (README line 5 says `remind-eeg`); PyPI returned 404 for every candidate name on 2026-10-21 (notes/gap_2 A7). `requires-python = ">=3.8"` and classifiers 3.8–3.12 (lines 16, 23–27) promise five Pythons, but `.github/workflows/guardrails.yml` pins 3.11 on `ubuntu-latest` in all four jobs (lines 16, 28, 44, 61). The wheel ships 16 top-level `py-modules` (lines 86–103), including `amused.py`, the repository's own shim (lines 1–5) whose import name is the upstream PyPI package `amused` 1.0.2 (inferred, not tested); the engine imports them at `src/muse_tmr/sources/amused_source.py` lines 13–14, 26, 248, `data/recorder.py` 16, `data/replay.py` 11–12 and `validation/pilot4.py` 13. `TEST_STATUS.md` lines 4–6 ("724 tests passing", "88% line coverage") are self-reported; CI uploads no coverage (notes/verify_repo_inventory.md A3, B2). No `CITATION.cff`, `CONTRIBUTING.md`, `ROADMAP.md` or templates exist; `README.md` line 185 cites only upstream amused-py.

The one safety item: `create_audio_backend()` (`src/muse_tmr/audio/audio_player.py` lines 297–301) maps `system` to `afplay` when found, else silently to `dry-run`. `run_pilot4_cueing_night` (`validation/pilot4.py` line 313) never checks the result; it writes the requested name to `metadata.json` (line 708) and the resolved one only to the summary (line 586), so a Pilot 4/5 night started with `--backend system` off macOS is silent and still passes (`docs/pilot4_low_volume_cueing.md` line 124); Pilot 2's ladder uses `play-test-cue --backend system` (`docs/pilot2_audio_calibration.md` line 31). The fallback is only logged afterwards (VRI C3).

Evaluators judge installability: ezscore-f "were not evaluated due to installation incompatibilities" (Parry & Briganti 2026, medRxiv, https://www.medrxiv.org/content/10.64898/2026.06.01.26354591v1.full). Tools that gained reuse pair pip, a DOI and disclosed versions: YASA (Vallat & Walker 2021, eLife), Portiloop (Valenchon et al. 2022, PLoS ONE), Dreamento (Jafarzadeh Esfahani et al. 2023, SoftwareX), sleepecg (JOSS 2023) (notes/wearable_rem_physiology_open_science.md KQ8). Of the repositories inspected, no open cueing engine is pip-installable with a citation file; Dreamento, the closest, is clone-only (Python 3.6, TensorFlow 1.13.1, ZMax-only, unpushed since 2024-03-18). Uniqueness 2/5: hygiene. A one-line install reaches people looking for a product, so the install path must say "n = 1 research software, not a medical device". No efficacy claim is made.

## Scope

Four sub-issues, one PR each: 8a packaging and CI matrix, 8b `muse_tmr.ble` namespace, 8c citation and governance, 8d fail-loud audio preflight. 8d is a sleep-time safety change with no dependency on the others and may land first; 8a–8c land in order.

Sub-issue 8a (PR A), packaging and CI:
- [ ] `pyproject.toml`: `name = "remind-eeg"`; keep the `muse-tmr` script and `muse_tmr` import; narrow `requires-python` and classifiers to what the matrix passes (target 3.9–3.13); drop the `docs` extra; delete `requirements-viz.txt`; fix "Amused" in `setup.py` and `run_tests.py`, and the 3.8 claims in README lines 7, 37.
- [ ] `.github/workflows/guardrails.yml`: `tests` and `package` as a `fail-fast: false` matrix, Python 3.9–3.13 × ubuntu/macos/windows; upload `coverage.xml` and print the total; platform-specific tests skipped with a named reason.
- [ ] `.github/workflows/release.yml` (new): on `v*` tags build sdist and wheel, run `scripts/check_wheel.py` and `muse-tmr --version` from the wheel, assert tag == `__version__`, attach `dist/*` to the release, publish via `pypa/gh-action-pypi-publish` trusted publishing gated on repository variable `PYPI_PUBLISH`; it also has `workflow_dispatch` with input `dry_run` (default `true`) that builds, checks and uploads artifacts without publishing, so the agent can exercise it without cutting a tag; `docs/release.md` (new); `docs/USAGE.md` lines 36–46.
- [ ] `tests/test_packaging.py` (new, text-based): name and script, `requires-python` floor vs classifiers vs matrix, `CITATION.cff` version vs `__version__`, no `amused` in `py-modules`.

Sub-issue 8b (PR B), namespace:
- [ ] This issue supersedes the `AGENTS.md` Repository Shape bullet ("Change [the top-level `amused.py` and `muse_*.py` modules] only for BLE or protocol fixes") and `docs/architecture.md` line 15 ("intentionally avoids moving the existing top-level `muse_*.py` modules"); rewrite both, and add to `docs/dependency_strategy.md` how upstream amused-py diffs map onto `src/muse_tmr/ble/`.
- [ ] `src/muse_tmr/ble/` (new): `git mv` the 15 `muse_*.py` modules, rewrite cross-imports, update the 8 engine import lines, the 13 test files plus `tests/record_test_data.py`, and 8 examples; `scripts/check_wheel.py` also fails on a top-level `amused*`.
- [ ] Shims for one minor version: top-level `muse_*.py` re-export with a `DeprecationWarning` and stay in `py-modules` until 0.5; `amused.py` re-exports too but leaves `py-modules` now; `tests/test_minimal.py` line 103 asserts the warning.
- [ ] `scripts/install_macos_launcher.py` line 226 and `docs/USAGE.md` line 119 drop `$REPO_ROOT` from `PYTHONPATH`; the amused-py docs (`docs/amused_upstream.md`) follow the new paths.

Sub-issue 8c (PR C), citation and governance:
- [ ] `CITATION.cff` (1.2.0, software, version, date-released, MIT, a `references` entry crediting amused-py by Adrian Tadeusz Belmans, `doi` pending Zenodo); `cffconvert --validate` in the `policy` job.
- [ ] `README.md` "Install" and "How to cite"; `muse-tmr --help` epilog and `muse-tmr status` print "REMind <version>: n = 1 research software, not a medical device" (test in `tests/test_cli.py`).
- [ ] `CONTRIBUTING.md` (dev setup, tests, data and SDK policy, no-efficacy-claims rule, attachment sanitisation); `ROADMAP.md` (dated, honest status first, #116 and #167 open, the ten initiatives with a state each).
- [ ] `.github/ISSUE_TEMPLATE/{bug_report,night_report,feature}.yml`, `.github/pull_request_template.md` with the `AGENTS.md` checklist; `night_report.yml` states that raw recordings, dream text, device names and addresses must not be attached, aggregate numbers only; use the existing nine default labels only (a label taxonomy needs an explicit maintainer request, `AGENTS.md` "Keep labels minimal"); two `good first issue`s from remaining drift.

Sub-issue 8d (PR D), fail-loud audio preflight (no dependency; may land first):
- [ ] `audio/audio_player.py`: `resolve_audio_backend(name, *, allow_dry_run_fallback=False)` returning a `BackendResolution` and raising `AudioBackendFallbackError` when `system`/`afplay` resolve to no sound; `create_audio_backend()` unchanged.
- [ ] `validation/pilot4.py`: resolve right after `config.validate()`, before `source.connect()` and any file write; `Pilot4CueingConfig.allow_dry_run_fallback`; metadata and summary record requested and resolved names.
- [ ] `cli/main.py`: `--allow-dry-run` on `play-test-cue`, `train-tlr-cue`, `run-pilot4-cueing`, `run-pilot5-full-night`; the refusal names the fix and exits 2. Tests in `tests/test_audio_player.py`, `tests/test_pilot4_cueing.py` (refusal before `connect`, nothing written; passes with the flag), `tests/test_cli.py`; docs: `docs/safety.md`, the Pilot 2/4/5 runbooks, `docs/USAGE.md`, `docs/data_model.md`.

## Acceptance criteria

- [ ] All four jobs green on every matrix cell; `python run_tests.py --all`, `python scripts/check_forbidden_files.py`, `git diff --check`, `tests/test_packaging.py` and `cffconvert --validate` pass; `release.yml` exercised once via `workflow_dispatch` with `dry_run=true`, run linked in the PR.
- [ ] `pip wheel . --no-deps` yields `remind_eeg-*.whl` with no top-level `amused*`; from a clean venv `muse-tmr --version` and `import muse_tmr.ble.muse_realtime_decoder` work; `import muse_realtime_decoder` from a checkout warns and works.
- [ ] `test_system_backend_falls_back_to_dry_run_without_afplay` still passes; Pilot 3 replay simulation still reports zero uncued `play`; no change to `StableRemGate`, `ArousalGuard`, `TmrCueScheduler` or randomization; `P_REM` reaches audio only through gate and guard; hard cap 0.20 unchanged.
- [ ] PR descriptions report, not promise: per-cell pass/fail and the final `requires-python`; the coverage total from the artifact, written into `TEST_STATUS.md` with the run id; platform tests skipped and why; import sites changed; wheel size and file count.
- [ ] The docs named in Scope are updated; the banner appears in `--help` and `status`; no efficacy wording is added.

## Out of scope

- Cross-platform real-audio backend, sleep inhibit, TTS, Linux/Windows launchers or night runner (rejected, notes/strategy_judgement.md).
- Software paper, second maintainer, Discussions, Code of Conduct, ADRs, documentation site, plugin registry, public benchmark table (rejected or deferred).
- Initiative 5's wording, LICENSE, upstream-URL and status-block work; 6's `[edf]` extra; 7's presets; 9's `demo`; any detector, gate or scheduler change.
- Publishing to PyPI, minting the DOI, cutting the tag: prepared here, executed by the maintainer.

## Depends on

- Initiative 5 — it edits `LICENSE`, the README status block and the upstream URLs that `CITATION.cff` and "How to cite" must agree with; if unmerged, use `Amused-EEG/amused-py` and reconcile at merge.
- Coordination only: Initiative 6 and 9 also touch `pyproject.toml` and `guardrails.yml`; whichever merges second rebases. 8d depends on nothing. Related: #116, #167 (in `ROADMAP.md`), #183.

## Needs from the maintainer

- Register a PyPI trusted publisher for `remind-eeg` and set repository variable `PYPI_PUBLISH=true`; needs a PyPI account. Without it the agent merges the workflow gated off and leaves a `needs-maintainer:` comment.
- Enable the Zenodo–GitHub integration and, after the first release, give the agent the concept DOI; needs Zenodo consent. Without it "DOI: pending" stays.
- Cut the release tag after the four sub-issues merge; publishing is irreversible (yank only). Without it nothing is released; the agent only runs the `dry_run` dispatch.
- On the Mac, run `muse-tmr play-test-cue --backend system` once after PR D to confirm audible output; CI's macOS runner only proves `afplay` exists.

## Files

`pyproject.toml`, `setup.py`, `run_tests.py`, `requirements-viz.txt`, `amused.py`, `muse_*.py`, `src/muse_tmr/ble/*`, `src/muse_tmr/{sources/amused_source.py, data/recorder.py, data/replay.py, validation/pilot4.py, audio/audio_player.py, audio/__init__.py, cli/main.py}`, `.github/workflows/{guardrails.yml, release.yml}`, `.github/ISSUE_TEMPLATE/*`, `CITATION.cff`, `CONTRIBUTING.md`, `ROADMAP.md`, `README.md`, `AGENTS.md`, `CHANGELOG.md`, `TEST_STATUS.md`, `scripts/{check_wheel.py, install_macos_launcher.py}`, `tests/{test_packaging.py, test_minimal.py, test_audio_player.py, test_pilot4_cueing.py, test_cli.py}` plus the tests and examples importing BLE modules, `docs/{release.md, USAGE.md, safety.md, architecture.md, amused_upstream.md, dependency_strategy.md, data_model.md, pilot2_audio_calibration.md, pilot4_low_volume_cueing.md, pilot5_full_night.md}`.

## Evidence

- docs/research/2026-10-uniqueness/report.md: "### 8. Сделать проект устанавливаемым, цитируемым и управляемым"; "Где собственные заявления репозитория не подкреплены данными".
- docs/research/2026-10-uniqueness/notes/: strategy_judgement.md (§8, "Rejected or deferred"), strategy_science.md §7, strategy_technical.md Initiative 8, strategy_community.md Initiatives 2 and 7, verify_repo_inventory.md A3, A10, B2, C3, gap_2 A7, gap_1 §7, wearable_rem_physiology_open_science.md KQ8, muse_ecosystem.md KQ5.
- Tooling: https://docs.pypi.org/trusted-publishers/; https://citation-file-format.github.io/; https://docs.github.com/en/repositories/archiving-a-github-repository/referencing-and-citing-content; https://pypi.org/pypi/amused/json; https://github.com/Amused-EEG/amused-py.
- Papers and repositories: Parry & Briganti 2026 (above); YASA https://elifesciences.org/articles/70092; Portiloop https://pmc.ncbi.nlm.nih.gov/articles/PMC9394839/; Dreamento https://doi.org/10.1016/j.softx.2023.101595 and https://github.com/dreamento/dreamento; sleepecg https://joss.theoj.org/papers/10.21105/joss.05411; https://github.com/SoftcodingForYou/EazzZyLearn_pc.
