"""REM-event feature on band-passed AF7 - AF8 (#225). Synthetic input, not sleep."""

import asyncio
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import sosfilt

from muse_tmr.annotations import build_rem_annotation_rows, load_rem_annotations
from muse_tmr.data.sample_types import EEGSample, MuseFrame
from muse_tmr.features import (
    RemEventConfig,
    RemEventTracker,
    detect_rem_events,
    extract_eeg_feature_rows,
    extract_eeg_features,
)
from muse_tmr.features.rem_event_features import design_bandpass
from muse_tmr.models import HeuristicRemDetector, PersonalRemModel, train_personal_rem_classifier
from muse_tmr.models.ml_rem_detector import DEFAULT_PERSONAL_REM_FEATURES
from tests.rem_event_synthetic import (
    FS,
    LINE_HZ,
    START_TIME,
    build_epochs,
    deflection,
    frames_from_channels,
    frontal_signal,
    rem_deflection_train,
)

SEEDS = (0, 1, 2, 3, 4)
SESSION_SECONDS = 300.0


def session_epochs(channels, *, frames=None, **kwargs):
    frames = frames if frames is not None else frames_from_channels(channels)
    return asyncio.run(build_epochs(frames, **kwargs))


def session_rows(channels, **kwargs):
    return extract_eeg_feature_rows(session_epochs(channels, **kwargs))


def event_times(rows):
    return [time for row in rows for time in row.rem_event_times]


def rem_dense(seed, *, line_uv=40.0):
    return frontal_signal(SESSION_SECONDS, seed=seed, event_count=60, blink_count=20, line_uv=line_uv)


def rem_free(seed, *, line_uv=40.0):
    return frontal_signal(SESSION_SECONDS, seed=seed, line_uv=line_uv)


def eye_path(moves, *, ramp_s=0.05):
    """AF7 - AF8 for a sequence of saccades: (target in µV, hold in s), each reached by a
    raised-cosine ramp from the previous position, then back to 0."""
    ramp = 0.5 * (1 - np.cos(np.pi * np.arange(int(ramp_s * FS)) / int(ramp_s * FS)))
    parts, level = [], 0.0
    for target, hold in tuple(moves) + ((0.0, 0.0),):
        parts.append(level + (target - level) * ramp)
        parts.append(np.full(int(hold * FS), target))
        level = target
    return np.concatenate(parts)


def count_clean(bipolar):
    """Events in ``bipolar`` (AF7 - AF8) after 60 s of 0.01 µV noise, split evenly."""
    lead, tail = np.zeros(int(60 * FS)), np.zeros(int(10 * FS))
    trace = np.concatenate([lead, bipolar, tail])
    noise = 0.01 * np.random.default_rng(0).standard_normal((2, trace.size))
    return len(detect_rem_events(trace / 2 + noise[0], -trace / 2 + noise[1]))


class TestOldProxySaturates(unittest.TestCase):
    def test_old_proxy_scores_one_on_rem_dense_and_rem_free_epochs(self):
        detector = HeuristicRemDetector()
        for line_uv in (40.0, 0.0):
            for signal in (rem_dense(0, line_uv=line_uv), rem_free(0, line_uv=line_uv)):
                for epoch in session_epochs(signal.channels):
                    prediction = detector.predict_features(eeg=extract_eeg_features(epoch))
                    self.assertEqual(prediction.feature_scores["eye_movement_proxy"], 1.0)


