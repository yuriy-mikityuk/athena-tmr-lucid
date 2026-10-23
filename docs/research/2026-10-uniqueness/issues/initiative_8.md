# Initiative 8: Install, cite, govern: PyPI release as remind-eeg, CITATION.cff and DOI, CI matrix, package namespace and a loud audio preflight

## Why

Nobody can install, cite or reproduce REMind without cloning it. `pyproject.toml` line 6 still names the distribution `athena-tmr-lucid` while `README.md` line 5 says `remind-eeg`; PyPI returns 404 for `athena-tmr-lucid`, `muse-tmr`, `remind-eeg` and `muse_tmr` (notes/gap_2 A7, re-checked 2026-10-23). `requires-python = ">=3.8"` (line 16), classifiers 3.8–3.12 (lines 23–27) and the README badge (line 7) promise five Pythons, but `.github/workflows/guardrails.yml` pins `python-version: "3.11"` on `ubuntu-latest` in all four jobs (lines 16, 28, 44, 61). The `docs` extra (lines 67–71) builds nothing (no `docs/conf.py`), `requirements-viz.txt` is referenced nowhere, `setup.py` and `run_tests.py` (lines 3, 93, 101) still say "Amused". The wheel ships 16 top-level `py-modules` (lines 86–103), among them `amused.py`, this repository's own shim ("until the project has a package-layout migration", lines 1–5), which shares its import name with the upstream PyPI package `amused` 1.0.2, so a plain install would shadow or overwrite it (inferred from the module list, not tested). The engine imports these modules at `src/muse_tmr/sources/amused_source.py` lines 13–14, 26, 248, `data/recorder.py` line 16, `data/replay.py` lines 11–12 and `validation/pilot4.py` line 13; 14 test files and 8 `examples/*.py` do too. `TEST_STATUS.md` lines 4–6 ("724 tests passing", "88% line coverage") are self-reported: CI writes `coverage.xml` (line 36) and uploads nothing (notes/verify_repo_inventory.md A3, A4, B2). There is no `CITATION.cff`, `CONTRIBUTING.md`, `ROADMAP.md` or issue/PR template; `README.md` line 185 asks readers to cite upstream amused-py and offers nothing for REMind.

The one safety item: `create_audio_backend()` (`src/muse_tmr/audio/audio_player.py` lines 297–301) maps `system` to `MacOSAfplayBackend` when `shutil.which("afplay")` succeeds, else to `DryRunAudioBackend`. `run_pilot4_cueing_night` (`validation/pilot4.py` line 313) builds the player from `config.audio_backend_name` without checking the result; the requested name goes to `metadata.json` (line 708), the resolved one only to the summary (line 586), so a Pilot 4/5 night started with `--backend system` off macOS is silent and still passes ("An empty cue night can still pass", `docs/pilot4_low_volume_cueing.md` line 124). The Pilot 2 ladder relies on `play-test-cue --backend system` (`docs/pilot2_audio_calibration.md` line 31; parser default `system`, `cli/main.py` lines 227–232). Code over notes: the fallback is logged as `backend_name` in `audio_playback.jsonl` (VRI C3); it is inaudible, not invisible.

