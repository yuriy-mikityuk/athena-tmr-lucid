import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from muse_tmr.cli.main import main
from muse_tmr.validation import validate_pilot1_recording


class TestPilot1Validation(unittest.TestCase):
    def test_valid_pilot1_recording_passes_and_reports_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            recording_dir = Path(tmp)
            _write_summary(recording_dir)

            report = validate_pilot1_recording(recording_dir)

        self.assertTrue(report.passed)
        self.assertEqual(report.metrics["duration_hours"], 6.0)
        self.assertTrue(report.coverage_targets["eeg"]["passed"])
        self.assertEqual(report.failed_criteria, ())

    def test_missing_summary_fails_with_actionable_criterion(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_pilot1_recording(Path(tmp))

        self.assertFalse(report.passed)
        self.assertEqual(report.failed_criteria, ("summary_exists",))

    def test_short_or_audio_sidecar_recording_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            recording_dir = Path(tmp)
            _write_summary(recording_dir, duration_seconds=5 * 3600)
            (recording_dir / "night-001_scheduler.jsonl").write_text("{}", encoding="utf-8")

            report = validate_pilot1_recording(recording_dir)

        self.assertFalse(report.passed)
        self.assertIn("duration_at_least_minimum", report.failed_criteria)
        self.assertIn("no_audio_sidecars", report.failed_criteria)

    def test_cli_writes_report_and_returns_nonzero_on_failed_pilot(self):
        with tempfile.TemporaryDirectory() as tmp:
            recording_dir = Path(tmp) / "recording"
            output_path = Path(tmp) / "pilot1_report.json"
            _write_summary(recording_dir, modality_counts={"eeg": 100, "imu": 100})

            with redirect_stdout(io.StringIO()) as stdout:
                exit_code = main([
                    "validate-pilot1-recording",
                    str(recording_dir),
                    "--output",
                    str(output_path),
                ])

            payload = json.loads(stdout.getvalue())
            saved = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["passed"])
        self.assertEqual(payload, saved)
        self.assertIn("required_modality_ppg_present", payload["failed_criteria"])


def _write_summary(
    recording_dir: Path,
    *,
    duration_seconds: float = 6 * 3600,
    modality_counts=None,
) -> Path:
    recording_dir.mkdir(parents=True, exist_ok=True)
    raw_path = recording_dir / "raw_amused.bin"
    raw_path.write_bytes(b"raw")
    payload = {
        "output_dir": str(recording_dir),
        "raw_path": str(raw_path),
        "metadata_path": str(recording_dir / "metadata.json"),
        "events_path": str(recording_dir / "events.jsonl"),
        "summary_path": str(recording_dir / "summary.json"),
        "started_at": "2026-05-13T00:00:00+00:00",
        "ended_at": "2026-05-13T06:00:00+00:00",
        "duration_seconds": duration_seconds,
        "frame_count": 1234,
        "raw_packet_count": 1234,
        "modality_counts": modality_counts or {"eeg": 900, "imu": 800, "ppg": 700},
        "reconnect_attempts": 0,
        "downtime_seconds": 0.0,
        "stop_reason": "duration_complete",
    }
    summary_path = recording_dir / "summary.json"
    summary_path.write_text(json.dumps(payload), encoding="utf-8")
    return summary_path


if __name__ == "__main__":
    unittest.main()
