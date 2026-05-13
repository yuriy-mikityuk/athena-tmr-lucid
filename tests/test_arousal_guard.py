import math
import tempfile
import unittest
from pathlib import Path

from muse_tmr.features.eeg_features import EEGFeatureRow
from muse_tmr.features.imu_features import IMUFeatureRow
from muse_tmr.features.ppg_features import PPGFeatureRow
from muse_tmr.protocol import (
    ArousalGuard,
    ArousalGuardConfig,
    load_arousal_guard_decisions,
)


class TestArousalGuard(unittest.TestCase):
    def test_default_allows_quiet_features(self):
        decision = ArousalGuard().evaluate(
            timestamp_seconds=0.0,
            eeg=_eeg(alpha=0.10),
            imu=_imu(stillness_score=0.99),
            ppg=_ppg(),
        )

        self.assertEqual(decision.action, "allow")
        self.assertEqual(decision.reason_codes, ())
        self.assertEqual(decision.volume_multiplier, 1.0)

    def test_motion_arousal_pauses_and_logs_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "arousal_guard.jsonl"
            guard = ArousalGuard(event_log_path=log_path)

            decision = guard.evaluate(
                timestamp_seconds=30.0,
                imu=_imu(
                    arousal_guard_reason_codes=("motion_arousal_proxy",),
                    arousal_event_count=1,
                ),
            )
            logged = load_arousal_guard_decisions(log_path)

        self.assertEqual(decision.action, "pause")
        self.assertEqual(decision.pause_seconds, 120.0)
        self.assertIn("motion_arousal_proxy", decision.reason_codes)
        self.assertEqual([item.action for item in logged], ["pause"])

    def test_alpha_proxy_lowers_volume_before_stronger_pause_threshold(self):
        config = ArousalGuardConfig(
            alpha_lower_volume_relative_power=0.20,
            alpha_pause_relative_power=0.40,
            lower_volume_multiplier=0.40,
        )
        guard = ArousalGuard(config)

        mild = guard.evaluate(timestamp_seconds=0.0, eeg=_eeg(alpha=0.30))
        strong = guard.evaluate(timestamp_seconds=30.0, eeg=_eeg(alpha=0.50))

        self.assertEqual(mild.action, "lower_volume")
        self.assertEqual(mild.volume_multiplier, 0.40)
        self.assertIn("alpha_arousal_proxy_mild", mild.reason_codes)
        self.assertEqual(strong.action, "pause")
        self.assertIn("alpha_arousal_proxy", strong.reason_codes)

    def test_sudden_heart_rate_jump_pauses_cueing(self):
        decision = ArousalGuard().evaluate(
            timestamp_seconds=60.0,
            ppg=_ppg(sudden_hr_change_count=1, max_sudden_hr_change_bpm=18.0),
        )

        self.assertEqual(decision.action, "pause")
        self.assertIn("sudden_heart_rate_change", decision.reason_codes)

    def test_out_of_range_heart_rate_artifact_pauses_cueing(self):
        decision = ArousalGuard().evaluate(
            timestamp_seconds=60.0,
            ppg=_ppg(artifact_flags=("heart_rate_out_of_range",)),
        )

        self.assertEqual(decision.action, "pause")
        self.assertIn("heart_rate_out_of_range", decision.reason_codes)
        self.assertIn("ppg_artifact_flags", decision.reason_codes)

    def test_repeated_single_channel_eeg_artifact_lowers_volume_without_pause_or_stop(self):
        guard = ArousalGuard(
            ArousalGuardConfig(stop_after_consecutive_artifact_epochs=2)
        )

        decisions = [
            guard.evaluate(
                timestamp_seconds=index * 30.0,
                eeg=_eeg(
                    artifact_flags=("eeg_clipping_AF8",),
                    bad_channels=("AF8",),
                    usable_channel_count=3,
                ),
            )
            for index in range(3)
        ]

        self.assertEqual([decision.action for decision in decisions], ["lower_volume"] * 3)
        self.assertTrue(
            all("single_channel_eeg_artifact" in decision.reason_codes for decision in decisions)
        )
        self.assertEqual(guard.consecutive_artifact_epochs, 0)
        self.assertEqual(guard.consecutive_critical_artifact_epochs, 0)

    def test_repeated_noncritical_artifact_pauses_recoverably(self):
        guard = ArousalGuard(
            ArousalGuardConfig(stop_after_consecutive_artifact_epochs=2)
        )

        first = guard.evaluate(
            timestamp_seconds=0.0,
            eeg=_eeg(artifact_flags=("eeg_missing",)),
        )
        second = guard.evaluate(
            timestamp_seconds=30.0,
            eeg=_eeg(artifact_flags=("eeg_missing",)),
        )
        clean = guard.evaluate(
            timestamp_seconds=60.0,
            eeg=_eeg(),
        )

        self.assertEqual(first.action, "lower_volume")
        self.assertEqual(second.action, "pause")
        self.assertIn("repeated_artifact_quality", second.reason_codes)
        self.assertIn("eeg_artifact_flags", second.reason_codes)
        self.assertEqual(clean.action, "allow")
        self.assertEqual(guard.consecutive_artifact_epochs, 0)

    def test_legacy_repeated_artifact_stop_option_is_still_available(self):
        guard = ArousalGuard(
            ArousalGuardConfig(
                repeated_artifact_action="stop",
                stop_after_consecutive_artifact_epochs=2,
            )
        )

        guard.evaluate(timestamp_seconds=0.0, eeg=_eeg(artifact_flags=("eeg_missing",)))
        second = guard.evaluate(timestamp_seconds=30.0, eeg=_eeg(artifact_flags=("eeg_missing",)))

        self.assertEqual(second.action, "stop")
        self.assertIn("repeated_artifact_quality", second.reason_codes)

    def test_critical_multi_channel_eeg_artifact_stops_after_configured_streak(self):
        guard = ArousalGuard(
            ArousalGuardConfig(
                critical_eeg_bad_channel_count=3,
                stop_after_consecutive_critical_artifact_epochs=2,
            )
        )

        first = guard.evaluate(
            timestamp_seconds=0.0,
            eeg=_eeg(
                artifact_flags=("eeg_clipping_AF7", "eeg_clipping_AF8", "eeg_clipping_TP9"),
                bad_channels=("AF7", "AF8", "TP9"),
                usable_channel_count=1,
            ),
        )
        second = guard.evaluate(
            timestamp_seconds=30.0,
            eeg=_eeg(
                artifact_flags=("eeg_clipping_AF7", "eeg_clipping_AF8", "eeg_clipping_TP9"),
                bad_channels=("AF7", "AF8", "TP9"),
                usable_channel_count=1,
            ),
        )

        self.assertEqual(first.action, "pause")
        self.assertIn("critical_eeg_artifact", first.reason_codes)
        self.assertEqual(second.action, "stop")
        self.assertIn("critical_eeg_artifact", second.reason_codes)

    def test_motion_and_hr_arousal_pause_then_recover_after_clean_epoch(self):
        guard = ArousalGuard()

        motion = guard.evaluate(
            timestamp_seconds=0.0,
            imu=_imu(arousal_guard_reason_codes=("motion_arousal_proxy",), arousal_event_count=1),
        )
        hr = guard.evaluate(
            timestamp_seconds=30.0,
            ppg=_ppg(sudden_hr_change_count=1, max_sudden_hr_change_bpm=18.0),
        )
        clean = guard.evaluate(
            timestamp_seconds=60.0,
            eeg=_eeg(alpha=0.10),
            imu=_imu(stillness_score=0.99),
            ppg=_ppg(),
        )

        self.assertEqual(motion.action, "pause")
        self.assertEqual(hr.action, "pause")
        self.assertEqual(clean.action, "allow")
        self.assertEqual(guard.consecutive_pause_epochs, 0)

    def test_eeg_channel_diagnostics_are_logged_for_artifacts(self):
        decision = ArousalGuard().evaluate(
            timestamp_seconds=0.0,
            eeg=_eeg(
                artifact_flags=("eeg_clipping_AF7",),
                channel_diagnostics={
                    "AF7": {
                        "max_uv": 760.0,
                        "median_uv": 725.0,
                        "centered_abs_max_uv": 35.0,
                    }
                },
            ),
        )

        self.assertEqual(decision.action, "lower_volume")
        self.assertIn("eeg_channel_diagnostics", decision.metadata)
        self.assertEqual(
            decision.metadata["eeg_channel_diagnostics"]["AF7"]["centered_abs_max_uv"],
            35.0,
        )

    def test_config_rejects_unordered_alpha_thresholds(self):
        with self.assertRaises(ValueError):
            ArousalGuardConfig(
                alpha_lower_volume_relative_power=0.50,
                alpha_pause_relative_power=0.40,
            ).validate()


