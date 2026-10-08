"""Polar H10 chest strap over BLE: standard Heart Rate Service plus Polar PMD.

Written from Polar's published documentation ("Polar Measurement Data, online
measurement", v1.0 Aug 2024, and TimeSystemExplained.md in
polarofficial/polar-ble-sdk). Where that document is silent the behaviour of
Polar's own SDK was used as the reference, without copying code:

- the frame timestamp is the time of the *last* sample in the frame, in ns
  since 2000-01-01T00:00:00Z on the sensor clock;
- control point responses are ``F0 <opcode> <type> <status> <more> <params>``;
- settings are serialized as ``<type> <count> <value LE>...``.

Polar's known issue: an H10 that is not told to stop ECG/ACC streaming stays on
until the battery runs out, so callers must always send stop commands.

Kept separate from the Muse sources: chest data never goes into MuseFrame.
"""

from __future__ import annotations

import asyncio
import math
import struct
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

HEART_RATE_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"
DEVICE_INFORMATION_MODEL = "00002a24-0000-1000-8000-00805f9b34fb"
DEVICE_INFORMATION_FIRMWARE = "00002a26-0000-1000-8000-00805f9b34fb"
DEVICE_INFORMATION_MANUFACTURER = "00002a29-0000-1000-8000-00805f9b34fb"
PMD_SERVICE = "fb005c80-02e7-f387-1cad-8acd2d8df0c8"
PMD_CONTROL_POINT = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"

# Short names used in the raw notification log.
CHARACTERISTIC_NAMES = {
    HEART_RATE_MEASUREMENT: "hr",
    PMD_CONTROL_POINT: "pmd_cp",
    PMD_DATA: "pmd_data",
}

# Seconds between the Unix epoch and the Polar epoch (2000-01-01T00:00:00Z).
POLAR_EPOCH_OFFSET_S = 946684800

MEASUREMENT_ECG = 0
MEASUREMENT_ACC = 2
MEASUREMENT_NAMES = {MEASUREMENT_ECG: "ecg", MEASUREMENT_ACC: "acc"}

CP_GET_SETTINGS = 0x01
CP_START = 0x02
CP_STOP = 0x03
CP_RESPONSE = 0xF0
CP_FEATURES = 0x0F

SETTING_SAMPLE_RATE = 0
SETTING_RESOLUTION = 1
SETTING_RANGE = 2
SETTING_RANGE_MILLIUNIT = 3
SETTING_CHANNELS = 4
SETTING_FACTOR = 5
SETTING_FIELD_SIZES = {
    SETTING_SAMPLE_RATE: 2,
    SETTING_RESOLUTION: 2,
    SETTING_RANGE: 2,
    SETTING_RANGE_MILLIUNIT: 4,
    SETTING_CHANNELS: 1,
    SETTING_FACTOR: 4,
}
SETTING_NAMES = {
    SETTING_SAMPLE_RATE: "sample_rate",
    SETTING_RESOLUTION: "resolution",
    SETTING_RANGE: "range",
    SETTING_RANGE_MILLIUNIT: "range_milliunit",
    SETTING_CHANNELS: "channels",
    SETTING_FACTOR: "factor",
}

CP_STATUS_NAMES = {
    0: "success",
    1: "invalid_op_code",
    2: "invalid_measurement_type",
    3: "not_supported",
    4: "invalid_length",
    5: "invalid_parameter",
    6: "already_in_state",
    7: "invalid_resolution",
    8: "invalid_sample_rate",
    9: "invalid_range",
    10: "invalid_mtu",
    11: "invalid_number_of_channels",
    12: "invalid_state",
    13: "device_in_charger",
}


# --- Heart Rate Service ------------------------------------------------------


@dataclass(frozen=True)
class HeartRateMeasurement:
    heart_rate_bpm: int
    sensor_contact_supported: bool
    sensor_contact: Optional[bool]
    energy_expended_kj: Optional[int]
    rr_intervals_ms: Tuple[float, ...]


