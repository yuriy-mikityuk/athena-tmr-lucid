"""Load a decoded Polar H10 session onto the Muse time base.

Muse replay timestamps are host wall-clock, so Polar data is mapped there too:

1. sensor clock -> host monotonic: offset plus linear drift fitted to the
   *lower envelope* of (receive time - sensor time) over the PMD frames. BLE
   only ever adds delay, so the earliest-arriving frames carry the mapping and
   a least-squares line would be biased late by the mean delay. An H10 that
   powers down during a reconnect restarts its clock, so frames are split into
   clock segments wherever that offset jumps and each segment gets its own fit;
2. host monotonic -> wall clock through the clock anchors, so an NTP step
   during the night shows up instead of silently shifting everything;
3. HR-service RR intervals carry no sensor timestamp: with ECG on, each device
   beat is matched to an ECG R-peak; without ECG they keep their receive-time
   estimate, uncertain by up to about a second.

With the electrodes off the skin the H10 keeps sending ECG and even RR, all
noise. RR beats around the spans it reports no contact are dropped, and R-peaks
are searched only in the ECG outside them.

Chest acceleration stays its own table; it is not head IMU and never goes into
MuseFrame.imu.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import linprog

from muse_tmr.data.polar_recorder import POLAR_DIRNAME, decode_polar_session
from muse_tmr.features.cardio_resp_features import CardioRespConfig, detect_r_peaks


@dataclass(frozen=True)
class ClockMapping:
    """host = host_ref + (sensor - sensor_ref) * (1 + drift) + offset."""

    sensor_ref_s: float
    host_ref_s: float
    offset_s: float
    drift: float
    points: int
    delay_median_ms: float
    delay_p95_ms: float

    def to_host(self, sensor_s) -> np.ndarray:
        x = np.asarray(sensor_s, dtype=float) - self.sensor_ref_s
        return self.host_ref_s + x * (1.0 + self.drift) + self.offset_s

    def to_dict(self) -> Dict[str, float]:
        return {
            "sensor_ref_s": self.sensor_ref_s,
            "host_ref_s": self.host_ref_s,
            "offset_s": self.offset_s,
            "drift_ppm": self.drift * 1e6,
            "points": self.points,
            "delay_median_ms": self.delay_median_ms,
            "delay_p95_ms": self.delay_p95_ms,
        }


CLOCK_JUMP_SECONDS = 30.0


def split_clock_segments(frames: Sequence[dict]) -> List[List[dict]]:
    """Group PMD frame rows (receive order) into runs of one sensor clock.

    Receive time minus sensor time only moves by drift (~2 s over 8 h at
    70 ppm) and BLE delay; a jump beyond CLOCK_JUMP_SECONDS means the sensor
    clock was reset or changed.
    """
    ordered = sorted(frames, key=lambda row: row["host_mono"])
    segments: List[List[dict]] = []
    previous_offset = None
    for row in ordered:
        offset = row["host_mono"] - row["sensor_ns"] / 1e9
        if previous_offset is None or abs(offset - previous_offset) > CLOCK_JUMP_SECONDS:
            segments.append([])
        segments[-1].append(row)
        previous_offset = offset
    return segments


def fit_clock_mapping(sensor_s: Sequence[float], host_s: Sequence[float]) -> ClockMapping:
    """Lower-envelope line through (sensor, host - sensor).

    Linear program: maximize the line (minimize the summed delays) subject to
    every point lying on or above it. With 2 or fewer points it degrades to the
    minimum offset.
    """
    sensor = np.asarray(sensor_s, dtype=float)
    host = np.asarray(host_s, dtype=float)
    if sensor.size == 0:
        raise ValueError("no PMD frames to align")
    sensor_ref, host_ref = float(sensor[0]), float(host[0])
    x = sensor - sensor_ref
    y = host - host_ref - x
    if sensor.size <= 2 or np.ptp(x) <= 0:
        offset, drift = float(np.min(y)), 0.0
    else:
        scale = float(np.ptp(x))
        xs = x / scale
        result = linprog(
            c=[-float(xs.size), -float(xs.sum())],
            A_ub=np.column_stack([np.ones_like(xs), xs]),
            b_ub=y,
            bounds=[(None, None), (None, None)],
            method="highs",
        )
        if result.success:
            offset, drift = float(result.x[0]), float(result.x[1]) / scale
        else:
            offset, drift = float(np.min(y)), 0.0
    delays = (y - (offset + drift * x)) * 1000.0
    return ClockMapping(
        sensor_ref_s=sensor_ref,
        host_ref_s=host_ref,
        offset_s=offset,
        drift=drift,
        points=int(sensor.size),
        delay_median_ms=float(np.median(delays)),
        delay_p95_ms=float(np.percentile(delays, 95)),
    )


# On the 2026-10-09 calibration run the ECG turned to rail-to-rail noise ~13 s
# before the contact flag went false and stayed noise ~7 s after it came back.
NO_CONTACT_LEAD_SECONDS = 15.0
NO_CONTACT_TAIL_SECONDS = 10.0


def no_contact_spans(
    hr: pd.DataFrame,
    lead_s: float = NO_CONTACT_LEAD_SECONDS,
    tail_s: float = NO_CONTACT_TAIL_SECONDS,
    end_of_data: Optional[float] = None,
) -> List[Tuple[float, float]]:
    """Wall-clock spans around HR notifications that reported no skin contact.

    A span runs from lead_s before the first such notification to tail_s after
    the next one that reports contact again; None (contact not reported) leaves
    it as it is. A span still open at the last notification runs to end_of_data.
    """
    if hr.empty or "contact" not in hr:
        return []
    spans: List[Tuple[float, float]] = []
    start = None
    for time, contact in zip(hr["time"].to_numpy(dtype=float), hr["contact"]):
        if contact is None or pd.isna(contact):
            continue
        if not bool(contact) and start is None:
            start = time
        elif bool(contact) and start is not None:
            spans.append((float(start - lead_s), float(time + tail_s)))
            start = None
    if start is not None:
        last = float(hr["time"].iloc[-1])
        spans.append((float(start - lead_s), max(last, end_of_data if end_of_data is not None else last) + tail_s))
    merged: List[Tuple[float, float]] = []
    for low, high in spans:
        if merged and low <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], high))
        else:
            merged.append((low, high))
    return merged


def r_peaks_with_contact(
    ecg: pd.DataFrame,
    rate: float,
    spans: Sequence[Tuple[float, float]],
    config: CardioRespConfig,
) -> pd.DataFrame:
    """R-peaks found separately in each stretch of ECG outside the no-contact spans.

    Off the skin the H10 ECG swings rail to rail; left in, it would pick the
    detector's polarity and threshold for the whole recording.
    """
    times = ecg["time"].to_numpy(dtype=float)
    values = ecg["uv"].to_numpy(dtype=float)
    usable = np.ones(times.size, dtype=bool)
    for low, high in spans:
        usable &= ~((times >= low) & (times <= high))
    edges = np.flatnonzero(np.diff(np.concatenate(([0], usable.astype(np.int8), [0]))))
    found_times, found_amplitudes = [], []
    for first, stop in zip(edges[::2], edges[1::2]):
        if stop - first <= int(10 * config.ecg_rate_hz):
            continue
        positions, amplitudes = detect_r_peaks(values[first:stop], fs=rate, config=config)
        found_times.append(np.interp(positions, np.arange(stop - first), times[first:stop]))
        found_amplitudes.append(amplitudes)
    if not found_times:
        return pd.DataFrame({"time": [], "amplitude": []})
    return pd.DataFrame({"time": np.concatenate(found_times), "amplitude": np.concatenate(found_amplitudes)})


def _outside(frame: pd.DataFrame, spans: Sequence[Tuple[float, float]]) -> pd.DataFrame:
    if not spans or frame.empty:
        return frame
    times = frame["time"].to_numpy(dtype=float)
    inside = np.zeros(times.size, dtype=bool)
    for low, high in spans:
        inside |= (times >= low) & (times <= high)
    return frame.loc[~inside].reset_index(drop=True)


@dataclass
class PolarSession:
    ecg: pd.DataFrame  # time (host wall s), uv
    acc: pd.DataFrame  # time, x, y, z (mG)
    hr: pd.DataFrame  # time (receive), hr_bpm, contact
    rr: pd.DataFrame  # time (end of beat), rr_ms, aligned_to
    r_peaks: pd.DataFrame  # time, amplitude
    alignment: Dict[str, object] = field(default_factory=dict)
    quality: Dict[str, object] = field(default_factory=dict)
    # Wall-clock spans whose beats were dropped for lost skin contact.
    no_contact: List[Tuple[float, float]] = field(default_factory=list)


def load_polar_session(
    session_dir: Path,
    *,
    decode_if_missing: bool = True,
    config: Optional[CardioRespConfig] = None,
) -> PolarSession:
    config = config or CardioRespConfig()
    polar_dir = Path(session_dir) / POLAR_DIRNAME
    if decode_if_missing and not (polar_dir / "ecg.jsonl").exists():
        decode_polar_session(session_dir)
    ecg_rows = _read_jsonl(polar_dir / "ecg.jsonl")
    acc_rows = _read_jsonl(polar_dir / "acc.jsonl")
    hr_rows = _read_jsonl(polar_dir / "hr_rr.jsonl")
    anchors = _read_jsonl(polar_dir / "clock_anchors.jsonl")

    mono_to_wall, ntp_step_ms = _anchor_conversion(anchors, ecg_rows + acc_rows + hr_rows)
    alignment: Dict[str, object] = {"method": "lower_envelope_sensor_to_monotonic", "ntp_step_ms": ntp_step_ms}
    segments = split_clock_segments(ecg_rows + acc_rows)
    mappings = []
    for number, segment in enumerate(segments):
        mapping = fit_clock_mapping([row["sensor_ns"] / 1e9 for row in segment], [row["host_mono"] for row in segment])
        mappings.append(mapping)
        for row in segment:
            row["clock_segment"] = number
    if mappings:
        alignment["mapping"] = mappings[0].to_dict()
        alignment["clock_segments"] = [mapping.to_dict() for mapping in mappings]

    ecg = _expand(ecg_rows, ("uv",), mappings, mono_to_wall)
    acc = _expand(acc_rows, ("x", "y", "z"), mappings, mono_to_wall)
    hr = pd.DataFrame(
        {
            "time": [float(mono_to_wall(row["host_mono"])) for row in hr_rows],
            "hr_bpm": [row["hr_bpm"] for row in hr_rows],
            "contact": [row.get("contact") for row in hr_rows],
        }
    )

    device_rr = _device_beats(hr_rows, mono_to_wall)
    ends = [float(frame["time"].max()) for frame in (ecg, acc, hr, device_rr) if len(frame)]
    spans = no_contact_spans(hr, end_of_data=max(ends) if ends else None)

    r_peaks = pd.DataFrame({"time": [], "amplitude": []})
    if len(ecg) > int(10 * config.ecg_rate_hz):
        rate = ecg_sample_rate(ecg_rows) or config.ecg_rate_hz
        r_peaks = r_peaks_with_contact(ecg, rate, spans, config)

    device_beats = len(device_rr)
    device_rr = _outside(device_rr, spans)
    rr, rr_alignment = align_rr_to_ecg(device_rr, r_peaks["time"].to_numpy())
    alignment["rr"] = rr_alignment

    summary_path = polar_dir / "summary.json"
    quality: Dict[str, object] = {
        "ecg_samples": int(len(ecg)),
        "acc_samples": int(len(acc)),
        "hr_notifications": int(len(hr)),
        "rr_beats": int(len(rr)),
        "r_peaks": int(len(r_peaks)),
        "no_contact_spans": [[low, high] for low, high in spans],
        "no_contact_seconds": float(sum(high - low for low, high in spans)),
        "no_contact_dropped_rr": int(device_beats - len(device_rr)),
    }
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        quality.update(
            {
                "stop_reason": summary.get("stop_reason"),
                "reconnects": summary.get("reconnects"),
                "downtime_seconds": summary.get("downtime_seconds"),
                "decode_gaps": (summary.get("decode") or {}).get("gaps"),
            }
        )
    return PolarSession(
        ecg=ecg, acc=acc, hr=hr, rr=rr, r_peaks=r_peaks, alignment=alignment, quality=quality, no_contact=spans
    )


def ecg_sample_rate(ecg_rows: Sequence[dict]) -> Optional[float]:
    periods = [row["dt_ns"] for row in ecg_rows if row.get("dt_ns")]
    return 1e9 / float(np.median(periods)) if periods else None


def align_rr_to_ecg(
    device_beats: pd.DataFrame,
    r_peak_times: np.ndarray,
    *,
    search_back_seconds: float = 4.0,
    slack_seconds: float = 0.3,
    rr_tolerance_ms: float = 40.0,
) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """Put device RR beats on ECG R-peak times where the two agree.

    The HR service sends about once a second, but on a live H10 the last beat
    of a notification ended a median 2 s (max ~3.2 s) before it arrived. Each
    notification's RR batch is matched as a block against runs of consecutive
    ECG RR intervals ending within [receive - search_back, receive + slack];
    the run with the smallest mean RR difference wins if it is within
    ``rr_tolerance_ms``. Unmatched beats keep their receive-time estimate.
    """
    rr = device_beats.copy()
    rr["aligned_to"] = "host_receive"
    rr["ecg_rr_ms"] = math.nan
    info: Dict[str, object] = {"matched": 0, "beats": int(len(rr)), "notification_delay_s": None, "rr_agreement_ms": None}
    peaks = np.sort(np.asarray(r_peak_times, dtype=float))
    if rr.empty or peaks.size < 3:
        info["note"] = "no ECG R-peaks; RR beat times are receive-time estimates (typically ~2 s late)"
        return rr, info
    peak_rr = np.concatenate(([math.nan], np.diff(peaks) * 1000.0))

    times = rr["time"].to_numpy(dtype=float).copy()
    values = rr["rr_ms"].to_numpy(dtype=float)
    ecg_rr = np.full(len(rr), math.nan)
    aligned = np.zeros(len(rr), dtype=bool)
    delays = []
    last_used = 0
    for _notification, rows in rr.groupby("notification", sort=True).indices.items():
        rows = np.sort(rows)
        count = rows.size
        receive = float(rr["receive_time"].iloc[rows[-1]])
        ends = np.flatnonzero((peaks >= receive - search_back_seconds) & (peaks <= receive + slack_seconds))
        best, best_cost = None, math.inf
        for end in ends:
            first = end - count + 1
            if first < max(1, last_used + 1):
                continue
            cost = float(np.mean(np.abs(peak_rr[first : end + 1] - values[rows])))
            if cost < best_cost:
                best, best_cost = end, cost
        if best is None or best_cost > rr_tolerance_ms:
            continue
        first = best - count + 1
        times[rows] = peaks[first : best + 1]
        ecg_rr[rows] = peak_rr[first : best + 1]
        aligned[rows] = True
        delays.append(receive - peaks[best])
        last_used = best
    rr["time"] = times
    rr["ecg_rr_ms"] = ecg_rr
    rr.loc[aligned, "aligned_to"] = "ecg_r_peak"
    rr = rr.sort_values("time", kind="stable").reset_index(drop=True)
    differences = np.abs(values[aligned] - ecg_rr[aligned])
    info.update(
        {
            "matched": int(aligned.sum()),
            "notification_delay_s": float(np.median(delays)) if delays else None,
            "rr_agreement_ms": float(np.median(differences)) if differences.size else None,
            "rr_agreement_p95_ms": float(np.percentile(differences, 95)) if differences.size else None,
        }
    )
    return rr, info


def _device_beats(hr_rows: Sequence[dict], mono_to_wall) -> pd.DataFrame:
    """Each notification's RR list ends at about its receive time; walk backwards."""
    times: List[float] = []
    values: List[float] = []
    notifications: List[int] = []
    receives: List[float] = []
    for number, row in enumerate(hr_rows):
        intervals = row.get("rr_ms") or []
        end = float(mono_to_wall(row["host_mono"]))
        beat_end = end
        stamped = []
        for value in reversed(intervals):
            stamped.append((beat_end, value))
            beat_end -= value / 1000.0
        for time, value in reversed(stamped):
            times.append(time)
            values.append(value)
            notifications.append(number)
            receives.append(end)
    return pd.DataFrame({"time": times, "rr_ms": values, "notification": notifications, "receive_time": receives})


