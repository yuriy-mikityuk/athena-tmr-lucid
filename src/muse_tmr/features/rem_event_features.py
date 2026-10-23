"""Causal REM-event detection on the bipolar AF7-AF8 derivation (#225).

Horizontal eye movements reach AF7 and AF8, both referenced near Fpz, with opposite
polarity, so they add up in AF7 - AF8, while blinks and frontal slow waves, which are in
phase on the two sites, mostly cancel there. ``RemEventTracker`` band-passes that
difference to 0.3-5 Hz, keeps a running MAD of it and counts deflections whose peak
clears ``max(mad_k * MAD, floor_uv)`` and whose width at half the peak is 0.3-1.5 s
(supra-threshold stretches less than ``merge_gap_seconds`` apart are one deflection, so
both lobes of a biphasic one count once). An optional common-mode veto drops a
deflection when (AF7 + AF8) / 2 in the same band is larger than the difference, which is
what an asymmetric blink looks like.

The tracker is causal and deterministic: each threshold comes from samples before it,
the filter state is carried between calls, and the result does not depend on how the
stream is cut into epochs. Overlapping epochs (a stride shorter than the epoch) feed each
sample once. Run one tracker per session.

The defaults are starting values, not fitted on any night. The feature is a supporting
term: blinks (wake, N1) and frontal slow waves (N3) share the band, and the reference
near Fpz attenuates horizontal EOG.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

from muse_tmr.features.epochs import SleepEpoch

_FILTER_INIT_SECONDS = 0.5
_WIDTH_FRACTION = 0.5


@dataclass(frozen=True)
class RemEventConfig:
    """Starting values, not fitted on any night; the refit waits for REM-bearing p21
    nights (#225). The band-pass alone takes a 40 µV ~64 Hz line below 0.1 µV, so no
    line removal runs first (tests/test_rem_event_features.py)."""

    sample_rate_hz: float = 256.0
    channels: Tuple[str, str] = ("AF7", "AF8")
    band_hz: Tuple[float, float] = (0.3, 5.0)
    filter_order: int = 4
    mad_k: float = 5.0
    floor_uv: float = 10.0
    mad_window_seconds: float = 300.0
    threshold_update_seconds: float = 1.0
    history_rate_hz: float = 32.0
    min_history_seconds: float = 5.0
    warmup_seconds: float = 60.0
    settle_seconds: float = 2.0
    min_duration_seconds: float = 0.3
    max_duration_seconds: float = 1.5
    merge_gap_seconds: float = 0.5
    gap_seconds: float = 0.5
    common_mode_veto: bool = True
    common_mode_ratio: float = 1.0
    burst_window_seconds: float = 10.0
    burst_min_events: int = 2

    def validate(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        low_hz, high_hz = self.band_hz
        if not 0 < low_hz < high_hz < self.sample_rate_hz / 2:
            raise ValueError("band_hz must be ordered inside (0, Nyquist)")
        if self.filter_order < 1:
            raise ValueError("filter_order must be at least 1")
        if self.mad_k <= 0 or self.floor_uv < 0:
            raise ValueError("mad_k must be positive and floor_uv non-negative")
        if not 0 < self.history_rate_hz <= self.sample_rate_hz:
            raise ValueError("history_rate_hz must be inside (0, sample_rate_hz]")
        if self.threshold_update_seconds <= 0:
            raise ValueError("threshold_update_seconds must be positive")
        if not 0 < self.min_history_seconds <= self.warmup_seconds <= self.mad_window_seconds:
            raise ValueError("need 0 < min_history_seconds <= warmup_seconds <= mad_window_seconds")
        if self.settle_seconds < 0:
            raise ValueError("settle_seconds must be non-negative")
        if not 0 < self.min_duration_seconds < self.max_duration_seconds:
            raise ValueError("event durations must be ordered and positive")
        if self.merge_gap_seconds <= 0 or self.gap_seconds <= 0:
            raise ValueError("merge_gap_seconds and gap_seconds must be positive")
        if self.common_mode_ratio <= 0:
            raise ValueError("common_mode_ratio must be positive")
        if self.burst_window_seconds <= 0 or self.burst_min_events < 1:
            raise ValueError("burst window must be positive and burst_min_events at least 1")


@dataclass(frozen=True)
class RemEvent:
    """One accepted deflection, in the stream's clock (frame timestamps).

    ``time`` is the peak, ``onset_time``/``offset_time`` bound the width at half the
    peak, and ``confirmed_time`` is when the tracker accepted it, a merge gap after its
    last supra-threshold sample; an epoch counts the events confirmed inside it.
    """

    time: float
    onset_time: float
    offset_time: float
    duration_seconds: float
    peak_uv: float
    confirmed_time: float


@dataclass(frozen=True)
class RemEventSummary:
    """What one epoch reports. NaN fields mean AF7 or AF8 was missing or unusable."""

    rem_event_count: float
    rem_density_per_min: float
    last_rem_event_age_s: float
    rem_burst_active: bool
    rem_event_times: Tuple[float, ...]
    rem_event_threshold_uv: float
    rem_event_warmup: bool

    @classmethod
    def missing(cls, *, warmup: bool = True) -> "RemEventSummary":
        return cls(
            rem_event_count=math.nan,
            rem_density_per_min=math.nan,
            last_rem_event_age_s=math.nan,
            rem_burst_active=False,
            rem_event_times=(),
            rem_event_threshold_uv=math.nan,
            rem_event_warmup=warmup,
        )


@dataclass
class _OpenEvent:
    first_supra_index: int
    last_supra_index: int
    peak_abs: float = 0.0
    peak_uv: float = 0.0
    peak_time: float = math.nan
    common_mode_peak: float = 0.0
    buffered_until: int = 0
    magnitudes: List[np.ndarray] = field(default_factory=list)
    times: List[np.ndarray] = field(default_factory=list)
    too_long: bool = False


class RemEventTracker:
    """Stateful, causal REM-event detector for one session."""

    def __init__(self, config: Optional[RemEventConfig] = None) -> None:
        self.config = config or RemEventConfig()
        self.config.validate()
        fs = self.config.sample_rate_hz
        self._sos = butter(
            self.config.filter_order,
            self.config.band_hz,
            btype="bandpass",
            fs=fs,
            output="sos",
        )
        self._zi_unit = sosfilt_zi(self._sos)
        self._settle_samples = int(round(self.config.settle_seconds * fs))
        self._init_samples = max(1, int(round(_FILTER_INIT_SECONDS * fs)))
        self._update_samples = max(1, int(round(self.config.threshold_update_seconds * fs)))
        self._merge_gap_samples = max(1, int(round(self.config.merge_gap_seconds * fs)))
        self._max_event_samples = int(round(4 * self.config.max_duration_seconds * fs))
        self._decimation = max(1, int(round(fs / self.config.history_rate_hz)))
        history_rate = fs / self._decimation
        self._history = np.zeros(max(1, int(round(self.config.mad_window_seconds * history_rate))))
        self._min_history = max(1, int(round(self.config.min_history_seconds * history_rate)))
        self._warmup_history = max(1, int(round(self.config.warmup_seconds * history_rate)))
        self._history_count = 0
        self._history_position = 0
        self._usable_index = 0
        self._threshold: Optional[float] = None
        self._events: List[RemEvent] = []
        self._last_event_time: Optional[float] = None
        self._last_time: Optional[float] = None
        self._consumed_until: Optional[float] = None
        self._reset_segment()

    # -- public API ---------------------------------------------------------

    @property
    def warmup(self) -> bool:
        return self._history_count < self._warmup_history

    @property
    def threshold_uv(self) -> float:
        return math.nan if self._threshold is None else float(self._threshold)

    @property
    def events(self) -> Tuple[RemEvent, ...]:
        return tuple(self._events)

    def update(self, epoch: SleepEpoch) -> RemEventSummary:
        """Feed the epoch's samples not seen before and summarise the epoch."""
        left, right = self.config.channels
        fs = self.config.sample_rate_hz
        left_parts: List[np.ndarray] = []
        right_parts: List[np.ndarray] = []
        time_parts: List[np.ndarray] = []
        for frame in self._new_frames(epoch):
            if frame.eeg is None:
                continue
            left_values = frame.eeg.channels_uv.get(left)
            right_values = frame.eeg.channels_uv.get(right)
            if not left_values or not right_values:
                left_parts.append(np.array([math.nan]))
                right_parts.append(np.array([math.nan]))
                time_parts.append(np.array([frame.timestamp]))
                continue
            count = min(len(left_values), len(right_values))
            left_parts.append(np.asarray(left_values[:count], dtype=float))
            right_parts.append(np.asarray(right_values[:count], dtype=float))
            time_parts.append(frame.timestamp + np.arange(count) / fs)
        self._consumed_until = (
            epoch.end_time
            if self._consumed_until is None
            else max(self._consumed_until, epoch.end_time)
        )
        if left_parts:
            self._feed(
                np.concatenate(left_parts),
                np.concatenate(right_parts),
                np.concatenate(time_parts),
            )
        if self._last_time is None:
            return RemEventSummary.missing(warmup=self.warmup)
        return self._summary(epoch)

    def skip(self, epoch: SleepEpoch) -> RemEventSummary:
        """Mark the epoch's new samples as unusable: a gap for the filter, NaN features."""
        self._consumed_until = (
            epoch.end_time
            if self._consumed_until is None
            else max(self._consumed_until, epoch.end_time)
        )
        self._reset_segment()
        return RemEventSummary.missing(warmup=self.warmup)

    def feed_samples(
        self,
        left_uv: Sequence[float],
        right_uv: Sequence[float],
        times: Sequence[float],
    ) -> Tuple[RemEvent, ...]:
        """Feed raw samples with their times; returns the events confirmed by them."""
        before = len(self._events)
        self._feed(
            np.asarray(left_uv, dtype=float),
            np.asarray(right_uv, dtype=float),
            np.asarray(times, dtype=float),
        )
        return tuple(self._events[before:])

    # -- internals ----------------------------------------------------------

    def _new_frames(self, epoch: SleepEpoch):
        if self._consumed_until is None:
            return epoch.frames
        return tuple(frame for frame in epoch.frames if frame.timestamp >= self._consumed_until)

    def _reset_segment(self) -> None:
        self._zi: Optional[np.ndarray] = None
        self._pending: List[Tuple[np.ndarray, np.ndarray]] = []
        self._settle_remaining = self._settle_samples
        self._open: Optional[_OpenEvent] = None

    def _feed(self, left: np.ndarray, right: np.ndarray, times: np.ndarray) -> None:
        if left.size == 0:
            return
        finite = np.isfinite(left) & np.isfinite(right) & np.isfinite(times)
        breaks = np.zeros(left.size, dtype=bool)
        if self._last_time is not None and finite[0]:
            breaks[0] = abs(times[0] - (self._last_time + 1.0 / self.config.sample_rate_hz)) > self.config.gap_seconds
        if left.size > 1:
            step = np.diff(times) - 1.0 / self.config.sample_rate_hz
            breaks[1:] = np.abs(step) > self.config.gap_seconds
        start = 0
        while start < left.size:
            if not finite[start]:
                self._reset_segment()
                start += 1
                continue
            stop = start + 1
            while stop < left.size and finite[stop] and not breaks[stop]:
                stop += 1
            if breaks[start]:
                self._reset_segment()
            self._consume(left[start:stop], right[start:stop], times[start:stop])
            self._last_time = float(times[stop - 1])
            start = stop

    def _consume(self, left: np.ndarray, right: np.ndarray, times: np.ndarray) -> None:
        stacked = np.vstack([left - right, 0.5 * (left + right)])
        if self._zi is None:
            # Start the filter from the mean of the first half second, not from the first
            # sample: a sample is off by the ~64 Hz line and the ringing would bias the
            # first minutes of the MAD.
            self._pending.append((stacked, times))
            if sum(part[1].size for part in self._pending) < self._init_samples:
                return
            stacked = np.concatenate([part[0] for part in self._pending], axis=1)
            times = np.concatenate([part[1] for part in self._pending])
            self._pending = []
            level = stacked[:, : self._init_samples].mean(axis=1)
            self._zi = self._zi_unit[:, None, :] * level[None, :, None]
        filtered, self._zi = sosfilt(self._sos, stacked, axis=1, zi=self._zi)
        skip = min(self._settle_remaining, filtered.shape[1])
        self._settle_remaining -= skip
        bipolar = filtered[0, skip:]
        common = filtered[1, skip:]
        times = times[skip:]
        position = 0
        while position < bipolar.size:
            if self._usable_index % self._update_samples == 0:
                self._refresh_threshold()
            until_update = self._update_samples - self._usable_index % self._update_samples
            stop = min(bipolar.size, position + until_update)
            self._detect(bipolar[position:stop], common[position:stop], times[position:stop])
            self._append_history(bipolar[position:stop])
            self._usable_index += stop - position
            position = stop

    def _refresh_threshold(self) -> None:
        if self._history_count < self._min_history:
            self._threshold = None
            return
        values = self._history[: self._history_count]
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        self._threshold = max(self.config.mad_k * mad, self.config.floor_uv)

    def _append_history(self, values: np.ndarray) -> None:
        first = (-self._usable_index) % self._decimation
        size = self._history.size
        kept = values[first :: self._decimation][-size:]
        slots = (self._history_position + np.arange(kept.size)) % size
        self._history[slots] = kept
        self._history_position = int((self._history_position + kept.size) % size)
        self._history_count = min(self._history_count + kept.size, size)

    def _detect(self, bipolar: np.ndarray, common: np.ndarray, times: np.ndarray) -> None:
        base = self._usable_index
        block_end = base + bipolar.size
        magnitude = np.abs(bipolar)
        if self._threshold is not None:
            supra = magnitude > self._threshold
            run_starts = np.flatnonzero(supra & ~np.concatenate([[False], supra[:-1]]))
            run_stops = np.flatnonzero(supra & ~np.concatenate([supra[1:], [False]]))
            for first, last in zip(run_starts, run_stops):
                first_index = base + int(first)
                event = self._open
                if event is not None and first_index - event.last_supra_index > self._merge_gap_samples:
                    self._buffer(magnitude, times, base, event.last_supra_index + 1)
                    self._close(times, base)
                if self._open is None:
                    self._open = _OpenEvent(
                        first_supra_index=first_index,
                        last_supra_index=first_index,
                        buffered_until=first_index,
                    )
                event = self._open
                run = slice(int(first), int(last) + 1)
                peak = int(first) + int(np.argmax(magnitude[run]))
                if magnitude[peak] > event.peak_abs:
                    event.peak_abs = float(magnitude[peak])
                    event.peak_uv = float(bipolar[peak])
                    event.peak_time = float(times[peak])
                event.common_mode_peak = max(event.common_mode_peak, float(np.max(np.abs(common[run]))))
                event.last_supra_index = base + int(last)

        if self._open is not None:
            self._buffer(magnitude, times, base, block_end)
            if self._open.last_supra_index + self._merge_gap_samples < block_end:
                self._close(times, base)

    def _buffer(self, magnitude: np.ndarray, times: np.ndarray, base: int, upto: int) -> None:
        """Keep the open event's samples from its first supra-threshold sample on."""
        event = self._open
        start = max(event.buffered_until, base)
        stop = min(upto, base + magnitude.size)
        if event.too_long or stop <= start:
            return
        event.magnitudes.append(magnitude[start - base : stop - base])
        event.times.append(times[start - base : stop - base])
        event.buffered_until = stop
        if stop - event.first_supra_index > self._max_event_samples:
            event.too_long = True
            event.magnitudes, event.times = [], []

    def _close(self, times: np.ndarray, base: int) -> None:
        """Accept or drop the open event; the duration is its width at half its peak."""
        event, self._open = self._open, None
        if event is None or event.too_long:
            return
        span = event.last_supra_index - event.first_supra_index + 1
        magnitude = np.concatenate(event.magnitudes)[:span]
        event_times = np.concatenate(event.times)[:span]
        above = np.flatnonzero(magnitude >= _WIDTH_FRACTION * event.peak_abs)
        duration = (above[-1] - above[0] + 1) / self.config.sample_rate_hz
        if not self.config.min_duration_seconds <= duration <= self.config.max_duration_seconds:
            return
        if (
            self.config.common_mode_veto
            and event.common_mode_peak > self.config.common_mode_ratio * event.peak_abs
        ):
            return
        close_index = event.last_supra_index + self._merge_gap_samples
        accepted = RemEvent(
            time=event.peak_time,
            onset_time=float(event_times[above[0]]),
            offset_time=float(event_times[above[-1]]),
            duration_seconds=float(duration),
            peak_uv=event.peak_uv,
            confirmed_time=_time_at(times, base, close_index, self.config.sample_rate_hz),
        )
        self._events.append(accepted)
        self._last_event_time = accepted.time

    def _summary(self, epoch: SleepEpoch) -> RemEventSummary:
        now = self._last_time if self._last_time is not None else epoch.end_time
        keep_from = min(epoch.start_time, now - self.config.burst_window_seconds)
        self._events = [event for event in self._events if event.confirmed_time >= keep_from]
        in_epoch = [
            event for event in self._events
            if epoch.start_time <= event.confirmed_time < epoch.end_time
        ]
        recent = [
            event for event in self._events
            if event.time > now - self.config.burst_window_seconds
        ]
        minutes = epoch.duration_seconds / 60.0
        return RemEventSummary(
            rem_event_count=float(len(in_epoch)),
            rem_density_per_min=float(len(in_epoch) / minutes) if minutes > 0 else math.nan,
            last_rem_event_age_s=(
                math.nan if self._last_event_time is None else float(now - self._last_event_time)
            ),
            rem_burst_active=len(recent) >= self.config.burst_min_events,
            rem_event_times=tuple(event.time for event in in_epoch),
            rem_event_threshold_uv=self.threshold_uv,
            rem_event_warmup=self.warmup,
        )


def detect_rem_events(
    left_uv: Sequence[float],
    right_uv: Sequence[float],
    *,
    start_time: float = 0.0,
    config: Optional[RemEventConfig] = None,
) -> Tuple[RemEvent, ...]:
    """Run a fresh tracker over two equal-length sample arrays (AF7, AF8 by default).

    Events still open at the end of the arrays are not returned, as a live tracker would
    not have confirmed them yet.
    """
    tracker = RemEventTracker(config)
    left = np.asarray(left_uv, dtype=float)
    right = np.asarray(right_uv, dtype=float)
    if left.shape != right.shape:
        raise ValueError("left and right channels must have the same length")
    times = start_time + np.arange(left.size) / tracker.config.sample_rate_hz
    return tracker.feed_samples(left, right, times)


def _time_at(times: np.ndarray, base: int, index: int, sample_rate_hz: float) -> float:
    """Time of global sample ``index``; events close inside the block being read, the
    nominal-rate fallback is only a guard."""
    position = index - base
    if 0 <= position < times.size:
        return float(times[position])
    anchor = 0 if position < 0 else times.size - 1
    return float(times[anchor] + (position - anchor) / sample_rate_hz)
