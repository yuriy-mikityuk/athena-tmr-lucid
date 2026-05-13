"""Pilot 4 low-volume REM-gated cueing workflow."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Dict, Iterable, Mapping, Optional, Tuple

from muse_raw_stream import MuseRawStream

from muse_tmr.audio import (
    AudioBackend,
    AudioCuePlayer,
    AudioPlaybackConfig,
    CueLibrary,
    CuePlaybackResult,
    TestCue,
    VolumeCalibration,
    audio_config_with_calibration,
    create_audio_backend,
)
from muse_tmr.data.sample_types import MuseFrame
from muse_tmr.features import (
    EpochBuilder,
    EpochConfig,
    extract_eeg_features,
    extract_imu_features,
    extract_ppg_features,
)
from muse_tmr.models import HeuristicRemDetector, RemGateConfig, StableRemGate
from muse_tmr.protocol import PuzzleCatalog, PuzzleCueAssignment
from muse_tmr.protocol.arousal_guard import ArousalGuard, ArousalGuardConfig
from muse_tmr.protocol.puzzle_protocol import NightPuzzleSession
from muse_tmr.protocol.tmr_scheduler import (
    TmrCueScheduler,
    TmrSchedulerConfig,
    TmrSchedulerEvent,
)
from muse_tmr.sources.base_source import BaseMuseSource, MuseSourceMetadata

PILOT4_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Pilot4Criterion:
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
class Pilot4CueingConfig:
    output_dir: Path
    duration_seconds: float
    source_name: str = "amused"
    allow_short: bool = False
    no_data_timeout_seconds: float = 30.0
    hard_max_volume: float = 0.20
    default_volume: float = 0.02
    fade_in_seconds: float = 0.25
    fade_out_seconds: float = 0.25
    audio_backend_name: str = "dry-run"
    emergency_stop_path: Optional[Path] = None
    epoch_config: EpochConfig = field(default_factory=EpochConfig)
    gate_config: RemGateConfig = field(default_factory=RemGateConfig)
    scheduler_config: TmrSchedulerConfig = field(
        default_factory=lambda: TmrSchedulerConfig(enable_tlr_block=False)
    )
    arousal_guard_config: ArousalGuardConfig = field(default_factory=ArousalGuardConfig)

    def validate(self) -> None:
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if not self.allow_short and not 7200 <= self.duration_seconds <= 28800:
            raise ValueError("pilot4 cueing nights must be between 2 and 8 hours")
        if self.no_data_timeout_seconds <= 0:
            raise ValueError("no_data_timeout_seconds must be positive")
        if not 0.0 <= self.hard_max_volume <= 1.0:
            raise ValueError("hard_max_volume must be between 0.0 and 1.0")
        if not 0.0 <= self.default_volume <= 1.0:
            raise ValueError("default_volume must be between 0.0 and 1.0")


@dataclass(frozen=True)
class Pilot4CueingSummary:
    output_dir: str
    raw_path: str
    metadata_path: str
    recording_events_path: str
    scheduler_events_path: str
    arousal_guard_events_path: str
    audio_log_path: str
    awakening_events_path: str
    summary_path: str
    emergency_stop_path: str
    started_at: str
    ended_at: str
    duration_seconds: float
    stop_reason: str
    criteria: Tuple[Pilot4Criterion, ...]
    frame_count: int = 0
    raw_packet_count: int = 0
    epoch_count: int = 0
    modality_counts: Mapping[str, int] = field(default_factory=dict)
    scheduler_event_type_counts: Mapping[str, int] = field(default_factory=dict)
    audio_status_counts: Mapping[str, int] = field(default_factory=dict)
    cue_play_count: int = 0
    uncued_puzzle_play_count: int = 0
    max_requested_volume: float = 0.0
    max_effective_volume: float = 0.0
    calibration_device_name: str = ""
    calibration_scheduler_max_volume: float = 0.0
    hard_max_volume: float = 0.20
    audio_backend_name: str = "unknown"
    emergency_stop_triggered: bool = False
    generated_at_utc: str = ""
    schema_version: int = PILOT4_SCHEMA_VERSION
    pilot_id: str = "m8_pilot4_low_volume_rem_gated_cueing"

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
            "output_dir": self.output_dir,
            "raw_path": self.raw_path,
            "metadata_path": self.metadata_path,
            "recording_events_path": self.recording_events_path,
            "scheduler_events_path": self.scheduler_events_path,
            "arousal_guard_events_path": self.arousal_guard_events_path,
            "audio_log_path": self.audio_log_path,
            "awakening_events_path": self.awakening_events_path,
            "summary_path": self.summary_path,
            "emergency_stop_path": self.emergency_stop_path,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "stop_reason": self.stop_reason,
            "criteria": [criterion.to_dict() for criterion in self.criteria],
            "frame_count": self.frame_count,
            "raw_packet_count": self.raw_packet_count,
            "epoch_count": self.epoch_count,
            "modality_counts": dict(self.modality_counts),
            "scheduler_event_type_counts": dict(self.scheduler_event_type_counts),
            "audio_status_counts": dict(self.audio_status_counts),
            "cue_play_count": self.cue_play_count,
            "uncued_puzzle_play_count": self.uncued_puzzle_play_count,
            "max_requested_volume": self.max_requested_volume,
            "max_effective_volume": self.max_effective_volume,
            "calibration_device_name": self.calibration_device_name,
            "calibration_scheduler_max_volume": self.calibration_scheduler_max_volume,
            "hard_max_volume": self.hard_max_volume,
            "audio_backend_name": self.audio_backend_name,
            "emergency_stop_triggered": self.emergency_stop_triggered,
        }

    def save(self, output_path: Path) -> Path:
        output_path = output_path.expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return output_path


@dataclass
class _Pilot4State:
    frame_count: int = 0
    raw_packet_count: int = 0
    epoch_count: int = 0
    modality_counts: Dict[str, int] = field(default_factory=dict)
    playback_results: list = field(default_factory=list)
    stop_reason: str = "duration_complete"
    emergency_stop_triggered: bool = False
    first_epoch_start: Optional[float] = None


@dataclass(frozen=True)
class AwakeningEvent:
    event_type: str = "awakening"
    timestamp_utc: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp_utc:
            object.__setattr__(self, "timestamp_utc", _utc_now())
        if not self.event_type.strip():
            raise ValueError("event_type must not be empty")

    def to_dict(self) -> Dict[str, object]:
        return {
            "event_type": self.event_type,
            "timestamp_utc": self.timestamp_utc,
            "notes": self.notes,
        }


async def run_pilot4_cueing_night(
    source: BaseMuseSource,
    *,
    config: Pilot4CueingConfig,
    catalog: PuzzleCatalog,
    session: NightPuzzleSession,
    assignment: PuzzleCueAssignment,
    cue_library: CueLibrary,
    calibration: VolumeCalibration,
    backend: Optional[AudioBackend] = None,
) -> Pilot4CueingSummary:
    config.validate()
    assignment.validate_against_session(session)
    _validate_pilot4_cues(catalog, assignment, cue_library)

    output_dir = config.output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw_amused.bin"
    metadata_path = output_dir / "metadata.json"
    recording_events_path = output_dir / "events.jsonl"
    scheduler_events_path = output_dir / "scheduler_events.jsonl"
    arousal_guard_events_path = output_dir / "arousal_guard_events.jsonl"
    audio_log_path = output_dir / "audio_playback.jsonl"
    awakening_events_path = output_dir / "awakening_events.jsonl"
    summary_path = output_dir / "pilot4_summary.json"
    emergency_stop_path = (
        config.emergency_stop_path.expanduser()
        if config.emergency_stop_path is not None
        else output_dir / "EMERGENCY_STOP"
    )
    scheduler_events_path.touch(exist_ok=True)
    arousal_guard_events_path.touch(exist_ok=True)
    audio_log_path.touch(exist_ok=True)
    awakening_events_path.touch(exist_ok=True)

    state = _Pilot4State()
    started_at_dt = dt.datetime.now(dt.timezone.utc)
    started_monotonic = time.monotonic()
    deadline = started_monotonic + config.duration_seconds
    metadata = await source.connect()
    _write_metadata(metadata_path, metadata, config, calibration, started_at_dt)
    _append_jsonl(
        recording_events_path,
        {
            "event": "pilot4_started",
            "timestamp_utc": started_at_dt.isoformat(),
            "source": metadata.source_name,
            "emergency_stop_path": str(emergency_stop_path),
        },
    )

    audio_config = audio_config_with_calibration(
        AudioPlaybackConfig(
            max_volume=config.hard_max_volume,
            default_volume=config.default_volume,
            fade_in_seconds=config.fade_in_seconds,
            fade_out_seconds=config.fade_out_seconds,
            device_name=calibration.device_name,
            log_path=audio_log_path,
        ),
        calibration,
    )
    player = AudioCuePlayer(
        audio_config,
        backend=backend or create_audio_backend(config.audio_backend_name),
    )
    detector = HeuristicRemDetector()
    gate = StableRemGate(config.gate_config)
    arousal_guard = ArousalGuard(
        config.arousal_guard_config,
        event_log_path=arousal_guard_events_path,
    )
    scheduler = TmrCueScheduler(
        assignment=assignment,
        catalog=catalog,
        cue_library=cue_library,
        config=config.scheduler_config,
        event_log_path=scheduler_events_path,
    )
    raw_stream = MuseRawStream(str(raw_path))
    raw_stream.open_write()

    try:
        frame_stream = _recording_frame_stream(
            source=source,
            raw_stream=raw_stream,
            state=state,
            deadline=deadline,
            no_data_timeout_seconds=config.no_data_timeout_seconds,
        )
        builder = EpochBuilder(config.epoch_config)
        async for epoch in builder.build(frame_stream):
            state.epoch_count += 1
            if state.first_epoch_start is None:
                state.first_epoch_start = epoch.start_time
            _maybe_trigger_emergency_stop(player, state, emergency_stop_path, recording_events_path)
            timestamp_seconds = max(0.0, epoch.start_time - state.first_epoch_start)
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
            for event in events:
                if event.event_type == "play":
                    result = _play_scheduler_event(event, cue_library, player)
                    state.playback_results.append(result)
                    _append_jsonl(
                        recording_events_path,
                        {
                            "event": "audio_playback_result",
                            "timestamp_seconds": event.timestamp_seconds,
                            "scheduler_event": event.to_dict(),
                            "playback_result": result.to_dict(),
                        },
                    )
                _maybe_trigger_emergency_stop(player, state, emergency_stop_path, recording_events_path)
    finally:
        raw_stream.close()
        await source.stop()

    ended_at_dt = dt.datetime.now(dt.timezone.utc)
    _append_jsonl(
        recording_events_path,
        {
            "event": "pilot4_stopped",
            "timestamp_utc": ended_at_dt.isoformat(),
            "reason": state.stop_reason,
        },
    )

    summary = _build_summary(
        config=config,
        output_dir=output_dir,
        raw_path=raw_path,
        metadata_path=metadata_path,
        recording_events_path=recording_events_path,
        scheduler_events_path=scheduler_events_path,
        arousal_guard_events_path=arousal_guard_events_path,
        audio_log_path=audio_log_path,
        awakening_events_path=awakening_events_path,
        summary_path=summary_path,
        emergency_stop_path=emergency_stop_path,
        started_at=started_at_dt,
        ended_at=ended_at_dt,
        state=state,
        scheduler_events=scheduler.events,
        calibration=calibration,
        player=player,
        assignment=assignment,
    )
    summary.save(summary_path)
    return summary


def append_awakening_event(output_path: Path, event: AwakeningEvent) -> Path:
    _append_jsonl(output_path, event.to_dict())
    return output_path.expanduser()


async def _recording_frame_stream(
    *,
    source: BaseMuseSource,
    raw_stream: MuseRawStream,
    state: _Pilot4State,
    deadline: float,
    no_data_timeout_seconds: float,
) -> AsyncIterator[MuseFrame]:
    stream = source.stream().__aiter__()
    while time.monotonic() < deadline:
        timeout = min(no_data_timeout_seconds, max(0.01, deadline - time.monotonic()))
        try:
            frame = await asyncio.wait_for(stream.__anext__(), timeout=timeout)
        except asyncio.TimeoutError:
            state.stop_reason = "no_data_timeout"
            break
        except StopAsyncIteration:
            state.stop_reason = "source_ended"
            break

        state.frame_count += 1
        for modality in frame.modalities():
            state.modality_counts[modality] = state.modality_counts.get(modality, 0) + 1
        if frame.raw_packet:
            packet_timestamp = dt.datetime.fromtimestamp(frame.timestamp)
            if packet_timestamp < raw_stream.session_start:
                packet_timestamp = raw_stream.session_start
            raw_stream.write_packet(frame.raw_packet, packet_timestamp)
            state.raw_packet_count += 1
        yield frame


def _play_scheduler_event(
    event: TmrSchedulerEvent,
    cue_library: CueLibrary,
    player: AudioCuePlayer,
) -> CuePlaybackResult:
    if event.cue_id is None:
        raise ValueError("scheduler play event is missing cue_id")
    cue = cue_library.by_id(event.cue_id)
    if cue.frequency_hz is None:
        raise ValueError(f"pilot4 cue must include frequency_hz: {cue.cue_id}")
    requested_volume = float(event.metadata.get("volume_hint", cue.volume_hint or player.config.default_volume))
    return player.play_test_cue(
        TestCue(
            cue_id=cue.cue_id,
            frequency_hz=cue.frequency_hz,
            duration_seconds=cue.duration_seconds,
        ),
        volume=requested_volume,
    )


def _maybe_trigger_emergency_stop(
    player: AudioCuePlayer,
    state: _Pilot4State,
    emergency_stop_path: Path,
    recording_events_path: Path,
) -> None:
    if state.emergency_stop_triggered or not emergency_stop_path.exists():
        return
    result = player.emergency_stop()
    state.emergency_stop_triggered = True
    _append_jsonl(
        recording_events_path,
        {
            "event": "emergency_stop_triggered",
            "timestamp_utc": _utc_now(),
            "emergency_stop_path": str(emergency_stop_path),
            "playback_result": result.to_dict(),
        },
    )


def _build_summary(
    *,
    config: Pilot4CueingConfig,
    output_dir: Path,
    raw_path: Path,
    metadata_path: Path,
    recording_events_path: Path,
    scheduler_events_path: Path,
    arousal_guard_events_path: Path,
    audio_log_path: Path,
    awakening_events_path: Path,
    summary_path: Path,
    emergency_stop_path: Path,
    started_at: dt.datetime,
    ended_at: dt.datetime,
    state: _Pilot4State,
    scheduler_events: Tuple[TmrSchedulerEvent, ...],
    calibration: VolumeCalibration,
    player: AudioCuePlayer,
    assignment: PuzzleCueAssignment,
) -> Pilot4CueingSummary:
    scheduler_event_type_counts = _event_type_counts(scheduler_events)
    audio_status_counts = _audio_status_counts(state.playback_results)
    cue_play_count = scheduler_event_type_counts.get("play", 0)
    uncued_puzzle_play_count = sum(
        1
        for event in scheduler_events
        if event.event_type == "play"
        and event.puzzle_id is not None
        and assignment.is_uncued(event.puzzle_id)
    )
    max_requested_volume = max(
        (result.requested_volume for result in state.playback_results),
        default=0.0,
    )
    max_effective_volume = max(
        (result.effective_volume for result in state.playback_results),
        default=0.0,
    )
    criteria = _build_criteria(
        epoch_count=state.epoch_count,
        scheduler_events=scheduler_events,
        cue_play_count=cue_play_count,
        uncued_puzzle_play_count=uncued_puzzle_play_count,
        max_effective_volume=max_effective_volume,
        calibration=calibration,
        hard_max_volume=config.hard_max_volume,
        arousal_guard_events_path=arousal_guard_events_path,
        emergency_stop_path=emergency_stop_path,
    )
    return Pilot4CueingSummary(
        output_dir=str(output_dir),
        raw_path=str(raw_path),
        metadata_path=str(metadata_path),
        recording_events_path=str(recording_events_path),
        scheduler_events_path=str(scheduler_events_path),
        arousal_guard_events_path=str(arousal_guard_events_path),
        audio_log_path=str(audio_log_path),
        awakening_events_path=str(awakening_events_path),
        summary_path=str(summary_path),
        emergency_stop_path=str(emergency_stop_path),
        started_at=started_at.isoformat(),
        ended_at=ended_at.isoformat(),
        duration_seconds=(ended_at - started_at).total_seconds(),
        stop_reason=state.stop_reason,
        criteria=criteria,
        frame_count=state.frame_count,
        raw_packet_count=state.raw_packet_count,
        epoch_count=state.epoch_count,
        modality_counts=state.modality_counts,
        scheduler_event_type_counts=scheduler_event_type_counts,
        audio_status_counts=audio_status_counts,
        cue_play_count=cue_play_count,
        uncued_puzzle_play_count=uncued_puzzle_play_count,
        max_requested_volume=max_requested_volume,
        max_effective_volume=max_effective_volume,
        calibration_device_name=calibration.device_name,
        calibration_scheduler_max_volume=calibration.scheduler_max_volume,
        hard_max_volume=config.hard_max_volume,
        audio_backend_name=player.backend.name,
        emergency_stop_triggered=state.emergency_stop_triggered,
    )


def _build_criteria(
    *,
    epoch_count: int,
    scheduler_events: Tuple[TmrSchedulerEvent, ...],
    cue_play_count: int,
    uncued_puzzle_play_count: int,
    max_effective_volume: float,
    calibration: VolumeCalibration,
    hard_max_volume: float,
    arousal_guard_events_path: Path,
    emergency_stop_path: Path,
) -> Tuple[Pilot4Criterion, ...]:
    scheduler_plays = tuple(event for event in scheduler_events if event.event_type == "play")
    stable_rem_plays = all("rem_gate_open" in event.reason_codes for event in scheduler_plays)
    return (
        Pilot4Criterion(
            name="epochs_present",
            passed=epoch_count > 0,
            observed=epoch_count,
            target="> 0 live epochs",
        ),
        Pilot4Criterion(
            name="scheduler_events_generated",
            passed=bool(scheduler_events),
            observed=len(scheduler_events),
            target="inspectable scheduler event stream",
        ),
        Pilot4Criterion(
            name="cues_only_after_stable_rem",
            passed=stable_rem_plays,
            observed=cue_play_count,
            target="every scheduler play event includes rem_gate_open",
        ),
        Pilot4Criterion(
            name="no_uncued_puzzle_cues",
            passed=uncued_puzzle_play_count == 0,
            observed=uncued_puzzle_play_count,
            target="zero uncued puzzle play events",
        ),
        Pilot4Criterion(
            name="volume_within_calibration_cap",
            passed=max_effective_volume <= min(calibration.scheduler_max_volume, hard_max_volume),
            observed=max_effective_volume,
            target=f"<= min(calibration={calibration.scheduler_max_volume}, hard_cap={hard_max_volume})",
        ),
        Pilot4Criterion(
            name="arousal_guard_events_logged",
            passed=arousal_guard_events_path.exists(),
            observed=str(arousal_guard_events_path),
            target="arousal guard JSONL exists",
        ),
        Pilot4Criterion(
            name="emergency_stop_available",
            passed=bool(str(emergency_stop_path)),
            observed=str(emergency_stop_path),
            target="operator can create this file to block future playback",
        ),
    )


def _validate_pilot4_cues(
    catalog: PuzzleCatalog,
    assignment: PuzzleCueAssignment,
    cue_library: CueLibrary,
) -> None:
    for puzzle_id in assignment.scheduled_puzzle_ids:
        cue = cue_library.by_id(catalog.get_puzzle(puzzle_id).cue_id)
        if cue.cue_type != "generated_tone":
            raise ValueError(f"pilot4 supports generated_tone cues only: {cue.cue_id}")
        if cue.frequency_hz is None:
            raise ValueError(f"pilot4 generated cue must include frequency_hz: {cue.cue_id}")


def _write_metadata(
    metadata_path: Path,
    metadata: MuseSourceMetadata,
    config: Pilot4CueingConfig,
    calibration: VolumeCalibration,
    started_at: dt.datetime,
) -> None:
    payload = {
        "started_at": started_at.isoformat(),
        "pilot_id": "m8_pilot4_low_volume_rem_gated_cueing",
        "source": {
            "source_name": metadata.source_name,
            "device_name": metadata.device_name,
            "device_id": metadata.device_id,
            "capabilities": dict(metadata.capabilities),
            "metadata": dict(metadata.metadata or {}),
        },
        "audio": {
            "backend_name": config.audio_backend_name,
            "hard_max_volume": config.hard_max_volume,
            "default_volume": config.default_volume,
            "calibration": calibration.to_dict(),
        },
    }
    metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(output_path: Path, payload: Mapping[str, object]) -> None:
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), sort_keys=True) + "\n")


def _event_type_counts(events: Iterable[TmrSchedulerEvent]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for event in events:
        counts[event.event_type] = counts.get(event.event_type, 0) + 1
    return counts


def _audio_status_counts(results: Iterable[CuePlaybackResult]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()
