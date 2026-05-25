import json
import tempfile
import unittest
from pathlib import Path

from muse_tmr.reports.source_diagnostics import (
    compare_source_diagnostic_reports,
    format_source_diagnostic_markdown,
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
                "AF7": {"count": 11520.0},
                "AF8": {"count": 11520.0},
                "TP9": {"count": 11520.0},
                "TP10": {"count": 11520.0},
            },
            "blink": {
                "AF7": {"count": 5120.0},
                "AF8": {"count": 5120.0},
                "TP9": {"count": 5120.0},
                "TP10": {"count": 5120.0},
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


if __name__ == "__main__":
    unittest.main()