Evaluators judge installability: ezscore-f "were not evaluated due to installation incompatibilities" (Parry & Briganti 2026, medRxiv, https://www.medrxiv.org/content/10.64898/2026.06.01.26354591v1.full). Reused sleep tools pair a permissive licence with pip, a DOI and disclosed versions: YASA (Vallat & Walker 2021, eLife), Portiloop (Valenchon et al. 2022, PLoS ONE), Dreamento (Jafarzadeh Esfahani et al. 2023, SoftwareX), sleepecg (JOSS 2023), pyRiemann's Zenodo DOI (notes/wearable_rem_physiology_open_science.md KQ8). Of the repositories inspected, no open cueing engine is pip-installable with a citation file: Dreamento, the closest, has a paper and MIT but is clone-only, Python 3.6/TensorFlow 1.13.1, ZMax plus Windows HDServer, unpushed since 2024-03-18; EazzZyLearn_pc ships `requirements.txt` and a Windows Nuitka recipe, no tests, CI or package metadata (notes/gap_1 §7); the pip-installable Muse projects (muse-lsl, BrainFlow, OpenMuse) are streamers. Uniqueness 2/5: hygiene. A one-line install reaches people looking for a product, so the install path must say "n = 1 research software, not a medical device". No efficacy claim is made.

## Scope

Four PRs, in order.

PR A, packaging and CI:
- [ ] `pyproject.toml`: `name = "remind-eeg"`; keep `[project.scripts] muse-tmr` (line 56) and the `muse_tmr` import; `requires-python` and classifiers narrowed to what the matrix passes (target 3.9–3.13); drop the `docs` extra; add a `Changelog` URL. Delete `requirements-viz.txt`; fix "Amused" in `setup.py`, `run_tests.py`; README lines 7, 37.
- [ ] `.github/workflows/guardrails.yml`: `tests` and `package` as a `fail-fast: false` matrix, Python 3.9–3.13 × ubuntu/macos/windows; `policy` and `page` stay single; upload `coverage.xml` as an artifact and print the total; platform-specific tests skipped with a named reason.
- [ ] `.github/workflows/release.yml` (new): on `v*` tags build sdist and wheel, run `scripts/check_wheel.py` and `muse-tmr --version` from the wheel, assert tag == `muse_tmr.__version__`, attach `dist/*` to the GitHub release, publish with `pypa/gh-action-pypi-publish` (trusted publishing, `id-token: write`, environment `pypi`), the publish step gated on repository variable `PYPI_PUBLISH == 'true'`.
- [ ] `docs/release.md` (new): version bump in `src/muse_tmr/__init__.py`, `CHANGELOG.md`, `CITATION.cff`, tag, CI, PyPI (yank-only), Zenodo. `docs/USAGE.md` lines 36–46 gain `pip install remind-eeg` ("after the first release").
- [ ] `tests/test_packaging.py` (new, text-based so it runs on 3.9): distribution and script names, `requires-python` floor equals the lowest classifier, every classifier is in the matrix, `CITATION.cff` version equals `__version__`, no top-level `amused` in `py-modules`.

PR B, namespace:
- [ ] `src/muse_tmr/ble/` (new): `git mv` the 15 `muse_*.py` modules, rewrite cross-imports, update the 8 engine import lines above, `tests/record_test_data.py`, the 14 test files, the 8 examples; `scripts/check_wheel.py` additionally fails on any top-level `amused*` entry.
- [ ] Shims for one minor version: the 15 top-level `muse_*.py` become re-exports with a `DeprecationWarning` naming `muse_tmr.ble`, kept in `py-modules` until 0.5; `amused.py` re-exports from `muse_tmr.ble`, stays in the checkout for `examples/`, leaves `py-modules` now. `tests/test_minimal.py` line 103 asserts the warning.
- [ ] `scripts/install_macos_launcher.py` line 226 and `docs/USAGE.md` line 119 drop `$REPO_ROOT` from `PYTHONPATH`; update `AGENTS.md` Repository Shape, `docs/architecture.md` line 15, `docs/amused_upstream.md`, `docs/dependency_strategy.md`, `CHANGELOG.md`.

PR C, citation and governance:
- [ ] `CITATION.cff` (1.2.0, software, REMind, Yuriy Mikityuk, version, date-released, repository-code, MIT, a `references` entry for amused-py by Adrian Tadeusz Belmans at https://github.com/Amused-EEG/amused-py, `doi` left for Zenodo); `cffconvert --validate` in the `policy` job, pinned in the `dev` extra.
- [ ] `README.md`: "Install" and "How to cite" (DOI "pending"); `muse-tmr --help` epilog and `muse-tmr status` print "REMind <version>: n = 1 research software, not a medical device" (test in `tests/test_cli.py`).
- [ ] `CONTRIBUTING.md` (dev setup, `run_tests.py` vs `--all` vs pytest, page check, data and SDK policy, no-efficacy-claims rule, attachment sanitisation: never raw files, device identifiers or dream text, pointers to `AGENTS.md` and `docs/release.md`); `ROADMAP.md` (dated; opens with the honest status: one EEG-only night, in-sample thresholds, zero audio nights, #116 and #167 open; the ten initiatives with a state each; standing ask "seek one Muse+PSG night"; EPIC #1's closed sub-issues are tooling, not validation).
- [ ] `.github/ISSUE_TEMPLATE/{bug_report,night_report,feature}.yml` + `config.yml`, `.github/pull_request_template.md` with the `AGENTS.md` checklist; labels `area/*`, `kind/*`, `P1`–`P3` via `gh label create`; two `good first issue`s (`protocol/session_state.py` placeholder; lowest-coverage modules in `TEST_STATUS.md`).

PR D, fail-loud audio preflight:
- [ ] `audio/audio_player.py`: `resolve_audio_backend(name, *, allow_dry_run_fallback=False)` returning `BackendResolution` (`requested`, `resolved`, `fell_back`, `reason`), raising `AudioBackendFallbackError` when `system`/`afplay` resolve to no sound; `create_audio_backend()` unchanged.
- [ ] `validation/pilot4.py`: resolve right after `config.validate()`, before `source.connect()` and any file write; `Pilot4CueingConfig.allow_dry_run_fallback`; `metadata.json` and the summary record requested and resolved names.
- [ ] `cli/main.py`: `--allow-dry-run` on `play-test-cue`, `train-tlr-cue`, `run-pilot4-cueing`, `run-pilot5-full-night` (lines 227–232, 477, 360–365, 410–415); the refusal names the fix and exits 2.
- [ ] Tests in `tests/test_audio_player.py` (`shutil.which` patched; `dry-run`/`mock` never raise), `tests/test_pilot4_cueing.py` (refusal before `connect`, no `metadata.json`; passes with the flag and records both names), `tests/test_cli.py`. Docs: `docs/safety.md` lines 29–33, the Pilot 2/4/5 runbooks' Preflight sections, `docs/USAGE.md` line 287, `docs/data_model.md`, `CHANGELOG.md`.

## Acceptance criteria

- [ ] Every matrix cell of `policy`, `tests`, `package`, `page` is green; `python run_tests.py --all`, `python scripts/check_forbidden_files.py`, `git diff --check` pass.
- [ ] `pip wheel . --no-deps` yields `remind_eeg-*.whl`; `scripts/check_wheel.py` passes; no top-level `amused*` in the wheel; from a clean venv `muse-tmr --version` and `python -c "import muse_tmr.ble.muse_realtime_decoder"` work; `import muse_realtime_decoder` from a checkout warns and works.
- [ ] `tests/test_packaging.py` and `cffconvert --validate` pass in CI; `release.yml` is exercised once with publish gated off (`workflow_dispatch` or a fork tag) and the PR links that run.
- [ ] Fail-loud tests pass; `test_system_backend_falls_back_to_dry_run_without_afplay` still passes; Pilot 3 replay simulation still reports zero uncued `play`.
- [ ] No change to `StableRemGate`, `ArousalGuard`, `TmrCueScheduler`, randomization, the detector or any threshold; uncued puzzles never schedulable; `P_REM` reaches audio only through gate and guard; hard cap 0.20 unchanged.
- [ ] PR descriptions report, not promise: per-cell pass/fail and the final `requires-python`; the coverage total read from the artifact, written into `TEST_STATUS.md` with the run id (replacing the self-reported 88 %); platform tests skipped and why; import sites changed; wheel size and file count.
- [ ] README, `docs/USAGE.md`, `docs/release.md`, `docs/safety.md`, Pilot 2/4/5 runbooks, `CONTRIBUTING.md`, `ROADMAP.md`, `CHANGELOG.md` updated; the banner appears in `--help` and `status`; no efficacy wording added.

## Out of scope

- Cross-platform real-audio backend (`sounddevice`, `aplay`, `winsound`), sleep inhibit, TTS, Linux/Windows launchers or night runner (rejected, notes/strategy_judgement.md).
- Software paper, second maintainer, Discussions, Code of Conduct, ADRs, branch protection, documentation site, plugin registry, public benchmark table (rejected or deferred).
- Wording, LICENSE line, upstream-URL unification, README status block, `docs/compare.md`, `docs/numbers.md`, `configs/` deletion (Initiative 5); `[edf]` extra (6); protocol presets (7); `demo` and synthetic corpus (9); detector, gate or scheduler changes (1–4).
- Publishing to PyPI, minting the DOI, cutting the tag: prepared here, executed by the maintainer.

## Depends on

- Initiative 5 — it edits `LICENSE`, the README status block and the upstream URLs that `CITATION.cff` and "How to cite" must agree with; if unmerged, use `Amused-EEG/amused-py` and reconcile at merge.
- Coordination only: Initiative 6 (`pyproject.toml` `[edf]` extra, `guardrails.yml`) and 9 (end-to-end CI job joins the matrix); whichever merges second rebases. Related: #116, #167 (in `ROADMAP.md`), #183 (origin of `check_wheel.py`).

## Needs from the maintainer

- Register a PyPI trusted publisher for `remind-eeg` (owner `yuriy-mikityuk/remind-eeg`, workflow `release.yml`, environment `pypi`) and set repository variable `PYPI_PUBLISH=true`; needs a PyPI account. Without it the agent merges the workflow gated off and leaves a `needs-maintainer:` comment.
- Enable the Zenodo–GitHub integration and, after the first release, give the agent the concept DOI for `CITATION.cff` and README; needs Zenodo consent. Without it "DOI: pending" stays.
- Cut the release tag (`v0.4.0` or your choice) after the four PRs merge; publishing is irreversible (yank only). Without it everything merges, nothing is released.
- On the Mac, run `muse-tmr play-test-cue --backend system` once after PR D: CI's macOS runner proves `afplay` exists, not that sound comes out. If `gh label create` is refused, create the labels in repository settings.

## Files

`pyproject.toml`, `setup.py`, `run_tests.py`, `requirements-viz.txt` (deleted), `amused.py`, `muse_*.py` (15 shims), `src/muse_tmr/ble/*` (new), `src/muse_tmr/{sources/amused_source.py, data/recorder.py, data/replay.py, validation/pilot4.py, audio/audio_player.py, audio/__init__.py, cli/main.py}`, `.github/workflows/{guardrails.yml, release.yml}`, `.github/ISSUE_TEMPLATE/*`, `.github/pull_request_template.md`, `CITATION.cff`, `CONTRIBUTING.md`, `ROADMAP.md`, `README.md`, `AGENTS.md`, `CHANGELOG.md`, `TEST_STATUS.md`, `scripts/{check_wheel.py, install_macos_launcher.py}`, `tests/{test_packaging.py (new), test_minimal.py, test_audio_player.py, test_pilot4_cueing.py, test_cli.py, record_test_data.py}` plus the other 13 tests importing BLE modules, `examples/*.py`, `docs/{release.md (new), USAGE.md, safety.md, architecture.md, amused_upstream.md, dependency_strategy.md, data_model.md, pilot2_audio_calibration.md, pilot4_low_volume_cueing.md, pilot5_full_night.md}`.

## Evidence

- docs/research/2026-10-uniqueness/report.md: "### 8. Сделать проект устанавливаемым, цитируемым и управляемым"; "Где собственные заявления репозитория не подкреплены данными".
- docs/research/2026-10-uniqueness/notes/: strategy_judgement.md (§8, "Rejected or deferred"), strategy_science.md §7, strategy_technical.md Initiative 8 step 2, strategy_community.md Initiatives 2 and 7, verify_repo_inventory.md A3, A4, A10, A15, B2, B3, C2, C3, gap_2 A7, gap_1 §7, wearable_rem_physiology_open_science.md KQ8, muse_ecosystem.md KQ5.
- Tooling: https://docs.pypi.org/trusted-publishers/; https://citation-file-format.github.io/; https://docs.github.com/en/repositories/archiving-a-github-repository/referencing-and-citing-content; https://pypi.org/pypi/amused/json; https://github.com/Amused-EEG/amused-py.
- Papers and repositories: Parry & Briganti 2026 (above); YASA https://elifesciences.org/articles/70092; Portiloop https://pmc.ncbi.nlm.nih.gov/articles/PMC9394839/; Dreamento https://doi.org/10.1016/j.softx.2023.101595 and https://github.com/dreamento/dreamento; sleepecg https://joss.theoj.org/papers/10.21105/joss.05411; https://github.com/SoftcodingForYou/EazzZyLearn_pc; https://github.com/alexandrebarachant/muse-lsl; https://github.com/brainflow-dev/brainflow; https://github.com/DominiqueMakowski/OpenMuse.