class TestFixtureCounts(unittest.TestCase):
    """Five seeded 5 min sessions, 30 s epochs, one tracker each."""

    @classmethod
    def setUpClass(cls):
        cls.dense = {seed: rem_dense(seed) for seed in SEEDS}
        cls.found = {
            (seed, line_uv): event_times(session_rows(rem_dense(seed, line_uv=line_uv).channels))
            for seed in SEEDS
            for line_uv in (40.0, 0.0)
        }

    def test_count_within_20_percent_of_injected_with_and_without_the_line(self):
        for (seed, line_uv), times in self.found.items():
            injected = len(self.dense[seed].event_onsets)
            self.assertLessEqual(abs(len(times) - injected), 0.2 * injected, (seed, line_uv, len(times)))

    def test_the_line_changes_nothing(self):
        for seed in SEEDS:
            with_line, without_line = self.found[seed, 40.0], self.found[seed, 0.0]
            self.assertEqual(len(with_line), len(without_line), seed)
            np.testing.assert_allclose(with_line, without_line, atol=0.01)

    def test_events_sit_on_injected_deflections_not_on_blinks(self):
        for seed in SEEDS:
            signal = self.dense[seed]
            for time in self.found[seed, 40.0]:
                offset = time - START_TIME
                self.assertLess(np.min(np.abs(signal.event_centres - offset)), 1.0, (seed, offset))
                self.assertGreater(np.min(np.abs(signal.blink_centres - offset)), 0.5, (seed, offset))

    def test_about_zero_without_injected_deflections(self):
        for seed in SEEDS:
            found = len(event_times(session_rows(rem_free(seed).channels)))
            self.assertLessEqual(found, 2, seed)

    def test_band_pass_alone_takes_a_40_uv_line_well_below_0_1_uv(self):
        t = np.arange(int(20 * FS)) / FS
        for frequency in (LINE_HZ, 64.0):
            line = 40.0 * np.sin(2 * np.pi * frequency * t)
            filtered = sosfilt(design_bandpass(RemEventConfig()), line)
            self.assertLess(np.max(np.abs(filtered[int(5 * FS) :])), 0.001)

    def test_blinks_do_not_count(self):
        at_blinks_without_veto = 0
        for seed in SEEDS:
            signal = frontal_signal(SESSION_SECONDS, seed=seed, blink_count=40)
            left, right = signal.channels["AF7"], signal.channels["AF8"]
            for event in detect_rem_events(left, right):
                self.assertGreater(np.min(np.abs(signal.blink_centres - event.time)), 1.0, seed)
            unvetoed = detect_rem_events(left, right, config=RemEventConfig(common_mode_veto=False))
            at_blinks_without_veto += sum(
                np.min(np.abs(signal.blink_centres - event.time)) < 1.0 for event in unvetoed
            )
        # Without the veto the residual of the asymmetric blinks in AF7 - AF8 counts.
        self.assertGreater(at_blinks_without_veto, 20)


class TestDeflectionShapes(unittest.TestCase):
    """What one event is, on clean waveforms (0.01 µV of noise, threshold at its floor)."""

    def test_a_deflection_and_its_return_count_once_at_any_size(self):
        for amplitude in (25.0, 50.0, 100.0, 300.0):
            for duration in (0.4, 0.6, 1.0, 1.5):
                self.assertEqual(count_clean(deflection(duration, amplitude)), 1, (duration, amplitude))
            for hold in (0.3, 0.6):
                self.assertEqual(count_clean(eye_path([(amplitude, hold)])), 1, (hold, amplitude))

    def test_saccades_that_stay_out_count_once_each(self):
        for amplitude in (25.0, 300.0):
            # Out, held for 3 s, then back: two saccades.
            self.assertEqual(count_clean(eye_path([(amplitude, 3.0)])), 2, amplitude)
            # Six alternating saccades 0.5 s apart: three deflections with their returns.
            moves = [(amplitude if index % 2 == 0 else -amplitude, 0.5) for index in range(6)]
            self.assertEqual(count_clean(eye_path(moves)), 3, amplitude)

    def test_spikes_and_drifts_do_not_count(self):
        for amplitude in (50.0, 300.0):
            spike = amplitude * np.sin(np.pi * np.arange(int(0.1 * FS)) / int(0.1 * FS))
            drift = amplitude * np.sin(np.pi * np.arange(int(10 * FS)) / int(10 * FS))
            self.assertEqual(count_clean(spike), 0, amplitude)
            self.assertEqual(count_clean(deflection(0.2, amplitude)), 0, amplitude)
            self.assertEqual(count_clean(drift), 0, amplitude)


