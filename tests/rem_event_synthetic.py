"""Seeded synthetic frontal EEG with injected eye-movement deflections (#225).

Synthetic input, not sleep. It stands in for Muse AF7/AF8: a shared 1/f background, a
smaller independent 1/f noise per channel, the ~64 Hz optics line (#154), biphasic
deflections of opposite polarity on AF7 and AF8 for horizontal eye movements, and
in-phase blinks that are larger on one side. The noise and the two shapes come from
``muse_tmr.testing.synthetic``, which builds whole synthetic nights from them.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from muse_tmr.data.sample_types import EEGSample, MuseFrame
from muse_tmr.features.epochs import EpochBuilder, EpochConfig
from muse_tmr.testing import synthetic
from muse_tmr.testing.synthetic import blink_shape, deflection

FS = 256.0
LINE_HZ = 63.93
CHANNELS = ("TP9", "AF7", "AF8", "TP10")
SAMPLES_PER_FRAME = 12
START_TIME = 1_700_000_000.0

# The deflections in the rem_like_eeg_channels() fixtures: onset (s), duration (s) and
# sign of the AF7 lobe. AF8 gets the mirror image, so AF7 - AF8 carries twice the swing.
# They start after 7.5 s, so a tracker that sees only this epoch (0.5 s filter start,
# 2 s settling, 5 s before its first threshold) counts all eight.
FIXTURE_DEFLECTIONS = (
    (8.0, 0.5, 1.0),
    (10.5, 0.8, -1.0),
    (13.0, 0.6, 1.0),
    (15.5, 1.0, -1.0),
    (18.0, 0.5, 1.0),
    (20.5, 0.8, -1.0),
    (23.0, 0.6, 1.0),
    (25.5, 1.0, -1.0),
)


def pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    """Unit-RMS noise with a 1/f power spectrum."""
    return synthetic.pink_noise(n, 1.0, rng, fs=FS)


def rem_deflection_train(
    seconds: float = 30.0,
    deflections=FIXTURE_DEFLECTIONS,
    amplitude_uv: float = 20.0,
) -> np.ndarray:
    """The AF7 eye term of the rem_like_eeg_channels() fixtures; AF8 gets its negative."""
    eye = np.zeros(int(round(seconds * FS)))
    for onset_s, duration_s, sign in deflections:
        shape = sign * deflection(duration_s, amplitude_uv)
        start = int(round(onset_s * FS))
        eye[start : start + shape.size] += shape[: max(0, eye.size - start)]
    return eye


@dataclass(frozen=True)
class FrontalSignal:
    channels: Dict[str, np.ndarray]
    event_onsets: Tuple[float, ...]
    event_durations: Tuple[float, ...]
    blink_onsets: Tuple[float, ...]
    blink_duration_s: float

    @property
    def event_centres(self) -> np.ndarray:
        """Seconds from the start to the middle of each injected deflection."""
        return np.array(self.event_onsets) + np.array(self.event_durations) / 2

    @property
    def blink_centres(self) -> np.ndarray:
        return np.array(self.blink_onsets) + self.blink_duration_s / 2


def frontal_signal(
    seconds: float,
    *,
    seed: int,
    event_count: int = 0,
    blink_count: int = 0,
    line_uv: float = 40.0,
    shared_rms_uv: float = 14.0,
    independent_rms_uv: float = 5.0,
    first_event_s: float = 10.0,
    amplitude_range_uv: Tuple[float, float] = (20.0, 60.0),
    duration_range_s: Tuple[float, float] = (0.4, 1.5),
    blink_amplitude_range_uv: Tuple[float, float] = (100.0, 200.0),
    blink_duration_s: float = 0.35,
    min_spacing_s: float = 2.5,
) -> FrontalSignal:
    """Four channels in µV; deflections and blinks never overlap one another.

    Each channel is ``shared_rms_uv`` of common 1/f background plus
    ``independent_rms_uv`` of its own 1/f noise (about 15 µV RMS in total). A
    deflection puts ``a * d(t)`` on AF7 and ``-a * r * d(t)`` on AF8 (a in
    ``amplitude_range_uv``, r in 0.8-1.0); a blink puts ``b * w(t)`` on one frontal site
    and ``b * r * w(t)`` on the other (r in 0.7-0.9). The line is ``line_uv`` on AF7 and
    0.6 of that, phase-shifted, on AF8. Every random draw comes before the line's, so the
    same seed gives the same noise, deflections and blinks with or without it.
    """
    rng = np.random.default_rng(seed)
    n = int(round(seconds * FS))
    t = np.arange(n) / FS
    shared = shared_rms_uv * pink_noise(n, rng)
    channels = {name: shared + independent_rms_uv * pink_noise(n, rng) for name in CHANNELS}

    onsets = _spaced_onsets(
        rng,
        count=event_count + blink_count,
        first_s=first_event_s,
        last_s=seconds - 3.0,
        min_spacing_s=min_spacing_s,
    )
    kinds = np.array([True] * event_count + [False] * blink_count)
    rng.shuffle(kinds)
    event_onsets, event_durations, blink_onsets = [], [], []
    for onset_s, is_event in zip(onsets, kinds):
        start = int(round(onset_s * FS))
        if is_event:
            duration_s = float(rng.uniform(*duration_range_s))
            sign = rng.choice([-1.0, 1.0])
            shape = sign * deflection(duration_s, float(rng.uniform(*amplitude_range_uv)))
            stop = start + shape.size
            channels["AF7"][start:stop] += shape
            channels["AF8"][start:stop] -= float(rng.uniform(0.8, 1.0)) * shape
            event_onsets.append(float(onset_s))
            event_durations.append(duration_s)
        else:
            shape = blink_shape(blink_duration_s, float(rng.uniform(*blink_amplitude_range_uv)))
            stop = start + shape.size
            larger, smaller = ("AF7", "AF8") if rng.random() < 0.5 else ("AF8", "AF7")
            channels[larger][start:stop] += shape
            channels[smaller][start:stop] += float(rng.uniform(0.7, 0.9)) * shape
            blink_onsets.append(float(onset_s))

    if line_uv:
        phase = float(rng.uniform(0, 2 * np.pi))
        channels["AF7"] = channels["AF7"] + line_uv * np.sin(2 * np.pi * LINE_HZ * t + phase)
        channels["AF8"] = channels["AF8"] + 0.6 * line_uv * np.sin(2 * np.pi * LINE_HZ * t + phase + 1.0)
    return FrontalSignal(
        channels=channels,
        event_onsets=tuple(event_onsets),
        event_durations=tuple(event_durations),
        blink_onsets=tuple(blink_onsets),
        blink_duration_s=blink_duration_s,
    )


def _spaced_onsets(rng, *, count, first_s, last_s, min_spacing_s):
    onsets = []
    attempts = 0
    while len(onsets) < count:
        attempts += 1
        if attempts > 100_000:
            raise ValueError("cannot place that many events with that spacing")
        candidate = float(rng.uniform(first_s, last_s))
        if all(abs(candidate - other) >= min_spacing_s for other in onsets):
            onsets.append(candidate)
    return sorted(onsets)


def frames_from_channels(
    channels: Dict[str, np.ndarray],
    *,
    start_time: float = START_TIME,
    samples_per_frame: int = SAMPLES_PER_FRAME,
    drop_channel: Optional[str] = None,
    jitter_s: float = 0.0,
    seed: int = 0,
) -> Sequence[MuseFrame]:
    """EEG frames of ``samples_per_frame`` samples; ``jitter_s`` moves each frame's
    timestamp by up to that much, like BLE notification times."""
    rng = np.random.default_rng(seed)
    total = next(iter(channels.values())).size
    frames = []
    for offset in range(0, total - samples_per_frame + 1, samples_per_frame):
        timestamp = start_time + offset / FS
        if jitter_s:
            timestamp += float(rng.uniform(-jitter_s, jitter_s))
        frames.append(
            MuseFrame(
                timestamp=timestamp,
                eeg=EEGSample(
                    timestamp=timestamp,
                    channels_uv={
                        name: tuple(float(v) for v in values[offset : offset + samples_per_frame])
                        for name, values in channels.items()
                        if name != drop_channel
                    },
                    source="synthetic",
                ),
                source="synthetic",
            )
        )
    return frames


async def _aiter(frames):
    for frame in frames:
        yield frame


async def build_epochs(frames, *, epoch_seconds: float = 30.0, stride_seconds: float = 30.0):
    builder = EpochBuilder(EpochConfig(epoch_seconds=epoch_seconds, stride_seconds=stride_seconds))
    return [epoch async for epoch in builder.build(_aiter(frames))]
