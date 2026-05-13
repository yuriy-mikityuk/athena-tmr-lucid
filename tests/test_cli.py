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

    def test_stream_command_parses_openmuse_lsl_source(self):
        args = build_parser().parse_args([
            "stream",
            "--source",
            "openmuse",
            "--duration-seconds",
            "5",
            "--require-lsl-stream",
            "eeg",
            "--require-lsl-stream",
            "imu",
            "--lsl-resolve-timeout",
            "2.5",
            "--openmuse-eeg-stream",
            "Muse_EEG",
            "--openmuse-imu-stream",
            "Muse_ACCGYRO",
        ])

        self.assertEqual(args.command, "stream")
        self.assertEqual(args.source, "openmuse")
        self.assertEqual(args.duration_seconds, 5)
        self.assertEqual(args.require_lsl_stream, ["eeg", "imu"])
        self.assertEqual(args.lsl_resolve_timeout, 2.5)
        self.assertEqual(args.openmuse_eeg_stream, "Muse_EEG")
        self.assertEqual(args.openmuse_imu_stream, "Muse_ACCGYRO")

    def test_stream_command_parses_sdk_stub_source(self):
        args = build_parser().parse_args([
            "stream",
            "--source",
            "sdk",
            "--sdk-path",
            "/tmp/local-muse-sdk",
            "--duration-seconds",
            "5",
        ])

        self.assertEqual(args.command, "stream")
        self.assertEqual(args.source, "sdk")
        self.assertEqual(args.sdk_path, Path("/tmp/local-muse-sdk"))
        self.assertEqual(args.duration_seconds, 5)

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

    def test_train_rem_classifier_command_parses_model_options(self):
        args = build_parser().parse_args([
            "train-rem-classifier",
            "data/annotations/session.csv",
            "--output",
            "data/models/personal_rem_model.json",
            "--feature",
            "p_rem",
            "--feature",
            "feature_score_stillness",
            "--epochs",
            "500",
            "--threshold",
            "0.6",
        ])

        self.assertEqual(args.command, "train-rem-classifier")
        self.assertEqual(args.annotations, Path("data/annotations/session.csv"))
        self.assertEqual(args.output, Path("data/models/personal_rem_model.json"))
        self.assertEqual(args.features, ["p_rem", "feature_score_stillness"])
        self.assertEqual(args.epochs, 500)
        self.assertEqual(args.threshold, 0.6)

    def test_cue_library_commands_parse_paths_and_filters(self):
        create_args = build_parser().parse_args([
            "create-cue-library",
            "--output",
            "data/cues/starter.json",
        ])
        validate_args = build_parser().parse_args([
            "validate-cue-library",
            "data/cues/starter.json",
            "--skip-file-check",
        ])
        list_args = build_parser().parse_args([
            "list-cues",
            "data/cues/starter.json",
            "--protocol",
            "puzzle",
            "--tag",
            "generated",
        ])

        self.assertEqual(create_args.command, "create-cue-library")
        self.assertEqual(create_args.output, Path("data/cues/starter.json"))
        self.assertEqual(validate_args.command, "validate-cue-library")
        self.assertTrue(validate_args.skip_file_check)
        self.assertEqual(list_args.command, "list-cues")
        self.assertEqual(list_args.protocol, "puzzle")
        self.assertEqual(list_args.tag, "generated")

    def test_tlr_protocol_commands_parse_paths(self):
        create_args = build_parser().parse_args([
            "create-tlr-cue",
            "--output",
            "data/cues/tlr.json",
        ])
        train_args = build_parser().parse_args([
            "train-tlr-cue",
            "data/cues/tlr.json",
            "--output",
            "data/protocol/tlr_training.json",
            "--event-log",
            "data/protocol/tlr_training.jsonl",
        ])
        block_args = build_parser().parse_args([
            "plan-tlr-block",
            "data/cues/tlr.json",
            "--output",
            "data/protocol/tlr_block.json",
            "--disabled",
        ])

        self.assertEqual(create_args.command, "create-tlr-cue")
        self.assertEqual(create_args.output, Path("data/cues/tlr.json"))
        self.assertEqual(train_args.command, "train-tlr-cue")
        self.assertEqual(train_args.backend, "dry-run")
        self.assertEqual(block_args.command, "plan-tlr-block")
        self.assertTrue(block_args.disabled)

    def test_puzzle_protocol_commands_parse_paths(self):
        import_args = build_parser().parse_args([
            "import-puzzles",
            "puzzles.csv",
            "--output",
            "data/protocol/catalog.json",
        ])
        attempt_args = build_parser().parse_args([
            "record-puzzle-attempt",
            "data/protocol/catalog.json",
            "--puzzle-id",
            "p1",
            "--response",
            "answer",
            "--duration-seconds",
            "30",
            "--solved",
        ])
        association_args = build_parser().parse_args([
            "record-association-check",
            "data/protocol/session.json",
            "--catalog",
            "data/protocol/catalog.json",
            "--puzzle-id",
            "p1",
            "--response",
            "answer",
        ])
        assignment_args = build_parser().parse_args([
            "assign-puzzle-cues",
            "data/protocol/session.json",
            "--output",
            "data/protocol/assignment.json",
            "--seed",
            "17",
        ])

        self.assertEqual(import_args.command, "import-puzzles")
        self.assertEqual(import_args.output, Path("data/protocol/catalog.json"))
        self.assertEqual(attempt_args.command, "record-puzzle-attempt")
        self.assertTrue(attempt_args.solved)
        self.assertEqual(association_args.command, "record-association-check")
        self.assertEqual(association_args.catalog, Path("data/protocol/catalog.json"))
        self.assertEqual(assignment_args.command, "assign-puzzle-cues")
        self.assertEqual(assignment_args.seed, 17)

    def test_morning_report_command_parses_dream_report_fields(self):
        args = build_parser().parse_args([
            "record-dream-report",
            "data/protocol/session.json",
            "--catalog",
            "data/protocol/catalog.json",
            "--output",
            "data/reports/night-001_dream_report.json",
            "--lucid",
            "yes",
            "--cues-heard",
            "no",
            "--confidence",
            "0.7",
            "--dream-text",
            "I saw the puzzle answer.",
            "--puzzle-link",
            "p1=the answer appeared",
            "--puzzle-link",
            "p2=the shape was in the dream",
        ])

        self.assertEqual(args.command, "record-dream-report")
        self.assertEqual(args.session, Path("data/protocol/session.json"))
        self.assertEqual(args.catalog, Path("data/protocol/catalog.json"))
        self.assertEqual(args.output, Path("data/reports/night-001_dream_report.json"))
        self.assertEqual(args.lucid, "yes")
        self.assertEqual(args.cues_heard, "no")
        self.assertEqual(args.confidence, 0.7)
        self.assertEqual(args.puzzle_link, [
            "p1=the answer appeared",
            "p2=the shape was in the dream",
        ])

    def test_morning_retest_command_parses_blind_results(self):
        args = build_parser().parse_args([
            "record-puzzle-retest",
            "data/protocol/session.json",
            "--catalog",
            "data/protocol/catalog.json",
            "--assignment",
            "data/protocol/assignment.json",
            "--output",
            "data/reports/night-001_retest.json",
            "--result",
            "p1=answer",
            "--result",
            "p2=wrong",
            "--solved",
            "p1",
            "--duration",
            "p1=12",
            "--duration",
            "p2=24",
            "--confidence",
            "p1=0.9",
            "--confidence",
            "p2=0.3",
        ])

        self.assertEqual(args.command, "record-puzzle-retest")
        self.assertEqual(args.session, Path("data/protocol/session.json"))
        self.assertEqual(args.catalog, Path("data/protocol/catalog.json"))
        self.assertEqual(args.assignment, Path("data/protocol/assignment.json"))
        self.assertEqual(args.output, Path("data/reports/night-001_retest.json"))
        self.assertEqual(args.result, ["p1=answer", "p2=wrong"])
        self.assertEqual(args.solved, ["p1"])
        self.assertEqual(args.duration, ["p1=12", "p2=24"])
        self.assertEqual(args.confidence, ["p1=0.9", "p2=0.3"])

    def test_cued_uncued_analysis_command_parses_report_inputs(self):
        args = build_parser().parse_args([
            "analyze-cued-uncued",
            "data/protocol/session.json",
            "--assignment",
            "data/protocol/assignment.json",
            "--retest",
            "data/reports/retest.json",
            "--dream-report",
            "data/reports/dream.json",
            "--scheduler-events",
            "data/reports/scheduler.jsonl",
            "--output",
            "data/reports/analysis.json",
            "--markdown-output",
            "data/reports/analysis.md",
            "--analysis-id",
            "analysis-001",
            "--min-group-size",
            "3",
        ])

        self.assertEqual(args.command, "analyze-cued-uncued")
        self.assertEqual(args.session, Path("data/protocol/session.json"))
        self.assertEqual(args.assignment, Path("data/protocol/assignment.json"))
        self.assertEqual(args.retest, Path("data/reports/retest.json"))
        self.assertEqual(args.dream_report, Path("data/reports/dream.json"))
        self.assertEqual(args.scheduler_events, Path("data/reports/scheduler.jsonl"))
        self.assertEqual(args.output, Path("data/reports/analysis.json"))
        self.assertEqual(args.markdown_output, Path("data/reports/analysis.md"))
        self.assertEqual(args.analysis_id, "analysis-001")
        self.assertEqual(args.min_group_size, 3)

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
