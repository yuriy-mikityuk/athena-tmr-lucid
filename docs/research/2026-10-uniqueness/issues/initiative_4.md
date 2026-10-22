# Initiative 4: Sham and no-cue nights, N-of-1 blocks, delayed retest, blind incorporation coding and SCRIBE/CENT export

## Why

Item-level control exists: `ensure_schedulable()` (`src/muse_tmr/protocol/randomization.py` lines 83–88) makes uncued puzzles unschedulable, `_scheduled_puzzles()` builds cues only from `scheduled_puzzle_ids` (`src/muse_tmr/protocol/tmr_scheduler.py` lines 478–490), and the Morning tab never learns `cue_condition` (`src/muse_tmr/app/morning.py` lines 8, 204–222). Night-level control does not: at HEAD `083649b` nothing under `src/` or `docs/` (outside `docs/research/`) defines a `sham`, `no_cue`, `nof1`, `retest_wave` or `rater` field; `TmrSchedulerEvent` has no arm field (`tmr_scheduler.py` lines 80–87); `MorningRetest` knows one wave (`src/muse_tmr/reports/morning_retest.py` line 85); `DreamReport` has no sound-awakening, cue-perception or rater fields (`src/muse_tmr/reports/dream_report.py` lines 17–23, 57–68); and the seven codes of `_limitations()` (`src/muse_tmr/reports/analysis.py` lines 469–558) say nothing about arms, blinding or delayed testing. Every cued-vs-uncued delta is confounded with "a night on which sounds played".

