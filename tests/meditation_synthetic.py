"""Synthetic 4-channel MuseFrame streams for meditation analysis tests."""

import numpy as np
from scipy.signal import butter, sosfiltfilt

from muse_tmr.data.sample_types import EEGSample, MuseFrame

FS = 256.0
CHANNELS = ("TP9", "AF7", "AF8", "TP10")
SAMPLES_PER_FRAME = 12


def pink_noise(n, chi, rng):
    freqs = np.fft.rfftfreq(n, 1.0 / FS)
    spectrum = rng.standard_normal(freqs.size) + 1j * rng.standard_normal(freqs.size)
    spectrum[1:] *= freqs[1:] ** (-chi / 2.0)
    spectrum[0] = 0.0
    signal = np.fft.irfft(spectrum, n)
    return signal / np.std(signal)


def band_noise(n, band_hz, rng):
    sos = butter(4, band_hz, btype="bandpass", fs=FS, output="sos")
    signal = sosfiltfilt(sos, rng.standard_normal(n))
    return signal / np.std(signal)


def condition_signal(condition, seconds, rng, emg_uv=0.0):
    """'busy': broadband noise (high LZC). 'calm': strong alpha + 1/f^2 (low LZC)."""
    n = int(seconds * FS)
    t = np.arange(n) / FS
    out = {}
    for channel in CHANNELS:
        if condition == "busy":
            signal = 10.0 * pink_noise(n, 0.5, rng)
        elif condition == "calm":
            signal = 10.0 * pink_noise(n, 2.0, rng) + 15.0 * np.sin(2 * np.pi * 10.0 * t + rng.uniform(0, 6.28))
        else:
            raise ValueError(condition)
        if emg_uv:
            # Broadband EMG-like burst activity that varies epoch to epoch.
            envelope = np.repeat(rng.uniform(0.3, 1.7, size=n // int(10 * FS) + 1), int(10 * FS))[:n]
            signal = signal + emg_uv * envelope * band_noise(n, (30.0, 95.0), rng)
        out[channel] = signal
    return out


def frames_from_segments(segments, start_time=1_700_000_000.0):
    """segments: list of dicts channel -> samples, played back to back."""
    data = {channel: np.concatenate([segment[channel] for segment in segments]) for channel in CHANNELS}
    total = data[CHANNELS[0]].size
    frames = []
    for offset in range(0, total - SAMPLES_PER_FRAME + 1, SAMPLES_PER_FRAME):
        timestamp = start_time + offset / FS
        frames.append(
            MuseFrame(
                timestamp=timestamp,
                eeg=EEGSample(
                    timestamp=timestamp,
                    channels_uv={
                        channel: tuple(float(v) for v in data[channel][offset : offset + SAMPLES_PER_FRAME])
                        for channel in CHANNELS
                    },
                ),
                source="synthetic",
            )
        )
    return frames


def session_frames(plan, conditions_signal, rng, end_padding_s=10.0):
    """Frames for a plan: settle, then each block's condition signal."""
    segments = [conditions_signal("settle", plan.settle_seconds, rng)] if plan.settle_seconds else []
    for block in plan.blocks:
        segments.append(conditions_signal(block.condition, block.end_s - block.start_s, rng))
    segments.append(conditions_signal("settle", end_padding_s, rng))
    return frames_from_segments(segments)


async def aiter_frames(frames):
    for frame in frames:
        yield frame
