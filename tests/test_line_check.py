import unittest
from pathlib import Path

import numpy as np

from muse_tmr.cli.main import _calibration_record_command
from muse_tmr.protocol.calibration import (
    BATTERY_PULL_SAY,
    LINE_CHECK_DONE_SAY,
    LINE_CHECK_INTRO_SAY,
    LINE_CHECK_PRESETS,
    PROTOCOL,
    calibration_protocol,
    run_line_check,
)
from muse_tmr.reports.calibration_report import render_calibration_report
from muse_tmr.reports.line_check import line_levels, render_section, summarize

from tests.meditation_synthetic import FS, pink_noise


def eeg(seconds, rng, line_uv=0.0):
    t = np.arange(int(seconds * FS)) / FS
    signal = 3.0 * pink_noise(t.size, 1.0, rng) + 2.0 * np.sin(2 * np.pi * 10.0 * t)
    # Where the line sits in EEG-sample terms: at the optics rate, not 64.00.
    return signal + line_uv * np.sin(2 * np.pi * 63.92 * t + 0.3)


class LineLevelsTest(unittest.TestCase):
    def test_line_is_measured_and_plain_eeg_is_not_a_line(self):
        rng = np.random.default_rng(1)
        levels = line_levels({"AF7": eeg(60, rng, line_uv=30.0), "TP9": eeg(60, rng)})
        self.assertAlmostEqual(levels["AF7"]["amplitude_uv"], 30.0, delta=2.0)
        self.assertGreater(levels["AF7"]["height_db"], 20.0)
        self.assertEqual(levels["AF7"]["windows"], 6.0)
        self.assertLess(levels["TP9"]["amplitude_uv"], 1.0)
        self.assertLess(levels["TP9"]["height_db"], 6.0)

    def test_verdicts(self):
        line = {
            "AF7": {"amplitude_uv": 20.0, "height_db": 35.0, "windows": 12},
            "AF8": {"amplitude_uv": 15.0, "height_db": 30.0, "windows": 12},
        }
        none = {
            "AF7": {"amplitude_uv": 0.2, "height_db": 2.0, "windows": 12},
            "AF8": {"amplitude_uv": 0.3, "height_db": 3.0, "windows": 12},
        }
        short = {"AF7": {"amplitude_uv": 0.2, "height_db": 2.0, "windows": 3}}

        def run(*channels):
            return summarize(
                [{"index": i + 1, "preset": preset, "channels": c} for i, (preset, c) in enumerate(zip(LINE_CHECK_PRESETS, channels))]
            )

        self.assertEqual(run(line, none, line, none)["verdict"], "optics")
        self.assertEqual(run(line, line, line, none)["verdict"], "not_optics")
        self.assertEqual(run(none, none, none, none)["verdict"], "unclear")
        # Every segment has to be there: one failed or too short leaves it open.
        self.assertEqual(run(line, {}, line, {})["verdict"], "unclear")
        self.assertEqual(run(line, none, line, {})["verdict"], "unclear")
        self.assertEqual(run(line, none, {}, none)["verdict"], "unclear")
        self.assertEqual(run(line, none, line, short)["verdict"], "unclear")
        page = render_section(run(line, none, line, none))
        self.assertIn("the optics put it there", page)
        self.assertIn("20.0 µV / 35 dB", page)


class LineCheckRunTest(unittest.TestCase):
    def test_four_recordings_in_order_with_cues(self):
        spoken, recorded = [], []
        speaker = type(
            "Speaker",
            (),
            {"speak": lambda self, text: spoken.append(text), "wait": lambda self: spoken.append("<wait>")},
        )()

        def record(directory, preset):
            recorded.append((directory.name, preset))
            return 0 if preset == "p1034" else 3

        results = run_line_check([Path(f"/tmp/s{i}") for i in range(4)], speaker, record)
        self.assertEqual([preset for _name, preset in recorded], list(LINE_CHECK_PRESETS))
        self.assertEqual([result["returncode"] for result in results], [0, 3, 0, 3])
        # The intro and the closing cue are let finish before anything else is said.
        self.assertEqual(spoken[:2], [LINE_CHECK_INTRO_SAY, "<wait>"])
        self.assertEqual(spoken[-2:], [LINE_CHECK_DONE_SAY, "<wait>"])
        self.assertEqual(len(spoken), 8)

    def test_record_command_carries_the_preset(self):
        command = _calibration_record_command(Path("/tmp/x"), "p21", 120.0, with_polar=False, polar_address="AA")
        self.assertEqual(command[command.index("--preset") + 1], "p21")
        self.assertNotIn("--with-polar", command)
        self.assertNotIn("--polar-address", command)
        with_polar = _calibration_record_command(Path("/tmp/x"), "p1034", 1400.0, with_polar=True, polar_address="AA")
        self.assertIn("--with-polar", with_polar)
        self.assertEqual(with_polar[with_polar.index("--polar-address") + 1], "AA")


class BatteryPullTest(unittest.TestCase):
    def test_only_the_h10_minute_changes(self):
        pulled = calibration_protocol(battery_pull=True)
        self.assertEqual(calibration_protocol(), PROTOCOL)
        self.assertEqual([(s.name, s.start_s, s.end_s) for s in pulled], [(s.name, s.start_s, s.end_s) for s in PROTOCOL])
        changed = [segment for segment, original in zip(pulled, PROTOCOL) if segment != original]
        self.assertEqual([segment.name for segment in changed], ["h10_off"])
        self.assertEqual(changed[0].say, BATTERY_PULL_SAY)

    def test_calibration_report_shows_a_line_check(self):
        line = {"AF7": {"amplitude_uv": 20.0, "height_db": 35.0, "windows": 12}}
        none = {"AF7": {"amplitude_uv": 0.2, "height_db": 2.0, "windows": 12}}
        summary = {
            "recording": "x",
            "line_check": summarize(
                [{"index": i + 1, "preset": p, "channels": c} for i, (p, c) in enumerate(zip(LINE_CHECK_PRESETS, (line, none, line, none)))]
            ),
        }
        page = render_calibration_report(summary)
        self.assertIn("64 Hz line by headband mode", page)


if __name__ == "__main__":
    unittest.main()
