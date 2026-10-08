import tempfile
import unittest
from pathlib import Path

import numpy as np

from muse_tmr.data.polar_session import load_polar_session
from muse_tmr.reports.night_cardio import night_cardio_section, night_cardio_windows

from tests.polar_synthetic import write_raw_session


class NightCardioTest(unittest.TestCase):
    def test_windows_and_section_for_a_still_sleeper(self):
        rng = np.random.default_rng(21)
        with tempfile.TemporaryDirectory() as tmp:
            truth = write_raw_session(tmp, 20 * 60, rng, breaths_per_min=12.0)
            start, end = truth["wall0"], truth["wall0"] + 20 * 60
            windows = night_cardio_windows(load_polar_session(Path(tmp)), start, end)
            self.assertEqual(len(windows), 4)
            self.assertEqual([round(window["t_hours"] * 60) for window in windows], [0, 5, 10, 15])
            for window in windows:
                self.assertAlmostEqual(window["mean_hr_bpm"], 60.0, delta=2.0)
                self.assertEqual(window["resp_reliable"], 1.0)
                self.assertAlmostEqual(window["resp_rate_bpm"], 12.0, delta=0.5)

            section = night_cardio_section(Path(tmp), start, end)
            self.assertIn("Heart and breathing (Polar H10)", section)
            self.assertIn("<svg", section)
            self.assertIn("Breathing median <b>12.0/min</b> over 4 of 4 windows", section)
            self.assertNotIn("<script", section)

    def test_no_polar_folder_means_no_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(night_cardio_section(Path(tmp), 0.0, 600.0), "")

    def test_broken_polar_log_is_reported_not_raised(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            polar = Path(tmp) / "polar"
            polar.mkdir()
            (polar / "raw_notifications.jsonl").write_text("{}\n")
            with patch("muse_tmr.data.polar_session.load_polar_session", side_effect=ValueError("torn file")):
                section = night_cardio_section(Path(tmp), 0.0, 600.0)
            self.assertIn("could not be read: torn file", section)

if __name__ == "__main__":
    unittest.main()
