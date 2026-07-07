#!/usr/bin/env python3
"""Offline reference sleep staging with YASA (runs in the isolated .venv-yasa).

Reads an .npz of reconstructed Muse EEG (channel arrays in microvolts + sfreq)
written by validate_rem_detection.py, runs YASA's automated stager, and writes a
per-30s-epoch hypnogram JSON to --out.

This deliberately lives in a separate venv: YASA pulls in numpy 2 / mne / numba /
lightgbm, which we do not want to force onto the project's main environment.

YASA is a PROXY reference, not PSG ground truth. Its classifier was trained on
central electrodes (C3/C4) referenced to the mastoids or Fpz; the Muse gives only
frontal (AF7/AF8) and temporal (TP9/TP10) channels referenced near Fpz, and there
is no EMG. Treat the resulting hypnogram as an independent second opinion, not
truth.
"""

from __future__ import annotations

import argparse
import json

import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npz", required=True, help="Input .npz with channel arrays (uV) + sfreq + ch_names")
    parser.add_argument("--eeg", default="AF7", help="Channel name to use as the YASA EEG derivation")
    parser.add_argument("--eog", default="AF8", help="Channel name to use as the YASA EOG derivation (or 'none')")
    parser.add_argument("--out", required=True, help="Output hypnogram JSON path")
    args = parser.parse_args()

    import mne
    import yasa

    mne.set_log_level("ERROR")

    data = np.load(args.npz)
    sfreq = float(data["sfreq"])
    ch_names = [str(c) for c in data["ch_names"]]
    # MNE expects volts; our reconstruction is in microvolts.
    signals_v = np.vstack([np.asarray(data[name], dtype=np.float64) * 1e-6 for name in ch_names])

    info = mne.create_info(ch_names, sfreq, ch_types="eeg")
    raw = mne.io.RawArray(signals_v, info, verbose="ERROR")

    eog_name = None if str(args.eog).lower() in ("", "none") else args.eog
    staging = yasa.SleepStaging(raw, eeg_name=args.eeg, eog_name=eog_name)

    # YASA >=0.7 returns a Hypnogram (per-epoch labels WAKE/N1/N2/N3/REM on a
    # RangeIndex 0..N-1); .proba is the class-probability DataFrame.
    hypnogram = staging.predict()
    stages = [str(s) for s in (hypnogram.hypno if hasattr(hypnogram, "hypno") else hypnogram)]
    proba = hypnogram.proba if hasattr(hypnogram, "proba") else staging.predict_proba()

    rem_col = next((c for c in ("REM", "R") if c in proba.columns), None)
    rem_proba = proba[rem_col].to_numpy() if rem_col is not None else np.full(len(stages), np.nan)
    confidence = proba.to_numpy().max(axis=1)

    epochs = [
        {
            "epoch": i,
            "stage": stages[i],
            "proba_rem": float(rem_proba[i]),
            "confidence": float(confidence[i]),
        }
        for i in range(len(stages))
    ]
    stage_counts: dict[str, int] = {}
    for s in stages:
        stage_counts[s] = stage_counts.get(s, 0) + 1

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
    print(f"yasa staged {len(epochs)} epochs; stage_counts={stage_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
