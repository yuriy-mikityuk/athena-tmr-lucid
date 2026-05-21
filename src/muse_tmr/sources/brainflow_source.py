"""Optional BrainFlow source adapter for Muse S Athena.

BrainFlow is kept as an optional acquisition backend. Importing this module does
not import BrainFlow; the dependency is loaded only when the source is used.
"""

from __future__ import annotations

import asyncio
import importlib
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Mapping, Optional, Sequence, Tuple

from muse_tmr.data.sample_types import (
    BatterySample,
    EEGSample,
    IMUSample,
    MuseFrame,
    PPGSample,
)
from muse_tmr.sources.base_source import BaseMuseSource, MuseDeviceInfo, MuseSourceMetadata

BRAINFLOW_SOURCE_NAME = "brainflow"
DEFAULT_BRAINFLOW_BOARD = "MUSE_S_ATHENA_BOARD"
DEFAULT_BRAINFLOW_PRESET = "p1041"


class BrainFlowDependencyError(RuntimeError):
    """Raised when the optional BrainFlow dependency is unavailable."""


@dataclass(frozen=True)
class BrainFlowSourceConfig:
    board_name: str = DEFAULT_BRAINFLOW_BOARD
    preset: str = DEFAULT_BRAINFLOW_PRESET
    low_latency: bool = True
    address: Optional[str] = None
    serial_number: Optional[str] = None
    name_filter: str = "Muse"
    duration_seconds: float = 0.0
    poll_interval_seconds: float = 0.05
    max_chunk_samples: int = 256
    streamer_params: str = ""
    connect_timeout_seconds: float = 20.0
    stream_start_timeout_seconds: float = 10.0
    stop_timeout_seconds: float = 10.0
    session_cooldown_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not self.board_name:
            raise ValueError("board_name must be non-empty")
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if self.max_chunk_samples <= 0:
            raise ValueError("max_chunk_samples must be positive")
        if self.connect_timeout_seconds <= 0:
            raise ValueError("connect_timeout_seconds must be positive")
        if self.stream_start_timeout_seconds <= 0:
            raise ValueError("stream_start_timeout_seconds must be positive")
        if self.stop_timeout_seconds <= 0:
            raise ValueError("stop_timeout_seconds must be positive")
        if self.session_cooldown_seconds < 0:
            raise ValueError("session_cooldown_seconds must be non-negative")


