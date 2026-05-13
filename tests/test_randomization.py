import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from muse_tmr.cli.main import build_parser, main
from muse_tmr.protocol import (
    NightPuzzleSession,
    PuzzleCatalog,
    PuzzleCueAssignment,
    PuzzleTask,
    assign_cued_uncued_puzzles,
    load_puzzle_cue_assignment,
)
from muse_tmr.protocol.randomization import split_cued_uncued


class TestRandomization(unittest.TestCase):
    def test_split_is_deterministic(self):
        first = split_cued_uncued(["a", "b", "c", "d"], seed=7)
        second = split_cued_uncued(["a", "b", "c", "d"], seed=7)

        self.assertEqual(first, second)
        self.assertEqual(len(first.cued), 2)
        self.assertEqual(len(first.uncued), 2)

    def test_puzzle_cue_assignment_is_deterministic_and_balanced(self):
        session = NightPuzzleSession(
            session_id="night-001",
            puzzle_ids=("p1", "p2", "p3", "p4"),
            puzzle_count=4,
        )

        first = assign_cued_uncued_puzzles(session, seed=17)
        second = assign_cued_uncued_puzzles(session, seed=17)

        self.assertEqual(first.cued_puzzle_ids, second.cued_puzzle_ids)
        self.assertEqual(first.uncued_puzzle_ids, second.uncued_puzzle_ids)
        self.assertEqual(len(first.cued_puzzle_ids), 2)
        self.assertEqual(len(first.uncued_puzzle_ids), 2)
        self.assertEqual(set(first.all_puzzle_ids), set(session.puzzle_ids))
        self.assertEqual(first.scheduled_puzzle_ids, first.cued_puzzle_ids)

    def test_assignment_round_trip_preserves_cued_and_uncued_groups(self):
        assignment = PuzzleCueAssignment(
            session_id="night-001",
            cued_puzzle_ids=("p1", "p3"),
            uncued_puzzle_ids=("p2", "p4"),
            seed=7,
            generated_at_utc="2026-05-13T00:00:00+00:00",
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "assignment.json"
            assignment.save(path)
            loaded = load_puzzle_cue_assignment(path)

        self.assertEqual(loaded.cued_puzzle_ids, ("p1", "p3"))
        self.assertEqual(loaded.uncued_puzzle_ids, ("p2", "p4"))
        self.assertEqual(loaded.seed, 7)
        self.assertEqual(loaded.to_dict()["scheduled_puzzle_ids"], ["p1", "p3"])

    def test_uncued_puzzles_are_never_schedulable(self):
        assignment = PuzzleCueAssignment(
            session_id="night-001",
            cued_puzzle_ids=("p1", "p3"),
            uncued_puzzle_ids=("p2", "p4"),
            seed=7,
        )
        catalog = PuzzleCatalog(
            puzzles=(
                PuzzleTask("p1", "Puzzle 1", "Answer 1", cue_id="cue-1"),
                PuzzleTask("p2", "Puzzle 2", "Answer 2", cue_id="cue-2"),
                PuzzleTask("p3", "Puzzle 3", "Answer 3", cue_id="cue-3"),
                PuzzleTask("p4", "Puzzle 4", "Answer 4", cue_id="cue-4"),
            )
        )

        self.assertEqual(assignment.scheduled_cue_ids(catalog), ("cue-1", "cue-3"))
        with self.assertRaises(ValueError):
            assignment.ensure_schedulable("p2")
        with self.assertRaises(KeyError):
            assignment.ensure_schedulable("p9")

    def test_assignment_must_cover_session_exactly(self):
        session = NightPuzzleSession(
            session_id="night-001",
            puzzle_ids=("p1", "p2", "p3", "p4"),
            puzzle_count=4,
        )
        incomplete = PuzzleCueAssignment(
            session_id="night-001",
            cued_puzzle_ids=("p1", "p2"),
            uncued_puzzle_ids=("p3",),
            seed=7,
        )

        with self.assertRaises(ValueError):
            incomplete.validate_against_session(session)

    def test_assignment_rejects_overlapping_groups(self):
        with self.assertRaises(ValueError):
            PuzzleCueAssignment(
                session_id="night-001",
                cued_puzzle_ids=("p1", "p2"),
                uncued_puzzle_ids=("p2", "p3"),
                seed=7,
            )


class TestRandomizationCli(unittest.TestCase):
    def test_assign_puzzle_cues_command_parses_seed(self):
        args = build_parser().parse_args([
            "assign-puzzle-cues",
            "data/protocol/night-001_puzzles.json",
            "--output",
            "data/protocol/night-001_assignment.json",
            "--seed",
            "17",
        ])

        self.assertEqual(args.command, "assign-puzzle-cues")
        self.assertEqual(args.session, Path("data/protocol/night-001_puzzles.json"))
        self.assertEqual(args.output, Path("data/protocol/night-001_assignment.json"))
        self.assertEqual(args.seed, 17)

    def test_assign_puzzle_cues_cli_writes_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            session_path = tmp_path / "session.json"
            assignment_path = tmp_path / "assignment.json"
            NightPuzzleSession(
                session_id="night-001",
                puzzle_ids=("p1", "p2", "p3", "p4"),
                puzzle_count=4,
            ).save(session_path)

            with redirect_stdout(io.StringIO()) as output:
                exit_code = main([
                    "assign-puzzle-cues",
                    str(session_path),
                    "--output",
                    str(assignment_path),
                    "--seed",
                    "17",
                ])
            assignment = load_puzzle_cue_assignment(assignment_path)

        self.assertEqual(exit_code, 0)
        self.assertIn("puzzle cue assignment generated", output.getvalue())
        self.assertEqual(assignment.session_id, "night-001")
        self.assertEqual(len(assignment.cued_puzzle_ids), 2)
        self.assertEqual(len(assignment.uncued_puzzle_ids), 2)
        self.assertEqual(assignment.scheduled_puzzle_ids, assignment.cued_puzzle_ids)


if __name__ == "__main__":
    unittest.main()
