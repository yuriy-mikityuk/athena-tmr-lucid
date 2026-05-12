import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from muse_tmr.audio import (
    AudioPlayer,
    AudioCuePlayer,
    AudioPlaybackConfig,
    MockAudioBackend,
    TestCue,
    create_audio_backend,
)
from muse_tmr.cli.main import build_parser, main


class TestAudioCuePlayer(unittest.TestCase):
    def test_volume_cap_is_enforced_before_backend_playback(self):
        backend = MockAudioBackend()
        player = AudioCuePlayer(
            AudioPlaybackConfig(max_volume=0.20, default_volume=0.05),
            backend=backend,
        )

        result = player.play_test_cue(TestCue(duration_seconds=0.01), volume=0.80)

        self.assertTrue(result.played)
        self.assertTrue(result.volume_capped)
        self.assertEqual(result.requested_volume, 0.80)
        self.assertEqual(result.effective_volume, 0.20)
        self.assertEqual(backend.requests[0].effective_volume, 0.20)
        self.assertIn("volume_capped", result.reason_codes)

    def test_fade_and_device_selection_are_passed_to_backend_and_logs(self):
        backend = MockAudioBackend()
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "audio.jsonl"
            player = AudioCuePlayer(
                AudioPlaybackConfig(
                    max_volume=0.20,
                    fade_in_seconds=0.10,
                    fade_out_seconds=0.20,
                    device_name="Bedroom Headphones",
                    log_path=log_path,
                ),
                backend=backend,
            )

            result = player.play_test_cue(TestCue(duration_seconds=0.01), volume=0.05)
            event = json.loads(log_path.read_text(encoding="utf-8").strip())

        self.assertEqual(result.device_name, "Bedroom Headphones")
        self.assertEqual(backend.requests[0].device_name, "Bedroom Headphones")
        self.assertEqual(backend.requests[0].fade_in_seconds, 0.10)
        self.assertEqual(backend.requests[0].fade_out_seconds, 0.20)
        self.assertIn("device_selected", result.reason_codes)
        self.assertEqual(event["device_name"], "Bedroom Headphones")
        self.assertEqual(event["fade_in_seconds"], 0.10)

    def test_emergency_stop_blocks_future_playback_until_cleared(self):
        backend = MockAudioBackend()
        player = AudioCuePlayer(backend=backend)

        stop_result = player.emergency_stop()
        blocked = player.play_test_cue(TestCue(duration_seconds=0.01))
        player.clear_emergency_stop()
        played = player.play_test_cue(TestCue(duration_seconds=0.01))

        self.assertEqual(stop_result.status, "stopped")
        self.assertEqual(backend.stop_calls, 1)
        self.assertEqual(blocked.status, "blocked")
        self.assertIn("emergency_stop_active", blocked.reason_codes)
        self.assertTrue(played.played)

    def test_dry_run_backend_is_available_without_audio_device(self):
        player = AudioCuePlayer(backend=create_audio_backend("dry-run"))

        result = player.play_test_cue(TestCue(duration_seconds=0.01))

        self.assertTrue(result.played)
        self.assertEqual(result.backend_name, "dry-run")
        self.assertIn("dry_run", result.reason_codes)

    def test_invalid_volume_is_rejected(self):
        player = AudioCuePlayer(backend=MockAudioBackend())

        with self.assertRaises(ValueError):
            player.play_test_cue(volume=1.5)

    def test_audio_player_alias_keeps_legacy_max_volume_constructor(self):
        backend = MockAudioBackend()
        player = AudioPlayer(max_volume=0.10, backend=backend)

        result = player.play_test_cue(TestCue(duration_seconds=0.01), volume=0.20)

        self.assertEqual(result.effective_volume, 0.10)

    def test_playback_result_is_not_rem_gate_or_scheduler_decision(self):
        result = AudioCuePlayer(backend=MockAudioBackend()).play_test_cue(
            TestCue(duration_seconds=0.01)
        )

        self.assertFalse(hasattr(result, "gate_open"))
        self.assertFalse(hasattr(result, "should_play"))


class TestAudioCuePlayerCli(unittest.TestCase):
    def test_play_test_cue_command_parses_safe_audio_options(self):
        args = build_parser().parse_args([
            "play-test-cue",
            "--backend",
            "dry-run",
            "--volume",
            "0.3",
            "--max-volume",
            "0.2",
            "--fade-in-seconds",
            "0.1",
            "--fade-out-seconds",
            "0.2",
            "--device-name",
            "Bedroom Headphones",
        ])

        self.assertEqual(args.command, "play-test-cue")
        self.assertEqual(args.backend, "dry-run")
        self.assertEqual(args.volume, 0.3)
        self.assertEqual(args.max_volume, 0.2)
        self.assertEqual(args.device_name, "Bedroom Headphones")

    def test_play_test_cue_cli_works_with_dry_run_backend(self):
        with redirect_stdout(io.StringIO()) as output:
            exit_code = main([
                "play-test-cue",
                "--backend",
                "dry-run",
                "--duration-seconds",
                "0.01",
                "--volume",
                "0.3",
                "--max-volume",
                "0.2",
            ])

        self.assertEqual(exit_code, 0)
        self.assertIn("status=played", output.getvalue())
        self.assertIn("volume_capped=True", output.getvalue())

    def test_play_test_cue_cli_writes_jsonl_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "playback.jsonl"
            with redirect_stdout(io.StringIO()):
                exit_code = main([
                    "play-test-cue",
                    "--backend",
                    "dry-run",
                    "--duration-seconds",
                    "0.01",
                    "--log-path",
                    str(log_path),
                ])
            event = json.loads(log_path.read_text(encoding="utf-8").strip())

        self.assertEqual(exit_code, 0)
        self.assertEqual(event["status"], "played")
        self.assertEqual(event["backend_name"], "dry-run")


if __name__ == "__main__":
    unittest.main()
