"""EEG complexity, aperiodic, chaoticity and EMG metrics for meditation epochs.

Pure numpy/scipy. Metrics follow the set compared in Mago et al. 2025
("Meditative absorption shifts brain dynamics toward criticality",
arXiv:2511.20990, preprint): Lempel-Ziv complexity, sample and permutation
entropy, spectral entropy, Hjorth parameters, aperiodic 1/f fit, largest
Lyapunov exponent and band-envelope DFA. On a 4-channel Muse most of these
also move with scalp EMG, so EMG indicators are computed next to them.

This module is a side track to the REM/TMR pipeline and must stay decoupled
from REM detection, gating, scheduling and audio.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.integrate import trapezoid
from scipy.signal import butter, detrend, filtfilt, hilbert, iirnotch, sosfiltfilt, welch
from scipy.spatial import cKDTree

from muse_tmr.features.eeg_features import (
    EEG_BANDS,
    EEGFeatureConfig,
    _collect_epoch_eeg,
    extract_eeg_features,
)
from muse_tmr.features.epochs import SleepEpoch

COMPLEXITY_CHANNELS = ("TP9", "AF7", "AF8", "TP10")

# Per-epoch metric names, in output order. Per-channel columns are
# f"{metric}_{channel}", aggregates f"{metric}_{group}" for CHANNEL_GROUPS.
EPOCH_METRICS = (
    "lzc",
    "sample_entropy",
    "permutation_entropy",
    "spectral_entropy",
    "hjorth_mobility",
    "hjorth_complexity",
    "aperiodic_exponent_2_20",
    "aperiodic_offset_2_20",
    "aperiodic_exponent_2_40",
    "aperiodic_offset_2_40",
    "lyapunov_max",
    "band_power_delta",
    "band_power_theta",
    "band_power_alpha",
    "band_power_beta",
    "band_power_gamma",
    "relative_power_alpha",
    "relative_power_gamma",
    "emg_power_30_45",
    "emg_power_30_45_rel",
    "emg_power_55_95",
    "emg_high_band_over_floor_db",
)
CHANNEL_GROUPS = ("all", "frontal", "temporal")


@dataclass(frozen=True)
class ComplexityConfig:
    """Every parameter of the metrics; written into each analysis output."""

    sample_rate_hz: float = 256.0
    channels: Tuple[str, ...] = COMPLEXITY_CHANNELS
    frontal_channels: Tuple[str, ...] = ("AF7", "AF8")
    temporal_channels: Tuple[str, ...] = ("TP9", "TP10")
    min_channel_seconds: float = 2.0
    # Complexity metrics run on a detrended, zero-phase band-passed signal.
    complexity_band_hz: Tuple[float, float] = (0.5, 40.0)
    filter_order: int = 4
    # Spectral and EMG metrics run on the detrended signal with a mains notch.
    notch_hz: Optional[float] = 50.0
    notch_quality: float = 30.0
    welch_seconds: float = 2.0
    spectral_entropy_band_hz: Tuple[float, float] = (0.5, 40.0)
    sample_entropy_m: int = 2
    sample_entropy_r: float = 0.2
    permutation_order: int = 3
    permutation_delay: int = 1
    aperiodic_ranges_hz: Tuple[Tuple[float, float], ...] = ((2.0, 20.0), (2.0, 40.0))
    aperiodic_peak_threshold_sigma: float = 2.0
    aperiodic_max_iterations: int = 5
    # Rosenstein 1993. Experimental: noisy and parameter-sensitive on 10 s.
    lyapunov_enabled: bool = True
    lyapunov_embedding_dimension: int = 7
    lyapunov_delay_samples: int = 4
    lyapunov_theiler_samples: int = 64
    lyapunov_trajectory_samples: int = 32
    bands: Mapping[str, Tuple[float, float]] = field(default_factory=lambda: dict(EEG_BANDS))
    emg_low_band_hz: Tuple[float, float] = (30.0, 45.0)
    # Above 50 Hz mains and below its 100 Hz harmonic.
    emg_high_band_hz: Tuple[float, float] = (55.0, 95.0)
    emg_reference_band_hz: Tuple[float, float] = (1.0, 45.0)
    # Near-Nyquist floor: if 55-95 Hz is not above it, the band carries nothing.
    emg_floor_band_hz: Tuple[float, float] = (110.0, 125.0)
    # Narrow device lines bridged over in the EMG bands. Muse S Athena has one
    # at exactly fs/4 = 64 Hz, 23-45 dB above its neighbours and fading over a
    # session; left in, it is most of the 55-95 Hz power.
    emg_exclude_hz: Tuple[float, ...] = (64.0,)
    emg_exclude_half_width_hz: float = 1.5
    dfa_bands_hz: Mapping[str, Tuple[float, float]] = field(
        default_factory=lambda: {
            "theta": (4.0, 8.0),
            "alpha": (8.0, 12.0),
            "beta": (12.0, 30.0),
            "low_gamma": (30.0, 45.0),
        }
    )
    dfa_broadband_hz: Tuple[float, float] = (1.0, 40.0)
    dfa_min_window_seconds: float = 1.0
    dfa_max_window_fraction: float = 0.1
    dfa_window_count: int = 16
    dfa_min_segment_seconds: float = 20.0
    artifact_abs_uv_threshold: float = 500.0
    artifact_clipping_fraction_threshold: float = 0.05
    flat_std_uv_threshold: float = 1e-6
    min_eeg_coverage: float = 0.5

    def validate(self) -> None:
        nyquist = self.sample_rate_hz / 2.0
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        low, high = self.complexity_band_hz
        if not 0 < low < high < nyquist:
            raise ValueError("complexity_band_hz must be inside (0, nyquist)")
        if self.emg_high_band_hz[1] >= nyquist:
            raise ValueError("emg_high_band_hz must stay below nyquist")
        if self.sample_entropy_m < 1 or self.sample_entropy_r <= 0:
            raise ValueError("sample entropy needs m >= 1 and r > 0")
        if self.permutation_order < 2 or self.permutation_delay < 1:
            raise ValueError("permutation entropy needs order >= 2 and delay >= 1")
        if self.lyapunov_embedding_dimension < 2 or self.lyapunov_trajectory_samples < 2:
            raise ValueError("lyapunov needs embedding dimension >= 2 and trajectory >= 2")
        if not 0 < self.dfa_max_window_fraction <= 0.5:
            raise ValueError("dfa_max_window_fraction must be inside (0, 0.5]")

    def to_dict(self) -> Dict[str, object]:
        return _jsonable(asdict(self))

    def eeg_feature_config(self) -> EEGFeatureConfig:
        return EEGFeatureConfig(
            sample_rate_hz=self.sample_rate_hz,
            artifact_abs_uv_threshold=self.artifact_abs_uv_threshold,
            artifact_clipping_fraction_threshold=self.artifact_clipping_fraction_threshold,
            flat_std_uv_threshold=self.flat_std_uv_threshold,
            min_eeg_coverage=self.min_eeg_coverage,
        )


@dataclass(frozen=True)
class ComplexityFeatureRow:
    epoch_index: int
    start_time: float
    end_time: float
    values: Mapping[str, float]
    artifact_flags: Tuple[str, ...]
    bad_channels: Tuple[str, ...]

    @property
    def is_artifact(self) -> bool:
        return bool(self.artifact_flags)

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "epoch_index": self.epoch_index,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "is_artifact": self.is_artifact,
            "artifact_flags": ";".join(self.artifact_flags),
            "bad_channels": ";".join(self.bad_channels),
        }
        payload.update(self.values)
        return payload


def extract_complexity_features(
    epoch: SleepEpoch,
    config: Optional[ComplexityConfig] = None,
    channels: Optional[Mapping[str, np.ndarray]] = None,
) -> ComplexityFeatureRow:
    """Per-channel metrics plus channel-group means for one epoch.

    Artifact flags come from ``eeg_features`` (clipping, flatline, empty,
    nonfinite, coverage), plus ``eeg_missing_<ch>`` / ``eeg_short_<ch>`` when a
    configured channel is absent or too short, so a group mean never silently
    covers fewer channels in a "clean" epoch. Flagged epochs are kept and
    marked; bad channels get NaN and are left out of the group means.
    """
    config = config or ComplexityConfig()
    config.validate()
    if channels is None:
        channels = _collect_epoch_eeg(epoch)
    eeg_row = extract_eeg_features(epoch, config=config.eeg_feature_config())
    flags = set(eeg_row.artifact_flags)
    bad = set(eeg_row.bad_channels)
    min_samples = config.min_channel_seconds * config.sample_rate_hz
    for channel in config.channels:
        values = channels.get(channel)
        if values is None:
            flags.add(f"eeg_missing_{channel}")
            bad.add(channel)
        elif np.count_nonzero(np.isfinite(values)) < min_samples:
            flags.add(f"eeg_short_{channel}")
            bad.add(channel)

    per_channel: Dict[str, Dict[str, float]] = {}
    for channel in config.channels:
        if channel in bad:
            per_channel[channel] = {metric: math.nan for metric in EPOCH_METRICS}
            continue
        per_channel[channel] = channel_metrics(channels[channel], config)

    values: Dict[str, float] = {}
    for metric in EPOCH_METRICS:
        for channel in config.channels:
            values[f"{metric}_{channel}"] = per_channel[channel][metric]
        for group, members in _channel_groups(config).items():
            values[f"{metric}_{group}"] = _nanmean(
                per_channel[channel][metric] for channel in members
            )
    return ComplexityFeatureRow(
        epoch_index=epoch.index,
        start_time=epoch.start_time,
        end_time=epoch.end_time,
        values=values,
        artifact_flags=tuple(sorted(flags)),
        bad_channels=tuple(sorted(bad)),
    )


def channel_metrics(values: np.ndarray, config: ComplexityConfig) -> Dict[str, float]:
    """All per-epoch metrics for one channel's raw microvolt samples."""
    fs = config.sample_rate_hz
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < config.min_channel_seconds * fs or float(np.std(x)) <= 0:
        return {metric: math.nan for metric in EPOCH_METRICS}

    x = detrend(x)
    filtered = bandpass(x, fs, config.complexity_band_hz, config.filter_order)
    spectral_input = notch(x, fs, config.notch_hz, config.notch_quality)
    freqs, psd = welch(
        spectral_input,
        fs=fs,
        nperseg=min(x.size, int(round(config.welch_seconds * fs))),
        scaling="density",
    )

    metrics: Dict[str, float] = {
        "lzc": lempel_ziv_complexity(filtered),
        "sample_entropy": sample_entropy(
            filtered, m=config.sample_entropy_m, r_factor=config.sample_entropy_r
        ),
        "permutation_entropy": permutation_entropy(
            filtered, order=config.permutation_order, delay=config.permutation_delay
        ),
        "spectral_entropy": spectral_entropy(freqs, psd, config.spectral_entropy_band_hz),
    }
    metrics["hjorth_mobility"], metrics["hjorth_complexity"] = hjorth_parameters(filtered)
    for low, high in config.aperiodic_ranges_hz:
        fit = aperiodic_fit(
            freqs,
            psd,
            (low, high),
            peak_threshold_sigma=config.aperiodic_peak_threshold_sigma,
            max_iterations=config.aperiodic_max_iterations,
        )
        suffix = f"{_fmt_hz(low)}_{_fmt_hz(high)}"
        metrics[f"aperiodic_exponent_{suffix}"] = fit["exponent"]
        metrics[f"aperiodic_offset_{suffix}"] = fit["offset"]
    metrics["lyapunov_max"] = (
        lyapunov_rosenstein(
            filtered,
            fs=fs,
            embedding_dimension=config.lyapunov_embedding_dimension,
            delay_samples=config.lyapunov_delay_samples,
            theiler_samples=config.lyapunov_theiler_samples,
            trajectory_samples=config.lyapunov_trajectory_samples,
        )
        if config.lyapunov_enabled
        else math.nan
    )

    band_powers = {band: band_power(freqs, psd, low, high) for band, (low, high) in config.bands.items()}
    total = sum(value for value in band_powers.values() if math.isfinite(value))
    for band in ("delta", "theta", "alpha", "beta", "gamma"):
        metrics[f"band_power_{band}"] = band_powers.get(band, math.nan)
    metrics["relative_power_alpha"] = _ratio(band_powers.get("alpha", math.nan), total)
    metrics["relative_power_gamma"] = _ratio(band_powers.get("gamma", math.nan), total)

    emg_low = band_power(freqs, psd, *config.emg_low_band_hz)
    metrics["emg_power_30_45"] = emg_low
    metrics["emg_power_30_45_rel"] = _ratio(emg_low, band_power(freqs, psd, *config.emg_reference_band_hz))
    emg_psd = bridge_lines(freqs, psd, config.emg_exclude_hz, config.emg_exclude_half_width_hz)
    metrics["emg_power_55_95"] = band_power(freqs, emg_psd, *config.emg_high_band_hz)
    metrics["emg_high_band_over_floor_db"] = _over_floor_db(
        freqs, emg_psd, config.emg_high_band_hz, config.emg_floor_band_hz
    )
    # Keep keys in EPOCH_METRICS order and fill anything a custom config skipped.
    return {metric: float(metrics.get(metric, math.nan)) for metric in EPOCH_METRICS}


