"""Comparison tables for source diagnostic reports."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class SourceDiagnosticComparisonRow:
    session_id: str
    source: str
    preset: str
    report_path: str
    blink_detected: bool
    blink_reason_codes: Tuple[str, ...]
    blink_frontal_ratio: Optional[float]
    blink_temporal_ratio: Optional[float]
    blink_frontal_temporal_ratio: Optional[float]
    blink_rank: Tuple[str, ...]
    open_baseline_eeg_rate_hz: Optional[float]
    blink_eeg_rate_hz: Optional[float]
    open_baseline_eeg_missing_fraction: Optional[float]
    blink_eeg_missing_fraction: Optional[float]
    hr_present: Optional[bool]
    ppg_present: Optional[bool]
    imu_present: Optional[bool]
    battery_present: Optional[bool]
    modality_evidence: str
    disconnect_reason: str
    source_frame_count: Optional[int]

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "source": self.source,
            "preset": self.preset,
            "report_path": self.report_path,
            "blink_detected": self.blink_detected,
            "blink_reason_codes": list(self.blink_reason_codes),
            "blink_frontal_ratio": self.blink_frontal_ratio,
            "blink_temporal_ratio": self.blink_temporal_ratio,
            "blink_frontal_temporal_ratio": self.blink_frontal_temporal_ratio,
            "blink_rank": list(self.blink_rank),
            "open_baseline_eeg_rate_hz": self.open_baseline_eeg_rate_hz,
            "blink_eeg_rate_hz": self.blink_eeg_rate_hz,
            "open_baseline_eeg_missing_fraction": self.open_baseline_eeg_missing_fraction,
            "blink_eeg_missing_fraction": self.blink_eeg_missing_fraction,
            "hr_present": self.hr_present,
            "ppg_present": self.ppg_present,
            "imu_present": self.imu_present,
            "battery_present": self.battery_present,
            "modality_evidence": self.modality_evidence,
            "disconnect_reason": self.disconnect_reason,
            "source_frame_count": self.source_frame_count,
        }


@dataclass(frozen=True)
class BlinkChannelInspectionRow:
    session_id: str
    source: str
    preset: str
    phase: str
    channel: str
    channel_group: str
    report_path: str
    rank: Optional[int]
    count: Optional[float]
    raw_mean: Optional[float]
    raw_median: Optional[float]
    raw_std: Optional[float]
    raw_peak_to_peak: Optional[float]
    centered_p95_abs: Optional[float]
    centered_p99_abs: Optional[float]
    centered_peak_to_peak: Optional[float]
    hp05_std: Optional[float]
    hp05_p95_abs: Optional[float]
    hp05_p99_abs: Optional[float]
    hp05_peak_to_peak: Optional[float]
    centered_p99_abs_ratio: Optional[float]
    hp05_p99_abs_ratio: Optional[float]
    hp05_peak_to_peak_ratio: Optional[float]
    frontal_hp05_p99_abs_ratio_mean: Optional[float]
    temporal_hp05_p99_abs_ratio_mean: Optional[float]
    frontal_temporal_hp05_p99_abs_ratio: Optional[float]

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "source": self.source,
            "preset": self.preset,
            "phase": self.phase,
            "channel": self.channel,
            "channel_group": self.channel_group,
            "report_path": self.report_path,
            "rank": self.rank,
            "count": self.count,
            "raw_mean": self.raw_mean,
            "raw_median": self.raw_median,
            "raw_std": self.raw_std,
            "raw_peak_to_peak": self.raw_peak_to_peak,
            "centered_p95_abs": self.centered_p95_abs,
            "centered_p99_abs": self.centered_p99_abs,
            "centered_peak_to_peak": self.centered_peak_to_peak,
            "hp05_std": self.hp05_std,
            "hp05_p95_abs": self.hp05_p95_abs,
            "hp05_p99_abs": self.hp05_p99_abs,
            "hp05_peak_to_peak": self.hp05_peak_to_peak,
            "centered_p99_abs_ratio": self.centered_p99_abs_ratio,
            "hp05_p99_abs_ratio": self.hp05_p99_abs_ratio,
            "hp05_peak_to_peak_ratio": self.hp05_peak_to_peak_ratio,
            "frontal_hp05_p99_abs_ratio_mean": self.frontal_hp05_p99_abs_ratio_mean,
            "temporal_hp05_p99_abs_ratio_mean": self.temporal_hp05_p99_abs_ratio_mean,
            "frontal_temporal_hp05_p99_abs_ratio": self.frontal_temporal_hp05_p99_abs_ratio,
        }


def compare_source_diagnostic_reports(
    report_paths: Sequence[Path],
) -> Tuple[SourceDiagnosticComparisonRow, ...]:
    return tuple(_comparison_row(Path(path)) for path in report_paths)


def inspect_blink_channel_reports(
    report_paths: Sequence[Path],
    *,
    phases: Optional[Sequence[str]] = None,
) -> Tuple[BlinkChannelInspectionRow, ...]:
    phase_filter = tuple(phases) if phases else None
    rows = []
    for path in report_paths:
        rows.extend(_channel_inspection_rows(Path(path), phase_filter))
    return tuple(rows)


def format_source_diagnostic_markdown(
    rows: Sequence[SourceDiagnosticComparisonRow],
) -> str:
    headers = (
        "session",
        "source",
        "preset",
        "blink",
        "frontal",
        "temporal",
        "F/T",
        "rank",
        "baseline Hz",
        "blink Hz",
        "baseline missing",
        "blink missing",
        "HR",
        "PPG",
        "IMU",
        "battery",
        "modality evidence",
        "disconnect",
    )
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        values = (
            row.session_id,
            row.source,
            row.preset,
            "yes" if row.blink_detected else "no",
            _format_float(row.blink_frontal_ratio),
            _format_float(row.blink_temporal_ratio),
            _format_float(row.blink_frontal_temporal_ratio),
            ",".join(row.blink_rank),
            _format_float(row.open_baseline_eeg_rate_hz),
            _format_float(row.blink_eeg_rate_hz),
            _format_percent(row.open_baseline_eeg_missing_fraction),
            _format_percent(row.blink_eeg_missing_fraction),
            _format_bool(row.hr_present),
            _format_bool(row.ppg_present),
            _format_bool(row.imu_present),
            _format_bool(row.battery_present),
            row.modality_evidence,
            row.disconnect_reason or "none",
        )
        lines.append("| " + " | ".join(_escape_markdown(value) for value in values) + " |")
    return "\n".join(lines)


def format_blink_channel_inspection_markdown(
    rows: Sequence[BlinkChannelInspectionRow],
) -> str:
    headers = (
        "session",
        "source",
        "preset",
        "phase",
        "channel",
        "group",
        "rank",
        "count",
        "raw median",
        "raw std",
        "raw p2p",
        "centered p99",
        "hp05 p99",
        "hp05 p2p",
        "centered ratio",
        "hp05 ratio",
        "hp05 p2p ratio",
        "frontal ratio",
        "temporal ratio",
        "F/T",
    )
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        values = (
            row.session_id,
            row.source,
            row.preset,
            row.phase,
            row.channel,
            row.channel_group,
            _format_optional_int(row.rank),
            _format_count(row.count),
            _format_float(row.raw_median),
            _format_float(row.raw_std),
            _format_float(row.raw_peak_to_peak),
            _format_float(row.centered_p99_abs),
            _format_float(row.hp05_p99_abs),
            _format_float(row.hp05_peak_to_peak),
            _format_float(row.centered_p99_abs_ratio),
            _format_float(row.hp05_p99_abs_ratio),
            _format_float(row.hp05_peak_to_peak_ratio),
            _format_float(row.frontal_hp05_p99_abs_ratio_mean),
            _format_float(row.temporal_hp05_p99_abs_ratio_mean),
            _format_float(row.frontal_temporal_hp05_p99_abs_ratio),
        )
        lines.append("| " + " | ".join(_escape_markdown(value) for value in values) + " |")
    return "\n".join(lines)


def save_source_diagnostic_comparison(
    rows: Sequence[SourceDiagnosticComparisonRow],
    output_path: Path,
    *,
    output_format: Optional[str] = None,
) -> Path:
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = output_format or _format_from_suffix(output_path)
    if fmt == "json":
        output_path.write_text(
            json.dumps([row.to_dict() for row in rows], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    elif fmt == "csv":
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].to_dict()) if rows else [])
            writer.writeheader()
            for row in rows:
                payload = row.to_dict()
                payload["blink_reason_codes"] = ";".join(payload["blink_reason_codes"])
                payload["blink_rank"] = ";".join(payload["blink_rank"])
                writer.writerow(payload)
    elif fmt == "markdown":
        output_path.write_text(format_source_diagnostic_markdown(rows) + "\n", encoding="utf-8")
    else:
        raise ValueError("comparison output format must be json, csv, or markdown")
    return output_path


def save_blink_channel_inspection(
    rows: Sequence[BlinkChannelInspectionRow],
    output_path: Path,
    *,
    output_format: Optional[str] = None,
) -> Path:
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = output_format or _format_from_suffix(output_path)
    if fmt == "json":
        output_path.write_text(
            json.dumps([row.to_dict() for row in rows], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    elif fmt == "csv":
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].to_dict()) if rows else [])
            writer.writeheader()
            for row in rows:
                writer.writerow(row.to_dict())
    elif fmt == "markdown":
        output_path.write_text(format_blink_channel_inspection_markdown(rows) + "\n", encoding="utf-8")
    else:
        raise ValueError("inspection output format must be json, csv, or markdown")
    return output_path


def _comparison_row(report_path: Path) -> SourceDiagnosticComparisonRow:
    report_path = report_path.expanduser().resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    source = str(report.get("source") or _nested(report, "source_metadata", "source_name") or "unknown")
    source_metadata = report.get("source_metadata") if isinstance(report.get("source_metadata"), Mapping) else {}
    source_diagnostics = (
        report.get("source_diagnostics")
        if isinstance(report.get("source_diagnostics"), Mapping)
        else {}
    )
    session_summary = (
        report.get("session_summary")
        if isinstance(report.get("session_summary"), Mapping)
        else {}
    )
    blink = report.get("blink_summary") if isinstance(report.get("blink_summary"), Mapping) else {}
    config = report.get("config") if isinstance(report.get("config"), Mapping) else {}
    sample_rate_hz = _as_float(config.get("sample_rate_hz")) or 256.0
    baseline_phase = str(config.get("open_baseline_phase") or "eyes_open_baseline")
    blink_phase = str(config.get("blink_phase") or "blink")

    return SourceDiagnosticComparisonRow(
        session_id=str(session_summary.get("session_id") or report_path.stem),
        source=source,
        preset=_report_preset(source, source_metadata),
        report_path=str(report_path),
        blink_detected=bool(blink.get("detected")),
        blink_reason_codes=tuple(str(reason) for reason in blink.get("reason_codes", ())),
        blink_frontal_ratio=_finite_or_none(blink.get("frontal_hp05_p99_abs_ratio_mean")),
        blink_temporal_ratio=_finite_or_none(blink.get("temporal_hp05_p99_abs_ratio_mean")),
        blink_frontal_temporal_ratio=_finite_or_none(
            blink.get("frontal_to_temporal_hp05_p99_abs_ratio")
        ),
        blink_rank=tuple(str(channel) for channel in blink.get("rank_by_hp05_p99_abs_ratio", ())),
        open_baseline_eeg_rate_hz=_phase_eeg_rate(report, baseline_phase),
        blink_eeg_rate_hz=_phase_eeg_rate(report, blink_phase),
        open_baseline_eeg_missing_fraction=_missing_fraction(
            _phase_eeg_rate(report, baseline_phase),
            sample_rate_hz,
        ),
        blink_eeg_missing_fraction=_missing_fraction(
            _phase_eeg_rate(report, blink_phase),
            sample_rate_hz,
        ),
        hr_present=_modality_present(report, "heart_rate", source),
        ppg_present=_modality_present(report, "ppg", source),
        imu_present=_modality_present(report, "imu", source),
        battery_present=_modality_present(report, "battery", source),
        modality_evidence=_modality_evidence(report),
        disconnect_reason=str(source_diagnostics.get("disconnect_reason") or ""),
        source_frame_count=_optional_int(source_diagnostics.get("frame_count")),
    )


def _channel_inspection_rows(
    report_path: Path,
    phase_filter: Optional[Sequence[str]],
) -> Tuple[BlinkChannelInspectionRow, ...]:
    report_path = report_path.expanduser().resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    source = str(report.get("source") or _nested(report, "source_metadata", "source_name") or "unknown")
    source_metadata = report.get("source_metadata") if isinstance(report.get("source_metadata"), Mapping) else {}
    session_summary = (
        report.get("session_summary")
        if isinstance(report.get("session_summary"), Mapping)
        else {}
    )
    config = report.get("config") if isinstance(report.get("config"), Mapping) else {}
    phase_metrics = report.get("phase_metrics") if isinstance(report.get("phase_metrics"), Mapping) else {}
    ratios = (
        report.get("ratios_vs_open_baseline")
        if isinstance(report.get("ratios_vs_open_baseline"), Mapping)
        else {}
    )
    channels = tuple(str(channel) for channel in config.get("channels", ("TP9", "AF7", "AF8", "TP10")))
    frontal_channels = tuple(str(channel) for channel in config.get("frontal_channels", ("AF7", "AF8")))
    temporal_channels = tuple(str(channel) for channel in config.get("temporal_channels", ("TP9", "TP10")))
    baseline_phase = str(config.get("open_baseline_phase") or "eyes_open_baseline")
    selected_phases = tuple(phase_filter) if phase_filter else tuple(str(phase) for phase in phase_metrics)
    rows = []
    for phase_name in selected_phases:
        metrics_by_channel = phase_metrics.get(phase_name)
        if not isinstance(metrics_by_channel, Mapping):
            continue
        phase_ratios = ratios.get(phase_name) if isinstance(ratios.get(phase_name), Mapping) else {}
        rank = _rank_lookup(phase_ratios)
        group_summary = _phase_group_ratio_summary(
            phase_name,
            baseline_phase,
            phase_ratios,
            frontal_channels,
            temporal_channels,
        )
        for channel in channels:
            metrics = metrics_by_channel.get(channel)
            if not isinstance(metrics, Mapping):
                continue
            channel_ratios = (
                phase_ratios.get(channel) if isinstance(phase_ratios.get(channel), Mapping) else {}
            )
            if phase_name == baseline_phase and not channel_ratios:
                channel_ratios = _baseline_channel_ratios()
            rows.append(
                BlinkChannelInspectionRow(
                    session_id=str(session_summary.get("session_id") or report_path.stem),
                    source=source,
                    preset=_report_preset(source, source_metadata),
                    phase=phase_name,
                    channel=channel,
                    channel_group=_channel_group(channel, frontal_channels, temporal_channels),
                    report_path=str(report_path),
                    rank=rank.get(channel),
                    count=_finite_or_none(metrics.get("count")),
                    raw_mean=_finite_or_none(metrics.get("raw_mean")),
                    raw_median=_finite_or_none(metrics.get("raw_median")),
                    raw_std=_finite_or_none(metrics.get("raw_std")),
                    raw_peak_to_peak=_finite_or_none(metrics.get("raw_peak_to_peak")),
                    centered_p95_abs=_finite_or_none(metrics.get("centered_p95_abs")),
                    centered_p99_abs=_finite_or_none(metrics.get("centered_p99_abs")),
                    centered_peak_to_peak=_finite_or_none(metrics.get("centered_peak_to_peak")),
                    hp05_std=_finite_or_none(metrics.get("hp05_std")),
                    hp05_p95_abs=_finite_or_none(metrics.get("hp05_p95_abs")),
                    hp05_p99_abs=_finite_or_none(metrics.get("hp05_p99_abs")),
                    hp05_peak_to_peak=_finite_or_none(metrics.get("hp05_peak_to_peak")),
                    centered_p99_abs_ratio=_finite_or_none(
                        channel_ratios.get("centered_p99_abs_ratio")
                    ),
                    hp05_p99_abs_ratio=_finite_or_none(channel_ratios.get("hp05_p99_abs_ratio")),
                    hp05_peak_to_peak_ratio=_finite_or_none(
                        channel_ratios.get("hp05_peak_to_peak_ratio")
                    ),
                    frontal_hp05_p99_abs_ratio_mean=group_summary["frontal"],
                    temporal_hp05_p99_abs_ratio_mean=group_summary["temporal"],
                    frontal_temporal_hp05_p99_abs_ratio=group_summary["frontal_temporal"],
                )
            )
    return tuple(rows)


def _phase_eeg_rate(report: Mapping[str, object], phase_name: str) -> Optional[float]:
    duration = _phase_duration(report, phase_name)
    if duration is None or duration <= 0:
        return None
    phase_metrics = report.get("phase_metrics")
    if not isinstance(phase_metrics, Mapping):
        return None
    metrics = phase_metrics.get(phase_name)
    if not isinstance(metrics, Mapping):
        return None
    counts = [
        _as_float(channel_metrics.get("count"))
        for channel_metrics in metrics.values()
        if isinstance(channel_metrics, Mapping)
    ]
    counts = [count for count in counts if count is not None]
    if not counts:
        return None
    return float(sum(counts) / len(counts) / duration)


def _phase_duration(report: Mapping[str, object], phase_name: str) -> Optional[float]:
    phases = report.get("phases")
    if not isinstance(phases, Iterable):
        return None
    for phase in phases:
        if isinstance(phase, Mapping) and phase.get("name") == phase_name:
            return _as_float(phase.get("duration_seconds"))
    return None


def _missing_fraction(rate_hz: Optional[float], expected_hz: float) -> Optional[float]:
    if rate_hz is None or expected_hz <= 0:
        return None
    return max(0.0, 1.0 - min(rate_hz / expected_hz, 1.0))


def _modality_present(report: Mapping[str, object], modality: str, source: str) -> Optional[bool]:
    total_counts = _nested(report, "session_summary", "total_modality_counts")
    if isinstance(total_counts, Mapping) and modality in total_counts:
        return bool(_optional_int(total_counts.get(modality)) or 0)

    capabilities = _nested(report, "source_metadata", "capabilities")
    if isinstance(capabilities, Mapping) and modality in capabilities:
        return bool(capabilities[modality])

    defaults = {
        "amused": {"heart_rate": True, "ppg": True, "imu": True, "battery": True},
        "brainflow": {"heart_rate": False, "ppg": True, "imu": True, "battery": True},
    }
    source_defaults = defaults.get(source)
    if source_defaults is None:
        return None
    return source_defaults.get(modality)


def _modality_evidence(report: Mapping[str, object]) -> str:
    if _nested(report, "session_summary", "total_modality_counts") is not None:
        return "observed"
    if _nested(report, "source_metadata", "capabilities") is not None:
        return "capability"
    return "source_default"


def _report_preset(source: str, source_metadata: Mapping[str, object]) -> str:
    metadata = source_metadata.get("metadata")
    if isinstance(metadata, Mapping):
        preset = metadata.get("preset")
        if preset:
            return str(preset)
    defaults = {"brainflow": "p1041", "amused": "p1034"}
    return defaults.get(source, "unknown")


def _phase_group_ratio_summary(
    phase_name: str,
    baseline_phase: str,
    phase_ratios: Mapping[str, object],
    frontal_channels: Sequence[str],
    temporal_channels: Sequence[str],
) -> Mapping[str, Optional[float]]:
    if phase_name == baseline_phase and not phase_ratios:
        frontal = 1.0
        temporal = 1.0
    else:
        frontal = _mean_channel_ratio(phase_ratios, frontal_channels, "hp05_p99_abs_ratio")
        temporal = _mean_channel_ratio(phase_ratios, temporal_channels, "hp05_p99_abs_ratio")
    return {
        "frontal": frontal,
        "temporal": temporal,
        "frontal_temporal": _optional_ratio(frontal, temporal),
    }


def _mean_channel_ratio(
    phase_ratios: Mapping[str, object],
    channels: Sequence[str],
    metric_name: str,
) -> Optional[float]:
    values = []
    for channel in channels:
        channel_ratios = phase_ratios.get(channel)
        if not isinstance(channel_ratios, Mapping):
            continue
        value = _finite_or_none(channel_ratios.get(metric_name))
        if value is not None:
            values.append(value)
    return sum(values) / len(values) if values else None


def _optional_ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _rank_lookup(phase_ratios: Mapping[str, object]) -> Mapping[str, int]:
    rank = phase_ratios.get("rank_by_hp05_p99_abs_ratio")
    if not isinstance(rank, Iterable) or isinstance(rank, (str, bytes)):
        return {}
    return {str(channel): idx + 1 for idx, channel in enumerate(rank)}


def _baseline_channel_ratios() -> Mapping[str, float]:
    return {
        "centered_p99_abs_ratio": 1.0,
        "hp05_p99_abs_ratio": 1.0,
        "hp05_peak_to_peak_ratio": 1.0,
    }


def _channel_group(
    channel: str,
    frontal_channels: Sequence[str],
    temporal_channels: Sequence[str],
) -> str:
    if channel in frontal_channels:
        return "frontal"
    if channel in temporal_channels:
        return "temporal"
    return "other"


def _nested(payload: Mapping[str, object], *keys: str):
    current = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _as_float(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_or_none(value) -> Optional[float]:
    return _as_float(value)


def _optional_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_optional_int(value: Optional[int]) -> str:
    return "unknown" if value is None else str(value)


def _format_count(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    return str(int(value)) if value.is_integer() else f"{value:.3f}"


def _format_float(value: Optional[float]) -> str:
    return "unknown" if value is None else f"{value:.3f}"


def _format_percent(value: Optional[float]) -> str:
    return "unknown" if value is None else f"{value * 100:.1f}%"


def _format_bool(value: Optional[bool]) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _escape_markdown(value: str) -> str:
    return str(value).replace("|", "\\|")


def _format_from_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        return "csv"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    return "markdown"
