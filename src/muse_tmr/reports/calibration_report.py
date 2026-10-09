"""Report for one voice-guided calibration run (``calibration-run``).

From one recording it answers:

1. Muscle. How many dB the 55-95 Hz EMG indicator rises on its own channels
   (jaw on TP9/TP10, forehead on AF7/AF8) for slight and for strong tension,
   and how far LZC and the 1/f slope move with it. 30-45 Hz sits next to it,
   because that is the part of the EMG that overlaps the EEG metrics; 55-95 Hz
   is only its proxy.
2. Breathing. The three breathing-rate estimates against a known pace.
3. Inhale vs exhale. Whether chest ACC shows the 4:6 and 2:3 asymmetry, and
   whether heart rate alone picks the ACC direction that is inhaling.
4. The H10 unclip: when contact and the Bluetooth link dropped and came back.

Every tension segment is compared with relaxed windows of its own length on
both sides (see ``muse_tmr.protocol.calibration``), through the same
analyze-meditation code, so each pair also gets its own meditation report.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import AsyncIterable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from muse_tmr.data.sample_types import MuseFrame
from muse_tmr.features.complexity_features import ComplexityConfig
from muse_tmr.features.epochs import EpochBuilder, EpochConfig
from muse_tmr.protocol.calibration import (
    CALIBRATION_DIRNAME,
    PROTOCOL,
    TENSION_PAIRS,
    load_cues,
    pair_blocks,
    segments_from_cues,
)
from muse_tmr.reports.meditation_analysis import (
    EpochRecord,
    MeditationAnalysis,
    MeditationAnalysisConfig,
    MeditationBlock,
    MeditationBlocks,
    _epoch_record,
    assign_block,
    build_meditation_analysis,
    json_safe,
)
from muse_tmr.reports.meditation_report import _PAGE, _e, _fmt, _num, _table

# 2: EMG without the 64 Hz device line; inhale check reports the ACC peak
# against the exhale cue instead of the trough-to-peak share.
CALIBRATION_REPORT_SCHEMA_VERSION = 2
PAIR_LABELS = {"jaw": "Jaw, slight", "forehead": "Forehead, slight", "clench": "Clench pulses", "breathing": "6/min vs 12/min"}
GROUP_LABELS = (("all", "all"), ("frontal", "AF7/AF8"), ("temporal", "TP9/TP10"))
_UNSET = MeditationBlock(index=-1, condition="", start_s=0.0, end_s=0.0)


@dataclass(frozen=True)
class CalibrationReportConfig:
    epoch_seconds: float = 10.0
    # Tension starts right after the instruction, so only its first seconds are skipped.
    trim_block_start_seconds: float = 10.0
    # Paced breathing: skip the first cycles while breathing locks onto the voice.
    breathing_settle_seconds: float = 10.0
    complexity: ComplexityConfig = field(default_factory=lambda: ComplexityConfig(lyapunov_enabled=False))

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["complexity"] = self.complexity.to_dict()
        return payload


@dataclass
class CalibrationReport:
    summary: Dict[str, object]
    analyses: Dict[str, MeditationAnalysis]

    def write(self, output_dir: Path) -> Dict[str, Path]:
        output_dir = Path(output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, analysis in self.analyses.items():
            analysis.write(output_dir / name)
        paths = {"summary": output_dir / "summary.json", "report": output_dir / "report.html"}
        paths["summary"].write_text(json.dumps(json_safe(self.summary), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        paths["report"].write_text(render_calibration_report(self.summary), encoding="utf-8")
        return paths


async def build_calibration_report_from_frames(
    frames: AsyncIterable[MuseFrame],
    segments: Sequence[Mapping[str, object]],
    *,
    polar=None,
    polar_events: Sequence[Mapping[str, object]] = (),
    polar_error: Optional[str] = None,
    stop_reason: Optional[str] = None,
    recording: str = "",
    config: Optional[CalibrationReportConfig] = None,
) -> CalibrationReport:
    config = config or CalibrationReportConfig()
    records, origin = await _all_epochs(frames, config)
    if origin is None:
        raise ValueError("the recording has no Muse frames")
    analysis_config = MeditationAnalysisConfig(
        epoch_seconds=config.epoch_seconds,
        trim_block_start_seconds=config.trim_block_start_seconds,
        emg_indicator="emg_power_55_95",
        complexity=config.complexity,
    )
    analyses: Dict[str, MeditationAnalysis] = {}
    pairs: Dict[str, object] = {}
    for name, blocks in pair_blocks(segments).items():
        pair_records = _reassign(records, blocks, config.trim_block_start_seconds)
        if not pair_records:
            pairs[name] = {"error": "no epochs inside the blocks"}
            continue
        analysis = build_meditation_analysis(
            pair_records, blocks, analysis_config, recording=recording, polar=polar, origin_time=origin
        )
        analyses[name] = analysis
        pairs[name] = _pair_numbers(name, analysis, blocks)

    summary: Dict[str, object] = {
        "schema_version": CALIBRATION_REPORT_SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "recording": recording,
        "first_frame_time": origin,
        "stop_reason": stop_reason,
        "config": config.to_dict(),
        "segments": [dict(item) for item in segments],
        "pairs": pairs,
        "timeline": _timeline(records, segments),
    }
    if polar is not None:
        summary["breathing"] = _breathing_reference(polar, origin, segments, config)
        summary["h10"] = _h10_unclip(polar, polar_events, origin, segments)
    else:
        summary["breathing"] = []
        summary["h10"] = {"available": False, "error": polar_error}
    return CalibrationReport(summary=summary, analyses=analyses)


async def build_calibration_report(
    recording_dir: Path, config: Optional[CalibrationReportConfig] = None
) -> CalibrationReport:
    from muse_tmr.data.replay import ReplayConfig, ReplaySession

    recording_dir = Path(recording_dir)
    calibration = recording_dir / CALIBRATION_DIRNAME
    if not (calibration / "cues.jsonl").is_file():
        raise ValueError(f"{recording_dir} has no {CALIBRATION_DIRNAME}/cues.jsonl: not a calibration run")
    stop_reason = None
    try:
        saved = json.loads((calibration / "segments.json").read_text(encoding="utf-8"))
        segments, stop_reason = saved["segments"], saved.get("stop_reason")
    except (OSError, ValueError, KeyError):
        # The guide was killed before it wrote segments.json; the cue log is enough.
        segments = segments_from_cues(load_cues(recording_dir))

    polar, polar_error, events = None, None, []
    polar_dir = recording_dir / "polar"
    if (polar_dir / "raw_notifications.jsonl").exists():
        from muse_tmr.data.polar_session import load_polar_session

        try:
            polar = load_polar_session(recording_dir)
        except Exception as exc:  # a broken Polar log must not stop the EEG part
            polar_error = f"{type(exc).__name__}: {exc}"
        events = _read_jsonl(polar_dir / "events.jsonl")
    else:
        polar_error = "no polar/ folder in this recording"

    session = ReplaySession(ReplayConfig(input_path=recording_dir, speed=0.0))
    await session.connect()
    try:
        return await build_calibration_report_from_frames(
            session.stream(),
            segments,
            polar=polar,
            polar_events=events,
            polar_error=polar_error,
            stop_reason=stop_reason,
            recording=str(recording_dir),
            config=config,
        )
    finally:
        await session.stop()


# --- EEG ---------------------------------------------------------------------


async def _all_epochs(frames, config: CalibrationReportConfig) -> Tuple[List[EpochRecord], Optional[float]]:
    """Features for every epoch once; each pair then picks its own."""
    builder = EpochBuilder(
        EpochConfig(epoch_seconds=config.epoch_seconds, stride_seconds=config.epoch_seconds, emit_partial=False)
    )
    analysis_config = MeditationAnalysisConfig(epoch_seconds=config.epoch_seconds, complexity=config.complexity)
    records: List[EpochRecord] = []
    origin: Optional[float] = None
    async for epoch in builder.build(frames):
        if origin is None:
            origin = epoch.start_time
        start_s = epoch.start_time - origin
        records.append(_epoch_record(epoch, _UNSET, start_s, start_s + config.epoch_seconds, analysis_config))
    return records, origin


def _reassign(records: Sequence[EpochRecord], blocks: MeditationBlocks, trim_seconds: float) -> List[EpochRecord]:
    selected = []
    for record in records:
        block = assign_block(record.start_s, record.end_s, blocks, trim_seconds)
        if block is None:
            continue
        features = {**record.features, "block_index": block.index, "condition": block.condition}
        selected.append(EpochRecord(block=block, start_s=record.start_s, end_s=record.end_s, features=features, channels=record.channels))
    return selected


def _pair_numbers(name: str, analysis: MeditationAnalysis, blocks: MeditationBlocks) -> Dict[str, object]:
    contrasts = {(item["metric"], item["group"], item["variant"]): item for item in analysis.summary["contrasts"]}
    condition_a, condition_b = blocks.condition_pair()
    table = analysis.blocks
    variants = {}
    for variant in ("all", "clean"):
        rows = table[table["variant"] == variant]

        def difference(metric: str, group: str = "all") -> float:
            item = contrasts.get((metric, group, variant)) or {}
            return float(item.get("difference", math.nan))

        variants[variant] = {
            "epochs": {
                condition: int(rows.loc[rows["condition"] == condition, "epochs"].sum())
                for condition in (condition_a, condition_b)
            },
            "emg_55_95_db": {group: 10.0 * difference("emg_power_55_95", group) for group, _ in GROUP_LABELS},
            "emg_30_45_db": {group: 10.0 * difference("emg_power_30_45", group) for group, _ in GROUP_LABELS},
            "lzc_all": difference("lzc"),
            "aperiodic_exponent_2_40_all": difference("aperiodic_exponent_2_40"),
            "aperiodic_exponent_2_20_all": difference("aperiodic_exponent_2_20"),
            "band_power_gamma_db": 10.0 * difference("band_power_gamma"),
        }
    return {
        "conditions": [condition_a, condition_b],
        "contrast": f"{condition_a} - {condition_b}",
        "blocks": [block.to_dict() for block in blocks.blocks],
        "variants": variants,
        "report": f"{name}/report.html",
    }


def _timeline(records: Sequence[EpochRecord], segments: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    rows = []
    for record in records:
        middle = (record.start_s + record.end_s) / 2
        segment = next(
            (item["name"] for item in segments if float(item["start_s"]) <= middle < float(item["end_s"])), None
        )
        features = record.features
        rows.append(
            {
                "start_s": record.start_s,
                "segment": segment,
                "artifact": bool(features.get("is_artifact")),
                "emg_55_95_frontal_db": _db(features.get("emg_power_55_95_frontal")),
                "emg_55_95_temporal_db": _db(features.get("emg_power_55_95_temporal")),
                "emg_30_45_frontal_db": _db(features.get("emg_power_30_45_frontal")),
                "emg_30_45_temporal_db": _db(features.get("emg_power_30_45_temporal")),
                "lzc_all": _num(features.get("lzc_all")),
            }
        )
    return rows


# --- breathing -----------------------------------------------------------------


def _breathing_reference(polar, origin: float, segments, config: CalibrationReportConfig) -> List[Dict[str, object]]:
    from muse_tmr.features.cardio_resp_features import extract_cardio_resp_features

    results = []
    for segment in segments:
        rate = segment.get("known_rate_bpm")
        cycles = [float(value) for value in segment.get("cycle_starts_s") or ()]
        if not rate or len(cycles) < 3:
            continue
        period = float(segment["pace_period_s"])
        start = cycles[0] + config.breathing_settle_seconds
        end = cycles[-1] + period
        features = extract_cardio_resp_features(polar, origin + start, origin + end)
        estimates = {
            "acc_spectral": features.get("resp_rate_bpm", math.nan),
            "acc_breath": features.get("resp_rate_breath_bpm", math.nan),
            "edr": features.get("edr_rate_bpm", math.nan),
        }
        beats = segment.get("beats") or ()
        exhale_at = next((float(offset) for offset, _word in beats if float(offset) > 0), None)
        locked = [cycle for cycle in cycles if cycle >= start and cycle + period <= end + 1e-6]
        results.append(
            {
                "segment": segment["name"],
                "known_rate_bpm": float(rate),
                "window_s": [start, end],
                "estimates_bpm": estimates,
                "errors_bpm": {key: value - float(rate) for key, value in estimates.items()},
                "resp_reliable": features.get("resp_reliable"),
                "acc_posture_change_pct": features.get("acc_posture_change_pct"),
                "inhale_exhale": inhale_exhale_check(polar, origin, locked, period, exhale_at)
                if exhale_at is not None
                else None,
            }
        )
    return results


def inhale_exhale_check(
    polar,
    origin: float,
    cycle_starts_s: Sequence[float],
    period_s: float,
    inhale_s: float,
    fs: float = 10.0,
) -> Dict[str, object]:
    """Average chest ACC and heart rate over the paced cycles, locked to the "inhale" cue.

    The ACC breathing component has an arbitrary sign. Oriented by the cues
    (rising through the inhale), its peak should sit at the exhale cue. The
    trough is no use: after a quick passive exhale the chest rests until the
    next inhale, so trough-to-peak overstates the inhale (0.76 of the cycle for
    a paced 0.4 on the first real run). The check without cues: does heart
    rate, which rises on the inhale, pick the same sign?
    """
    from muse_tmr.features.cardio_resp_features import acc_breathing_component, correct_rr

    cycles = sorted(float(value) for value in cycle_starts_s)
    result: Dict[str, object] = {"cycles": 0, "expected_inhale_fraction": inhale_s / period_s}
    if len(cycles) < 3 or polar.acc is None or len(polar.acc) == 0:
        return result
    margin = 5.0
    window = (origin + cycles[0] - margin, origin + cycles[-1] + period_s + margin)
    acc = polar.acc[(polar.acc["time"] >= window[0]) & (polar.acc["time"] < window[1])]
    if len(acc) < 10:
        return result
    grid, component = acc_breathing_component(acc["time"].to_numpy(), acc[["x", "y", "z"]].to_numpy())
    phase = np.arange(int(round(period_s * fs))) / fs
    cycle_times = [origin + cycle + phase for cycle in cycles if origin + cycle >= grid[0] and origin + cycle + period_s <= grid[-1]]
    if len(cycle_times) < 3:
        return result
    acc_cycles = np.array([np.interp(times, grid, component) for times in cycle_times])
    acc_wave = acc_cycles.mean(axis=0)

    hr_wave = None
    rr = polar.rr[(polar.rr["time"] >= window[0]) & (polar.rr["time"] < window[1])] if polar.rr is not None else None
    if rr is not None and len(rr) >= 8:
        corrected, _flags = correct_rr(rr["rr_ms"].to_numpy(dtype=float))
        hr_times, hr = rr["time"].to_numpy(dtype=float), 60000.0 / corrected
        hr_cycles = np.array([np.interp(times, hr_times, hr) for times in cycle_times])
        hr_wave = (hr_cycles - hr_cycles.mean(axis=1, keepdims=True)).mean(axis=0)

    cue_sign = 1.0 if np.interp(inhale_s, phase, acc_wave) >= acc_wave[0] else -1.0
    oriented = cue_sign * acc_wave
    peak = int(np.argmax(oriented))
    span = float(np.ptp(oriented)) or 1.0
    result.update(
        {
            "cycles": len(cycle_times),
            "acc_peak_s": float(phase[peak]),
            "acc_peak_after_exhale_cue_s": _wrap(float(phase[peak]) - inhale_s, period_s),
            "acc_amplitude_mg": span,
            "acc_wave": [round(float(value), 4) for value in (oriented - oriented.min()) / span],
        }
    )
    if hr_wave is not None and np.ptp(hr_wave) > 0:
        correlation = float(np.corrcoef(oriented, hr_wave)[0, 1])
        hr_peak = float(phase[int(np.argmax(hr_wave))])
        result.update(
            {
                "hr_peak_s": hr_peak,
                "hr_swing_bpm": float(np.ptp(hr_wave)),
                "acc_hr_correlation": correlation,
                # HR rises on the inhale, so a positive correlation means HR alone
                # would have picked the same ACC sign as the cues.
                "hr_picks_inhale_direction": correlation > 0,
                "hr_wave": [round(float(value), 3) for value in hr_wave],
            }
        )
    return result


def _wrap(offset_s: float, period_s: float) -> float:
    """Offset folded into [-period/2, period/2)."""
    return (offset_s + period_s / 2.0) % period_s - period_s / 2.0


# --- H10 unclip ------------------------------------------------------------------


def _h10_unclip(polar, events: Sequence[Mapping[str, object]], origin: float, segments) -> Dict[str, object]:
    by_name = {item["name"]: item for item in segments}
    off = by_name.get("h10_off")
    if off is None:
        return {"available": False, "error": "the run stopped before the unclip step"}
    back = by_name.get("h10_back")
    start = float(off["start_s"]) - 5.0
    end = float(back["end_s"]) if back else float(off["end_s"]) + 120.0
    link_events = [
        {"event": item.get("event"), "elapsed_s": float(item["wall"]) - origin}
        for item in events
        if item.get("event") in ("disconnected", "connected", "connect_failed")
        and start <= float(item.get("wall", math.nan)) - origin <= end
    ]
    ecg_times = polar.ecg["time"].to_numpy(dtype=float) - origin if polar.ecg is not None and len(polar.ecg) else np.array([])
    in_window = ecg_times[(ecg_times >= start) & (ecg_times <= end)]
    # The window edges count too: ECG that never came back is a gap up to the end.
    points = np.concatenate(([start], in_window, [end]))
    steps = np.diff(points)
    index = int(np.argmax(steps))
    gap = None
    if steps[index] > 1.0:
        gap = {
            "from_s": float(points[index]),
            "to_s": float(points[index + 1]),
            "seconds": float(steps[index]),
            "until_end": bool(index + 1 == points.size - 1),
        }
    contact_lost_s = contact_back_s = None
    if polar.hr is not None and len(polar.hr):
        hr = polar.hr.assign(elapsed=polar.hr["time"] - origin)
        lost = hr[(hr["elapsed"] >= float(off["start_s"])) & (hr["contact"] == False)]  # noqa: E712 (None means unknown)
        if len(lost):
            contact_lost_s = float(lost["elapsed"].iloc[0])
            regained = hr[(hr["elapsed"] > contact_lost_s) & (hr["contact"] == True)]  # noqa: E712
            if len(regained):
                contact_back_s = float(regained["elapsed"].iloc[0])
    tail = ecg_times[(ecg_times >= end - 60.0) & (ecg_times <= end)]
    return {
        "available": True,
        "unclip_cue_s": float(off["start_s"]),
        "clip_back_cue_s": float(back["start_s"]) if back else None,
        "link_events": link_events,
        "disconnects": sum(1 for item in link_events if item["event"] == "disconnected"),
        "reconnects": sum(1 for item in link_events if item["event"] == "connected"),
        "ecg_gap": gap,
        "contact_lost_s": contact_lost_s,
        "contact_back_s": contact_back_s,
        "ecg_rate_last_minute_hz": float(tail.size / 60.0) if tail.size else 0.0,
    }


# --- page ------------------------------------------------------------------------


def render_calibration_report(summary: Mapping[str, object]) -> str:
    name = str(summary.get("recording") or "").rstrip("/").split("/")[-1] or "calibration"
    sections = [
        _header(name, summary),
        _tension_section(summary.get("pairs") or {}),
        _timeline_section(summary.get("timeline") or [], summary.get("segments") or []),
        _breathing_section(
            summary.get("breathing") or [],
            (summary.get("pairs") or {}).get("breathing"),
            _num((summary.get("config") or {}).get("breathing_settle_seconds")),
        ),
        _inhale_section(summary.get("breathing") or []),
        _h10_section(summary.get("h10") or {}),
    ]
    body = "\n".join(section for section in sections if section)
    return _PAGE.format(title=_e(f"Calibration run {name}"), body=body)


def _header(name: str, summary: Mapping[str, object]) -> str:
    segments = summary.get("segments") or []
    done = sum(1 for item in segments if item.get("completed"))
    stop = summary.get("stop_reason")
    status = f"{done} of {len(PROTOCOL)} steps completed" + (f", stopped: {str(stop).replace('_', ' ')}" if stop and stop != "completed" else "")
    return (
        f"<header><h1>Calibration run <span class=mono>{_e(name)}</span></h1>"
        f"<p class=muted>{_e(status)} · generated {_e(str(summary.get('generated_at', ''))[:16].replace('T', ' '))} UTC</p></header>"
    )


def _tension_section(pairs: Mapping[str, object]) -> str:
    rows = []
    for name, *_rest in TENSION_PAIRS:
        pair = pairs.get(name)
        if not pair:
            continue
        if "error" in pair:
            rows.append([_e(PAIR_LABELS[name]), _e(str(pair["error"]))] + [""] * 8)
            continue
        for variant in ("all", "clean"):
            item = pair["variants"][variant]
            epochs = item["epochs"]
            label = f'<a href="{_e(pair["report"])}">{_e(PAIR_LABELS[name])}</a>' if variant == "all" else ""
            rows.append(
                [
                    label,
                    variant,
                    " / ".join(str(epochs.get(condition, 0)) for condition in pair["conditions"]),
                    _fmt(item["emg_55_95_db"]["frontal"], 1, signed=True),
                    _fmt(item["emg_55_95_db"]["temporal"], 1, signed=True),
                    _fmt(item["emg_30_45_db"]["frontal"], 1, signed=True),
                    _fmt(item["emg_30_45_db"]["temporal"], 1, signed=True),
                    _fmt(item["lzc_all"], 3, signed=True),
                    _fmt(item["aperiodic_exponent_2_40_all"], 2, signed=True),
                    _fmt(item["aperiodic_exponent_2_20_all"], 2, signed=True),
                ]
            )
    if not rows:
        return "<section><h2>Muscle tension</h2><p class=muted>No tension step completed.</p></section>"
    return (
        "<section><h2>Muscle tension</h2>"
        "<p>Each tension step minus the relaxed minutes on both sides of it, so slow drift cancels. "
        "dB is 10·log10 of the power ratio. The jaw should show on TP9/TP10 and the forehead on AF7/AF8. "
        "55–95 Hz is the indicator; 30–45 Hz is the muscle activity that actually overlaps the EEG metrics. "
        "<i>clean</i> drops artifact-flagged epochs, which can be exactly the tense ones.</p>"
        + _table(
            [
                "Step",
                "Epochs",
                "Tense / relaxed",
                "55–95 AF dB",
                "55–95 TP dB",
                "30–45 AF dB",
                "30–45 TP dB",
                "ΔLZC all",
                "Δ1/f 2–40",
                "Δ1/f 2–20",
            ],
            rows,
        )
        + "</section>"
    )


def _timeline_section(timeline: Sequence[Mapping[str, object]], segments: Sequence[Mapping[str, object]]) -> str:
    points = [row for row in timeline if math.isfinite(_num(row.get("emg_55_95_temporal_db")))]
    if len(points) < 2:
        return ""
    width, height, left, top, bottom = 860, 220, 44, 26, 24
    end_s = max(float(row["start_s"]) for row in timeline) + 10.0
    values = [
        _num(row.get(key))
        for row in points
        for key in ("emg_55_95_frontal_db", "emg_55_95_temporal_db")
        if math.isfinite(_num(row.get(key)))
    ]
    low, high = min(values) - 1.0, max(values) + 1.0

    def x(seconds: float) -> float:
        return left + seconds / end_s * (width - left - 4)

    def y(value: float) -> float:
        return top + (high - value) / (high - low) * (height - top - bottom)

    shapes = []
    for item in segments:
        condition = item.get("condition")
        if condition and condition != "relaxed":
            x0, x1 = x(float(item["start_s"])), x(float(item["end_s"]))
            shapes.append(f'<rect x="{x0:.1f}" y="{top}" width="{max(1.0, x1 - x0):.1f}" height="{height - top - bottom}" class="band"><title>{_e(str(item.get("label")))}</title></rect>')
            shapes.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{top - 8}" class="lbl" text-anchor="middle">{_e(str(condition))}</text>')
    for key, css in (("emg_55_95_frontal_db", "af"), ("emg_55_95_temporal_db", "tp")):
        path = " ".join(
            f"{x(float(row['start_s']) + 5.0):.1f},{y(_num(row[key])):.1f}" for row in points if math.isfinite(_num(row.get(key)))
        )
        shapes.append(f'<polyline points="{path}" class="line {css}"/>')
    for minute in range(0, int(end_s // 60) + 1, 2):
        shapes.append(f'<text x="{x(minute * 60):.1f}" y="{height - 6}" class="lbl" text-anchor="middle">{minute}</text>')
    shapes.append(f'<text x="2" y="{y(high - 1):.1f}" class="lbl">{high - 1:.0f} dB</text>')
    shapes.append(f'<text x="2" y="{y(low + 1):.1f}" class="lbl">{low + 1:.0f} dB</text>')
    return (
        "<section><h2>55–95 Hz power over the run</h2>"
        "<p class=muted>Per 10 s epoch, dB. <span class=af>AF7/AF8</span> and <span class=tp>TP9/TP10</span>; "
        "shaded steps are not relaxed. Minutes on the axis. The first minutes show how long the muscles take to settle.</p>"
        f'<svg viewBox="0 0 {width} {height}" class="timeline" role="img" aria-label="EMG power over the run">'
        + "".join(shapes)
        + "</svg>"
        "<style>.timeline{width:100%;height:auto}.timeline .band{fill:var(--line);opacity:.6}"
        ".timeline .line{fill:none;stroke-width:1.8}.timeline .af{stroke:var(--a)}.timeline .tp{stroke:var(--b)}"
        ".timeline .lbl{fill:var(--muted);font-size:11px}span.af{color:var(--a);font-weight:600}span.tp{color:var(--b);font-weight:600}</style>"
        "</section>"
    )


def _breathing_section(
    breathing: Sequence[Mapping[str, object]], pair: Optional[Mapping[str, object]], settle_seconds: float
) -> str:
    if not breathing:
        return ""
    rows = []
    for item in breathing:
        estimates, errors = item["estimates_bpm"], item["errors_bpm"]
        rows.append(
            [
                _e(str(item["segment"])),
                _fmt(item["known_rate_bpm"], 0),
                f"{_fmt(estimates['acc_spectral'], 1)} ({_fmt(errors['acc_spectral'], 1, signed=True)})",
                f"{_fmt(estimates['acc_breath'], 1)} ({_fmt(errors['acc_breath'], 1, signed=True)})",
                f"{_fmt(estimates['edr'], 1)} ({_fmt(errors['edr'], 1, signed=True)})",
                "yes" if _num(item.get("resp_reliable")) == 1.0 else "no",
            ]
        )
    link = f' The <a href="{_e(pair["report"])}">6 vs 12/min report</a> has the EEG side.' if pair and "report" in pair else ""
    return (
        "<section><h2>Breathing against a known pace</h2>"
        f"<p>Breathing paced by voice; the first {_fmt(settle_seconds, 0)} s after the first cue are skipped. "
        f"Estimate (error) in breaths/min.{link}</p>"
        + _table(["Step", "Paced /min", "ACC spectral", "ACC breath-by-breath", "ECG-derived", "Trusted by the gate"], rows)
        + "</section>"
    )


def _inhale_section(breathing: Sequence[Mapping[str, object]]) -> str:
    checks = [(item["segment"], item.get("inhale_exhale") or {}) for item in breathing]
    checks = [(segment, check) for segment, check in checks if check.get("cycles")]
    if not checks:
        return ""
    rows, plots = [], []
    for segment, check in checks:
        rows.append(
            [
                _e(str(segment)),
                str(check["cycles"]),
                _fmt(check.get("acc_peak_after_exhale_cue_s"), 1, signed=True),
                _fmt(check.get("hr_peak_s"), 1),
                _fmt(check.get("hr_swing_bpm"), 1),
                _fmt(check.get("acc_hr_correlation"), 2, signed=True),
                {True: "yes", False: "no"}.get(check.get("hr_picks_inhale_direction"), "–"),
            ]
        )
        plots.append(_cycle_plot(str(segment), check))
    return (
        "<section><h2>Inhale vs exhale</h2>"
        "<p>Chest ACC and heart rate averaged over the paced cycles, from the “inhale” cue. "
        "Oriented by the cues, ACC rises through the inhale, so its peak should sit at the exhale cue. "
        "The last column is the check without cues: heart rate rises on the inhale, so does it pick the same ACC direction?</p>"
        + _table(
            ["Step", "Cycles", "ACC peak after exhale cue, s", "HR peak s", "HR swing bpm", "r(ACC, HR)", "HR picks inhale"],
            rows,
        )
        + "".join(plots)
        + "</section>"
    )


def _cycle_plot(segment: str, check: Mapping[str, object]) -> str:
    acc = [float(value) for value in check.get("acc_wave") or ()]
    if len(acc) < 2:
        return ""
    width, height, left = 420, 120, 6
    n = len(acc)
    hr = [float(value) for value in check.get("hr_wave") or ()]

    def series(values: Sequence[float], css: str) -> str:
        low, high = min(values), max(values)
        span = (high - low) or 1.0
        points = " ".join(
            f"{left + index / (n - 1) * (width - 2 * left):.1f},{10 + (high - value) / span * (height - 30):.1f}"
            for index, value in enumerate(values)
        )
        return f'<polyline points="{points}" class="{css}"/>'

    exhale = float(check["expected_inhale_fraction"])
    x_exhale = left + exhale * (width - 2 * left)
    return (
        f'<figure class="cycle"><svg viewBox="0 0 {width} {height}" role="img" aria-label="Average breathing cycle, {_e(segment)}">'
        f'<line x1="{x_exhale:.1f}" x2="{x_exhale:.1f}" y1="6" y2="{height - 18}" class="cue"/>'
        + series(acc, "acc")
        + (series(hr, "hr") if len(hr) == n else "")
        + f'<text x="{left}" y="{height - 4}" class="lbl">inhale cue</text>'
        f'<text x="{x_exhale + 4:.1f}" y="{height - 4}" class="lbl">exhale cue</text>'
        "</svg>"
        f"<figcaption class=muted>{_e(segment)}: <span class=af>ACC</span>, <span class=tp>HR</span></figcaption></figure>"
        "<style>.cycle{display:inline-block;width:min(420px,100%);margin:8px 12px 0 0}.cycle svg{width:100%;height:auto}"
        ".cycle .acc{fill:none;stroke:var(--a);stroke-width:2}.cycle .hr{fill:none;stroke:var(--b);stroke-width:2}"
        ".cycle .cue{stroke:var(--line);stroke-dasharray:3 3}.cycle .lbl{fill:var(--muted);font-size:11px}</style>"
    )


def _h10_section(h10: Mapping[str, object]) -> str:
    if not h10.get("available"):
        error = h10.get("error")
        return f"<section><h2>H10 unclip</h2><p class=muted>{_e(str(error or 'No Polar data.'))}</p></section>"

    def at(seconds) -> str:
        value = _num(seconds)
        return "–" if not math.isfinite(value) else f"{int(value // 60)}:{int(value % 60):02d}"

    gap = h10.get("ecg_gap")
    parts = [f"Unclip cue at {at(h10.get('unclip_cue_s'))}, clip-back cue at {at(h10.get('clip_back_cue_s'))}."]
    if h10.get("contact_lost_s") is not None:
        parts.append(f"Skin contact lost at {at(h10['contact_lost_s'])}, back at {at(h10.get('contact_back_s'))}.")
    parts.append(f"Bluetooth: {h10.get('disconnects', 0)} disconnect(s), {h10.get('reconnects', 0)} reconnect(s).")
    if gap and gap.get("until_end"):
        parts.append(f"ECG stopped at {at(gap['from_s'])} and did not come back before the end.")
    elif gap:
        parts.append(f"Longest ECG gap {_fmt(gap['seconds'], 0)} s ({at(gap['from_s'])}–{at(gap['to_s'])}).")
    else:
        parts.append("No ECG gap over 1 s: the strap kept streaming.")
    parts.append(f"ECG in the last minute: {_fmt(h10.get('ecg_rate_last_minute_hz'), 1)} samples/s (130 expected).")
    events = [[_e(str(item["event"])), at(item["elapsed_s"])] for item in h10.get("link_events") or ()]
    return "<section><h2>H10 unclip</h2><p>" + " ".join(_e(part) for part in parts) + "</p>" + _table(["Event", "At"], events) + "</section>"


# --- helpers ---------------------------------------------------------------------


def _db(value) -> float:
    number = _num(value)
    return 10.0 * math.log10(number) if math.isfinite(number) and number > 0 else math.nan


def _read_jsonl(path: Path) -> List[Dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows
