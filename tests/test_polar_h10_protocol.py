import struct
import unittest

from muse_tmr.sources.polar_h10 import (
    CP_START,
    PmdStreamSettings,
    SETTING_CHANNELS,
    SETTING_FACTOR,
    SETTING_RANGE,
    SETTING_RESOLUTION,
    SETTING_SAMPLE_RATE,
    decode_delta_frames,
    factor_from_settings,
    get_settings_command,
    parse_control_point_response,
    parse_heart_rate_measurement,
    parse_pmd_frame,
    parse_settings,
    parse_start_command,
    sample_times_ns,
    serialize_settings,
    start_command,
    stop_command,
)

from tests.polar_synthetic import acc_frame_delta, acc_frame_uncompressed, ecg_frame, hr_measurement

ECG = PmdStreamSettings(sample_rate=130, resolution=14, channels=1)
ACC = PmdStreamSettings(sample_rate=50, resolution=16, channels=3)


class HeartRateServiceTest(unittest.TestCase):
    def test_uint8_hr_without_extras(self):
        parsed = parse_heart_rate_measurement(hr_measurement(72))
        self.assertEqual(parsed.heart_rate_bpm, 72)
        self.assertFalse(parsed.sensor_contact_supported)
        self.assertIsNone(parsed.sensor_contact)
        self.assertIsNone(parsed.energy_expended_kj)
        self.assertEqual(parsed.rr_intervals_ms, ())

    def test_uint16_hr(self):
        self.assertEqual(parse_heart_rate_measurement(hr_measurement(300, uint16=True)).heart_rate_bpm, 300)

    def test_contact_bits(self):
        on = parse_heart_rate_measurement(hr_measurement(60, contact=True))
        off = parse_heart_rate_measurement(hr_measurement(60, contact=False))
        self.assertTrue(on.sensor_contact_supported and on.sensor_contact)
        self.assertTrue(off.sensor_contact_supported)
        self.assertFalse(off.sensor_contact)

    def test_energy_and_rr_with_every_flag(self):
        payload = hr_measurement(65, rr_ms=(1000.0, 937.5), uint16=True, contact=True, energy=321)
        parsed = parse_heart_rate_measurement(payload)
        self.assertEqual(parsed.heart_rate_bpm, 65)
        self.assertEqual(parsed.energy_expended_kj, 321)
        self.assertEqual(len(parsed.rr_intervals_ms), 2)

    def test_rr_converted_from_1024ths(self):
        # 1024 ticks = 1000 ms; 512 ticks = 500 ms; 1 tick = 0.9765625 ms.
        payload = bytes([0x10, 60]) + struct.pack("<HHH", 1024, 512, 1)
        self.assertEqual(parse_heart_rate_measurement(payload).rr_intervals_ms, (1000.0, 500.0, 0.9765625))


class ControlPointTest(unittest.TestCase):
    def test_commands(self):
        self.assertEqual(get_settings_command(2), bytes([0x01, 0x02]))
        self.assertEqual(stop_command(0), bytes([0x03, 0x00]))
        command = start_command(0, {SETTING_SAMPLE_RATE: 130, SETTING_RESOLUTION: 14})
        self.assertEqual(command, bytes([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00]))
        self.assertEqual(parse_start_command(command), (0, {SETTING_SAMPLE_RATE: 130, SETTING_RESOLUTION: 14}))

    def test_factor_never_serialized(self):
        self.assertEqual(serialize_settings({SETTING_FACTOR: 123, SETTING_CHANNELS: 3}), bytes([0x04, 0x01, 0x03]))

    def test_settings_response_parsing(self):
        payload = bytes([0xF0, 0x01, 0x02, 0x00, 0x00]) + bytes(
            [0x00, 0x04, 25, 0, 50, 0, 100, 0, 200, 0, 0x01, 0x01, 16, 0, 0x02, 0x03, 2, 0, 4, 0, 8, 0]
        )
        response = parse_control_point_response(payload)
        self.assertTrue(response.ok)
        self.assertEqual(response.measurement_type, 2)
        settings = parse_settings(response.parameters)
        self.assertEqual(settings[SETTING_SAMPLE_RATE], (25, 50, 100, 200))
        self.assertEqual(settings[SETTING_RESOLUTION], (16,))
        self.assertEqual(settings[SETTING_RANGE], (2, 4, 8))

    def test_error_response_and_factor(self):
        error = parse_control_point_response(bytes([0xF0, CP_START, 0x00, 0x05]))
        self.assertFalse(error.ok)
        self.assertEqual(error.status_name, "invalid_parameter")
        factor_bytes = bytes([0x05, 0x01]) + struct.pack("<f", 0.24399999)
        self.assertAlmostEqual(factor_from_settings(parse_settings(factor_bytes)), 0.244, places=5)