class BrainFlowSource(BaseMuseSource):
    """Stream MuseFrames from BrainFlow's Muse S Athena board support."""

    source_name = BRAINFLOW_SOURCE_NAME
    strategy = "optional-brainflow"

    def __init__(
        self,
        config: Optional[BrainFlowSourceConfig] = None,
        *,
        brainflow_backend: Optional[object] = None,
    ) -> None:
        self.config = config or BrainFlowSourceConfig()
        self._backend = brainflow_backend
        self._board = None
        self._board_id: Optional[int] = None
        self._prepared = False
        self._streaming = False
        self._stop_requested = False
        self.metadata: Optional[MuseSourceMetadata] = None
        self.frame_count = 0
        self.batch_count = 0
        self.last_poll_monotonic: Optional[float] = None
        self.last_frame_timestamp: Optional[float] = None
        self.disconnect_reason: Optional[str] = None

    async def discover(self) -> Sequence[MuseDeviceInfo]:
        backend = self._get_backend()
        board_id = backend.board_id_value(self.config.board_name)
        name = f"BrainFlow Muse S Athena ({self.config.board_name})"
        if self.config.name_filter and self.config.name_filter.lower() not in name.lower():
            return ()
        return (
            MuseDeviceInfo(
                name=name,
                address=self.config.address or "brainflow://auto",
                rssi=0,
                metadata={
                    "source": self.source_name,
                    "board_id": str(board_id),
                    "preset": self.config.preset,
                    "discovery": "configured" if self.config.address else "brainflow-autodiscovery",
                },
            ),
        )

    async def connect(self, device: Optional[MuseDeviceInfo] = None) -> MuseSourceMetadata:
        backend = self._get_backend()
        board_id = backend.board_id_value(self.config.board_name)
        params = backend.input_params()
        address = self.config.address
        if device is not None and device.address != "brainflow://auto":
            address = device.address
        if address:
            setattr(params, "mac_address", address)
        if self.config.serial_number:
            setattr(params, "serial_number", self.config.serial_number)
        setattr(params, "timeout", int(math.ceil(self.config.connect_timeout_seconds)))
        if self.config.preset:
            setattr(params, "other_info", self._other_info())

        board = backend.board_shim(board_id, params)
        try:
            await _run_blocking_with_timeout(
                board.prepare_session,
                self.config.connect_timeout_seconds,
                "BrainFlow prepare_session",
            )
        except TimeoutError as exc:
            self.disconnect_reason = "connect_timeout"
            raise RuntimeError(str(exc)) from exc
        self._board = board
        self._board_id = board_id
        self._prepared = True
        self._streaming = False
        self._stop_requested = False
        self.frame_count = 0
        self.batch_count = 0
        self.disconnect_reason = None

        self.metadata = MuseSourceMetadata(
            source_name=self.source_name,
            device_name=self.config.serial_number or self.config.board_name,
            device_id=address or "brainflow://auto",
            capabilities={
                "eeg": True,
                "imu": True,
                "ppg": True,
                "heart_rate": False,
                "battery": True,
                "raw_packets": False,
            },
            metadata={
                "strategy": self.strategy,
                "board_name": self.config.board_name,
                "board_id": str(board_id),
                "preset": self.config.preset,
                "low_latency": str(self.config.low_latency).lower(),
            },
        )
        return self.metadata

    async def stream(self) -> AsyncIterator[MuseFrame]:
        if self._board is None:
            await self.connect()
        assert self._board is not None
        assert self._board_id is not None

        if not self._streaming:
            try:
                await _run_blocking_with_timeout(
                    lambda: self._board.start_stream(
                        self.config.max_chunk_samples * 10,
                        self.config.streamer_params,
                    ),
                    self.config.stream_start_timeout_seconds,
                    "BrainFlow start_stream",
                )
            except TimeoutError as exc:
                self.disconnect_reason = "stream_start_timeout"
                raise RuntimeError(str(exc)) from exc
            self._streaming = True

        try:
            deadline = (
                time.monotonic() + self.config.duration_seconds
                if self.config.duration_seconds > 0
                else None
            )
            while not self._stop_requested and (deadline is None or time.monotonic() < deadline):
                frames = await asyncio.to_thread(self._poll_frames)
                if frames:
                    for frame in frames:
                        self.frame_count += 1
                        self.last_frame_timestamp = frame.timestamp
                        yield frame
                    continue
                await asyncio.sleep(self.config.poll_interval_seconds)
        finally:
            await self.stop()

    async def stop(self) -> None:
        self._stop_requested = True
        board = self._board
        if board is None:
            return
        try:
            if self._streaming:
                try:
                    await _run_blocking_with_timeout(
                        board.stop_stream,
                        self.config.stop_timeout_seconds,
                        "BrainFlow stop_stream",
                    )
                except TimeoutError:
                    self.disconnect_reason = "stop_timeout"
        finally:
            self._streaming = False
            try:
                if self._prepared:
                    try:
                        await _run_blocking_with_timeout(
                            board.release_session,
                            self.config.stop_timeout_seconds,
                            "BrainFlow release_session",
                        )
                    except TimeoutError:
                        self.disconnect_reason = "release_timeout"
            finally:
                self._prepared = False
                self._board = None
                self._board_id = None
                if self.config.session_cooldown_seconds > 0:
                    await asyncio.sleep(self.config.session_cooldown_seconds)

    def diagnostics(self) -> Mapping[str, Any]:
        return {
            "source": self.source_name,
            "strategy": self.strategy,
            "board_name": self.config.board_name,
            "preset": self.config.preset,
            "frame_count": self.frame_count,
            "batch_count": self.batch_count,
            "last_frame_timestamp": self.last_frame_timestamp,
            "connect_timeout_seconds": self.config.connect_timeout_seconds,
            "session_cooldown_seconds": self.config.session_cooldown_seconds,
            "last_poll_age_seconds": (
                time.monotonic() - self.last_poll_monotonic
                if self.last_poll_monotonic is not None
                else None
            ),
            "disconnect_reason": self.disconnect_reason,
        }

    def _get_backend(self):
        if self._backend is None:
            self._backend = _load_brainflow_backend()
        return self._backend

    def _other_info(self) -> str:
        return f"preset={self.config.preset};low_latency={str(self.config.low_latency).lower()}"

    def _poll_frames(self) -> Tuple[MuseFrame, ...]:
        assert self._board is not None
        assert self._board_id is not None
        backend = self._get_backend()
        self.last_poll_monotonic = time.monotonic()
        frames = []

        default_preset = backend.preset_value("DEFAULT_PRESET")
        eeg_data = _get_board_data(self._board, self.config.max_chunk_samples, default_preset)
        eeg_frame = _eeg_frame_from_data(backend, self._board_id, default_preset, eeg_data)
        if eeg_frame is not None:
            frames.append(eeg_frame)

        auxiliary_preset = backend.preset_value("AUXILIARY_PRESET")
        imu_data = _get_board_data(self._board, self.config.max_chunk_samples, auxiliary_preset)
        imu_frame = _imu_frame_from_data(backend, self._board_id, auxiliary_preset, imu_data)
        if imu_frame is not None:
            frames.append(imu_frame)

        ancillary_preset = backend.preset_value("ANCILLARY_PRESET")
        ancillary_data = _get_board_data(
            self._board,
            self.config.max_chunk_samples,
            ancillary_preset,
        )
        ancillary_frame = _ancillary_frame_from_data(
            backend,
            self._board_id,
            ancillary_preset,
            ancillary_data,
        )
        if ancillary_frame is not None:
            frames.append(ancillary_frame)

        if frames:
            self.batch_count += 1
        return tuple(frames)