# --- preprocessing -----------------------------------------------------------


def bandpass(x: np.ndarray, fs: float, band_hz: Tuple[float, float], order: int = 4) -> np.ndarray:
    sos = butter(order, band_hz, btype="bandpass", fs=fs, output="sos")
    return sosfiltfilt(sos, x)


def notch(x: np.ndarray, fs: float, notch_hz: Optional[float], quality: float) -> np.ndarray:
    if notch_hz is None or not 0 < notch_hz < fs / 2:
        return x
    b, a = iirnotch(notch_hz, quality, fs=fs)
    return filtfilt(b, a, x)


# --- complexity --------------------------------------------------------------


def lempel_ziv_complexity(x: np.ndarray) -> float:
    """LZ76 on the median-binarized signal, normalized by n / log2(n)."""
    x = np.asarray(x, dtype=float)
    n = x.size
    if n < 2:
        return math.nan
    symbols = (x > np.median(x)).astype(np.uint8).tobytes()
    return _lz76(symbols) * math.log2(n) / n


def _lz76(s: bytes) -> int:
    # Kaspar & Schuster 1987.
    n = len(s)
    c, l, i, k, k_max = 1, 1, 0, 1, 1
    while True:
        if s[i + k - 1] == s[l + k - 1]:
            k += 1
            if l + k > n:
                c += 1
                break
        else:
            if k > k_max:
                k_max = k
            i += 1
            if i == l:
                c += 1
                l += k_max
                if l + 1 > n:
                    break
                i, k, k_max = 0, 1, 1
            else:
                k = 1
    return c


