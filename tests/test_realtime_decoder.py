"""
Tests for Muse Real-time Decoder
"""

import unittest
import datetime
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from muse_realtime_decoder import MuseRealtimeDecoder, DecodedData
import muse_athena_protocol as proto


def build_tag_packet(first_tag, first_data, extra_subpackets=None):
    """Build a synthetic TAG-based packet for testing."""
    header = bytearray(14)
    header[9] = first_tag
    packet = bytes(header) + first_data
    if extra_subpackets:
        for tag, data in extra_subpackets:
            sub_header = bytearray(4)
            packet += bytes([tag]) + bytes(sub_header) + data
    return packet


class TestRealtimeDecoder(unittest.TestCase):
    """Test real-time packet decoding"""

    def setUp(self):
        """Set up test fixtures"""
        self.decoder = MuseRealtimeDecoder()

    def test_eeg_packet_decoding(self):
        """Test EEG packet decoding with TAG-based format"""
        eeg_packet = build_tag_packet(proto.TAG_EEG_4CH, bytes(28))

        decoded = self.decoder.decode(eeg_packet)

        self.assertIsNotNone(decoded.eeg)
        # Should have 4 channels
        self.assertEqual(len(decoded.eeg), 4)
        # Should use proper channel names
        for name in proto.EEG_CHANNELS_4:
            self.assertIn(name, decoded.eeg)
        # Each channel should have 4 samples (4ch mode)
        self.assertEqual(len(decoded.eeg['TP9']), 4)

    def test_eeg_packet_preserves_athena_channel_order(self):
        """Synthetic 4ch EEG columns should map to TP9, AF7, AF8, TP10."""
        rows = [
            [proto.EEG_MID_COUNT + 10, proto.EEG_MID_COUNT + 20,
             proto.EEG_MID_COUNT + 30, proto.EEG_MID_COUNT + 40],
            [proto.EEG_MID_COUNT + 11, proto.EEG_MID_COUNT + 21,
             proto.EEG_MID_COUNT + 31, proto.EEG_MID_COUNT + 41],
            [proto.EEG_MID_COUNT + 12, proto.EEG_MID_COUNT + 22,
             proto.EEG_MID_COUNT + 32, proto.EEG_MID_COUNT + 42],
            [proto.EEG_MID_COUNT + 13, proto.EEG_MID_COUNT + 23,
             proto.EEG_MID_COUNT + 33, proto.EEG_MID_COUNT + 43],
        ]
        eeg_packet = build_tag_packet(
            proto.TAG_EEG_4CH,
            _pack_14bit_lsb([value for row in rows for value in row]),
        )

        decoded = self.decoder.decode(eeg_packet)

        self.assertAlmostEqual(decoded.eeg['TP9'][0], _uv(proto.EEG_MID_COUNT + 10), places=5)
        self.assertAlmostEqual(decoded.eeg['AF7'][0], _uv(proto.EEG_MID_COUNT + 20), places=5)
        self.assertAlmostEqual(decoded.eeg['AF8'][0], _uv(proto.EEG_MID_COUNT + 30), places=5)
        self.assertAlmostEqual(decoded.eeg['TP10'][0], _uv(proto.EEG_MID_COUNT + 40), places=5)
        self.assertAlmostEqual(decoded.eeg['AF7'][3], _uv(proto.EEG_MID_COUNT + 23), places=5)

    def test_imu_packet_decoding(self):
        """Test IMU packet decoding with TAG-based format"""
        imu_packet = build_tag_packet(proto.TAG_ACCGYRO, bytes(36))

        decoded = self.decoder.decode(imu_packet)

        self.assertIsNotNone(decoded.imu)
        self.assertIn('accel', decoded.imu)
        self.assertIn('gyro', decoded.imu)
        # 3 samples x 3 accel channels
        self.assertEqual(len(decoded.imu['accel']), 3)
        self.assertEqual(len(decoded.imu['gyro']), 3)

    def test_optics_packet_decoding(self):
        """Test optics/PPG packet decoding with TAG-based format"""
        optics_packet = build_tag_packet(proto.TAG_OPTICS_8CH, bytes(40))

        decoded = self.decoder.decode(optics_packet)

        self.assertIsNotNone(decoded.ppg)
        # Should have 8 optics channels
        self.assertEqual(len(decoded.ppg), 8)
        for name in proto.OPTICS_CHANNELS_8:
            self.assertIn(name, decoded.ppg)

    def test_multi_subpacket(self):
        """Test packet with multiple subpacket types"""
        packet = build_tag_packet(
            proto.TAG_EEG_4CH, bytes(28),
            extra_subpackets=[
                (proto.TAG_ACCGYRO, bytes(36)),
                (proto.TAG_OPTICS_8CH, bytes(40)),
            ]
        )

        decoded = self.decoder.decode(packet)

        self.assertIsNotNone(decoded.eeg)
        self.assertIsNotNone(decoded.imu)
        self.assertIsNotNone(decoded.ppg)
        self.assertEqual(decoded.packet_type, 'MULTI')

        stats = self.decoder.get_stats()
        self.assertEqual(stats['tag_counts']['0x11'], 1)
        self.assertEqual(stats['tag_counts']['0x47'], 1)
        self.assertEqual(stats['tag_counts']['0x35'], 1)
        self.assertEqual(stats['tag_type_counts']['EEG'], 1)
        self.assertEqual(stats['tag_type_counts']['ACCGYRO'], 1)
        self.assertEqual(stats['tag_type_counts']['OPTICS'], 1)
        self.assertEqual(stats['unknown_tag_counts'], {})

    def test_repeated_eeg_subpackets_append_channel_samples(self):
        """Repeated EEG subpackets in one notification should not overwrite."""
        packet = build_tag_packet(
            proto.TAG_EEG_4CH, bytes(28),
            extra_subpackets=[
                (proto.TAG_EEG_4CH, bytes(28)),
            ]
        )

        decoded = self.decoder.decode(packet)
        stats = self.decoder.get_stats()

        self.assertIsNotNone(decoded.eeg)
        for name in proto.EEG_CHANNELS_4:
            self.assertEqual(len(decoded.eeg[name]), 8)
        self.assertEqual(stats['eeg_subpackets'], 2)
        self.assertEqual(stats['eeg_sample_rows'], 8)
        self.assertEqual(stats['eeg_values'], 32)
        self.assertEqual(stats['eeg_samples'], 32)

    def test_repeated_ppg_subpackets_append_channel_samples(self):
        """Repeated PPG subpackets in one notification should not overwrite."""
        packet = build_tag_packet(
            proto.TAG_OPTICS_8CH, bytes(40),
            extra_subpackets=[
                (proto.TAG_OPTICS_8CH, bytes(40)),
            ]
        )

        decoded = self.decoder.decode(packet)
        stats = self.decoder.get_stats()

        self.assertIsNotNone(decoded.ppg)
        for name in proto.OPTICS_CHANNELS_8:
            self.assertEqual(len(decoded.ppg[name]), 4)
        self.assertEqual(stats['ppg_subpackets'], 2)
        self.assertEqual(stats['ppg_sample_rows'], 4)
        self.assertEqual(stats['ppg_values'], 32)
        self.assertEqual(stats['ppg_samples'], 4)

    def test_callback_system(self):
        """Test callback registration and triggering"""
        eeg_called = False
        packet_data = None

        def on_eeg(data: DecodedData):
            nonlocal eeg_called, packet_data
            eeg_called = True
            packet_data = data

        self.decoder.register_callback('eeg', on_eeg)

        eeg_packet = build_tag_packet(proto.TAG_EEG_4CH, bytes(28))
        self.decoder.decode(eeg_packet)

        self.assertTrue(eeg_called)
        self.assertIsNotNone(packet_data)
        self.assertIsNotNone(packet_data.eeg)

    def test_statistics_tracking(self):
        """Test statistics tracking"""
        self.decoder.reset_stats()

        eeg_packet = build_tag_packet(proto.TAG_EEG_4CH, bytes(28))
        imu_packet = build_tag_packet(proto.TAG_ACCGYRO, bytes(36))

        self.decoder.decode(eeg_packet)
        self.decoder.decode(imu_packet)

        stats = self.decoder.get_stats()

        self.assertEqual(stats['packets_decoded'], 2)
        self.assertGreater(stats['eeg_samples'], 0)
        self.assertEqual(stats['eeg_subpackets'], 1)
        self.assertEqual(stats['eeg_sample_rows'], 4)
        self.assertEqual(stats['eeg_values'], 16)
        self.assertGreater(stats['imu_samples'], 0)
        self.assertEqual(stats['decode_errors'], 0)

    def test_effective_eeg_sample_rate_uses_sample_rows(self):
        """Sample-rate accounting is based on per-channel EEG sample rows."""
        self.decoder.reset_stats()
        eeg_packet = build_tag_packet(proto.TAG_EEG_4CH, bytes(28))
        t0 = datetime.datetime(2026, 1, 1, 0, 0, 0)

        self.decoder.decode(eeg_packet, timestamp=t0)
        self.decoder.decode(eeg_packet, timestamp=t0 + datetime.timedelta(seconds=1))

        stats = self.decoder.get_stats()
        self.assertEqual(stats['eeg_sample_rows'], 8)
        self.assertAlmostEqual(stats['eeg_effective_sample_rate_hz'], 8.0)

    def test_rolling_eeg_sample_rate_uses_recent_modality_window(self):
        """Rolling rate should avoid old startup samples."""
        self.decoder.reset_stats()
        eeg_packet = build_tag_packet(proto.TAG_EEG_4CH, bytes(28))
        t0 = datetime.datetime(2026, 1, 1, 0, 0, 0)

        self.decoder.decode(eeg_packet, timestamp=t0)
        self.decoder.decode(eeg_packet, timestamp=t0 + datetime.timedelta(seconds=20))
        self.decoder.decode(eeg_packet, timestamp=t0 + datetime.timedelta(seconds=21))
        self.decoder.decode(eeg_packet, timestamp=t0 + datetime.timedelta(seconds=22))

        stats = self.decoder.get_stats()
        self.assertEqual(stats['eeg_sample_rows'], 16)
        self.assertAlmostEqual(stats['eeg_effective_sample_rate_hz'], 16 / 22)
        self.assertAlmostEqual(stats['eeg_rolling_sample_rate_hz'], 8 / 2)
        self.assertAlmostEqual(stats['eeg_rolling_subpackets_per_second'], 2 / 2)

    def test_unknown_and_short_payload_diagnostics(self):
        """Malformed packets should be visible in decoder diagnostics."""
        unknown = bytearray(14)
        unknown[9] = 0x99

        self.decoder.decode(bytes(unknown) + bytes(28))
        self.decoder.decode(b"")

        stats = self.decoder.get_stats()
        self.assertEqual(stats['unknown_tag_counts'], {'0x99': 1})
        self.assertEqual(stats['short_notifications'], 1)
        self.assertEqual(stats['truncated_notifications'], 1)

    def test_battery_telemetry_updates_decoder_diagnostics(self):
        """Battery telemetry should decode without polluting unknown TAG stats."""
        battery_raw = int(91.5 * 256).to_bytes(2, byteorder="little") + bytes(198)
        packet = bytearray(build_tag_packet(proto.TAG_BATTERY_1, battery_raw))
        packet[0] = len(packet)

        decoded = self.decoder.decode(bytes(packet))

        self.assertEqual(decoded.packet_type, 'BATTERY')
        self.assertAlmostEqual(decoded.battery, 91.5)
        stats = self.decoder.get_stats()
        self.assertEqual(stats['tag_counts'], {'0x88': 1})
        self.assertEqual(stats['tag_type_counts'], {'BATTERY': 1})
        self.assertEqual(stats['unknown_tag_counts'], {})
        self.assertEqual(stats['battery_packets'], 1)
        self.assertEqual(stats['battery_payload_bytes'], 200)
        self.assertAlmostEqual(stats['battery_last_percent'], 91.5)

    def test_drl_ref_telemetry_updates_decoder_diagnostics(self):
        """DRL/REF telemetry should be known but not emitted as contact data."""
        packet = build_tag_packet(proto.TAG_DRL_REF, bytes(24))

        decoded = self.decoder.decode(packet)

        self.assertEqual(decoded.packet_type, 'SENSOR')
        self.assertIsNone(decoded.eeg)
        stats = self.decoder.get_stats()
        self.assertEqual(stats['tag_counts'], {'0x53': 1})
        self.assertEqual(stats['tag_type_counts'], {'DRLREF': 1})
        self.assertEqual(stats['unknown_tag_counts'], {})
        self.assertEqual(stats['drl_ref_packets'], 1)
        self.assertEqual(stats['drl_ref_payload_bytes'], 24)

    def test_error_handling(self):
        """Test error handling for malformed packets"""
        # Empty packet
        decoded = self.decoder.decode(b'')
        self.assertEqual(decoded.packet_type, 'EMPTY')

        # Very short packet
        decoded = self.decoder.decode(b'\x00')
        self.assertIsNotNone(decoded)

        # Malformed packet shouldn't crash
        decoded = self.decoder.decode(b'\xFF\xFF\xFF')
        self.assertIsNotNone(decoded)

        stats = self.decoder.get_stats()
        self.assertGreaterEqual(stats['packets_decoded'], 3)


