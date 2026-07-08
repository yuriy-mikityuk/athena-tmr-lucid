import unittest

from muse_tmr.models import (
    RemGateConfig,
    RemPrediction,
    StableRemGate,
    build_rem_confidence,
)


def prediction(probability, *reason_codes):
    return RemPrediction(
        probability=probability,
        reason_codes=reason_codes,
        source="test",
    )


def gate_config(**overrides):
    params = {
        "enter_threshold": 0.70,
        "exit_threshold": 0.45,
        "min_stable_seconds": 60.0,
        "epoch_seconds": 30.0,
        "cooldown_seconds": 90.0,
    }
    params.update(overrides)
    return RemGateConfig(**params)


class TestStableRemGate(unittest.TestCase):
    def test_requires_consecutive_stable_rem_epochs_before_opening(self):
        gate = StableRemGate(gate_config())

        first = gate.update(prediction(0.82))
        second = gate.update(prediction(0.84))

        self.assertFalse(first.gate_open)
        self.assertEqual(first.state, "warming")
        self.assertIn("stability_window_not_met", first.reason_codes)
        self.assertTrue(second.gate_open)
        self.assertEqual(second.state, "open")
        self.assertEqual(second.stable_seconds, 60.0)
        self.assertIn("stable_rem_gate_open", second.reason_codes)

    def test_single_probability_spike_does_not_open_gate(self):
        gate = StableRemGate(gate_config())

        decisions = gate.update_many([
            prediction(0.82),
            prediction(0.30),
            prediction(0.83),
        ])

        self.assertEqual([decision.gate_open for decision in decisions], [False, False, False])
        self.assertEqual(decisions[1].stable_seconds, 0.0)
        self.assertIn("below_enter_threshold", decisions[1].reason_codes)
        self.assertIn("stability_window_not_met", decisions[2].reason_codes)

    def test_hysteresis_keeps_open_gate_until_exit_threshold(self):
        gate = StableRemGate(gate_config())
        gate.update(prediction(0.82))
        opened = gate.update(prediction(0.84))

        moderate = gate.update(prediction(0.55))
        low = gate.update(prediction(0.20))

        self.assertTrue(opened.gate_open)
        self.assertTrue(moderate.gate_open)
        self.assertIn("within_hysteresis", moderate.reason_codes)
        self.assertFalse(low.gate_open)
        self.assertEqual(low.state, "closed")
        self.assertIn("below_exit_threshold", low.reason_codes)

    def test_motion_arousal_blocks_gate_and_starts_cooldown(self):
        gate = StableRemGate(gate_config())
        gate.update(prediction(0.82))
        gate.update(prediction(0.84))

        arousal = gate.update(prediction(0.90, "motion_arousal_proxy"))
        cooldown = gate.update(prediction(0.90))

        self.assertFalse(arousal.gate_open)
        self.assertEqual(arousal.state, "blocked")
        self.assertEqual(arousal.cooldown_remaining_seconds, 90.0)
        self.assertIn("motion_arousal_block", arousal.reason_codes)
        self.assertFalse(cooldown.gate_open)
        self.assertEqual(cooldown.state, "blocked")
        self.assertEqual(cooldown.cooldown_remaining_seconds, 60.0)
        self.assertIn("cooldown_active", cooldown.reason_codes)

    def test_gate_can_reopen_after_cooldown_and_new_stability_window(self):
        gate = StableRemGate(gate_config(cooldown_seconds=60.0))
        gate.update(prediction(0.82))
        gate.update(prediction(0.84))
        gate.update(prediction(0.90, "motion_arousal_proxy"))

        blocked = gate.update(prediction(0.90))
        warming = gate.update(prediction(0.90))
        reopened = gate.update(prediction(0.91))

        self.assertFalse(blocked.gate_open)
        self.assertIn("cooldown_active", blocked.reason_codes)
        self.assertFalse(warming.gate_open)
        self.assertEqual(warming.state, "warming")
        self.assertTrue(reopened.gate_open)

    def test_low_feature_support_caps_confidence_below_threshold(self):
        confidence = build_rem_confidence(
            prediction(0.95, "insufficient_features"),
            config=gate_config(low_confidence_cap=0.55),
        )
        gate = StableRemGate(gate_config(low_confidence_cap=0.55))

        decision = gate.update(prediction(0.95, "insufficient_features"))

        self.assertEqual(confidence.confidence, 0.55)
        self.assertFalse(confidence.is_rem_like)
        self.assertFalse(decision.gate_open)
        self.assertIn("low_feature_confidence", decision.reason_codes)
        self.assertIn("below_enter_threshold", decision.reason_codes)

    def test_optics_capable_default_caps_missing_cardiac_coverage(self):
        # Regression anchor for #112: on an optics preset (default), a missing
        # PPG/HR signal caps confidence to 0.55 < 0.70 enter, so the gate never
        # opens despite a high probability.
        capped = build_rem_confidence(
            prediction(0.95, "low_ppg_hr_coverage"),
            config=gate_config(low_confidence_cap=0.55),
        )
        gate = StableRemGate(gate_config())
        first = gate.update(prediction(0.95, "low_ppg_hr_coverage"))
        second = gate.update(prediction(0.95, "low_ppg_hr_coverage"))

        self.assertEqual(capped.confidence, 0.55)
        self.assertFalse(capped.is_rem_like)
        self.assertFalse(first.gate_open)
        self.assertFalse(second.gate_open)

    def test_optics_incapable_preset_ignores_missing_cardiac_and_opens_gate(self):
        # The #112 fix: an EEG-only preset (optics_capable=False) must not be
        # penalized for a cardiac signal it never streams -- the gate opens on
        # sustained high probability.
        confidence = build_rem_confidence(
            prediction(0.82, "low_ppg_hr_coverage"),
            config=gate_config(optics_capable=False),
        )
        gate = StableRemGate(gate_config(optics_capable=False))
        first = gate.update(prediction(0.82, "low_ppg_hr_coverage"))
        second = gate.update(prediction(0.84, "low_ppg_hr_coverage"))

        self.assertEqual(confidence.confidence, 0.82)
        self.assertTrue(confidence.is_rem_like)
        self.assertNotIn("low_feature_confidence", confidence.reason_codes)
        self.assertFalse(first.gate_open)
        self.assertEqual(first.state, "warming")
        self.assertTrue(second.gate_open)
        self.assertEqual(second.state, "open")

    def test_optics_incapable_still_caps_non_cardiac_low_confidence(self):
        # Only the cardiac reason codes are ignored; other low-confidence codes
        # (e.g. a real EEG dropout) still cap even on an EEG-only preset.
        confidence = build_rem_confidence(
            prediction(0.95, "low_eeg_coverage"),
            config=gate_config(optics_capable=False, low_confidence_cap=0.55),
        )
        gate = StableRemGate(gate_config(optics_capable=False))
        decision = gate.update(prediction(0.95, "low_eeg_coverage"))

        self.assertEqual(confidence.confidence, 0.55)
        self.assertFalse(confidence.is_rem_like)
        self.assertIn("low_feature_confidence", confidence.reason_codes)
        self.assertFalse(decision.gate_open)

    def test_optics_incapable_still_blocks_on_arousal(self):
        # Turning off the cardiac cap must not weaken the arousal guard.
        gate = StableRemGate(gate_config(optics_capable=False))
        gate.update(prediction(0.82, "low_ppg_hr_coverage"))
        gate.update(prediction(0.84, "low_ppg_hr_coverage"))

        arousal = gate.update(prediction(0.90, "low_ppg_hr_coverage", "motion_arousal_proxy"))

        self.assertFalse(arousal.gate_open)
        self.assertEqual(arousal.state, "blocked")
        self.assertIn("motion_arousal_block", arousal.reason_codes)

    def test_gate_decision_is_not_audio_playback_decision(self):
        gate = StableRemGate(gate_config())
        decision = gate.update(prediction(0.82))

        self.assertFalse(hasattr(decision, "should_play"))

    def test_config_rejects_invalid_thresholds(self):
        with self.assertRaises(ValueError):
            RemGateConfig(enter_threshold=0.40, exit_threshold=0.60).validate()


if __name__ == "__main__":
    unittest.main()
