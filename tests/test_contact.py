import asyncio
import json
import unittest
from pathlib import Path

from muse_tmr.contact import (
    REQUIRED_CONTACT_CHANNELS,
    ChannelContactState,
    ContactQualitySnapshot,
    MockContactProvider,
    available_mock_contact_scenarios,
    builtin_contact_snapshots,
    load_contact_snapshots_jsonl,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "contact"


class TestContactContracts(unittest.TestCase):
    def test_channel_contact_state_validates_status_and_bounds(self):
        with self.assertRaises(ValueError):
            ChannelContactState("AF7", "excellent", 1.0, 1.0, 1)
        with self.assertRaises(ValueError):
            ChannelContactState("AF7", "good", 1.2, 1.0, 1)
        with self.assertRaises(ValueError):
            ChannelContactState("AF7", "good", 1.0, -0.1, 1)
        with self.assertRaises(ValueError):
            ChannelContactState("AF7", "good", 1.0, 1.0, -1)

    def test_snapshot_serializes_live_contact_contract_shape(self):
        snapshot = builtin_contact_snapshots("all_good")[0]
        payload = snapshot.to_dict()
        restored = ContactQualitySnapshot.from_dict(json.loads(json.dumps(payload)))

        self.assertTrue(restored.all_good)
        self.assertEqual(restored.source, "mock")
        self.assertEqual(restored.connection_state, "connected")
        self.assertEqual(restored.required_channels, REQUIRED_CONTACT_CHANNELS)
        self.assertEqual(set(restored.channels), set(REQUIRED_CONTACT_CHANNELS))
        self.assertEqual(restored.channels["AF7"].status, "good")

    def test_all_good_is_computed_from_required_channels_and_stale_state(self):
        snapshot = builtin_contact_snapshots("all_good")[0]
        stale_payload = snapshot.to_dict()
        stale_payload["stale"] = True
        stale_payload["all_good"] = True

        restored = ContactQualitySnapshot.from_dict(stale_payload)

        self.assertFalse(restored.all_good)


class TestMockContactProvider(unittest.TestCase):
    def test_builtin_scenarios_cover_required_mock_states(self):
        expected = {
            "all_missing",
            "one_channel_poor",
            "mixed_fair_good",
            "all_good",
            "flapping_af7",
            "disconnect_after_good",
            "stale_data",
        }

        self.assertEqual(set(available_mock_contact_scenarios()), expected)
        for name in expected:
            with self.subTest(name=name):
                snapshots = builtin_contact_snapshots(name)
                self.assertGreaterEqual(len(snapshots), 1)
                for snapshot in snapshots:
                    self.assertEqual(snapshot.required_channels, REQUIRED_CONTACT_CHANNELS)
                    self.assertEqual(set(snapshot.channels), set(REQUIRED_CONTACT_CHANNELS))

        self.assertTrue(builtin_contact_snapshots("all_good")[0].all_good)
        self.assertFalse(builtin_contact_snapshots("all_missing")[0].all_good)
        self.assertEqual(
            builtin_contact_snapshots("one_channel_poor")[0].channels["TP10"].status,
            "poor",
        )
        self.assertTrue(builtin_contact_snapshots("stale_data")[-1].stale)
        self.assertEqual(
            builtin_contact_snapshots("disconnect_after_good")[-1].connection_state,
            "disconnected",
        )

    def test_provider_defaults_to_one_hz_and_loops_when_configured(self):
        provider = MockContactProvider.for_scenario("flapping-af7", loop=True, interval_seconds=0)
        default_provider = MockContactProvider.for_scenario("all_good")

        self.assertEqual(default_provider.interval_seconds, 1.0)
        self.assertEqual([provider.next_snapshot().sequence for _ in range(4)], [0, 1, 2, 0])

    def test_provider_repeats_last_snapshot_when_not_looping(self):
        provider = MockContactProvider.for_scenario("disconnect_after_good", interval_seconds=0)

        self.assertEqual(provider.next_snapshot().connection_state, "connected")
        self.assertEqual(provider.next_snapshot().connection_state, "disconnected")
        self.assertEqual(provider.next_snapshot().connection_state, "disconnected")

    def test_async_stream_uses_mock_snapshots_without_ble(self):
        async def collect_sequences():
            provider = MockContactProvider.for_scenario("mixed_fair_good", interval_seconds=0)
            sequences = []
            async for snapshot in provider.stream():
                sequences.append(snapshot.sequence)
                await provider.stop()
            return sequences

        self.assertEqual(asyncio.run(collect_sequences()), [0])

    def test_jsonl_fixtures_match_contact_snapshot_schema(self):
        fixture_names = {path.stem for path in FIXTURE_DIR.glob("*.jsonl")}
        self.assertEqual(fixture_names, set(available_mock_contact_scenarios()))

        for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
            with self.subTest(path=path.name):
                snapshots = load_contact_snapshots_jsonl(path)
                self.assertGreaterEqual(len(snapshots), 1)
                for snapshot in snapshots:
                    payload = snapshot.to_dict()
                    self.assertEqual(set(payload), {
                        "source",
                        "connection_state",
                        "sequence",
                        "timestamp_seconds",
                        "stale",
                        "required_channels",
                        "channels",
                        "all_good",
                    })
                    self.assertEqual(set(snapshot.channels), set(REQUIRED_CONTACT_CHANNELS))


if __name__ == "__main__":
    unittest.main()
