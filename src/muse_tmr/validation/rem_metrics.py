"""REM agreement metrics against a reference hypnogram.

One implementation of each metric. ``scripts/validate_rem_detection.py`` scores the
detector against an automated stager with them, and ``muse_tmr.testing.agreement``
against the hypnogram a synthetic night was generated from. The κ here is binary
(REM against not REM), not five-class.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


def binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    tp = int(np.sum((y_pred == 1) & (y_true == 1)))
    fp = int(np.sum((y_pred == 1) & (y_true == 0)))
    fn = int(np.sum((y_pred == 0) & (y_true == 1)))
    tn = int(np.sum((y_pred == 0) & (y_true == 0)))
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    if math.isfinite(precision) and math.isfinite(recall):
        # Conventional F1: a total miss (P=R=0) is F1=0, not undefined.
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    else:
        f1 = float("nan")
    accuracy = (tp + tn) / total if total else float("nan")
    kappa = _cohen_kappa(tp, fp, fn, tn)
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "accuracy": accuracy, "kappa": kappa,
    }


def _cohen_kappa(tp: int, fp: int, fn: int, tn: int) -> float:
    total = tp + fp + fn + tn
    if total == 0:
        return float("nan")
    po = (tp + tn) / total
    p_pred_pos = (tp + fp) / total
    p_true_pos = (tp + fn) / total
    pe = p_pred_pos * p_true_pos + (1 - p_pred_pos) * (1 - p_true_pos)
    return (po - pe) / (1 - pe) if (1 - pe) else float("nan")


def roc_auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    from scipy.stats import rankdata

    n_pos = int(np.sum(y_true == 1))
    n_neg = int(np.sum(y_true == 0))
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = rankdata(scores)
    sum_pos = float(np.sum(ranks[y_true == 1]))
    return (sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def threshold_sweep(y_true: np.ndarray, scores: np.ndarray, step: float = 0.05) -> List[Dict[str, float]]:
    rows = []
    thr = step
    while thr < 1.0:
        m = binary_metrics(y_true, (scores >= thr).astype(int))
        rows.append({"threshold": round(thr, 3), **m})
        thr += step
    return rows


def best_f1_threshold(y_true: np.ndarray, scores: np.ndarray) -> Tuple[float, Dict[str, float]]:
    best_thr, best = 0.5, binary_metrics(y_true, (scores >= 0.5).astype(int))
    for thr in np.round(np.arange(0.01, 1.0, 0.01), 2):
        m = binary_metrics(y_true, (scores >= thr).astype(int))
        f1 = m["f1"]
        if math.isfinite(f1) and (not math.isfinite(best["f1"]) or f1 > best["f1"]):
            best_thr, best = float(thr), m
    return best_thr, best


def gate_open_fraction(gate_open: Sequence[bool]) -> float:
    """Share of epochs with the gate open, one flag per epoch; NaN when there are none."""
    values = np.asarray(gate_open, dtype=bool)
    if values.ndim != 1:
        raise ValueError("gate_open must be one flag per epoch")
    return float(values.mean()) if values.size else float("nan")


def rem_onset_latency_seconds(
    reference_rem_runs: Sequence[Tuple[float, float]],
    gate_open: Sequence[Tuple[float, bool]],
) -> List[Optional[float]]:
    """Seconds from the start of each reference REM run to the first open gate in it.

    ``reference_rem_runs`` are ``(start, end)`` seconds of the reference's REM periods.
    ``gate_open`` holds ``(decision_seconds, open)`` per epoch on the same clock, where
    a decision exists once its epoch has ended (start plus epoch length). A decision
    counts for a run when ``start < decision_seconds <= end``; a run with no open gate
    among them gives None. A gate that was already open when the run began counts from
    its first decision inside the run.
    """
    decisions = sorted((float(seconds), bool(is_open)) for seconds, is_open in gate_open)
    latencies: List[Optional[float]] = []
    for start, end in reference_rem_runs:
        start, end = float(start), float(end)
        first = next(
            (seconds for seconds, is_open in decisions if is_open and start < seconds <= end),
            None,
        )
        latencies.append(None if first is None else first - start)
    return latencies
