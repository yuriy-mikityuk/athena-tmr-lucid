"""Artifact and quality diagnostic helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.ndimage import median_filter

from muse_tmr.data.sample_types import MuseFrame

DEFAULT_EEG_CHANNELS = ("TP9", "AF7", "AF8", "TP10")
DEFAULT_FRONTAL_CHANNELS = ("AF7", "AF8")
DEFAULT_TEMPORAL_CHANNELS = ("TP9", "TP10")
DEFAULT_OPEN_BASELINE_PHASE = "eyes_open_baseline"
DEFAULT_BLINK_PHASE = "blink"
DEFAULT_CLOSED_EYES_PHASE = "eyes_closed_baseline"


@dataclass(frozen=True)
class ArtifactPhase:
    name: str
    duration_seconds: float
    instruction: str
    role: str = "stimulus"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("phase name must be non-empty")
        if self.duration_seconds <= 0:
            raise ValueError("phase duration_seconds must be positive")
        if not self.instruction:
            raise ValueError("phase instruction must be non-empty")

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "duration_seconds": self.duration_seconds,
            "instruction": self.instruction,
            "role": self.role,
        }


@dataclass(frozen=True)
class ArtifactDiagnosticConfig:
    sample_rate_hz: float = 256.0
    channels: Tuple[str, ...] = DEFAULT_EEG_CHANNELS
    frontal_channels: Tuple[str, ...] = DEFAULT_FRONTAL_CHANNELS
    temporal_channels: Tuple[str, ...] = DEFAULT_TEMPORAL_CHANNELS
    open_baseline_phase: str = DEFAULT_OPEN_BASELINE_PHASE
    blink_phase: str = DEFAULT_BLINK_PHASE
    closed_eyes_phase: str = DEFAULT_CLOSED_EYES_PHASE
    center_window_seconds: float = 5.0
    highpass_cutoff_hz: float = 0.5
    window_seconds: float = 1.0
    blink_ratio_threshold: float = 1.5
    blink_frontal_temporal_ratio_threshold: float = 1.1

    def validate(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if self.center_window_seconds <= 0:
            raise ValueError("center_window_seconds must be positive")
        if self.highpass_cutoff_hz <= 0:
            raise ValueError("highpass_cutoff_hz must be positive")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if not self.channels:
            raise ValueError("channels must be non-empty")

    def to_dict(self) -> Dict[str, object]:
        return {
            "sample_rate_hz": self.sample_rate_hz,
            "channels": list(self.channels),
            "frontal_channels": list(self.frontal_channels),
            "temporal_channels": list(self.temporal_channels),
            "open_baseline_phase": self.open_baseline_phase,
            "blink_phase": self.blink_phase,
            "closed_eyes_phase": self.closed_eyes_phase,
            "center_window_seconds": self.center_window_seconds,
            "highpass_cutoff_hz": self.highpass_cutoff_hz,
            "window_seconds": self.window_seconds,
            "blink_ratio_threshold": self.blink_ratio_threshold,
            "blink_frontal_temporal_ratio_threshold": (
                self.blink_frontal_temporal_ratio_threshold
            ),
        }


@dataclass(frozen=True)
class BlinkArtifactDiagnosticReport:
    source: str
    config: ArtifactDiagnosticConfig
    phases: Tuple[ArtifactPhase, ...]
    phase_metrics: Mapping[str, Mapping[str, Mapping[str, float]]]
    ratios_vs_open_baseline: Mapping[str, Mapping[str, object]]
    blink_summary: Mapping[str, object]
    closed_eyes_summary: Mapping[str, object]
    warnings: Tuple[str, ...] = ()
    source_metadata: Mapping[str, object] = field(default_factory=dict)
    source_diagnostics: Mapping[str, object] = field(default_factory=dict)
    session_summary: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": self.source,
            "config": self.config.to_dict(),
            "phases": [phase.to_dict() for phase in self.phases],
            "phase_metrics": _json_safe(self.phase_metrics),
            "ratios_vs_open_baseline": _json_safe(self.ratios_vs_open_baseline),
            "blink_summary": _json_safe(self.blink_summary),
            "closed_eyes_summary": _json_safe(self.closed_eyes_summary),
            "warnings": list(self.warnings),
            "source_metadata": _json_safe(self.source_metadata),
            "source_diagnostics": _json_safe(self.source_diagnostics),
            "session_summary": _json_safe(self.session_summary),
        }


def default_blink_artifact_phases(
    *,
    settle_seconds: float = 30.0,
    eyes_open_baseline_seconds: float = 45.0,
    blink_seconds: float = 20.0,
    recovery_open_seconds: float = 30.0,
    jaw_clench_seconds: float = 20.0,
    head_movement_seconds: float = 20.0,
    eyes_closed_baseline_seconds: float = 45.0,
) -> Tuple[ArtifactPhase, ...]:
    """Return the live blink/artifact diagnostic protocol.

    The closed-eyes baseline is deliberately last, so it cannot contaminate the
    open-eyes blink baseline.
    """

    return (
        ArtifactPhase(
            name="settle",
            duration_seconds=settle_seconds,
            instruction=(
                "Sit still while the signal settles. Keep eyes open and do not "
                "touch the headset. This phase is not used as the blink baseline."
            ),
            role="settle",
        ),
        ArtifactPhase(
            name=DEFAULT_OPEN_BASELINE_PHASE,
            duration_seconds=eyes_open_baseline_seconds,
            instruction=(
                "Eyes open. Look at one point, avoid deliberate blinking, do not "
                "talk, and do not move the jaw."
            ),
            role="baseline",
        ),
        ArtifactPhase(
            name=DEFAULT_BLINK_PHASE,
            duration_seconds=blink_seconds,
            instruction=(
                "Eyes open. Blink clearly about once per second. Keep the head still."
            ),
            role="blink",
        ),
        ArtifactPhase(
            name="recovery_open",
            duration_seconds=recovery_open_seconds,
            instruction="Eyes open. Sit still again, no deliberate blinking or jaw movement.",
            role="recovery",
        ),
        ArtifactPhase(
            name="jaw_clench",
            duration_seconds=jaw_clench_seconds,
            instruction=(
                "Eyes open. Lightly clench the jaw for about one second every "
                "three seconds. Do not touch the headset."
            ),
            role="artifact",
        ),
        ArtifactPhase(
            name="head_movement",
            duration_seconds=head_movement_seconds,
            instruction=(
                "Eyes open. Slowly turn the head left and right a few times. "
                "Do not touch the headset."
            ),
            role="artifact",
        ),
        ArtifactPhase(
            name=DEFAULT_CLOSED_EYES_PHASE,
            duration_seconds=eyes_closed_baseline_seconds,
            instruction=(
                "Close the eyes softly. Do not squeeze them shut, keep the jaw "
                "relaxed, and do not talk."
            ),
            role="closed_eyes_control",
        ),
    )


def analyze_blink_artifact_phases(
    phase_frames: Mapping[str, Sequence[MuseFrame]],
    *,
    source: str = "unknown",
    phases: Optional[Sequence[ArtifactPhase]] = None,
    config: Optional[ArtifactDiagnosticConfig] = None,
    source_metadata: Optional[Mapping[str, object]] = None,
    source_diagnostics: Optional[Mapping[str, object]] = None,
    session_summary: Optional[Mapping[str, object]] = None,
) -> BlinkArtifactDiagnosticReport:
    config = config or ArtifactDiagnosticConfig()
    config.validate()
    phase_specs = tuple(phases) if phases is not None else tuple(
        ArtifactPhase(name=name, duration_seconds=1.0, instruction=name)
        for name in phase_frames
    )
    phase_metrics = {
        phase_name: _phase_metrics(frames, config)
        for phase_name, frames in phase_frames.items()
    }
    ratios = _ratios_vs_open_baseline(phase_metrics, config)
    warnings = _diagnostic_warnings(phase_metrics, config)
    blink_summary = _blink_summary(ratios, phase_metrics, config)
    closed_eyes_summary = _closed_eyes_summary(ratios, phase_metrics, config)

    return BlinkArtifactDiagnosticReport(
        source=source,
        config=config,
        phases=phase_specs,
        phase_metrics=phase_metrics,
        ratios_vs_open_baseline=ratios,
        blink_summary=blink_summary,
        closed_eyes_summary=closed_eyes_summary,
        warnings=tuple(warnings),
        source_metadata=source_metadata or {},
        source_diagnostics=source_diagnostics or {},
        session_summary=session_summary or {},
    )


def _phase_metrics(
    frames: Sequence[MuseFrame],
    config: ArtifactDiagnosticConfig,
) -> Mapping[str, Mapping[str, float]]:
    channel_values = _collect_eeg_channel_values(frames, config.channels)
    return {
        channel: _channel_metrics(values, config)
        for channel, values in channel_values.items()
    }


def _collect_eeg_channel_values(
    frames: Iterable[MuseFrame],
    channels: Sequence[str],
) -> Mapping[str, Tuple[float, ...]]:
    collected = {channel: [] for channel in channels}
    for frame in frames:
        if frame.eeg is None:
            continue
        for channel in channels:
            values = frame.eeg.channels_uv.get(channel)
            if values is not None:
                collected[channel].extend(float(value) for value in values)
    return {channel: tuple(values) for channel, values in collected.items()}


def _channel_metrics(
    values: Sequence[float],
    config: ArtifactDiagnosticConfig,
) -> Mapping[str, float]:
    finite = _finite_array(values)
    if finite.size == 0:
        return _empty_channel_metrics()

    center_window_samples = max(1, int(round(config.center_window_seconds * config.sample_rate_hz)))
    if center_window_samples % 2 == 0:
        center_window_samples += 1
    center = median_filter(finite, size=center_window_samples, mode="nearest")
    centered = finite - center
    hp05 = _highpass(centered, config.sample_rate_hz, config.highpass_cutoff_hz)
    window_summary = _window_summary(
        hp05,
        sample_rate_hz=config.sample_rate_hz,
        window_seconds=config.window_seconds,
    )

    return {
        "count": float(finite.size),
        "raw_mean": float(np.mean(finite)),
        "raw_median": _median(finite),
        "raw_std": _std(finite),
        "raw_peak_to_peak": _peak_to_peak(finite),
        "raw_p99_abs": _percentile_abs(finite, 99.0),
        "centered_std": _std(centered),
        "centered_p95_abs": _percentile_abs(centered, 95.0),
        "centered_p99_abs": _percentile_abs(centered, 99.0),
        "centered_peak_to_peak": _peak_to_peak(centered),
        "hp05_std": _std(hp05),
        "hp05_p95_abs": _percentile_abs(hp05, 95.0),
        "hp05_p99_abs": _percentile_abs(hp05, 99.0),
        "hp05_peak_to_peak": _peak_to_peak(hp05),
        "window_hp05_p99_abs_max": window_summary["p99_abs_max"],
        "window_hp05_p99_abs_mean": window_summary["p99_abs_mean"],
    }


def _empty_channel_metrics() -> Mapping[str, float]:
    keys = (
        "count",
        "raw_mean",
        "raw_median",
        "raw_std",
        "raw_peak_to_peak",
        "raw_p99_abs",
        "centered_std",
        "centered_p95_abs",
        "centered_p99_abs",
        "centered_peak_to_peak",
        "hp05_std",
        "hp05_p95_abs",
        "hp05_p99_abs",
        "hp05_peak_to_peak",
        "window_hp05_p99_abs_max",
        "window_hp05_p99_abs_mean",
    )
    return {key: (0.0 if key == "count" else math.nan) for key in keys}


def _ratios_vs_open_baseline(
    phase_metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    config: ArtifactDiagnosticConfig,
) -> Mapping[str, Mapping[str, object]]:
    baseline = phase_metrics.get(config.open_baseline_phase, {})
    ratios: Dict[str, Mapping[str, object]] = {}
    for phase_name, channel_metrics in phase_metrics.items():
        if phase_name == config.open_baseline_phase:
            continue
        phase_ratios: Dict[str, object] = {}
        rank_items = []
        for channel in config.channels:
            current = channel_metrics.get(channel, {})
            base = baseline.get(channel, {})
            channel_ratios = {}
            for metric_name in (
                "centered_p99_abs",
                "centered_peak_to_peak",
                "hp05_std",
                "hp05_p99_abs",
                "hp05_peak_to_peak",
                "window_hp05_p99_abs_max",
            ):
                value = float(current.get(metric_name, math.nan))
                base_value = float(base.get(metric_name, math.nan))
                channel_ratios[f"{metric_name}_ratio"] = _safe_ratio(value, base_value)
                channel_ratios[f"{metric_name}_delta"] = _safe_delta(value, base_value)
            phase_ratios[channel] = channel_ratios
            rank_value = channel_ratios["hp05_p99_abs_ratio"]
            if isinstance(rank_value, float) and math.isfinite(rank_value):
                rank_items.append((channel, rank_value))
        phase_ratios["rank_by_hp05_p99_abs_ratio"] = [
            channel for channel, _ in sorted(rank_items, key=lambda item: item[1], reverse=True)
        ]
        ratios[phase_name] = phase_ratios
    return ratios


def _blink_summary(
    ratios: Mapping[str, Mapping[str, object]],
    phase_metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    config: ArtifactDiagnosticConfig,
) -> Mapping[str, object]:
    blink_ratios = ratios.get(config.blink_phase, {})
    frontal_ratio = _mean_channel_ratio(
        blink_ratios,
        config.frontal_channels,
        "hp05_p99_abs_ratio",
    )
    temporal_ratio = _mean_channel_ratio(
        blink_ratios,
        config.temporal_channels,
        "hp05_p99_abs_ratio",
    )
    frontal_window_ratio = _mean_channel_ratio(
        blink_ratios,
        config.frontal_channels,
        "window_hp05_p99_abs_max_ratio",
    )
    frontal_to_temporal = _safe_ratio(frontal_ratio, temporal_ratio)

    reason_codes = []
    if config.open_baseline_phase not in phase_metrics:
        reason_codes.append("missing_open_baseline")
    if config.blink_phase not in phase_metrics:
        reason_codes.append("missing_blink_phase")
    if not math.isfinite(frontal_ratio):
        reason_codes.append("missing_frontal_ratio")
    elif frontal_ratio < config.blink_ratio_threshold:
        reason_codes.append("weak_frontal_lift")
    if math.isfinite(frontal_to_temporal) and (
        frontal_to_temporal < config.blink_frontal_temporal_ratio_threshold
    ):
        reason_codes.append("frontal_not_above_temporal")

    detected = not reason_codes
    return {
        "phase": config.blink_phase,
        "frontal_channels": list(config.frontal_channels),
        "temporal_channels": list(config.temporal_channels),
        "frontal_hp05_p99_abs_ratio_mean": frontal_ratio,
        "temporal_hp05_p99_abs_ratio_mean": temporal_ratio,
        "frontal_to_temporal_hp05_p99_abs_ratio": frontal_to_temporal,
        "frontal_window_hp05_p99_abs_ratio_mean": frontal_window_ratio,
        "rank_by_hp05_p99_abs_ratio": blink_ratios.get("rank_by_hp05_p99_abs_ratio", []),
        "detected": detected,
        "reason_codes": reason_codes,
    }


def _closed_eyes_summary(
    ratios: Mapping[str, Mapping[str, object]],
    phase_metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    config: ArtifactDiagnosticConfig,
) -> Mapping[str, object]:
    closed_ratios = ratios.get(config.closed_eyes_phase, {})
    return {
        "phase": config.closed_eyes_phase,
        "present": config.closed_eyes_phase in phase_metrics,
        "role": "closed_eyes_control",
        "frontal_hp05_p99_abs_ratio_mean": _mean_channel_ratio(
            closed_ratios,
            config.frontal_channels,
            "hp05_p99_abs_ratio",
        ),
        "temporal_hp05_p99_abs_ratio_mean": _mean_channel_ratio(
            closed_ratios,
            config.temporal_channels,
            "hp05_p99_abs_ratio",
        ),
        "rank_by_hp05_p99_abs_ratio": closed_ratios.get("rank_by_hp05_p99_abs_ratio", []),
    }


def _diagnostic_warnings(
    phase_metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    config: ArtifactDiagnosticConfig,
) -> Tuple[str, ...]:
    warnings = []
    if config.open_baseline_phase not in phase_metrics:
        warnings.append("missing_open_baseline_phase")
    if config.closed_eyes_phase not in phase_metrics:
        warnings.append("missing_closed_eyes_phase")
    for phase_name, channel_metrics in phase_metrics.items():
        for channel in config.channels:
            count = channel_metrics.get(channel, {}).get("count", 0.0)
            if count <= 0:
                warnings.append(f"missing_eeg_samples:{phase_name}:{channel}")
    return tuple(warnings)


def _mean_channel_ratio(
    phase_ratios: Mapping[str, object],
    channels: Sequence[str],
    metric_name: str,
) -> float:
    values = []
    for channel in channels:
        channel_ratios = phase_ratios.get(channel, {})
        if not isinstance(channel_ratios, Mapping):
            continue
        value = channel_ratios.get(metric_name)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            values.append(float(value))
    return float(np.mean(values)) if values else math.nan


def _window_summary(
    values: np.ndarray,
    *,
    sample_rate_hz: float,
    window_seconds: float,
) -> Mapping[str, float]:
    if values.size == 0:
        return {"p99_abs_max": math.nan, "p99_abs_mean": math.nan}

    window_samples = max(1, int(round(sample_rate_hz * window_seconds)))
    step = max(1, window_samples // 2)
    min_samples = max(1, min(window_samples, window_samples // 2))
    window_values = []
    for start in range(0, values.size, step):
        segment = values[start : start + window_samples]
        if segment.size < min_samples:
            continue
        window_values.append(_percentile_abs(segment, 99.0))
    if not window_values:
        return {"p99_abs_max": math.nan, "p99_abs_mean": math.nan}
    return {
        "p99_abs_max": float(np.max(window_values)),
        "p99_abs_mean": float(np.mean(window_values)),
    }


def _highpass(values: np.ndarray, sample_rate_hz: float, cutoff_hz: float) -> np.ndarray:
    if values.size == 0:
        return values
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    dt = 1.0 / sample_rate_hz
    alpha = rc / (rc + dt)
    filtered = np.empty_like(values, dtype=float)
    filtered[0] = 0.0
    for idx in range(1, values.size):
        filtered[idx] = alpha * (filtered[idx - 1] + values[idx] - values[idx - 1])
    return filtered


def _finite_array(values: Sequence[float]) -> np.ndarray:
    data = np.asarray(tuple(values), dtype=float)
    if data.size == 0:
        return data
    return data[np.isfinite(data)]


def _median(values: np.ndarray) -> float:
    return float(np.median(values)) if values.size else math.nan


def _std(values: np.ndarray) -> float:
    return float(np.std(values)) if values.size else math.nan


def _peak_to_peak(values: np.ndarray) -> float:
    return float(np.ptp(values)) if values.size else math.nan


def _percentile_abs(values: np.ndarray, percentile: float) -> float:
    return float(np.percentile(np.abs(values), percentile)) if values.size else math.nan


def _safe_ratio(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator <= 0:
        return math.nan
    return numerator / denominator


def _safe_delta(value: float, baseline: float) -> float:
    if not math.isfinite(value) or not math.isfinite(baseline):
        return math.nan
    return value - baseline


def _json_safe(value):
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
