import asyncio
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from muse_tmr.features.complexity_features import ComplexityConfig
from muse_tmr.reports.meditation_analysis import (
    MeditationAnalysisConfig,
    MeditationBlocks,
    aggregate_meditation_summaries,
    analyze_meditation_frames,
    assign_block,
    bootstrap_ci,
    build_meditation_plan,
    load_meditation_blocks,
    sign_flip_p_value,
    write_meditation_blocks,
)

from tests.meditation_synthetic import (
    FS,
    aiter_frames,
    band_noise,
    condition_signal,
    pink_noise,
    session_frames,
)

FAST = ComplexityConfig(lyapunov_enabled=False)


def contrast(summary, metric, group="all", variant="clean"):
    for item in summary["contrasts"]:
        if (item["metric"], item["group"], item["variant"]) == (metric, group, variant):
            return item
    raise KeyError(metric)


def residualized(summary, metric, group="all", variant="clean"):
    for item in summary["emg"]["residualized_contrasts"]:
        if (item["metric"], item["group"], item["variant"]) == (metric, group, variant):
            return item
    raise KeyError(metric)


class MeditationPlanTest(unittest.TestCase):
    def test_plan_is_deterministic_and_counterbalanced(self):
        first = build_meditation_plan(["focus", "open"], blocks=4, block_minutes=8, settle_seconds=60, seed=3)
        again = build_meditation_plan(["focus", "open"], blocks=4, block_minutes=8, settle_seconds=60, seed=3)
        self.assertEqual(first, again)
        self.assertIn(first.order, (("focus", "open", "focus", "open"), ("open", "focus", "open", "focus")))
        orders = {build_meditation_plan(["focus", "open"], seed=seed).order for seed in range(20)}
        self.assertEqual(len(orders), 2)
        self.assertEqual([block.start_s for block in first.blocks], [60.0, 540.0, 1020.0, 1500.0])
        self.assertTrue(all(block.depth is None and block.sensory_fading is None for block in first.blocks))

    def test_json_round_trip(self):
        plan = build_meditation_plan(["focus", "open"], seed=11)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_meditation_blocks(plan, Path(tmp) / "blocks.json")
            payload = json.loads(path.read_text())
            self.assertEqual(payload["time_base"], "seconds_from_recording_start")
            self.assertEqual(payload["blocks"][0]["depth"], None)
            self.assertEqual(load_meditation_blocks(path), plan)

    def test_rejects_bad_plans(self):
        with self.assertRaises(ValueError):
            build_meditation_plan(["focus"], seed=1)
        with self.assertRaises(ValueError):
            build_meditation_plan(["focus", "focus"], seed=1)
        overlapping = {
            "schema_version": 1,
            "time_base": "seconds_from_recording_start",
            "blocks": [
                {"index": 0, "condition": "a", "start_s": 0, "end_s": 100},
                {"index": 1, "condition": "b", "start_s": 50, "end_s": 150},
            ],
        }
        with self.assertRaises(ValueError):
            MeditationBlocks.from_dict(overlapping)

    def test_epochs_mapped_to_blocks_with_trim_and_settle(self):
        plan = build_meditation_plan(["a", "b"], blocks=2, block_minutes=2, settle_seconds=60, seed=0)
        first, second = plan.blocks
        self.assertIsNone(assign_block(0, 10, plan, 30))  # settle
        self.assertIsNone(assign_block(60, 70, plan, 30))  # trimmed block start
        self.assertIsNone(assign_block(80, 90, plan, 30))
        self.assertEqual(assign_block(90, 100, plan, 30), first)
        self.assertIsNone(assign_block(175, 185, plan, 30))  # straddles the boundary
        self.assertEqual(assign_block(210, 220, plan, 30), second)
        self.assertIsNone(assign_block(300, 310, plan, 30))  # after the last block


