#!/usr/bin/env python3
"""Validate the wired REM detector against an offline reference stager (YASA or GSSC).

The project ships one wired REM detector -- the fixed-threshold, non-ML
``HeuristicRemDetector`` -- but nothing in the repo measures whether it fires REM
at the *right time*: there is no PSG/hypnogram ground truth. This script gives a
first, cheap, independent second opinion by comparing the heuristic against YASA's
automated stager on a recording you already have.

Pipeline
    recording/
      |-- decoded_frames.jsonl --> reconstruct continuous EEG (uV) -----+
      |                                                                 v
      |                                          YASA SleepStaging (.venv-yasa)
      |                                                                 |
      +-- raw_amused.bin -> ReplaySession -> EpochBuilder(30s)          |
                                     -> HeuristicRemDetector -> p_rem    |
                                     -> StableRemGate -> gate_open       |
                                                                         v
                          align 30s epochs by time  ->  agreement metrics

What it reports
    * REM precision / recall / F1 / Cohen's kappa of the heuristic vs YASA-REM,
      at the live gate's operating thresholds (enter=0.70, exit=0.45), at 0.50,
      and at the best-F1 threshold; plus a full threshold sweep and ROC-AUC.
    * The *system* view: the actual StableRemGate simulated over the p_rem series
      -- when the gate would open (i.e. fire a cue), how often is YASA calling REM?

Honest caveats (printed in the summary too)
    YASA is a PROXY, not PSG truth. Its model wants central electrodes (C3/C4);
    the Muse gives only frontal (AF7/AF8) + temporal (TP9/TP10) referenced near
    Fpz, and there is no EMG -- so its own REM calls are imperfect, especially
    W/N1/REM boundaries. Read agreement as directional evidence, not a grade.

Usage
    python scripts/validate_rem_detection.py data/recordings/overnight_20260707
    # override channels / venv / outputs:
    python scripts/validate_rem_detection.py <dir> --eeg AF7 --eog AF8 \
        --yasa-python .venv-yasa/bin/python --output out.json --html out.html
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import subprocess
import sys
import tempfile
from array import array
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from muse_tmr.data.replay import ReplayConfig, ReplaySession  # noqa: E402
from muse_tmr.features.epochs import EpochBuilder, EpochConfig  # noqa: E402
from muse_tmr.models import HeuristicRemDetector  # noqa: E402
from muse_tmr.models.rem_detector import RemPrediction  # noqa: E402
from muse_tmr.models.rem_gate import RemGateConfig, StableRemGate  # noqa: E402
from muse_tmr.presets import preset_provides_optics  # noqa: E402

EEG_CHANNELS = ("AF7", "AF8", "TP9", "TP10")
REM_STAGES = ("R", "REM")
NOMINAL_EEG_RATE_HZ = 256.0
GAP_FILL_THRESHOLD_SECONDS = 0.5


# --------------------------------------------------------------------------- #
# One replay pass: heuristic p_rem per epoch AND continuous EEG for the stager
# --------------------------------------------------------------------------- #
async def _collect(recording_dir: Path, epoch_seconds: float) -> Dict[str, object]:
    """Single pass over raw_amused.bin.

    Feeds every MuseFrame to the EpochBuilder (-> heuristic p_rem per epoch)
    while side-accumulating per-channel EEG samples (uV) for the reference
    stager. The heuristic epochs are anchored to wall-clock frame timestamps, so
    to keep YASA's sample-indexed 30s epochs on the SAME clock, we zero-fill any
    BLE-dropout / AF7-loss gap: array position then maps to real elapsed time and
    YASA epoch j covers real [t0 + j*30, ...). Without the fill, a mid-night gap
    would slide every later YASA epoch earlier and mispair the two grids.
    """
    channels: Dict[str, array] = {name: array("f") for name in EEG_CHANNELS}
    state: Dict[str, Optional[float]] = {"t0": None, "t_last": None, "n": 0, "prev_ts": None, "prev_width": 0}

    def sink(frame) -> None:
        eeg = getattr(frame, "eeg", None)
        if eeg is None:
            return
        per_channel = eeg.channels_uv or {}
        reference = per_channel.get("AF7")
        if not reference:
            return
        ts = frame.timestamp
        width = len(reference)
        if state["t0"] is None:
            state["t0"] = ts
        elif ts - state["prev_ts"] > GAP_FILL_THRESHOLD_SECONDS:
            # Insert the missing samples for the dropout span so the timeline stays real.
            n_fill = int(round((ts - state["prev_ts"]) * NOMINAL_EEG_RATE_HZ)) - int(state["prev_width"])
            if n_fill > 0:
                zeros = [0.0] * n_fill
                for name in EEG_CHANNELS:
                    channels[name].extend(zeros)
                state["n"] += n_fill
        state["prev_ts"] = ts
        state["prev_width"] = width
        state["t_last"] = ts
        state["n"] += width
        for name in EEG_CHANNELS:
            samples = per_channel.get(name) or []
            if len(samples) == width:
                channels[name].extend(samples)
            else:  # keep channels length-aligned even if one lags on a frame
                channels[name].extend(list(samples)[:width] + [0.0] * max(0, width - len(samples)))

    async def teed(stream):
        async for frame in stream:
            sink(frame)
            yield frame

    session = ReplaySession(ReplayConfig(input_path=recording_dir, speed=0.0))
    await session.connect()
    detector = HeuristicRemDetector()
    builder = EpochBuilder(EpochConfig(epoch_seconds=epoch_seconds, stride_seconds=epoch_seconds))
    predictions: List[Tuple[float, RemPrediction]] = []
    try:
        async for epoch in builder.build(teed(session.stream())):
            predictions.append((epoch.start_time, detector.predict_epoch(epoch)))
    finally:
        await session.stop()

    t0, t_last, n_samples = state["t0"], state["t_last"], int(state["n"])
    if t0 is None or t_last is None or n_samples == 0 or t_last <= t0:
        raise SystemExit("no usable EEG samples reconstructed from the recording")
    arrays = {name: np.frombuffer(buf, dtype=np.float32).copy() for name, buf in channels.items()}
    return {
        "predictions": predictions,
        "channels": arrays,
        "sfreq": float(n_samples / (t_last - t0)),
        "t0": float(t0),
        "n_samples": n_samples,
    }


def collect(recording_dir: Path, epoch_seconds: float) -> Dict[str, object]:
    return asyncio.run(_collect(recording_dir, epoch_seconds))


def resample_for_stager(channels: Dict[str, np.ndarray], sfreq: float, target: float = 100.0) -> Tuple[Dict[str, np.ndarray], float]:
    """Resample to ~target Hz with a fast polyphase FIR, preserving real duration.

    The Muse's empirical rate is a non-integer (~254.8 Hz). YASA resamples to 100
    Hz internally, and doing that from an irrational ratio on a multi-million
    sample array triggers a pathologically slow full-length FFT resample. Pre-
    resampling here (polyphase, O(n)) shrinks the array to ~target*duration
    samples and makes YASA's own step trivial. Duration is preserved, so YASA
    epoch j still maps to real time [t0 + j*30, ...).
    """
    from fractions import Fraction

    from scipy.signal import resample_poly

    frac = Fraction(target / sfreq).limit_denominator(1000)
    up, down = frac.numerator, frac.denominator
    resampled = {
        name: resample_poly(arr.astype(np.float64), up, down).astype(np.float32)
        for name, arr in channels.items()
    }
    # Declare exactly `target` Hz. The polyphase result is ~target (e.g. 99.999),
    # but a near-unity sfreq makes YASA's internal resample-to-100 pathologically
    # slow; declaring exactly 100 makes it a no-op. The <0.01% rate error is ~0.4s
    # of drift over a full night -- far below the 30s epoch grid.
    return resampled, float(target)


def simulate_gate(
    predictions: Sequence[RemPrediction],
    epoch_seconds: float,
    *,
    optics_capable: bool = True,
) -> List[bool]:
    """Run the real StableRemGate over the p_rem series, in time order.

    ``optics_capable`` mirrors the session preset: on an EEG-only preset (p21)
    the missing-cardiac reason codes must not cap confidence, or the gate never
    opens (see issue #112).
    """
    gate = StableRemGate(RemGateConfig(epoch_seconds=epoch_seconds, optics_capable=optics_capable))
    return [gate.update(pred, duration_seconds=epoch_seconds).gate_open for pred in predictions]


# --------------------------------------------------------------------------- #
# Reference stager (subprocess into the isolated YASA venv)
# --------------------------------------------------------------------------- #
# Reference stagers, each shelled into its own isolated venv (schemas identical).
REFERENCE_SCRIPTS = {"yasa": "_yasa_stage.py", "gssc": "_gssc_stage.py"}


def run_reference(
    reference: str, npz_path: Path, eeg: str, eog: str, python_path: Path
) -> Dict[str, object]:
    stager = Path(__file__).resolve().parent / REFERENCE_SCRIPTS[reference]
    out_path = npz_path.with_suffix(".hypno.json")
    cmd = [
        str(python_path), str(stager),
        "--npz", str(npz_path),
        "--eeg", eeg,
        "--eog", eog,
        "--out", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{reference} staging failed (exit {result.returncode}).\n"
            f"cmd: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return json.loads(out_path.read_text())


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run(
    recording_dir: Path,
    eeg: str,
    eog: str,
    reference_python: Path,
    epoch_seconds: float,
    preset: Optional[str] = None,
    reference: str = "yasa",
) -> Dict[str, object]:
    print(f"[1/4] replaying {recording_dir.name}: heuristic p_rem + EEG reconstruction ...", flush=True)
    collected = collect(recording_dir, epoch_seconds)
    t0 = float(collected["t0"])
    sfreq = float(collected["sfreq"])
    channels: Dict[str, np.ndarray] = collected["channels"]  # type: ignore[assignment]
    predictions: List[Tuple[float, RemPrediction]] = collected["predictions"]  # type: ignore[assignment]
    print(f"      {collected['n_samples']} samples/ch  eff_sfreq={sfreq:.2f} Hz  epochs={len(predictions)}", flush=True)

    print("[2/4] live-gate simulation over p_rem ...", flush=True)
    optics_capable = preset_provides_optics(preset)
    preds_only = [p for _, p in predictions]
    gate_open = simulate_gate(preds_only, epoch_seconds, optics_capable=optics_capable)
    n_open = sum(gate_open)
    n_min = round(n_open * epoch_seconds / 60, 1)
    print(
        f"      preset={preset or 'unknown'} optics_capable={optics_capable}  "
        f"gate opened on {n_open} epochs ({n_min} min)",
        flush=True,
    )
    if not optics_capable:
        # One replay, two policies: show the pre-fix counterfactual so the
        # EEG-only cueing gain is visible in a single run (issue #112).
        cf_open = sum(simulate_gate(preds_only, epoch_seconds, optics_capable=True))
        cf_min = round(cf_open * epoch_seconds / 60, 1)
        print(
            f"      counterfactual optics-capable cap (pre-#112-fix): "
            f"{cf_open} epochs ({cf_min} min)",
            flush=True,
        )

    print(f"[3/4] {reference} reference staging (eeg={eeg}, eog={eog}) ...", flush=True)
    channels, stage_sfreq = resample_for_stager(channels, sfreq)
    print(f"      resampled to {stage_sfreq:.2f} Hz for the stager", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        npz_path = Path(tmp) / "eeg.npz"
        np.savez(
            npz_path,
            sfreq=np.float64(stage_sfreq),
            ch_names=np.array(list(EEG_CHANNELS)),
            **{name: channels[name] for name in EEG_CHANNELS},
        )
        hypno = run_reference(reference, npz_path, eeg, eog, reference_python)
    hypno_by_index = {int(e["epoch"]): e for e in hypno["epochs"]}
    print(f"      staged {len(hypno_by_index)} epochs; {hypno.get('stage_counts')}", flush=True)

    print("[4/4] aligning epochs and computing metrics ...", flush=True)
    matched = []
    for (start, pred), opened in zip(predictions, gate_open):
        k = round((start - t0) / epoch_seconds)
        ref = hypno_by_index.get(k)
        if ref is None:
            continue
        matched.append(
            {
                "epoch": k,
                "p_rem": float(pred.probability),
                "gate_open": bool(opened),
                "ref_stage": ref["stage"],
                "ref_rem": 1 if ref["stage"] in REM_STAGES else 0,
                "ref_proba_rem": ref.get("proba_rem"),
            }
        )

    if not matched:
        raise SystemExit("no epochs aligned between heuristic and YASA -- check timestamps")

    y = np.array([m["ref_rem"] for m in matched], dtype=int)
    p = np.array([m["p_rem"] for m in matched], dtype=float)
    g = np.array([1 if m["gate_open"] else 0 for m in matched], dtype=int)

    reference_flags = _reference_flags(hypno.get("stage_counts", {}), int(y.sum()), len(matched))
    enter, exit_ = RemGateConfig().enter_threshold, RemGateConfig().exit_threshold
    best_thr, best = best_f1_threshold(y, p)
    result = {
        "recording": recording_dir.name,
        "reference": {"tool": reference, "eeg": eeg, "eog": hypno.get("eog"), "note": "proxy, not PSG"},
        "epochs_matched": len(matched),
        "epoch_seconds": epoch_seconds,
        "ref_rem_epochs": int(y.sum()),
        "ref_rem_fraction": float(y.mean()),
        "reference_flags": reference_flags,
        "mean_p_rem": float(p.mean()),
        "roc_auc": roc_auc(y, p),
        "threshold_metrics": {
            f"enter_{enter:g}": binary_metrics(y, (p >= enter).astype(int)),
            f"exit_{exit_:g}": binary_metrics(y, (p >= exit_).astype(int)),
            "at_0.5": binary_metrics(y, (p >= 0.5).astype(int)),
            f"best_f1_{best_thr:g}": best,
        },
        "gate_vs_ref": {
            **binary_metrics(y, g),
            "gate_open_epochs": int(g.sum()),
            "gate_open_minutes": round(int(g.sum()) * epoch_seconds / 60, 1),
        },
        "threshold_sweep": threshold_sweep(y, p),
        "matched": matched,
    }
    return result


def _reference_flags(stage_counts: Mapping[str, int], rem_epochs: int, matched: int) -> List[str]:
    """Flag a physiologically implausible YASA hypnogram (a degenerate reference).

    A full night of real sleep has ~15-25% REM and meaningful N3. If the
    reference is far off that, its REM labels are not trustworthy and the
    agreement metrics below cannot validate (or invalidate) the detector.
    """
    total = sum(stage_counts.values()) or 1
    rem_frac = stage_counts.get("REM", stage_counts.get("R", 0)) / total
    deep_frac = stage_counts.get("N3", 0) / total
    flags: List[str] = []
    if matched >= 240:  # only judge plausibility on a full night (>=2h), not a short nap
        if len([s for s, c in stage_counts.items() if c]) < 3:
            flags.append("fewer than 3 sleep stages scored")
        if rem_frac < 0.05:
            flags.append(f"implausibly low REM ({rem_frac * 100:.1f}%; a real night is ~15-25%)")
        if deep_frac < 0.02:
            flags.append(f"implausibly low N3 deep sleep ({deep_frac * 100:.1f}%)")
    if rem_epochs == 0:
        flags.append("zero REM epochs in the reference -- REM precision/recall are undefined")
    return flags


def _fmt(m: Dict[str, float]) -> str:
    def n(x):
        return "  n/a" if (isinstance(x, float) and not math.isfinite(x)) else f"{x:5.2f}"
    return (
        f"P={n(m['precision'])} R={n(m['recall'])} F1={n(m['f1'])} "
        f"kappa={n(m['kappa'])} acc={n(m['accuracy'])} "
        f"(tp={m['tp']} fp={m['fp']} fn={m['fn']} tn={m['tn']})"
    )


REFERENCE_CAVEATS = {
    "yasa": (
        "  CAVEAT: YASA is a proxy, not PSG. Its model expects central electrodes\n"
        "  (C3/C4); the Muse gives only frontal/temporal channels and no EMG, so YASA\n"
        "  mis-scores this montage badly -- treat it as a weak proxy, not a grade."
    ),
    "gssc": (
        "  CAVEAT: GSSC is frontal-trained (a much better montage fit than YASA), but\n"
        "  still an automated proxy, not PSG. Validate against a few manually-scored\n"
        "  nights before treating its REM calls as ground truth."
    ),
}


def print_summary(result: Dict[str, object]) -> None:
    tm = result["threshold_metrics"]
    gate = result["gate_vs_ref"]
    tool = str(result.get("reference", {}).get("tool", "reference")).upper()
    print("\n" + "=" * 78)
    print(f"REM detection vs {tool} reference -- {result['recording']}")
    print("=" * 78)
    print(
        f"matched epochs: {result['epochs_matched']}  |  "
        f"{tool} REM: {result['ref_rem_epochs']} epochs "
        f"({result['ref_rem_fraction']*100:.1f}% of night)  |  "
        f"mean p_rem: {result['mean_p_rem']:.2f}"
    )
    flags = result.get("reference_flags") or []
    if flags:
        print("!" * 78)
        print("  DEGENERATE REFERENCE -- the metrics below CANNOT be trusted:")
        for f in flags:
            print(f"    - {f}")
        print(f"  {tool} mis-staged this night (see caveat); the numbers are not a verdict")
        print("  on the detector. A trustworthy reference (manual scoring / PSG) is required.")
        print("!" * 78)
    auc = result["roc_auc"]
    print(f"ROC-AUC (p_rem ranks {tool}-REM): {auc:.3f}" if math.isfinite(auc) else "ROC-AUC: n/a")
    print("-" * 78)
    for label, m in tm.items():
        print(f"  p_rem >= {label:<14} {_fmt(m)}")
    print("-" * 78)
    print("  SYSTEM VIEW - real StableRemGate (enter 0.70 / exit 0.45 / 60s stable / 120s cooldown):")
    print(
        f"    gate opened on {gate['gate_open_epochs']} epochs "
        f"({gate['gate_open_minutes']} min).  vs {tool}-REM: {_fmt(gate)}"
    )
    print("-" * 78)
    print(REFERENCE_CAVEATS.get(tool.lower(), REFERENCE_CAVEATS["yasa"]))
    print("=" * 78 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recording_dir", type=Path)
    parser.add_argument("--eeg", default="AF7", help="EEG channel for YASA (default AF7)")
    parser.add_argument("--eog", default="AF8", help="EOG channel for YASA, or 'none' (default AF8)")
    parser.add_argument("--epoch-seconds", type=float, default=30.0)
    parser.add_argument(
        "--preset",
        default=None,
        help="Session preset (e.g. p21, p1034). EEG-only presets (p21) tell the "
        "gate no optics were streamed, so absent PPG does not cap confidence.",
    )
    parser.add_argument(
        "--reference",
        choices=("yasa", "gssc"),
        default="yasa",
        help="Offline reference stager. gssc is a frontal-trained model (better fit "
        "for the Muse montage than YASA's central-electrode model).",
    )
    parser.add_argument(
        "--yasa-python",
        type=Path,
        default=Path(__file__).resolve().parent.parent / ".venv-yasa" / "bin" / "python",
        help="Python of the isolated venv that has YASA installed",
    )
    parser.add_argument(
        "--gssc-python",
        type=Path,
        default=Path(__file__).resolve().parent.parent / ".venv-gssc" / "bin" / "python",
        help="Python of the isolated venv that has GSSC installed",
    )
    parser.add_argument("--output", type=Path, help="Write full metrics JSON here")
    parser.add_argument("--html", type=Path, help="Write an HTML overlay report here")
    args = parser.parse_args()

    if args.epoch_seconds != 30.0:
        raise SystemExit("YASA stages in fixed 30 s epochs; --epoch-seconds must be 30")

    recording_dir = args.recording_dir.resolve()
    if not recording_dir.exists():
        raise SystemExit(f"recording directory not found: {recording_dir}")

    reference_python = args.gssc_python if args.reference == "gssc" else args.yasa_python
    if not reference_python.exists():
        venv = ".venv-gssc" if args.reference == "gssc" else ".venv-yasa"
        raise SystemExit(
            f"{args.reference} venv python not found: {reference_python}\n"
            f"Create it with:  python -m venv {venv} && {venv}/bin/pip install {args.reference}"
        )

    # NB: do NOT resolve() the venv python -- it is a symlink to the base
    # interpreter, and resolving it would drop the venv's site-packages (numpy,
    # yasa/gssc). Invoke the venv path directly so venv detection kicks in.
    result = run(
        recording_dir, args.eeg, args.eog, reference_python, args.epoch_seconds,
        args.preset, args.reference,
    )
    print_summary(result)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({k: v for k, v in result.items() if k != "matched"}, indent=2))
        print(f"metrics written: {args.output}")
    if args.html:
        from _rem_validation_html import build_html  # local sibling module

        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(build_html(result))
        print(f"html overlay written: {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