def parse_heart_rate_measurement(payload: bytes) -> HeartRateMeasurement:
    """Bluetooth SIG Heart Rate Measurement (0x2A37)."""
    if len(payload) < 2:
        raise ValueError("heart rate measurement too short")
    flags = payload[0]
    offset = 1
    if flags & 0x01:
        heart_rate = struct.unpack_from("<H", payload, offset)[0]
        offset += 2
    else:
        heart_rate = payload[offset]
        offset += 1
    contact_supported = bool(flags & 0x04)
    contact = bool(flags & 0x02) if contact_supported else None
    energy = None
    if flags & 0x08:
        energy = struct.unpack_from("<H", payload, offset)[0]
        offset += 2
    rr: List[float] = []
    if flags & 0x10:
        while offset + 1 < len(payload):
            raw = struct.unpack_from("<H", payload, offset)[0]
            rr.append(raw * 1000.0 / 1024.0)
            offset += 2
    return HeartRateMeasurement(
        heart_rate_bpm=int(heart_rate),
        sensor_contact_supported=contact_supported,
        sensor_contact=contact,
        energy_expended_kj=energy,
        rr_intervals_ms=tuple(rr),
    )


# --- PMD control point -------------------------------------------------------


@dataclass(frozen=True)
class ControlPointResponse:
    op_code: int
    measurement_type: int
    status: int
    more: bool
    parameters: bytes

    @property
    def ok(self) -> bool:
        return self.status == 0

    @property
    def status_name(self) -> str:
        return CP_STATUS_NAMES.get(self.status, f"error_{self.status}")


def parse_control_point_response(payload: bytes) -> ControlPointResponse:
    if len(payload) < 4 or payload[0] != CP_RESPONSE:
        raise ValueError("not a PMD control point response")
    status = payload[3]
    return ControlPointResponse(
        op_code=payload[1],
        measurement_type=payload[2] & 0x3F,
        status=status,
        more=status == 0 and len(payload) > 4 and payload[4] != 0,
        parameters=bytes(payload[5:]) if status == 0 else b"",
    )


class ControlPointAssembler:
    """Joins control point responses split over several notifications.

    A response with ``more`` set continues in the next notification for the
    same op code and measurement type, which repeats the 5 byte header; the
    parameters are concatenated until a fragment arrives without ``more``.
    """

    def __init__(self) -> None:
        self._partial: Dict[Tuple[int, int], ControlPointResponse] = {}

    def feed(self, payload: bytes) -> Optional[ControlPointResponse]:
        response = parse_control_point_response(payload)
        key = (response.op_code, response.measurement_type)
        partial = self._partial.pop(key, None)
        if partial is not None:
            response = replace(response, parameters=partial.parameters + response.parameters)
        if response.more:
            self._partial[key] = response
            return None
        return response


def parse_settings(parameters: bytes) -> Dict[int, Tuple[int, ...]]:
    """``<type> <count> <values>`` blocks into {setting type: values}."""
    settings: Dict[int, Tuple[int, ...]] = {}
    offset = 0
    while offset + 1 < len(parameters):
        setting_type = parameters[offset]
        count = parameters[offset + 1]
        offset += 2
        size = SETTING_FIELD_SIZES.get(setting_type)
        if size is None:
            raise ValueError(f"unknown PMD setting type {setting_type}")
        values = []
        for _ in range(count):
            values.append(int.from_bytes(parameters[offset : offset + size], "little", signed=False))
            offset += size
        settings[setting_type] = tuple(values)
    return settings


def factor_from_settings(settings: Mapping[int, Sequence[int]]) -> Optional[float]:
    """The conversion factor is an IEEE 754 float carried as 4 raw bytes."""
    values = settings.get(SETTING_FACTOR)
    if not values:
        return None
    return float(struct.unpack("<f", int(values[0]).to_bytes(4, "little"))[0])


def serialize_settings(selected: Mapping[int, int]) -> bytes:
    out = bytearray()
    for setting_type, value in selected.items():
        if setting_type == SETTING_FACTOR:
            continue  # response-only
        out += bytes((setting_type, 1))
        out += int(value).to_bytes(SETTING_FIELD_SIZES[setting_type], "little")
    return bytes(out)


def get_settings_command(measurement_type: int) -> bytes:
    return bytes((CP_GET_SETTINGS, measurement_type))


