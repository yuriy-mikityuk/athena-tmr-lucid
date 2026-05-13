"""Optional OpenMuse LSL source adapter.

OpenMuse publishes Lab Streaming Layer streams separately. This adapter reads those
streams when either `mne_lsl` or `pylsl` is installed, but importing this module does
not require either optional dependency.
"""

from __future__ import annotations

import asyncio
import importlib
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, Mapping, Optional, Sequence, Tuple

from muse_tmr.data.sample_types import (
    BatterySample,
    EEGSample,
    HeartRateSample,
    IMUSample,
    MuseFrame,
    PPGSample,
)
from muse_tmr.sources.base_source import BaseMuseSource, MuseDeviceInfo, MuseSourceMetadata

OPENMUSE_SOURCE_NAME = "openmuse"

DEFAULT_OPENMUSE_STREAM_NAMES: Mapping[str, Tuple[str, ...]] = {
    "eeg": ("Muse_EEG", "Muse-EEG"),
    "imu": ("Muse_ACCGYRO", "Muse-ACCGYRO"),
    "ppg": ("Muse_PPG", "Muse-PPG"),
    "heart_rate": ("Muse_HR", "Muse_HEART", "Muse_HEART_RATE", "Muse-HeartRate"),
    "battery": ("Muse_BATT", "Muse_BATTERY", "Muse-Telemetry"),
}

DEFAULT_CHANNEL_LABELS: Mapping[str, Tuple[str, ...]] = {
    "eeg": ("TP9", "AF7", "AF8", "TP10", "AUX"),
    "imu": ("ACC_X", "ACC_Y", "ACC_Z", "GYRO_X", "GYRO_Y", "GYRO_Z"),
    "ppg": ("PPG0", "PPG1", "PPG2", "PPG3", "PPG4", "PPG5", "PPG6", "PPG7"),
    "heart_rate": ("BPM",),
    "battery": ("BATTERY",),
}


class OpenMuseLslDependencyError(RuntimeError):
    """Raised when no supported optional LSL dependency is installed."""


@dataclass(frozen=True)
class OpenMuseLslConfig:
    stream_names: Mapping[str, Tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_OPENMUSE_STREAM_NAMES)
    )
    required_modalities: Tuple[str, ...] = ()
    resolve_timeout_seconds: float = 5.0
    pull_timeout_seconds: float = 0.0
    poll_interval_seconds: float = 0.01
    max_buffer_seconds: int = 30
    duration_seconds: float = 0.0
    device_name: str = "OpenMuse LSL"

    def __post_init__(self) -> None:
        if self.resolve_timeout_seconds < 0:
            raise ValueError("resolve_timeout_seconds must be non-negative")
        if self.pull_timeout_seconds < 0:
            raise ValueError("pull_timeout_seconds must be non-negative")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if self.max_buffer_seconds <= 0:
            raise ValueError("max_buffer_seconds must be positive")
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        unknown = tuple(
            modality
            for modality in self.required_modalities
            if modality not in DEFAULT_OPENMUSE_STREAM_NAMES
        )
        if unknown:
            raise ValueError(f"unknown required OpenMuse modalities: {unknown}")


