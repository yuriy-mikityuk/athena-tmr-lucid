"""Beat-level cardio and respiration features from a Polar H10 chest strap.

ECG R-peaks, RR artifact correction, time-domain HRV, respiration rate from
chest acceleration (cross-checked against ECG-derived respiration), and RSA
measured around the actual breathing frequency. Classic HF (0.15-0.4 Hz)
assumes breathing faster than 9 breaths/min; during slow meditative breathing
the RSA moves into LF, so HF/LF are only reported next to the measured rate.

Not wired into REM detection, the gate, the arousal guard or audio.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Dict, Optional, Tuple

import numpy as np
from scipy.integrate import trapezoid
from scipy.interpolate import CubicSpline
from scipy.signal import butter, find_peaks, sosfiltfilt, welch


@dataclass(frozen=True)
class CardioRespConfig:
    ecg_rate_hz: float = 130.0
    qrs_band_hz: Tuple[float, float] = (5.0, 25.0)
    min_rr_ms: float = 300.0
    max_rr_ms: float = 2000.0
    # A beat is flagged when it is outside [min_rr, max_rr] or differs from the
    # median of the surrounding beats by more than this fraction.
    rr_correction_threshold: float = 0.2
    rr_correction_window_beats: int = 11
    hrv_min_seconds: float = 60.0
    respiration_band_hz: Tuple[float, float] = (0.05, 0.7)
    respiration_resample_hz: float = 10.0
    respiration_min_seconds: float = 30.0
    min_breath_seconds: float = 1.2
    rr_resample_hz: float = 4.0
    lf_band_hz: Tuple[float, float] = (0.04, 0.15)
    hf_band_hz: Tuple[float, float] = (0.15, 0.4)
    rsa_half_band_hz: float = 0.03
    hf_valid_min_breaths_per_min: float = 9.0

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


# --- ECG ---------------------------------------------------------------------


def detect_r_peaks(
    ecg_uv: np.ndarray,
    fs: float = 130.0,
    config: Optional[CardioRespConfig] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """R-peak positions (fractional sample index) and amplitudes.

    Detection on a QRS band-pass with an adaptive threshold; each peak is then
    refined on the 0.5 Hz high-passed ECG with a parabola through the apex and
    its two neighbours, since 130 Hz alone only resolves ~7.7 ms.
    """
    config = config or CardioRespConfig()
    x = _fill_nan(np.asarray(ecg_uv, dtype=float))
    if x.size < int(2 * fs):
        return np.array([]), np.array([])
    baseline_free = sosfiltfilt(butter(2, 0.5, btype="highpass", fs=fs, output="sos"), x)
    qrs = sosfiltfilt(butter(3, config.qrs_band_hz, btype="bandpass", fs=fs, output="sos"), x)
    if abs(np.percentile(qrs, 0.5)) > abs(np.percentile(qrs, 99.5)):
        qrs, baseline_free = -qrs, -baseline_free  # inverted lead placement

    window = int(2 * fs)
    maxima = [qrs[start : start + window].max() for start in range(0, qrs.size - window + 1, window)]
    threshold = 0.4 * float(np.median(maxima)) if maxima else float(qrs.max())
    distance = max(1, int(config.min_rr_ms / 1000.0 * fs))
    candidates, _ = find_peaks(qrs, height=threshold, distance=distance)

    half = max(1, int(round(0.04 * fs)))
    positions, amplitudes = [], []
    for candidate in candidates:
        low, high = max(1, candidate - half), min(x.size - 1, candidate + half + 1)
        apex = low + int(np.argmax(baseline_free[low:high]))
        if apex <= 0 or apex >= x.size - 1:
            continue
        before, peak, after = baseline_free[apex - 1], baseline_free[apex], baseline_free[apex + 1]
        denominator = before - 2 * peak + after
        shift = 0.5 * (before - after) / denominator if denominator < 0 else 0.0
        shift = float(np.clip(shift, -0.5, 0.5))
        positions.append(apex + shift)
        amplitudes.append(peak - 0.25 * (before - after) * shift)
    positions_array = np.asarray(positions)
    if positions_array.size:
        keep = np.concatenate(([True], np.diff(positions_array) > distance * 0.5))
        return positions_array[keep], np.asarray(amplitudes)[keep]
    return positions_array, np.asarray(amplitudes)


# --- RR ----------------------------------------------------------------------


def correct_rr(rr_ms: np.ndarray, config: Optional[CardioRespConfig] = None) -> Tuple[np.ndarray, np.ndarray]:
    """(corrected RR, flagged mask).

    Rule: a beat is flagged if it is outside [min_rr_ms, max_rr_ms] or deviates
    from the median of the surrounding ``rr_correction_window_beats`` beats by
    more than ``rr_correction_threshold``. Flagged beats are replaced by linear
    interpolation over beat index from unflagged neighbours. An ectopic beat
    usually flags as a short-long pair.
    """
    config = config or CardioRespConfig()
    rr = np.asarray(rr_ms, dtype=float)
    if rr.size == 0:
        return rr, np.zeros(0, dtype=bool)
    half = config.rr_correction_window_beats // 2
    flagged = (rr < config.min_rr_ms) | (rr > config.max_rr_ms) | ~np.isfinite(rr)
    plausible = np.where(flagged, np.nan, rr)
    for index in range(rr.size):
        neighbours = np.concatenate((plausible[max(0, index - half) : index], plausible[index + 1 : index + half + 1]))
        neighbours = neighbours[np.isfinite(neighbours)]
        if neighbours.size >= 2:
            local = float(np.median(neighbours))
            if abs(rr[index] - local) > config.rr_correction_threshold * local:
                flagged[index] = True
    corrected = rr.copy()
    good = ~flagged
    if good.sum() >= 2 and flagged.any():
        indices = np.arange(rr.size)
        corrected[flagged] = np.interp(indices[flagged], indices[good], rr[good])
    return corrected, flagged


def hrv_time_domain(rr_ms: np.ndarray, config: Optional[CardioRespConfig] = None) -> Dict[str, float]:
    """Mean HR always; RMSSD, SDNN and pNN50 only for windows >= hrv_min_seconds."""
    config = config or CardioRespConfig()
    rr = np.asarray(rr_ms, dtype=float)
    rr = rr[np.isfinite(rr)]
    result = {"beats": float(rr.size), "mean_hr_bpm": math.nan, "rmssd_ms": math.nan, "sdnn_ms": math.nan, "pnn50_pct": math.nan}
    if rr.size >= 2:
        result["mean_hr_bpm"] = 60000.0 / float(np.mean(rr))
    if rr.size >= 3 and rr.sum() / 1000.0 >= config.hrv_min_seconds:
        differences = np.diff(rr)
        result["rmssd_ms"] = float(np.sqrt(np.mean(differences ** 2)))
        result["sdnn_ms"] = float(np.std(rr, ddof=1))
        result["pnn50_pct"] = float(100.0 * np.mean(np.abs(differences) > 50.0))
    return result


def rr_spectrum(
    beat_times_s: np.ndarray,
    rr_ms: np.ndarray,
    breathing_hz: Optional[float],
    config: Optional[CardioRespConfig] = None,
) -> Dict[str, float]:
    """LF/HF power plus RSA power in a band centred on the measured breathing rate."""
    config = config or CardioRespConfig()
    nan = {"lf_power_ms2": math.nan, "hf_power_ms2": math.nan, "rsa_power_ms2": math.nan, "rsa_band_low_hz": math.nan, "rsa_band_high_hz": math.nan}
    times = np.asarray(beat_times_s, dtype=float)
    rr = np.asarray(rr_ms, dtype=float)
    order = np.argsort(times, kind="stable")
    times, rr = times[order], rr[order]
    keep = np.concatenate(([True], np.diff(times) > 0)) & np.isfinite(rr)
    times, rr = times[keep], rr[keep]
    if times.size < 8 or times[-1] - times[0] < config.hrv_min_seconds:
        return nan
    grid = np.arange(times[0], times[-1], 1.0 / config.rr_resample_hz)
    series = CubicSpline(times, rr)(grid)
    series = series - np.polyval(np.polyfit(grid - grid[0], series, 1), grid - grid[0])
    nperseg = min(series.size, int(120 * config.rr_resample_hz))
    freqs, psd = welch(series, fs=config.rr_resample_hz, nperseg=nperseg, nfft=max(nperseg, 4096))
    result = {
        "lf_power_ms2": _band(freqs, psd, *config.lf_band_hz),
        "hf_power_ms2": _band(freqs, psd, *config.hf_band_hz),
        "rsa_power_ms2": math.nan,
        "rsa_band_low_hz": math.nan,
        "rsa_band_high_hz": math.nan,
    }
    if breathing_hz is not None and math.isfinite(breathing_hz):
        low = max(0.0, breathing_hz - config.rsa_half_band_hz)
        high = breathing_hz + config.rsa_half_band_hz
        result.update({"rsa_power_ms2": _band(freqs, psd, low, high), "rsa_band_low_hz": low, "rsa_band_high_hz": high})
    return result


# --- respiration -------------------------------------------------------------


def respiration_from_acc(
    times_s: np.ndarray,
    xyz_mg: np.ndarray,
    config: Optional[CardioRespConfig] = None,
) -> Dict[str, float]:
    """Breathing rate from chest acceleration.

    Resample to a uniform grid, band-pass 0.05-0.7 Hz (removes gravity and
    posture drift), take the first principal component of the three axes, then
    report the spectral peak and the breath-by-breath median rate.
    """
    config = config or CardioRespConfig()
    times = np.asarray(times_s, dtype=float)
    xyz = np.asarray(xyz_mg, dtype=float)
    fs = config.respiration_resample_hz
    nan = {"rate_spectral_bpm": math.nan, "rate_breath_bpm": math.nan, "breaths": 0.0, "seconds": 0.0}
    if times.size < 10 or times[-1] - times[0] < config.respiration_min_seconds:
        return {**nan, "seconds": float(times[-1] - times[0]) if times.size else 0.0}
    grid = np.arange(times[0], times[-1], 1.0 / fs)
    resampled = np.column_stack([np.interp(grid, times, xyz[:, axis]) for axis in range(xyz.shape[1])])
    sos = butter(2, config.respiration_band_hz, btype="bandpass", fs=fs, output="sos")
    filtered = sosfiltfilt(sos, resampled - resampled.mean(axis=0), axis=0)
    _values, vectors = np.linalg.eigh(np.cov(filtered.T))
    component = filtered @ vectors[:, -1]
    return {**_respiration_rates(component, fs, config), "seconds": float(grid[-1] - grid[0])}


def respiration_from_ecg(
    r_peak_times_s: np.ndarray,
    r_amplitudes: np.ndarray,
    config: Optional[CardioRespConfig] = None,
) -> Dict[str, float]:
    """ECG-derived respiration from R-amplitude modulation, for cross-checking."""
    config = config or CardioRespConfig()
    times = np.asarray(r_peak_times_s, dtype=float)
    amplitudes = np.asarray(r_amplitudes, dtype=float)
    nan = {"rate_spectral_bpm": math.nan, "rate_breath_bpm": math.nan, "breaths": 0.0}
    if times.size < 8 or times[-1] - times[0] < config.respiration_min_seconds:
        return nan
    fs = config.rr_resample_hz
    grid = np.arange(times[0], times[-1], 1.0 / fs)
    series = CubicSpline(times, amplitudes)(grid)
    sos = butter(2, config.respiration_band_hz, btype="bandpass", fs=fs, output="sos")
    return _respiration_rates(sosfiltfilt(sos, series - series.mean()), fs, config)


def _respiration_rates(signal: np.ndarray, fs: float, config: CardioRespConfig) -> Dict[str, float]:
    nperseg = min(signal.size, int(120 * fs))
    freqs, psd = welch(signal, fs=fs, nperseg=nperseg, nfft=max(nperseg, 16384))
    band = (freqs >= config.respiration_band_hz[0]) & (freqs <= config.respiration_band_hz[1])
    rate_spectral = math.nan
    if np.any(band) and psd[band].max() > 0:
        index = np.flatnonzero(band)[int(np.argmax(psd[band]))]
        rate_spectral = 60.0 * _parabolic_peak(freqs, psd, index)
    peaks, _ = find_peaks(
        signal,
        distance=max(1, int(config.min_breath_seconds * fs)),
        prominence=0.3 * float(np.std(signal)),
    )
    rate_breath = 60.0 * fs / float(np.median(np.diff(peaks))) if peaks.size >= 3 else math.nan
    return {"rate_spectral_bpm": rate_spectral, "rate_breath_bpm": rate_breath, "breaths": float(peaks.size)}


# --- windows -----------------------------------------------------------------


def extract_cardio_resp_features(
    session,
    start_time: float,
    end_time: float,
    config: Optional[CardioRespConfig] = None,
) -> Dict[str, float]:
    """Features for one window (epoch or block) of a loaded Polar session.

    ``session`` is a ``muse_tmr.data.polar_session.PolarSession``; times are
    host wall-clock seconds, the same base as Muse replay.
    """
    config = config or CardioRespConfig()
    features: Dict[str, float] = {"window_seconds": float(end_time - start_time)}

    rr = _between(session.rr, start_time, end_time)
    rr_values = rr["rr_ms"].to_numpy(dtype=float) if len(rr) else np.array([])
    corrected, flagged = correct_rr(rr_values, config)
    features["rr_corrected_pct"] = float(100.0 * flagged.mean()) if flagged.size else math.nan
    features.update(hrv_time_domain(corrected, config))
    if len(rr) and "ecg_rr_ms" in rr:
        matched = rr["ecg_rr_ms"].notna()
        features["ecg_rr_matched_pct"] = float(100.0 * matched.mean())
        differences = (rr.loc[matched, "rr_ms"] - rr.loc[matched, "ecg_rr_ms"]).abs()
        features["ecg_rr_agreement_ms"] = float(differences.median()) if len(differences) else math.nan

    acc = _between(session.acc, start_time, end_time)
    respiration = (
        respiration_from_acc(acc["time"].to_numpy(), acc[["x", "y", "z"]].to_numpy(), config)
        if len(acc)
        else {"rate_spectral_bpm": math.nan, "rate_breath_bpm": math.nan, "breaths": 0.0}
    )
    features["resp_rate_bpm"] = respiration["rate_spectral_bpm"]
    features["resp_rate_breath_bpm"] = respiration["rate_breath_bpm"]
    features["resp_breaths"] = respiration["breaths"]

    peaks = _between(session.r_peaks, start_time, end_time)
    edr = (
        respiration_from_ecg(peaks["time"].to_numpy(), peaks["amplitude"].to_numpy(), config)
        if len(peaks)
        else {"rate_spectral_bpm": math.nan}
    )
    features["edr_rate_bpm"] = edr["rate_spectral_bpm"]
    features["resp_acc_edr_diff_bpm"] = abs(features["resp_rate_bpm"] - features["edr_rate_bpm"])

    breathing_hz = features["resp_rate_bpm"] / 60.0 if math.isfinite(features["resp_rate_bpm"]) else None
    beat_times = rr["time"].to_numpy(dtype=float) if len(rr) else np.array([])
    features.update(rr_spectrum(beat_times, corrected, breathing_hz, config))
    # Classic HF assumes breathing above ~9/min; slower breathing puts RSA into LF.
    features["hf_band_valid"] = float(
        breathing_hz is not None and features["resp_rate_bpm"] >= config.hf_valid_min_breaths_per_min
    )
    return features


# --- helpers -----------------------------------------------------------------


def _between(frame, start_time: float, end_time: float):
    if frame is None or len(frame) == 0:
        return frame
    times = frame["time"]
    return frame[(times >= start_time) & (times < end_time)]


def _parabolic_peak(freqs: np.ndarray, psd: np.ndarray, index: int) -> float:
    if 0 < index < psd.size - 1:
        before, peak, after = psd[index - 1], psd[index], psd[index + 1]
        denominator = before - 2 * peak + after
        if denominator < 0:
            shift = 0.5 * (before - after) / denominator
            return float(freqs[index] + shift * (freqs[1] - freqs[0]))
    return float(freqs[index])


def _band(freqs: np.ndarray, psd: np.ndarray, low: float, high: float) -> float:
    mask = (freqs >= low) & (freqs < high)
    if np.count_nonzero(mask) < 2:
        return math.nan
    return float(trapezoid(psd[mask], freqs[mask]))


def _fill_nan(x: np.ndarray) -> np.ndarray:
    finite = np.isfinite(x)
    if finite.all() or not finite.any():
        return np.nan_to_num(x)
    indices = np.arange(x.size)
    return np.interp(indices, indices[finite], x[finite])
