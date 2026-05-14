"""Contact quality contracts and mock scenarios for local Muse setup."""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Deque, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from muse_tmr.data.sample_types import MuseFrame

CONTACT_STATUSES = ("missing", "poor", "fair", "good")
REQUIRED_CONTACT_CHANNELS = ("TP9", "AF7", "AF8", "TP10")


@dataclass(frozen=True)
class ContactQualityConfig:
    window_seconds: float = 2.0
    sample_rate_hz: float = 256.0
    stale_timeout_seconds: float = 3.0
    fair_fill_threshold: float = 0.35
    good_fill_threshold: float = 0.80
    clipping_abs_uv_threshold: float = 500.0
    clipping_fraction_threshold: float = 0.05
    flat_std_uv_threshold: float = 1e-6

    def validate(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if self.stale_timeout_seconds <= 0:
            raise ValueError("stale_timeout_seconds must be positive")
        if not 0 <= self.fair_fill_threshold <= self.good_fill_threshold <= 1:
            raise ValueError("fill thresholds must satisfy 0 <= fair <= good <= 1")
        if self.clipping_abs_uv_threshold <= 0:
            raise ValueError("clipping_abs_uv_threshold must be positive")
        if not 0 < self.clipping_fraction_threshold <= 1:
            raise ValueError("clipping_fraction_threshold must be inside (0, 1]")
        if self.flat_std_uv_threshold < 0:
            raise ValueError("flat_std_uv_threshold must be non-negative")


@dataclass(frozen=True)
class ContactGateConfig:
    required_stability_seconds: float = 5.0

    def validate(self) -> None:
        if self.required_stability_seconds < 0:
            raise ValueError("required_stability_seconds must be non-negative")


@dataclass(frozen=True)
class ChannelContactState:
    channel: str
    status: str
    fill: float
    coverage: float
    sample_count: int
    reason_codes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        status = str(self.status)
        if status not in CONTACT_STATUSES:
            raise ValueError(f"invalid contact status: {status}")

        fill = float(self.fill)
        coverage = float(self.coverage)
        sample_count = int(self.sample_count)
        if not 0.0 <= fill <= 1.0:
            raise ValueError("fill must be between 0.0 and 1.0")
        if not 0.0 <= coverage <= 1.0:
            raise ValueError("coverage must be between 0.0 and 1.0")
        if sample_count < 0:
            raise ValueError("sample_count must be non-negative")

        object.__setattr__(self, "channel", str(self.channel))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "fill", fill)
        object.__setattr__(self, "coverage", coverage)
        object.__setattr__(self, "sample_count", sample_count)
        object.__setattr__(
            self,
            "reason_codes",
            tuple(str(code) for code in self.reason_codes),
        )

    @property
    def is_good(self) -> bool:
        return self.status == "good"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "status": self.status,
            "fill": self.fill,
            "coverage": self.coverage,
            "sample_count": self.sample_count,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChannelContactState":
        return cls(
            channel=str(data["channel"]),
            status=str(data["status"]),
            fill=float(data.get("fill", 0.0)),
            coverage=float(data.get("coverage", 0.0)),
            sample_count=int(data.get("sample_count", 0)),
            reason_codes=tuple(data.get("reason_codes", ())),
        )


@dataclass(frozen=True)
class ContactQualitySnapshot:
    source: str
    connection_state: str
    sequence: int
    timestamp_seconds: float
    stale: bool
    required_channels: Tuple[str, ...] = field(default_factory=lambda: REQUIRED_CONTACT_CHANNELS)
    channels: Mapping[str, ChannelContactState] = field(default_factory=dict)
    all_good: bool = False

    def __post_init__(self) -> None:
        required_channels = tuple(str(channel) for channel in self.required_channels)
        normalized_channels = {
            str(channel): (
                state
                if isinstance(state, ChannelContactState)
                else ChannelContactState.from_dict(state)
            )
            for channel, state in self.channels.items()
        }

        object.__setattr__(self, "source", str(self.source))
        object.__setattr__(self, "connection_state", str(self.connection_state))
        object.__setattr__(self, "sequence", int(self.sequence))
        object.__setattr__(self, "timestamp_seconds", float(self.timestamp_seconds))
        object.__setattr__(self, "stale", bool(self.stale))
        object.__setattr__(self, "required_channels", required_channels)
        object.__setattr__(self, "channels", normalized_channels)
        object.__setattr__(self, "all_good", self._compute_all_good())

    def _compute_all_good(self) -> bool:
        if self.stale or self.connection_state != "connected":
            return False
        return all(
            self.channels.get(channel, _missing_channel(channel)).is_good
            for channel in self.required_channels
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "connection_state": self.connection_state,
            "sequence": self.sequence,
            "timestamp_seconds": self.timestamp_seconds,
            "stale": self.stale,
            "required_channels": list(self.required_channels),
            "channels": {
                channel: state.to_dict()
                for channel, state in sorted(self.channels.items())
            },
            "all_good": self.all_good,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContactQualitySnapshot":
        channels = data.get("channels", {})
        if not isinstance(channels, Mapping):
            raise ValueError("channels must be a mapping")
        return cls(
            source=str(data.get("source", "unknown")),
            connection_state=str(data.get("connection_state", "disconnected")),
            sequence=int(data.get("sequence", 0)),
            timestamp_seconds=float(data.get("timestamp_seconds", 0.0)),
            stale=bool(data.get("stale", False)),
            required_channels=tuple(data.get("required_channels", REQUIRED_CONTACT_CHANNELS)),
            channels={
                str(channel): (
                    state
                    if isinstance(state, ChannelContactState)
                    else ChannelContactState.from_dict(state)
                )
                for channel, state in channels.items()
            },
            all_good=bool(data.get("all_good", False)),
        )


class ContactQualityMonitor:
    """Rolling-window EEG contact quality monitor for setup flows."""

    def __init__(
        self,
        source: str,
        config: Optional[ContactQualityConfig] = None,
        required_channels: Sequence[str] = REQUIRED_CONTACT_CHANNELS,
    ) -> None:
        self.source = source
        self.config = config or ContactQualityConfig()
        self.config.validate()
        self.required_channels = tuple(required_channels)
        self._frames: Deque[MuseFrame] = deque()
        self._last_frame_timestamp: Optional[float] = None
        self._sequence = 0

    def update(self, frame: MuseFrame) -> ContactQualitySnapshot:
        self._last_frame_timestamp = float(frame.timestamp)
        if frame.eeg is not None:
            self._frames.append(frame)
            self._prune(frame.timestamp)
        self._sequence += 1
        return self.snapshot(now_seconds=frame.timestamp)

    def snapshot(
        self,
        now_seconds: Optional[float] = None,
        connection_state: str = "connected",
    ) -> ContactQualitySnapshot:
        now = float(time.time() if now_seconds is None else now_seconds)
        self._prune(now)
        stale = (
            self._last_frame_timestamp is not None
            and now - self._last_frame_timestamp > self.config.stale_timeout_seconds
        )
        channels = {
            channel: self._channel_state(channel)
            for channel in self.required_channels
        }
        return ContactQualitySnapshot(
            source=self.source,
            connection_state=connection_state,
            sequence=self._sequence,
            timestamp_seconds=now,
            stale=stale,
            required_channels=self.required_channels,
            channels=channels,
        )

    def _prune(self, now_seconds: float) -> None:
        cutoff = float(now_seconds) - self.config.window_seconds
        while self._frames and self._frames[0].timestamp < cutoff:
            self._frames.popleft()

    def _channel_state(self, channel: str) -> ChannelContactState:
        values = tuple(_channel_values(self._frames, channel))
        sample_count = len(values)
        if sample_count == 0:
            return _state(channel, "missing", 0.0, 0.0, 0, ("no_recent_samples",))

        expected_count = max(1, int(self.config.window_seconds * self.config.sample_rate_hz))
        coverage = min(1.0, sample_count / expected_count)
        finite_values = tuple(value for value in values if math.isfinite(value))
        finite_fraction = len(finite_values) / sample_count
        centered_values = _centered_values(finite_values)
        clipping_fraction = _clipping_fraction(centered_values, self.config.clipping_abs_uv_threshold)
        fill = max(0.0, min(1.0, coverage * finite_fraction * (1.0 - clipping_fraction)))

        reasons = []
        hard_artifact = False
        if finite_fraction < 1.0:
            hard_artifact = True
            reasons.append("non_finite")
        if centered_values and _std(centered_values) <= self.config.flat_std_uv_threshold:
            hard_artifact = True
            reasons.append("flatline")
        if clipping_fraction >= self.config.clipping_fraction_threshold:
            hard_artifact = True
            reasons.append("clipping")
        if coverage < self.config.good_fill_threshold:
            reasons.append("low_coverage")
        if fill < self.config.fair_fill_threshold:
            reasons.append("low_fill")

        if hard_artifact or fill < self.config.fair_fill_threshold:
            status = "poor"
        elif fill < self.config.good_fill_threshold or reasons:
            status = "fair"
        else:
            status = "good"

        return _state(channel, status, fill, coverage, sample_count, tuple(sorted(set(reasons))))


@dataclass(frozen=True)
class ContactGateState:
    state: str
    all_good: bool
    stable_for_seconds: float
    required_stability_seconds: float
    armed: bool
    ready: bool
    reason_codes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", str(self.state))
        object.__setattr__(self, "all_good", bool(self.all_good))
        object.__setattr__(self, "stable_for_seconds", max(0.0, float(self.stable_for_seconds)))
        object.__setattr__(
            self,
            "required_stability_seconds",
            max(0.0, float(self.required_stability_seconds)),
        )
        object.__setattr__(self, "armed", bool(self.armed))
        object.__setattr__(self, "ready", bool(self.ready))
        object.__setattr__(self, "reason_codes", tuple(str(code) for code in self.reason_codes))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "all_good": self.all_good,
            "stable_for_seconds": self.stable_for_seconds,
            "required_stability_seconds": self.required_stability_seconds,
            "armed": self.armed,
            "ready": self.ready,
            "reason_codes": list(self.reason_codes),
        }


class ContactGate:
    """Backend-enforced pre-session contact gate."""

    def __init__(
        self,
        config: Optional[ContactGateConfig] = None,
        time_fn=time.time,
    ) -> None:
        self.config = config or ContactGateConfig()
        self.config.validate()
        self.time_fn = time_fn
        self.armed = False
        self.ready = False
        self.running = False
        self._stable_since: Optional[float] = None
        self._last_state = ContactGateState(
            state="disconnected",
            all_good=False,
            stable_for_seconds=0.0,
            required_stability_seconds=self.config.required_stability_seconds,
            armed=False,
            ready=False,
            reason_codes=("not_connected",),
        )

    def arm(
        self,
        snapshot: ContactQualitySnapshot,
        now_seconds: Optional[float] = None,
    ) -> ContactGateState:
        self.armed = True
        self.ready = False
        self.running = False
        self._stable_since = None
        return self.update(snapshot, now_seconds=now_seconds)

    def disarm(self) -> ContactGateState:
        self.armed = False
        self.ready = False
        self.running = False
        self._stable_since = None
        self._last_state = ContactGateState(
            state="connected_contact_check",
            all_good=False,
            stable_for_seconds=0.0,
            required_stability_seconds=self.config.required_stability_seconds,
            armed=False,
            ready=False,
            reason_codes=("gate_disarmed",),
        )
        return self._last_state

    def update(
        self,
        snapshot: ContactQualitySnapshot,
        now_seconds: Optional[float] = None,
    ) -> ContactGateState:
        now = float(self.time_fn() if now_seconds is None else now_seconds)
        all_good = snapshot.all_good
        reasons = _gate_reasons(snapshot)

        if self.running:
            state_reasons = tuple(reasons + (("in_session_contact_warning",) if reasons else ()))
            self._last_state = ContactGateState(
                state="running",
                all_good=all_good,
                stable_for_seconds=self._stable_for(now),
                required_stability_seconds=self.config.required_stability_seconds,
                armed=True,
                ready=True,
                reason_codes=state_reasons,
            )
            return self._last_state

        if not self.armed:
            state = "connected_contact_check" if snapshot.connection_state == "connected" else snapshot.connection_state
            self._stable_since = now if all_good else None
            self._last_state = ContactGateState(
                state=state,
                all_good=all_good,
                stable_for_seconds=self._stable_for(now) if all_good else 0.0,
                required_stability_seconds=self.config.required_stability_seconds,
                armed=False,
                ready=False,
                reason_codes=tuple(reasons or ["gate_disarmed"]),
            )
            return self._last_state

        if not all_good:
            self.ready = False
            self._stable_since = None
            self._last_state = ContactGateState(
                state="armed_waiting_contact",
                all_good=False,
                stable_for_seconds=0.0,
                required_stability_seconds=self.config.required_stability_seconds,
                armed=True,
                ready=False,
                reason_codes=tuple(reasons or ["contact_not_good"]),
            )
            return self._last_state

        if self._stable_since is None:
            self._stable_since = now
        stable_for = self._stable_for(now)
        self.ready = stable_for >= self.config.required_stability_seconds
        self._last_state = ContactGateState(
            state="ready" if self.ready else "ready_countdown",
            all_good=True,
            stable_for_seconds=stable_for,
            required_stability_seconds=self.config.required_stability_seconds,
            armed=True,
            ready=self.ready,
            reason_codes=() if self.ready else ("stability_window_pending",),
        )
        return self._last_state

    def start(
        self,
        snapshot: ContactQualitySnapshot,
        now_seconds: Optional[float] = None,
    ) -> ContactGateState:
        state = self.update(snapshot, now_seconds=now_seconds)
        if not state.ready:
            self._last_state = ContactGateState(
                state="blocked_contact",
                all_good=state.all_good,
                stable_for_seconds=state.stable_for_seconds,
                required_stability_seconds=state.required_stability_seconds,
                armed=state.armed,
                ready=False,
                reason_codes=tuple(sorted(set(state.reason_codes + ("contact_gate_not_ready",)))),
            )
            return self._last_state
        self.running = True
        self._last_state = ContactGateState(
            state="starting",
            all_good=state.all_good,
            stable_for_seconds=state.stable_for_seconds,
            required_stability_seconds=state.required_stability_seconds,
            armed=True,
            ready=True,
            reason_codes=(),
        )
        return self._last_state

    def state(self) -> ContactGateState:
        return self._last_state

    def _stable_for(self, now_seconds: float) -> float:
        if self._stable_since is None:
            return 0.0
        return max(0.0, now_seconds - self._stable_since)