class _BrainFlowBackend:
    name = "brainflow"

    def __init__(self, module) -> None:
        self._module = module

    def board_id_value(self, name: str) -> int:
        return _enum_value(getattr(self._module.BoardIds, name))

    def preset_value(self, name: str) -> int:
        return _enum_value(getattr(self._module.BrainFlowPresets, name))

    def input_params(self):
        return self._module.BrainFlowInputParams()

    def board_shim(self, board_id: int, params):
        return self._module.BoardShim(board_id, params)

    def eeg_channels(self, board_id: int, preset: int) -> Tuple[int, ...]:
        return _safe_channel_tuple(self._module.BoardShim.get_eeg_channels, board_id, preset)

    def eeg_names(self, board_id: int, preset: int) -> Tuple[str, ...]:
        try:
            return tuple(
                str(name)
                for name in self._module.BoardShim.get_eeg_names(board_id, preset)
            )
        except Exception:
            return ()

    def other_channels(self, board_id: int, preset: int) -> Tuple[int, ...]:
        return _safe_channel_tuple(self._module.BoardShim.get_other_channels, board_id, preset)

    def accel_channels(self, board_id: int, preset: int) -> Tuple[int, ...]:
        return _safe_channel_tuple(self._module.BoardShim.get_accel_channels, board_id, preset)

    def gyro_channels(self, board_id: int, preset: int) -> Tuple[int, ...]:
        return _safe_channel_tuple(self._module.BoardShim.get_gyro_channels, board_id, preset)

    def optical_channels(self, board_id: int, preset: int) -> Tuple[int, ...]:
        channels = _safe_channel_tuple(
            self._module.BoardShim.get_optical_channels,
            board_id,
            preset,
        )
        if channels:
            return channels
        return _safe_channel_tuple(self._module.BoardShim.get_ppg_channels, board_id, preset)

    def battery_channel(self, board_id: int, preset: int) -> Optional[int]:
        try:
            return int(self._module.BoardShim.get_battery_channel(board_id, preset))
        except Exception:
            return None

    def timestamp_channel(self, board_id: int, preset: int) -> Optional[int]:
        try:
            return int(self._module.BoardShim.get_timestamp_channel(board_id, preset))
        except Exception:
            return None


def _load_brainflow_backend() -> _BrainFlowBackend:
    try:
        module = importlib.import_module("brainflow.board_shim")
    except ImportError as exc:
        raise BrainFlowDependencyError(
            "BrainFlow source requires optional dependency `brainflow>=5.22.1`. "
            "Install with `pip install -e .[brainflow]` before using --source brainflow."
        ) from exc
    return _BrainFlowBackend(module)


async def _run_blocking_with_timeout(
    func: Callable[[], Any],
    timeout_seconds: float,
    operation_name: str,
) -> Any:
    call = _BlockingCall(func)
    call.start()
    deadline = time.monotonic() + timeout_seconds
    while not call.done.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{operation_name} timed out after {timeout_seconds:.1f}s")
        await asyncio.sleep(min(0.05, remaining))
    return call.result()


class _BlockingCall:
    def __init__(self, func: Callable[[], Any]) -> None:
        self.func = func
        self.done = threading.Event()
        self.value = None
        self.error: Optional[BaseException] = None

    def start(self) -> None:
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def result(self) -> Any:
        if self.error is not None:
            raise self.error
        return self.value

    def _run(self) -> None:
        try:
            self.value = self.func()
        except BaseException as exc:
            self.error = exc
        finally:
            self.done.set()


def _safe_channel_tuple(func, board_id: int, preset: int) -> Tuple[int, ...]:
    try:
        return tuple(int(channel) for channel in func(board_id, preset))
    except Exception:
        return ()


def _enum_value(value: Any) -> int:
    return int(getattr(value, "value", value))


def _get_board_data(board, max_samples: int, preset: int):
    try:
        return board.get_board_data(max_samples, preset)
    except TypeError:
        return board.get_board_data(preset=preset)


