import unittest

from muse_tmr.contact import (
    ContactGate,
    ContactGateConfig,
    ContactQualitySnapshot,
    builtin_contact_snapshots,
)


def scenario(name, index=0):
    return builtin_contact_snapshots(name)[index]


def disconnected_snapshot():
    return scenario("disconnect_after_good", 1)


def stale_snapshot():
    return scenario("stale_data", 1)


class TestContactGate(unittest.TestCase):
    def test_all_good_must_hold_for_stability_window(self):
        gate = ContactGate(ContactGateConfig(required_stability_seconds=5.0))
        good = scenario("all_good")

        armed = gate.arm(good, now_seconds=10.0)
        pending = gate.update(good, now_seconds=14.9)
        ready = gate.update(good, now_seconds=15.0)

        self.assertEqual(armed.state, "ready_countdown")
        self.assertFalse(armed.ready)
        self.assertEqual(pending.state, "ready_countdown")
        self.assertFalse(pending.ready)
        self.assertEqual(ready.state, "ready")
        self.assertTrue(ready.ready)
        self.assertEqual(ready.stable_for_seconds, 5.0)

    def test_poor_channel_blocks_and_resets_countdown(self):
        gate = ContactGate(ContactGateConfig(required_stability_seconds=5.0))
        poor = scenario("one_channel_poor")
        good = scenario("all_good")

        blocked = gate.arm(poor, now_seconds=0.0)
        recovered = gate.update(good, now_seconds=2.0)
        not_ready = gate.update(good, now_seconds=6.9)
        ready = gate.update(good, now_seconds=7.0)

        self.assertEqual(blocked.state, "armed_waiting_contact")
        self.assertIn("tp10_poor", blocked.reason_codes)
        self.assertEqual(recovered.stable_for_seconds, 0.0)
        self.assertFalse(not_ready.ready)
        self.assertTrue(ready.ready)

    def test_flapping_contact_resets_stability_window(self):
        gate = ContactGate(ContactGateConfig(required_stability_seconds=5.0))
        good = scenario("flapping_af7", 0)
        bad = scenario("flapping_af7", 1)

        gate.arm(good, now_seconds=0.0)
        blocked = gate.update(bad, now_seconds=2.0)
        restarted = gate.update(good, now_seconds=3.0)
        ready = gate.update(good, now_seconds=8.0)

        self.assertEqual(blocked.state, "armed_waiting_contact")
        self.assertEqual(restarted.stable_for_seconds, 0.0)
        self.assertTrue(ready.ready)

    def test_stale_or_disconnected_contact_resets_readiness(self):
        gate = ContactGate(ContactGateConfig(required_stability_seconds=5.0))

        stale = gate.arm(stale_snapshot(), now_seconds=0.0)
        disconnected = gate.update(disconnected_snapshot(), now_seconds=1.0)

        self.assertFalse(stale.ready)
        self.assertIn("stale_contact", stale.reason_codes)
        self.assertFalse(disconnected.ready)
        self.assertIn("disconnected", disconnected.reason_codes)

    def test_direct_start_blocks_until_gate_ready(self):
        gate = ContactGate(ContactGateConfig(required_stability_seconds=5.0))
        good = scenario("all_good")

        blocked = gate.start(good, now_seconds=0.0)
        gate.arm(good, now_seconds=1.0)
        ready = gate.update(good, now_seconds=6.0)
        starting = gate.start(good, now_seconds=6.0)

        self.assertEqual(blocked.state, "blocked_contact")
        self.assertIn("contact_gate_not_ready", blocked.reason_codes)
        self.assertTrue(ready.ready)
        self.assertEqual(starting.state, "starting")
        self.assertTrue(starting.ready)

    def test_running_state_warns_on_contact_drop_without_stopping(self):
        gate = ContactGate(ContactGateConfig(required_stability_seconds=0.0))
        good = scenario("all_good")
        poor = scenario("one_channel_poor")

        gate.arm(good, now_seconds=0.0)
        starting = gate.start(good, now_seconds=0.0)
        running = gate.update(poor, now_seconds=1.0)

        self.assertEqual(starting.state, "starting")
        self.assertEqual(running.state, "running")
        self.assertTrue(running.ready)
        self.assertIn("in_session_contact_warning", running.reason_codes)
        self.assertIn("tp10_poor", running.reason_codes)

    def test_gate_state_round_trip_shape_is_stable(self):
        gate = ContactGate(ContactGateConfig(required_stability_seconds=5.0))
        payload = gate.arm(scenario("all_good"), now_seconds=0.0).to_dict()

        self.assertEqual(set(payload), {
            "state",
            "all_good",
            "stable_for_seconds",
            "required_stability_seconds",
            "armed",
            "ready",
            "reason_codes",
        })


if __name__ == "__main__":
    unittest.main()
