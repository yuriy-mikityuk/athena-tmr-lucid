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
