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


def compare_source_diagnostic_reports(
    report_paths: Sequence[Path],
) -> Tuple[SourceDiagnosticComparisonRow, ...]:
    return tuple(_comparison_row(Path(path)) for path in report_paths)


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
