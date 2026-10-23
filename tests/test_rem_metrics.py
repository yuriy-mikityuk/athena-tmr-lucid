"""REM agreement metrics moved out of scripts/validate_rem_detection.py (#233).

The expected values were produced by the script's own functions before the move, on
the fixed arrays below, so the move changes no output.
"""

import importlib.util
import math
import unittest
from pathlib import Path

import numpy as np

from muse_tmr.validation import rem_metrics
from muse_tmr.validation.rem_metrics import (
    _cohen_kappa,
    best_f1_threshold,
    binary_metrics,
    gate_open_fraction,
    rem_onset_latency_seconds,
    roc_auc,
    threshold_sweep,
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_rem_detection.py"

Y_TRUE = np.array([0, 0, 1, 1, 0, 1, 0, 0, 1, 1, 1, 0], dtype=int)
SCORES = np.array([0.10, 0.40, 0.35, 0.80, 0.40, 0.90, 0.20, 0.65, 0.65, 0.55, 0.95, 0.05])
NAN = float("nan")


def _load_script():
    spec = importlib.util.spec_from_file_location("validate_rem_detection_for_metrics", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metrics(tp, fp, fn, tn, precision, recall, f1, accuracy, kappa):
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "accuracy": accuracy, "kappa": kappa,
    }


class SameOutputAsTheScriptTest(unittest.TestCase):
    def assertSameMetrics(self, observed, expected):
        self.assertEqual(list(observed), list(expected))
        for key, value in expected.items():
            if isinstance(value, float) and math.isnan(value):
                self.assertTrue(math.isnan(observed[key]), key)
            else:
                self.assertEqual(observed[key], value, key)

    def test_the_script_uses_these_functions(self):
        script = _load_script()
        for name in ("binary_metrics", "roc_auc", "threshold_sweep", "best_f1_threshold", "gate_open_fraction"):
            self.assertIs(getattr(script, name), getattr(rem_metrics, name), name)
        self.assertFalse(hasattr(script, "_cohen_kappa"))

    def test_binary_metrics(self):
        self.assertSameMetrics(
            binary_metrics(Y_TRUE, (SCORES >= 0.5).astype(int)),
            _metrics(5, 1, 1, 5, 5 / 6, 5 / 6, 0.8333333333333334, 0.8333333333333334, 0.6666666666666667),
        )
        self.assertSameMetrics(
            binary_metrics(Y_TRUE, np.zeros_like(Y_TRUE)),
            _metrics(0, 0, 6, 6, NAN, 0.0, NAN, 0.5, 0.0),
        )
        self.assertSameMetrics(
            binary_metrics(np.zeros_like(Y_TRUE), (SCORES >= 0.5).astype(int)),
            _metrics(0, 6, 0, 6, 0.0, NAN, NAN, 0.5, 0.0),
        )

    def test_kappa(self):
        self.assertEqual(_cohen_kappa(4, 1, 2, 5), 0.5)
        self.assertTrue(math.isnan(_cohen_kappa(0, 0, 0, 0)))

    def test_roc_auc(self):
        self.assertEqual(roc_auc(Y_TRUE, SCORES), 0.875)
        self.assertTrue(math.isnan(roc_auc(np.ones_like(Y_TRUE), SCORES)))

    def test_threshold_sweep(self):
        rows = threshold_sweep(Y_TRUE, SCORES, step=0.25)
        expected = [
            (0.25, _metrics(6, 3, 0, 3, 0.6666666666666666, 1.0, 0.8, 0.75, 0.5)),
            (0.5, _metrics(5, 1, 1, 5, 0.8333333333333334, 0.8333333333333334,
                           0.8333333333333334, 0.8333333333333334, 0.6666666666666667)),
            (0.75, _metrics(3, 0, 3, 6, 1.0, 0.5, 0.6666666666666666, 0.75, 0.5)),
        ]
        self.assertEqual(len(rows), len(expected))
        for row, (threshold, metrics) in zip(rows, expected):
            self.assertSameMetrics(row, {"threshold": threshold, **metrics})

        default = threshold_sweep(Y_TRUE, SCORES)
        self.assertEqual(len(default), 19)
        self.assertSameMetrics(
            default[0], {"threshold": 0.05, **_metrics(6, 6, 0, 0, 0.5, 1.0, 0.6666666666666666, 0.5, 0.0)}
        )
        # The threshold adds up 0.05 steps, so the last one is a hair above 0.95 and the
        # 0.95 score falls under it. The move keeps that.
        self.assertSameMetrics(
            default[-1], {"threshold": 0.95, **_metrics(0, 0, 6, 6, NAN, 0.0, NAN, 0.5, 0.0)}
        )

    def test_best_f1_threshold(self):
        threshold, metrics = best_f1_threshold(Y_TRUE, SCORES)
        self.assertEqual(threshold, 0.5)
        self.assertSameMetrics(
            metrics,
            _metrics(5, 1, 1, 5, 0.8333333333333334, 0.8333333333333334,
                     0.8333333333333334, 0.8333333333333334, 0.6666666666666667),
        )


class GateOpenFractionTest(unittest.TestCase):
    def test_share_of_open_epochs(self):
        self.assertEqual(gate_open_fraction([True, False, False, True]), 0.5)
        self.assertEqual(gate_open_fraction(np.array([1, 0, 0, 0])), 0.25)

    def test_no_epochs_is_nan(self):
        self.assertTrue(math.isnan(gate_open_fraction([])))

    def test_pairs_are_refused(self):
        with self.assertRaises(ValueError):
            gate_open_fraction([(30.0, True), (60.0, False)])


class RemOnsetLatencyTest(unittest.TestCase):
    def test_first_open_decision_inside_each_run(self):
        # REM 600-900 s and 1800-1950 s; decisions every 30 s at the end of each epoch.
        decisions = [(30.0 * k, False) for k in range(1, 80)]
        opened = {660.0, 690.0, 720.0, 1860.0}
        decisions = [(seconds, seconds in opened) for seconds, _ in decisions]

        self.assertEqual(
            rem_onset_latency_seconds([(600.0, 900.0), (1800.0, 1950.0)], decisions),
            [60.0, 60.0],
        )

    def test_run_without_an_open_gate_is_none(self):
        decisions = [(630.0, False), (660.0, False), (960.0, True)]
        self.assertEqual(rem_onset_latency_seconds([(600.0, 900.0)], decisions), [None])

    def test_decision_at_the_run_start_belongs_to_the_epoch_before(self):
        decisions = [(600.0, True), (630.0, True)]
        self.assertEqual(rem_onset_latency_seconds([(600.0, 900.0)], decisions), [30.0])

    def test_decision_at_the_run_end_still_counts(self):
        self.assertEqual(rem_onset_latency_seconds([(600.0, 660.0)], [(660.0, True)]), [60.0])

    def test_decisions_need_not_be_sorted(self):
        decisions = [(720.0, True), (690.0, True), (660.0, False)]
        self.assertEqual(rem_onset_latency_seconds([(600.0, 900.0)], decisions), [90.0])


if __name__ == "__main__":
    unittest.main()