class MockContactProvider:
    """Deterministic contact snapshots for UI and gate development."""

    def __init__(
        self,
        snapshots: Sequence[ContactQualitySnapshot],
        interval_seconds: float = 1.0,
        loop: bool = False,
    ) -> None:
        if not snapshots:
            raise ValueError("mock contact provider requires at least one snapshot")
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be non-negative")
        self.snapshots = tuple(snapshots)
        self.interval_seconds = float(interval_seconds)
        self.loop = bool(loop)
        self._index = 0
        self._stop_requested = False

    @classmethod
    def for_scenario(
        cls,
        name: str,
        interval_seconds: float = 1.0,
        loop: bool = False,
    ) -> "MockContactProvider":
        return cls(
            builtin_contact_snapshots(name),
            interval_seconds=interval_seconds,
            loop=loop,
        )

    @classmethod
    def from_jsonl(
        cls,
        path: Path,
        interval_seconds: float = 1.0,
        loop: bool = False,
    ) -> "MockContactProvider":
        return cls(
            load_contact_snapshots_jsonl(path),
            interval_seconds=interval_seconds,
            loop=loop,
        )

    def reset(self) -> None:
        self._index = 0
        self._stop_requested = False

    def next_snapshot(self) -> ContactQualitySnapshot:
        if self._index >= len(self.snapshots):
            if self.loop:
                self._index = 0
            else:
                return self.snapshots[-1]

        snapshot = self.snapshots[self._index]
        self._index += 1
        return snapshot

    async def stream(self) -> AsyncIterator[ContactQualitySnapshot]:
        self._stop_requested = False
        while not self._stop_requested:
            yield self.next_snapshot()
            if self.interval_seconds > 0:
                await asyncio.sleep(self.interval_seconds)

    async def stop(self) -> None:
        self._stop_requested = True