def start_command(measurement_type: int, selected: Mapping[int, int]) -> bytes:
    # First byte: recording type (online = 0) << 7 | measurement type.
    return bytes((CP_START, measurement_type & 0x3F)) + serialize_settings(selected)


def stop_command(measurement_type: int) -> bytes:
    return bytes((CP_STOP, measurement_type))


def parse_start_command(payload: bytes) -> Tuple[int, Dict[int, int]]:
    """Inverse of start_command, used when decoding the raw log."""
    if len(payload) < 2 or payload[0] != CP_START:
        raise ValueError("not a PMD start command")
    settings = parse_settings(payload[2:])
    return payload[1] & 0x3F, {key: values[0] for key, values in settings.items() if values}


# --- PMD data frames ---------------------------------------------------------


@dataclass(frozen=True)
class PmdFrame:
    measurement_type: int
    timestamp_ns: int  # sensor clock, last sample, ns since 2000-01-01Z
    frame_type: int
    compressed: bool
    samples: Tuple[Tuple[float, ...], ...]


@dataclass(frozen=True)
class PmdStreamSettings:
    sample_rate: int
    resolution: int
    channels: int
    factor: float = 1.0
    range: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "sample_rate": self.sample_rate,
            "resolution": self.resolution,
            "channels": self.channels,
            "factor": self.factor,
            "range": self.range,
        }


DEFAULT_CHANNELS = {MEASUREMENT_ECG: 1, MEASUREMENT_ACC: 3}


def parse_pmd_frame(payload: bytes, settings: PmdStreamSettings) -> PmdFrame:
    if len(payload) < 10:
        raise ValueError("PMD data frame shorter than its 10 byte header")
    measurement_type = payload[0] & 0x3F
    timestamp_ns = int.from_bytes(payload[1:9], "little", signed=False)
    frame_byte = payload[9]
    frame_type = frame_byte & 0x7F
    compressed = bool(frame_byte & 0x80)
    content = bytes(payload[10:])
    if compressed:
        raw_samples = decode_delta_frames(content, settings.channels, settings.resolution)
    else:
        raw_samples = _uncompressed_samples(measurement_type, frame_type, content)
    factor = settings.factor if settings.factor else 1.0
    samples = tuple(tuple(value * factor for value in sample) for sample in raw_samples)
    return PmdFrame(measurement_type, timestamp_ns, frame_type, compressed, samples)


def _uncompressed_samples(measurement_type: int, frame_type: int, content: bytes) -> List[Tuple[int, ...]]:
    if measurement_type == MEASUREMENT_ECG and frame_type == 0:
        width, channels = 3, 1
    elif measurement_type == MEASUREMENT_ACC and frame_type in (0, 1, 2):
        width, channels = frame_type + 1, 3
    else:
        raise ValueError(f"unsupported uncompressed frame: type {measurement_type} frame {frame_type}")
    step = width * channels
    samples = []
    for offset in range(0, len(content) - step + 1, step):
        samples.append(
            tuple(
                int.from_bytes(content[offset + i * width : offset + (i + 1) * width], "little", signed=True)
                for i in range(channels)
            )
        )
    return samples


def decode_delta_frames(content: bytes, channels: int, resolution: int) -> List[Tuple[int, ...]]:
    """Polar delta compression.

    A reference sample of ``channels`` signed integers, ceil(resolution / 8)
    bytes each, followed by blocks of ``<bit width> <sample count>`` and
    ``count * channels`` signed deltas packed LSB-first. Each delta is added to
    the previous sample.
    """
    width = math.ceil(resolution / 8)
    if len(content) < channels * width:
        raise ValueError("delta frame shorter than its reference sample")
    reference = []
    for channel in range(channels):
        chunk = content[channel * width : (channel + 1) * width]
        reference.append(_sign_extend(int.from_bytes(chunk, "little"), resolution))
    samples = [tuple(reference)]
    offset = channels * width
    while offset + 1 < len(content):
        bit_width = content[offset]
        count = content[offset + 1]
        offset += 2
        total_bits = bit_width * count * channels
        block_len = math.ceil(total_bits / 8)
        block = content[offset : offset + block_len]
        if len(block) < block_len or bit_width == 0:
            break
        bits = int.from_bytes(block, "little")
        position = 0
        for _ in range(count):
            previous = samples[-1]
            sample = []
            for channel in range(channels):
                delta = (bits >> position) & ((1 << bit_width) - 1)
                position += bit_width
                sample.append(previous[channel] + _sign_extend(delta, bit_width))
            samples.append(tuple(sample))
        offset += block_len
    return samples