def _eeg(
    alpha=0.10,
    artifact_flags=(),
    channel_diagnostics=None,
    bad_channels=(),
    usable_channel_count=2,
):
    return EEGFeatureRow(
        epoch_index=1,
        start_time=0.0,
        end_time=30.0,
        eeg_coverage=1.0,
        sample_count=256,
        channel_count=2,
        channel_sample_counts={"AF7": 256, "AF8": 256},
        band_powers={},
        relative_band_powers={"alpha": alpha},
        ratios={},
        asymmetry={},
        eye_movement_proxy=0.0,
        artifact_flags=artifact_flags,
        quality_flags=(),
        channel_diagnostics=channel_diagnostics or {},
        bad_channels=bad_channels,
        usable_channel_count=usable_channel_count,
    )


def _imu(
    stillness_score=1.0,
    arousal_guard_reason_codes=(),
    arousal_event_count=0,
):
    return IMUFeatureRow(
        epoch_index=1,
        start_time=0.0,
        end_time=30.0,
        imu_coverage=1.0,
        sample_count=100,
        accelerometer_sample_count=100,
        gyroscope_sample_count=100,
        motion_level=0.0,
        stillness_score=stillness_score,
        accel_rms_delta_g=0.0,
        accel_peak_delta_g=0.0,
        gyro_rms_dps=0.0,
        gyro_peak_dps=0.0,
        movement_event_count=arousal_event_count,
        arousal_event_count=arousal_event_count,
        arousal_proxy=0.0,
        movement_events=(),
        cue_movement_logs=(),
        artifact_flags=(),
        quality_flags=(),
        arousal_guard_reason_codes=arousal_guard_reason_codes,
    )


