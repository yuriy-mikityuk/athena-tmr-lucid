# Unified Muse Data Model

`muse_tmr.data.sample_types` defines the common frame format used by live sources, recorders, replay, feature extraction, and future REM detection.

## Units

- `MuseFrame.timestamp`: Unix epoch seconds as a float.
- `EEGSample.channels_uv`: microvolts per channel. Values are stored as sample arrays, even when a packet contains a single sample.
- `IMUSample.accelerometer_g`: acceleration in g, keyed by `x`, `y`, and `z`.
- `IMUSample.gyroscope_dps`: angular velocity in degrees per second, keyed by `x`, `y`, and `z`.
- `PPGSample.channels`: raw optics values from the Muse protocol decoder.
- `HeartRateSample.bpm`: beats per minute.
- `BatterySample.percent`: battery percentage.
- `MuseFrame.raw_packet`: optional raw BLE packet bytes, serialized as `raw_packet_hex`.

Missing modalities are valid. A frame may contain only EEG, only IMU, only PPG, or any combination available from a packet.

## Serialization

Each sample type supports `to_dict()` and `from_dict()`. `MuseFrame` additionally supports `to_json()` and `from_json()`. Raw bytes are encoded as hex so frame JSON remains portable.

## Source Attribution

Every sample and frame carries a `source` string. The amused-py adapter uses `amused`; future OpenMuse and SDK adapters should use distinct source names.

## Offline Replay

`muse_tmr.data.replay.ReplaySession` reads a recording directory or `raw_amused.bin`,
decodes raw packets through the same TAG decoder used by live streaming, and emits
`MuseFrame` objects for downstream epoch building and feature extraction.

Replay speed is explicit:

- `speed=1.0` preserves real-time packet spacing.
- `speed>1.0` accelerates replay.
- `speed=0.0` disables sleeps for tests and batch processing.

`start_seconds` and `end_seconds` are relative to the raw recording start, allowing
feature code to replay a specific sleep segment without loading unrelated packets.

## Sleep Epochs

`muse_tmr.features.epochs.EpochBuilder` consumes any async stream of `MuseFrame`
objects, including live `AmusedSource.stream()` and offline `ReplaySession.stream()`.
The default configuration builds 30-second epochs with a 30-second stride. Strides
of 5 or 10 seconds create overlapping windows for smoother downstream REM features.

Each `SleepEpoch` contains:

- `frames`: frames inside `[start_time, end_time)`.
- `modality_counts`: number of frames carrying each modality.
- `sample_counts`: estimated sample totals per modality.
- `coverage`: observed samples divided by expected samples for EEG, IMU, PPG, and HR.
- `quality_flags`: `missing_*` or `low_*_coverage` flags instead of exceptions.

Default expected rates are EEG 256 Hz, IMU 52 Hz, PPG 64 Hz, and HR 1 Hz.

## EEG Feature Rows

`muse_tmr.features.eeg_features.extract_eeg_features()` converts one `SleepEpoch`
into an `EEGFeatureRow`. `extract_eeg_feature_rows()` handles an iterable of epochs,
and `export_eeg_feature_rows()` writes `.csv`, `.parquet`, or `.pq` through pandas.

Current EEG features include:

- absolute and relative band powers for delta, theta, alpha, beta, and gamma
- theta/alpha, delta/beta, and slow/fast ratios
- frontal and posterior alpha asymmetry
- frontal theta asymmetry
- a simple frontal eye-movement proxy from AF7-AF8 changes
- artifact flags for missing EEG, low coverage, flatline, clipping, and non-finite channels

Feature rows carry epoch timing, channel counts, sample counts, coverage, and quality
flags so downstream REM detectors can filter noisy epochs before inference.

## IMU Feature Rows

`muse_tmr.features.imu_features.extract_imu_features()` converts one `SleepEpoch`
into an `IMUFeatureRow`. `extract_imu_feature_rows()` handles an iterable of epochs,
and `export_imu_feature_rows()` writes `.csv`, `.parquet`, or `.pq` through pandas.

Current IMU features include:

- dimensionless `motion_level` from accelerometer delta and gyroscope magnitude
- `stillness_score` as the quiet sample fraction inside the epoch
- accelerometer RMS/peak delta from the epoch baseline magnitude
- gyroscope RMS/peak angular velocity
- grouped movement events with duration, peak motion, and arousal-proxy flag
- `arousal_guard_reason_codes` for downstream cue safety decisions
- cue-window movement logs when cue timestamps are supplied per epoch
- artifact flags for missing IMU, low coverage, missing axes, and non-finite values

