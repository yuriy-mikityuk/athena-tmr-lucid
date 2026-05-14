import unittest

from muse_tmr.contact import (
    ContactQualityConfig,
    ContactQualityMonitor,
    REQUIRED_CONTACT_CHANNELS,
)
from muse_tmr.data.sample_types import EEGSample, MuseFrame


def frame(timestamp, channels):
    return MuseFrame(
        timestamp=timestamp,
        eeg=EEGSample(timestamp=timestamp, channels_uv=channels, source="test"),
        source="test",
    )


def good_values(count=512):
    return [10.0 if index % 2 == 0 else -10.0 for index in range(count)]


class TestContactQualityMonitor(unittest.TestCase):
    def test_missing_data_reports_each_required_channel_missing(self):
        monitor = ContactQualityMonitor(source="test")
        snapshot = monitor.snapshot(now_seconds=0.0)

        self.assertFalse(snapshot.all_good)
        self.assertEqual(snapshot.required_channels, REQUIRED_CONTACT_CHANNELS)
        self.assertEqual(
            {channel: state.status for channel, state in snapshot.channels.items()},
            {channel: "missing" for channel in REQUIRED_CONTACT_CHANNELS},
        )

    def test_all_good_contact_requires_each_channel_good(self):
        monitor = ContactQualityMonitor(source="test")
        monitor.update(frame(0.0, {channel: good_values() for channel in REQUIRED_CONTACT_CHANNELS}))
        snapshot = monitor.snapshot(now_seconds=1.0)

        self.assertTrue(snapshot.all_good)
        self.assertTrue(all(state.status == "good" for state in snapshot.channels.values()))
        self.assertTrue(all(state.fill >= 0.80 for state in snapshot.channels.values()))

    def test_one_bad_channel_does_not_poison_other_channels(self):
        monitor = ContactQualityMonitor(source="test")
        channels = {channel: good_values() for channel in REQUIRED_CONTACT_CHANNELS}
        channels["AF7"] = [0.0] * 512

        monitor.update(frame(0.0, channels))
        snapshot = monitor.snapshot(now_seconds=1.0)

        self.assertFalse(snapshot.all_good)
        self.assertEqual(snapshot.channels["AF7"].status, "poor")
        self.assertIn("flatline", snapshot.channels["AF7"].reason_codes)
        self.assertEqual(snapshot.channels["TP9"].status, "good")
        self.assertEqual(snapshot.channels["AF8"].status, "good")
        self.assertEqual(snapshot.channels["TP10"].status, "good")

    def test_short_coverage_reports_fair_contact(self):
        monitor = ContactQualityMonitor(source="test")
        channels = {channel: good_values(512) for channel in REQUIRED_CONTACT_CHANNELS}
        channels["TP10"] = good_values(256)

        monitor.update(frame(0.0, channels))
        snapshot = monitor.snapshot(now_seconds=1.0)

        self.assertFalse(snapshot.all_good)
        self.assertEqual(snapshot.channels["TP10"].status, "fair")
        self.assertIn("low_coverage", snapshot.channels["TP10"].reason_codes)
        self.assertGreaterEqual(snapshot.channels["TP10"].fill, 0.35)
        self.assertLess(snapshot.channels["TP10"].fill, 0.80)

    def test_nonfinite_and_clipping_are_poor_contact(self):
        monitor = ContactQualityMonitor(source="test")
        channels = {channel: good_values() for channel in REQUIRED_CONTACT_CHANNELS}
        channels["TP9"] = [float("nan")] * 32 + good_values(480)
        channels["AF8"] = [900.0] * 64 + good_values(448)

        monitor.update(frame(0.0, channels))
        snapshot = monitor.snapshot(now_seconds=1.0)

        self.assertEqual(snapshot.channels["TP9"].status, "poor")
        self.assertIn("non_finite", snapshot.channels["TP9"].reason_codes)
        self.assertEqual(snapshot.channels["AF8"].status, "poor")
        self.assertIn("clipping", snapshot.channels["AF8"].reason_codes)

    def test_live_dc_offset_does_not_count_as_clipping(self):
        monitor = ContactQualityMonitor(source="test")
        offset_values = [725.0 + (10.0 if index % 2 == 0 else -10.0) for index in range(512)]

        monitor.update(frame(0.0, {channel: offset_values for channel in REQUIRED_CONTACT_CHANNELS}))
        snapshot = monitor.snapshot(now_seconds=1.0)

        self.assertTrue(snapshot.all_good)
        self.assertTrue(all(state.status == "good" for state in snapshot.channels.values()))
        self.assertTrue(all("clipping" not in state.reason_codes for state in snapshot.channels.values()))

    def test_snapshot_marks_stale_when_frames_stop_arriving(self):
        monitor = ContactQualityMonitor(
            source="test",
            config=ContactQualityConfig(stale_timeout_seconds=2.0),
        )
        monitor.update(frame(10.0, {channel: good_values() for channel in REQUIRED_CONTACT_CHANNELS}))

        fresh = monitor.snapshot(now_seconds=11.0)
        stale = monitor.snapshot(now_seconds=13.1)

        self.assertFalse(fresh.stale)
        self.assertTrue(fresh.all_good)
        self.assertTrue(stale.stale)
        self.assertFalse(stale.all_good)


if __name__ == "__main__":
    unittest.main()