class PmdFrameTest(unittest.TestCase):
    def test_ecg_frame(self):
        values = [-70, 15, 1203, -8_000_000, 8_000_000]
        frame = parse_pmd_frame(ecg_frame(599_616_023_171_427_290, values), ECG)
        self.assertEqual(frame.measurement_type, 0)
        self.assertEqual(frame.timestamp_ns, 599_616_023_171_427_290)
        self.assertFalse(frame.compressed)
        self.assertEqual([sample[0] for sample in frame.samples], values)

    def test_uncompressed_acc_frame_types(self):
        samples = [(1, -2, 3), (-4, 5, -6)]
        for frame_type in (0, 1, 2):
            frame = parse_pmd_frame(acc_frame_uncompressed(10, samples, frame_type=frame_type), ACC)
            self.assertEqual(frame.frame_type, frame_type)
            self.assertEqual(list(frame.samples), samples)

    def test_compressed_acc_frame_round_trip(self):
        samples = [(12, -40, 1003), (14, -41, 1001), (9, -35, 998), (-300, 250, 700)] + [
            (i % 7 - 3, -(i % 5), 1000 + i % 3) for i in range(40)
        ]
        payload = acc_frame_delta(5_000_000_000, samples)
        frame = parse_pmd_frame(payload, ACC)
        self.assertTrue(frame.compressed)
        self.assertEqual(frame.frame_type, 1)
        self.assertEqual(list(frame.samples), samples)

    def test_conversion_factor_applied(self):
        scaled = PmdStreamSettings(sample_rate=50, resolution=16, channels=3, factor=0.5)
        frame = parse_pmd_frame(acc_frame_uncompressed(1, [(10, -20, 30)]), scaled)
        self.assertEqual(frame.samples, ((5.0, -10.0, 15.0),))

    def test_delta_reference_sign_extension_below_16_bits(self):
        # A 14-bit -5 carried in two bytes as 0xFFFB, then one delta block of +1.
        content = (0xFFFB).to_bytes(2, "little") + bytes([2, 1, 0b01])
        self.assertEqual(decode_delta_frames(content, 1, 14), [(-5,), (-4,)])

    def test_sample_times_last_sample_is_frame_time(self):
        first, period = sample_times_ns(1_000_000_000, None, 5, 100.0)
        self.assertAlmostEqual(period, 1e7)
        self.assertAlmostEqual(first + 4 * period, 1_000_000_000)
        # With a previous frame the real rate wins (130 Hz +2 %).
        first, period = sample_times_ns(2_000_000_000, 2_000_000_000 - int(73 * 1e9 / 132.6), 73, 130.0)
        self.assertAlmostEqual(1e9 / period, 132.6, places=1)
        # A gap does not stretch the period.
        _first, period = sample_times_ns(10_000_000_000, 1_000_000_000, 73, 130.0)
        self.assertAlmostEqual(period, 1e9 / 130.0)


if __name__ == "__main__":
    unittest.main()
