import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from muse_tmr.data.sample_types import EEGSample, MuseFrame
from muse_tmr.features.eeg_features import (
    EEGFeatureConfig,
    export_eeg_feature_rows,
    extract_eeg_feature_rows,
    extract_eeg_features,
)
from muse_tmr.features.epochs import EpochBuilder, EpochConfig, SleepEpoch


def sine_values(frequency_hz: float, seconds: float = 30.0, sample_rate_hz: int = 256, amplitude: float = 10.0):
    timestamps = np.arange(0, seconds, 1 / sample_rate_hz)
    return (amplitude * np.sin(2 * np.pi * frequency_hz * timestamps)).tolist()


def eeg_epoch(channels, *, epoch_index: int = 0) -> SleepEpoch:
    frame = MuseFrame(
        timestamp=1000.0,
        eeg=EEGSample(timestamp=1000.0, channels_uv=channels, source="test"),
        source="test",
    )
    return EpochBuilder(EpochConfig(epoch_seconds=30, stride_seconds=30))._build_epoch(
        epoch_index,
        1000.0,
        (frame,),
    )


class TestEEGFeatures(unittest.TestCase):
    def test_alpha_sine_has_dominant_alpha_power(self):
        alpha = sine_values(10.0)
        epoch = eeg_epoch({
            "TP9": alpha,
            "AF7": alpha,
            "AF8": alpha,
            "TP10": alpha,
        })

        row = extract_eeg_features(epoch)

        self.assertGreater(row.band_powers["alpha"], row.band_powers["theta"])
        self.assertGreater(row.band_powers["alpha"], row.band_powers["beta"])
        self.assertGreater(row.relative_band_powers["alpha"], 0.8)
        self.assertEqual(row.artifact_flags, ())

    def test_delta_sine_has_dominant_delta_power(self):
        delta = sine_values(2.0)
        epoch = eeg_epoch({
            "TP9": delta,
            "AF7": delta,
            "AF8": delta,
            "TP10": delta,
        })

        row = extract_eeg_features(epoch)

        self.assertGreater(row.band_powers["delta"], row.band_powers["theta"])
        self.assertGreater(row.band_powers["delta"], row.band_powers["alpha"])
        self.assertGreater(row.relative_band_powers["delta"], 0.8)

    def test_frontal_alpha_asymmetry_tracks_right_left_power(self):
        epoch = eeg_epoch({
            "AF7": sine_values(10.0, amplitude=1.0),
            "AF8": sine_values(10.0, amplitude=4.0),
            "TP9": sine_values(10.0, amplitude=1.0),
            "TP10": sine_values(10.0, amplitude=1.0),
        })

        row = extract_eeg_features(epoch)

        self.assertGreater(row.asymmetry["alpha_asymmetry_af8_af7"], 2.0)
        self.assertAlmostEqual(row.asymmetry["alpha_asymmetry_tp10_tp9"], 0.0, places=3)

    def test_eye_movement_proxy_uses_frontal_difference_changes(self):
        epoch = eeg_epoch({
            "AF7": sine_values(1.0, amplitude=10.0),
            "AF8": sine_values(1.0, amplitude=-10.0),
            "TP9": sine_values(10.0),
            "TP10": sine_values(10.0),
        })

        row = extract_eeg_features(epoch)

        self.assertGreater(row.eye_movement_proxy, 0.1)

    def test_missing_eeg_returns_flags_without_crashing(self):
        epoch = SleepEpoch(
            index=0,
            start_time=1000.0,
            end_time=1030.0,
            frames=(),
            modality_counts={},
            sample_counts={},
            coverage={"eeg": 0.0},
            quality_flags=("missing_eeg",),
        )

        row = extract_eeg_features(epoch)

        self.assertEqual(row.sample_count, 0)
        self.assertTrue(math.isnan(row.band_powers["alpha"]))
        self.assertIn("eeg_missing", row.artifact_flags)

    def test_flatline_and_clipping_are_flagged(self):
        clipping = [0.0] * (30 * 256)
        clipping[: 30 * 26] = [600.0] * (30 * 26)
        epoch = eeg_epoch({
            "AF7": [0.0] * (30 * 256),
            "AF8": clipping,
        })

        row = extract_eeg_features(
            epoch,
            EEGFeatureConfig(artifact_abs_uv_threshold=500.0),
        )

        self.assertIn("eeg_flatline_AF7", row.artifact_flags)
        self.assertIn("eeg_clipping_AF8", row.artifact_flags)
        self.assertEqual(row.bad_channels, ("AF7", "AF8"))
        self.assertEqual(row.usable_channel_count, 0)
        self.assertGreater(row.channel_diagnostics["AF8"]["centered_abs_max_uv"], 500.0)
        self.assertGreater(
            row.channel_diagnostics["AF8"]["centered_abs_over_threshold_fraction"],
            0.05,
        )

    def test_dc_offset_alone_does_not_count_as_clipping(self):
        epoch = eeg_epoch({
            "AF7": (725.0 + np.asarray(sine_values(10.0, amplitude=25.0))).tolist(),
            "AF8": (725.0 + np.asarray(sine_values(10.0, amplitude=25.0))).tolist(),
        })

        row = extract_eeg_features(
            epoch,
            EEGFeatureConfig(artifact_abs_uv_threshold=500.0),
        )

        self.assertNotIn("eeg_clipping_AF7", row.artifact_flags)
        self.assertNotIn("eeg_clipping_AF8", row.artifact_flags)
        self.assertEqual(row.bad_channels, ())
        self.assertEqual(row.usable_channel_count, 2)
        self.assertGreater(row.channel_diagnostics["AF7"]["max_uv"], 500.0)
        self.assertLess(row.channel_diagnostics["AF7"]["centered_abs_max_uv"], 500.0)

    def test_single_bad_af8_does_not_poison_all_eeg_features(self):
        alpha = sine_values(10.0)
        clipping = [0.0] * (30 * 256)
        clipping[: 30 * 26] = [600.0] * (30 * 26)
        epoch = eeg_epoch({
            "AF7": alpha,
            "AF8": clipping,
            "TP9": alpha,
            "TP10": alpha,
        })

        row = extract_eeg_features(
            epoch,
            EEGFeatureConfig(artifact_abs_uv_threshold=500.0),
        )

        self.assertEqual(row.bad_channels, ("AF8",))
        self.assertEqual(row.channel_count, 4)
        self.assertEqual(row.usable_channel_count, 3)
        self.assertGreater(row.relative_band_powers["alpha"], 0.8)
        self.assertTrue(math.isnan(row.asymmetry["alpha_asymmetry_af8_af7"]))
        self.assertAlmostEqual(row.asymmetry["alpha_asymmetry_tp10_tp9"], 0.0, places=3)

    def test_bad_frontal_channel_disables_eye_movement_proxy(self):
        clipping = [0.0] * (30 * 256)
        clipping[: 30 * 26] = [600.0] * (30 * 26)
        epoch = eeg_epoch({
            "AF7": sine_values(1.0, amplitude=10.0),
            "AF8": clipping,
            "TP9": sine_values(10.0),
            "TP10": sine_values(10.0),
        })

        row = extract_eeg_features(
            epoch,
            EEGFeatureConfig(artifact_abs_uv_threshold=500.0),
        )

        self.assertEqual(row.bad_channels, ("AF8",))
        self.assertTrue(math.isnan(row.eye_movement_proxy))

    def test_multi_channel_sustained_clipping_marks_multiple_bad_channels(self):
        clipping = [0.0] * (30 * 256)
        clipping[: 30 * 26] = [600.0] * (30 * 26)
        epoch = eeg_epoch({
            "AF7": clipping,
            "AF8": clipping,
            "TP9": clipping,
            "TP10": sine_values(10.0),
        })

        row = extract_eeg_features(
            epoch,
            EEGFeatureConfig(artifact_abs_uv_threshold=500.0),
        )

        self.assertEqual(row.bad_channels, ("AF7", "AF8", "TP9"))
        self.assertEqual(row.usable_channel_count, 1)

    def test_nonfinite_channel_is_flagged(self):
        epoch = eeg_epoch({
            "AF7": [math.nan] * (30 * 256),
            "AF8": sine_values(10.0),
        })

        row = extract_eeg_features(epoch)

        self.assertIn("eeg_nonfinite_AF7", row.artifact_flags)
        self.assertGreater(row.band_powers["alpha"], 0.0)

    def test_low_eeg_coverage_is_flagged(self):
        short = sine_values(10.0, seconds=3.0)
        epoch = eeg_epoch({"AF7": short, "AF8": short})

        row = extract_eeg_features(epoch)

        self.assertLess(row.eeg_coverage, 0.5)
        self.assertIn("low_eeg_coverage", row.artifact_flags)

    def test_feature_rows_export_to_csv(self):
        epoch = eeg_epoch({
            "AF7": sine_values(10.0),
            "AF8": sine_values(10.0),
        })
        rows = extract_eeg_feature_rows([epoch])

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "eeg_features.csv"
            export_eeg_feature_rows(rows, output_path)
            frame = pd.read_csv(output_path)

        self.assertEqual(len(frame), 1)
        self.assertIn("band_power_alpha", frame.columns)
        self.assertIn("theta_alpha_ratio", frame.columns)

    @unittest.skipIf(
        importlib.util.find_spec("pyarrow") is None and importlib.util.find_spec("fastparquet") is None,
        "pandas parquet engine is not installed",
    )
    def test_feature_rows_export_to_parquet_when_engine_available(self):
        epoch = eeg_epoch({
            "AF7": sine_values(10.0),
            "AF8": sine_values(10.0),
        })
        rows = extract_eeg_feature_rows([epoch])

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "eeg_features.parquet"
            export_eeg_feature_rows(rows, output_path)
            frame = pd.read_parquet(output_path)

        self.assertEqual(len(frame), 1)
        self.assertIn("band_power_alpha", frame.columns)


if __name__ == "__main__":
    unittest.main()
