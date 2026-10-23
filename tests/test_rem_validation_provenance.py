"""Provenance of the REM check against a reference stager (Initiative 5, #229).

Runs scripts/validate_rem_detection.py on synthetic input with the stager
subprocess replaced by a fake hypnogram, so no YASA or GSSC venv is needed.
"""

import importlib.util
import io
import json
import shlex
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

from muse_tmr.models import heuristic_rem_detector  # noqa: E402
from muse_tmr.models.rem_detector import RemPrediction  # noqa: E402
from muse_tmr.presets import preset_gate_thresholds  # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vrd = _load("validate_rem_detection")
html_report = _load("_rem_validation_html")
gssc_stage = _load("_gssc_stage")
yasa_stage = _load("_yasa_stage")

PROVENANCE_KEYS = {
    "command_line",
    "timestamp_utc",
    "muse_tmr_version",
    "git_commit",
    "python",
    "numpy",
    "scipy",
    "resample_hz",
    "epoch_seconds",
    "preset",
    "enter_threshold",
    "exit_threshold",
    "eeg",
    "eog",
    "channels_not_passed",
    "stager",
}
STAGER_KEYS = {"tool", "package_version", "torch_version", "mne_version", "returns_probabilities"}

N_EPOCHS = 12
T0 = 1000.0
REM_EPOCHS = range(4, 8)


def _fake_collect(recording_dir, epoch_seconds):
    predictions = [
        (T0 + k * epoch_seconds, RemPrediction(probability=0.95 if k in REM_EPOCHS else 0.2))
        for k in range(N_EPOCHS)
    ]
    n_samples = int(N_EPOCHS * epoch_seconds * 256)
    channels = {name: np.zeros(n_samples, dtype=np.float32) for name in vrd.EEG_CHANNELS}
    return {"predictions": predictions, "channels": channels, "sfreq": 256.0, "t0": T0, "n_samples": n_samples}


def _fake_hypnogram(reference, eog):
    return {
        "sfreq": 100.0,
        "eeg": "AF7",
        "eog": None if eog.lower() == "none" else eog,
        "epoch_seconds": 30,
        "stager": {
            "tool": reference,
            "package_version": "0.0.9-fake",
            "torch_version": "torch-fake",
            "mne_version": "mne-fake",
            "returns_probabilities": False,
        },
        "stage_counts": {"N2": N_EPOCHS - len(REM_EPOCHS), "REM": len(REM_EPOCHS)},
        "epochs": [
            {"epoch": k, "stage": "REM" if k in REM_EPOCHS else "N2", "proba_rem": 0.0, "confidence": 1.0}
            for k in range(N_EPOCHS)
        ],
    }


def _run(reference="gssc", eog=None, preset="p21"):
    calls = []

    def fake_reference(ref, npz_path, eeg, eog_arg, python_path):
        calls.append((ref, eeg, eog_arg))
        return _fake_hypnogram(ref, eog_arg)

    argv = ["scripts/validate_rem_detection.py", "data/recordings/synthetic night", "--reference", reference]
    with mock.patch.object(vrd, "collect", _fake_collect), mock.patch.object(vrd, "run_reference", fake_reference):
        with redirect_stdout(io.StringIO()):
            result = vrd.run(
                Path("synthetic_night"), "AF7", eog, Path(sys.executable), 30.0,
                preset, reference, None, argv=argv,
            )
    return result, calls, argv