class MeditationAnalysisEndToEndTest(unittest.TestCase):
    def analyze(self, plan, signal_for, config=None, seed=5):
        rng = np.random.default_rng(seed)
        frames = session_frames(plan, signal_for, rng)
        config = config or MeditationAnalysisConfig(emg_indicator="emg_power_55_95", complexity=FAST)
        return asyncio.run(analyze_meditation_frames(aiter_frames(frames), plan, config, recording="synthetic"))

    def test_conditions_that_differ_by_construction_give_expected_signs(self):
        plan = build_meditation_plan(["busy", "calm"], blocks=4, block_minutes=2, settle_seconds=20, seed=2)

        def signal_for(condition, seconds, rng):
            return condition_signal("busy" if condition == "settle" else condition, seconds, rng)

        analysis = self.analyze(plan, signal_for)
        summary = analysis.summary

        self.assertEqual(summary["conditions"], ["busy", "calm"])
        self.assertEqual(summary["counts"]["blocks_with_epochs"], 4)
        lzc = contrast(summary, "lzc")
        self.assertTrue(lzc["primary"])
        primaries = [item for item in summary["contrasts"] if item["primary"]]
        self.assertEqual(len(primaries), 1)
        self.assertFalse(contrast(summary, "lzc", variant="all")["primary"])
        self.assertFalse(any(item["primary"] for item in summary["emg"]["residualized_contrasts"]))
        self.assertGreater(lzc["difference"], 0.2)
        self.assertGreater(contrast(summary, "permutation_entropy")["difference"], 0)
        self.assertLess(contrast(summary, "aperiodic_exponent_2_40")["difference"], -0.5)
        self.assertLess(contrast(summary, "band_power_alpha")["difference"], 0)
        self.assertEqual(contrast(summary, "sample_entropy")["label"], "exploratory")
        self.assertTrue(math.isfinite(contrast(summary, "dfa_alpha")["a_mean"]))
        self.assertEqual(set(analysis.blocks["variant"]), {"all", "clean"})
        self.assertEqual(len(analysis.blocks), 8)
        # 2 min blocks minus 30 s trim = 9 epochs of 10 s each.
        self.assertEqual(len(analysis.epochs), 4 * 9)

        with tempfile.TemporaryDirectory() as tmp:
            paths = analysis.write(Path(tmp))
            written = json.loads(paths["summary"].read_text())
            self.assertIn("limitations", written)
            self.assertEqual(written["primary_metric"]["metric"], "lzc")
            self.assertIn("lyapunov_enabled", written["config"]["complexity"])
            self.assertTrue(paths["epochs"].exists() and paths["blocks"].exists())

    def test_emg_only_difference_is_flagged_and_residualized_contrast_shrinks(self):
        # B is A plus broadband EMG-like 30-95 Hz bursts. Pure 60-90 Hz noise
        # cannot move the 0.5-40 Hz complexity metrics, real EMG is broadband.
        plan = build_meditation_plan(["relaxed", "tense"], blocks=4, block_minutes=2, settle_seconds=20, seed=4)

        def signal_for(condition, seconds, rng):
            emg = 12.0 if condition == "tense" else 0.0
            return condition_signal("busy", seconds, rng, emg_uv=emg)

        summary = self.analyze(plan, signal_for).summary
        emg = summary["emg"]
        self.assertEqual(emg["indicator"], "emg_power_55_95")
        self.assertTrue(emg["emg_confounded"])
        self.assertLess(emg["condition_difference"]["clean"]["difference_log10"], -0.1)

        raw = residualized(summary, "lzc")
        self.assertLess(raw["raw_difference"], 0)  # tense has higher LZC
        self.assertLess(abs(raw["residualized_difference"]), 0.5 * abs(raw["raw_difference"]))
        rho = next(
            item["spearman_rho"]
            for item in emg["correlations"]
            if (item["metric"], item["group"], item["variant"]) == ("lzc", "all", "clean")
        )
        self.assertGreater(rho, 0.5)

    def test_no_emg_difference_is_not_flagged(self):
        plan = build_meditation_plan(["a", "b"], blocks=4, block_minutes=2, settle_seconds=20, seed=6)

        def signal_for(condition, seconds, rng):
            signal = condition_signal("busy", seconds, rng)
            if condition == "b":
                t = np.arange(int(seconds * FS)) / FS
                signal = {name: values + 15.0 * np.sin(2 * np.pi * 10.0 * t) for name, values in signal.items()}
            return signal

        summary = self.analyze(plan, signal_for).summary
        self.assertFalse(summary["emg"]["emg_confounded"])
        self.assertLess(contrast(summary, "band_power_alpha")["difference"], -0.3)

    def test_auto_indicator_falls_back_when_high_band_is_at_the_floor(self):
        plan = build_meditation_plan(["a", "b"], blocks=2, block_minutes=1.5, settle_seconds=0, seed=1)

        def white(condition, seconds, rng):
            n = int(seconds * FS)
            return {name: 10.0 * rng.standard_normal(n) for name in ("TP9", "AF7", "AF8", "TP10")}

        config = MeditationAnalysisConfig(complexity=FAST)
        summary = self.analyze(plan, white, config=config).summary
        self.assertEqual(summary["emg"]["indicator"], "emg_power_30_45")
        self.assertTrue(any("30-45 Hz" in item for item in summary["limitations"]))

        def low_passed(condition, seconds, rng):
            n = int(seconds * FS)
            return {name: 10.0 * band_noise(n, (1.0, 100.0), rng) for name in ("TP9", "AF7", "AF8", "TP10")}

        summary = self.analyze(plan, low_passed, config=config).summary
        self.assertEqual(summary["emg"]["indicator"], "emg_power_55_95")

    def test_artifact_epochs_are_flagged_and_dropped_only_from_clean_variant(self):
        plan = build_meditation_plan(["a", "b"], blocks=2, block_minutes=1.5, settle_seconds=0, seed=1)

        def with_clipping(condition, seconds, rng):
            n = int(seconds * FS)
            signal = {name: 10.0 * pink_noise(n, 1.0, rng) for name in ("TP9", "AF7", "AF8", "TP10")}
            if condition == "a":
                signal["TP9"][int(42 * FS) : int(44 * FS)] = 2000.0
            return signal

        analysis = self.analyze(plan, with_clipping)
        flagged = analysis.epochs[analysis.epochs["is_artifact"]]
        self.assertGreaterEqual(len(flagged), 1)
        self.assertTrue(flagged["artifact_flags"].str.contains("TP9").all())
        rows = analysis.blocks
        block_a = rows[rows["condition"] == "a"]
        self.assertLess(
            int(block_a.loc[block_a["variant"] == "clean", "epochs"].iloc[0]),
            int(block_a.loc[block_a["variant"] == "all", "epochs"].iloc[0]),
        )


