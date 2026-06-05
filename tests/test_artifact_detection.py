import unittest

from muse_tmr.data.sample_types import EEGSample, MuseFrame
from muse_tmr.features.artifact_detection import (
    ArtifactDiagnosticConfig,
    analyze_blink_artifact_phases,
    default_blink_artifact_phases,
)


class TestBlinkArtifactDiagnostics(unittest.TestCase):
    def test_default_protocol_ends_with_closed_eyes_baseline(self):
        phases = default_blink_artifact_phases(
            settle_seconds=1.0,
            eyes_open_baseline_seconds=1.0,
            blink_seconds=1.0,
            recovery_open_seconds=1.0,
            jaw_clench_seconds=1.0,
            head_movement_seconds=1.0,
            eyes_closed_baseline_seconds=1.0,
        )

        self.assertEqual(phases[-1].name, "eyes_closed_baseline")
        self.assertEqual(phases[-1].role, "closed_eyes_control")

    def test_blink_score_uses_centered_highpass_metrics_not_raw_offsets(self):
        phases = default_blink_artifact_phases(
            settle_seconds=1.0,
            eyes_open_baseline_seconds=2.0,
            blink_seconds=2.0,
            recovery_open_seconds=1.0,
            jaw_clench_seconds=1.0,
            head_movement_seconds=1.0,
            eyes_closed_baseline_seconds=2.0,
        )
        config = ArtifactDiagnosticConfig(
            sample_rate_hz=20.0,
            center_window_seconds=1.0,
            highpass_cutoff_hz=0.5,
            window_seconds=1.0,
        )
        phase_frames = {
            "eyes_open_baseline": _eeg_frames(_signal(count=40, dc_offset=3300.0)),
            "blink": _eeg_frames(
                _signal(
                    count=40,
                    dc_offset=3300.0,
                    frontal_spike_uv=160.0,
                    temporal_spike_uv=8.0,
                )
            ),
            "eyes_closed_baseline": _eeg_frames(_signal(count=40, dc_offset=3300.0)),
        }

        report = analyze_blink_artifact_phases(
            phase_frames,
            source="synthetic",
            phases=phases,
            config=config,
        )

        self.assertGreater(
            report.blink_summary["frontal_hp05_p99_abs_ratio_mean"],
            1.5,
        )
        self.assertTrue(report.blink_summary["detected"])
        self.assertTrue(report.closed_eyes_summary["present"])
        self.assertIn("eyes_closed_baseline", report.ratios_vs_open_baseline)

    def test_temporal_only_artifact_is_not_detected_as_blink(self):
        phases = default_blink_artifact_phases(
            settle_seconds=1.0,
            eyes_open_baseline_seconds=2.0,
            blink_seconds=2.0,
            recovery_open_seconds=1.0,
            jaw_clench_seconds=1.0,
            head_movement_seconds=1.0,
            eyes_closed_baseline_seconds=2.0,
        )
        config = ArtifactDiagnosticConfig(
            sample_rate_hz=20.0,
            center_window_seconds=1.0,
            highpass_cutoff_hz=0.5,
            window_seconds=1.0,
        )
        phase_frames = {
            "eyes_open_baseline": _eeg_frames(_signal(count=40, dc_offset=3300.0)),
            "blink": _eeg_frames(
                _signal(
                    count=40,
                    dc_offset=3300.0,
                    frontal_spike_uv=8.0,
                    temporal_spike_uv=160.0,
                )
            ),
            "eyes_closed_baseline": _eeg_frames(_signal(count=40, dc_offset=3300.0)),
        }

        report = analyze_blink_artifact_phases(
            phase_frames,
            source="synthetic",
            phases=phases,
            config=config,
        )

        self.assertFalse(report.blink_summary["detected"])
        self.assertIn("frontal_not_above_temporal", report.blink_summary["reason_codes"])
        self.assertLess(
            report.blink_summary["frontal_to_temporal_hp05_p99_abs_ratio"],
            1.0,
        )


def _signal(
    *,
    count,
    dc_offset,
    frontal_spike_uv=0.0,
    temporal_spike_uv=0.0,
):
    values = {"TP9": [], "AF7": [], "AF8": [], "TP10": []}
    for idx in range(count):
        noise = ((idx % 5) - 2) * 2.0
        spike = 1.0 if idx in {8, 18, 28, 38} else 0.0
        values["TP9"].append(dc_offset + noise + temporal_spike_uv * spike)
        values["TP10"].append(dc_offset - noise + temporal_spike_uv * spike)
        values["AF7"].append(dc_offset + noise + frontal_spike_uv * spike)
        values["AF8"].append(dc_offset - noise + frontal_spike_uv * spike)
    return values


def _eeg_frames(values_by_channel):
    count = len(next(iter(values_by_channel.values())))
    frames = []
    for idx in range(count):
        timestamp = idx / 20.0
        frames.append(
            MuseFrame(
                timestamp=timestamp,
                eeg=EEGSample(
                    timestamp=timestamp,
                    channels_uv={
                        channel: (values[idx],)
                        for channel, values in values_by_channel.items()
                    },
                    source="synthetic",
                ),
                source="synthetic",
            )
        )
    return tuple(frames)


if __name__ == "__main__":
    unittest.main()
