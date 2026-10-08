"""Stdlib HTTP server for the local Muse setup app."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import mimetypes
import os
import posixpath
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

from muse_tmr.contact import (
    ContactGate,
    ContactGateConfig,
    ContactQualityConfig,
    ContactQualityMonitor,
    ContactQualitySnapshot,
    MockContactProvider,
    available_mock_contact_scenarios,
    builtin_contact_snapshots,
)

CONNECTION_STATES = ("disconnected", "scanning", "connecting", "connected", "error")

CAFFEINATE = "/usr/bin/caffeinate"

# The recorder rewrites progress.json every ~2 s while frames arrive.
RECORDER_HEARTBEAT_STALE_SECONDS = 10.0

# kind -> (preset, duration_hours, allow_short)
RECORDING_KINDS: Dict[str, Tuple[str, float, bool]] = {
    "night": ("p21", 8.0, False),
    "session": ("p1034", 1.0, True),
}


@dataclass
class RecordingHandle:
    kind: str
    output_dir: Path
    log_path: Path
    command: List[str]
    preset: str
    duration_seconds: float
    started_at_seconds: float
    pid: Optional[int] = None
    process: Optional[Any] = None  # Popen, or a fake in tests; None after app restart
    state: str = "launching"  # launching | running | stopping | completed | failed
    stop_signalled_at_seconds: Optional[float] = None


def _real_launcher(command: List[str], log_path: Path):
    """Spawn a detached recording process that outlives this app.

    start_new_session=True makes the child a session/process-group leader
    detached from the app's controlling terminal, so closing the terminal that
    launched the app does not signal the recorder. Its stdout/stderr go to a log
    file the app can tail.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(log_path, "ab", buffering=0)
    try:
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        # The child keeps its own dup'd copy of the fd; the parent does not need it.
        log_fh.close()