class MeditationWithPolarTest(unittest.TestCase):
    def test_polar_breathing_lands_in_blocks_contrasts_and_confound_flag(self):
        from muse_tmr.data.polar_session import load_polar_session
        from tests.polar_synthetic import write_raw_session

        plan = build_meditation_plan(["slow", "normal"], blocks=4, block_minutes=2, settle_seconds=20, seed=3)
        wall0 = 1_790_000_000.0
        rng = np.random.default_rng(9)

        def signal_for(condition, seconds, rng):
            return condition_signal("busy", seconds, rng)

        def breathing(t):
            for block in plan.blocks:
                if block.start_s <= t < block.end_s:
                    return 6.0 if block.condition == "slow" else 15.0
            return 12.0

        frames = session_frames(plan, signal_for, rng)
        offset = wall0 - frames[0].timestamp
        frames = [
            type(frame)(timestamp=frame.timestamp + offset, eeg=type(frame.eeg)(timestamp=frame.eeg.timestamp + offset, channels_uv=frame.eeg.channels_uv), source=frame.source)
            for frame in frames
        ]
        seconds = plan.blocks[-1].end_s + 10.0
        with tempfile.TemporaryDirectory() as tmp:
            write_raw_session(tmp, seconds, rng, wall0=wall0, acc_breaths_per_min=breathing)
            polar = load_polar_session(Path(tmp))
            config = MeditationAnalysisConfig(emg_indicator="emg_power_55_95", complexity=FAST)
            analysis = asyncio.run(analyze_meditation_frames(aiter_frames(frames), plan, config, polar=polar))

        summary = analysis.summary
        cardio = summary["cardio"]
        self.assertTrue(cardio["available"])
        self.assertTrue(cardio["breathing_confounded"])
        self.assertAlmostEqual(cardio["breathing_difference_bpm"], -9.0, delta=1.0)
        self.assertEqual(cardio["hf_band_invalid_blocks"], 2)
        rows = analysis.blocks[analysis.blocks["variant"] == "all"].set_index("block_index")
        for block in plan.blocks:
            expected = 6.0 if block.condition == "slow" else 15.0
            self.assertAlmostEqual(rows.loc[block.index, "cardio_resp_rate_bpm"], expected, delta=0.7)
            self.assertAlmostEqual(rows.loc[block.index, "cardio_mean_hr_bpm"], 60.0, delta=3.0)
        chest = [item for item in summary["contrasts"] if item["group"] == "chest"]
        self.assertTrue(chest and not any(item["primary"] for item in chest))
        self.assertTrue(any("breathing rate" in item for item in summary["limitations"]))

        self.assertEqual(cardio["breathing_unreliable_blocks"], [])

        # The chest contrasts flow into the cross-session aggregate like any other,
        # and a session recorded without Polar keeps its slot as a gap.
        without_polar = {**summary, "contrasts": [item for item in summary["contrasts"] if item["group"] != "chest"]}
        aggregate = aggregate_meditation_summaries([summary, without_polar, summary], labels=["s1", "s2", "s3"])
        breathing = next(row for row in aggregate["rows"] if row["metric"] == "cardio_resp_rate_bpm")
        self.assertEqual(aggregate["sessions"], ["s1", "s2", "s3"])
        self.assertEqual(len(breathing["differences"]), 3)
        self.assertTrue(math.isnan(breathing["differences"][1]))
        self.assertEqual(breathing["n_sessions"], 2)

    def test_block_with_movement_is_left_out_of_breathing_contrasts(self):
        from muse_tmr.data.polar_session import load_polar_session
        from tests.polar_synthetic import write_raw_session

        plan = build_meditation_plan(["a", "b"], blocks=2, block_minutes=2, settle_seconds=20, seed=0)
        wall0 = 1_790_000_000.0
        rng = np.random.default_rng(10)
        frames = session_frames(plan, lambda c, s, r: condition_signal("busy", s, r), rng)
        offset = wall0 - frames[0].timestamp
        frames = [
            type(frame)(timestamp=frame.timestamp + offset, eeg=type(frame.eeg)(timestamp=frame.eeg.timestamp + offset, channels_uv=frame.eeg.channels_uv), source=frame.source)
            for frame in frames
        ]
        with tempfile.TemporaryDirectory() as tmp:
            write_raw_session(tmp, plan.blocks[-1].end_s + 10.0, rng, wall0=wall0, acc_breaths_per_min=10.0)
            polar = load_polar_session(Path(tmp))
            moving = plan.blocks[1]
            times = polar.acc["time"].to_numpy() - wall0
            for start in np.arange(moving.start_s + 35, moving.end_s - 10, 20.0):
                window = (times >= start) & (times < start + 8)
                polar.acc.loc[window, "x"] += 350.0 * np.sin(np.pi * (times[window] - start) / 8.0)
            config = MeditationAnalysisConfig(emg_indicator="emg_power_55_95", complexity=FAST)
            summary = asyncio.run(analyze_meditation_frames(aiter_frames(frames), plan, config, polar=polar)).summary

        cardio = summary["cardio"]
        self.assertEqual(cardio["breathing_unreliable_blocks"], [moving.index])
        self.assertFalse(cardio["breathing_confounded"])
        breathing = next(item for item in summary["contrasts"] if item["metric"] == "cardio_resp_rate_bpm")
        self.assertEqual(breathing["n_blocks_a"] + breathing["n_blocks_b"], 1)
        self.assertTrue(any("not trusted" in item for item in summary["limitations"]))

    def test_without_polar_the_section_says_so(self):
        plan = build_meditation_plan(["a", "b"], blocks=2, block_minutes=1.5, settle_seconds=0, seed=1)
        rng = np.random.default_rng(2)
        frames = session_frames(plan, lambda c, s, r: condition_signal("busy", s, r), rng)
        config = MeditationAnalysisConfig(emg_indicator="emg_power_55_95", complexity=FAST)
        summary = asyncio.run(analyze_meditation_frames(aiter_frames(frames), plan, config)).summary
        self.assertEqual(summary["cardio"], {"available": False})
        self.assertFalse(any(item["group"] == "chest" for item in summary["contrasts"]))