def sample_entropy(x: np.ndarray, m: int = 2, r_factor: float = 0.2) -> float:
    """SampEn with Chebyshev distance and tolerance r = r_factor * std."""
    x = np.asarray(x, dtype=float)
    n = x.size
    r = r_factor * float(np.std(x))
    if n <= m + 2 or r <= 0:
        return math.nan
    # Same N - m templates for lengths m and m + 1.
    templates_m = np.lib.stride_tricks.sliding_window_view(x, m)[: n - m]
    templates_m1 = np.lib.stride_tricks.sliding_window_view(x, m + 1)
    b = _matching_pairs(templates_m, r)
    a = _matching_pairs(templates_m1, r)
    if a == 0 or b == 0:
        return math.nan
    return float(-math.log(a / b))


def _matching_pairs(templates: np.ndarray, r: float) -> int:
    tree = cKDTree(templates)
    # Ordered pairs within r, including each template with itself.
    count = int(tree.count_neighbors(tree, r, p=np.inf))
    return (count - len(templates)) // 2


def permutation_entropy(x: np.ndarray, order: int = 3, delay: int = 1) -> float:
    """Bandt-Pompe permutation entropy normalized to [0, 1]."""
    x = np.asarray(x, dtype=float)
    span = (order - 1) * delay + 1
    if x.size < span + 1:
        return math.nan
    embedded = np.lib.stride_tricks.sliding_window_view(x, span)[:, ::delay]
    ranks = np.argsort(embedded, axis=1, kind="stable")
    codes = ranks @ (order ** np.arange(order))
    _, counts = np.unique(codes, return_counts=True)
    p = counts / counts.sum()
    return float(-np.sum(p * np.log2(p)) / math.log2(math.factorial(order))) + 0.0


