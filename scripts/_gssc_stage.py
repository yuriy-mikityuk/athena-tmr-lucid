#!/usr/bin/env python3
"""Offline reference sleep staging with GSSC (runs in the isolated .venv-gssc).

Reads the same .npz that _yasa_stage.py consumes (Muse EEG channel arrays in
microvolts + sfreq) and writes the identical per-30s-epoch hypnogram JSON, so it
is a drop-in reference for validate_rem_detection.py (--reference gssc).

Why GSSC beside YASA: GSSC was trained mostly on C3, C4, F3, F4 (NSRR PSG) and
stages from one EEG channel without EOG/EMG, while YASA's model expects central
electrodes and mis-stages this montage. There is no published evaluation of GSSC
on forehead-only EEG such as the Muse AF7/AF8. It is an automated proxy, not PSG
ground truth: an independent second opinion, not truth.

NB: the pinned gssc 0.0.9 mne_infer returns (stages, times): argmax stages, no
per-class probabilities, so proba_rem is then a hard 0/1 label from the winning
stage, not a calibrated probability. gssc's main branch returns (stages, times,
probs); both are accepted, and probs are used only when they look like one row of
five class probabilities per epoch. The hypnogram's "stager" block records which
happened (returns_probabilities) and the gssc, torch and mne versions.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# GSSC stage index -> label (gssc.utils graph_summary stage_names).
STAGE_NAMES = {0: "Wake", 1: "N1", 2: "N2", 3: "N3", 4: "REM"}
REM_INDEX = 4


def _version(distribution: str) -> Optional[str]:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def stager_block(returns_probabilities: bool) -> Dict[str, object]:
    return {
        "tool": "gssc",
        "package_version": _version("gssc"),
        "torch_version": _version("torch"),
        "mne_version": _version("mne"),
        "returns_probabilities": bool(returns_probabilities),
    }


def unpack_infer(result: Sequence[object]) -> Tuple[List[int], Optional[np.ndarray]]:
    """Stages and, when usable, per-class probabilities from ``EEGInfer.mne_infer``.

    gssc 0.0.9 returns ``(stages, times)``; gssc main returns ``(stages, times,
    probs)``. ``probs`` is kept only if it has one row of five values per epoch,
    each in [0, 1] and summing to 1; anything else (log-probabilities, a different
    class count) falls back to the hard stage labels.
    """
    if not isinstance(result, (tuple, list)) or len(result) not in (2, 3):
        size = len(result) if isinstance(result, (tuple, list)) else "n/a"
        raise ValueError(f"unexpected mne_infer result: {type(result).__name__} of length {size}")
    stages = [int(s) for s in np.asarray(result[0]).ravel().tolist()]
    if len(result) == 2 or result[2] is None:
        return stages, None
    probs = np.asarray(result[2], dtype=float)
    usable = (
        probs.shape == (len(stages), len(STAGE_NAMES))
        and bool(np.all((probs >= 0.0) & (probs <= 1.0)))
        and bool(np.allclose(probs.sum(axis=1), 1.0, atol=1e-3))
    )
    return stages, (probs if usable else None)


def epoch_rows(stages: Sequence[int], probs: Optional[np.ndarray]) -> List[Dict[str, object]]:
    rows = []
    for i, s in enumerate(stages):
        name = STAGE_NAMES.get(s, str(s))
        if probs is None:
            proba_rem, confidence = (1.0 if name == "REM" else 0.0), 1.0
        else:
            proba_rem, confidence = float(probs[i, REM_INDEX]), float(probs[i].max())
        rows.append({"epoch": i, "stage": name, "proba_rem": proba_rem, "confidence": confidence})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npz", required=True, help="Input .npz with channel arrays (uV) + sfreq + ch_names")
    parser.add_argument("--eeg", default="AF7", help="Channel name to stage from")
    parser.add_argument("--eog", default="none", help="EOG channel name, or 'none' (GSSC stages EEG-only here)")
    parser.add_argument("--out", required=True, help="Output hypnogram JSON path")
    args = parser.parse_args()

    import mne
    import torch

    # GSSC 0.0.9 pickles its bundled net classes and loads them with torch.load.
    # torch >= 2.6 defaults weights_only=True, which rejects those classes. These
    # are GSSC's own trusted weights shipped in the package, so force the full
    # (pre-2.6) load behavior.
    _orig_torch_load = torch.load

    def _full_torch_load(*a, **k):
        k.setdefault("weights_only", False)
        return _orig_torch_load(*a, **k)

    torch.load = _full_torch_load

    from gssc.infer import EEGInfer

    mne.set_log_level("ERROR")

    data = np.load(args.npz)
    sfreq = float(data["sfreq"])
    ch_names = [str(c) for c in data["ch_names"]]
    # MNE expects volts; our reconstruction is in microvolts.
    signals_v = np.vstack([np.asarray(data[name], dtype=np.float64) * 1e-6 for name in ch_names])
    info = mne.create_info(ch_names, sfreq, ch_types="eeg")
    raw = mne.io.RawArray(signals_v, info, verbose="ERROR")

    eog_name = None if str(args.eog).lower() in ("", "none") else args.eog
    eog = [] if eog_name is None else [eog_name]

    ei = EEGInfer(use_cuda=False)
    stages, probs = unpack_infer(ei.mne_infer(raw, eeg=[args.eeg], eog=eog))

    epochs = epoch_rows(stages, probs)
    stage_counts: dict[str, int] = {}
    for row in epochs:
        stage_counts[row["stage"]] = stage_counts.get(row["stage"], 0) + 1

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "sfreq": sfreq,
                "eeg": args.eeg,
                "eog": eog_name,
                "epoch_seconds": 30,
                "stager": stager_block(probs is not None),
                "stage_counts": stage_counts,
                "epochs": epochs,
            },
            handle,
        )
    print(f"gssc staged {len(epochs)} epochs; stage_counts={stage_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
