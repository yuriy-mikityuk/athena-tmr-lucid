import importlib.util
import math
import unittest

import numpy as np

from muse_tmr.data.sample_types import EEGSample, MuseFrame
from muse_tmr.features.complexity_features import (
    EPOCH_METRICS,
    ComplexityConfig,
    aperiodic_fit,
    channel_metrics,
    dfa_exponent,
    dfa_window_sizes,
    envelope_dfa,
    extract_complexity_features,
    hjorth_parameters,
    lempel_ziv_complexity,
    lyapunov_rosenstein,
    permutation_entropy,
    sample_entropy,
)
from muse_tmr.features.epochs import SleepEpoch
from scipy.signal import welch

from tests.meditation_synthetic import FS, band_noise, pink_noise

HAS_ANTROPY = importlib.util.find_spec("antropy") is not None
HAS_NEUROKIT = importlib.util.find_spec("neurokit2") is not None


class ComplexityMetricTest(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(42)
        self.t = np.arange(2560) / FS
        self.noise = self.rng.standard_normal(2560)
        self.sine = np.sin(2 * np.pi * 10.0 * self.t)

    def test_lzc_sine_far_below_white_noise(self):
        noise_lzc = lempel_ziv_complexity(self.noise)
        self.assertLess(lempel_ziv_complexity(self.sine), 0.3 * noise_lzc)
        self.assertGreater(noise_lzc, 0.9)
        self.assertLess(noise_lzc, 1.15)

    def test_permutation_entropy_ramp_zero_noise_near_one(self):
        self.assertAlmostEqual(permutation_entropy(np.arange(200.0)), 0.0)
        self.assertGreater(permutation_entropy(self.noise), 0.98)

    def test_sample_entropy_sine_below_noise(self):
        self.assertLess(sample_entropy(self.sine), sample_entropy(self.noise))

    def test_hjorth_mobility_of_sampled_sine(self):
        for frequency in (3.0, 10.0, 25.0):
            signal = np.sin(2 * np.pi * frequency * self.t)
            mobility, _complexity = hjorth_parameters(signal)
            self.assertAlmostEqual(mobility, 2 * math.sin(math.pi * frequency / FS), places=3)

    def test_aperiodic_exponent_recovered_with_and_without_alpha_peak(self):
        n = int(60 * FS)
        for chi in (1.0, 2.0):
            background = pink_noise(n, chi, self.rng)
            with_peak = background + 1.5 * np.sin(2 * np.pi * 10.0 * np.arange(n) / FS)
            for signal in (background, with_peak):
                freqs, psd = welch(signal, fs=FS, nperseg=int(2 * FS))
                for fit_range in ((2.0, 20.0), (2.0, 40.0)):
                    fit = aperiodic_fit(freqs, psd, fit_range)
                    self.assertAlmostEqual(fit["exponent"], chi, delta=0.2, msg=(chi, fit_range))

    def test_peak_exclusion_matters_for_strong_peak(self):
        n = int(60 * FS)
        signal = pink_noise(n, 1.0, self.rng) + 3.0 * np.sin(2 * np.pi * 10.0 * np.arange(n) / FS)
        freqs, psd = welch(signal, fs=FS, nperseg=int(2 * FS))
        with_exclusion = aperiodic_fit(freqs, psd, (2.0, 20.0))
        without = aperiodic_fit(freqs, psd, (2.0, 20.0), max_iterations=0)
        self.assertLess(abs(with_exclusion["exponent"] - 1.0), abs(without["exponent"] - 1.0))

    def test_dfa_white_and_integrated_noise(self):
        noise = self.rng.standard_normal(20000)
        sizes = dfa_window_sizes(noise.size, FS, ComplexityConfig())
        self.assertAlmostEqual(dfa_exponent(noise, sizes), 0.5, delta=0.1)
        self.assertAlmostEqual(dfa_exponent(np.cumsum(noise), sizes), 1.5, delta=0.1)

    def test_envelope_dfa_reports_fit_range_and_skips_short_segments(self):
        config = ComplexityConfig()
        long_segment = 20.0 * self.rng.standard_normal(int(60 * FS))
        short_segment = 20.0 * self.rng.standard_normal(int(10 * FS))
        result = envelope_dfa([long_segment, short_segment], (8.0, 12.0), config)
        self.assertAlmostEqual(result["seconds"], 60.0, delta=0.01)
        self.assertGreaterEqual(result["windows"], 3)
        self.assertAlmostEqual(result["min_window_s"], 1.0, delta=0.01)
        self.assertTrue(math.isfinite(result["alpha"]))
        self.assertTrue(math.isnan(envelope_dfa([short_segment], (8.0, 12.0), config)["alpha"]))

    def test_lyapunov_signs(self):
        logistic = np.empty(3000)
        logistic[0] = 0.4
        for index in range(1, logistic.size):
            logistic[index] = 4.0 * logistic[index - 1] * (1.0 - logistic[index - 1])
        chaotic = lyapunov_rosenstein(
            logistic, fs=1.0, embedding_dimension=2, delay_samples=1, theiler_samples=1, trajectory_samples=4
        )
        self.assertGreater(chaotic, 0.3)
        sine = lyapunov_rosenstein(self.sine, fs=1.0)
        self.assertLess(abs(sine), 0.05)

    def test_emg_indicator_rises_with_60_90_hz_noise_not_with_alpha(self):
        config = ComplexityConfig()
        base = 20.0 * self.noise
        plain = channel_metrics(base, config)
        with_emg = channel_metrics(base + 20.0 * band_noise(base.size, (60.0, 90.0), self.rng), config)
        with_alpha = channel_metrics(base + 20.0 * self.sine, config)
        self.assertGreater(with_emg["emg_power_55_95"], 1.3 * plain["emg_power_55_95"])
        self.assertAlmostEqual(with_alpha["emg_power_55_95"], plain["emg_power_55_95"], delta=0.02 * plain["emg_power_55_95"])
        self.assertGreater(with_alpha["band_power_alpha"], 2.0 * plain["band_power_alpha"])

    def test_lyapunov_can_be_switched_off(self):
        metrics = channel_metrics(20.0 * self.noise, ComplexityConfig(lyapunov_enabled=False))
        self.assertTrue(math.isnan(metrics["lyapunov_max"]))
        self.assertTrue(math.isfinite(metrics["lzc"]))


class ExtractComplexityFeaturesTest(unittest.TestCase):
    def epoch(self, channels):
        frames = []
        n = len(next(iter(channels.values())))
        for offset in range(0, n, 12):
            timestamp = 100.0 + offset / FS
            frames.append(
                MuseFrame(
                    timestamp=timestamp,
                    eeg=EEGSample(
                        timestamp=timestamp,
                        channels_uv={name: tuple(values[offset : offset + 12]) for name, values in channels.items()},
                    ),
                    source="synthetic",
                )
            )
        return SleepEpoch(
            index=3,
            start_time=100.0,
            end_time=110.0,
            frames=tuple(frames),
            modality_counts={"eeg": len(frames)},
            sample_counts={"eeg": n},
            coverage={"eeg": 1.0},
            quality_flags=(),
        )

    def test_flags_bad_channel_and_keeps_it_out_of_group_means(self):
        rng = np.random.default_rng(0)
        n = 2556
        channels = {name: list(20.0 * rng.standard_normal(n)) for name in ("TP9", "AF7", "AF8")}
        channels["TP10"] = [5.0] * n  # flatline
        row = extract_complexity_features(self.epoch(channels))

        self.assertTrue(row.is_artifact)
        self.assertIn("eeg_flatline_TP10", row.artifact_flags)
        self.assertEqual(row.bad_channels, ("TP10",))
        self.assertTrue(math.isnan(row.values["lzc_TP10"]))
        self.assertAlmostEqual(row.values["lzc_temporal"], row.values["lzc_TP9"])
        expected_all = np.mean([row.values[f"lzc_{name}"] for name in ("TP9", "AF7", "AF8")])
        self.assertAlmostEqual(row.values["lzc_all"], expected_all)
        for metric in EPOCH_METRICS:
            self.assertIn(f"{metric}_frontal", row.values)


@unittest.skipUnless(HAS_ANTROPY, "antropy not installed")
class AntropyCrossCheckTest(unittest.TestCase):
    def test_matches_antropy(self):
        import antropy

        rng = np.random.default_rng(7)
        signal = rng.standard_normal(2560)
        self.assertAlmostEqual(
            permutation_entropy(signal, order=3, delay=1),
            antropy.perm_entropy(signal, order=3, delay=1, normalize=True),
            places=6,
        )
        self.assertAlmostEqual(sample_entropy(signal), antropy.sample_entropy(signal, order=2), delta=0.05)
        self.assertAlmostEqual(
            lempel_ziv_complexity(signal),
            antropy.lziv_complexity(signal > np.median(signal), normalize=True),
            delta=0.05,
        )


@unittest.skipUnless(HAS_NEUROKIT, "neurokit2 not installed")
class NeurokitCrossCheckTest(unittest.TestCase):
    def test_matches_neurokit(self):
        import neurokit2 as nk

        rng = np.random.default_rng(7)
        signal = rng.standard_normal(2560)
        pe, _ = nk.entropy_permutation(signal, dimension=3, delay=1)
        self.assertAlmostEqual(permutation_entropy(signal), pe, delta=0.02)
        sampen, _ = nk.entropy_sample(signal, dimension=2, tolerance=0.2 * np.std(signal))
        self.assertAlmostEqual(sample_entropy(signal), sampen, delta=0.05)


if __name__ == "__main__":
    unittest.main()