def _real_terminator(pid: int, sig: int) -> None:
    """Signal the whole process group led by ``pid`` (caffeinate + python)."""
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _read_json_tolerant(path: Path) -> Mapping[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _recorder_live_view(
    progress: Mapping[str, Any], now_seconds: float
) -> Optional[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
    """Contact snapshot and source diagnostics from the recorder's heartbeat.

    Returns None when progress.json carries no contact (older recorder, or no
    frame yet). A heartbeat older than RECORDER_HEARTBEAT_STALE_SECONDS means
    the recorder stopped getting frames, so the contact is reported stale with
    no channels rather than replaying the last good values.
    """
    contact = progress.get("contact")
    if not isinstance(contact, Mapping):
        return None
    heartbeat_age = _heartbeat_age_seconds(progress, now_seconds)
    if heartbeat_age is None or heartbeat_age > RECORDER_HEARTBEAT_STALE_SECONDS:
        contact = {**contact, "stale": True, "channels": {}}
    try:
        snapshot = ContactQualitySnapshot.from_dict(contact)
    except (KeyError, TypeError, ValueError):
        return None

    diagnostics = progress.get("source_diagnostics")
    if isinstance(diagnostics, Mapping):
        diagnostics = dict(diagnostics)
        packet_age = diagnostics.get("last_packet_age_seconds")
        if isinstance(packet_age, (int, float)) and heartbeat_age is not None:
            diagnostics["last_packet_age_seconds"] = packet_age + heartbeat_age
    else:
        diagnostics = None
    return snapshot.to_dict(), diagnostics


def _heartbeat_age_seconds(progress: Mapping[str, Any], now_seconds: float) -> Optional[float]:
    try:
        updated_at = dt.datetime.fromisoformat(str(progress["updated_at"]))
    except (KeyError, ValueError):
        return None
    return max(0.0, now_seconds - updated_at.timestamp())


def _expected_report_path(output_dir: Path) -> str:
    kind = output_dir.parent.name
    if kind in ("night", "session"):
        return str(Path("data/reports") / kind / f"{output_dir.name}.html")
    return str(Path("data/reports/nightly") / f"{output_dir.name}.html")


def _format_hours(hours: float) -> str:
    return str(int(hours)) if float(hours).is_integer() else str(hours)


@dataclass(frozen=True)
class AppConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    source: str = "mock"
    address: Optional[str] = None
    name_filter: str = "Muse"
    preset: str = "p1034"
    mock_scenario: str = "mixed_fair_good"
    mock_interval_seconds: float = 1.0
    gate_stability_seconds: float = 5.0

    def validate(self) -> None:
        if self.source not in {"mock", "amused"}:
            raise ValueError("app source must be mock or amused")
        if self.port < 0 or self.port > 65535:
            raise ValueError("port must be between 0 and 65535")
        if self.mock_scenario not in available_mock_contact_scenarios():
            raise ValueError(f"unknown mock contact scenario: {self.mock_scenario}")
        if self.mock_interval_seconds < 0:
            raise ValueError("mock_interval_seconds must be non-negative")
        if self.gate_stability_seconds < 0:
            raise ValueError("gate_stability_seconds must be non-negative")


class LocalMuseAppState:
    def __init__(
        self,
        config: AppConfig,
        *,
        launcher: Optional[Callable[[List[str], Path], Any]] = None,
        terminator: Optional[Callable[[int, int], None]] = None,
        recordings_base: Optional[Path] = None,
        now_fn: Optional[Callable[[], dt.datetime]] = None,
    ) -> None:
        config.validate()
        self.config = config
        self._launcher = launcher if launcher is not None else _real_launcher
        self._terminator = terminator if terminator is not None else _real_terminator
        self._recordings_base = Path(recordings_base) if recordings_base is not None else None
        self._now = now_fn if now_fn is not None else (lambda: dt.datetime.now())
        self._recording: Optional[RecordingHandle] = None
        self._lock = threading.Lock()
        self._connection_state = "disconnected"
        self._device_name: Optional[str] = None
        self._device_address: Optional[str] = config.address
        self._error_message: Optional[str] = None
        self._devices: Sequence[Mapping[str, Any]] = ()
        self._source = None
        self._contact_stop_requested = threading.Event()
        self._contact_thread: Optional[threading.Thread] = None
        self._contact_provider = (
            MockContactProvider.for_scenario(
                config.mock_scenario,
                interval_seconds=config.mock_interval_seconds,
                loop=True,
            )
            if config.source == "mock"
            else None
        )
        self._contact_monitor = (
            ContactQualityMonitor(
                source=config.source,
                config=ContactQualityConfig(sample_rate_hz=128.0),
            )
            if config.source != "mock"
            else None
        )
        self._contact_gate = ContactGate(
            ContactGateConfig(required_stability_seconds=config.gate_stability_seconds)
        )
        self._start_when_ready_requested = False
        self._last_contact_snapshot = None
        self._connected_at_seconds: Optional[float] = None
        self._session_started_at_seconds: Optional[float] = None
        self._contact_warning_count = 0
        self._contact_warning_events: List[Dict[str, Any]] = []
        self._active_contact_warning_started_at: Optional[float] = None
        self._active_contact_warning_channels: Tuple[str, ...] = ()
        self._active_contact_warning_reasons: Tuple[str, ...] = ()

    def health(self) -> Mapping[str, Any]:
        return {
            "ok": True,
            "service": "muse-tmr-local-app",
            "source": self.config.source,
        }

    def state(self) -> Mapping[str, Any]:
        with self._lock:
            return self._state_unlocked()

    def ui_state(self) -> Mapping[str, Any]:
        with self._lock:
            source = self._source
            snapshot = self._contact_snapshot_unlocked(advance_mock=True)
            gate = self._advance_gate_unlocked(snapshot)
            generated_at_seconds = time.time()
            state = self._state_unlocked(now_seconds=generated_at_seconds)
            contact = snapshot.to_dict()
            gate_payload = gate.to_dict()

        source_diagnostics = self._source_diagnostics(source)
        recording, progress = self._recording_payload_and_progress()
        if recording.get("active"):
            # The app released BLE to the recorder, so its own monitor sees
            # nothing; show what the recorder publishes instead.
            recorder_view = _recorder_live_view(progress, generated_at_seconds)
            if recorder_view is not None:
                contact, source_diagnostics = recorder_view

        return {
            "service": "muse-tmr-local-app",
            "generated_at_seconds": generated_at_seconds,
            "state": state,
            "contact": contact,
            "gate": gate_payload,
            "source_diagnostics": source_diagnostics,
            "recording": recording,
        }

    def contact(self) -> Mapping[str, Any]:
        with self._lock:
            snapshot = self._contact_snapshot_unlocked(advance_mock=True)
            self._advance_gate_unlocked(snapshot)
            return snapshot.to_dict()

    def gate(self) -> Mapping[str, Any]:
        with self._lock:
            snapshot = self._contact_snapshot_unlocked(advance_mock=False)
            return self._advance_gate_unlocked(snapshot).to_dict()

    def diagnostics(self) -> Mapping[str, Any]:
        with self._lock:
            source = self._source
            state = self._state_unlocked()
            contact = (
                self._last_contact_snapshot.to_dict()
                if self._last_contact_snapshot is not None
                else None
            )

        return {
            "service": "muse-tmr-local-app",
            "state": state,
            "contact": contact,
            "source_diagnostics": self._source_diagnostics(source),
        }

    def arm_gate(self) -> Mapping[str, Any]:
        with self._lock:
            snapshot = self._contact_snapshot_unlocked(advance_mock=False)
            self._start_when_ready_requested = True
            state = self._contact_gate.arm(snapshot)
            if state.ready:
                self._start_when_ready_requested = False
                state = self._contact_gate.start(snapshot)
                self._mark_session_started_unlocked()
            return state.to_dict()

    def start_session(self) -> Mapping[str, Any]:
        with self._lock:
            snapshot = self._contact_snapshot_unlocked(advance_mock=False)
            state = self._contact_gate.start(snapshot)
            if state.ready:
                self._start_when_ready_requested = False
                self._mark_session_started_unlocked()
            return state.to_dict()

    def scan(self) -> Mapping[str, Any]:
        self._set_state("scanning", error_message=None)
        try:
            if self.config.source == "mock":
                devices = (
                    {
                        "name": "Muse Mock Headband",
                        "address": self.config.address or "mock://muse-s",
                        "rssi": -42,
                    },
                )
            else:
                devices = tuple(_device_to_dict(device) for device in asyncio.run(self._amused_source().discover()))
            with self._lock:
                self._devices = devices
                self._connection_state = "disconnected"
                self._error_message = None if devices else "No Muse devices found"
                return self._state_unlocked(extra={"devices": list(devices)})
        except Exception as exc:
            self._set_state("error", error_message=str(exc))
            return self.state()

    def connect(self) -> Mapping[str, Any]:
        with self._lock:
            if self._connection_state == "connected":
                return self._state_unlocked()

        self._set_state("connecting", error_message=None)
        try:
            if self.config.source == "mock":
                with self._lock:
                    self._device_name = "Muse Mock Headband"
                    self._device_address = self.config.address or "mock://muse-s"
                    self._connection_state = "connected"
                    self._connected_at_seconds = time.time()
                    return self._state_unlocked()

            source = self._amused_source()
            metadata = asyncio.run(source.connect())
            with self._lock:
                self._source = source
                self._device_name = metadata.device_name
                self._device_address = metadata.device_id
                self._connection_state = "connected"
                self._error_message = None
                self._connected_at_seconds = time.time()
                state = self._state_unlocked()
            self._start_contact_stream(source)
            return state
        except Exception as exc:
            with self._lock:
                self._source = None
                self._contact_thread = None
            self._set_state("error", error_message=str(exc))
            return self.state()

    def disconnect(self) -> Mapping[str, Any]:
        source = None
        thread = None
        with self._lock:
            self._contact_stop_requested.set()
            thread = self._contact_thread
            self._contact_thread = None
            source = self._source
            self._source = None
            self._connection_state = "disconnected"
            self._device_name = None
            self._device_address = self.config.address
            self._connected_at_seconds = None
            self._error_message = None
            self._start_when_ready_requested = False
            self._reset_session_unlocked()
            self._contact_gate.disarm()
        if source is not None:
            asyncio.run(source.stop())
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        return self.state()

    def shutdown(self) -> None:
        # Intentionally does NOT stop a running recording: the recorder is a
        # detached process meant to outlive the app.
        self.disconnect()

    def start_recording(self, kind: Optional[str]) -> Tuple[Mapping[str, Any], HTTPStatus]:
        if kind not in RECORDING_KINDS:
            return {"error": "kind must be night or session"}, HTTPStatus.BAD_REQUEST
        if self.config.source != "amused":
            return {"error": "recording requires the live amused source"}, HTTPStatus.CONFLICT

        preset, duration_hours, _ = RECORDING_KINDS[kind]
        with self._lock:
            if self._recording is not None and self._recording_alive_unlocked():
                return {"error": "a recording is already running"}, HTTPStatus.CONFLICT
            output_dir = (
                self._recordings_base_resolved() / kind / self._now().strftime("%Y%m%d_%H%M%S")
            )
            command = self._build_record_command(kind, output_dir)
            handle = RecordingHandle(
                kind=kind,
                output_dir=output_dir,
                log_path=output_dir / "record.log",
                command=command,
                preset=preset,
                duration_seconds=duration_hours * 3600.0,
                started_at_seconds=time.time(),
                state="launching",
            )
            self._recording = handle

        # Release our own BLE grip on the headband BEFORE spawning the recorder;
        # the Muse allows only one connection at a time.
        self.disconnect()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            self._write_launch_json(handle)
            proc = self._launcher(command, handle.log_path)
        except Exception as exc:
            with self._lock:
                if self._recording is handle:
                    handle.state = "failed"
            return {"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR

        with self._lock:
            if self._recording is handle:
                handle.process = proc
                handle.pid = getattr(proc, "pid", None)
                handle.state = "running"
        self._write_launch_json(handle)
        return self._recording_payload(), HTTPStatus.OK

    def stop_recording(self) -> Tuple[Mapping[str, Any], HTTPStatus]:
        with self._lock:
            handle = self._recording
            if handle is None or not self._recording_alive_unlocked():
                return {"error": "no recording is running"}, HTTPStatus.CONFLICT
            pid = handle.pid
            handle.state = "stopping"
            handle.stop_signalled_at_seconds = time.time()

        if pid is not None:
            # SIGINT (not SIGTERM) so the recorder's finally-block runs: it closes
            # files cleanly and releases BLE. killpg reaches caffeinate + python.
            self._terminator(pid, signal.SIGINT)
        return self._recording_payload(), HTTPStatus.OK

    def _recording_alive_unlocked(self) -> bool:
        handle = self._recording
        if handle is None or handle.state in ("completed", "failed"):
            return False
        proc = handle.process
        if proc is not None:
            # poll() reaps a finished child, avoiding a zombie reporting as alive.
            return proc.poll() is None
        if handle.pid is not None:
            try:
                os.kill(handle.pid, 0)
                return True
            except (ProcessLookupError, PermissionError):
                return False
        # Slot reserved but not spawned yet.
        return handle.state == "launching"

    def _recording_payload(self) -> Mapping[str, Any]:
        return self._recording_payload_and_progress()[0]

    def _recording_payload_and_progress(self) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
        escalate_pid: Optional[int] = None
        with self._lock:
            handle = self._recording
            if handle is None:
                return {"active": False, "state": "idle"}, {}
            alive = self._recording_alive_unlocked()
            if (
                handle.state == "stopping"
                and alive
                and handle.pid is not None
                and handle.stop_signalled_at_seconds is not None
                and time.time() - handle.stop_signalled_at_seconds > 5.0
            ):
                escalate_pid = handle.pid
            snapshot = (
                handle.kind,
                handle.output_dir,
                handle.log_path,
                handle.pid,
                handle.preset,
                handle.duration_seconds,
                handle.started_at_seconds,
                handle.state,
            )

        if escalate_pid is not None:
            self._terminator(escalate_pid, signal.SIGKILL)

        kind, output_dir, log_path, pid, preset, duration, started, state = snapshot
        progress = _read_json_tolerant(output_dir / "progress.json")
        summary = _read_json_tolerant(output_dir / "summary.json")
        summary_available = bool(summary)

        if summary_available:
            state = "completed"
        elif not alive and state in ("running", "stopping"):
            state = "failed"

        if state in ("completed", "failed"):
            with self._lock:
                if self._recording is handle:
                    handle.state = state

        elapsed = progress.get("elapsed_seconds")
        if elapsed is None:
            elapsed = max(0.0, time.time() - started)

        reconnects = progress.get("reconnect_attempts")
        if reconnects is None:
            reconnects = summary.get("reconnect_attempts")

        return {
            "active": state in ("launching", "running", "stopping"),
            "kind": kind,
            "state": state,
            "pid": pid,
            "preset": preset,
            "output_dir": str(output_dir),
            "log_path": str(log_path),
            "report_path": _expected_report_path(output_dir),
            "started_at_seconds": started,
            "duration_seconds": duration,
            "elapsed_seconds": elapsed,
            "progress_fraction": min(1.0, elapsed / duration) if duration else None,
            "frame_count": progress.get("frame_count"),
            "battery_percent": progress.get("battery_percent"),
            "reconnect_attempts": reconnects,
            "last_event": progress.get("last_event") or summary.get("stop_reason"),
            "summary_available": summary_available,
        }, progress

    def _build_record_command(self, kind: str, output_dir: Path) -> List[str]:
        preset, duration_hours, allow_short = RECORDING_KINDS[kind]
        command = [
            CAFFEINATE,
            "-s",
            sys.executable,
            "-m",
            "muse_tmr.cli.main",
            "record",
            "--source",
            "amused",
            "--preset",
            preset,
            "--duration-hours",
            _format_hours(duration_hours),
            "--no-data-timeout-seconds",
            "45",
            "--max-reconnect-attempts",
            "1000",
            "--output-dir",
            str(output_dir.resolve()),
            "--quiet",
        ]
        if allow_short:
            command.append("--allow-short")
        return command

    def _recordings_base_resolved(self) -> Path:
        if self._recordings_base is not None:
            return self._recordings_base
        from muse_tmr.cli.main import _default_path_base

        return _default_path_base() / "data" / "recordings"

    def _write_launch_json(self, handle: RecordingHandle) -> None:
        payload = {
            "kind": handle.kind,
            "preset": handle.preset,
            "pid": handle.pid,
            "duration_seconds": handle.duration_seconds,
            "started_at_seconds": handle.started_at_seconds,
            "command": list(handle.command),
            "log_path": str(handle.log_path),
            "output_dir": str(handle.output_dir),
        }
        try:
            handle.output_dir.mkdir(parents=True, exist_ok=True)
            (handle.output_dir / "launch.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        except OSError:
            pass

    def _state_unlocked(
        self,
        extra: Optional[Mapping[str, Any]] = None,
        now_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        now = time.time() if now_seconds is None else float(now_seconds)
        payload: Dict[str, Any] = {
            "source": self.config.source,
            "connection_state": self._connection_state,
            "connected_at_seconds": self._connected_at_seconds,
            "connected_elapsed_seconds": (
                now - self._connected_at_seconds
                if self._connected_at_seconds is not None
                else None
            ),
            "device": (
                {
                    "name": self._device_name,
                    "address": self._device_address,
                }
                if self._device_name or self._device_address
                else None
            ),
            "error_message": self._error_message,
            "devices": list(self._devices),
            "mock": {
                "scenario": self.config.mock_scenario,
                "interval_seconds": self.config.mock_interval_seconds,
            }
            if self.config.source == "mock"
            else None,
            "session": self._session_payload_unlocked(now),
            "available_states": list(CONNECTION_STATES),
        }
        if extra:
            payload.update(dict(extra))
        return payload

    def _source_diagnostics(self, source) -> Optional[Mapping[str, Any]]:
        return (
            source.diagnostics()
            if source is not None and hasattr(source, "diagnostics")
            else None
        )

    def _set_state(self, connection_state: str, error_message: Optional[str] = None) -> None:
        with self._lock:
            self._connection_state = connection_state
            self._error_message = error_message

    def _advance_gate_unlocked(self, snapshot: ContactQualitySnapshot):
        state = self._contact_gate.update(snapshot)
        if self._start_when_ready_requested and state.ready:
            self._start_when_ready_requested = False
            state = self._contact_gate.start(snapshot)
            self._mark_session_started_unlocked()
            return state
        if state.state == "running" and self._session_started_at_seconds is None:
            self._mark_session_started_unlocked()
        self._track_contact_warning_unlocked(snapshot, state)
        return state

    def _mark_session_started_unlocked(self) -> None:
        if self._session_started_at_seconds is not None:
            return
        self._session_started_at_seconds = time.time()
        self._contact_warning_count = 0
        self._contact_warning_events = []
        self._active_contact_warning_started_at = None
        self._active_contact_warning_channels = ()
        self._active_contact_warning_reasons = ()

    def _reset_session_unlocked(self) -> None:
        self._session_started_at_seconds = None
        self._contact_warning_count = 0
        self._contact_warning_events = []
        self._active_contact_warning_started_at = None
        self._active_contact_warning_channels = ()
        self._active_contact_warning_reasons = ()

    def _session_payload_unlocked(self, now: float) -> Dict[str, Any]:
        active_warning = None
        if self._active_contact_warning_started_at is not None:
            active_warning = {
                "started_at_seconds": self._active_contact_warning_started_at,
                "elapsed_seconds": now - self._active_contact_warning_started_at,
                "channels": list(self._active_contact_warning_channels),
                "reason_codes": list(self._active_contact_warning_reasons),
            }
        return {
            "running": self._session_started_at_seconds is not None,
            "started_at_seconds": self._session_started_at_seconds,
            "elapsed_seconds": (
                now - self._session_started_at_seconds
                if self._session_started_at_seconds is not None
                else None
            ),
            "contact_warning_count": self._contact_warning_count,
            "active_contact_warning": active_warning,
            "contact_warning_events": list(self._contact_warning_events[-20:]),
        }

    def _track_contact_warning_unlocked(self, snapshot: ContactQualitySnapshot, gate_state) -> None:
        if gate_state.state != "running" or self._session_started_at_seconds is None:
            return

        bad_channels = []
        reasons = []
        for channel in snapshot.required_channels:
            channel_state = snapshot.channels.get(channel)
            if channel_state is None or channel_state.status == "good":
                continue
            bad_channels.append(f"{channel} {channel_state.status}")
            reasons.extend(channel_state.reason_codes)

        now = time.time()
        if bad_channels:
            bad_tuple = tuple(bad_channels)
            reason_tuple = tuple(dict.fromkeys(str(reason) for reason in reasons if reason))
            if self._active_contact_warning_started_at is None:
                self._active_contact_warning_started_at = now
                self._active_contact_warning_channels = bad_tuple
                self._active_contact_warning_reasons = reason_tuple
                self._contact_warning_count += 1
                self._append_contact_warning_event_unlocked(
                    {
                        "timestamp_seconds": now,
                        "kind": "contact_drop",
                        "channels": list(bad_tuple),
                        "reason_codes": list(reason_tuple),
                        "duration_seconds": None,
                    }
                )
            else:
                self._active_contact_warning_channels = bad_tuple
                self._active_contact_warning_reasons = reason_tuple
            return

        if self._active_contact_warning_started_at is None:
            return

        duration = now - self._active_contact_warning_started_at
        for event in reversed(self._contact_warning_events):
            if event.get("kind") == "contact_drop" and event.get("duration_seconds") is None:
                event["duration_seconds"] = duration
                break
        self._append_contact_warning_event_unlocked(
            {
                "timestamp_seconds": now,
                "kind": "contact_recovered",
                "channels": [],
                "reason_codes": [],
                "duration_seconds": duration,
            }
        )
        self._active_contact_warning_started_at = None
        self._active_contact_warning_channels = ()
        self._active_contact_warning_reasons = ()

    def _append_contact_warning_event_unlocked(self, event: Dict[str, Any]) -> None:
        self._contact_warning_events.append(event)
        if len(self._contact_warning_events) > 50:
            del self._contact_warning_events[:-50]

    def _amused_source(self):
        from muse_tmr.sources.amused_source import AmusedSource

        if self._source is None:
            self._source = AmusedSource(
                address=self.config.address,
                name_filter=self.config.name_filter,
                preset=self.config.preset,
                duration_seconds=0,
                verbose=False,
            )
        return self._source

    def _contact_snapshot_unlocked(self, advance_mock: bool):
        if self._contact_provider is not None:
            if advance_mock or self._last_contact_snapshot is None:
                self._last_contact_snapshot = self._contact_provider.next_snapshot()
            if self._connection_state != "connected":
                missing = builtin_contact_snapshots("all_missing")[0].to_dict()
                missing["source"] = self.config.source
                missing["connection_state"] = self._connection_state
                return ContactQualitySnapshot.from_dict(missing)
            return self._last_contact_snapshot
        if self._contact_monitor is not None:
            self._last_contact_snapshot = self._contact_monitor.snapshot(
                connection_state=self._connection_state,
            )
            return self._last_contact_snapshot
        snapshot = builtin_contact_snapshots("all_missing")[0]
        self._last_contact_snapshot = snapshot
        return snapshot

    def _start_contact_stream(self, source) -> None:
        if self._contact_monitor is None:
            return
        with self._lock:
            if self._contact_thread is not None and self._contact_thread.is_alive():
                return
            self._contact_stop_requested.clear()
            thread = threading.Thread(
                target=self._run_contact_stream,
                args=(source,),
                daemon=True,
            )
            self._contact_thread = thread
        thread.start()

    def _run_contact_stream(self, source) -> None:
        async def consume() -> None:
            try:
                async for frame in source.stream():
                    if self._contact_stop_requested.is_set():
                        break
                    with self._lock:
                        assert self._contact_monitor is not None
                        self._contact_monitor.update(frame)
            except Exception as exc:
                self._set_state("error", error_message=str(exc))

        asyncio.run(consume())


class LocalMuseAppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address,
        RequestHandlerClass,
        app_state: LocalMuseAppState,
        static_dir: Path,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.app_state = app_state
        self.static_dir = static_dir


class LocalMuseAppHandler(BaseHTTPRequestHandler):
    server: LocalMuseAppServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self._write_json(self.server.app_state.health())
            return
        if path == "/api/muse/ui-state":
            self._write_json(self.server.app_state.ui_state())
            return
        if path == "/api/muse/state":
            self._write_json(self.server.app_state.state())
            return
        if path == "/api/muse/contact":
            self._write_json(self.server.app_state.contact())
            return
        if path == "/api/muse/contact/stream":
            self._write_contact_stream(parse_qs(parsed.query))
            return
        if path == "/api/muse/gate":
            self._write_json(self.server.app_state.gate())
            return
        if path == "/api/muse/diagnostics":
            self._write_json(self.server.app_state.diagnostics())
            return
        self._serve_static()

    def do_POST(self) -> None:
        if self.path == "/api/muse/scan":
            self._write_json(self.server.app_state.scan())
            return
        if self.path == "/api/muse/connect":
            self._write_json(self.server.app_state.connect())
            return
        if self.path == "/api/muse/disconnect":
            self._write_json(self.server.app_state.disconnect())
            return
        if self.path == "/api/muse/start-when-ready":
            self._write_json(self.server.app_state.arm_gate())
            return
        if self.path == "/api/session/start":
            state = self.server.app_state.start_session()
            status = HTTPStatus.OK if state.get("ready") else HTTPStatus.CONFLICT
            self._write_json(state, status=status)
            return
        if self.path == "/api/session/record":
            body = self._read_json_body()
            payload, status = self.server.app_state.start_recording(body.get("kind"))
            self._write_json(payload, status=status)
            return
        if self.path == "/api/session/record/stop":
            payload, status = self.server.app_state.stop_recording()
            self._write_json(payload, status=status)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "unknown app endpoint")

    def _read_json_body(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return {}
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def log_message(self, format: str, *args) -> None:
        return

    def _write_json(self, payload: Mapping[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_contact_stream(self, params: Mapping[str, Sequence[str]]) -> None:
        count = int(params.get("count", ["0"])[0] or "0")
        interval_seconds = float(params.get("interval", ["1.0"])[0] or "1.0")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        sent = 0
        while count <= 0 or sent < count:
            payload = json.dumps(self.server.app_state.contact(), sort_keys=True)
            event = f"event: contact\ndata: {payload}\n\n".encode("utf-8")
            try:
                self.wfile.write(event)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break
            sent += 1
            if interval_seconds > 0 and (count <= 0 or sent < count):
                time.sleep(interval_seconds)

    def _serve_static(self) -> None:
        relative_path = self.path.split("?", 1)[0]
        if relative_path in {"", "/"}:
            relative_path = "/index.html"
        normalized = posixpath.normpath(relative_path).lstrip("/")
        if normalized.startswith("../") or normalized == "..":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        static_root = self.server.static_dir.resolve()
        file_path = (self.server.static_dir / normalized).resolve()
        if not _is_relative_to(file_path, static_root) or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        body = file_path.read_bytes()
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_local_app_server(
    config: AppConfig,
    *,
    launcher: Optional[Callable[[List[str], Path], Any]] = None,
    terminator: Optional[Callable[[int, int], None]] = None,
    recordings_base: Optional[Path] = None,
    now_fn: Optional[Callable[[], dt.datetime]] = None,
) -> LocalMuseAppServer:
    config.validate()
    static_dir = resources.files("muse_tmr.app").joinpath("static")
    return LocalMuseAppServer(
        (config.host, config.port),
        LocalMuseAppHandler,
        app_state=LocalMuseAppState(
            config,
            launcher=launcher,
            terminator=terminator,
            recordings_base=recordings_base,
            now_fn=now_fn,
        ),
        static_dir=Path(str(static_dir)),
    )


def run_local_app(config: AppConfig) -> int:
    server = create_local_app_server(config)
    host, port = server.server_address
    print(f"Muse TMR local app serving at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.app_state.shutdown()
        server.server_close()
    return 0


def _device_to_dict(device) -> Mapping[str, Any]:
    return {
        "name": device.name,
        "address": device.address,
        "rssi": device.rssi,
    }


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
