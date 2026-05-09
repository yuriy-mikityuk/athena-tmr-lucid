"""REM detector contracts."""

from dataclasses import dataclass, field
from typing import Dict, Mapping, Tuple


@dataclass(frozen=True)
class RemPrediction:
    probability: float
    reason_codes: Tuple[str, ...] = ()
    feature_scores: Mapping[str, float] = field(default_factory=dict)
    feature_values: Mapping[str, float] = field(default_factory=dict)
    source: str = "unknown"

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("probability must be between 0.0 and 1.0")

    def to_dict(self) -> Dict[str, object]:
        return {
            "probability": self.probability,
            "reason_codes": list(self.reason_codes),
            "feature_scores": dict(self.feature_scores),
            "feature_values": dict(self.feature_values),
            "source": self.source,
        }
