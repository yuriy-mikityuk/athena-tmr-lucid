import json
import tempfile
import unittest
from pathlib import Path

from muse_tmr.reports.source_diagnostics import (
    compare_source_diagnostic_reports,
    format_blink_channel_inspection_markdown,
    format_source_diagnostic_markdown,
    inspect_blink_channel_reports,
    save_blink_channel_inspection,
    save_source_diagnostic_comparison,
)


class TestSourceDiagnosticComparison(unittest.TestCase):
    def test_compares_blink_reports_into_source_quality_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "brainflow_session.json"
            report_path.write_text(
                json.dumps(_diagnostic_report("brainflow", preset="p1041")),
                encoding="utf-8",
            )

            rows = compare_source_diagnostic_reports((report_path,))

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row.source, "brainflow")
            self.assertEqual(row.preset, "p1041")
            self.assertTrue(row.blink_detected)
            self.assertAlmostEqual(row.blink_frontal_ratio, 3.2)
            self.assertAlmostEqual(row.open_baseline_eeg_rate_hz, 256.0)
            self.assertAlmostEqual(row.open_baseline_eeg_missing_fraction, 0.0)
            self.assertFalse(row.hr_present)
            self.assertTrue(row.ppg_present)
            self.assertEqual(row.modality_evidence, "observed")

    def test_formats_and_saves_markdown_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "amused_session.json"
            output_path = tmp_path / "comparison.md"
            report_path.write_text(
                json.dumps(_diagnostic_report("amused", preset="p1034", blink_detected=False)),
                encoding="utf-8",
            )
            rows = compare_source_diagnostic_reports((report_path,))

            table = format_source_diagnostic_markdown(rows)
            saved = save_source_diagnostic_comparison(rows, output_path, output_format="markdown")

            self.assertIn("| session | source | preset | blink |", table)
            self.assertIn("| amused_session | amused | p1034 | no |", table)
            self.assertEqual(saved, output_path)
            self.assertIn("amused_session", output_path.read_text(encoding="utf-8"))

    def test_inspects_per_channel_blink_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "brainflow_session.json"
            output_path = tmp_path / "channels.csv"
            report_path.write_text(
                json.dumps(_diagnostic_report("brainflow", preset="p1041")),
                encoding="utf-8",
            )

            rows = inspect_blink_channel_reports((report_path,), phases=("blink",))
            table = format_blink_channel_inspection_markdown(rows)
            saved = save_blink_channel_inspection(rows, output_path, output_format="csv")

            self.assertEqual(len(rows), 4)
            af7 = next(row for row in rows if row.channel == "AF7")
            self.assertEqual(af7.channel_group, "frontal")
            self.assertEqual(af7.rank, 1)
            self.assertAlmostEqual(af7.hp05_p99_abs_ratio, 4.0)
            self.assertAlmostEqual(af7.frontal_hp05_p99_abs_ratio_mean, 3.5)
            self.assertAlmostEqual(af7.temporal_hp05_p99_abs_ratio_mean, 1.1)
            self.assertGreater(af7.frontal_temporal_hp05_p99_abs_ratio, 3.0)
            self.assertIn("| brainflow_session | brainflow | p1041 | blink | AF7 | frontal |", table)
            self.assertEqual(saved, output_path)
            self.assertIn("frontal_hp05_p99_abs_ratio_mean", output_path.read_text(encoding="utf-8"))


def _diagnostic_report(source, *, preset, blink_detected=True):
    return {
        "source": source,
        "config": {
            "sample_rate_hz": 256.0,
            "open_baseline_phase": "eyes_open_baseline",
            "blink_phase": "blink",
        },
        "phases": [
            {"name": "eyes_open_baseline", "duration_seconds": 45.0},
            {"name": "blink", "duration_seconds": 20.0},
        ],
        "phase_metrics": {
            "eyes_open_baseline": {
                "AF7": _channel_metrics(11520.0, hp05_p99_abs=10.0),
                "AF8": _channel_metrics(11520.0, hp05_p99_abs=10.0),
                "TP9": _channel_metrics(11520.0, hp05_p99_abs=10.0),
                "TP10": _channel_metrics(11520.0, hp05_p99_abs=10.0),
            },
            "blink": {
                "AF7": _channel_metrics(5120.0, hp05_p99_abs=40.0),
                "AF8": _channel_metrics(5120.0, hp05_p99_abs=30.0),
                "TP9": _channel_metrics(5120.0, hp05_p99_abs=12.0),
                "TP10": _channel_metrics(5120.0, hp05_p99_abs=10.0),
            },
        },
        "ratios_vs_open_baseline": {
            "blink": {
                "AF7": _channel_ratios(4.0),
                "AF8": _channel_ratios(3.0),
                "TP9": _channel_ratios(1.2),
                "TP10": _channel_ratios(1.0),
                "rank_by_hp05_p99_abs_ratio": ["AF7", "AF8", "TP9", "TP10"],
            },
        },
        "blink_summary": {
            "detected": blink_detected,
            "reason_codes": [] if blink_detected else ["weak_frontal_lift"],
            "frontal_hp05_p99_abs_ratio_mean": 3.2,
            "temporal_hp05_p99_abs_ratio_mean": 1.1,
            "frontal_to_temporal_hp05_p99_abs_ratio": 2.9,
            "rank_by_hp05_p99_abs_ratio": ["AF7", "AF8", "TP9", "TP10"],
        },
        "source_metadata": {
            "source_name": source,
            "capabilities": {
                "heart_rate": source == "amused",
                "ppg": True,
                "imu": True,
                "battery": True,
            },
            "metadata": {"preset": preset},
        },
        "source_diagnostics": {"disconnect_reason": None, "frame_count": 100},
        "session_summary": {
            "session_id": f"{source}_session",
            "total_modality_counts": {
                "eeg": 10,
                "ppg": 5,
                "imu": 5,
                "battery": 1,
                "heart_rate": 2 if source == "amused" else 0,
            },
        },
    }


def _channel_metrics(count, *, hp05_p99_abs):
    return {
        "count": count,
        "raw_mean": 3300.0,
        "raw_median": 3300.0,
        "raw_std": 5.0,
        "raw_peak_to_peak": 20.0,
        "centered_p95_abs": hp05_p99_abs * 0.8,
        "centered_p99_abs": hp05_p99_abs,
        "centered_peak_to_peak": hp05_p99_abs * 2.0,
        "hp05_std": hp05_p99_abs * 0.4,
        "hp05_p95_abs": hp05_p99_abs * 0.8,
        "hp05_p99_abs": hp05_p99_abs,
        "hp05_peak_to_peak": hp05_p99_abs * 2.0,
    }


def _channel_ratios(hp05_p99_abs_ratio):
    return {
        "centered_p99_abs_ratio": hp05_p99_abs_ratio,
        "hp05_p99_abs_ratio": hp05_p99_abs_ratio,
        "hp05_peak_to_peak_ratio": hp05_p99_abs_ratio,
    }


if __name__ == "__main__":
    unittest.main()