class OpenMuseLslSource(BaseMuseSource):
    """Stream MuseFrames from OpenMuse LSL streams."""

    source_name = OPENMUSE_SOURCE_NAME
    strategy = "optional-lsl"

    def __init__(
        self,
        config: Optional[OpenMuseLslConfig] = None,
        *,
        lsl_backend: Optional[object] = None,
    ) -> None:
        self.config = config or OpenMuseLslConfig()
        self._backend = lsl_backend
        self._inlets: Dict[str, object] = {}
        self._stream_infos: Dict[str, object] = {}
        self._channel_labels: Dict[str, Tuple[str, ...]] = {}
        self._time_corrections: Dict[str, float] = {}
        self._lsl_to_unix_offset = 0.0
        self._stop_requested = False
        self.metadata: Optional[MuseSourceMetadata] = None
        self.frame_count = 0

    async def discover(self) -> Sequence[MuseDeviceInfo]:
        backend = self._get_backend()
        infos = await asyncio.to_thread(self._resolve_infos, backend)
        devices = []
        for info in infos:
            stream_name = _stream_name(info)
            devices.append(
                MuseDeviceInfo(
                    name=stream_name,
                    address=_stream_uid(info),
                    rssi=0,
                    metadata={
                        "source": self.source_name,
                        "stream_type": _stream_type(info),
                        "modality": self._modality_for_stream_name(stream_name) or "unknown",
                    },
                )
            )
        return tuple(devices)

    async def connect(self, device: Optional[MuseDeviceInfo] = None) -> MuseSourceMetadata:
        backend = self._get_backend()
        infos = await asyncio.to_thread(self._resolve_infos, backend)
        selected = self._select_streams(infos)
        if not selected:
            raise RuntimeError(
                "No OpenMuse LSL streams found. Start OpenMuse separately and make "
                "sure Muse_EEG or related streams are visible on LSL."
            )
        missing = tuple(
            modality
            for modality in self.config.required_modalities
            if modality not in selected
        )
        if missing:
            raise RuntimeError(f"Missing required OpenMuse LSL streams: {missing}")

        await asyncio.to_thread(self._open_inlets, backend, selected)
        device_name = device.name if device is not None else self.config.device_name
        self.metadata = MuseSourceMetadata(
            source_name=self.source_name,
            device_name=device_name,
            device_id=";".join(
                _stream_uid(info)
                for _, info in sorted(selected.items(), key=lambda item: item[0])
            ),
            capabilities={
                "eeg": "eeg" in self._inlets,
                "imu": "imu" in self._inlets,
                "ppg": "ppg" in self._inlets,
                "heart_rate": "heart_rate" in self._inlets,
                "battery": "battery" in self._inlets,
                "raw_packets": False,
            },
            metadata={
                "strategy": self.strategy,
                "lsl_backend": getattr(backend, "name", backend.__class__.__name__),
                "stream_names": ",".join(_stream_name(info) for info in selected.values()),
            },
        )
        self._stop_requested = False
        self.frame_count = 0
        return self.metadata

    async def stream(self) -> AsyncIterator[MuseFrame]:
        if not self._inlets:
            await self.connect()

        deadline = (
            time.monotonic() + self.config.duration_seconds
            if self.config.duration_seconds > 0
            else None
        )
        while not self._stop_requested and (deadline is None or time.monotonic() < deadline):
            yielded = False
            for modality in tuple(self._inlets):
                frame = await asyncio.to_thread(self._pull_frame, modality)
                if frame is None:
                    continue
                self.frame_count += 1
                yielded = True
                yield frame
            if not yielded:
                await asyncio.sleep(self.config.poll_interval_seconds)

    async def stop(self) -> None:
        self._stop_requested = True
        await asyncio.to_thread(self._close_inlets)

    def _get_backend(self):
        if self._backend is None:
            self._backend = _load_lsl_backend()
        return self._backend

    def _resolve_infos(self, backend) -> Tuple[object, ...]:
        infos = tuple(backend.resolve_streams(self.config.resolve_timeout_seconds))
        if infos:
            return tuple(info for info in infos if self._modality_for_stream_name(_stream_name(info)))

        resolved = []
        seen = set()
        for names in self.config.stream_names.values():
            for name in names:
                for info in backend.resolve_by_name(name, self.config.resolve_timeout_seconds):
                    uid = _stream_uid(info)
                    if uid not in seen:
                        seen.add(uid)
                        resolved.append(info)
        return tuple(resolved)

    def _select_streams(self, infos: Sequence[object]) -> Dict[str, object]:
        selected: Dict[str, object] = {}
        for info in infos:
            modality = self._modality_for_stream_name(_stream_name(info))
            if modality is not None and modality not in selected:
                selected[modality] = info
        return selected

    def _open_inlets(self, backend, selected: Mapping[str, object]) -> None:
        self._close_inlets()
        self._lsl_to_unix_offset = _lsl_to_unix_offset(backend)
        for modality, info in selected.items():
            inlet = backend.stream_inlet(info, max_buffer_seconds=self.config.max_buffer_seconds)
            _open_stream(inlet, self.config.resolve_timeout_seconds)
            self._inlets[modality] = inlet
            self._stream_infos[modality] = info
            self._channel_labels[modality] = _channel_labels(
                info,
                DEFAULT_CHANNEL_LABELS[modality],
            )
            self._time_corrections[modality] = _time_correction(inlet)

    def _close_inlets(self) -> None:
        for inlet in self._inlets.values():
            close_stream = getattr(inlet, "close_stream", None)
            if callable(close_stream):
                close_stream()
        self._inlets.clear()
        self._stream_infos.clear()
        self._channel_labels.clear()
        self._time_corrections.clear()

    def _pull_frame(self, modality: str) -> Optional[MuseFrame]:
        inlet = self._inlets[modality]
        sample = _pull_sample(inlet, self.config.pull_timeout_seconds)
        if sample is None:
            return None
        values, lsl_timestamp = sample
        timestamp = self._lsl_to_unix(lsl_timestamp + self._time_corrections.get(modality, 0.0))
        return _frame_from_lsl_sample(
            modality,
            timestamp,
            values,
            labels=self._channel_labels.get(modality, ()),
        )

    def _lsl_to_unix(self, lsl_timestamp: float) -> float:
        if self._lsl_to_unix_offset:
            return lsl_timestamp + self._lsl_to_unix_offset
        if lsl_timestamp < 1_000_000_000:
            return time.time()
        return lsl_timestamp

    def _modality_for_stream_name(self, stream_name: str) -> Optional[str]:
        normalized = _normalized_name(stream_name)
        for modality, names in self.config.stream_names.items():
            if any(normalized.startswith(_normalized_name(name)) for name in names):
                return modality
        return None