class TestRemEventRow(unittest.TestCase):
    def test_missing_af7_or_af8_gives_nan(self):
        signal = rem_dense(0)
        for dropped in ("AF7", "AF8"):
            frames = frames_from_channels(signal.channels, drop_channel=dropped)
            row = extract_eeg_feature_rows(session_epochs(None, frames=frames))[3]
            self.assertTrue(math.isnan(row.rem_event_count))
            self.assertTrue(math.isnan(row.rem_density_per_min))
            self.assertTrue(math.isnan(row.last_rem_event_age_s))
            self.assertTrue(math.isnan(row.rem_event_threshold_uv))
            self.assertFalse(row.rem_burst_active)
            self.assertEqual(row.rem_event_times, ())
            prediction = HeuristicRemDetector().predict_features(eeg=row)
            self.assertNotIn("rem_event_density", prediction.feature_scores)
            self.assertNotIn("eeg_rem_events_low", prediction.reason_codes)
            self.assertNotIn("eeg_rem_events_support", prediction.reason_codes)

    def test_bad_frontal_channel_gives_nan_for_that_epoch(self):
        channels = dict(rem_dense(0).channels)
        clipped = channels["AF8"].copy()
        clipped[int(60 * FS) : int(80 * FS)] = 900.0
        channels["AF8"] = clipped
        rows = session_rows(channels)
        self.assertIn("AF8", rows[2].bad_channels)
        self.assertTrue(math.isnan(rows[2].rem_event_count))
        for index, row in enumerate(rows):
            if index != 2:
                self.assertTrue(math.isfinite(row.rem_event_count), index)

    def test_epoch_mostly_without_samples_gives_nan(self):
        signal = frontal_signal(310.0, seed=0, event_count=60)
        rows = session_rows(signal.channels)
        self.assertEqual(len(rows), 11)
        self.assertTrue(all(math.isfinite(row.rem_event_count) for row in rows[:10]))
        self.assertTrue(math.isnan(rows[10].rem_event_count))

    def test_row_columns_and_warmup(self):
        rows = session_rows(rem_dense(0).channels)
        first = rows[0].to_dict()
        for column in (
            "eye_movement_proxy",
            "rem_event_count",
            "rem_density_per_min",
            "last_rem_event_age_s",
            "rem_burst_active",
            "rem_event_times",
            "rem_event_threshold_uv",
            "rem_event_warmup",
        ):
            self.assertIn(column, first)
        self.assertEqual([row.rem_event_warmup for row in rows[:3]], [True, True, False])
        self.assertAlmostEqual(rows[4].rem_density_per_min, rows[4].rem_event_count * 2.0, places=4)
        self.assertGreaterEqual(rows[4].rem_event_threshold_uv, RemEventConfig().floor_uv)
        self.assertEqual(len(rows[4].rem_event_times), int(rows[4].rem_event_count))

    def test_annotation_rows_keep_the_old_proxy_columns(self):
        rows = build_rem_annotation_rows(session_epochs(rem_dense(0).channels))
        later = rows[4].to_dict()
        # Older CSVs and personal models key on the proxy columns; they stay.
        self.assertIn("feature_score_eye_movement_proxy", later)
        self.assertIn("feature_value_eye_movement_proxy", later)
        self.assertGreater(later["feature_value_rem_event_count"], 0)
        self.assertIn("feature_score_rem_event_density", later)
        self.assertIn("feature_value_rem_event_threshold_uv", later)
        self.assertEqual(later["feature_value_rem_event_warmup"], 0.0)

    def test_older_annotation_csvs_and_models_still_load(self):
        rows = build_rem_annotation_rows(session_epochs(rem_dense(0).channels))
        with tempfile.TemporaryDirectory() as tmp:
            # A template written before #225: no REM-event columns, labels filled in.
            old = pd.DataFrame([row.to_dict() for row in rows])
            old = old[[column for column in old.columns if "rem_event" not in column]]
            old["label"] = ["probable_rem" if index % 2 else "nrem" for index in range(len(old))]
            old_path = Path(tmp) / "old_labels.csv"
            old.to_csv(old_path, index=False)
            loaded = load_rem_annotations(old_path)
            model = train_personal_rem_classifier(loaded)
            model_path = model.save(Path(tmp) / "old_model.json")
            restored = PersonalRemModel.load(model_path)
        self.assertEqual(len(loaded), len(rows))
        self.assertEqual(restored.feature_names, DEFAULT_PERSONAL_REM_FEATURES)
        prediction = restored.predict_mapping(rows[4].to_training_dict())
        self.assertTrue(0.0 <= prediction.probability <= 1.0)

    def test_burst_and_age_follow_the_last_events(self):
        eye = np.concatenate([rem_deflection_train(), np.zeros(int(60 * FS))])
        base = 12.0 * np.sin(2 * np.pi * 6.0 * np.arange(eye.size) / FS)
        rows = session_rows({"TP9": base, "AF7": base + eye, "AF8": base - eye, "TP10": base})
        self.assertEqual(rows[0].rem_event_count, 8.0)
        self.assertTrue(rows[0].rem_burst_active)
        self.assertLess(rows[0].last_rem_event_age_s, 6.0)
        self.assertEqual(rows[2].rem_event_count, 0.0)
        self.assertFalse(rows[2].rem_burst_active)
        self.assertGreater(rows[2].last_rem_event_age_s, 60.0)


