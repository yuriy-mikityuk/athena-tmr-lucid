import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from muse_tmr.audio import VolumeCalibration, save_volume_calibration
from muse_tmr.cli.main import main
from muse_tmr.validation import validate_pilot2_calibration


class TestPilot2Validation(unittest.TestCase):
    def test_valid_calibration_and_cap_probe_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            calibration_path, playback_log_path = _pilot2_inputs(Path(tmp))

            report = validate_pilot2_calibration(
                calibration_path,
                device_name="Bedroom Headphones",
                playback_log_path=playback_log_path,
            )

        self.assertTrue(report.passed)
        self.assertEqual(report.failed_criteria, ())
        self.assertEqual(report.metrics["scheduler_max_volume"], 0.06)
        self.assertEqual(report.metrics["cap_probe"]["effective_volume"], 0.06)

    def test_missing_cap_probe_log_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            calibration_path, _ = _pilot2_inputs(Path(tmp))

            report = validate_pilot2_calibration(
                calibration_path,
                device_name="Bedroom Headphones",
                playback_log_path=Path(tmp) / "missing.jsonl",
            )

        self.assertFalse(report.passed)
        self.assertIn("cap_probe_log_present", report.failed_criteria)

    def test_uncapped_probe_fails_use_later_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            calibration_path = tmp_path / "volume.json"
            playback_log_path = tmp_path / "playback.jsonl"
            save_volume_calibration(
                VolumeCalibration("Bedroom Headphones", 0.01, 0.04, 0.06),
                calibration_path,
            )
            _write_playback_event(
                playback_log_path,
                effective_volume=0.10,
                max_volume=0.20,
                volume_capped=False,
            )

            report = validate_pilot2_calibration(
                calibration_path,
                device_name="Bedroom Headphones",
                playback_log_path=playback_log_path,
            )

        self.assertFalse(report.passed)
        self.assertIn("cap_probe_effective_volume_capped", report.failed_criteria)
        self.assertIn("cap_probe_max_volume_uses_calibration", report.failed_criteria)

    def test_cli_writes_report_and_returns_nonzero_on_missing_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            calibration_path = tmp_path / "volume.json"
            output_path = tmp_path / "pilot2_report.json"
            save_volume_calibration(
                VolumeCalibration("Bedroom Headphones", 0.01, 0.04, 0.06),
                calibration_path,
            )

            with redirect_stdout(io.StringIO()) as stdout:
                exit_code = main([
                    "validate-pilot2-calibration",
                    str(calibration_path),
                    "--device-name",
                    "Bedroom Headphones",
                    "--playback-log",
                    str(tmp_path / "missing.jsonl"),
                    "--output",
                    str(output_path),
                ])

            payload = json.loads(stdout.getvalue())
            saved = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["passed"])
        self.assertEqual(payload, saved)
        self.assertIn("cap_probe_log_present", payload["failed_criteria"])


def _pilot2_inputs(tmp_path: Path):
    calibration_path = tmp_path / "volume.json"
    playback_log_path = tmp_path / "playback.jsonl"
    save_volume_calibration(
        VolumeCalibration(
            "Bedroom Headphones",
            detectable_volume=0.01,
            identifiable_volume=0.04,
            comfortable_volume=0.06,
            backend_name="dry-run",
            notes="Daytime calibration before sleep pilots.",
        ),
        calibration_path,
    )
    _write_playback_event(playback_log_path)
    return calibration_path, playback_log_path


def _write_playback_event(
    playback_log_path: Path,
    *,
    effective_volume: float = 0.06,
    max_volume: float = 0.06,
    volume_capped: bool = True,
) -> None:
    event = {
        "cue_id": "test-cue",
        "status": "played",
        "backend_name": "dry-run",
        "requested_volume": 0.10,
        "effective_volume": effective_volume,
        "max_volume": max_volume,
        "volume_capped": volume_capped,
        "fade_in_seconds": 0.25,
        "fade_out_seconds": 0.25,
        "device_name": "Bedroom Headphones",
        "reason_codes": ["volume_capped", "dry_run", "device_selected"],
    }
    playback_log_path.write_text(json.dumps(event) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