class _MneLslBackend:
    name = "mne_lsl"

    def __init__(self, module) -> None:
        self.module = module

    def resolve_streams(self, timeout_seconds: float) -> Sequence[object]:
        try:
            return self.module.resolve_streams(timeout=timeout_seconds)
        except TypeError:
            return self.module.resolve_streams(timeout_seconds)

    def resolve_by_name(self, name: str, timeout_seconds: float) -> Sequence[object]:
        return tuple(
            info
            for info in self.resolve_streams(timeout_seconds)
            if _stream_name(info) == name
        )

    def stream_inlet(self, info: object, *, max_buffer_seconds: int) -> object:
        try:
            return self.module.StreamInlet(info, max_buffered=max_buffer_seconds)
        except TypeError:
            return self.module.StreamInlet(info)

    def local_clock(self) -> float:
        clock = getattr(self.module, "local_clock", None)
        if callable(clock):
            return float(clock())
        return time.monotonic()


class _PylslBackend:
    name = "pylsl"

    def __init__(self, module) -> None:
        self.module = module

    def resolve_streams(self, timeout_seconds: float) -> Sequence[object]:
        resolver = getattr(self.module, "resolve_streams", None)
        if callable(resolver):
            try:
                return resolver(wait_time=timeout_seconds)
            except TypeError:
                return resolver(timeout_seconds)
        return ()

    def resolve_by_name(self, name: str, timeout_seconds: float) -> Sequence[object]:
        resolver = getattr(self.module, "resolve_stream", None)
        if not callable(resolver):
            return ()
        try:
            return resolver("name", name, timeout=timeout_seconds)
        except TypeError:
            return resolver("name", name, timeout_seconds)

    def stream_inlet(self, info: object, *, max_buffer_seconds: int) -> object:
        try:
            return self.module.StreamInlet(info, max_buflen=max_buffer_seconds)
        except TypeError:
            return self.module.StreamInlet(info)

    def local_clock(self) -> float:
        return float(self.module.local_clock())


def _load_lsl_backend():
    try:
        return _MneLslBackend(importlib.import_module("mne_lsl.lsl"))
    except ImportError:
        pass
    try:
        return _PylslBackend(importlib.import_module("pylsl"))
    except ImportError as exc:
        raise OpenMuseLslDependencyError(
            "OpenMuse LSL source requires optional dependency `mne_lsl` or `pylsl` "
            "plus liblsl. Install one of them, then run OpenMuse separately."
        ) from exc


def _frame_from_lsl_sample(
    modality: str,
    timestamp: float,
    values: Tuple[float, ...],
    *,
    labels: Sequence[str],
) -> MuseFrame:
    if modality == "eeg":
        eeg = EEGSample(timestamp, _series_by_label(values, labels), source=OPENMUSE_SOURCE_NAME)
        return MuseFrame(timestamp=timestamp, eeg=eeg, source=OPENMUSE_SOURCE_NAME)
    if modality == "imu":
        accel = _axis_row(values[:3], ("x", "y", "z"))
        gyro = _axis_row(values[3:6], ("x", "y", "z"))
        imu = IMUSample(
            timestamp,
            accelerometer_g=(accel,) if accel else None,
            gyroscope_dps=(gyro,) if gyro else None,
            source=OPENMUSE_SOURCE_NAME,
        )
        return MuseFrame(timestamp=timestamp, imu=imu, source=OPENMUSE_SOURCE_NAME)
    if modality == "ppg":
        ppg = PPGSample(timestamp, _series_by_label(values, labels), source=OPENMUSE_SOURCE_NAME)
        return MuseFrame(timestamp=timestamp, ppg=ppg, source=OPENMUSE_SOURCE_NAME)
    if modality == "heart_rate":
        return MuseFrame(
            timestamp=timestamp,
            heart_rate=HeartRateSample(timestamp, values[0], source=OPENMUSE_SOURCE_NAME),
            source=OPENMUSE_SOURCE_NAME,
        )
    if modality == "battery":
        return MuseFrame(
            timestamp=timestamp,
            battery=BatterySample(timestamp, values[0], source=OPENMUSE_SOURCE_NAME),
            source=OPENMUSE_SOURCE_NAME,
        )
    raise ValueError(f"unknown OpenMuse modality: {modality}")


