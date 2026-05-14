import json
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import AsyncMock, patch

from muse_tmr.app import AppConfig, create_local_app_server


class TestLocalMuseApp(unittest.TestCase):
    def setUp(self):
        self.server = create_local_app_server(AppConfig(port=0, source="mock"))
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.app_state.shutdown()
        self.server.server_close()

    def get_json(self, path):
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path):
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_health_and_initial_state_are_available_without_ble(self):
        health = self.get_json("/api/health")
        state = self.get_json("/api/muse/state")
        contact = self.get_json("/api/muse/contact")

        self.assertTrue(health["ok"])
        self.assertEqual(health["source"], "mock")
        self.assertEqual(state["connection_state"], "disconnected")
        self.assertEqual(state["source"], "mock")
        self.assertEqual(state["device"], None)
        self.assertEqual(set(contact["required_channels"]), {"TP9", "AF7", "AF8", "TP10"})
        self.assertEqual(set(contact["channels"]), {"TP9", "AF7", "AF8", "TP10"})
        self.assertEqual(contact["connection_state"], "disconnected")
        self.assertEqual(contact["channels"]["AF7"]["status"], "missing")

    def test_contact_stream_emits_sse_snapshots(self):
        with urllib.request.urlopen(
            f"{self.base_url}/api/muse/contact/stream?count=2&interval=0",
            timeout=2,
        ) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(response.headers["Content-Type"], "text/event-stream; charset=utf-8")
        self.assertEqual(body.count("event: contact"), 2)
        self.assertIn("\"required_channels\": [\"TP9\", \"AF7\", \"AF8\", \"TP10\"]", body)

    def test_start_when_ready_arms_gate_and_direct_start_blocks(self):
        armed = self.post_json("/api/muse/start-when-ready")

        self.assertEqual(armed["state"], "armed_waiting_contact")
        self.assertTrue(armed["armed"])
        self.assertFalse(armed["ready"])
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post_json("/api/session/start")
        self.assertEqual(raised.exception.code, 409)

    def test_mock_scan_connect_and_disconnect_states(self):
        scanned = self.post_json("/api/muse/scan")
        connected = self.post_json("/api/muse/connect")
        contact = self.get_json("/api/muse/contact")
        disconnected = self.post_json("/api/muse/disconnect")

        self.assertEqual(scanned["connection_state"], "disconnected")
        self.assertEqual(scanned["devices"][0]["address"], "mock://muse-s")
        self.assertEqual(connected["connection_state"], "connected")
        self.assertEqual(connected["device"]["name"], "Muse Mock Headband")
        self.assertEqual(contact["channels"]["AF7"]["status"], "fair")
        self.assertEqual(disconnected["connection_state"], "disconnected")

    def test_static_ui_loads_connect_muse_screen(self):
        with urllib.request.urlopen(f"{self.base_url}/", timeout=2) as response:
            body = response.read().decode("utf-8")
        with urllib.request.urlopen(f"{self.base_url}/app.js", timeout=2) as response:
            script = response.read().decode("utf-8")

        self.assertIn("Connect Muse", body)
        self.assertIn("headband-title", body)
        self.assertIn("data-channel=\"TP9\"", body)
        self.assertIn("data-channel=\"AF7\"", body)
        self.assertIn("data-channel=\"AF8\"", body)
        self.assertIn("data-channel=\"TP10\"", body)
        self.assertIn("/api/muse/state", script)
        self.assertIn("/api/muse/contact", script)
        self.assertIn("/api/muse/start-when-ready", script)


class TestLocalMuseAppReadyGate(unittest.TestCase):
    def setUp(self):
        self.server = create_local_app_server(
            AppConfig(port=0, source="mock", mock_scenario="all_good", gate_stability_seconds=0.0)
        )
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.app_state.shutdown()
        self.server.server_close()

    def post_json(self, path):
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_direct_start_succeeds_after_ready_gate(self):
        self.post_json("/api/muse/connect")
        armed = self.post_json("/api/muse/start-when-ready")
        started = self.post_json("/api/session/start")

        self.assertEqual(armed["state"], "ready")
        self.assertTrue(armed["ready"])
        self.assertEqual(started["state"], "starting")
        self.assertTrue(started["ready"])


class TestLocalMuseAppAmusedScan(unittest.TestCase):
    def test_empty_live_scan_returns_disconnected_error_without_sticking_scanning(self):
        with patch(
            "muse_tmr.sources.amused_source.AmusedSource.discover",
            new_callable=AsyncMock,
        ) as discover:
            discover.return_value = []
            server = create_local_app_server(AppConfig(port=0, source="amused"))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            host, port = server.server_address
            base_url = f"http://{host}:{port}"
            try:
                request = urllib.request.Request(
                    f"{base_url}/api/muse/scan",
                    data=b"",
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    scanned = json.loads(response.read().decode("utf-8"))

                self.assertEqual(scanned["connection_state"], "disconnected")
                self.assertEqual(scanned["devices"], [])
                self.assertEqual(scanned["error_message"], "No Muse devices found")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.app_state.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
