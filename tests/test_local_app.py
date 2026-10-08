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
        self.assertIn("device-battery", body)
        self.assertIn("scan-result", body)
        self.assertIn("with-polar-checkbox", body)
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


class BatteryFakeAmusedSource(LoopSafeFakeAmusedSource):
    """Connects by address like amused (name == address) and streams battery frames."""

    async def discover(self):
        from muse_tmr.sources.base_source import MuseDeviceInfo

        return [
            MuseDeviceInfo(name="Muse-OTHER", address="other-address", rssi=-80),
            MuseDeviceInfo(name="MuseS-1234", address="test-address", rssi=-55),
        ]

    async def connect(self, device=None):
        self.connect_calls += 1
        return MuseSourceMetadata(
            source_name="amused", device_name="test-address", device_id="test-address", capabilities={"eeg": True}
        )

    async def stream(self):
        from muse_tmr.data.sample_types import BatterySample, MuseFrame

        self.stream_calls += 1
        percent = 81.5
        while not self.stop_requested:
            yield MuseFrame(timestamp=time.time(), battery=BatterySample(timestamp=time.time(), percent=percent), source="amused")
            await asyncio.sleep(0.01)


class TestLocalMuseAppBatteryAndScan(unittest.TestCase):
    def make(self, address):
        BatteryFakeAmusedSource.instances = []
        patcher = patch("muse_tmr.sources.amused_source.AmusedSource", BatteryFakeAmusedSource)
        patcher.start()
        self.addCleanup(patcher.stop)
        server = create_local_app_server(AppConfig(port=0, source="amused", address=address))
        self.addCleanup(server.server_close)
        self.addCleanup(server.app_state.shutdown)
        return server.app_state

    def test_scan_reports_configured_headband_and_sorts_by_signal(self):
        state = self.make("test-address")
        scanned = state.scan()
        self.assertEqual([device["name"] for device in scanned["devices"]], ["MuseS-1234", "Muse-OTHER"])
        self.assertTrue(scanned["scan"]["configured_found"])
        self.assertEqual(scanned["scan"]["count"], 2)

    def test_failed_scan_replaces_the_previous_result(self):
        state = self.make("test-address")
        self.assertTrue(state.scan()["scan"]["configured_found"])
        with patch.object(BatteryFakeAmusedSource, "discover", side_effect=RuntimeError("Bluetooth is off")):
            failed = state.scan()
        self.assertEqual(failed["devices"], [])
        self.assertTrue(failed["scan"]["failed"])
        self.assertIn("Bluetooth is off", failed["scan"]["error"])

    def test_scan_says_when_the_configured_headband_is_missing(self):
        state = self.make("not-around")
        self.assertFalse(state.scan()["scan"]["configured_found"])

    def test_battery_while_connected_and_name_instead_of_address(self):
        state = self.make("test-address")
        self.assertIsNone(state.state()["battery_percent"])
        state.scan()
        state.connect()
        deadline = time.time() + 2
        while state.state()["battery_percent"] is None and time.time() < deadline:
            time.sleep(0.02)
        connected = state.state()
        self.assertEqual(connected["battery_percent"], 81.5)
        self.assertEqual(connected["device"]["name"], "MuseS-1234")
        state.disconnect()
        self.assertIsNone(state.state()["battery_percent"])

    def test_name_falls_back_to_muse_without_a_scan(self):
        state = self.make("test-address")
        self.assertEqual(state.connect()["device"]["name"], "Muse")


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
        self.assertTrue(payload["report_command"].startswith("cd "))
        self.assertIn(
            f"&& {sys.executable} scripts/generate_nightly_report.py {expected_dir}",
            payload["report_command"],
        )
        self.assertEqual(payload["kind"], "night")
        self.assertEqual(payload["preset"], "p21")
        self.assertTrue(payload["active"])
        self.assertTrue((expected_dir / "launch.json").exists())

    def test_report_command_uses_project_venv_outside_a_venv(self):
        project_root = self.recordings_base / "project"
        venv_python = project_root / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("", encoding="utf-8")
        state = self._make_state()

        # The macOS Python.app launch: base interpreter, venv only on PYTHONPATH.
        with patch.object(sys, "prefix", sys.base_prefix), patch(
            "muse_tmr.cli.main._find_project_root", return_value=project_root
        ):
            payload, _status = state.start_recording("night")

        self.assertTrue(
            payload["report_command"].startswith(
                f"cd {project_root} && {venv_python} scripts/generate_nightly_report.py "
            )
        )

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

    def test_running_recording_blocks_auto_update_restart(self):
        state = self._make_state()
        self.assertTrue(state.idle_for_update())
        state.start_recording("night")
        self.assertFalse(state.idle_for_update())

    def test_record_with_polar_passes_flag_and_reports_h10_status(self):
        import base64

        state = self._make_state()
        payload, status = state.start_recording("session", with_polar=True)
        self.assertEqual(int(status), 200)
        command, _log = self.launcher.calls[0]
        self.assertEqual(command[-1], "--with-polar")
        self.assertTrue(payload["with_polar"])
        self.assertEqual(payload["polar"]["state"], "starting")
        output_dir = Path(payload["output_dir"])
        launch = json.loads((output_dir / "launch.json").read_text())
        self.assertTrue(launch["with_polar"])

        polar = output_dir / "polar"
        polar.mkdir(parents=True)
        (polar / "events.jsonl").write_text(
            json.dumps({"event": "recording_started"}) + "\n" + json.dumps({"event": "connected"}) + "\n"
        )
        hr = bytes([0x16, 72, 0x00, 0x04])  # contact supported + detected, RR present
        (polar / "raw_notifications.jsonl").write_text(
            json.dumps({"char": "pmd_data", "b64": "AA=="}) + "\n"
            + json.dumps({"char": "hr", "b64": base64.b64encode(hr).decode()}) + "\n"
        )
        status_now = state.ui_state()["recording"]["polar"]
        self.assertEqual((status_now["state"], status_now["heart_rate_bpm"], status_now["contact"]), ("connected", 72, True))

        (polar / "events.jsonl").write_text(json.dumps({"event": "disconnected"}) + "\n")
        self.assertEqual(state.ui_state()["recording"]["polar"]["state"], "reconnecting")

        (output_dir / "events.jsonl").write_text(json.dumps({"event": "companion_exited"}) + "\n")
        self.assertEqual(state.ui_state()["recording"]["polar"]["state"], "failed")

        (polar / "summary.json").write_text(json.dumps({"stop_reason": "user_stopped"}))
        self.assertEqual(state.ui_state()["recording"]["polar"]["state"], "stopped")

    def test_recording_stays_active_while_the_recorder_waits_for_its_polar_child(self):
        proc = _FakeProc()
        state = self._make_state(proc=proc)
        payload, _ = state.start_recording("session", with_polar=True)
        output_dir = Path(payload["output_dir"])
        (output_dir / "summary.json").write_text(json.dumps({"stop_reason": "user_stopped"}))

        finishing = state.ui_state()["recording"]
        self.assertEqual(finishing["state"], "finishing")
        self.assertTrue(finishing["active"])
        _payload, status = state.start_recording("session")
        self.assertEqual(int(status), 409)  # the old child may still hold the H10

        proc.returncode = 0
        done = state.ui_state()["recording"]
        self.assertEqual(done["state"], "completed")
        self.assertFalse(done["active"])

    def test_recording_without_polar_has_no_status_or_flag(self):
        state = self._make_state()
        payload, _status = state.start_recording("night")
        self.assertNotIn("--with-polar", self.launcher.calls[0][0])
        self.assertIsNone(payload["polar"])

    def test_stop_waits_longer_before_sigkill_when_polar_is_on(self):
        for with_polar, expect_kill in ((False, True), (True, False)):
            terminator = TerminatorSpy()
            server = create_local_app_server(
                AppConfig(port=0, source="amused"),
                launcher=LauncherSpy(),
                terminator=terminator,
                recordings_base=self.recordings_base / str(with_polar),
                now_fn=lambda: _FIXED_NOW,
            )
            self.addCleanup(server.server_close)
            self.addCleanup(server.app_state.shutdown)
            state = server.app_state
            state.start_recording("session", with_polar=with_polar)
            state.stop_recording()
            state._recording.stop_signalled_at_seconds -= 10.0  # 10 s after Stop
            state.ui_state()
            killed = (4242, signal.SIGKILL) in terminator.signals
            self.assertEqual(killed, expect_kill, f"with_polar={with_polar}")

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

    def _write_progress_with_contact(self, output_dir, updated_at):
        channels = {
            channel: {
                "channel": channel,
                "status": "good",
                "fill": 1.0,
                "coverage": 1.0,
                "sample_count": 256,
                "reason_codes": [],
            }
            for channel in ("TP9", "AF7", "AF8", "TP10")
        }
        (output_dir / "progress.json").write_text(
            json.dumps(
                {
                    "updated_at": updated_at.isoformat(),
                    "elapsed_seconds": 30.0,
                    "frame_count": 500,
                    "contact": {
                        "source": "amused",
                        "connection_state": "connected",
                        "sequence": 500,
                        "timestamp_seconds": updated_at.timestamp(),
                        "stale": False,
                        "channels": channels,
                    },
                    "source_diagnostics": {
                        "last_packet_age_seconds": 0.5,
                        "decoder": {"eeg_rolling_sample_rate_hz": 128.0},
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_ui_state_shows_recorder_contact_while_recording(self):
        state = self._make_state()
        state.start_recording("session")
        output_dir = (self.recordings_base / "session" / "20260707_010000").resolve()
        self._write_progress_with_contact(output_dir, dt.datetime.now(dt.timezone.utc))

        payload = state.ui_state()

        self.assertEqual(payload["state"]["connection_state"], "disconnected")
        self.assertTrue(payload["contact"]["all_good"])
        self.assertEqual(payload["contact"]["channels"]["AF7"]["status"], "good")
        diagnostics = payload["source_diagnostics"]
        self.assertEqual(diagnostics["decoder"]["eeg_rolling_sample_rate_hz"], 128.0)
        self.assertGreaterEqual(diagnostics["last_packet_age_seconds"], 0.5)
        self.assertLess(diagnostics["last_packet_age_seconds"], 5.0)
        self.assertNotIn("contact", payload["recording"])

    def test_ui_state_marks_recorder_contact_stale_when_heartbeat_stops(self):
        state = self._make_state()
        state.start_recording("session")
        output_dir = (self.recordings_base / "session" / "20260707_010000").resolve()
        updated_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=60)
        self._write_progress_with_contact(output_dir, updated_at)

        payload = state.ui_state()

        contact = payload["contact"]
        self.assertTrue(contact["stale"])
        self.assertFalse(contact["all_good"])
        self.assertEqual(contact["channels"], {})
        self.assertGreater(payload["source_diagnostics"]["last_packet_age_seconds"], 60.0)

    def test_ui_state_falls_back_without_recorder_contact(self):
        state = self._make_state()
        state.start_recording("session")
        output_dir = (self.recordings_base / "session" / "20260707_010000").resolve()
        (output_dir / "progress.json").write_text(
            json.dumps({"elapsed_seconds": 5.0, "frame_count": 10}), encoding="utf-8"
        )

        payload = state.ui_state()

        self.assertEqual(payload["contact"]["connection_state"], "disconnected")
        self.assertFalse(payload["contact"]["all_good"])
        self.assertIsNone(payload["source_diagnostics"])

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


class TestLocalMuseAppReport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.reports = root / "reports"
        self.procs = []

        def launcher(command, log_path):
            proc = _FakeProc(pid=5000 + len(self.procs))
            self.procs.append((list(command), proc))
            return proc

        self.server = create_local_app_server(
            AppConfig(port=0, source="amused"),
            launcher=launcher,
            terminator=TerminatorSpy(),
            recordings_base=root / "recordings",
            reports_base=self.reports,
            now_fn=lambda: _FIXED_NOW,
        )
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.app_state.shutdown)
        self.state = self.server.app_state

    def finish_recording(self):
        payload, _ = self.state.start_recording("session")
        output_dir = Path(payload["output_dir"])
        (output_dir / "summary.json").write_text(json.dumps({"stop_reason": "duration_complete"}))
        self.procs[0][1].returncode = 0
        return output_dir

    def test_no_report_while_recording(self):
        self.state.start_recording("session")
        _payload, status = self.state.build_report()
        self.assertEqual(int(status), 409)

    def test_build_runs_the_script_and_reports_progress(self):
        output_dir = self.finish_recording()
        self.assertEqual(self.state.ui_state()["recording"]["report"]["state"], "none")

        payload, status = self.state.build_report()
        self.assertEqual(int(status), 200)
        command, report_proc = self.procs[1]
        report_file = (self.reports / "session" / f"{output_dir.name}.html").resolve()
        self.assertEqual(command[0], sys.executable)
        self.assertTrue(command[1].endswith("scripts/generate_nightly_report.py"))
        self.assertEqual(command[2:], [str(output_dir.resolve()), "--output", str(report_file)])
        self.assertEqual(payload["report"]["state"], "running")

        # A second click while it runs does not start another builder.
        self.state.build_report()
        self.assertEqual(len(self.procs), 2)

        report_file.write_text("<html>report</html>")
        report_proc.returncode = 0
        ready = self.state.ui_state()["recording"]["report"]
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(ready["url"], f"/reports/session/{output_dir.name}.html")

    def test_report_build_blocks_auto_update_restart(self):
        self.finish_recording()
        self.assertTrue(self.state.idle_for_update())
        self.state.build_report()
        self.assertFalse(self.state.idle_for_update())
        self.procs[1][1].returncode = 0
        self.assertTrue(self.state.idle_for_update())

    def test_concurrent_build_requests_start_one_builder(self):
        import threading as threads

        self.finish_recording()
        gate = threads.Event()
        original = self.state._launcher

        def slow_launcher(command, log_path):
            gate.wait(2)
            return original(command, log_path)

        self.state._launcher = slow_launcher
        results = []
        workers = [threads.Thread(target=lambda: results.append(self.state.build_report())) for _ in range(2)]
        for worker in workers:
            worker.start()
        time.sleep(0.2)
        gate.set()
        for worker in workers:
            worker.join(5)
        self.assertEqual(len(self.procs), 2)  # the recorder plus exactly one report builder
        self.assertEqual(sorted(int(status) for _payload, status in results), [200, 200])

    def test_failed_build_is_reported(self):
        self.finish_recording()
        self.state.build_report()
        self.procs[1][1].returncode = 1
        failed = self.state.ui_state()["recording"]["report"]
        self.assertEqual(failed["state"], "failed")
        self.assertTrue(failed["log_path"].endswith("report.log"))

    def test_reports_are_served_and_nothing_else(self):
        (self.reports / "session").mkdir(parents=True)
        (self.reports / "session" / "a.html").write_text("<html>hello</html>")
        (self.reports / "session" / "a.json").write_text("{}")
        thread = threading.Thread(target=self.server.serve_forever)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.shutdown)
        host, port = self.server.server_address
        base = f"http://{host}:{port}"
        with urllib.request.urlopen(f"{base}/reports/session/a.html", timeout=2) as response:
            self.assertIn("hello", response.read().decode())
        for bad in ("/reports/session/a.json", "/reports/../../../etc/passwd", "/reports/%2e%2e/%2e%2e/etc/hosts"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f"{base}{bad}", timeout=2)
            self.assertEqual(error.exception.code, 404, bad)


class TestLocalMuseAppMeditation(TestLocalMuseAppReport):
    def start(self, **overrides):
        body = {"conditions": ["focus", "open"], "blocks": 2, "block_minutes": 1, "settle_seconds": 30, "seed": 4}
        body.update(overrides)
        return self.state.start_meditation(body)

    def test_bad_plans_are_rejected(self):
        for overrides in ({"conditions": ["focus"]}, {"blocks": 1}, {"block_minutes": 0}, {"settle_seconds": -1}):
            _payload, status = self.start(**overrides)
            self.assertEqual(int(status), 400, overrides)
        self.assertEqual(self.procs, [])

    def test_start_writes_the_plan_and_records_long_enough(self):
        payload, status = self.start(with_polar=True)
        self.assertEqual(int(status), 200)
        command, _proc = self.procs[0]
        self.assertNotIn("--duration-hours", command)
        self.assertEqual(command[command.index("--duration-seconds") + 1], "210")  # 30 + 2 x 60 + 60 slack
        self.assertIn("--with-polar", command)
        self.assertIn("--duration-from-first-frame", command)
        output_dir = Path(payload["output_dir"])
        plan = json.loads((output_dir / "blocks.json").read_text())
        self.assertEqual([block["start_s"] for block in plan["blocks"]], [30.0, 90.0])
        self.assertEqual(payload["meditation"]["plan"]["conditions"], ["focus", "open"])
        self.assertIsNone(payload["meditation"]["first_frame_elapsed_seconds"])
        (output_dir / "progress.json").write_text(json.dumps({"elapsed_seconds": 12.0, "first_frame_elapsed_seconds": 4.5}))
        self.assertEqual(self.state.ui_state()["recording"]["meditation"]["first_frame_elapsed_seconds"], 4.5)

    def test_ratings_are_saved_into_blocks_json(self):
        payload, _ = self.start()
        output_dir = Path(payload["output_dir"])
        _payload, status = self.state.save_meditation_rating({"block_index": 1, "depth": "7", "sensory_fading": 4})
        self.assertEqual(int(status), 200)
        plan = json.loads((output_dir / "blocks.json").read_text())
        self.assertEqual((plan["blocks"][1]["depth"], plan["blocks"][1]["sensory_fading"]), (7.0, 4.0))
        self.assertIsNone(plan["blocks"][0]["depth"])
        for bad in ({"block_index": 1, "depth": 11}, {"block_index": 9, "depth": 3}, {"depth": 3}):
            _payload, status = self.state.save_meditation_rating(bad)
            self.assertEqual(int(status), 400, bad)

    def test_ratings_need_a_meditation_recording(self):
        self.state.start_recording("session")
        _payload, status = self.state.save_meditation_rating({"block_index": 0, "depth": 3})
        self.assertEqual(int(status), 409)

    def test_analyze_runs_analyze_meditation_and_links_the_report(self):
        payload, _ = self.start()
        output_dir = Path(payload["output_dir"])
        _payload, status = self.state.analyze_meditation()
        self.assertEqual(int(status), 409)  # still recording
        (output_dir / "summary.json").write_text(json.dumps({"stop_reason": "duration_complete"}))
        self.procs[0][1].returncode = 0

        payload, status = self.state.analyze_meditation()
        self.assertEqual(int(status), 200)
        command, analysis = self.procs[1]
        report_dir = (self.reports / "meditation" / output_dir.name).resolve()
        self.assertEqual(command[1:4], ["-m", "muse_tmr.cli.main", "analyze-meditation"])
        self.assertEqual(command[-4:], ["--blocks", str((output_dir / "blocks.json").resolve()), "--output-dir", str(report_dir)])
        self.assertEqual(payload["meditation"]["analysis"]["state"], "running")
        self.assertFalse(self.state.idle_for_update())

        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.html").write_text("<html>ok</html>")
        analysis.returncode = 0
        ready = self.state.ui_state()["recording"]["meditation"]["analysis"]
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(ready["url"], f"/reports/meditation/{output_dir.name}/report.html")

    def test_plain_recording_has_no_meditation_section(self):
        payload, _ = self.state.start_recording("session")
        self.assertIsNone(payload["meditation"])


class TestLocalMuseAppRecentRecordings(TestLocalMuseAppReport):
    def make_recording(self, kind, name, summary=None, blocks=False, polar=False):
        folder = self.state._recordings_base_resolved() / kind / name
        folder.mkdir(parents=True)
        if summary is not None:
            (folder / "summary.json").write_text(json.dumps(summary))
        if blocks:
            (folder / "blocks.json").write_text("{}")
        if polar:
            (folder / "polar").mkdir()
        return folder

    def test_lists_recordings_newest_first_with_their_reports(self):
        self.make_recording("night", "20261007_230000", {"duration_seconds": 28800, "stop_reason": "duration_complete"})
        self.make_recording("session", "20261008_235854", {"duration_seconds": 791, "stop_reason": "user_stopped"}, blocks=True, polar=True)
        (self.reports / "night").mkdir(parents=True)
        (self.reports / "night" / "20261007_230000.html").write_text("<html></html>")

        recordings = self.state.list_recordings()["recordings"]
        self.assertEqual([item["name"] for item in recordings], ["20261008_235854", "20261007_230000"])
        newest, older = recordings
        self.assertEqual((newest["stop_reason"], newest["meditation"], newest["with_polar"]), ("user_stopped", True, True))
        self.assertEqual(newest["started_at"], "2026-10-08T23:58:54")
        self.assertEqual(newest["report"]["state"], "none")
        self.assertEqual(newest["meditation_report"]["state"], "none")
        self.assertEqual(older["report"]["url"], "/reports/night/20261007_230000.html")
        self.assertIsNone(older["meditation_report"])

    def test_builds_for_an_older_recording_and_rejects_bad_input(self):
        folder = self.make_recording("session", "20261008_235854", {"stop_reason": "user_stopped"})
        entry, status = self.state.build_report_for("session", "20261008_235854")
        self.assertEqual(int(status), 200)
        self.assertEqual(entry["report"]["state"], "running")
        command, _proc = self.procs[0]
        self.assertEqual(command[2], str(folder.resolve()))
        self.assertFalse(self.state.idle_for_update())

        _entry, status = self.state.analyze_meditation_for("session", "20261008_235854")
        self.assertEqual(int(status), 409)  # no blocks.json
        for kind, name, expected in (
            ("bogus", "x", 400),
            ("session", "../night", 400),
            ("session", "..", 400),
            ("session", "20990101_000000", 404),
        ):
            _payload, status = self.state.build_report_for(kind, name)
            self.assertEqual(int(status), expected, (kind, name))

    def test_detached_recorder_is_still_live_after_an_app_restart(self):
        import os
        import subprocess

        folder = self.make_recording("session", "20261009_010000")
        # A recorder this app instance does not know about, with the folder on its command line.
        recorder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", str(folder.resolve())])
        self.addCleanup(recorder.wait)
        self.addCleanup(recorder.kill)
        (folder / "launch.json").write_text(json.dumps({"pid": recorder.pid}))
        _payload, status = self.state.build_report_for("session", folder.name)
        self.assertEqual(int(status), 409)
        self.assertTrue(self.state.list_recordings()["recordings"][0]["live"])

        # Same PID number but not this recording (PID reuse) and no heartbeat: finished.
        (folder / "launch.json").write_text(json.dumps({"pid": os.getpid()}))
        self.assertFalse(self.state.list_recordings()["recordings"][0]["live"])

    def test_cli_recording_is_live_while_its_heartbeat_moves(self):
        import os

        folder = self.make_recording("session", "20261009_020000")
        (folder / "progress.json").write_text("{}")
        self.assertTrue(self.state.list_recordings()["recordings"][0]["live"])
        old = time.time() - 600
        os.utime(folder / "progress.json", (old, old))
        self.assertFalse(self.state.list_recordings()["recordings"][0]["live"])
        (folder / "summary.json").write_text(json.dumps({"stop_reason": "duration_complete"}))
        self.assertFalse(self.state.list_recordings()["recordings"][0]["live"])

    def test_live_recording_cannot_be_reported_yet(self):
        payload, _ = self.state.start_recording("session")
        name = Path(payload["output_dir"]).name
        _payload, status = self.state.build_report_for("session", name)
        self.assertEqual(int(status), 409)
        entry = self.state.list_recordings()["recordings"][0]
        self.assertTrue(entry["live"])
        self.assertIsNone(entry["report"])


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