class AggregateMeditationTest(unittest.TestCase):
    def summary(self, conditions, lzc_difference, recording):
        return {
            "recording": recording,
            "conditions": list(conditions),
            "contrasts": [
                {"metric": "lzc", "group": "all", "variant": "clean", "difference": lzc_difference},
                {"metric": "sample_entropy", "group": "all", "variant": "clean", "difference": None},
            ],
            "emg": {
                "emg_confounded": recording == "s2",
                "residualized_contrasts": [
                    {"metric": "lzc", "group": "all", "variant": "clean", "residualized_difference": lzc_difference / 2}
                ],
            },
        }

    def row(self, result, metric="lzc", kind="raw"):
        return next(item for item in result["rows"] if item["metric"] == metric and item["kind"] == kind)

    def test_few_sessions_give_descriptives_and_warning_only(self):
        summaries = [
            self.summary(("focus", "open"), 0.10, "s1"),
            self.summary(("open", "focus"), -0.20, "s2"),  # reversed labels: sign flipped
            self.summary(("focus", "open"), 0.30, "s3"),
        ]
        result = aggregate_meditation_summaries(summaries)

        lzc = self.row(result)
        self.assertEqual(lzc["differences"], [0.10, 0.20, 0.30])
        self.assertAlmostEqual(lzc["mean_difference"], 0.2)
        self.assertTrue(lzc["primary"])
        self.assertNotIn("p_sign_flip", lzc)
        self.assertNotIn("ci95", lzc)
        self.assertTrue(result["warnings"])
        self.assertEqual(result["emg_confounded_sessions"], ["s2"])
        residual = self.row(result, kind="emg_residualized")
        self.assertEqual(residual["differences"], [0.05, 0.10, 0.15])
        self.assertFalse(residual["primary"])
        self.assertEqual(self.row(result, metric="sample_entropy")["n_sessions"], 0)

    def test_eight_sessions_get_sign_flip_and_bootstrap(self):
        summaries = [self.summary(("focus", "open"), 0.1 + 0.01 * index, f"s{index}") for index in range(8)]
        result = aggregate_meditation_summaries(summaries)
        lzc = self.row(result)
        self.assertFalse(result["warnings"])
        # All 8 positive: only the all-plus and all-minus sign patterns are as extreme.
        self.assertAlmostEqual(lzc["p_sign_flip"], 2 / 256)
        low, high = lzc["ci95"]
        self.assertLess(low, lzc["mean_difference"])
        self.assertGreater(high, lzc["mean_difference"])

    def test_mismatched_conditions_are_rejected(self):
        with self.assertRaises(ValueError):
            aggregate_meditation_summaries(
                [self.summary(("focus", "open"), 0.1, "s1"), self.summary(("focus", "body"), 0.1, "s2")]
            )

    def test_sign_flip_and_bootstrap_helpers(self):
        self.assertAlmostEqual(sign_flip_p_value(np.array([1.0, -1.0, 1.0, -1.0])), 1.0)
        low, high = bootstrap_ci(np.array([1.0, 1.0, 1.0]))
        self.assertEqual((low, high), (1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
