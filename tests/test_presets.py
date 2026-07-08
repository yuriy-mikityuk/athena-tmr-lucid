import unittest

from muse_tmr.presets import (
    NO_OPTICS_PRESETS,
    preset_gate_thresholds,
    preset_provides_optics,
)


class TestPresetProvidesOptics(unittest.TestCase):
    def test_eeg_only_preset_has_no_optics(self):
        self.assertFalse(preset_provides_optics("p21"))

    def test_full_sensor_presets_have_optics(self):
        for preset in ("p1034", "p1035", "p1041"):
            self.assertTrue(preset_provides_optics(preset), preset)

    def test_unknown_preset_is_conservatively_optics_capable(self):
        self.assertTrue(preset_provides_optics("p9999"))

    def test_none_and_empty_are_conservatively_optics_capable(self):
        self.assertTrue(preset_provides_optics(None))
        self.assertTrue(preset_provides_optics(""))
        self.assertTrue(preset_provides_optics("   "))

    def test_preset_is_normalized(self):
        self.assertFalse(preset_provides_optics("  P21 "))

    def test_no_optics_presets_is_frozen(self):
        self.assertIn("p21", NO_OPTICS_PRESETS)
        self.assertIsInstance(NO_OPTICS_PRESETS, frozenset)


class TestPresetGateThresholds(unittest.TestCase):
    def test_p21_is_validated_recalibrated_point(self):
        self.assertEqual(preset_gate_thresholds("p21"), (0.90, 0.85))

    def test_optics_presets_get_conservative_provisional_point(self):
        for preset in ("p1034", "p1035", "p1041"):
            self.assertEqual(preset_gate_thresholds(preset), (0.80, 0.70), preset)

    def test_unknown_and_none_fall_back_to_conservative(self):
        self.assertEqual(preset_gate_thresholds("p9999"), (0.80, 0.70))
        self.assertEqual(preset_gate_thresholds(None), (0.80, 0.70))
        self.assertEqual(preset_gate_thresholds(""), (0.80, 0.70))

    def test_thresholds_are_normalized_and_valid(self):
        self.assertEqual(preset_gate_thresholds("  P21 "), (0.90, 0.85))
        for preset in ("p21", "p1034", None):
            enter, exit_ = preset_gate_thresholds(preset)
            self.assertLessEqual(exit_, enter)  # gate invariant


if __name__ == "__main__":
    unittest.main()
