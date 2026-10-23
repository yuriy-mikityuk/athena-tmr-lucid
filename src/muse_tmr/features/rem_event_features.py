"""Causal REM-event detection on the bipolar AF7-AF8 derivation (#225).

Horizontal eye movements reach AF7 and AF8, both referenced near Fpz, with opposite
polarity, so they add up in AF7 - AF8, while blinks and frontal slow waves, which are in
phase on the two sites, mostly cancel there. ``RemEventTracker`` filters that difference
causally to 0.3-5 Hz and reads it as a run of segments: stretches of one sign where it
stays above half the threshold ``max(mad_k * MAD, floor_uv)``, the MAD taken over the
filtered difference of the last ``mad_window_seconds``. A segment whose peak clears the
threshold starts an event. The next segment joins it when it follows within
``merge_gap_seconds``, has the other sign and clears the threshold too, so a deflection
and its return count once, while a saccade that stays out counts on its own and a run
of eye movements counts once per deflection instead of merging into one long event. A
segment that follows an event at once but peaks below ``echo_fraction`` of it is the
filter's after-swing and does not count.

An event counts when it lasts ``min_duration_seconds`` to ``max_duration_seconds``,
measured from where its first segment rises past half its own peak to where its last
segment falls below half its own, and, with the common-mode veto on, when (AF7 + AF8) / 2
in the same band carries no more power than the difference over those samples, which
drops in-phase blinks. The width is a property of the waveform, not of the threshold,
so a larger copy of a counted deflection counts the same.

The filter is a first-order Butterworth high-pass, the usual EOG setting, so a saccade
(a step in AF7 - AF8) decays without ringing, and a fourth-order low-pass, which takes a
40 µV line at about 64 Hz (the optics line, #154) below 0.001 µV, so no line removal
runs first. The tracker is causal and deterministic: the threshold for a sample comes
from samples before it, the filter state is carried between calls, and the result does
not depend on how the stream is cut into epochs. Overlapping epochs (a stride shorter
than the epoch) feed each sample once. Run one tracker per session.

Event times are the peak of the filtered difference, about 0.2 s after a saccade starts.
An epoch counts the events confirmed inside it, which happens when the event's last
segment has ended, about 0.5-1.5 s after it started. A jump of more than
``gap_seconds`` in the frame clock, a loss that long reported in ``EEGSample.gaps``, a
frame without AF7 or AF8 or a non-finite sample restarts the filter; shorter losses are
bridged. Density is per minute of the epoch the tracker actually read, and NaN when
that is less than ``min_observed_fraction`` of it.

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
_SEGMENT_BUFFER_FACTOR = 4.0


@dataclass(frozen=True)
class RemEventConfig:
    """UNFITTED: starting values, not fitted on any night; the refit waits for
    REM-bearing p21 nights (#225). Never fit them on synthetic data.

    The low-pass alone takes a 40 µV ~64 Hz line below 0.1 µV, so no line removal runs
    first (tests/test_rem_event_features.py).
    """

    sample_rate_hz: float = 256.0
    channels: Tuple[str, str] = ("AF7", "AF8")
    band_hz: Tuple[float, float] = (0.3, 5.0)
    highpass_order: int = 1
    lowpass_order: int = 4
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
    merge_gap_seconds: float = 0.25
    echo_fraction: float = 0.5
    gap_seconds: float = 0.5
    common_mode_veto: bool = True
    common_mode_ratio: float = 1.0
    burst_window_seconds: float = 10.0
    burst_min_events: int = 2
    min_observed_fraction: float = 0.5

    def validate(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        low_hz, high_hz = self.band_hz
        if not 0 < low_hz < high_hz < self.sample_rate_hz / 2:
            raise ValueError("band_hz must be ordered inside (0, Nyquist)")
        if self.highpass_order < 1 or self.lowpass_order < 1:
            raise ValueError("filter orders must be at least 1")
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
        if self.merge_gap_seconds < 0 or self.gap_seconds <= 0:
            raise ValueError("merge_gap_seconds must be non-negative and gap_seconds positive")
        if not 0 <= self.echo_fraction <= 1:
            raise ValueError("echo_fraction must be between 0 and 1")
        if self.common_mode_ratio <= 0:
            raise ValueError("common_mode_ratio must be positive")
        if self.burst_window_seconds <= 0 or self.burst_min_events < 1:
            raise ValueError("burst window must be positive and burst_min_events at least 1")
        if not 0 <= self.min_observed_fraction <= 1:
            raise ValueError("min_observed_fraction must be between 0 and 1")


@dataclass(frozen=True)
class RemEvent:
    """One counted deflection, in the stream's clock (frame timestamps).

    ``time`` is the peak of the filtered AF7 - AF8, ``onset_time``/``offset_time`` are
    where it rose past and fell below half its peak (per segment), ``segments`` is 2
    when the return joined it, and ``confirmed_time`` is when the tracker accepted it;
    an epoch counts the events confirmed inside it.
    """

    time: float
    onset_time: float
    offset_time: float
    duration_seconds: float
    peak_uv: float
    segments: int
    confirmed_time: float


@dataclass(frozen=True)
class RemEventSummary:
    """What one epoch reports. NaN fields mean AF7 or AF8 was missing or unusable for
    more than ``1 - min_observed_fraction`` of the epoch."""

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
class _Segment:
    """A stretch of one sign above half the threshold, in usable-sample indices."""

    start: int
    sign: int
    truncated: bool
    follows_first: bool = False
    length: int = 0
    peak_abs: float = 0.0
    significant: bool = False
    values: List[np.ndarray] = field(default_factory=list)
    common: List[np.ndarray] = field(default_factory=list)
    times: List[np.ndarray] = field(default_factory=list)
    buffered: bool = True
    end: int = -1
    peak_uv: float = math.nan
    peak_time: float = math.nan
    bipolar_energy: float = 0.0
    common_energy: float = 0.0
    half_rise: int = -1
    half_fall: int = -1
    half_rise_time: float = math.nan
    half_fall_time: float = math.nan

    @property
    def width(self) -> int:
        """Samples from the half-peak rise to the half-peak fall, inclusive."""
        return self.half_fall - self.half_rise + 1 if self.half_rise >= 0 else -1


class RemEventTracker:
    """Stateful, causal REM-event detector for one session."""

    def __init__(self, config: Optional[RemEventConfig] = None) -> None:
        self.config = config or RemEventConfig()
        self.config.validate()
        fs = self.config.sample_rate_hz
        self._sos = design_bandpass(self.config)
        self._zi_unit = sosfilt_zi(self._sos)
        self._settle_samples = int(round(self.config.settle_seconds * fs))
        self._init_samples = max(1, int(round(_FILTER_INIT_SECONDS * fs)))
        self._update_samples = max(1, int(round(self.config.threshold_update_seconds * fs)))
        self._merge_gap_samples = int(round(self.config.merge_gap_seconds * fs))
        self._min_samples = int(round(self.config.min_duration_seconds * fs))
        self._max_samples = int(round(self.config.max_duration_seconds * fs))
        self._buffer_samples = int(round(_SEGMENT_BUFFER_FACTOR * self.config.max_duration_seconds * fs))
        self._lost_samples_limit = self.config.gap_seconds * fs
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
        self._last_examined_time = math.nan
        self._consumed_until: Optional[float] = None
        self._spans: List[List[float]] = []
        self._first: Optional[_Segment] = None
        self._reset_segment()

    # -- public API ---------------------------------------------------------

    @property
    def warmup(self) -> bool:
        """True while the running MAD covers less than ``warmup_seconds``."""
        return self._history_count < self._warmup_history

    @property
    def threshold_uv(self) -> float:
        return math.nan if self._threshold is None else float(self._threshold)

    @property
    def events(self) -> Tuple[RemEvent, ...]:
        """Events kept for the epochs still to come (all of them for raw samples)."""
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
                _append_break(left_parts, right_parts, time_parts, frame.timestamp)
                continue
            count = min(len(left_values), len(right_values))
            frame_left = np.asarray(left_values[:count], dtype=float)
            frame_right = np.asarray(right_values[:count], dtype=float)
            frame_times = frame.timestamp + np.arange(count) / fs
            cuts = sorted(
                {
                    index
                    for index, missing in frame.eeg.gaps
                    if missing >= self._lost_samples_limit and 0 <= index < count
                }
            )
            start = 0
            for cut in cuts:
                left_parts.append(frame_left[start:cut])
                right_parts.append(frame_right[start:cut])
                time_parts.append(frame_times[start:cut])
                _append_break(left_parts, right_parts, time_parts, float(frame_times[cut]))
                start = cut
            left_parts.append(frame_left[start:])
            right_parts.append(frame_right[start:])
            time_parts.append(frame_times[start:])
        self._consume_until(epoch)
        if left_parts:
            self._feed(
                np.concatenate(left_parts),
                np.concatenate(right_parts),
                np.concatenate(time_parts),
            )
        return self._summary(epoch)

    def skip(self, epoch: SleepEpoch) -> RemEventSummary:
        """Mark the epoch's new samples as unusable: a gap for the filter, NaN features."""
        self._consume_until(epoch)
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

    # -- input --------------------------------------------------------------

    def _new_frames(self, epoch: SleepEpoch):
        if self._consumed_until is None:
            return epoch.frames
        return tuple(frame for frame in epoch.frames if frame.timestamp >= self._consumed_until)

    def _consume_until(self, epoch: SleepEpoch) -> None:
        self._consumed_until = (
            epoch.end_time
            if self._consumed_until is None
            else max(self._consumed_until, epoch.end_time)
        )

    def _reset_segment(self) -> None:
        """Restart the filter. A segment still open is dropped; one waiting for its
        partner is complete and counts on its own."""
        if self._first is not None:
            self._emit(self._first, None, self._last_examined_time)
        self._zi: Optional[np.ndarray] = None
        self._pending_input: List[Tuple[np.ndarray, np.ndarray]] = []
        self._settle_remaining = self._settle_samples
        self._segment: Optional[_Segment] = None
        self._first = None
        self._examining = False
        self._truncation_index = -1
        self._echo_end = -math.inf
        self._echo_peak = 0.0
        self._span_open = False

    def _feed(self, left: np.ndarray, right: np.ndarray, times: np.ndarray) -> None:
        if left.size == 0:
            return
        step = 1.0 / self.config.sample_rate_hz
        finite = np.isfinite(left) & np.isfinite(right) & np.isfinite(times)
        jumps = np.zeros(left.size, dtype=bool)
        if self._last_time is not None:
            jumps[0] = abs(times[0] - (self._last_time + step)) > self.config.gap_seconds
        if left.size > 1:
            with np.errstate(invalid="ignore"):
                jumps[1:] = np.abs(np.diff(times) - step) > self.config.gap_seconds
        jumps &= finite
        cuts = np.flatnonzero(~finite | jumps)
        bounds = np.concatenate([[0], cuts, [left.size]])
        for start, stop in zip(bounds[:-1], bounds[1:]):
            if start == stop:
                continue
            if not finite[start]:
                self._reset_segment()
                start += 1
                if start == stop:
                    continue
            elif jumps[start]:
                self._reset_segment()
            self._consume(left[start:stop], right[start:stop], times[start:stop])
            self._last_time = float(times[stop - 1])

    def _consume(self, left: np.ndarray, right: np.ndarray, times: np.ndarray) -> None:
        stacked = np.vstack([left - right, 0.5 * (left + right)])
        if self._zi is None:
            # Start the filter from the mean of the first half second, not from the first
            # sample: one sample is off by the ~64 Hz line and the start would ring.
            self._pending_input.append((stacked, times))
            if sum(part[1].size for part in self._pending_input) < self._init_samples:
                return
            stacked = np.concatenate([part[0] for part in self._pending_input], axis=1)
            times = np.concatenate([part[1] for part in self._pending_input])
            self._pending_input = []
            level = stacked[:, : self._init_samples].mean(axis=1)
            self._zi = self._zi_unit[:, None, :] * level[None, :, None]
        filtered, self._zi = sosfilt(self._sos, stacked, axis=1, zi=self._zi)
        skip = min(self._settle_remaining, filtered.shape[1])
        self._settle_remaining -= skip
        bipolar = filtered[0, skip:]
        common = filtered[1, skip:]
        times = times[skip:]
        if bipolar.size and not self._examining:
            # The first sample read after a (re)start: a segment that starts here has
            # lost its beginning to the filter's settling.
            self._examining = True
            self._truncation_index = self._usable_index
        position = 0
        while position < bipolar.size:
            if self._usable_index % self._update_samples == 0:
                self._refresh_threshold()
            until_update = self._update_samples - self._usable_index % self._update_samples
            stop = min(bipolar.size, position + until_update)
            self._scan(bipolar[position:stop], common[position:stop], times[position:stop])
            self._append_history(bipolar[position:stop])
            self._usable_index += stop - position
            position = stop

    # -- threshold ----------------------------------------------------------

    def _refresh_threshold(self) -> None:
        if self._history_count < self._min_history:
            self._threshold = None
            return
        if self._threshold is None:
            # Segments can only start from here on; one already above half the new
            # threshold has lost its beginning.
            self._truncation_index = self._usable_index
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

    # -- segments and events --------------------------------------------------

    def _scan(self, bipolar: np.ndarray, common: np.ndarray, times: np.ndarray) -> None:
        """Cut one block (one threshold) into segments and settle the events they end."""
        base = self._usable_index
        size = bipolar.size
        threshold = self._threshold
        if threshold is None:
            labels = np.zeros(size, dtype=np.int8)
        else:
            above = np.abs(bipolar) >= 0.5 * threshold
            labels = np.where(above, np.where(bipolar >= 0.0, 1, -1), 0).astype(np.int8)
            end_time = float(times[-1]) + 1.0 / self.config.sample_rate_hz
            if self._span_open:
                self._spans[-1][1] = max(self._spans[-1][1], end_time)
            else:
                self._spans.append([float(times[0]), end_time])
                self._span_open = True
        run_starts = np.concatenate([[0], np.flatnonzero(labels[1:] != labels[:-1]) + 1])
        run_stops = np.concatenate([run_starts[1:], [size]])
        for start, stop in zip(run_starts, run_stops):
            label = int(labels[start])
            segment = self._segment
            if segment is not None and (label != segment.sign or start > 0):
                self._close_segment(segment, base + int(start), times, base)
                segment = None
            if label == 0:
                self._expire_first(base + int(stop), times, base)
                continue
            if segment is None:
                segment = self._open_segment(base + int(start), label, times, base)
            self._extend_segment(segment, bipolar[start:stop], common[start:stop], times[start:stop], threshold)
        self._last_examined_time = float(times[-1])

    def _open_segment(self, index: int, sign: int, times: np.ndarray, base: int) -> _Segment:
        self._expire_first(index, times, base)
        segment = _Segment(start=index, sign=sign, truncated=index == self._truncation_index)
        if self._first is not None:
            segment.follows_first = True
        self._segment = segment
        return segment

    def _extend_segment(
        self,
        segment: _Segment,
        bipolar: np.ndarray,
        common: np.ndarray,
        times: np.ndarray,
        threshold: Optional[float],
    ) -> None:
        peak = float(np.max(np.abs(bipolar)))
        segment.peak_abs = max(segment.peak_abs, peak)
        if threshold is not None and peak > threshold:
            segment.significant = True
        segment.length += bipolar.size
        if not segment.buffered:
            return
        if segment.length > self._buffer_samples:
            segment.buffered = False
            segment.values, segment.common, segment.times = [], [], []
            return
        segment.values.append(bipolar)
        segment.common.append(common)
        segment.times.append(times)

    def _close_segment(self, segment: _Segment, end: int, times: np.ndarray, base: int) -> None:
        """Settle the segment that ended just before sample ``end`` of this block."""
        self._segment = None
        segment.end = end
        if segment.buffered:
            values = np.concatenate(segment.values)
            magnitude = np.abs(values)
            peak = int(np.argmax(magnitude))
            half = 0.5 * magnitude[peak]
            below_before = np.flatnonzero(magnitude[:peak] < half)
            below_after = np.flatnonzero(magnitude[peak + 1 :] < half)
            rise = int(below_before[-1]) + 1 if below_before.size else 0
            fall = peak + int(below_after[0]) if below_after.size else values.size - 1
            segment_times = np.concatenate(segment.times)
            common = np.concatenate(segment.common)[rise : fall + 1]
            segment.peak_uv = float(values[peak])
            segment.peak_time = float(segment_times[peak])
            segment.bipolar_energy = float(np.sum(values[rise : fall + 1] ** 2))
            segment.common_energy = float(np.sum(common**2))
            segment.half_rise = segment.start + rise
            segment.half_fall = segment.start + fall
            segment.half_rise_time = float(segment_times[rise])
            segment.half_fall_time = float(segment_times[fall])
            segment.values, segment.common, segment.times = [], [], []
        confirmed_time = float(times[end - base])
        first = self._first
        if first is not None and segment.follows_first:
            self._first = None
            if (
                segment.significant
                and segment.buffered
                and segment.sign != first.sign
                and segment.half_fall - first.half_rise + 1 <= self._max_samples
            ):
                self._emit(first, segment, confirmed_time)
                return
            self._emit(first, None, confirmed_time)
        if not segment.significant or segment.truncated:
            return
        if (
            segment.start - self._echo_end <= self._merge_gap_samples
            and segment.peak_abs < self.config.echo_fraction * self._echo_peak
        ):
            return
        if segment.buffered and segment.width <= self._max_samples:
            self._first = segment
        else:
            self._echo_end, self._echo_peak = segment.end, segment.peak_abs

    def _expire_first(self, index: int, times: np.ndarray, base: int) -> None:
        """A first segment with no follower within the merge gap counts on its own."""
        first = self._first
        if first is None or self._segment is not None:
            return
        deadline = first.end + self._merge_gap_samples
        if deadline < index:
            self._first = None
            self._emit(first, None, float(times[max(0, deadline - base)]))

    def _emit(self, first: _Segment, second: Optional[_Segment], confirmed_time: float) -> None:
        last = second or first
        top = first if second is None or first.peak_abs >= second.peak_abs else second
        self._echo_end, self._echo_peak = last.end, top.peak_abs
        width = last.half_fall - first.half_rise + 1
        if not self._min_samples <= width <= self._max_samples:
            return
        segments = (first,) if second is None else (first, second)
        common_energy = sum(segment.common_energy for segment in segments)
        bipolar_energy = sum(segment.bipolar_energy for segment in segments)
        if (
            self.config.common_mode_veto
            and common_energy > self.config.common_mode_ratio**2 * bipolar_energy
        ):
            return
        event = RemEvent(
            time=top.peak_time,
            onset_time=first.half_rise_time,
            offset_time=last.half_fall_time,
            duration_seconds=width / self.config.sample_rate_hz,
            peak_uv=top.peak_uv,
            segments=1 if second is None else 2,
            confirmed_time=confirmed_time,
        )
        self._events.append(event)
        self._last_event_time = event.time

    # -- summary ------------------------------------------------------------

    def _summary(self, epoch: SleepEpoch) -> RemEventSummary:
        duration = epoch.duration_seconds
        observed = sum(
            max(0.0, min(end, epoch.end_time) - max(start, epoch.start_time))
            for start, end in self._spans
        )
        if self._last_time is None or duration <= 0 or observed <= 0:
            return RemEventSummary.missing(warmup=self.warmup)
        if observed < self.config.min_observed_fraction * duration:
            return RemEventSummary.missing(warmup=self.warmup)
        now = self._last_time
        keep_from = min(epoch.start_time, now - self.config.burst_window_seconds)
        self._events = [event for event in self._events if event.confirmed_time >= keep_from]
        open_span = self._spans[-1] if self._span_open else None
        self._spans = [
            span for span in self._spans if span[1] > epoch.start_time or span is open_span
        ]
        in_epoch = [
            event for event in self._events
            if epoch.start_time <= event.confirmed_time < epoch.end_time
        ]
        recent = [
            event for event in self._events
            if event.time > now - self.config.burst_window_seconds
        ]
        return RemEventSummary(
            rem_event_count=float(len(in_epoch)),
            rem_density_per_min=float(len(in_epoch) / (observed / 60.0)),
            last_rem_event_age_s=(
                math.nan if self._last_event_time is None else float(now - self._last_event_time)
            ),
            rem_burst_active=len(recent) >= self.config.burst_min_events,
            rem_event_times=tuple(event.time for event in in_epoch),
            rem_event_threshold_uv=self.threshold_uv,
            rem_event_warmup=self.warmup,
        )


def design_bandpass(config: RemEventConfig) -> np.ndarray:
    """The tracker's causal band-pass as second-order sections: a Butterworth high-pass
    of ``highpass_order`` at ``band_hz[0]`` and a low-pass of ``lowpass_order`` at
    ``band_hz[1]``."""
    low_hz, high_hz = config.band_hz
    fs = config.sample_rate_hz
    highpass = butter(config.highpass_order, low_hz, btype="highpass", fs=fs, output="sos")
    lowpass = butter(config.lowpass_order, high_hz, btype="lowpass", fs=fs, output="sos")
    return np.vstack([highpass, lowpass])


def detect_rem_events(
    left_uv: Sequence[float],
    right_uv: Sequence[float],
    *,
    start_time: float = 0.0,
    config: Optional[RemEventConfig] = None,
) -> Tuple[RemEvent, ...]:
    """Run a fresh tracker over two equal-length sample arrays (AF7, AF8 by default).

    Events not yet confirmed at the end of the arrays are not returned, as a live
    tracker would not have confirmed them yet.
    """
    tracker = RemEventTracker(config)
    left = np.asarray(left_uv, dtype=float)
    right = np.asarray(right_uv, dtype=float)
    if left.shape != right.shape:
        raise ValueError("left and right channels must have the same length")
    times = start_time + np.arange(left.size) / tracker.config.sample_rate_hz
    return tracker.feed_samples(left, right, times)


def _append_break(
    left_parts: List[np.ndarray],
    right_parts: List[np.ndarray],
    time_parts: List[np.ndarray],
    timestamp: float,
) -> None:
    """A non-finite sample: the filter restarts there."""
    left_parts.append(np.array([math.nan]))
    right_parts.append(np.array([math.nan]))
    time_parts.append(np.array([timestamp]))