class TestRemEventTracker(unittest.TestCase):
    def test_same_events_for_one_array_30_s_epochs_and_overlapping_epochs(self):
        signal = rem_dense(2)
        whole = [
            event.time
            for event in detect_rem_events(
                signal.channels["AF7"], signal.channels["AF8"], start_time=START_TIME
            )
        ]
        by_epoch = event_times(session_rows(signal.channels))
        overlapping = session_rows(signal.channels, stride_seconds=10.0)
        by_overlap = sorted({round(time, 6) for row in overlapping for time in row.rem_event_times})
        self.assertGreater(len(whole), 40)
        np.testing.assert_allclose(by_epoch, whole, atol=1e-4)
        np.testing.assert_allclose(by_overlap, whole, atol=1e-4)
        self.assertEqual(sum(row.rem_event_count for row in overlapping[::3]), len(whole))

    def test_same_events_whatever_the_chunks(self):
        signal = rem_dense(1)
        left, right = signal.channels["AF7"], signal.channels["AF8"]
        times = np.arange(left.size) / FS
        whole = RemEventTracker().feed_samples(left, right, times)
        tracker, chunked, position = RemEventTracker(), [], 0
        sizes = np.random.default_rng(1).choice([1, 7, 12, 255, 256, 257, 5000], size=left.size)
        for size in sizes:
            if position >= left.size:
                break
            stop = position + int(size)
            chunked.extend(tracker.feed_samples(left[position:stop], right[position:stop], times[position:stop]))
            position = stop
        self.assertEqual(chunked, list(whole))

    def test_frame_clock_jitter_changes_no_count(self):
        signal = rem_dense(3)
        steady = event_times(session_rows(signal.channels))
        jittered = extract_eeg_feature_rows(
            session_epochs(None, frames=frames_from_channels(signal.channels, jitter_s=0.02, seed=3))
        )
        self.assertEqual(len(event_times(jittered)), len(steady))

    def test_session_tracker_counts_deflections_early_in_later_epochs(self):
        early = tuple((onset, 0.6, 1.0 if index % 2 else -1.0) for index, onset in enumerate((1.0, 3.0, 5.0)))
        eye = np.concatenate([rem_deflection_train(deflections=early)] * 4)
        epochs = session_epochs({"AF7": eye, "AF8": -eye})
        session = extract_eeg_feature_rows(epochs)
        fresh = [extract_eeg_features(epoch) for epoch in epochs]
        self.assertEqual([row.rem_event_count for row in session[1:]], [3.0, 3.0, 3.0])
        # A tracker that sees one epoch has no threshold for its first 7.5 s.
        self.assertEqual([row.rem_event_count for row in fresh], [0.0] * 4)
        self.assertTrue(all(row.rem_event_warmup for row in fresh))

    def test_gap_in_the_frame_clock_restarts_the_filter(self):
        channels = self._two_deflections()
        self.assertEqual(len(event_times(session_rows(channels))), 2)
        kept = [
            frame for frame in frames_from_channels(channels)
            if not START_TIME + 145.0 <= frame.timestamp < START_TIME + 150.0
        ]
        epochs = session_epochs(None, frames=kept)
        times = event_times(extract_eeg_feature_rows(epochs))
        # After the 5 s gap the filter starts again: 151 s falls inside its half-second
        # start and 2 s settling, 160 s is counted. Read across the gap as if the samples
        # were adjacent, both would be.
        self.assertEqual(len(times), 1)
        self.assertAlmostEqual(times[0] - START_TIME, 160.3, delta=0.5)
        no_gap = RemEventTracker(RemEventConfig(gap_seconds=1000.0))
        self.assertEqual(len(event_times(extract_eeg_feature_rows(epochs, rem_tracker=no_gap))), 2)

    def test_reported_sample_loss_restarts_the_filter(self):
        channels = self._two_deflections()
        for missing, expected in ((256, 1), (4, 2)):
            frames = list(frames_from_channels(channels))
            index = int(150.0 * FS) // 12
            frame = frames[index]
            frames[index] = MuseFrame(
                timestamp=frame.timestamp,
                eeg=EEGSample(frame.timestamp, frame.eeg.channels_uv, source="synthetic", gaps=((0, missing),)),
                source="synthetic",
            )
            times = event_times(extract_eeg_feature_rows(session_epochs(None, frames=frames)))
            self.assertEqual(len(times), expected, missing)

    def test_config_rejects_bad_values(self):
        for bad in (
            {"band_hz": (5.0, 0.3)},
            {"min_duration_seconds": 2.0},
            {"warmup_seconds": 400.0},
            {"mad_k": 0.0},
            {"highpass_order": 0},
            {"echo_fraction": 1.5},
            {"min_observed_fraction": -0.1},
        ):
            with self.assertRaises(ValueError, msg=str(bad)):
                RemEventTracker(RemEventConfig(**bad))

    @staticmethod
    def _two_deflections():
        signal = rem_free(3)
        eye = rem_deflection_train(
            seconds=SESSION_SECONDS,
            deflections=((151.0, 0.6, 1.0), (160.0, 0.6, -1.0)),
            amplitude_uv=40.0,
        )
        return dict(signal.channels, AF7=signal.channels["AF7"] + eye, AF8=signal.channels["AF8"] - eye)


if __name__ == "__main__":
    unittest.main()
