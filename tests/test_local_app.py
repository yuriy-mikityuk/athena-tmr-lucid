import asyncio
import datetime as dt
import json
import signal
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import AsyncMock, patch

from muse_tmr.app import AppConfig, create_local_app_server
from muse_tmr.app.server import CAFFEINATE
from muse_tmr.sources.base_source import MuseSourceMetadata


class LoopSafeFakeAmusedSource:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.connect_calls = 0
        self.stream_calls = 0
        self.stop_requested = False
        LoopSafeFakeAmusedSource.instances.append(self)

    async def discover(self):
        return []

    async def connect(self, device=None):
        self.connect_calls += 1
        return MuseSourceMetadata(
            source_name="amused",
            device_name="Muse Test",
            device_id=self.kwargs.get("address") or "test-address",
            capabilities={"eeg": True},
        )

    async def stream(self):
        self.stream_calls += 1
        while not self.stop_requested:
            await asyncio.sleep(0.01)
        if False:
            yield

    async def stop(self):
        self.stop_requested = True

    def diagnostics(self):
        return {"connect_calls": self.connect_calls, "stream_calls": self.stream_calls}


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
        ui_state = self.get_json("/api/muse/ui-state")

        self.assertTrue(health["ok"])
        self.assertEqual(health["source"], "mock")
        self.assertEqual(state["connection_state"], "disconnected")
        self.assertEqual(state["source"], "mock")
        self.assertEqual(state["device"], None)
        self.assertEqual(set(contact["required_channels"]), {"TP9", "AF7", "AF8", "TP10"})
        self.assertEqual(set(contact["channels"]), {"TP9", "AF7", "AF8", "TP10"})
        self.assertEqual(contact["connection_state"], "disconnected")
        self.assertEqual(contact["channels"]["AF7"]["status"], "missing")
        self.assertEqual(contact["channels"]["AF7"]["quality_score"], contact["channels"]["AF7"]["fill"])
        self.assertEqual(ui_state["service"], "muse-tmr-local-app")
        self.assertIn("generated_at_seconds", ui_state)
        self.assertEqual(ui_state["state"]["connection_state"], "disconnected")
        self.assertEqual(ui_state["contact"]["connection_state"], "disconnected")
        self.assertEqual(ui_state["gate"]["state"], "disconnected")
        self.assertIsNone(ui_state["source_diagnostics"])

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
        self.assertIn("session-strip", body)
        self.assertIn("device-card", body)
        self.assertIn("warning-log", body)
        self.assertIn("diagnostics-panel", body)
        self.assertIn("source-badge", body)
        self.assertIn("data-channel=\"TP9\"", body)
        self.assertIn("data-channel=\"AF7\"", body)
        self.assertIn("data-channel=\"AF8\"", body)
        self.assertIn("data-channel=\"TP10\"", body)
        self.assertIn('id="start-session-button"', body)
        self.assertIn('id="start-night-button"', body)
        self.assertIn("Start night session", body)
        self.assertIn('id="stop-recording-button"', body)
        self.assertIn('id="recording-strip"', body)
        self.assertIn("/api/muse/ui-state", script)
        self.assertNotIn('requestJson("/api/muse/state"', script)
        self.assertNotIn('requestJson("/api/muse/contact"', script)
        self.assertNotIn('requestJson("/api/muse/gate"', script)
        self.assertNotIn('requestJson("/api/muse/diagnostics"', script)
        self.assertIn("/api/session/record", script)
        self.assertIn("/api/session/record/stop", script)
        self.assertIn("Starting session", script)
        self.assertIn("Session running", script)
        self.assertIn("contact warnings", script)
        self.assertIn("contact-sparkline", script)
        self.assertIn("active-warning-status", script)
        self.assertIn('scanButton.hidden = connection === "connected"', script)
        self.assertIn("startSessionButton.hidden = !canRecord", script)

    def test_diagnostics_endpoint_reports_state_and_last_contact(self):
        self.post_json("/api/muse/connect")
        self.get_json("/api/muse/contact")

        diagnostics = self.get_json("/api/muse/diagnostics")

        self.assertEqual(diagnostics["service"], "muse-tmr-local-app")
        self.assertEqual(diagnostics["state"]["connection_state"], "connected")
        self.assertIsNone(diagnostics["source_diagnostics"])
        self.assertEqual(diagnostics["contact"]["channels"]["AF7"]["status"], "fair")
        self.assertIn("session", diagnostics["state"])
        self.assertFalse(diagnostics["state"]["session"]["running"])


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

    def get_json(self, path):
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_start_when_ready_auto_starts_after_ready_gate(self):
        self.post_json("/api/muse/connect")
        armed = self.post_json("/api/muse/start-when-ready")
        ui_state = self.get_json("/api/muse/ui-state")

        self.assertEqual(armed["state"], "starting")
        self.assertTrue(armed["ready"])
        self.assertEqual(ui_state["contact"]["connection_state"], "connected")
        self.assertTrue(ui_state["contact"]["all_good"])
        self.assertEqual(ui_state["gate"]["state"], "running")
        self.assertTrue(ui_state["gate"]["ready"])
        self.assertTrue(ui_state["state"]["session"]["running"])
        self.assertIsNotNone(ui_state["state"]["session"]["started_at_seconds"])


