"""Stdlib HTTP server for the local Muse setup app."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import posixpath
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
from urllib.parse import parse_qs, urlparse

from muse_tmr.contact import (
    ContactGate,
    ContactGateConfig,
    ContactQualityMonitor,
    ContactQualitySnapshot,
    MockContactProvider,
    available_mock_contact_scenarios,
    builtin_contact_snapshots,
)

CONNECTION_STATES = ("disconnected", "scanning", "connecting", "connected", "error")


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
    def __init__(self, config: AppConfig) -> None:
        config.validate()
        self.config = config
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
            ContactQualityMonitor(source=config.source)
            if config.source != "mock"
            else None
        )
        self._contact_gate = ContactGate(
            ContactGateConfig(required_stability_seconds=config.gate_stability_seconds)
        )
        self._last_contact_snapshot = None

    def health(self) -> Mapping[str, Any]:
        return {
            "ok": True,
            "service": "muse-tmr-local-app",
            "source": self.config.source,
        }

    def state(self) -> Mapping[str, Any]:
        with self._lock:
            return self._state_unlocked()

    def contact(self) -> Mapping[str, Any]:
        with self._lock:
            snapshot = self._contact_snapshot_unlocked(advance_mock=True)
            self._contact_gate.update(snapshot)
            return snapshot.to_dict()

    def gate(self) -> Mapping[str, Any]:
        with self._lock:
            snapshot = self._contact_snapshot_unlocked(advance_mock=False)
            return self._contact_gate.update(snapshot).to_dict()

    def arm_gate(self) -> Mapping[str, Any]:
        with self._lock:
            snapshot = self._contact_snapshot_unlocked(advance_mock=False)
            return self._contact_gate.arm(snapshot).to_dict()

    def start_session(self) -> Mapping[str, Any]:
        with self._lock:
            snapshot = self._contact_snapshot_unlocked(advance_mock=False)
            return self._contact_gate.start(snapshot).to_dict()

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
        self._set_state("connecting", error_message=None)
        try:
            if self.config.source == "mock":
                with self._lock:
                    self._device_name = "Muse Mock Headband"
                    self._device_address = self.config.address or "mock://muse-s"
                    self._connection_state = "connected"
                    return self._state_unlocked()

            source = self._amused_source()
            metadata = asyncio.run(source.connect())
            with self._lock:
                self._source = source
                self._device_name = metadata.device_name
                self._device_address = metadata.device_id
                self._connection_state = "connected"
                self._error_message = None
                state = self._state_unlocked()
            self._start_contact_stream(source)
            return state
        except Exception as exc:
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
            self._error_message = None
        if source is not None:
            asyncio.run(source.stop())
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        return self.state()

    def shutdown(self) -> None:
        self.disconnect()

    def _state_unlocked(self, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "source": self.config.source,
            "connection_state": self._connection_state,
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
            "available_states": list(CONNECTION_STATES),
        }
        if extra:
            payload.update(dict(extra))
        return payload

    def _set_state(self, connection_state: str, error_message: Optional[str] = None) -> None:
        with self._lock:
            self._connection_state = connection_state
            self._error_message = error_message

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
        self._contact_stop_requested.clear()
        thread = threading.Thread(
            target=self._run_contact_stream,
            args=(source,),
            daemon=True,
        )
        with self._lock:
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
        self.send_error(HTTPStatus.NOT_FOUND, "unknown app endpoint")

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


def create_local_app_server(config: AppConfig) -> LocalMuseAppServer:
    config.validate()
    static_dir = resources.files("muse_tmr.app").joinpath("static")
    return LocalMuseAppServer(
        (config.host, config.port),
        LocalMuseAppHandler,
        app_state=LocalMuseAppState(config),
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