def load_contact_snapshots_jsonl(path: Path) -> Tuple[ContactQualitySnapshot, ...]:
    snapshots = []
    with path.expanduser().open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number} of {path}") from exc
            snapshots.append(ContactQualitySnapshot.from_dict(payload))
    if not snapshots:
        raise ValueError(f"contact fixture is empty: {path}")
    return tuple(snapshots)


def builtin_contact_snapshots(name: str) -> Tuple[ContactQualitySnapshot, ...]:
    scenario = _normalize_scenario_name(name)
    if scenario == "all_missing":
        return (_snapshot(0, _all_missing_channels()),)
    if scenario == "one_channel_poor":
        return (_snapshot(0, _one_channel_poor_channels()),)
    if scenario == "mixed_fair_good":
        return (_snapshot(0, _mixed_fair_good_channels()),)
    if scenario == "all_good":
        return (_snapshot(0, _all_good_channels()),)
    if scenario == "flapping_af7":
        return (
            _snapshot(0, _all_good_channels()),
            _snapshot(1, _af7_poor_channels()),
            _snapshot(2, _all_good_channels()),
        )
    if scenario == "disconnect_after_good":
        return (
            _snapshot(0, _all_good_channels()),
            _snapshot(
                1,
                _disconnected_channels(),
                connection_state="disconnected",
            ),
        )
    if scenario == "stale_data":
        return (
            _snapshot(0, _all_good_channels()),
            _snapshot(1, _stale_channels(), stale=True),
        )
    raise ValueError(f"unknown mock contact scenario: {name}")


def available_mock_contact_scenarios() -> Tuple[str, ...]:
    return (
        "all_missing",
        "one_channel_poor",
        "mixed_fair_good",
        "all_good",
        "flapping_af7",
        "disconnect_after_good",
        "stale_data",
    )


def _normalize_scenario_name(name: str) -> str:
    return str(name).strip().lower().replace("-", "_").replace(" ", "_")


def _snapshot(
    sequence: int,
    channels: Mapping[str, ChannelContactState],
    connection_state: str = "connected",
    stale: bool = False,
) -> ContactQualitySnapshot:
    return ContactQualitySnapshot(
        source="mock",
        connection_state=connection_state,
        sequence=sequence,
        timestamp_seconds=float(sequence),
        stale=stale,
        required_channels=REQUIRED_CONTACT_CHANNELS,
        channels=channels,
    )


def _state(
    channel: str,
    status: str,
    fill: float,
    coverage: float,
    sample_count: int,
    reason_codes: Tuple[str, ...] = (),
) -> ChannelContactState:
    return ChannelContactState(
        channel=channel,
        status=status,
        fill=fill,
        coverage=coverage,
        sample_count=sample_count,
        reason_codes=reason_codes,
    )