class TestLocalMuseAppContactWarningLog(unittest.TestCase):
    def setUp(self):
        self.server = create_local_app_server(
            AppConfig(port=0, source="mock", mock_scenario="flapping_af7", gate_stability_seconds=0.0)
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

    def get_json(self, path):
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_running_session_logs_contact_drop_and_recovery(self):
        self.post_json("/api/muse/connect")
        self.post_json("/api/muse/start-when-ready")
        dropped = self.get_json("/api/muse/ui-state")
        recovered = self.get_json("/api/muse/ui-state")

        dropped_session = dropped["state"]["session"]
        self.assertEqual(dropped["contact"]["channels"]["AF7"]["status"], "poor")
        self.assertFalse(dropped["contact"]["all_good"])
        self.assertEqual(dropped["gate"]["state"], "running")
        self.assertTrue(dropped_session["running"])
        self.assertEqual(dropped_session["contact_warning_count"], 1)
        self.assertIsNotNone(dropped_session["active_contact_warning"])
        self.assertIn("AF7 poor", dropped_session["active_contact_warning"]["channels"])

        session = recovered["state"]["session"]
        self.assertTrue(recovered["contact"]["all_good"])
        self.assertTrue(session["running"])
        self.assertEqual(session["contact_warning_count"], 1)
        self.assertIsNone(session["active_contact_warning"])
        self.assertEqual(
            [event["kind"] for event in session["contact_warning_events"]],
            ["contact_drop", "contact_recovered"],
        )
        self.assertIn("AF7 poor", session["contact_warning_events"][0]["channels"])
        self.assertIn("low_coverage", session["contact_warning_events"][0]["reason_codes"])


class TestLocalMuseAppAmusedScan(unittest.TestCase):
    def test_live_app_uses_effective_amused_contact_sample_rate(self):
        server = create_local_app_server(AppConfig(port=0, source="amused"))
        try:
            self.assertEqual(server.app_state._contact_monitor.config.sample_rate_hz, 128.0)
        finally:
            server.app_state.shutdown()
            server.server_close()

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


class TestLocalMuseAppAmusedConnect(unittest.TestCase):
    def test_repeated_live_connect_is_idempotent(self):
        LoopSafeFakeAmusedSource.instances = []
        with patch("muse_tmr.sources.amused_source.AmusedSource", LoopSafeFakeAmusedSource):
            server = create_local_app_server(
                AppConfig(
                    port=0,
                    source="amused",
                    address="2C48FFC8-A1C5-BDFD-A5A4-EEA280A7BBA6",
                )
            )
            try:
                first = server.app_state.connect()
                second = server.app_state.connect()
                time.sleep(0.05)

                self.assertEqual(first["connection_state"], "connected")
                self.assertEqual(second["connection_state"], "connected")
                self.assertEqual(len(LoopSafeFakeAmusedSource.instances), 1)
                source = LoopSafeFakeAmusedSource.instances[0]
                self.assertEqual(source.connect_calls, 1)
                self.assertEqual(source.stream_calls, 1)
                self.assertEqual(server.app_state.state()["connection_state"], "connected")
            finally:
                server.app_state.shutdown()
                server.server_close()


class _FakeProc:
    def __init__(self, pid=4242):
        self.pid = pid
        self.returncode = None

    def poll(self):
        return self.returncode


class LauncherSpy:
    def __init__(self, proc=None):
        self.calls = []
        self._proc = proc if proc is not None else _FakeProc()

    def __call__(self, command, log_path):
        self.calls.append((list(command), Path(log_path)))
        return self._proc


class TerminatorSpy:
    def __init__(self):
        self.signals = []

    def __call__(self, pid, sig):
        self.signals.append((pid, sig))


_FIXED_NOW = dt.datetime(2026, 7, 7, 1, 0, 0)


class TestLocalMuseAppRecording(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.recordings_base = Path(self._tmp.name)
        self.launcher = LauncherSpy()
        self.terminator = TerminatorSpy()

    def tearDown(self):
        self._tmp.cleanup()

    def _make_state(self, source="amused", proc=None):
        server = create_local_app_server(
            AppConfig(port=0, source=source),
            launcher=LauncherSpy(proc) if proc is not None else self.launcher,
            terminator=self.terminator,
            recordings_base=self.recordings_base,
            now_fn=lambda: _FIXED_NOW,
        )
        self.addCleanup(server.server_close)
        self.addCleanup(server.app_state.shutdown)
        return server.app_state

    def test_record_requires_amused_source(self):
        state = self._make_state(source="mock")
        payload, status = state.start_recording("night")
        self.assertEqual(int(status), 409)
        self.assertIn("amused", payload["error"])
        self.assertEqual(self.launcher.calls, [])

    def test_record_rejects_unknown_kind(self):
        state = self._make_state()
        payload, status = state.start_recording("bogus")
        self.assertEqual(int(status), 400)
        self.assertEqual(self.launcher.calls, [])

    def test_record_night_builds_expected_command_and_folder(self):
        state = self._make_state()
        payload, status = state.start_recording("night")

        self.assertEqual(int(status), 200)
        self.assertEqual(len(self.launcher.calls), 1)
        command, _log = self.launcher.calls[0]
        expected_dir = (self.recordings_base / "night" / "20260707_010000").resolve()
        self.assertEqual(
            command,
            [
                CAFFEINATE,
                "-s",
                sys.executable,
                "-m",
                "muse_tmr.cli.main",
                "record",
                "--source",
                "amused",
                "--preset",
                "p21",
                "--duration-hours",
                "8",
                "--no-data-timeout-seconds",
                "45",
                "--max-reconnect-attempts",
                "1000",
                "--output-dir",
                str(expected_dir),
                "--quiet",
            ],
        )
        self.assertNotIn("--allow-short", command)
        self.assertEqual(payload["kind"], "night")
        self.assertEqual(payload["preset"], "p21")
        self.assertTrue(payload["active"])
        self.assertTrue((expected_dir / "launch.json").exists())

    def test_record_session_uses_p1034_and_allow_short(self):
        state = self._make_state()
        payload, status = state.start_recording("session")

        self.assertEqual(int(status), 200)
        command, _log = self.launcher.calls[0]
        expected_dir = (self.recordings_base / "session" / "20260707_010000").resolve()
        self.assertIn("--preset", command)
        self.assertEqual(command[command.index("--preset") + 1], "p1034")
        self.assertEqual(command[command.index("--duration-hours") + 1], "1")
        self.assertEqual(command[-1], "--allow-short")
        self.assertEqual(command[command.index("--output-dir") + 1], str(expected_dir))
        self.assertEqual(payload["preset"], "p1034")

    def test_double_start_returns_conflict(self):
        state = self._make_state()
        first, first_status = state.start_recording("night")
        self.assertEqual(int(first_status), 200)
        payload, status = state.start_recording("session")
        self.assertEqual(int(status), 409)
        self.assertIn("already running", payload["error"])
        self.assertEqual(len(self.launcher.calls), 1)

    def test_stop_signals_sigint_to_group(self):
        state = self._make_state()
        state.start_recording("night")
        payload, status = state.stop_recording()

        self.assertEqual(int(status), 200)
        self.assertEqual(self.terminator.signals, [(4242, signal.SIGINT)])
        self.assertEqual(payload["state"], "stopping")

    def test_stop_without_recording_returns_conflict(self):
        state = self._make_state()
        payload, status = state.stop_recording()
        self.assertEqual(int(status), 409)
        self.assertEqual(self.terminator.signals, [])

    def test_ui_state_reports_progress_from_progress_json(self):
        state = self._make_state()
        state.start_recording("night")
        output_dir = (self.recordings_base / "night" / "20260707_010000").resolve()
        (output_dir / "progress.json").write_text(
            json.dumps(
                {
                    "elapsed_seconds": 120.0,
                    "frame_count": 999,
                    "battery_percent": 87.0,
                    "reconnect_attempts": 2,
                    "last_event": "reconnect_scheduled",
                }
            ),
            encoding="utf-8",
        )
        recording = state.ui_state()["recording"]
        self.assertTrue(recording["active"])
        self.assertEqual(recording["frame_count"], 999)
        self.assertEqual(recording["battery_percent"], 87.0)
        self.assertEqual(recording["reconnect_attempts"], 2)
        self.assertEqual(recording["elapsed_seconds"], 120.0)
        self.assertEqual(recording["last_event"], "reconnect_scheduled")

    def test_ui_state_marks_completed_when_summary_present(self):
        proc = _FakeProc()
        state = self._make_state(proc=proc)
        state.start_recording("night")
        output_dir = (self.recordings_base / "night" / "20260707_010000").resolve()
        (output_dir / "summary.json").write_text(
            json.dumps({"stop_reason": "duration_complete", "reconnect_attempts": 3}),
            encoding="utf-8",
        )
        proc.returncode = 0

        recording = state.ui_state()["recording"]
        self.assertEqual(recording["state"], "completed")
        self.assertFalse(recording["active"])
        self.assertTrue(recording["summary_available"])

        # A finished recording must not block a new one.
        _payload, status = state.start_recording("session")
        self.assertEqual(int(status), 200)

    def test_start_recording_releases_ble_before_spawn(self):
        LoopSafeFakeAmusedSource.instances = []
        with patch("muse_tmr.sources.amused_source.AmusedSource", LoopSafeFakeAmusedSource):
            state = self._make_state()
            connected = state.connect()
            self.assertEqual(connected["connection_state"], "connected")

            payload, status = state.start_recording("night")
            self.assertEqual(int(status), 200)

            source = LoopSafeFakeAmusedSource.instances[0]
            self.assertTrue(source.stop_requested)
            self.assertEqual(state.state()["connection_state"], "disconnected")
            self.assertEqual(len(self.launcher.calls), 1)


class TestLocalMuseAppRecordingEndpoint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.launcher = LauncherSpy()
        self.server = create_local_app_server(
            AppConfig(port=0, source="mock"),
            launcher=self.launcher,
            recordings_base=Path(self._tmp.name),
            now_fn=lambda: _FIXED_NOW,
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
        self._tmp.cleanup()

    def _post(self, path, body):
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return urllib.request.urlopen(request, timeout=2)

    def test_record_endpoint_conflicts_in_mock_mode(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self._post("/api/session/record", {"kind": "night"})
        self.assertEqual(raised.exception.code, 409)
        self.assertEqual(self.launcher.calls, [])


if __name__ == "__main__":
    unittest.main()