def _sign_extend(value: int, bits: int) -> int:
    if bits <= 0:
        return 0
    sign = 1 << (bits - 1)
    return (value & (sign - 1)) - (value & sign)


def sample_times_ns(
    frame_timestamp_ns: int,
    previous_timestamp_ns: Optional[int],
    sample_count: int,
    sample_rate: float,
) -> Tuple[float, float]:
    """(first sample time, sample period) on the sensor clock, in ns.

    The frame timestamp is the last sample. With a previous frame of the same
    stream the period comes from the gap between the two timestamps, which
    tracks the sensor's real rate (130 Hz +-2 % for ECG); otherwise from the
    nominal rate.
    """
    if sample_count <= 0:
        raise ValueError("frame has no samples")
    period = 1e9 / sample_rate
    if previous_timestamp_ns is not None and frame_timestamp_ns > previous_timestamp_ns:
        candidate = (frame_timestamp_ns - previous_timestamp_ns) / sample_count
        # A gap (dropped frames, reconnect) would stretch the period; keep nominal then.
        if 0.8 * period <= candidate <= 1.2 * period:
            period = candidate
    return frame_timestamp_ns - period * (sample_count - 1), period


# --- BLE client ----------------------------------------------------------------


@dataclass
class PolarH10Settings:
    ecg: bool = True
    acc: bool = True
    acc_rate_hz: int = 50
    acc_range_g: int = 2
    ecg_rate_hz: int = 130
    scan_timeout_seconds: float = 15.0
    command_timeout_seconds: float = 10.0


NotificationCallback = Callable[[str, str, bytes], None]  # (direction, characteristic uuid, payload)


