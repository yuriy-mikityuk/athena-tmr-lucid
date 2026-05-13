"""EEG sleep feature extraction for SleepEpoch windows."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid
from scipy.signal import welch

from muse_tmr.features.epochs import SleepEpoch

EEG_BANDS = {
    "delta": (0.5, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 12.0),
    "beta": (12.0, 30.0),
    "gamma": (30.0, 45.0),
}


@dataclass(frozen=True)
class EEGFeatureConfig:
    sample_rate_hz: float = 256.0
    bands: Mapping[str, Tuple[float, float]] = field(default_factory=lambda: dict(EEG_BANDS))
    artifact_abs_uv_threshold: float = 500.0
    artifact_clipping_fraction_threshold: float = 0.05
    flat_std_uv_threshold: float = 1e-6
    min_eeg_coverage: float = 0.5
    frontal_channels: Tuple[str, str] = ("AF7", "AF8")
    posterior_channels: Tuple[str, str] = ("TP9", "TP10")

    def validate(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if not 0 <= self.min_eeg_coverage <= 1:
            raise ValueError("min_eeg_coverage must be between 0 and 1")
        if not 0 < self.artifact_clipping_fraction_threshold <= 1:
            raise ValueError("artifact_clipping_fraction_threshold must be inside (0, 1]")
        for band_name, (low_hz, high_hz) in self.bands.items():
            if low_hz < 0 or high_hz <= low_hz:
                raise ValueError(f"invalid EEG band {band_name}")


@dataclass(frozen=True)
class EEGFeatureRow:
    epoch_index: int
    start_time: float
    end_time: float
    eeg_coverage: float
    sample_count: int
    channel_count: int
    channel_sample_counts: Mapping[str, int]
    band_powers: Mapping[str, float]
    relative_band_powers: Mapping[str, float]
    ratios: Mapping[str, float]
    asymmetry: Mapping[str, float]
    eye_movement_proxy: float
    artifact_flags: Tuple[str, ...]
    quality_flags: Tuple[str, ...]
    channel_diagnostics: Mapping[str, Mapping[str, float]] = field(default_factory=dict)

    @property
    def is_noisy(self) -> bool:
        return bool(self.artifact_flags)

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "epoch_index": self.epoch_index,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "eeg_coverage": self.eeg_coverage,
            "sample_count": self.sample_count,
            "channel_count": self.channel_count,
            "eye_movement_proxy": self.eye_movement_proxy,
            "is_noisy": self.is_noisy,
            "artifact_flags": ";".join(self.artifact_flags),
            "quality_flags": ";".join(self.quality_flags),
        }
        for channel, count in sorted(self.channel_sample_counts.items()):
            payload[f"channel_samples_{channel}"] = count
        for channel, diagnostics in sorted(self.channel_diagnostics.items()):
            for name, value in sorted(diagnostics.items()):
                payload[f"channel_{channel}_{name}"] = value
        for band, value in sorted(self.band_powers.items()):
            payload[f"band_power_{band}"] = value
        for band, value in sorted(self.relative_band_powers.items()):
            payload[f"relative_power_{band}"] = value
        for name, value in sorted(self.ratios.items()):
            payload[name] = value
        for name, value in sorted(self.asymmetry.items()):
            payload[name] = value
        return payload


def extract_eeg_features(
    epoch: SleepEpoch,
    config: Optional[EEGFeatureConfig] = None,
) -> EEGFeatureRow:
    config = config or EEGFeatureConfig()
    config.validate()

    channels = _collect_epoch_eeg(epoch)
    channel_sample_counts = {channel: int(values.size) for channel, values in channels.items()}
    sample_count = max(channel_sample_counts.values(), default=0)
    eeg_coverage = float(epoch.coverage.get("eeg", 0.0))
    quality_flags = tuple(flag for flag in epoch.quality_flags if "eeg" in flag)
    channel_diagnostics = _channel_diagnostics(channels, config)
    artifact_flags = _artifact_flags(
        channels=channels,
        channel_diagnostics=channel_diagnostics,
        eeg_coverage=eeg_coverage,
        quality_flags=quality_flags,
        config=config,
    )

    channel_band_powers = {
        channel: _channel_band_powers(values, config)
        for channel, values in channels.items()
        if values.size > 0
    }
    band_powers = _mean_band_powers(channel_band_powers, config.bands)
    total_power = _safe_sum(band_powers.values())
    relative_band_powers = {
        band: _safe_divide(value, total_power)
        for band, value in band_powers.items()
    }
    ratios = _ratios(band_powers)
    asymmetry = _asymmetry(channel_band_powers, config)
    eye_movement_proxy = _eye_movement_proxy(channels, config.frontal_channels)

    return EEGFeatureRow(
        epoch_index=epoch.index,
        start_time=epoch.start_time,
        end_time=epoch.end_time,
        eeg_coverage=eeg_coverage,
        sample_count=sample_count,
        channel_count=len(channels),
        channel_sample_counts=channel_sample_counts,
        band_powers=band_powers,
        relative_band_powers=relative_band_powers,
        ratios=ratios,
        asymmetry=asymmetry,
        eye_movement_proxy=eye_movement_proxy,
        artifact_flags=artifact_flags,
        quality_flags=quality_flags,
        channel_diagnostics=channel_diagnostics,
    )


def extract_eeg_feature_rows(
    epochs: Iterable[SleepEpoch],
    config: Optional[EEGFeatureConfig] = None,
) -> Tuple[EEGFeatureRow, ...]:
    return tuple(extract_eeg_features(epoch, config=config) for epoch in epochs)


def export_eeg_feature_rows(rows: Sequence[EEGFeatureRow], output_path: Path) -> Path:
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([row.to_dict() for row in rows])

    suffix = output_path.suffix.lower()
    if suffix == ".csv":
        frame.to_csv(output_path, index=False)
    elif suffix in {".parquet", ".pq"}:
        frame.to_parquet(output_path, index=False)
    else:
        raise ValueError("EEG feature export path must end with .csv, .parquet, or .pq")
    return output_path


def _collect_epoch_eeg(epoch: SleepEpoch) -> Mapping[str, np.ndarray]:
    channel_values: Dict[str, list] = {}
    for frame in epoch.frames:
        if frame.eeg is None:
            continue
        for channel, values in frame.eeg.channels_uv.items():
            channel_values.setdefault(channel, []).extend(values)
    return {
        channel: np.asarray(values, dtype=float)
        for channel, values in channel_values.items()
    }


def _channel_band_powers(values: np.ndarray, config: EEGFeatureConfig) -> Mapping[str, float]:
    finite_values = values[np.isfinite(values)]
    if finite_values.size < 4:
        return {band: math.nan for band in config.bands}

    signal = finite_values - np.mean(finite_values)
    if np.std(signal) <= 0:
        return {band: 0.0 for band in config.bands}

    nperseg = min(finite_values.size, int(config.sample_rate_hz * 4))
    freqs, psd = welch(
        signal,
        fs=config.sample_rate_hz,
        nperseg=max(4, nperseg),
        scaling="density",
    )
    return {
        band: _integrate_band_power(freqs, psd, low_hz, high_hz)
        for band, (low_hz, high_hz) in config.bands.items()
    }


def _integrate_band_power(
    freqs: np.ndarray,
    psd: np.ndarray,
    low_hz: float,
    high_hz: float,
) -> float:
    mask = (freqs >= low_hz) & (freqs < high_hz)
    if not np.any(mask):
        return 0.0
    return float(trapezoid(psd[mask], freqs[mask]))


def _mean_band_powers(
    channel_band_powers: Mapping[str, Mapping[str, float]],
    bands: Mapping[str, Tuple[float, float]],
) -> Mapping[str, float]:
    averaged = {}
    for band in bands:
        values = [
            powers[band]
            for powers in channel_band_powers.values()
            if band in powers and math.isfinite(powers[band])
        ]
        averaged[band] = float(np.mean(values)) if values else math.nan
    return averaged


def _ratios(band_powers: Mapping[str, float]) -> Mapping[str, float]:
    delta = band_powers.get("delta", math.nan)
    theta = band_powers.get("theta", math.nan)
    alpha = band_powers.get("alpha", math.nan)
    beta = band_powers.get("beta", math.nan)
    gamma = band_powers.get("gamma", math.nan)
    return {
        "theta_alpha_ratio": _safe_divide(theta, alpha),
        "delta_beta_ratio": _safe_divide(delta, beta),
        "slow_fast_ratio": _safe_divide(delta + theta, beta + gamma),
    }


def _asymmetry(
    channel_band_powers: Mapping[str, Mapping[str, float]],
    config: EEGFeatureConfig,
) -> Mapping[str, float]:
    features = {}
    left_frontal, right_frontal = config.frontal_channels
    left_posterior, right_posterior = config.posterior_channels
    features["alpha_asymmetry_af8_af7"] = _log_power_difference(
        channel_band_powers,
        right_frontal,
        left_frontal,
        "alpha",
    )
    features["theta_asymmetry_af8_af7"] = _log_power_difference(
        channel_band_powers,
        right_frontal,
        left_frontal,
        "theta",
    )
    features["alpha_asymmetry_tp10_tp9"] = _log_power_difference(
        channel_band_powers,
        right_posterior,
        left_posterior,
        "alpha",
    )
    return features


def _log_power_difference(
    channel_band_powers: Mapping[str, Mapping[str, float]],
    right_channel: str,
    left_channel: str,
    band: str,
) -> float:
    right = channel_band_powers.get(right_channel, {}).get(band, math.nan)
    left = channel_band_powers.get(left_channel, {}).get(band, math.nan)
    if not math.isfinite(right) or not math.isfinite(left) or right <= 0 or left <= 0:
        return math.nan
    return float(math.log(right) - math.log(left))


def _eye_movement_proxy(
    channels: Mapping[str, np.ndarray],
    frontal_channels: Tuple[str, str],
) -> float:
    left, right = frontal_channels
    left_values = channels.get(left)
    right_values = channels.get(right)
    if left_values is None or right_values is None:
        return math.nan

    sample_count = min(left_values.size, right_values.size)
    if sample_count < 2:
        return math.nan

    frontal_difference = left_values[:sample_count] - right_values[:sample_count]
    return float(np.mean(np.abs(np.diff(frontal_difference))))


def _artifact_flags(
    channels: Mapping[str, np.ndarray],
    channel_diagnostics: Mapping[str, Mapping[str, float]],
    eeg_coverage: float,
    quality_flags: Tuple[str, ...],
    config: EEGFeatureConfig,
) -> Tuple[str, ...]:
    flags = set(quality_flags)
    if not channels:
        flags.add("eeg_missing")
        return tuple(sorted(flags))
    if eeg_coverage < config.min_eeg_coverage:
        flags.add("low_eeg_coverage")

    for channel, values in channels.items():
        if values.size == 0:
            flags.add(f"eeg_empty_{channel}")
            continue
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            flags.add(f"eeg_nonfinite_{channel}")
            continue
        diagnostics = channel_diagnostics.get(channel, {})
        over_threshold_fraction = float(
            diagnostics.get("centered_abs_over_threshold_fraction", math.nan)
        )
        if (
            math.isfinite(over_threshold_fraction)
            and over_threshold_fraction >= config.artifact_clipping_fraction_threshold
        ):
            flags.add(f"eeg_clipping_{channel}")
        if float(np.std(finite)) <= config.flat_std_uv_threshold:
            flags.add(f"eeg_flatline_{channel}")
    return tuple(sorted(flags))


def _channel_diagnostics(
    channels: Mapping[str, np.ndarray],
    config: EEGFeatureConfig,
) -> Mapping[str, Mapping[str, float]]:
    diagnostics: Dict[str, Mapping[str, float]] = {}
    for channel, values in channels.items():
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            diagnostics[channel] = {
                "finite_sample_count": 0.0,
                "min_uv": math.nan,
                "max_uv": math.nan,
                "mean_uv": math.nan,
                "median_uv": math.nan,
                "peak_to_peak_uv": math.nan,
                "centered_abs_max_uv": math.nan,
                "centered_abs_p95_uv": math.nan,
                "centered_abs_over_threshold_fraction": math.nan,
            }
            continue

        median = float(np.median(finite))
        centered_abs = np.abs(finite - median)
        diagnostics[channel] = {
            "finite_sample_count": float(finite.size),
            "min_uv": float(np.min(finite)),
            "max_uv": float(np.max(finite)),
            "mean_uv": float(np.mean(finite)),
            "median_uv": median,
            "peak_to_peak_uv": float(np.ptp(finite)),
            "centered_abs_max_uv": float(np.max(centered_abs)),
            "centered_abs_p95_uv": float(np.percentile(centered_abs, 95)),
            "centered_abs_over_threshold_fraction": float(
                np.mean(centered_abs >= config.artifact_abs_uv_threshold)
            ),
        }
    return diagnostics


def _safe_sum(values: Iterable[float]) -> float:
    finite_values = [value for value in values if math.isfinite(value)]
    return float(sum(finite_values)) if finite_values else math.nan


def _safe_divide(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator <= 0:
        return math.nan
    return float(numerator / denominator)