def _eeg_frame_from_data(backend, board_id: int, preset: int, data) -> Optional[MuseFrame]:
    if _sample_count(data) == 0:
        return None
    timestamp = _timestamp_from_data(backend, board_id, preset, data)
    eeg_channels = backend.eeg_channels(board_id, preset)
    other_channels = tuple(
        channel
        for channel in backend.other_channels(board_id, preset)
        if channel not in eeg_channels
    )
    eeg_names = backend.eeg_names(board_id, preset)
    channels = {}
    for idx, channel in enumerate(eeg_channels):
        name = eeg_names[idx] if idx < len(eeg_names) else f"EEG_{idx}"
        channels[name] = _row_series(data, channel)
    for idx, channel in enumerate(other_channels):
        channels[f"OTHER_{idx}"] = _row_series(data, channel)
    if not channels:
        return None
    eeg = EEGSample(timestamp=timestamp, channels_uv=channels, source=BRAINFLOW_SOURCE_NAME)
    return MuseFrame(timestamp=timestamp, eeg=eeg, source=BRAINFLOW_SOURCE_NAME)


def _imu_frame_from_data(backend, board_id: int, preset: int, data) -> Optional[MuseFrame]:
    if _sample_count(data) == 0:
        return None
    timestamp = _timestamp_from_data(backend, board_id, preset, data)
    accel_rows = _axis_rows(data, backend.accel_channels(board_id, preset))
    gyro_rows = _axis_rows(data, backend.gyro_channels(board_id, preset))
    if accel_rows is None and gyro_rows is None:
        return None
    imu = IMUSample(
        timestamp=timestamp,
        accelerometer_g=accel_rows,
        gyroscope_dps=gyro_rows,
        source=BRAINFLOW_SOURCE_NAME,
    )
    return MuseFrame(timestamp=timestamp, imu=imu, source=BRAINFLOW_SOURCE_NAME)


def _ancillary_frame_from_data(backend, board_id: int, preset: int, data) -> Optional[MuseFrame]:
    if _sample_count(data) == 0:
        return None
    timestamp = _timestamp_from_data(backend, board_id, preset, data)
    optics = {
        f"OPTICAL_{idx}": _row_series(data, channel)
        for idx, channel in enumerate(backend.optical_channels(board_id, preset))
    }
    ppg = (
        PPGSample(timestamp=timestamp, channels=optics, source=BRAINFLOW_SOURCE_NAME)
        if optics
        else None
    )

    battery = None
    battery_channel = backend.battery_channel(board_id, preset)
    if battery_channel is not None:
        percent = _last_finite(_row_series(data, battery_channel))
        if percent is not None:
            battery = BatterySample(
                timestamp=timestamp,
                percent=percent,
                source=BRAINFLOW_SOURCE_NAME,
            )

    if ppg is None and battery is None:
        return None
    return MuseFrame(timestamp=timestamp, ppg=ppg, battery=battery, source=BRAINFLOW_SOURCE_NAME)


def _axis_rows(data, channels: Sequence[int]) -> Optional[Tuple[Mapping[str, float], ...]]:
    axes = ("x", "y", "z")
    channels = tuple(channels[:3])
    if not channels:
        return None
    count = _sample_count(data)
    rows = []
    series = [_row_series(data, channel) for channel in channels]
    for sample_idx in range(count):
        row = {
            axes[idx]: values[sample_idx]
            for idx, values in enumerate(series)
            if sample_idx < len(values)
        }
        if row:
            rows.append(row)
    return tuple(rows) if rows else None


def _timestamp_from_data(backend, board_id: int, preset: int, data) -> float:
    timestamp_channel = backend.timestamp_channel(board_id, preset)
    if timestamp_channel is not None:
        timestamp = _last_finite(_row_series(data, timestamp_channel))
        if timestamp is not None:
            return timestamp
    return time.time()


def _sample_count(data) -> int:
    shape = getattr(data, "shape", None)
    if shape is not None and len(shape) >= 2:
        return int(shape[1])
    try:
        row_count = len(data)
    except TypeError:
        return 0
    if row_count == 0:
        return 0
    if data[0] is None:
        return 0
    try:
        return len(data[0])
    except TypeError:
        return 0


def _row_series(data, row: int) -> Tuple[float, ...]:
    if row < 0:
        return ()
    try:
        values = data[row]
    except (IndexError, TypeError):
        return ()
    tolist = getattr(values, "tolist", None)
    if callable(tolist):
        values = tolist()
    if isinstance(values, (int, float)):
        return (float(values),)
    return tuple(float(value) for value in values)


def _last_finite(values: Sequence[float]) -> Optional[float]:
    for value in reversed(values):
        if math.isfinite(value):
            return float(value)
    return None
