"""Pilot 1 validation for overnight no-audio recordings."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

PILOT1_SCHEMA_VERSION = 1
DEFAULT_PILOT1_MIN_DURATION_SECONDS = 6 * 60 * 60
DEFAULT_PILOT1_REQUIRED_MODALITIES = ("eeg", "imu", "ppg")
DEFAULT_PILOT1_MAX_DOWNTIME_FRACTION = 0.05
NO_AUDIO_SIDECAR_PATTERNS = (
    "*audio*.jsonl",
    "*cue*.jsonl",
    "*scheduler*.jsonl",
    "*tlr*.jsonl",
)


@dataclass(frozen=True)
class Pilot1Criterion:
    name: str
    passed: bool
    observed: Any
    target: str
    message: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "observed": self.observed,
            "target": self.target,
            "message": self.message,
        }


@dataclass(frozen=True)
class Pilot1ValidationReport:
    recording_dir: str
    summary_path: str
    criteria: Tuple[Pilot1Criterion, ...]
    metrics: Mapping[str, object] = field(default_factory=dict)
    coverage_targets: Mapping[str, object] = field(default_factory=dict)
    generated_at_utc: str = ""
    schema_version: int = PILOT1_SCHEMA_VERSION
    pilot_id: str = "m8_pilot1_no_audio_recording"

    def __post_init__(self) -> None:
        object.__setattr__(self, "criteria", tuple(self.criteria))
        if not self.generated_at_utc:
            object.__setattr__(self, "generated_at_utc", _utc_now())

    @property
    def passed(self) -> bool:
        return all(criterion.passed for criterion in self.criteria)

    @property
    def failed_criteria(self) -> Tuple[str, ...]:
        return tuple(criterion.name for criterion in self.criteria if not criterion.passed)

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "pilot_id": self.pilot_id,
            "generated_at_utc": self.generated_at_utc,
            "passed": self.passed,
            "failed_criteria": list(self.failed_criteria),
            "recording_dir": self.recording_dir,
            "summary_path": self.summary_path,
            "criteria": [criterion.to_dict() for criterion in self.criteria],
            "coverage_targets": dict(self.coverage_targets),
            "metrics": dict(self.metrics),
        }

    def save(self, output_path: Path) -> Path:
        output_path = output_path.expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return output_path


def validate_pilot1_recording(
    input_path: Path,
    *,
    min_duration_seconds: float = DEFAULT_PILOT1_MIN_DURATION_SECONDS,
    required_modalities: Iterable[str] = DEFAULT_PILOT1_REQUIRED_MODALITIES,
    max_downtime_fraction: float = DEFAULT_PILOT1_MAX_DOWNTIME_FRACTION,
) -> Pilot1ValidationReport:
    if min_duration_seconds <= 0:
        raise ValueError("min_duration_seconds must be positive")
    if max_downtime_fraction < 0:
        raise ValueError("max_downtime_fraction must be non-negative")

    input_path = input_path.expanduser()
    summary_path = _summary_path(input_path)
    recording_dir = summary_path.parent

    criteria = [
        Pilot1Criterion(
            name="summary_exists",
            passed=summary_path.exists(),
            observed=str(summary_path),
            target="summary.json exists",
        )
    ]
    if not summary_path.exists():
        return Pilot1ValidationReport(
            recording_dir=str(recording_dir),
            summary_path=str(summary_path),
            criteria=tuple(criteria),
        )

    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        criteria.append(
            Pilot1Criterion(
                name="summary_parseable",
                passed=False,
                observed=str(exc),
                target="valid JSON",
            )
        )
        return Pilot1ValidationReport(
            recording_dir=str(recording_dir),
            summary_path=str(summary_path),
            criteria=tuple(criteria),
        )

    recording_dir = _recording_dir(payload, summary_path)
    duration_seconds = _float(payload.get("duration_seconds"))
    downtime_seconds = _float(payload.get("downtime_seconds"))
    downtime_fraction = downtime_seconds / duration_seconds if duration_seconds > 0 else None
    modality_counts = _modality_counts(payload.get("modality_counts", {}))
    required = _required_modalities(required_modalities)
    raw_path = _resolve_recording_path(payload.get("raw_path"), recording_dir)
    no_audio_sidecars = _no_audio_sidecars(recording_dir)

    criteria.extend(
        [
            Pilot1Criterion(
                name="summary_parseable",
                passed=True,
                observed="valid JSON",
                target="valid JSON",
            ),
            Pilot1Criterion(
                name="duration_at_least_minimum",
                passed=duration_seconds >= min_duration_seconds,
                observed=duration_seconds,
                target=f">= {min_duration_seconds:.0f} seconds",
            ),
            Pilot1Criterion(
                name="stop_reason_duration_complete",
                passed=str(payload.get("stop_reason", "")) == "duration_complete",
                observed=str(payload.get("stop_reason", "")),
                target="duration_complete",
            ),
            Pilot1Criterion(
                name="raw_capture_present",
                passed=bool(raw_path and raw_path.exists() and _int(payload.get("raw_packet_count")) > 0),
                observed={
                    "raw_path": str(raw_path) if raw_path is not None else "",
                    "raw_packet_count": _int(payload.get("raw_packet_count")),
                },
                target="raw packet file exists and raw_packet_count > 0",
            ),
            Pilot1Criterion(
                name="downtime_fraction_within_target",
                passed=downtime_fraction is not None and downtime_fraction <= max_downtime_fraction,
                observed=downtime_fraction,
                target=f"<= {max_downtime_fraction}",
            ),
            Pilot1Criterion(
                name="no_audio_sidecars",
                passed=not no_audio_sidecars,
                observed=[str(path) for path in no_audio_sidecars],
                target="no audio, cue, scheduler, or TLR sidecar logs in the recording directory",
            ),
        ]
    )
    criteria.extend(
        Pilot1Criterion(
            name=f"required_modality_{modality}_present",
            passed=modality_counts.get(modality, 0) > 0,
            observed=modality_counts.get(modality, 0),
            target="> 0 frames",
        )
        for modality in required
    )

    coverage_targets = {
        modality: {
            "frame_count": modality_counts.get(modality, 0),
            "target": "> 0 frames",
            "passed": modality_counts.get(modality, 0) > 0,
        }
        for modality in required
    }
    metrics = {
        "duration_seconds": duration_seconds,
        "duration_hours": duration_seconds / 3600 if duration_seconds > 0 else 0.0,
        "frame_count": _int(payload.get("frame_count")),
        "raw_packet_count": _int(payload.get("raw_packet_count")),
        "modality_counts": modality_counts,
        "reconnect_attempts": _int(payload.get("reconnect_attempts")),
        "downtime_seconds": downtime_seconds,
        "downtime_fraction": downtime_fraction,
        "stop_reason": str(payload.get("stop_reason", "")),
        "no_audio_sidecar_count": len(no_audio_sidecars),
    }
    return Pilot1ValidationReport(
        recording_dir=str(recording_dir),
        summary_path=str(summary_path),
        criteria=tuple(criteria),
        coverage_targets=coverage_targets,
        metrics=metrics,
    )


def _summary_path(input_path: Path) -> Path:
    if input_path.name == "summary.json":
        return input_path
    if input_path.suffix == ".json" and input_path.is_file():
        return input_path
    return input_path / "summary.json"


def _recording_dir(payload: Mapping[str, object], summary_path: Path) -> Path:
    output_dir = payload.get("output_dir")
    if isinstance(output_dir, str) and output_dir.strip():
        return Path(output_dir).expanduser()
    return summary_path.parent


def _resolve_recording_path(value: object, recording_dir: Path) -> Optional[Path]:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return recording_dir / path


def _required_modalities(values: Iterable[str]) -> Tuple[str, ...]:
    modalities = tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    if not modalities:
        raise ValueError("required_modalities must not be empty")
    return modalities


def _modality_counts(value: object) -> Dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): _int(count) for key, count in value.items()}


def _no_audio_sidecars(recording_dir: Path) -> Tuple[Path, ...]:
    if not recording_dir.exists() or not recording_dir.is_dir():
        return ()
    matches = []
    for pattern in NO_AUDIO_SIDECAR_PATTERNS:
        matches.extend(
            path
            for path in recording_dir.glob(pattern)
            if path.name not in {"metadata.json", "summary.json", "events.jsonl"}
        )
    return tuple(sorted(set(matches)))


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()
