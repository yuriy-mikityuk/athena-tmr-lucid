"""Manual REM annotation rows with feature overlays."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

import pandas as pd

from muse_tmr.features.epochs import SleepEpoch
from muse_tmr.models import HeuristicRemDetector, RemPrediction

REM_LABELS = ("wake", "nrem", "probable_rem", "unknown")
TRAINING_LABELS = tuple(label for label in REM_LABELS if label != "unknown")
REM_LABEL_TO_CODE = {
    "wake": 0,
    "nrem": 1,
    "probable_rem": 2,
    "unknown": -1,
}


@dataclass(frozen=True)
class RemAnnotation:
    recording_id: str
    epoch_index: int
    start_time: float
    end_time: float
    duration_seconds: float
    label: str = "unknown"
    notes: str = ""
    p_rem: float = math.nan
    reason_codes: Tuple[str, ...] = ()
    feature_scores: Mapping[str, float] = field(default_factory=dict)
    feature_values: Mapping[str, float] = field(default_factory=dict)
    prediction_source: str = "unknown"

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", validate_rem_label(self.label))

    @property
    def is_training_label(self) -> bool:
        return self.label in TRAINING_LABELS

    @property
    def label_code(self) -> int:
        return REM_LABEL_TO_CODE[self.label]

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "recording_id": self.recording_id,
            "epoch_index": self.epoch_index,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "label": self.label,
            "label_code": self.label_code,
            "notes": self.notes,
            "p_rem": self.p_rem,
            "reason_codes": ";".join(self.reason_codes),
            "prediction_source": self.prediction_source,
        }
        for name, value in sorted(self.feature_scores.items()):
            payload[f"feature_score_{name}"] = value
        for name, value in sorted(self.feature_values.items()):
            payload[f"feature_value_{name}"] = value
        return payload

    def to_training_dict(self) -> Dict[str, object]:
        payload = self.to_dict()
        payload.pop("notes", None)
        payload.pop("reason_codes", None)
        return payload


def validate_rem_label(label: str) -> str:
    normalized = str(label).strip().lower()
    if normalized not in REM_LABELS:
        raise ValueError(f"label must be one of: {', '.join(REM_LABELS)}")
    return normalized


def build_rem_annotation(
    epoch: SleepEpoch,
    *,
    detector: Optional[HeuristicRemDetector] = None,
    prediction: Optional[RemPrediction] = None,
    recording_id: str = "",
    label: str = "unknown",
    notes: str = "",
) -> RemAnnotation:
    prediction = prediction or (detector or HeuristicRemDetector()).predict_epoch(epoch)
    return RemAnnotation(
        recording_id=recording_id,
        epoch_index=epoch.index,
        start_time=epoch.start_time,
        end_time=epoch.end_time,
        duration_seconds=epoch.duration_seconds,
        label=validate_rem_label(label),
        notes=notes,
        p_rem=prediction.probability,
        reason_codes=prediction.reason_codes,
        feature_scores=prediction.feature_scores,
        feature_values=prediction.feature_values,
        prediction_source=prediction.source,
    )


def build_rem_annotation_rows(
    epochs: Iterable[SleepEpoch],
    *,
    detector: Optional[HeuristicRemDetector] = None,
    recording_id: str = "",
    label: str = "unknown",
) -> Tuple[RemAnnotation, ...]:
    detector = detector or HeuristicRemDetector()
    return tuple(
        build_rem_annotation(
            epoch,
            detector=detector,
            recording_id=recording_id,
            label=label,
        )
        for epoch in epochs
    )


def export_rem_annotations(rows: Sequence[RemAnnotation], output_path: Path) -> Path:
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()

    if suffix == ".csv":
        pd.DataFrame([row.to_dict() for row in rows]).to_csv(output_path, index=False)
    elif suffix == ".json":
        output_path.write_text(
            json.dumps([row.to_dict() for row in rows], indent=2, sort_keys=True),
            encoding="utf-8",
        )
    else:
        raise ValueError("REM annotation export path must end with .csv or .json")
    return output_path


def load_rem_annotations(input_path: Path) -> Tuple[RemAnnotation, ...]:
    input_path = input_path.expanduser()
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(input_path)
        records = frame.to_dict(orient="records")
    elif suffix == ".json":
        records = json.loads(input_path.read_text(encoding="utf-8"))
    else:
        raise ValueError("REM annotation input path must end with .csv or .json")

    return tuple(_annotation_from_record(record) for record in records)


def rem_training_rows(
    rows: Iterable[RemAnnotation],
    *,
    include_unknown: bool = False,
) -> Tuple[Mapping[str, object], ...]:
    training_rows = []
    for row in rows:
        if not include_unknown and row.label == "unknown":
            continue
        training_rows.append(row.to_training_dict())
    return tuple(training_rows)


def _annotation_from_record(record: Mapping[str, object]) -> RemAnnotation:
    feature_scores = _prefixed_values(record, "feature_score_")
    feature_values = _prefixed_values(record, "feature_value_")
    return RemAnnotation(
        recording_id=str(record.get("recording_id", "")),
        epoch_index=int(record["epoch_index"]),
        start_time=float(record["start_time"]),
        end_time=float(record["end_time"]),
        duration_seconds=float(record["duration_seconds"]),
        label=validate_rem_label(str(record.get("label", "unknown"))),
        notes="" if _is_missing(record.get("notes")) else str(record.get("notes", "")),
        p_rem=_float_or_nan(record.get("p_rem")),
        reason_codes=_split_codes(record.get("reason_codes")),
        feature_scores=feature_scores,
        feature_values=feature_values,
        prediction_source=str(record.get("prediction_source", "unknown")),
    )


def _prefixed_values(record: Mapping[str, object], prefix: str) -> Mapping[str, float]:
    values = {}
    for key, value in record.items():
        if not str(key).startswith(prefix):
            continue
        values[str(key)[len(prefix):]] = _float_or_nan(value)
    return values


def _split_codes(value: object) -> Tuple[str, ...]:
    if _is_missing(value):
        return ()
    return tuple(code for code in str(value).split(";") if code)


def _float_or_nan(value: object) -> float:
    if _is_missing(value):
        return math.nan
    return float(value)


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False
