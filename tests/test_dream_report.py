import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from muse_tmr.cli.main import main
from muse_tmr.protocol import NightPuzzleSession, PuzzleCatalog, PuzzleTask
from muse_tmr.reports import (
    DreamPuzzleIncorporation,
    DreamReport,
    build_dream_report,
    load_dream_report,
)


class TestDreamReport(unittest.TestCase):
    def test_report_round_trips_json_and_counts_puzzle_links(self):
        report = DreamReport(
            report_id="report-001",
            session_id="night-001",
            lucid=True,
            cues_heard=False,
            confidence=0.75,
            dream_text="I saw a blue key on a desk.",
            puzzle_incorporations=(
                DreamPuzzleIncorporation(
                    puzzle_id="p1",
                    cue_id="cue-p1",
                    dream_content="blue key on a desk",
                    confidence=0.8,
                ),
            ),
            reported_at_utc="2026-05-13T00:00:00+00:00",
        )

        loaded = DreamReport.from_dict(report.to_dict())

        self.assertEqual(loaded.report_id, "report-001")
        self.assertTrue(loaded.lucid)
        self.assertFalse(loaded.cues_heard)
        self.assertEqual(loaded.incorporated_puzzle_ids, ("p1",))
        self.assertEqual(loaded.puzzle_incorporation_count, 1)

    def test_build_report_links_only_session_puzzles_and_uses_catalog_cue_ids(self):
        session = NightPuzzleSession(
            session_id="night-001",
            puzzle_ids=("p1", "p2"),
            puzzle_count=2,
        )
        catalog = PuzzleCatalog(
            puzzles=(
                PuzzleTask("p1", "Puzzle 1", "Answer 1", cue_id="cue-p1"),
                PuzzleTask("p2", "Puzzle 2", "Answer 2", cue_id="cue-p2"),
            )
        )

        report = build_dream_report(
            session,
            catalog=catalog,
            lucid=False,
            cues_heard=True,
            confidence=0.6,
            dream_text="There was a locked room.",
            puzzle_incorporation_text={"p2": "the second puzzle answer appeared"},
        )

        self.assertEqual(report.session_id, "night-001")
        self.assertEqual(report.puzzle_incorporations[0].puzzle_id, "p2")
        self.assertEqual(report.puzzle_incorporations[0].cue_id, "cue-p2")

    def test_build_report_rejects_unknown_puzzle_links(self):
        session = NightPuzzleSession(
            session_id="night-001",
            puzzle_ids=("p1",),
            puzzle_count=1,
        )

        with self.assertRaises(ValueError):
            build_dream_report(
                session,
                lucid=False,
                cues_heard=False,
                confidence=0.5,
                dream_text="No recall.",
                puzzle_incorporation_text={"p2": "not in session"},
            )

    def test_report_rejects_duplicate_puzzle_links(self):
        with self.assertRaises(ValueError):
            DreamReport(
                session_id="night-001",
                lucid=False,
                cues_heard=False,
                confidence=0.5,
                dream_text="Fragmented recall.",
                puzzle_incorporations=(
                    DreamPuzzleIncorporation("p1", "first"),
                    DreamPuzzleIncorporation("p1", "second"),
                ),
            )

    def test_cli_records_dream_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            session_path = tmp_path / "session.json"
            catalog_path = tmp_path / "catalog.json"
            report_path = tmp_path / "dream_report.json"
            NightPuzzleSession(
                session_id="night-001",
                puzzle_ids=("p1", "p2"),
                puzzle_count=2,
            ).save(session_path)
            PuzzleCatalog(
                puzzles=(
                    PuzzleTask("p1", "Puzzle 1", "Answer 1", cue_id="cue-p1"),
                    PuzzleTask("p2", "Puzzle 2", "Answer 2", cue_id="cue-p2"),
                )
            ).save(catalog_path)

            with redirect_stdout(io.StringIO()):
                code = main([
                    "record-dream-report",
                    str(session_path),
                    "--catalog",
                    str(catalog_path),
                    "--output",
                    str(report_path),
                    "--lucid",
                    "yes",
                    "--cues-heard",
                    "no",
                    "--confidence",
                    "0.7",
                    "--dream-text",
                    "I found Answer 1 in a notebook.",
                    "--puzzle-link",
                    "p1=Answer 1 appeared in a notebook",
                ])

            report = load_dream_report(report_path)

        self.assertEqual(code, 0)
        self.assertTrue(report.lucid)
        self.assertFalse(report.cues_heard)
        self.assertEqual(report.confidence, 0.7)
        self.assertEqual(report.puzzle_incorporations[0].cue_id, "cue-p1")

    def test_saved_json_uses_stable_schema_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report = DreamReport(
                session_id="night-001",
                lucid=False,
                cues_heard=False,
                confidence=0.5,
                dream_text="No recall.",
            )
            report.save(report_path)

            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["session_id"], "night-001")
        self.assertEqual(payload["puzzle_incorporation_count"], 0)
        self.assertIn("puzzle_incorporations", payload)


if __name__ == "__main__":
    unittest.main()