def spectral_entropy(freqs: np.ndarray, psd: np.ndarray, band_hz: Tuple[float, float]) -> float:
    mask = (freqs >= band_hz[0]) & (freqs <= band_hz[1])
    power = psd[mask]
    total = float(np.sum(power))
    if power.size < 2 or total <= 0:
        return math.nan
    p = power / total
    p = p[p > 0]
    return float(-np.sum(p * np.log2(p)) / math.log2(power.size))


def hjorth_parameters(x: np.ndarray) -> Tuple[float, float]:
    """Mobility and complexity with the derivative as np.diff (per sample)."""
    x = np.asarray(x, dtype=float)
    if x.size < 3:
        return math.nan, math.nan
    dx = np.diff(x)
    ddx = np.diff(dx)
    var_x, var_dx, var_ddx = float(np.var(x)), float(np.var(dx)), float(np.var(ddx))
    if var_x <= 0 or var_dx <= 0:
        return math.nan, math.nan
    mobility = math.sqrt(var_dx / var_x)
    return mobility, math.sqrt(var_ddx / var_dx) / mobility


# --- spectra -----------------------------------------------------------------


def band_power(freqs: np.ndarray, psd: np.ndarray, low_hz: float, high_hz: float) -> float:
    mask = (freqs >= low_hz) & (freqs < high_hz)
    if np.count_nonzero(mask) < 2:
        return math.nan
    return float(trapezoid(psd[mask], freqs[mask]))