def _missing_channel(channel: str) -> ChannelContactState:
    return _state(channel, "missing", 0.0, 0.0, 0, ("no_recent_samples",))


def _all_missing_channels() -> Mapping[str, ChannelContactState]:
    return {channel: _missing_channel(channel) for channel in REQUIRED_CONTACT_CHANNELS}


def _all_good_channels() -> Mapping[str, ChannelContactState]:
    return {
        "TP9": _state("TP9", "good", 0.96, 0.98, 256, ()),
        "AF7": _state("AF7", "good", 0.94, 0.96, 256, ()),
        "AF8": _state("AF8", "good", 0.95, 0.97, 256, ()),
        "TP10": _state("TP10", "good", 0.93, 0.95, 256, ()),
    }


def _one_channel_poor_channels() -> Mapping[str, ChannelContactState]:
    channels = dict(_all_good_channels())
    channels["TP10"] = _state("TP10", "poor", 0.18, 0.91, 256, ("hard_artifact", "clipping"))
    return channels


def _mixed_fair_good_channels() -> Mapping[str, ChannelContactState]:
    channels = dict(_all_good_channels())
    channels["AF7"] = _state("AF7", "fair", 0.58, 0.64, 192, ("low_coverage",))
    channels["TP10"] = _state("TP10", "fair", 0.73, 0.84, 224, ("mild_noise",))
    return channels


def _af7_poor_channels() -> Mapping[str, ChannelContactState]:
    channels = dict(_all_good_channels())
    channels["AF7"] = _state("AF7", "poor", 0.22, 0.42, 128, ("low_coverage", "flatline"))
    return channels


def _disconnected_channels() -> Mapping[str, ChannelContactState]:
    return {
        channel: _state(channel, "missing", 0.0, 0.0, 0, ("source_disconnected",))
        for channel in REQUIRED_CONTACT_CHANNELS
    }


def _stale_channels() -> Mapping[str, ChannelContactState]:
    return {
        channel: _state(channel, "poor", 0.0, 0.0, 0, ("stale_snapshot",))
        for channel in REQUIRED_CONTACT_CHANNELS
    }


def _channel_values(frames: Iterable[MuseFrame], channel: str) -> Iterable[float]:
    for frame in frames:
        if frame.eeg is None:
            continue
        for value in frame.eeg.channels_uv.get(channel, ()):
            yield float(value)


def _std(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def _centered_values(values: Sequence[float]) -> Tuple[float, ...]:
    if not values:
        return ()
    baseline = sorted(values)[len(values) // 2]
    return tuple(value - baseline for value in values)


def _clipping_fraction(values: Sequence[float], threshold: float) -> float:
    if not values:
        return 1.0
    clipped = sum(1 for value in values if abs(value) >= threshold)
    return clipped / len(values)


def _gate_reasons(snapshot: ContactQualitySnapshot) -> Tuple[str, ...]:
    reasons = []
    if snapshot.connection_state == "disconnected":
        reasons.append("disconnected")
    elif snapshot.connection_state != "connected":
        reasons.append(snapshot.connection_state)
    if snapshot.stale:
        reasons.append("stale_contact")
    for channel in snapshot.required_channels:
        state = snapshot.channels.get(channel, _missing_channel(channel))
        if state.status != "good":
            reasons.append(f"{channel.lower()}_{state.status}")
    return tuple(sorted(set(reasons)))


__all__ = [
    "CONTACT_STATUSES",
    "REQUIRED_CONTACT_CHANNELS",
    "ChannelContactState",
    "ContactGate",
    "ContactGateConfig",
    "ContactGateState",
    "ContactQualityConfig",
    "ContactQualityMonitor",
    "ContactQualitySnapshot",
    "MockContactProvider",
    "available_mock_contact_scenarios",
    "builtin_contact_snapshots",
    "load_contact_snapshots_jsonl",
]
