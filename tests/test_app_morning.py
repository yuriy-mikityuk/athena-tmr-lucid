import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from muse_tmr.app import AppConfig, create_local_app_server, morning
from muse_tmr.protocol import NightPuzzleSession, PuzzleCatalog, PuzzleCueAssignment, PuzzleTask
from muse_tmr.reports import load_dream_report, load_morning_retest

PUZZLES = ("p1", "p2", "p3", "p4")


def write_night(protocol_dir, session_file="night-001_puzzles.json", session_id="night-001", catalog_file="puzzle_catalog.json", assignment=True):
    protocol_dir.mkdir(parents=True, exist_ok=True)
    PuzzleCatalog(
        puzzles=tuple(PuzzleTask(puzzle_id=puzzle, prompt=f"Prompt {puzzle}", solution=f"Answer {puzzle}") for puzzle in PUZZLES)
    ).save(protocol_dir / catalog_file)
    NightPuzzleSession(session_id=session_id, puzzle_ids=PUZZLES, puzzle_count=4).save(protocol_dir / session_file)
    if assignment:
        PuzzleCueAssignment(
            session_id=session_id, cued_puzzle_ids=("p2", "p3"), uncued_puzzle_ids=("p1", "p4"), seed=7
        ).save(protocol_dir / f"{session_id}_assignment.json")


def dream_body(**overrides):
    body = {
        "night": "night-001",
        "lucid": "no",
        "cues_heard": "yes",
        "confidence": 0.6,
        "dream_text": "A staircase that kept folding.",
        "puzzle_links": {"p3": "the folding stairs", "p1": "  "},
    }
    body.update(overrides)
    return body


def retest_body(**overrides):
    body = {
        "night": "night-001",
        "results": [
            {"puzzle_id": puzzle, "response": f"try {puzzle}", "solved": puzzle == "p2", "duration_seconds": 40 + index, "confidence": 0.5}
            for index, puzzle in enumerate(PUZZLES)
        ],
    }
    body.update(overrides)
    return body