class PolarH10Client:
    """Connects, starts HR + PMD ECG/ACC, and reports every payload as-is.

    ``on_payload`` receives received notifications (``rx``) and the control
    point commands we write (``tx``), so the raw log is enough to re-decode.
    """

    def __init__(
        self,
        settings: Optional[PolarH10Settings] = None,
        *,
        address: Optional[str] = None,
        name_filter: str = "Polar H10",
    ) -> None:
        self.settings = settings or PolarH10Settings()
        self.address = address
        self.name_filter = name_filter
        self._client = None
        self._on_payload: Optional[NotificationCallback] = None
        self._responses: "asyncio.Queue[ControlPointResponse]" = asyncio.Queue()
        self._assembler = ControlPointAssembler()
        self.disconnected = asyncio.Event()
        self.stream_settings: Dict[str, PmdStreamSettings] = {}
        self._started: List[int] = []

    async def connect(self, on_payload: NotificationCallback) -> Dict[str, object]:
        from bleak import BleakClient, BleakScanner

        self._on_payload = on_payload
        self.disconnected = asyncio.Event()
        self._responses = asyncio.Queue()
        self._assembler = ControlPointAssembler()
        device = await self._find_device(BleakScanner)
        self._client = BleakClient(device, disconnected_callback=lambda _client: self.disconnected.set())
        await self._client.connect()
        metadata: Dict[str, object] = {"device_name": getattr(device, "name", None)}
        for key, uuid in (
            ("model", DEVICE_INFORMATION_MODEL),
            ("firmware", DEVICE_INFORMATION_FIRMWARE),
            ("manufacturer", DEVICE_INFORMATION_MANUFACTURER),
        ):
            try:
                metadata[key] = bytes(await self._client.read_gatt_char(uuid)).decode("utf-8", "replace").strip("\x00")
            except Exception:
                metadata[key] = None
        await self._client.start_notify(HEART_RATE_MEASUREMENT, self._notification(HEART_RATE_MEASUREMENT))
        if self.settings.ecg or self.settings.acc:
            await self._client.start_notify(PMD_CONTROL_POINT, self._notification(PMD_CONTROL_POINT))
            await self._client.start_notify(PMD_DATA, self._notification(PMD_DATA))
            if self.settings.ecg:
                self.stream_settings["ecg"] = await self._start_stream(
                    MEASUREMENT_ECG, {SETTING_SAMPLE_RATE: self.settings.ecg_rate_hz}
                )
            if self.settings.acc:
                self.stream_settings["acc"] = await self._start_stream(
                    MEASUREMENT_ACC,
                    {SETTING_SAMPLE_RATE: self.settings.acc_rate_hz, SETTING_RANGE: self.settings.acc_range_g},
                )
        metadata["streams"] = {name: value.to_dict() for name, value in self.stream_settings.items()}
        return metadata

    async def stop(self) -> None:
        """Stop PMD streams (see Polar known issue) and disconnect; never raises."""
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            if client.is_connected:
                for measurement_type in reversed(self._started):
                    try:
                        await self._write_control_point(client, stop_command(measurement_type))
                    except Exception:
                        pass
        finally:
            self._started = []
            try:
                await client.disconnect()
            except Exception:
                pass

    async def _find_device(self, scanner):
        timeout = self.settings.scan_timeout_seconds
        if self.address:
            device = await scanner.find_device_by_address(self.address, timeout=timeout)
        else:
            device = await scanner.find_device_by_filter(
                lambda d, _adv: bool(d.name) and self.name_filter.lower() in d.name.lower(),
                timeout=timeout,
            )
        if device is None:
            raise RuntimeError("Polar H10 not found (is it worn, and not held by a phone or watch?)")
        return device

    async def _start_stream(self, measurement_type: int, wanted: Mapping[int, int]) -> PmdStreamSettings:
        available = await self._command(get_settings_command(measurement_type))
        offered = parse_settings(available.parameters)
        selected: Dict[int, int] = {}
        for setting_type, values in offered.items():
            if setting_type == SETTING_FACTOR or not values:
                continue
            if setting_type in wanted:
                if wanted[setting_type] not in values:
                    name = SETTING_NAMES.get(setting_type, setting_type)
                    raise ValueError(f"{MEASUREMENT_NAMES[measurement_type]} {name} {wanted[setting_type]} not offered: {values}")
                selected[setting_type] = wanted[setting_type]
            else:
                selected[setting_type] = values[0]
        response = await self._command(start_command(measurement_type, selected))
        self._started.append(measurement_type)
        factor = factor_from_settings(parse_settings(response.parameters)) if response.parameters else None
        return PmdStreamSettings(
            sample_rate=selected.get(SETTING_SAMPLE_RATE, 0),
            resolution=selected.get(SETTING_RESOLUTION, 16),
            channels=selected.get(SETTING_CHANNELS, DEFAULT_CHANNELS[measurement_type]),
            factor=factor if factor else 1.0,
            range=selected.get(SETTING_RANGE),
        )

    async def _command(self, payload: bytes) -> ControlPointResponse:
        """Write a command and wait for its complete response.

        Responses for other commands (a late answer to a timed-out request) are
        skipped by op code and measurement type.
        """
        assert self._client is not None
        await self._write_control_point(self._client, payload)
        op_code, measurement_type = payload[0], payload[1] & 0x3F
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.command_timeout_seconds
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError(f"no response to PMD command {payload.hex()}")
            response = await asyncio.wait_for(self._responses.get(), timeout=remaining)
            if response.op_code == op_code and response.measurement_type == measurement_type:
                break
        if not response.ok and not (op_code == CP_START and response.status == 6):
            raise RuntimeError(f"PMD command {payload.hex()} failed: {response.status_name}")
        return response

    async def _write_control_point(self, client, payload: bytes) -> None:
        if self._on_payload is not None:
            self._on_payload("tx", PMD_CONTROL_POINT, bytes(payload))
        await client.write_gatt_char(PMD_CONTROL_POINT, bytes(payload), response=True)

    def _notification(self, uuid: str):
        def callback(_sender, data: bytearray) -> None:
            payload = bytes(data)
            if self._on_payload is not None:
                self._on_payload("rx", uuid, payload)
            if uuid == PMD_CONTROL_POINT and payload[:1] == bytes((CP_RESPONSE,)):
                try:
                    complete = self._assembler.feed(payload)
                except ValueError:
                    return
                if complete is not None:
                    self._responses.put_nowait(complete)

        return callback
