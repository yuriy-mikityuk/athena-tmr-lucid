import math
import unittest

import numpy as np

from muse_tmr.features.cardio_resp_features import (
    CardioRespConfig,
    correct_rr,
    detect_r_peaks,
    hrv_time_domain,
    respiration_from_acc,
    respiration_from_ecg,
    rr_spectrum,
)

from tests.polar_synthetic import ECG_FS, beat_times, chest_acc, ecg_signal


class RPeakTest(unittest.TestCase):
    def test_rr_from_130_hz_ecg_within_8_ms(self):
        rng = np.random.default_rng(1)
        beats = beat_times(180, rng)
        _t, ecg = ecg_signal(beats, 180, rng)
        positions, _amplitudes = detect_r_peaks(ecg, ECG_FS)
        detected = positions / ECG_FS
        self.assertEqual(detected.size, beats.size)
        matched = np.array([detected[np.argmin(np.abs(detected - beat))] for beat in beats])
        rr_error = np.abs(np.diff(matched) - np.diff(beats)) * 1000.0
        self.assertLess(rr_error.max(), 8.0)

    def test_inverted_lead_is_handled(self):
        rng = np.random.default_rng(2)
        beats = beat_times(60, rng)
        _t, ecg = ecg_signal(beats, 60, rng)
        positions, _ = detect_r_peaks(-ecg, ECG_FS)
        self.assertEqual(positions.size, beats.size)


class RRTest(unittest.TestCase):
    def test_ectopic_beats_flagged_counted_and_corrected(self):
        rng = np.random.default_rng(3)
        rr = 1000.0 + rng.normal(0, 15, 200)
        clean = rr.copy()
        for index in (50, 120):  # premature beat plus compensatory pause
            rr[index], rr[index + 1] = 650.0, 1350.0
        corrected, flagged = correct_rr(rr)
        self.assertEqual(set(np.flatnonzero(flagged)), {50, 51, 120, 121})
        self.assertAlmostEqual(100.0 * flagged.mean(), 2.0)
        self.assertLess(np.max(np.abs(corrected - clean)), 60.0)

    def test_out_of_range_beats_flagged(self):
        _corrected, flagged = correct_rr(np.array([1000.0, 1000.0, 250.0, 1000.0, 2500.0, 1000.0]))
        self.assertTrue(flagged[2] and flagged[4])

    def test_known_rmssd_reproduced(self):
        rr = np.tile([1000.0, 1040.0], 60)  # successive differences are all 40 ms
        metrics = hrv_time_domain(rr)
        self.assertAlmostEqual(metrics["rmssd_ms"], 40.0)
        self.assertAlmostEqual(metrics["pnn50_pct"], 0.0)
        self.assertAlmostEqual(metrics["sdnn_ms"], np.std(rr, ddof=1))
        self.assertAlmostEqual(metrics["mean_hr_bpm"], 60000.0 / 1020.0)

    def test_no_rmssd_on_short_windows(self):
        metrics = hrv_time_domain(np.full(10, 1000.0))
        self.assertTrue(math.isfinite(metrics["mean_hr_bpm"]))
        self.assertTrue(math.isnan(metrics["rmssd_ms"]))


class RespirationTest(unittest.TestCase):
    def test_acc_rate_at_6_and_15_breaths_per_minute(self):
        for breaths in (6.0, 15.0):
            rng = np.random.default_rng(int(breaths))
            t, xyz = chest_acc(180, rng, breaths)
            result = respiration_from_acc(t, xyz)
            self.assertAlmostEqual(result["rate_spectral_bpm"], breaths, delta=0.5)
            self.assertAlmostEqual(result["rate_breath_bpm"], breaths, delta=0.5)

    def test_edr_agrees_with_breathing(self):
        rng = np.random.default_rng(5)
        beats = beat_times(180, rng, breathing_hz=0.2)
        _t, ecg = ecg_signal(beats, 180, rng, breathing_hz=0.2)
        positions, amplitudes = detect_r_peaks(ecg, ECG_FS)
        result = respiration_from_ecg(positions / ECG_FS, amplitudes)
        self.assertAlmostEqual(result["rate_spectral_bpm"], 12.0, delta=0.5)

    def test_rsa_band_follows_slow_breathing_into_lf(self):
        rng = np.random.default_rng(6)
        beats = beat_times(300, rng, breathing_hz=0.1, rsa_s=0.05, jitter_s=0.003)
        rr = np.diff(beats) * 1000.0
        result = rr_spectrum(beats[1:], rr, 0.1)
        self.assertGreater(result["lf_power_ms2"], 5 * result["hf_power_ms2"])
        self.assertGreater(result["rsa_power_ms2"], 0.8 * result["lf_power_ms2"])
        self.assertAlmostEqual(result["rsa_band_low_hz"], 0.07)


if __name__ == "__main__":
    unittest.main()