class TestMorningNights(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.protocol = Path(self._tmp.name) / "data" / "protocol"
        self.reports = Path(self._tmp.name) / "data" / "reports"

    def tearDown(self):
        self._tmp.cleanup()

    def test_finds_a_night_whatever_its_files_are_called(self):
        write_night(self.protocol)
        write_night(self.protocol, "pilot5_smoke_session.json", "pilot5-smoke", "pilot5_smoke_catalog.json")
        os.utime(self.protocol / "night-001_puzzles.json", (1, 1))  # the older of the two

        nights = morning.find_nights(self.protocol)
        self.assertEqual([night.name for night in nights], ["pilot5_smoke", "night-001"])
        smoke, runbook = nights
        self.assertEqual(smoke.catalog_path.name, "pilot5_smoke_catalog.json")
        self.assertEqual(runbook.catalog_path.name, "puzzle_catalog.json")
        self.assertEqual(smoke.assignment.session_id, "pilot5-smoke")
        self.assertEqual(runbook.assignment.session_id, "night-001")

    def test_a_catalog_must_hold_every_puzzle_and_an_assignment_its_session(self):
        write_night(self.protocol, assignment=False)
        PuzzleCatalog(puzzles=(PuzzleTask(puzzle_id="p1", prompt="Only one", solution="x"),)).save(self.protocol / "night-001_catalog.json")
        PuzzleCueAssignment(session_id="another-night", cued_puzzle_ids=("p1",), uncued_puzzle_ids=("p2",), seed=1).save(
            self.protocol / "another_assignment.json"
        )
        (self.protocol / "notes.json").write_text("[1, 2]")

        (night,) = morning.find_nights(self.protocol)
        self.assertEqual(night.catalog_path.name, "puzzle_catalog.json")
        self.assertIsNone(night.assignment)
        payload = morning.nights_payload(self.protocol, self.reports)["nights"][0]
        self.assertFalse(payload["assignment_found"])

    def test_the_page_never_learns_which_puzzles_were_cued(self):
        write_night(self.protocol)
        morning.save_retest(self.protocol, self.reports, retest_body())

        payload = morning.night_payload(self.protocol, self.reports, "night-001")
        self.assertEqual([puzzle["prompt"] for puzzle in payload["puzzles"]], [f"Prompt {p}" for p in PUZZLES])
        text = json.dumps(payload)
        for leak in ("cued", "cue_condition", "uncued", "Answer p"):
            self.assertNotIn(leak, text)
        # The saved file keeps the conditions for the analysis.
        saved = load_morning_retest(self.reports / "night-001_retest.json")
        self.assertEqual({r.puzzle_id: r.cue_condition for r in saved.results}, {"p1": "uncued", "p2": "cued", "p3": "cued", "p4": "uncued"})


class TestMorningSaving(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.protocol = Path(self._tmp.name) / "data" / "protocol"
        self.reports = Path(self._tmp.name) / "data" / "reports"
        write_night(self.protocol)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_dream_report_goes_where_the_runbook_puts_it(self):
        result = morning.save_dream_report(self.protocol, self.reports, dream_body())
        self.assertEqual(result["saved"], "night-001_dream_report.json")

        report = load_dream_report(self.reports / "night-001_dream_report.json")
        self.assertEqual((report.session_id, report.lucid, report.cues_heard, report.confidence), ("night-001", False, True, 0.6))
        self.assertEqual(report.incorporated_puzzle_ids, ("p3",))
        saved = morning.night_payload(self.protocol, self.reports, "night-001")["dream_report"]
        self.assertEqual(saved["puzzle_links"], {"p3": "the folding stairs"})

    def test_saving_again_needs_replace(self):
        morning.save_dream_report(self.protocol, self.reports, dream_body())
        with self.assertRaises(morning.MorningFileExists):
            morning.save_dream_report(self.protocol, self.reports, dream_body(dream_text="Changed."))
        morning.save_dream_report(self.protocol, self.reports, dream_body(dream_text="Changed.", replace=True))
        self.assertEqual(load_dream_report(self.reports / "night-001_dream_report.json").dream_text, "Changed.")

    def test_the_retest_needs_every_puzzle_and_valid_answers(self):
        with self.assertRaises(ValueError):
            morning.save_retest(self.protocol, self.reports, retest_body(results=retest_body()["results"][:3]))
        with self.assertRaises(ValueError):
            bad = retest_body()
            bad["results"][0]["confidence"] = 7
            morning.save_retest(self.protocol, self.reports, bad)
        with self.assertRaises(ValueError):
            morning.save_dream_report(self.protocol, self.reports, dream_body(lucid="maybe"))
        self.assertFalse(self.reports.exists())

        morning.save_retest(self.protocol, self.reports, retest_body())
        retest = load_morning_retest(self.reports / "night-001_retest.json")
        self.assertEqual(retest.solved_count, 1)
        self.assertEqual([r.duration_seconds for r in retest.results], [40, 41, 42, 43])

    def test_the_retest_needs_the_nights_assignment(self):
        (self.protocol / "night-001_assignment.json").unlink()
        with self.assertRaises(ValueError) as raised:
            morning.save_retest(self.protocol, self.reports, retest_body())
        self.assertIn("no cue assignment", str(raised.exception))


class TestMorningEndpoints(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        data = Path(self._tmp.name) / "data"
        write_night(data / "protocol")
        self.server = create_local_app_server(AppConfig(port=0, source="mock"), recordings_base=data / "recordings")
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.app_state.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def request(self, path, body=None):
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="GET" if body is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_lists_shows_and_saves_a_night(self):
        status, payload = self.request("/api/morning/nights")
        self.assertEqual((status, [night["name"] for night in payload["nights"]]), (200, ["night-001"]))
        status, payload = self.request("/api/morning/night?name=night-001")
        self.assertEqual((status, payload["puzzle_count"], payload["dream_report"]), (200, 4, None))
        self.assertEqual(self.request("/api/morning/night?name=nope")[0], 404)

        self.assertEqual(self.request("/api/morning/dream-report", dream_body())[0], 200)
        status, payload = self.request("/api/morning/dream-report", dream_body())
        self.assertEqual((status, payload["exists"]), (409, True))
        self.assertEqual(self.request("/api/morning/retest", retest_body(night="nope"))[0], 404)
        self.assertEqual(self.request("/api/morning/retest", {"night": "night-001", "results": [{"puzzle_id": "p1"}]})[0], 400)
        self.assertEqual(self.request("/api/morning/retest", retest_body())[0], 200)

        status, payload = self.request("/api/morning/nights")
        night = payload["nights"][0]
        self.assertTrue(night["dream_report_saved"] and night["retest_saved"])


if __name__ == "__main__":
    unittest.main()