def bridge_lines(
    freqs: np.ndarray,
    psd: np.ndarray,
    lines_hz: Sequence[float],
    half_width_hz: float,
) -> np.ndarray:
    """PSD with the bins within half_width_hz of each line interpolated from their neighbours."""
    covered = np.zeros(freqs.shape, dtype=bool)
    for line in lines_hz:
        covered |= np.abs(freqs - line) <= half_width_hz
    if not np.any(covered) or np.all(covered):
        return psd
    bridged = np.array(psd, dtype=float, copy=True)
    bridged[covered] = np.interp(freqs[covered], freqs[~covered], psd[~covered])
    return bridged


def _over_floor_db(
    freqs: np.ndarray,
    psd: np.ndarray,
    band_hz: Tuple[float, float],
    floor_hz: Tuple[float, float],
) -> float:
    band = (freqs >= band_hz[0]) & (freqs < band_hz[1])
    floor = (freqs >= floor_hz[0]) & (freqs < floor_hz[1])
    if not np.any(band) or not np.any(floor):
        return math.nan
    band_level, floor_level = float(np.mean(psd[band])), float(np.mean(psd[floor]))
    if band_level <= 0 or floor_level <= 0:
        return math.nan
    return 10.0 * math.log10(band_level / floor_level)


def aperiodic_fit(
    freqs: np.ndarray,
    psd: np.ndarray,
    range_hz: Tuple[float, float],
    peak_threshold_sigma: float = 2.0,
    max_iterations: int = 5,
    min_points: int = 5,
) -> Dict[str, float]:
    """Log-log line fit of the PSD with iterative exclusion of peaks.

    Fit, drop points whose positive residual exceeds peak_threshold_sigma
    robust standard deviations (oscillatory peaks sit above the 1/f line),
    refit until the kept set stops changing. exponent = -slope.
    """
    mask = (freqs >= range_hz[0]) & (freqs <= range_hz[1]) & (psd > 0)
    log_f = np.log10(freqs[mask])
    log_p = np.log10(psd[mask])
    nan = {"exponent": math.nan, "offset": math.nan, "points": 0.0}
    if log_f.size < min_points:
        return nan
    keep = np.ones(log_f.size, dtype=bool)
    slope, intercept = np.polyfit(log_f, log_p, 1)
    for _ in range(max_iterations):
        residual = log_p - (slope * log_f + intercept)
        kept = residual[keep]
        sigma = 1.4826 * float(np.median(np.abs(kept - np.median(kept))))
        if sigma <= 0:
            break
        new_keep = residual <= peak_threshold_sigma * sigma
        if np.count_nonzero(new_keep) < min_points or np.array_equal(new_keep, keep):
            break
        keep = new_keep
        slope, intercept = np.polyfit(log_f[keep], log_p[keep], 1)
    return {"exponent": float(-slope), "offset": float(intercept), "points": float(np.count_nonzero(keep))}


