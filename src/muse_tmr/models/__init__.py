"""REM detection models."""

from muse_tmr.models.heuristic_rem_detector import HeuristicRemConfig, HeuristicRemDetector
from muse_tmr.models.rem_detector import RemPrediction

__all__ = [
    "HeuristicRemConfig",
    "HeuristicRemDetector",
    "RemPrediction",
]