class TestDecodedData(unittest.TestCase):
    """Test DecodedData dataclass"""

    def test_decoded_data_creation(self):
        """Test creating DecodedData objects"""
        data = DecodedData(
            timestamp=datetime.datetime.now(),
            packet_type='TEST',
            eeg={'TP9': [1, 2, 3]},
            ppg={'LO_NIR': [100, 200]},
            imu={'accel': [[0, 0, 1]], 'gyro': [[0, 0, 0]]},
            heart_rate=72.5,
            battery=85,
            raw_bytes=b'\x00\x01\x02'
        )

        self.assertEqual(data.packet_type, 'TEST')
        self.assertEqual(len(data.eeg['TP9']), 3)
        self.assertEqual(data.heart_rate, 72.5)
        self.assertEqual(data.battery, 85)


def _pack_14bit_lsb(values):
    data = bytearray(28)
    for value_idx, value in enumerate(values):
        for bit_idx in range(14):
            if int(value) & (1 << bit_idx):
                output_bit = value_idx * 14 + bit_idx
                data[output_bit // 8] |= 1 << (output_bit % 8)
    return bytes(data)


def _uv(raw_count):
    return (float(raw_count) - proto.EEG_MID_COUNT) * proto.EEG_SCALE_UV_PER_COUNT


if __name__ == '__main__':
    unittest.main()
