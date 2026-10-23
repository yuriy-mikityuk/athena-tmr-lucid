"""Pilot 3 replay-only cue plan simulation."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

from muse_tmr.audio import CueLibrary
from muse_tmr.data.replay import ReplayConfig, ReplaySession
from muse_tmr.features import (
    EpochBuilder,
    EpochConfig,
    SleepEpoch,
    extract_eeg_features,
    extract_imu_features,
    extract_ppg_features,
)
from muse_tmr.models import (
    HeuristicRemDetector,
    RemGateConfig,
    RemGateDecision,
    RemPrediction,
    StableRemGate,
)
from muse_tmr.protocol import PuzzleCatalog, PuzzleCueAssignment
from muse_tmr.protocol.arousal_guard import (
    ArousalGuard,
    ArousalGuardConfig,
    ArousalGuardDecision,
)
from muse_tmr.protocol.puzzle_protocol import NightPuzzleSession
from muse_tmr.protocol.tmr_scheduler import (
    TmrCueScheduler,
    TmrSchedulerConfig,
    TmrSchedulerEvent,
)

PILOT3_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Pilot3Criterion:
    name: str
    passed: bool
    observed: object
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
class Pilot3EpochResult:
    index: int
    timestamp_seconds: float
    duration_seconds: float
    prediction: RemPrediction
    gate_decision: RemGateDecision
    arousal_guard_decision: ArousalGuardDecision
    scheduler_events: Tuple[TmrSchedulerEvent, ...]

    def to_dict(self) -> Dict[str, object]:
        return {
            "index": self.index,
            "timestamp_seconds": self.timestamp_seconds,
            "duration_seconds": self.duration_seconds,
            "prediction": self.prediction.to_dict(),
            "gate_decision": self.gate_decision.to_dict(),
            "arousal_guard_decision": self.arousal_guard_decision.to_dict(),
            "scheduler_events": [event.to_dict() for event in self.scheduler_events],
        }


@dataclass(frozen=True)
class Pilot3ReplayCueSimulationReport:
    recording_input: str
    session_id: str
    criteria: Tuple[Pilot3Criterion, ...]
    epoch_results: Tuple[Pilot3EpochResult, ...]
    scheduler_events: Tuple[TmrSchedulerEvent, ...]
    metrics: Mapping[str, object] = field(default_factory=dict)
    audio_backend: str = "mock"
    audio_playback_executed: bool = False
    generated_at_utc: str = ""
    schema_version: int = PILOT3_SCHEMA_VERSION
    pilot_id: str = "m8_pilot3_replay_cue_simulation"

    def __post_init__(self) -> None:
        object.__setattr__(self, "criteria", tuple(self.criteria))
        object.__setattr__(self, "epoch_results", tuple(self.epoch_results))
        object.__setattr__(self, "scheduler_events", tuple(self.scheduler_events))
        if not self.generated_at_utc:
            object.__setattr__(self, "generated_at_utc", _utc_now())

    @property
    def passed(self) -> bool:
        return all(criterion.passed for criterion in self.criteria)

    @property
    def failed_criteria(self) -> Tuple[str, ...]:
        return tuple(criterion.name for criterion in self.criteria if not criterion.passed)

    @property
    def cue_plan(self) -> Tuple[TmrSchedulerEvent, ...]:
        return tuple(event for event in self.scheduler_events if event.event_type == "play")

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "pilot_id": self.pilot_id,
            "generated_at_utc": self.generated_at_utc,
            "passed": self.passed,
            "failed_criteria": list(self.failed_criteria),
            "recording_input": self.recording_input,
            "session_id": self.session_id,
            "audio_backend": self.audio_backend,
            "audio_playback_executed": self.audio_playback_executed,
            "criteria": [criterion.to_dict() for criterion in self.criteria],
            "metrics": dict(self.metrics),
            "cue_plan": [event.to_dict() for event in self.cue_plan],
            "scheduler_events": [event.to_dict() for event in self.scheduler_events],
            "epochs": [result.to_dict() for result in self.epoch_results],
        }

    def save(self, output_path: Path) -> Path:
        output_path = output_path.expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return output_path

    def save_scheduler_events(self, output_path: Path) -> Path:
        output_path = output_path.expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(event.to_dict(), sort_keys=True) for event in self.scheduler_events]
        output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return output_path


async def simulate_replay_cue_plan(
    input_path: Path,
    *,
    catalog: PuzzleCatalog,
    session: NightPuzzleSession,
    assignment: PuzzleCueAssignment,
    cue_library: CueLibrary,
    start_seconds: Optional[float] = None,
    end_seconds: Optional[float] = None,
    epoch_config: Optional[EpochConfig] = None,
    gate_config: Optional[RemGateConfig] = None,
    scheduler_config: Optional[TmrSchedulerConfig] = None,
    arousal_guard_config: Optional[ArousalGuardConfig] = None,
) -> Pilot3ReplayCueSimulationReport:
    replay = ReplaySession(
        ReplayConfig(
            input_path=input_path,
            speed=0.0,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        )
    )
    await replay.connect()
    try:
        builder = EpochBuilder(epoch_config or EpochConfig())
        epochs = [epoch async for epoch in builder.build(replay.stream())]
    finally:
        await replay.stop()

    return simulate_cue_plan_from_epochs(
        epochs,
        catalog=catalog,
        session=session,
        assignment=assignment,
        cue_library=cue_library,
        recording_input=str(replay.recording_dir),
        gate_config=gate_config,
        scheduler_config=scheduler_config,
        arousal_guard_config=arousal_guard_config,
    )


def simulate_cue_plan_from_epochs(
    epochs: Sequence[SleepEpoch],
    *,
    catalog: PuzzleCatalog,
    session: NightPuzzleSession,
    assignment: PuzzleCueAssignment,
    cue_library: CueLibrary,
    recording_input: str = "",
    detector: Optional[HeuristicRemDetector] = None,
    gate_config: Optional[RemGateConfig] = None,
    scheduler_config: Optional[TmrSchedulerConfig] = None,
    arousal_guard_config: Optional[ArousalGuardConfig] = None,
) -> Pilot3ReplayCueSimulationReport:
    assignment.validate_against_session(session)
    _validate_scheduled_cues(catalog, assignment, cue_library)

    detector = detector or HeuristicRemDetector()
    gate = StableRemGate(gate_config or RemGateConfig())
    arousal_guard = ArousalGuard(
        arousal_guard_config
        or ArousalGuardConfig(optics_capable=gate.config.optics_capable)
    )
    scheduler = TmrCueScheduler(
        assignment=assignment,
        catalog=catalog,
        cue_library=cue_library,
        config=scheduler_config or TmrSchedulerConfig(enable_tlr_block=False),
    )

    first_start_time = epochs[0].start_time if epochs else 0.0
    epoch_results = []
    scheduler_events = []

    for epoch in epochs:
        timestamp_seconds = max(0.0, epoch.start_time - first_start_time)
        eeg = extract_eeg_features(epoch)
        imu = extract_imu_features(epoch)
        ppg = extract_ppg_features(epoch)
        prediction = detector.predict_features(eeg=eeg, imu=imu, ppg=ppg)
        gate_decision = gate.update(prediction, duration_seconds=epoch.duration_seconds)
        guard_decision = arousal_guard.evaluate(
            timestamp_seconds=timestamp_seconds,
            eeg=eeg,
            imu=imu,
            ppg=ppg,
        )
        events = scheduler.update(
            gate_decision,
            timestamp_seconds=timestamp_seconds,
            guard_decision=guard_decision,
        )
        scheduler_events.extend(events)
        epoch_results.append(
            Pilot3EpochResult(
                index=epoch.index,
                timestamp_seconds=timestamp_seconds,
                duration_seconds=epoch.duration_seconds,
                prediction=prediction,
                gate_decision=gate_decision,
                arousal_guard_decision=guard_decision,
                scheduler_events=events,
            )
        )

    scheduler_events_tuple = tuple(scheduler_events)
    metrics = _build_metrics(
        epochs=epochs,
        epoch_results=tuple(epoch_results),
        scheduler_events=scheduler_events_tuple,
        assignment=assignment,
    )
    criteria = _build_criteria(metrics, audio_playback_executed=False)
    return Pilot3ReplayCueSimulationReport(
        recording_input=recording_input,
        session_id=session.session_id,
        criteria=criteria,
        epoch_results=tuple(epoch_results),
        scheduler_events=scheduler_events_tuple,
        metrics=metrics,
        audio_backend="mock",
        audio_playback_executed=False,
    )


def _validate_scheduled_cues(
    catalog: PuzzleCatalog,
    assignment: PuzzleCueAssignment,
    cue_library: CueLibrary,
) -> None:
    for puzzle_id in assignment.scheduled_puzzle_ids:
        assignment.ensure_schedulable(puzzle_id)
        cue_library.by_id(catalog.get_puzzle(puzzle_id).cue_id)


def _build_metrics(
    *,
    epochs: Sequence[SleepEpoch],
    epoch_results: Tuple[Pilot3EpochResult, ...],
    scheduler_events: Tuple[TmrSchedulerEvent, ...],
    assignment: PuzzleCueAssignment,
) -> Mapping[str, object]:
    event_type_counts: Dict[str, int] = {}
    play_by_puzzle: Dict[str, int] = {}
    for event in scheduler_events:
        event_type_counts[event.event_type] = event_type_counts.get(event.event_type, 0) + 1
        if event.event_type == "play" and event.puzzle_id is not None:
            play_by_puzzle[event.puzzle_id] = play_by_puzzle.get(event.puzzle_id, 0) + 1

    uncued_plays = {
        puzzle_id: count
        for puzzle_id, count in play_by_puzzle.items()
        if assignment.is_uncued(puzzle_id)
    }
    gate_open_count = sum(1 for result in epoch_results if result.gate_decision.gate_open)
    cue_plan = tuple(event for event in scheduler_events if event.event_type == "play")
    return {
        "epoch_count": len(epochs),
        "gate_open_count": gate_open_count,
        "event_type_counts": event_type_counts,
        "scheduler_event_count": len(scheduler_events),
        "cue_plan_count": len(cue_plan),
        "play_by_puzzle": play_by_puzzle,
        "cued_puzzle_ids": list(assignment.cued_puzzle_ids),
        "uncued_puzzle_ids": list(assignment.uncued_puzzle_ids),
        "uncued_puzzle_play_count": sum(uncued_plays.values()),
        "uncued_puzzle_plays": uncued_plays,
    }


def _build_criteria(
    metrics: Mapping[str, object],
    *,
    audio_playback_executed: bool,
) -> Tuple[Pilot3Criterion, ...]:
    return (
        Pilot3Criterion(
            name="epochs_present",
            passed=int(metrics.get("epoch_count", 0)) > 0,
            observed=metrics.get("epoch_count", 0),
            target="> 0 replay epochs",
        ),
        Pilot3Criterion(
            name="audio_backend_mocked",
            passed=not audio_playback_executed,
            observed=audio_playback_executed,
            target="audio_playback_executed is false",
        ),
        Pilot3Criterion(
            name="no_uncued_puzzle_cues",
            passed=int(metrics.get("uncued_puzzle_play_count", 0)) == 0,
            observed=metrics.get("uncued_puzzle_plays", {}),
            target="scheduler play events only target cued puzzles",
        ),
        Pilot3Criterion(
            name="scheduler_events_generated",
            passed=int(metrics.get("scheduler_event_count", 0)) > 0,
            observed=metrics.get("scheduler_event_count", 0),
            target="inspectable scheduler event stream",
        ),
    )


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()