IMU rows preserve noisy epochs and expose guard reasons instead of dropping data.
Future cue schedulers can turn `arousal_guard_reason_codes` into a `CueDecision`
through `muse_tmr.protocol.tmr_scheduler.arousal_guard_decision()`.

## PPG/HR/HRV Feature Rows

`muse_tmr.features.ppg_features.extract_ppg_features()` converts one `SleepEpoch`
into a `PPGFeatureRow`. `extract_ppg_feature_rows()` handles an iterable of epochs,
and `export_ppg_feature_rows()` writes `.csv`, `.parquet`, or `.pq` through pandas.

Current PPG/HR features include:

- PPG-derived heart-rate estimate from the strongest optics channel when raw PPG is present
- mean, median, min, max, and trend for `HeartRateSample.bpm`
- HRV proxy metrics: mean RR, SDNN, RMSSD, and pNN50
- sudden HR-change logs from adjacent heart-rate samples
- source fields showing whether HR/HRV came from PPG peaks, heart-rate samples, or missing data
- artifact flags for missing PPG, low coverage, flatline, non-finite values, and out-of-range HR

Raw PPG and heart-rate samples are optional. Missing modalities must produce flags and
`NaN` feature values where needed, not exceptions.

## REM Predictions

`muse_tmr.models.heuristic_rem_detector.HeuristicRemDetector` is the first non-ML
REM baseline. It can consume a `SleepEpoch` directly or precomputed EEG, IMU, and
PPG feature rows.

Each `RemPrediction` contains:

- `probability`: `P_REM` clamped to 0-1
- `reason_codes`: support, missing-feature, low-coverage, and guard-related explanations
- `feature_scores`: normalized heuristic component scores
- `feature_values`: raw feature values used by the heuristic
- `source`: currently `heuristic`

The REM detector does not play audio and does not return `CueDecision`. Stable gates,
cooldowns, arousal guards, and cue scheduling remain separate downstream layers.

## REM Annotation Rows

`muse_tmr.annotations.rem_annotations` defines manual annotation rows for later REM
classifier training. Valid labels are:

- `wake`
- `nrem`
- `probable_rem`
- `unknown`

`muse-tmr annotate-template <recording> --output <labels.csv|labels.json>` replays a
recording, builds epochs, runs the heuristic REM detector, and exports an editable
annotation template. Each row includes epoch timing, `label`, `notes`, `P_REM`, reason
codes, normalized feature scores, and raw feature values. The default label is
`unknown` so the file can be created before manual review.

`load_rem_annotations()` validates labels from CSV or JSON. `rem_training_rows()`
returns training-ready rows and excludes `unknown` labels by default.

## Personal REM Models

`muse_tmr.models.ml_rem_detector` trains a personal REM classifier from labeled
annotation rows. The default model is a small class-balanced logistic classifier over
the annotation feature columns, so it stays dependency-light and can be trained from
manually labeled nights.

`muse-tmr train-rem-classifier <labels.csv|labels.json> --output <model.json>` writes a
versioned JSON artifact with:

- feature names, means, scales, coefficients, and calibration intercept
- feature importance based on normalized coefficient magnitude
- training metrics, Brier/log-loss calibration metrics, and calibration bins
- optional leave-one-recording-out metrics when multiple recording IDs are present

`probable_rem` is the positive class. `wake` and `nrem` are negative classes.
`unknown` rows are skipped. A loaded `PersonalRemModel` returns `RemPrediction` with
`source="personal"` and remains separate from cue playback decisions.

## REM Stable Gate

`muse_tmr.models.rem_gate.StableRemGate` converts a stream of `RemPrediction` values
into a stateful REM gate decision. The gate keeps REM detection separate from cue
playback: it only emits `RemGateDecision`, never `CueDecision` or audio calls.

Each decision contains:

- `gate_open`: true only after stable REM confidence exceeds the entry threshold for
  the configured stability window
- `state`: `closed`, `warming`, `open`, or `blocked`
- `confidence`: the original `P_REM`, capped confidence, active threshold, source, and
  prediction reason codes
- `stable_seconds`: consecutive stable REM time tracked by the gate
- `cooldown_remaining_seconds`: remaining cooldown after motion/arousal blocks
- `reason_codes`: threshold, stability, hysteresis, cooldown, and block reasons

Default behavior uses an entry threshold of `0.70`, exit threshold of `0.45`, a
60-second stability window, and a 120-second cooldown. Motion/arousal reason codes
close the gate and start cooldown. Low feature-support reason codes cap confidence so
single high-probability spikes do not open the gate by themselves.

## Audio Playback

`muse_tmr.audio.audio_player.AudioCuePlayer` is the low-volume playback facade for
sleep cues. It does not inspect REM probabilities or make cue eligibility decisions;
M4/M5 protocol code must call it only after stable gate and safety layers allow a cue.