def _pull_sample(inlet: object, timeout_seconds: float) -> Optional[Tuple[Tuple[float, ...], float]]:
    pull_sample = getattr(inlet, "pull_sample", None)
    if not callable(pull_sample):
        raise RuntimeError("LSL inlet does not expose pull_sample()")
    try:
        sample, timestamp = pull_sample(timeout=timeout_seconds)
    except TypeError:
        sample, timestamp = pull_sample(timeout_seconds)
    if sample is None or timestamp is None:
        return None
    values = tuple(float(value) for value in sample)
    if not values:
        return None
    return values, float(timestamp)


def _series_by_label(values: Sequence[float], labels: Sequence[str]) -> Dict[str, Tuple[float, ...]]:
    result = {}
    for index, value in enumerate(values):
        label = labels[index] if index < len(labels) else f"CH{index}"
        result[label] = (float(value),)
    return result


def _axis_row(values: Sequence[float], axes: Tuple[str, ...]) -> Dict[str, float]:
    return {
        axis: float(values[index])
        for index, axis in enumerate(axes)
        if index < len(values)
    }


def _open_stream(inlet: object, timeout_seconds: float) -> None:
    open_stream = getattr(inlet, "open_stream", None)
    if not callable(open_stream):
        return
    try:
        open_stream(timeout=timeout_seconds)
    except TypeError:
        open_stream(timeout_seconds)


def _time_correction(inlet: object) -> float:
    time_correction = getattr(inlet, "time_correction", None)
    if not callable(time_correction):
        return 0.0
    try:
        return float(time_correction(timeout=0.2))
    except TypeError:
        return float(time_correction(0.2))
    except Exception:
        return 0.0


def _lsl_to_unix_offset(backend) -> float:
    local_clock = getattr(backend, "local_clock", None)
    if not callable(local_clock):
        return 0.0
    try:
        return time.time() - float(local_clock())
    except Exception:
        return 0.0


def _stream_name(info: object) -> str:
    return _stream_attr(info, "name", "OpenMuse LSL")


def _stream_type(info: object) -> str:
    return _stream_attr(info, "type", "") or _stream_attr(info, "stype", "")


def _stream_uid(info: object) -> str:
    return (
        _stream_attr(info, "source_id", "")
        or _stream_attr(info, "uid", "")
        or _stream_name(info)
    )


def _stream_attr(info: object, name: str, default: str) -> str:
    value = getattr(info, name, None)
    if callable(value):
        try:
            value = value()
        except TypeError:
            value = None
    if value is None:
        value = getattr(info, f"_{name}", None)
    return str(value) if value not in (None, "") else default


def _channel_labels(info: object, fallback: Sequence[str]) -> Tuple[str, ...]:
    labels = _channel_labels_from_metadata(info)
    if labels:
        return labels
    count = _channel_count(info)
    if count <= 0:
        return tuple(fallback)
    if count <= len(fallback):
        return tuple(fallback[:count])
    return tuple(fallback) + tuple(f"CH{index}" for index in range(len(fallback), count))


def _channel_count(info: object) -> int:
    for attr_name in ("channel_count", "n_channels"):
        value = getattr(info, attr_name, None)
        if callable(value):
            try:
                return int(value())
            except TypeError:
                pass
        if value not in (None, ""):
            return int(value)
    return 0


def _channel_labels_from_metadata(info: object) -> Tuple[str, ...]:
    desc = getattr(info, "desc", None)
    if not callable(desc):
        return ()
    try:
        channels = desc().child("channels")
        channel = channels.child("channel")
    except Exception:
        return ()
    labels = []
    while channel is not None:
        try:
            if channel.empty():
                break
        except Exception:
            break
        label = _xml_child_value(channel, "label") or _xml_child_value(channel, "name")
        if label:
            labels.append(label)
        try:
            channel = channel.next_sibling()
        except Exception:
            break
    return tuple(labels)


def _xml_child_value(node: object, child_name: str) -> str:
    try:
        return str(node.child_value(child_name) or "").strip()
    except Exception:
        return ""


def _normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())
