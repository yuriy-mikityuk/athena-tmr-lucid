"""Sleep epoch construction from MuseFrame streams."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import AsyncIterable, AsyncIterator, Deque, Dict, Mapping, Optional, Tuple

from muse_tmr.data.sample_types import MuseFrame

DEFAULT_SAMPLE_RATES = {
    "eeg": 256.0,
    "imu": 52.0,
    "ppg": 64.0,
    "heart_rate": 1.0,
}


@dataclass(frozen=True)
class EpochConfig:
    epoch_seconds: float = 30.0
    stride_seconds: float = 30.0
    min_coverage: float = 0.5
    emit_partial: bool = True
    expected_sample_rates: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_SAMPLE_RATES)
    )

    def validate(self) -> None:
        if self.epoch_seconds <= 0:
            raise ValueError("epoch_seconds must be positive")
        if self.stride_seconds <= 0:
            raise ValueError("stride_seconds must be positive")
        if not 0 <= self.min_coverage <= 1:
            raise ValueError("min_coverage must be between 0 and 1")
        for modality, sample_rate in self.expected_sample_rates.items():
            if sample_rate <= 0:
                raise ValueError(f"sample rate for {modality} must be positive")


@dataclass(frozen=True)
class SleepEpoch:
    index: int
    start_time: float
    end_time: float
    frames: Tuple[MuseFrame, ...]
    modality_counts: Mapping[str, int]
    sample_counts: Mapping[str, int]
    coverage: Mapping[str, float]
    quality_flags: Tuple[str, ...]

    @property
    def duration_seconds(self) -> float:
        return self.end_time - self.start_time

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def to_dict(self, include_frames: bool = False) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "index": self.index,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "frame_count": self.frame_count,
            "modality_counts": dict(self.modality_counts),
            "sample_counts": dict(self.sample_counts),
            "coverage": dict(self.coverage),
            "quality_flags": list(self.quality_flags),
        }
        if include_frames:
            payload["frames"] = [frame.to_dict(include_raw=False) for frame in self.frames]
        return payload


class EpochBuilder:
    """Build fixed-duration sleep epochs from a live or replay MuseFrame stream."""

    def __init__(self, config: Optional[EpochConfig] = None) -> None:
        self.config = config or EpochConfig()
        self.config.validate()

    async def build(self, frames: AsyncIterable[MuseFrame]) -> AsyncIterator[SleepEpoch]:
        window_frames: Deque[MuseFrame] = deque()
        epoch_start: Optional[float] = None
        epoch_index = 0

        async for frame in frames:
            if epoch_start is None:
                epoch_start = frame.timestamp

            while frame.timestamp >= epoch_start + self.config.epoch_seconds:
                yield self._build_epoch(epoch_index, epoch_start, tuple(window_frames))
                epoch_index += 1
                epoch_start += self.config.stride_seconds
                _drop_frames_before(window_frames, epoch_start)

            window_frames.append(frame)

        if self.config.emit_partial and epoch_start is not None and window_frames:
            yield self._build_epoch(epoch_index, epoch_start, tuple(window_frames))

    def _build_epoch(
        self,
        index: int,
        start_time: float,
        candidate_frames: Tuple[MuseFrame, ...],
    ) -> SleepEpoch:
        end_time = start_time + self.config.epoch_seconds
        frames = tuple(
            frame for frame in candidate_frames
            if start_time <= frame.timestamp < end_time
        )
        modality_counts = _modality_counts(frames)
        sample_counts = _sample_counts(frames)
        coverage = _coverage(
            sample_counts=sample_counts,
            expected_sample_rates=self.config.expected_sample_rates,
            epoch_seconds=self.config.epoch_seconds,
        )
        quality_flags = _quality_flags(
            coverage=coverage,
            min_coverage=self.config.min_coverage,
        )

        return SleepEpoch(
            index=index,
            start_time=start_time,
            end_time=end_time,
            frames=frames,
            modality_counts=modality_counts,
            sample_counts=sample_counts,
            coverage=coverage,
            quality_flags=quality_flags,
        )


def epoch_step_seconds(
    start_time: float,
    previous_start_time: Optional[float],
    stride_seconds: float,
) -> float:
    """Real time from the previous epoch's start to this one's; one stride for the first.

    A consumer that keeps time per epoch, such as the REM gate's stable window and
    cooldown, moves on by this much. With overlapping epochs (a stride shorter than the
    epoch) that is the stride, not the epoch length. The difference is rounded to the
    microsecond, so float error in the epoch starts cannot turn a 30 s step into
    29.9999999 s and leave a 60 s window one epoch short.
    """
    if previous_start_time is None:
        if stride_seconds <= 0:
            raise ValueError("stride_seconds must be positive")
        return float(stride_seconds)
    elapsed = round(start_time - previous_start_time, 6)
    if elapsed <= 0:
        raise ValueError("epoch start times must increase")
    return elapsed


def _drop_frames_before(frames: Deque[MuseFrame], timestamp: float) -> None:
    while frames and frames[0].timestamp < timestamp:
        frames.popleft()


def _modality_counts(frames: Tuple[MuseFrame, ...]) -> Mapping[str, int]:
    counts: Dict[str, int] = {}
    for frame in frames:
        for modality in frame.modalities():
            counts[modality] = counts.get(modality, 0) + 1
    return counts


def _sample_counts(frames: Tuple[MuseFrame, ...]) -> Mapping[str, int]:
    counts: Dict[str, int] = {}
    for frame in frames:
        frame_counts = _frame_sample_counts(frame)
        for modality, count in frame_counts.items():
            counts[modality] = counts.get(modality, 0) + count
    return counts


def _frame_sample_counts(frame: MuseFrame) -> Mapping[str, int]:
    counts: Dict[str, int] = {}
    if frame.eeg is not None:
        counts["eeg"] = _max_series_len(frame.eeg.channels_uv)
    if frame.imu is not None:
        counts["imu"] = max(
            len(frame.imu.accelerometer_g or ()),
            len(frame.imu.gyroscope_dps or ()),
        )
    if frame.ppg is not None:
        counts["ppg"] = _max_series_len(frame.ppg.channels)
    if frame.heart_rate is not None:
        counts["heart_rate"] = 1
    if frame.battery is not None:
        counts["battery"] = 1
    return counts


def _max_series_len(series_by_channel: Mapping[str, Tuple[float, ...]]) -> int:
    if not series_by_channel:
        return 0
    return max(len(series) for series in series_by_channel.values())


def _coverage(
    sample_counts: Mapping[str, int],
    expected_sample_rates: Mapping[str, float],
    epoch_seconds: float,
) -> Mapping[str, float]:
    coverage = {}
    for modality, sample_rate in expected_sample_rates.items():
        expected = sample_rate * epoch_seconds
        observed = sample_counts.get(modality, 0)
        coverage[modality] = min(1.0, observed / expected)
    return coverage


def _quality_flags(coverage: Mapping[str, float], min_coverage: float) -> Tuple[str, ...]:
    flags = []
    for modality, value in sorted(coverage.items()):
        if value == 0:
            flags.append(f"missing_{modality}")
        elif value < min_coverage:
            flags.append(f"low_{modality}_coverage")
    return tuple(flags)
