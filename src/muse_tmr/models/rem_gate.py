"""Stable REM confidence gate."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Tuple

from muse_tmr.models.rem_detector import RemPrediction

DEFAULT_AROUSAL_BLOCK_REASON_CODES = (
    "motion_arousal_proxy",
    "arousal_guard_blocked",
    "cue_related_arousal",
)

DEFAULT_LOW_CONFIDENCE_REASON_CODES = (
    "insufficient_features",
    "limited_feature_support",
    "missing_features_imputed",
    "low_eeg_coverage",
    "low_imu_coverage",
    "low_ppg_hr_coverage",
    "eeg_features_missing",
    "imu_features_missing",
    "ppg_features_missing",
)

# Low-confidence reason codes that stem from a missing cardiac (PPG/HR) signal.
# When the session preset has no optics *by design* (see RemGateConfig.optics_capable)
# these are ignored, so an EEG-only night is not permanently capped below the enter
# threshold. On a preset that does stream optics, a genuine dropout still trips them.
DEFAULT_OPTICS_DEPENDENT_REASON_CODES = (
    "low_ppg_hr_coverage",
    "ppg_features_missing",
)


@dataclass(frozen=True)
class RemGateConfig:
    # Recalibrated against a GSSC reference: the detector runs hot, so the
    # historical 0.70/0.45 over-fired (gate open ~75% of the night). These bare
    # defaults are the conservative optics point; per-preset values (esp. p21)
    # come from muse_tmr.presets.preset_gate_thresholds(). See presets.py.
    enter_threshold: float = 0.80
    exit_threshold: float = 0.70
    min_stable_seconds: float = 60.0
    epoch_seconds: float = 30.0
    cooldown_seconds: float = 120.0
    low_confidence_cap: float = 0.55
    arousal_confidence_cap: float = 0.20
    # Whether the session preset streams optics/PPG at all. When False (an
    # EEG-only preset such as p21), missing-cardiac reason codes do not lower
    # confidence -- otherwise the gate would never open on a deliberately
    # optics-free night. Defaults True to preserve behavior for optics presets.
    optics_capable: bool = True
    arousal_block_reason_codes: Tuple[str, ...] = field(
        default_factory=lambda: DEFAULT_AROUSAL_BLOCK_REASON_CODES
    )
    low_confidence_reason_codes: Tuple[str, ...] = field(
        default_factory=lambda: DEFAULT_LOW_CONFIDENCE_REASON_CODES
    )
    optics_dependent_reason_codes: Tuple[str, ...] = field(
        default_factory=lambda: DEFAULT_OPTICS_DEPENDENT_REASON_CODES
    )

    def validate(self) -> None:
        if not 0.0 <= self.exit_threshold <= self.enter_threshold <= 1.0:
            raise ValueError("thresholds must satisfy 0 <= exit <= enter <= 1")
        if self.min_stable_seconds <= 0:
            raise ValueError("min_stable_seconds must be positive")
        if self.epoch_seconds <= 0:
            raise ValueError("epoch_seconds must be positive")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")
        if not 0.0 <= self.low_confidence_cap <= 1.0:
            raise ValueError("low_confidence_cap must be between 0 and 1")
        if not 0.0 <= self.arousal_confidence_cap <= 1.0:
            raise ValueError("arousal_confidence_cap must be between 0 and 1")


@dataclass(frozen=True)
class RemConfidence:
    probability: float
    confidence: float
    active_threshold: float
    is_rem_like: bool
    source: str
    prediction_reason_codes: Tuple[str, ...] = ()
    reason_codes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, object]:
        return {
            "probability": self.probability,
            "confidence": self.confidence,
            "active_threshold": self.active_threshold,
            "is_rem_like": self.is_rem_like,
            "source": self.source,
            "prediction_reason_codes": list(self.prediction_reason_codes),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class RemGateDecision:
    gate_open: bool
    state: str
    confidence: RemConfidence
    stable_seconds: float
    cooldown_remaining_seconds: float
    reason_codes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, object]:
        return {
            "gate_open": self.gate_open,
            "state": self.state,
            "confidence": self.confidence.to_dict(),
            "stable_seconds": self.stable_seconds,
            "cooldown_remaining_seconds": self.cooldown_remaining_seconds,
            "reason_codes": list(self.reason_codes),
        }


class StableRemGate:
    """Stateful REM gate over detector/classifier probabilities.

    The gate only decides whether REM is stable enough for downstream protocol layers.
    It intentionally does not return cue playback decisions and does not call audio.
    """

    def __init__(self, config: Optional[RemGateConfig] = None) -> None:
        self.config = config or RemGateConfig()
        self.config.validate()
        self._is_open = False
        self._stable_seconds = 0.0
        self._cooldown_remaining_seconds = 0.0

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def stable_seconds(self) -> float:
        return self._stable_seconds

    @property
    def cooldown_remaining_seconds(self) -> float:
        return self._cooldown_remaining_seconds

    def reset(self) -> None:
        self._is_open = False
        self._stable_seconds = 0.0
        self._cooldown_remaining_seconds = 0.0

    def update(
        self,
        prediction: RemPrediction,
        *,
        duration_seconds: Optional[float] = None,
    ) -> RemGateDecision:
        duration = self.config.epoch_seconds if duration_seconds is None else duration_seconds
        if duration <= 0:
            raise ValueError("duration_seconds must be positive")

        if self._cooldown_remaining_seconds > 0:
            self._cooldown_remaining_seconds = max(
                0.0,
                self._cooldown_remaining_seconds - duration,
            )

        active_threshold = self.config.exit_threshold if self._is_open else self.config.enter_threshold
        confidence = build_rem_confidence(
            prediction,
            config=self.config,
            active_threshold=active_threshold,
        )
        block_reasons = list(confidence.reason_codes)

        arousal_blocked = "motion_arousal_block" in confidence.reason_codes
        if arousal_blocked and self.config.cooldown_seconds > 0:
            self._cooldown_remaining_seconds = self.config.cooldown_seconds

        cooldown_active = self._cooldown_remaining_seconds > 0 and not arousal_blocked
        if cooldown_active:
            block_reasons.append("cooldown_active")

        if arousal_blocked or cooldown_active:
            self._is_open = False
            self._stable_seconds = 0.0
            return RemGateDecision(
                gate_open=False,
                state="blocked",
                confidence=confidence,
                stable_seconds=self._stable_seconds,
                cooldown_remaining_seconds=self._cooldown_remaining_seconds,
                reason_codes=_unique(block_reasons),
            )

        if self._is_open:
            return self._update_open_state(confidence, duration, block_reasons)
        return self._update_closed_state(confidence, duration, block_reasons)

    def update_many(
        self,
        predictions: Iterable[RemPrediction],
        *,
        duration_seconds: Optional[float] = None,
    ) -> Tuple[RemGateDecision, ...]:
        return tuple(
            self.update(prediction, duration_seconds=duration_seconds)
            for prediction in predictions
        )

    def _update_open_state(
        self,
        confidence: RemConfidence,
        duration_seconds: float,
        reason_codes: Iterable[str],
    ) -> RemGateDecision:
        reasons = list(reason_codes)
        if confidence.confidence < self.config.exit_threshold:
            self._is_open = False
            self._stable_seconds = 0.0
            reasons.append("below_exit_threshold")
            return RemGateDecision(
                gate_open=False,
                state="closed",
                confidence=confidence,
                stable_seconds=self._stable_seconds,
                cooldown_remaining_seconds=self._cooldown_remaining_seconds,
                reason_codes=_unique(reasons),
            )

        self._stable_seconds += duration_seconds
        if confidence.confidence < self.config.enter_threshold:
            reasons.append("within_hysteresis")
        reasons.append("stable_rem_gate_open")
        return RemGateDecision(
            gate_open=True,
            state="open",
            confidence=confidence,
            stable_seconds=self._stable_seconds,
            cooldown_remaining_seconds=self._cooldown_remaining_seconds,
            reason_codes=_unique(reasons),
        )

    def _update_closed_state(
        self,
        confidence: RemConfidence,
        duration_seconds: float,
        reason_codes: Iterable[str],
    ) -> RemGateDecision:
        reasons = list(reason_codes)
        if not confidence.is_rem_like:
            self._stable_seconds = 0.0
            reasons.append("below_enter_threshold")
            return RemGateDecision(
                gate_open=False,
                state="closed",
                confidence=confidence,
                stable_seconds=self._stable_seconds,
                cooldown_remaining_seconds=self._cooldown_remaining_seconds,
                reason_codes=_unique(reasons),
            )

        self._stable_seconds += duration_seconds
        if self._stable_seconds < self.config.min_stable_seconds:
            reasons.append("stability_window_not_met")
            return RemGateDecision(
                gate_open=False,
                state="warming",
                confidence=confidence,
                stable_seconds=self._stable_seconds,
                cooldown_remaining_seconds=self._cooldown_remaining_seconds,
                reason_codes=_unique(reasons),
            )

        self._is_open = True
        reasons.append("stable_rem_gate_open")
        return RemGateDecision(
            gate_open=True,
            state="open",
            confidence=confidence,
            stable_seconds=self._stable_seconds,
            cooldown_remaining_seconds=self._cooldown_remaining_seconds,
            reason_codes=_unique(reasons),
        )


def build_rem_confidence(
    prediction: RemPrediction,
    *,
    config: Optional[RemGateConfig] = None,
    active_threshold: Optional[float] = None,
) -> RemConfidence:
    config = config or RemGateConfig()
    config.validate()
    threshold = config.enter_threshold if active_threshold is None else active_threshold
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("active_threshold must be between 0 and 1")

    probability = _finite_probability(prediction.probability)
    confidence = probability
    reason_codes = []
    prediction_reasons = tuple(prediction.reason_codes)

    low_confidence_codes = config.low_confidence_reason_codes
    if not config.optics_capable:
        optics_codes = set(config.optics_dependent_reason_codes)
        low_confidence_codes = tuple(
            code for code in low_confidence_codes if code not in optics_codes
        )

    if _has_any_reason(prediction_reasons, low_confidence_codes):
        confidence = min(confidence, config.low_confidence_cap)
        reason_codes.append("low_feature_confidence")

    if _has_arousal_block(prediction_reasons, config.arousal_block_reason_codes):
        confidence = min(confidence, config.arousal_confidence_cap)
        reason_codes.append("motion_arousal_block")

    confidence = _clamp01(confidence)
    return RemConfidence(
        probability=probability,
        confidence=confidence,
        active_threshold=threshold,
        is_rem_like=confidence >= threshold,
        source=prediction.source,
        prediction_reason_codes=prediction_reasons,
        reason_codes=_unique(reason_codes),
    )


def _has_arousal_block(reason_codes: Iterable[str], block_codes: Iterable[str]) -> bool:
    explicit_codes = set(block_codes)
    for reason in reason_codes:
        if reason in explicit_codes or "arousal" in reason:
            return True
    return False


def _has_any_reason(reason_codes: Iterable[str], expected_codes: Iterable[str]) -> bool:
    expected = set(expected_codes)
    return any(reason in expected for reason in reason_codes)


def _finite_probability(probability: float) -> float:
    if not math.isfinite(probability):
        raise ValueError("probability must be finite")
    return _clamp01(probability)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _unique(reason_codes: Iterable[str]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(code for code in reason_codes if code))