def _expand(rows: Sequence[dict], columns: Sequence[str], mappings: Sequence[ClockMapping], mono_to_wall) -> pd.DataFrame:
    if not rows or not mappings:
        return pd.DataFrame({"time": [], **{column: [] for column in columns}})
    host = np.concatenate(
        [
            mappings[row["clock_segment"]].to_host((row["t0_ns"] + row["dt_ns"] * np.arange(row["n"])) / 1e9)
            for row in rows
        ]
    )
    times = mono_to_wall(host)
    data = {"time": times}
    for column in columns:
        data[column] = np.concatenate([np.asarray(row[column], dtype=float) for row in rows])
    frame = pd.DataFrame(data).sort_values("time", kind="stable").reset_index(drop=True)
    return frame


def _anchor_conversion(anchors: Sequence[dict], rows: Sequence[dict]):
    """Monotonic -> wall via (wall - mono) interpolated over the anchors."""
    pairs = [(row["mono"], row["wall"] - row["mono"]) for row in anchors if "mono" in row and "wall" in row]
    if not pairs:
        pairs = [(row["host_mono"], row["host_wall"] - row["host_mono"]) for row in rows[:1]]
    if not pairs:
        return (lambda mono: np.asarray(mono, dtype=float)), None
    pairs.sort()
    monos = np.array([pair[0] for pair in pairs])
    offsets = np.array([pair[1] for pair in pairs])
    step_ms = float(np.max(np.abs(np.diff(offsets))) * 1000.0) if offsets.size > 1 else 0.0

    def convert(mono):
        mono = np.asarray(mono, dtype=float)
        return mono + np.interp(mono, monos, offsets)

    return convert, step_ms


def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return rows