`muse-tmr play-test-cue` plays or dry-runs a generated test tone. The playback request
captures:

- cue ID, frequency, and duration
- requested volume, effective capped volume, and max-volume cap
- fade-in/fade-out seconds
- optional device name metadata
- backend name and reason codes

`CuePlaybackResult` records `played`, `skipped`, `blocked`, or `stopped` outcomes and
can be appended to a JSONL log. The default `system` backend uses macOS `afplay` when
available and otherwise falls back to `dry-run`; tests use `MockAudioBackend` so CI does
not need an audio device.

## Volume Calibration

`muse_tmr.audio.volume_calibration.VolumeCalibration` stores the pre-sleep audible
thresholds for one playback device:

- `detectable_volume`: lowest volume the subject can notice
- `identifiable_volume`: lowest volume the subject can recognize as the intended cue
- `comfortable_volume`: highest volume accepted for sleep-time scheduling
- cue/backend metadata, timestamp, and optional notes

`VolumeCalibrationStore` writes versioned JSON metadata with a `calibrations` array.
Saving a new calibration for the same `device_name` replaces the prior record for that
device while preserving other devices. `muse-tmr calibrate-volume --output <file>`
creates or updates this metadata.

Scheduler-facing code should use `comfortable_volume` through
`calibrated_max_volume()` or `calibrated_cue_decision()`. The resulting max remains
bounded by the configured hard cap, and missing calibration should block planned
sleep-time cue sessions rather than falling back to an unverified speaker level.

## Cue Libraries

`muse_tmr.audio.cue_library.CueLibrary` stores cue metadata in JSON without committing
private audio files. A cue has:

- `cue_id`: stable identifier used by protocol and scheduler layers
- `cue_type`: `sound`, `generated_tone`, or `silence`
- `protocol`: `puzzle`, `tlr`, `test`, or `generic`
- `duration_seconds`, tags, optional description, and optional volume hint
- `path` for private sound files or `frequency_hz` for generated tones

`muse-tmr create-cue-library --output <catalog.json>` creates a starter metadata
catalog with puzzle, TLR, and silence-control cues. `validate-cue-library` checks
metadata and, by default, verifies that `sound` cue paths exist relative to the catalog
directory before a session starts. `list-cues` filters by protocol or tag.

Private cue files should live under gitignored folders such as `cues/private/`,
`data/cues/private/`, or `data/cues/audio/`. Commit cue metadata only when it does not
include private labels or personal audio paths.

## Puzzle Protocol

`muse_tmr.protocol.puzzle_protocol` defines versioned JSON records for the pre-sleep
puzzle workflow:

- `PuzzleCatalog`: puzzle tasks plus timed pre-sleep attempts
- `PuzzleTask`: puzzle ID, prompt, solution, cue ID, source/tags, and solved/known/retired flags
- `PuzzleAttempt`: response, duration, solved flag, known-after flag, timestamps, and notes
- `NightPuzzleSession`: generated session ID, selected puzzle IDs, seed, and association results
- `AssociationResult`: cue ID, response, expected solution, normalized match flag, timestamp, and notes

`muse-tmr import-puzzles` accepts CSV or JSON rows and writes a catalog. `muse-tmr
generate-puzzle-session` filters solved, known, and retired tasks and selects four
eligible unsolved puzzles by default. `record-puzzle-attempt` appends timed pre-sleep
attempts to the catalog, and `record-association-check` appends cue-to-solution checks
to the generated night session.

## Puzzle Cue Assignments

`muse_tmr.protocol.randomization.PuzzleCueAssignment` stores reproducible cued vs
uncued assignment for one `NightPuzzleSession`:

- `session_id` and randomization `seed`
- `cued_puzzle_ids`
- `uncued_puzzle_ids`
- derived `scheduled_puzzle_ids`, which contains only cued puzzle IDs
- generation timestamp and metadata

`muse-tmr assign-puzzle-cues <session.json> --seed <n> --output <assignment.json>`
splits half of the session puzzles into the cued group by default. The assignment must
cover exactly the session puzzle IDs with no overlap. Scheduler code should call
`scheduled_puzzle_ids` or `scheduled_cue_ids(catalog)` so uncued controls are never
eligible for cue playback.

## TLR Protocol

`muse_tmr.protocol.tlr_protocol` defines versioned records for targeted lucidity
reactivation:

- `TlrCueConfig`: default generated cue settings
- `TlrTrainingConfig`: pre-sleep repetition count, interval, volume, and backend name
- `TlrTrainingSession`: training summary with one event per cue presentation
- `TlrTrainingEvent`: playback status, requested/effective volume, reason codes, and scheduled offset
- `TlrBlockConfig`: REM block repetitions, interval, post-block pause, and enabled flag
- `TlrBlockPlan`: cue offsets and `puzzle_cue_start_offset_seconds`

`muse-tmr create-tlr-cue` writes a `CueLibrary` containing a generated TLR cue.
`train-tlr-cue` plays or dry-runs the cue through `AudioCuePlayer` and writes both a
summary JSON and JSONL training events. `plan-tlr-block` writes the TLR block that
future scheduler code should insert before puzzle cues when the REM gate opens.

## TMR Scheduler Events

`muse_tmr.protocol.tmr_scheduler.TmrCueScheduler` emits `TmrSchedulerEvent` records:

- `event_type`: `play`, `skip`, `pause`, or `stop`
- `timestamp_seconds`: replay/session-relative time
- optional `cue_id`, `protocol`, and `puzzle_id`
- `reason_codes`
- metadata such as duration, volume hint, next allowed cue time, or cooldown end time

The scheduler consumes `RemGateDecision`, `PuzzleCueAssignment`, `PuzzleCatalog`,
`CueLibrary`, and optional `TlrBlockPlan`. It uses only `scheduled_puzzle_ids` from
the assignment, so uncued puzzle controls are not eligible for playback. Events can be
appended to JSONL with `append_tmr_scheduler_events()` and read with
`load_tmr_scheduler_events()`.

## Arousal Guard Decisions

`muse_tmr.protocol.arousal_guard.ArousalGuard` emits `ArousalGuardDecision` records:

- `action`: `allow`, `lower_volume`, `pause`, or `stop`
- `timestamp_seconds`: replay/session-relative time
- `reason_codes`: motion, alpha, HR-jump, or artifact-quality explanations
- `volume_multiplier`: multiplier for lower-volume cue events
- `pause_seconds`: requested pause duration for pause decisions
- `metadata`: feature values, artifact flags, and consecutive guard counters

Decisions can be appended to JSONL with `append_arousal_guard_decisions()` and read
with `load_arousal_guard_decisions()`. The scheduler can consume a decision directly;
`lower_volume` scales cue event volume hints, `pause` records a pause and cooldown, and
`stop` records a stop event.

## Dream Reports

`muse_tmr.reports.dream_report` defines versioned morning dream report records:

- `DreamReport`: session ID, lucid yes/no, cues-heard yes/no, confidence, free-text
  dream recall, notes, metadata, and puzzle incorporation links
- `DreamPuzzleIncorporation`: puzzle ID, optional cue ID, dream-content excerpt, and
  link confidence

`build_dream_report()` validates links against `NightPuzzleSession` and can enrich links
with cue IDs from `PuzzleCatalog`. `muse-tmr record-dream-report` writes the report JSON.
Dream text and puzzle-link excerpts are private morning data and should stay in
gitignored report locations.

## Morning Retests

`muse_tmr.reports.morning_retest` defines versioned morning puzzle retest records:

- `MorningRetest`: session ID, result counts, solved/unsolved counts, mean duration,
  notes, metadata, and per-puzzle results
- `MorningRetestResult`: puzzle ID, cue ID, blind order, `cue_condition`, response,
  solved flag, duration, confidence, and notes

`build_morning_retest()` validates results against `NightPuzzleSession`, enriches cue
IDs from `PuzzleCatalog`, and stores cued/uncued condition from `PuzzleCueAssignment`
for analysis. `muse-tmr record-puzzle-retest` writes the retest JSON. The retest should
be administered blind; `cue_condition` is for downstream analysis, not subject-facing
prompts.

## Cued-vs-Uncued Analysis

`muse_tmr.reports.analysis` defines versioned analysis records:

- `CuedUncuedAnalysisReport`: session ID, per-puzzle rows, condition metrics, effect
  summary, cue timing summary, limitations, and metadata
- `PuzzleAnalysisRow`: puzzle ID, cue condition, retest solved/duration/confidence,
  dream incorporation flag, and scheduler puzzle cue timing
- `ConditionMetrics`: cued or uncued group counts, solve rate, incorporation rate,
  mean duration/confidence, and cue play counts

`build_cued_uncued_analysis()` validates `NightPuzzleSession`, `PuzzleCueAssignment`,
`MorningRetest`, and optional `DreamReport`; scheduler events are optional but used to
audit puzzle cue timing. The output is descriptive only and includes machine-readable
limitations such as `small_n`, `missing_scheduler_events`, or `uncued_cue_play_observed`.

Puzzle protocol files may contain private puzzle content, responses, and night/session
metadata, so `data/protocol/` is gitignored.
