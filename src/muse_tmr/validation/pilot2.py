"""Pilot 2 validation for audio calibration only workflows."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from muse_tmr.audio import VolumeCalibration, load_volume_calibrations

PILOT2_SCHEMA_VERSION = 1
DEFAULT_PILOT2_HARD_MAX_VOLUME = 0.20


@dataclass(frozen=True)
class Pilot2Criterion:
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
class Pilot2ValidationReport:
    calibration_path: str
    criteria: Tuple[Pilot2Criterion, ...]
    playback_log_path: str = ""
    selected_device_name: str = ""
    metrics: Mapping[str, object] = field(default_factory=dict)
    generated_at_utc: str = ""
    schema_version: int = PILOT2_SCHEMA_VERSION
    pilot_id: str = "m8_pilot2_audio_calibration_only"

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
            "calibration_path": self.calibration_path,
            "playback_log_path": self.playback_log_path,
            "selected_device_name": self.selected_device_name,
            "criteria": [criterion.to_dict() for criterion in self.criteria],
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


def validate_pilot2_calibration(
    calibration_path: Path,
    *,
    device_name: Optional[str] = None,
    playback_log_path: Optional[Path] = None,
    hard_max_volume: float = DEFAULT_PILOT2_HARD_MAX_VOLUME,
) -> Pilot2ValidationReport:
    if hard_max_volume < 0:
        raise ValueError("hard_max_volume must be non-negative")

    calibration_path = calibration_path.expanduser()
    playback_log_path = playback_log_path.expanduser() if playback_log_path is not None else None
    criteria = [
        Pilot2Criterion(
            name="calibration_file_exists",
            passed=calibration_path.exists(),
            observed=str(calibration_path),
            target="volume calibration JSON exists",
        )
    ]
    if not calibration_path.exists():
        return Pilot2ValidationReport(
            calibration_path=str(calibration_path),
            playback_log_path=str(playback_log_path or ""),
            criteria=tuple(criteria),
        )

    try:
        store = load_volume_calibrations(calibration_path)
        calibration = store.latest_for_device(device_name) if device_name else store.latest()
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        criteria.append(
            Pilot2Criterion(
                name="calibration_parseable",
                passed=False,
                observed=str(exc),
                target="valid calibration store with selected device",
            )
        )
        return Pilot2ValidationReport(
            calibration_path=str(calibration_path),
            playback_log_path=str(playback_log_path or ""),
            selected_device_name=device_name or "",
            criteria=tuple(criteria),
        )

    criteria.extend(_calibration_criteria(calibration, hard_max_volume))
    playback_event = _latest_playback_event(playback_log_path, calibration.device_name)
    criteria.extend(_playback_criteria(playback_event, playback_log_path, calibration))
    metrics = {
        "device_name": calibration.device_name,
        "detectable_volume": calibration.detectable_volume,
        "identifiable_volume": calibration.identifiable_volume,
        "comfortable_volume": calibration.comfortable_volume,
        "scheduler_max_volume": calibration.scheduler_max_volume,
        "hard_max_volume": hard_max_volume,
        "calibrated_at_utc": calibration.calibrated_at_utc,
        "cap_probe": dict(playback_event or {}),
    }
    return Pilot2ValidationReport(
        calibration_path=str(calibration_path),
        playback_log_path=str(playback_log_path or ""),
        selected_device_name=calibration.device_name,
        criteria=tuple(criteria),
        metrics=metrics,
    )


def _calibration_criteria(
    calibration: VolumeCalibration,
    hard_max_volume: float,
) -> Tuple[Pilot2Criterion, ...]:
    scheduler_max = calibration.scheduler_max_volume
    return (
        Pilot2Criterion(
            name="calibration_parseable",
            passed=True,
            observed=calibration.device_name,
            target="valid calibration store with selected device",
        ),
        Pilot2Criterion(
            name="comfort_thresholds_ordered",
            passed=(
                calibration.detectable_volume
                <= calibration.identifiable_volume
                <= calibration.comfortable_volume
            ),
            observed={
                "detectable_volume": calibration.detectable_volume,
                "identifiable_volume": calibration.identifiable_volume,
                "comfortable_volume": calibration.comfortable_volume,
            },
            target="detectable <= identifiable <= comfortable",
        ),
        Pilot2Criterion(
            name="scheduler_max_matches_comfortable",
            passed=scheduler_max == calibration.comfortable_volume,
            observed=scheduler_max,
            target="scheduler_max_volume equals comfortable_volume",
        ),
        Pilot2Criterion(
            name="scheduler_max_within_hard_cap",
            passed=scheduler_max <= hard_max_volume,
            observed=scheduler_max,
            target=f"<= {hard_max_volume}",
        ),
    )


def _playback_criteria(
    event: Optional[Mapping[str, object]],
    playback_log_path: Optional[Path],
    calibration: VolumeCalibration,
) -> Tuple[Pilot2Criterion, ...]:
    log_path = str(playback_log_path or "")
    scheduler_max = calibration.scheduler_max_volume
    if event is None:
        return (
            Pilot2Criterion(
                name="cap_probe_log_present",
                passed=False,
                observed=log_path,
                target="dry-run play-test-cue JSONL log exists for the selected device",
            ),
        )

    requested_volume = _float(event.get("requested_volume"))
    effective_volume = _float(event.get("effective_volume"))
    max_volume = _float(event.get("max_volume"))
    return (
        Pilot2Criterion(
            name="cap_probe_log_present",
            passed=True,
            observed=log_path,
            target="dry-run play-test-cue JSONL log exists for the selected device",
        ),
        Pilot2Criterion(
            name="cap_probe_device_matches",
            passed=str(event.get("device_name", "")) == calibration.device_name,
            observed=str(event.get("device_name", "")),
            target=calibration.device_name,
        ),
        Pilot2Criterion(
            name="cap_probe_backend_is_non_sleep",
            passed=str(event.get("backend_name", "")) in {"dry-run", "mock"},
            observed=str(event.get("backend_name", "")),
            target="dry-run or mock",
        ),
        Pilot2Criterion(
            name="cap_probe_requested_above_scheduler_max",
            passed=requested_volume > scheduler_max,
            observed=requested_volume,
            target=f"> {scheduler_max}",
        ),
        Pilot2Criterion(
            name="cap_probe_effective_volume_capped",
            passed=effective_volume <= scheduler_max and bool(event.get("volume_capped")) is True,
            observed={
                "effective_volume": effective_volume,
                "volume_capped": bool(event.get("volume_capped")),
            },
            target=f"effective_volume <= {scheduler_max} and volume_capped is true",
        ),
        Pilot2Criterion(
            name="cap_probe_max_volume_uses_calibration",
            passed=max_volume <= scheduler_max,
            observed=max_volume,
            target=f"<= {scheduler_max}",
        ),
    )


def _latest_playback_event(
    playback_log_path: Optional[Path],
    device_name: str,
) -> Optional[Mapping[str, object]]:
    if playback_log_path is None or not playback_log_path.exists():
        return None
    events = []
    for line in playback_log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    matching = [
        event
        for event in events
        if str(event.get("device_name", "")) == device_name
    ]
    return (matching or events or [None])[-1]


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()
