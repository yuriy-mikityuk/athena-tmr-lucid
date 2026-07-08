import unittest

from muse_tmr.presets import NO_OPTICS_PRESETS, preset_provides_optics


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


if __name__ == "__main__":
    unittest.main()