class EogResolutionTest(unittest.TestCase):
    def test_defaults_per_reference(self):
        self.assertEqual(vrd.resolve_eog("gssc", None), "none")
        self.assertEqual(vrd.resolve_eog("yasa", None), "AF8")

    def test_given_value_wins(self):
        self.assertEqual(vrd.resolve_eog("gssc", "AF8"), "AF8")
        self.assertEqual(vrd.resolve_eog("yasa", "none"), "none")

    def test_the_cli_leaves_eog_unset(self):
        argv = ["validate_rem_detection.py", "rec", "--reference", "gssc"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(vrd, "run") as run:
            run.side_effect = SystemExit(0)
            with mock.patch.object(Path, "exists", return_value=True):
                with self.assertRaises(SystemExit):
                    vrd.main()
        self.assertIsNone(run.call_args.args[2])


class ProvenanceTest(unittest.TestCase):
    def test_gssc_run_on_fake_stager_result(self):
        result, calls, argv = _run("gssc")

        self.assertEqual(calls, [("gssc", "AF7", "none")])
        self.assertEqual(result["kappa_definition"], "binary REM-vs-not κ against an automated stager; not five-class")
        provenance = result["provenance"]
        self.assertEqual(set(provenance), PROVENANCE_KEYS)
        self.assertEqual(set(provenance["stager"]), STAGER_KEYS)
        self.assertEqual(shlex.split(provenance["command_line"]), argv)
        self.assertIsNone(provenance["eog"])
        self.assertEqual(provenance["eeg"], "AF7")
        self.assertEqual(provenance["channels_not_passed"], ["AF8", "TP9", "TP10"])
        self.assertEqual(provenance["resample_hz"], 100.0)
        self.assertEqual(provenance["epoch_seconds"], 30.0)
        self.assertEqual(provenance["preset"], "p21")
        self.assertEqual(
            (provenance["enter_threshold"], provenance["exit_threshold"]), preset_gate_thresholds("p21")
        )
        self.assertEqual(provenance["stager"]["tool"], "gssc")
        self.assertEqual(provenance["stager"]["package_version"], "0.0.9-fake")
        self.assertIs(provenance["stager"]["returns_probabilities"], False)
        self.assertEqual(provenance["numpy"], np.__version__)
        self.assertTrue(provenance["timestamp_utc"].endswith("+00:00"))
        # The --output file is this dict without "matched"; it has to serialise as is.
        json.dumps({k: v for k, v in result.items() if k != "matched"})

    def test_yasa_keeps_af8_as_eog(self):
        result, calls, _ = _run("yasa")
        self.assertEqual(calls, [("yasa", "AF7", "AF8")])
        self.assertEqual(result["provenance"]["eog"], "AF8")
        self.assertEqual(result["provenance"]["channels_not_passed"], ["TP9", "TP10"])

    def test_gssc_with_af8_asked_for(self):
        result, calls, _ = _run("gssc", eog="AF8")
        self.assertEqual(calls, [("gssc", "AF7", "AF8")])
        self.assertEqual(result["provenance"]["channels_not_passed"], ["TP9", "TP10"])

    def test_hypnogram_without_stager_block(self):
        provenance = vrd.build_provenance(
            argv=["x"], reference="yasa", hypno={}, eeg="AF7", eog="AF8", preset=None,
            enter_threshold=0.8, exit_threshold=0.7, resample_hz=100.0, epoch_seconds=30.0,
        )
        self.assertEqual(provenance["stager"]["tool"], "yasa")
        self.assertIsNone(provenance["stager"]["package_version"])

    def test_html_labels(self):
        result, _, _ = _run("gssc")
        page = html_report.build_html(result)
        self.assertIn("eog none", page)
        self.assertNotIn("eog None", page)
        self.assertIn("binary REM-vs-not κ against an automated stager; not five-class", page)
        self.assertIn("Stager gssc 0.0.9-fake", page)
        self.assertIn("channels not given to it: AF8, TP9, TP10", page)


class GsscUnpackTest(unittest.TestCase):
    def test_two_tuple_of_gssc_0_0_9(self):
        stages, probs = gssc_stage.unpack_infer((np.array([0, 4, 2]), np.array([0, 30, 60])))
        self.assertEqual(stages, [0, 4, 2])
        self.assertIsNone(probs)
        rows = gssc_stage.epoch_rows(stages, probs)
        self.assertEqual([r["stage"] for r in rows], ["Wake", "REM", "N2"])
        self.assertEqual([r["proba_rem"] for r in rows], [0.0, 1.0, 0.0])

    def test_three_tuple_with_probabilities(self):
        probs = np.array([[0.7, 0.1, 0.1, 0.05, 0.05], [0.1, 0.1, 0.1, 0.1, 0.6]])
        stages, kept = gssc_stage.unpack_infer((np.array([0, 4]), np.array([0, 30]), probs))
        self.assertEqual(stages, [0, 4])
        self.assertIsNotNone(kept)
        rows = gssc_stage.epoch_rows(stages, kept)
        self.assertAlmostEqual(rows[1]["proba_rem"], 0.6)
        self.assertAlmostEqual(rows[0]["confidence"], 0.7)

    def test_three_tuple_without_usable_probabilities(self):
        stages = np.array([0, 4])
        times = np.array([0, 30])
        log_probs = np.log(np.full((2, 5), 0.2))
        for third in (None, log_probs, np.full((2, 4), 0.25)):
            self.assertIsNone(gssc_stage.unpack_infer((stages, times, third))[1])

    def test_other_shapes_fail(self):
        for bad in ((np.array([0]),), (1, 2, 3, 4), np.array([0, 1])):
            with self.assertRaises(ValueError):
                gssc_stage.unpack_infer(bad)

    def test_stager_blocks(self):
        for module, tool in ((gssc_stage, "gssc"), (yasa_stage, "yasa")):
            block = module.stager_block(True)
            self.assertEqual(set(block), STAGER_KEYS)
            self.assertEqual(block["tool"], tool)
            self.assertIs(block["returns_probabilities"], True)


class CollectTrackerTest(unittest.TestCase):
    def test_one_rem_event_tracker_for_the_whole_recording(self):
        import datetime as dt
        import tempfile

        import muse_athena_protocol as proto
        from muse_raw_stream import MuseRawStream

        trackers = []
        extract = heuristic_rem_detector.extract_eeg_features

        def recording_extract(epoch, *args, **kwargs):
            trackers.append(kwargs.get("rem_tracker"))
            return extract(epoch, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            recording_dir = Path(tmp)
            stream = MuseRawStream(str(recording_dir / "raw_amused.bin"))
            stream.open_write()
            for counter, seconds in enumerate((0, 35, 70)):
                header = bytearray(14)
                header[9] = proto.TAG_EEG_4CH
                header[10] = counter  # an unchanged counter reads as a repeated packet
                stream.write_packet(
                    bytes(header) + bytes(range(28)),
                    stream.session_start + dt.timedelta(seconds=seconds),
                )
            stream.close()
            with mock.patch.object(heuristic_rem_detector, "extract_eeg_features", recording_extract):
                collected = vrd.collect(recording_dir, 30.0)

        self.assertEqual(len(collected["predictions"]), len(trackers))
        self.assertGreaterEqual(len(trackers), 2)
        self.assertIsNotNone(trackers[0])
        self.assertTrue(all(tracker is trackers[0] for tracker in trackers))


if __name__ == "__main__":
    unittest.main()