def _ppg(sudden_hr_change_count=0, max_sudden_hr_change_bpm=math.nan, artifact_flags=()):
    return PPGFeatureRow(
        epoch_index=1,
        start_time=0.0,
        end_time=30.0,
        ppg_coverage=1.0,
        heart_rate_coverage=1.0,
        ppg_sample_count=64,
        heart_rate_sample_count=10,
        ppg_channel_count=1,
        ppg_channel_sample_counts={"ambient": 64},
        primary_ppg_channel="ambient",
        ppg_estimated_hr_bpm=60.0,
        ppg_confidence=0.9,
        ppg_peak_count=30,
        ppg_signal_quality="Good",
        mean_hr_bpm=60.0,
        median_hr_bpm=60.0,
        min_hr_bpm=58.0,
        max_hr_bpm=62.0,
        hr_trend_bpm_per_min=0.0,
        hr_source="heart_rate",
        mean_rr_ms=1000.0,
        sdnn_ms=20.0,
        rmssd_ms=25.0,
        pnn50_percent=0.0,
        hrv_source="heart_rate",
        sudden_hr_change_count=sudden_hr_change_count,
        max_sudden_hr_change_bpm=max_sudden_hr_change_bpm,
        sudden_hr_changes=(),
        artifact_flags=artifact_flags,
        quality_flags=(),
    )


if __name__ == "__main__":
    unittest.main()
