import unittest
from pathlib import Path
from unittest.mock import patch

from muse_tmr.cli.main import _default_recording_dir, _resolve_output_dir, build_parser
from muse_tmr.sources.amused_source import AmusedSource


class TestCli(unittest.TestCase):
    def test_stream_command_parses_amused_source(self):
        args = build_parser().parse_args([
            "stream",
            "--source",
            "amused",
            "--duration-seconds",
            "3600",
        ])

        self.assertEqual(args.command, "stream")
        self.assertEqual(args.source, "amused")
        self.assertEqual(args.duration_seconds, 3600)

    def test_record_command_parses_overnight_duration(self):
        args = build_parser().parse_args([
            "record",
            "--source",
            "amused",
            "--duration-hours",
            "8",
        ])

        self.assertEqual(args.command, "record")
        self.assertEqual(args.duration_hours, 8.0)

    def test_replay_command_parses_time_range(self):
        args = build_parser().parse_args([
            "replay",
            "data/recordings/session",
            "--speed",
            "10",
            "--start-seconds",
            "30",
            "--end-seconds",
            "90",
        ])

        self.assertEqual(args.command, "replay")
        self.assertEqual(args.input, Path("data/recordings/session"))
        self.assertEqual(args.speed, 10.0)
        self.assertEqual(args.start_seconds, 30.0)
        self.assertEqual(args.end_seconds, 90.0)

    def test_annotate_template_command_parses_output_and_label(self):
        args = build_parser().parse_args([
            "annotate-template",
            "data/recordings/session",
            "--output",
            "data/annotations/session.csv",
            "--label",
            "unknown",
            "--epoch-seconds",
            "30",
            "--stride-seconds",
            "10",
        ])

        self.assertEqual(args.command, "annotate-template")
        self.assertEqual(args.input, Path("data/recordings/session"))
        self.assertEqual(args.output, Path("data/annotations/session.csv"))
        self.assertEqual(args.label, "unknown")
        self.assertEqual(args.epoch_seconds, 30.0)
        self.assertEqual(args.stride_seconds, 10.0)

    def test_amused_source_import_does_not_cycle(self):
        self.assertEqual(AmusedSource.strategy, "forked-source")

    def test_default_recording_dir_avoids_root_when_cwd_is_unusable(self):
        with patch("muse_tmr.cli.main.Path.cwd", return_value=Path("/")):
            output_dir = _default_recording_dir()

        self.assertTrue(output_dir.is_absolute())
        self.assertEqual(output_dir.parent.name, "recordings")
        self.assertEqual(output_dir.parent.parent.name, "data")
        self.assertNotEqual(output_dir.parent.parent.parent, Path("/"))

    def test_relative_output_dir_avoids_root_when_cwd_is_unusable(self):
        with patch("muse_tmr.cli.main.Path.cwd", return_value=Path("/")):
            output_dir = _resolve_output_dir(Path("data/recordings/smoke"))

        self.assertTrue(output_dir.is_absolute())
        self.assertTrue(str(output_dir).endswith("data/recordings/smoke"))
        self.assertFalse(str(output_dir).startswith("/data/"))


if __name__ == "__main__":
    unittest.main()
