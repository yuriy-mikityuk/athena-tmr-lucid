#!/usr/bin/env python3
"""Offline reference sleep staging with GSSC (runs in the isolated .venv-gssc).

Reads the same .npz that _yasa_stage.py consumes (Muse EEG channel arrays in
microvolts + sfreq) and writes the identical per-30s-epoch hypnogram JSON, so it
is a drop-in reference for validate_rem_detection.py (--reference gssc).

Why GSSC beside YASA: GSSC's pretrained network was trained on a channel set that
INCLUDES frontal derivations (F3/F4) and it can stage from a single EEG channel
with no EOG/EMG -- a far better fit for the Muse frontal montage than YASA's
central-electrode model, which mis-stages this montage. It is still an automated
proxy, not PSG ground truth: an independent second opinion, not truth.

NB: GSSC's mne_infer returns argmax stages (no per-class probabilities), so
proba_rem here is a hard 0/1 label from the winning stage, not a calibrated
probability.
"""

from __future__ import annotations

import argparse
import json

import numpy as np

# GSSC stage index -> label (gssc.utils graph_summary stage_names).
STAGE_NAMES = {0: "Wake", 1: "N1", 2: "N2", 3: "N3", 4: "REM"}


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
    stages, _times = ei.mne_infer(raw, eeg=[args.eeg], eog=eog)
    stages = [int(s) for s in np.asarray(stages).ravel().tolist()]

    epochs = []
    stage_counts: dict[str, int] = {}
    for i, s in enumerate(stages):
        name = STAGE_NAMES.get(s, str(s))
        epochs.append(
            {
                "epoch": i,
                "stage": name,
                "proba_rem": 1.0 if name == "REM" else 0.0,
                "confidence": 1.0,
            }
        )
        stage_counts[name] = stage_counts.get(name, 0) + 1

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "sfreq": sfreq,
                "eeg": args.eeg,
                "eog": eog_name,
                "epoch_seconds": 30,
                "stage_counts": stage_counts,
                "epochs": epochs,
            },
            handle,
        )
    print(f"gssc staged {len(epochs)} epochs; stage_counts={stage_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
