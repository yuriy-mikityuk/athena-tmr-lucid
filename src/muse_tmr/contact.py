"""Contact quality contracts and mock scenarios for local Muse setup."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Mapping, Sequence, Tuple

CONTACT_STATUSES = ("missing", "poor", "fair", "good")
REQUIRED_CONTACT_CHANNELS = ("TP9", "AF7", "AF8", "TP10")


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


__all__ = [
    "CONTACT_STATUSES",
    "REQUIRED_CONTACT_CHANNELS",
    "ChannelContactState",
    "ContactQualitySnapshot",
    "MockContactProvider",
    "available_mock_contact_scenarios",
    "builtin_contact_snapshots",
    "load_contact_snapshots_jsonl",
]