The one randomised, participant-blind home TLR study interleaved untrained-sound and no-cue nights with TLR nights (F(1,118) = 6.28, p = .01; no-cue vs TLR p = .77; Konkoly et al. 2024, Consciousness and Cognition, https://pmc.ncbi.nlm.nih.gov/articles/PMC11542932). Konkoly et al. 2026 (Neuroscience of Consciousness, https://academic.oup.com/nc/article/2026/1/niaf067/8456489) list "no no-cue night" and incomplete blinding as limitations; blind-coded conceptual incorporation (β = 1.24, p = .037), not cueing (30 % vs 22 %, p > .6), predicted solving. REM-TMR effects appeared only at one week (d = 0.646; Pereira et al. 2023, J Neurosci, https://pmc.ncbi.nlm.nih.gov/articles/PMC10218979/) or ten days (Rakowska et al. 2021, NeuroImage, https://pmc.ncbi.nlm.nih.gov/articles/PMC8591408/). A sham-controlled multi-centre preprint found induction no different from sham, with cues perceived in 71.1 % of cued REM periods (Picard-Deland et al. 2024, bioRxiv v2 2026, https://www.biorxiv.org/content/10.1101/2024.06.21.600133v2.full). SCRIBE 2016 (Tate et al. 2016, https://pmc.ncbi.nlm.nih.gov/articles/PMC4960517/) and N-of-1 analysis with carry-over and autocorrelation (Schmid & Yang 2022, HDSR, https://hdsr.mitpress.mit.edu/pub/b6efwlql; Konigorski et al. 2026, Exp Physiol, https://doi.org/10.1113/EP092753) give the reporting frame; no N-of-1 TMR/TLR study was found (docs/research/2026-10-uniqueness/notes/tmr_tlr_science.md KQ7).

Of the repositories inspected, none seals night arms over physiology-gated cues: COsleep only obfuscates sham/stim and is stale since 2023, Taran-Douley plans sham nights, brainwave_opensync randomises blinded n-of-1 blocks without physiology (notes/cueing_tools_landscape.md KQ4; notes/gap_1_direct_open_source_competitor_softcoding.md §9). Nothing here measures efficacy: at n = 1 the experimenter cannot be blind, a sham still makes sound, the untrained sound may be recognised, and every output is a single-case description.

## Scope

- [ ] `src/muse_tmr/protocol/night_schedule.py` (new): arms `cue`, `sham`, `no_cue`, `washout`; `generate_night_schedule(seed, blocks, washout_nights)` counterbalanced per block; a `NightSchedule` JSON plus a sealed companion holding only `commitment_sha256` over canonical JSON and a random salt; `arm_for(night_id)`, `unseal()` writing `unsealed_at_utc`, `prereg_template()` rendering OSF-style Markdown from schedule, commitment and Initiative 7's manifest hash. CLI `plan-night-schedule`, `show-night-schedule`, `unseal-night-schedule`, `prereg-template` in `src/muse_tmr/cli/main.py`.
- [ ] Scheduler: `TmrSchedulerConfig.arm` and `sham_cue_id`; `TmrSchedulerEvent.arm` (default `cue`). In `sham` the scheduler substitutes `sham_cue_id` for puzzle and TLR cues, keeps `puzzle_id`, adds reason `sham_arm`, changes nothing else; in `no_cue` every would-be `play` becomes `skip` with reason `no_cue_arm` and `metadata.virtual_play = true`, and `_record()` raises on a `play`. `ensure_sham_untrained()` raises when the sham `cue_id` equals a catalog puzzle `cue_id` or a TLR training cue; `default_cue_library()` in `src/muse_tmr/audio/cue_library.py` gains `sham_soft_tone` (protocol `sham`, tag `untrained`).
- [ ] Runners: `--arm`, `--night-schedule`, `--night-id`, `--sham-cue-id` on `simulate-replay-cues`, `run-pilot4-cueing`, `run-pilot5-full-night`; `CuePlaybackResult.arm` (`src/muse_tmr/audio/audio_player.py`) in `audio_playback.jsonl`; `_play_scheduler_event` in `src/muse_tmr/validation/pilot4.py` refuses playback outside `cue`/`sham`; summaries gain `arm`, `night_id`, `schedule_commitment_sha256` and criteria `arm_matches_sealed_schedule`, `no_play_in_no_cue_arm` in `pilot3.py` and `pilot4.py`; the runner never prints the arm.
- [ ] Morning: `DreamReport` v2 adds `woke_from_sound` (yes/no/unknown), `cue_perception` (`not_perceived`, `in_dream`, `awake`, `unsure`, `unknown`) and `eye_signal_attempt_times` (LRLR-ready marking only); `MorningRetest` v2 adds `retest_wave` (`morning`, `day7`, `day10`) and `record-puzzle-retest --wave`; the Morning tab (`morning.py`, `app/static/index.html`, `app.js`) gets both items and a wave selector saving `<night>_retest_<wave>.json` for delayed waves.
- [ ] `src/muse_tmr/reports/incorporation_coding.py` (new): `export_blind_coding_packet()` (dream text and puzzles in `blind_index` order, nothing about cues or arm), `IncorporationCoding(rater_id, puzzle_id, sound_cue, direct_conceptual, indirect_conceptual, notes)`, `coding_agreement()` (percent agreement, Cohen's κ per category, pure Python); CLI `export-blind-coding`, `record-incorporation-coding`, `compare-incorporation-codings`.
- [ ] `analysis.py`: repeatable `--retest`, metrics and deltas per wave, `missing_delayed_retest`, an incorporation × solved cross-tab, rater codes preferred over self-links.
- [ ] `src/muse_tmr/reports/nof1_analysis.py` (new) and `analyze-nof1`: per-arm descriptives (lucidity, cue perception, awakenings, incorporation, cue counts, Initiative 3's `arousal_proxy_per_cue` when present, cued-minus-uncued delta per wave), first-night flags, lag-1 autocorrelation, a seeded within-block permutation difference with interval, limitations `single_subject`, `no_sham_nights`, `no_no_cue_nights`, `unbalanced_arms`, `unblinded_early`, `sham_detectable`, `carry_over_possible`, `first_night_effect_possible`, `missing_delayed_retest`, `missing_arousal_scoring`, `small_n`; Markdown with a SCRIBE 2016 / CENT 2015 checklist marking each item `auto`, `partial` or `manual`.
- [ ] Docs: new `docs/nof1_protocol.md` runbook; `docs/USAGE.md`, the three pilot runbooks (Pilot 5: do not open the summary before the morning forms), `docs/protocol.md`, `docs/validation.md`, `docs/data_model.md`, `README.md`, `CHANGELOG.md`, one `AGENTS.md` bullet.
- [ ] Tests: new `tests/test_night_schedule.py`, `test_incorporation_coding.py`, `test_nof1_analysis.py`; existing scheduler, Pilot 3/4 (mock backend), morning, analysis and CLI tests extended; all in `run_tests.py`.

## Acceptance criteria

- [ ] `python run_tests.py --all` and the four CI jobs (`policy`, `tests`, `package`, `page`) pass.
- [ ] A replayed synthetic night under `no_cue` yields zero scheduler `play` events and zero `status == "played"` rows in `audio_playback.jsonl`, with `virtual_play` skips where the `cue` arm plays; the same seed under `cue` and `sham` gives identical timestamps and volumes, differing only in `cue_id` and `arm`.
- [ ] Uncued puzzles stay unschedulable in every arm (`no_uncued_puzzle_cues` still passes); a sham `cue_id` equal to a trained cue raises.
- [ ] The scheduler still consumes only `RemGateDecision`; no module under `models/` or `features/` imports `muse_tmr.audio`.
- [ ] The `/api/morning/night` payload text contains none of `arm`, `sham`, `cue_condition`, `cued_puzzle_ids`, `commitment`; arms stay hidden until `unseal-night-schedule` ran, and unsealing is recorded.
- [ ] Schema-1 files load unchanged; `run-pilot5-full-night` without `--arm` behaves as today.
- [ ] The PR description reports, labelled "synthetic input, not sleep": the permutation interval on a 12-night synthetic series with and without a planted arm difference, κ for a two-rater synthetic packet, and SCRIBE items filled `auto` vs `manual`.
- [ ] `git diff --check` and `python scripts/check_forbidden_files.py` clean; nothing under `data/` committed; `docs/validation.md` wording rules respected.

## Out of scope

- Automatic LRLR detection (rejected, notes/gap_4 KQ B); the ±60 s AF7−AF8 plot and EDF+ annotation export of eye-signal attempts (follow-up after Initiatives 1 and 6).
- Computing `arousal_proxy_per_cue` (Initiative 3); the preset registry, manifest hash and sound→puzzle manipulation check (Initiative 7); README wording (Initiative 5); the synthetic night corpus (Initiative 9).
- Two-way volume titration, tonic/phasic sub-gate, Bayesian models with external priors, aggregation across participants, power heuristics, any real night.

## Depends on

- Initiative 3: `analyze-nof1` reads its `arousal_proxy_per_cue` output instead of defining a second schema.
- Initiative 7: the preregistration template and night `metadata.json` carry its protocol manifest hash; until it merges the field reads `unknown`.
- Related, not blocking: #116 and #167 (detector weight, first-cue latency); every arm comparison inherits them and the report must say so.

## Needs from the maintainer

- Run a first sealed series (two blocks, real audio, Pilot 5 safety setup) and keep the outputs under `data/`. Why: the agent has no headband, speakers or nights. Without it the agent merges everything on synthetic data and leaves a `needs-maintainer:` comment.
- Optionally have a second person code one exported blind packet; κ on real text needs two raters, otherwise it stays synthetic-tested.

## Files

The modules, pages, tests and docs named in Scope, plus `src/muse_tmr/protocol/__init__.py`, `src/muse_tmr/reports/__init__.py`, `src/muse_tmr/app/server.py`, `run_tests.py`, `README.md`, `CHANGELOG.md`, `AGENTS.md`. Shared with other initiatives: `tmr_scheduler.py`, `pilot3.py`, `pilot4.py`, `cli/main.py`, `docs/USAGE.md`, `docs/validation.md`.

## Evidence

- docs/research/2026-10-uniqueness/report.md: Part 2 "### 4. Добавить sham- и no-cue-ночи…" and Part 1 "Где собственные заявления репозитория не подкреплены данными".
- docs/research/2026-10-uniqueness/notes/: strategy_judgement.md (#4), strategy_science.md (#5, #8), strategy_technical.md (Initiative 5), tmr_tlr_science.md (KQ2, KQ3, KQ6, KQ7), verify_tmr_tlr_science.md (rows 4, 7, 8, 12), cueing_tools_landscape.md (KQ4), verify_cueing_tools_landscape.md (item 3), gap_1_… (§9), gap_4_… (KQ B), repo_inventory.md (KQ4), verify_repo_inventory.md (B4, B8).
- GitHub: #1, #116, #167. Repositories: https://github.com/Frederik-D-Weber/cosleep, https://github.com/Taran-Douley/closed-loop-sleep, https://github.com/occult-kranti/brainwave_opensync.