# --- chaoticity --------------------------------------------------------------


def lyapunov_rosenstein(
    x: np.ndarray,
    fs: float = 1.0,
    embedding_dimension: int = 7,
    delay_samples: int = 4,
    theiler_samples: int = 64,
    trajectory_samples: int = 32,
) -> float:
    """Largest Lyapunov exponent (Rosenstein 1993), per second when fs is given.

    Each embedded point is paired with its nearest neighbour outside the
    Theiler window; the slope of the mean log divergence over
    ``trajectory_samples`` steps is the exponent.
    """
    x = np.asarray(x, dtype=float)
    span = (embedding_dimension - 1) * delay_samples + 1
    if x.size < span + trajectory_samples + 2 * theiler_samples + 2:
        return math.nan
    embedded = np.lib.stride_tricks.sliding_window_view(x, span)[:, ::delay_samples]
    reference_count = embedded.shape[0] - trajectory_samples
    reference = embedded[:reference_count]
    norms = np.einsum("ij,ij->i", reference, reference)
    distances = norms[:, None] + norms[None, :] - 2.0 * (reference @ reference.T)
    index = np.arange(reference_count)
    distances[np.abs(index[:, None] - index[None, :]) <= theiler_samples] = np.inf
    neighbours = np.argmin(distances, axis=1)
    usable = np.isfinite(distances[index, neighbours])
    if not np.any(usable):
        return math.nan
    index, neighbours = index[usable], neighbours[usable]

    mean_log_divergence = []
    for step in range(trajectory_samples + 1):
        separation = np.linalg.norm(embedded[index + step] - embedded[neighbours + step], axis=1)
        separation = separation[separation > 0]
        mean_log_divergence.append(float(np.mean(np.log(separation))) if separation.size else math.nan)
    curve = np.asarray(mean_log_divergence)
    steps = np.arange(curve.size)
    finite = np.isfinite(curve)
    if np.count_nonzero(finite) < 2:
        return math.nan
    return float(np.polyfit(steps[finite], curve[finite], 1)[0] * fs)


# --- long-range temporal correlations ----------------------------------------


def dfa_exponent(x: np.ndarray, window_sizes: Sequence[int]) -> float:
    """Detrended fluctuation analysis exponent over the given window sizes."""
    x = np.asarray(x, dtype=float)
    profile = np.cumsum(x - np.mean(x))
    sizes: List[int] = []
    fluctuations: List[float] = []
    for size in sorted(set(int(size) for size in window_sizes)):
        segments = profile.size // size
        if size < 4 or segments < 2:
            continue
        windows = profile[: segments * size].reshape(segments, size)
        t = np.arange(size, dtype=float)
        slope, intercept = np.polyfit(t, windows.T, 1)
        residual = windows - (slope[:, None] * t[None, :] + intercept[:, None])
        sizes.append(size)
        fluctuations.append(float(np.sqrt(np.mean(residual ** 2))))
    if len(sizes) < 3 or min(fluctuations) <= 0:
        return math.nan
    return float(np.polyfit(np.log(sizes), np.log(fluctuations), 1)[0])


def dfa_window_sizes(n_samples: int, fs: float, config: ComplexityConfig) -> List[int]:
    low = int(round(config.dfa_min_window_seconds * fs))
    high = int(n_samples * config.dfa_max_window_fraction)
    if high <= low:
        return []
    return sorted(set(int(round(v)) for v in np.geomspace(low, high, config.dfa_window_count)))


def envelope_dfa(
    segments: Sequence[np.ndarray],
    band_hz: Tuple[float, float],
    config: ComplexityConfig,
) -> Dict[str, float]:
    """DFA of the band amplitude envelope over concatenated clean segments.

    Each segment is filtered and Hilbert-transformed on its own so the joins do
    not ring; segments shorter than dfa_min_segment_seconds are skipped.
    """
    fs = config.sample_rate_hz
    min_samples = int(config.dfa_min_segment_seconds * fs)
    envelopes = []
    for segment in segments:
        segment = np.asarray(segment, dtype=float)
        segment = segment[np.isfinite(segment)]
        if segment.size < min_samples:
            continue
        filtered = bandpass(detrend(segment), fs, band_hz, config.filter_order)
        envelopes.append(np.abs(hilbert(filtered)))
    empty = {"alpha": math.nan, "seconds": 0.0, "windows": 0.0, "min_window_s": math.nan, "max_window_s": math.nan}
    if not envelopes:
        return empty
    signal = np.concatenate(envelopes)
    sizes = dfa_window_sizes(signal.size, fs, config)
    if len(sizes) < 3:
        return {**empty, "seconds": signal.size / fs}
    return {
        "alpha": dfa_exponent(signal, sizes),
        "seconds": signal.size / fs,
        "windows": float(len(sizes)),
        "min_window_s": sizes[0] / fs,
        "max_window_s": sizes[-1] / fs,
    }


def block_dfa(
    channel_segments: Mapping[str, Sequence[np.ndarray]],
    config: ComplexityConfig,
) -> Dict[str, float]:
    """dfa_<band>_<channel|group> for one block, plus fit-range bookkeeping."""
    bands = dict(config.dfa_bands_hz)
    bands["broadband"] = config.dfa_broadband_hz
    values: Dict[str, float] = {}
    per_channel: Dict[str, Dict[str, float]] = {}
    for channel in config.channels:
        per_channel[channel] = {}
        for band, band_hz in bands.items():
            result = envelope_dfa(channel_segments.get(channel, ()), band_hz, config)
            per_channel[channel][band] = result["alpha"]
            values[f"dfa_{band}_{channel}"] = result["alpha"]
            if band == "broadband":
                values[f"dfa_seconds_{channel}"] = result["seconds"]
                values[f"dfa_windows_{channel}"] = result["windows"]
                values[f"dfa_min_window_s_{channel}"] = result["min_window_s"]
                values[f"dfa_max_window_s_{channel}"] = result["max_window_s"]
    for band in bands:
        for group, members in _channel_groups(config).items():
            values[f"dfa_{band}_{group}"] = _nanmean(per_channel[channel][band] for channel in members)
    return values


def dfa_metric_names(config: ComplexityConfig) -> Tuple[str, ...]:
    return tuple(f"dfa_{band}" for band in (*config.dfa_bands_hz, "broadband"))


# --- helpers -----------------------------------------------------------------


def _channel_groups(config: ComplexityConfig) -> Dict[str, Tuple[str, ...]]:
    return {
        "all": tuple(config.channels),
        "frontal": tuple(config.frontal_channels),
        "temporal": tuple(config.temporal_channels),
    }


def _nanmean(values) -> float:
    finite = [value for value in values if value is not None and math.isfinite(value)]
    return float(np.mean(finite)) if finite else math.nan


def _ratio(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator <= 0:
        return math.nan
    return float(numerator / denominator)


def _fmt_hz(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value).replace(".", "p")


def _jsonable(value):
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
