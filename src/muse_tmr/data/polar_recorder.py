"""Polar H10 companion recorder and raw-log decoder.

Runs as its own process (``muse-tmr record-polar``) so a chest-strap problem
can never stop or slow the Muse recording. Every BLE payload is written to
``polar/raw_notifications.jsonl`` before anything is parsed; ``decode-polar``
rebuilds the decoded files from that log alone.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Protocol

from muse_tmr.sources.polar_h10 import (
    CHARACTERISTIC_NAMES,
    CP_RESPONSE,
    CP_START,
    DEFAULT_CHANNELS,
    MEASUREMENT_ACC,
    MEASUREMENT_ECG,
    MEASUREMENT_NAMES,
    ControlPointAssembler,
    PmdStreamSettings,
    SETTING_CHANNELS,
    SETTING_RANGE,
    SETTING_RESOLUTION,
    SETTING_SAMPLE_RATE,
    factor_from_settings,
    parse_heart_rate_measurement,
    parse_pmd_frame,
    parse_settings,
    parse_start_command,
    sample_times_ns,
)

POLAR_DIRNAME = "polar"
RAW_FILENAME = "raw_notifications.jsonl"
CLOCK_ANCHOR_INTERVAL_SECONDS = 60.0


class PolarClient(Protocol):
    disconnected: asyncio.Event
    stream_settings: Dict[str, PmdStreamSettings]

    async def connect(self, on_payload) -> Dict[str, object]: ...

    async def stop(self) -> None: ...


@dataclass(frozen=True)
class PolarRecordingConfig:
    output_dir: Path  # the session directory; files go to <output_dir>/polar/
    duration_seconds: float
    max_reconnect_attempts: int = 1000
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0

    def validate(self) -> None:
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")


class PolarRecorder:
    def __init__(self, config: PolarRecordingConfig) -> None:
        config.validate()
        self.config = config
        self.polar_dir = Path(config.output_dir) / POLAR_DIRNAME

    async def record(self, client: PolarClient) -> Dict[str, object]:
        self.polar_dir.mkdir(parents=True, exist_ok=True)
        started_wall = time.time()
        started_mono = time.monotonic()
        deadline = started_mono + self.config.duration_seconds
        counts = {name: 0 for name in ("hr", "pmd_cp", "pmd_data", "tx")}
        state = {
            "stop_reason": "duration_complete",
            "reconnects": 0,
            "failed_connects": 0,
            "downtime_seconds": 0.0,
            "down_since": started_mono,
        }
        downtimes: List[Dict[str, float]] = []
        metadata: Dict[str, object] = {
            "started_at": dt.datetime.fromtimestamp(started_wall, dt.timezone.utc).isoformat(),
            "config": {
                "duration_seconds": self.config.duration_seconds,
                "max_reconnect_attempts": self.config.max_reconnect_attempts,
            },
            "raw_format": "jsonl: seq, dir, char, uuid, wall, mono, b64",
        }

        raw_file = (self.polar_dir / RAW_FILENAME).open("a", encoding="utf-8")
        events_file = (self.polar_dir / "events.jsonl").open("a", encoding="utf-8")
        anchors_file = (self.polar_dir / "clock_anchors.jsonl").open("a", encoding="utf-8")
        sequence = [0]

        def on_payload(direction: str, uuid: str, payload: bytes) -> None:
            name = CHARACTERISTIC_NAMES.get(uuid.lower(), uuid.lower())
            record = {
                "seq": sequence[0],
                "dir": direction,
                "char": name,
                "uuid": uuid.lower(),
                "wall": time.time(),
                "mono": time.monotonic(),
                "b64": base64.b64encode(payload).decode("ascii"),
            }
            sequence[0] += 1
            raw_file.write(json.dumps(record, separators=(",", ":")) + "\n")
            raw_file.flush()
            key = "tx" if direction == "tx" else name
            counts[key] = counts.get(key, 0) + 1

        def event(name: str, **details) -> None:
            events_file.write(
                json.dumps({"event": name, "wall": time.time(), "mono": time.monotonic(), "details": details}, sort_keys=True)
                + "\n"
            )
            events_file.flush()

        def anchor(label: str) -> None:
            anchors_file.write(
                json.dumps({"label": label, "wall": time.time(), "mono": time.monotonic()}) + "\n"
            )
            anchors_file.flush()

        anchor("start")
        event("recording_started", duration_seconds=self.config.duration_seconds)
        next_anchor = started_mono + CLOCK_ANCHOR_INTERVAL_SECONDS
        try:
            attempts = 0
            while time.monotonic() < deadline:
                try:
                    device_metadata = await client.connect(on_payload)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    attempts += 1
                    state["failed_connects"] += 1
                    event("connect_failed", attempt=attempts, error=str(exc))
                    if attempts > self.config.max_reconnect_attempts:
                        state["stop_reason"] = "max_reconnect_attempts"
                        break
                    await client.stop()
                    await asyncio.sleep(min(self._backoff(attempts), max(0.0, deadline - time.monotonic())))
                    continue

                now = time.monotonic()
                if state["down_since"] is not None:
                    gap = now - state["down_since"]
                    if attempts or state["reconnects"]:
                        state["downtime_seconds"] += gap
                        downtimes.append({"start_mono": state["down_since"], "seconds": gap})
                    state["down_since"] = None
                attempts = 0
                streams = {name: value.to_dict() for name, value in client.stream_settings.items()}
                metadata["device"] = {key: value for key, value in device_metadata.items() if key != "streams"}
                metadata["streams"] = streams
                self._write_json("metadata.json", metadata)
                event("connected", streams=streams)

                while time.monotonic() < deadline and not client.disconnected.is_set():
                    timeout = max(0.01, min(next_anchor, deadline) - time.monotonic())
                    try:
                        await asyncio.wait_for(client.disconnected.wait(), timeout=timeout)
                    except asyncio.TimeoutError:
                        pass
                    if time.monotonic() >= next_anchor:
                        anchor("periodic")
                        next_anchor += CLOCK_ANCHOR_INTERVAL_SECONDS

                if client.disconnected.is_set() and time.monotonic() < deadline:
                    state["reconnects"] += 1
                    state["down_since"] = time.monotonic()
                    event("disconnected", reconnect=state["reconnects"])
                    await client.stop()
                    await asyncio.sleep(min(self._backoff(1), max(0.0, deadline - time.monotonic())))
        except asyncio.CancelledError:
            # SIGINT from Ctrl-C or from the parent Muse recorder: a normal stop.
            uncancel = getattr(asyncio.current_task(), "uncancel", None)
            if uncancel is not None:
                uncancel()
            state["stop_reason"] = "user_stopped"
        finally:
            # Always stop PMD streams: an H10 left streaming stays on until its battery dies.
            await client.stop()
            if state["down_since"] is not None and (state["reconnects"] or state["failed_connects"]):
                gap = time.monotonic() - state["down_since"]
                state["downtime_seconds"] += gap
                downtimes.append({"start_mono": state["down_since"], "seconds": gap})
            anchor("stop")
            event("recording_stopped", reason=state["stop_reason"])
            raw_file.close()
            events_file.close()
            anchors_file.close()

        summary: Dict[str, object] = {
            "started_at": metadata["started_at"],
            "ended_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "duration_seconds": time.monotonic() - started_mono,
            "stop_reason": state["stop_reason"],
            "reconnects": state["reconnects"],
            "failed_connects": state["failed_connects"],
            "downtime_seconds": state["downtime_seconds"],
            "downtimes": downtimes,
            "notification_counts": counts,
        }
        # Summary first: a parent that stops us may kill us during decoding.
        self._write_json("summary.json", summary)
        try:
            summary["decode"] = decode_polar_session(self.config.output_dir)
        except Exception as exc:  # raw log is intact; decode-polar can retry
            summary["decode"] = {"error": str(exc)}
        self._write_json("summary.json", summary)
        return summary

    def _backoff(self, attempt: int) -> float:
        return min(self.config.backoff_max_seconds, self.config.backoff_base_seconds * 2 ** max(0, attempt - 1))

    def _write_json(self, name: str, payload: Mapping[str, object]) -> None:
        path = self.polar_dir / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)


# --- decoding ---------------------------------------------------------------------


def iter_raw_notifications(polar_dir: Path):
    path = Path(polar_dir) / RAW_FILENAME
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue  # a torn last line after a hard kill
            record["payload"] = base64.b64decode(record["b64"])
            yield record


def decode_polar_session(session_dir: Path) -> Dict[str, object]:
    """Rebuild hr_rr.jsonl, ecg.jsonl and acc.jsonl from the raw log.

    Stream settings are recovered from the logged control point traffic: the
    start command we sent (rate, resolution, range, channels) and the device's
    start response (conversion factor).
    """
    polar_dir = Path(session_dir) / POLAR_DIRNAME
    settings: Dict[int, PmdStreamSettings] = {}
    pending_start: Dict[int, Dict[int, int]] = {}
    previous_timestamp: Dict[int, Optional[int]] = {MEASUREMENT_ECG: None, MEASUREMENT_ACC: None}
    counts = {"hr": 0, "rr": 0, "ecg_frames": 0, "ecg_samples": 0, "acc_frames": 0, "acc_samples": 0}
    errors: Dict[str, int] = {}
    gaps: Dict[str, List[Dict[str, float]]] = {"ecg": [], "acc": []}
    assembler = ControlPointAssembler()

    outputs = {
        "hr": (polar_dir / "hr_rr.jsonl.tmp").open("w", encoding="utf-8"),
        "ecg": (polar_dir / "ecg.jsonl.tmp").open("w", encoding="utf-8"),
        "acc": (polar_dir / "acc.jsonl.tmp").open("w", encoding="utf-8"),
    }
    try:
        for record in iter_raw_notifications(polar_dir):
            payload = record["payload"]
            char = record["char"]
            try:
                if char == "pmd_cp" and record["dir"] == "tx" and payload[:1] == bytes((CP_START,)):
                    measurement_type, selected = parse_start_command(payload)
                    pending_start[measurement_type] = selected
                    # A new stream start resets the frame-to-frame period estimate.
                    previous_timestamp[measurement_type] = None
                elif char == "pmd_cp" and record["dir"] == "rx" and payload[:1] == bytes((CP_RESPONSE,)):
                    response = assembler.feed(payload)
                    if response is None:
                        continue
                    if response.op_code == CP_START and response.measurement_type in pending_start:
                        selected = pending_start.pop(response.measurement_type)
                        factor = factor_from_settings(parse_settings(response.parameters)) if response.parameters else None
                        settings[response.measurement_type] = PmdStreamSettings(
                            sample_rate=selected.get(SETTING_SAMPLE_RATE, 0),
                            resolution=selected.get(SETTING_RESOLUTION, 16),
                            channels=selected.get(SETTING_CHANNELS, DEFAULT_CHANNELS[response.measurement_type]),
                            factor=factor if factor else 1.0,
                            range=selected.get(SETTING_RANGE),
                        )
                elif char == "hr":
                    measurement = parse_heart_rate_measurement(payload)
                    counts["hr"] += 1
                    counts["rr"] += len(measurement.rr_intervals_ms)
                    outputs["hr"].write(
                        json.dumps(
                            {
                                "seq": record["seq"],
                                "host_wall": record["wall"],
                                "host_mono": record["mono"],
                                "hr_bpm": measurement.heart_rate_bpm,
                                "contact": measurement.sensor_contact,
                                "contact_supported": measurement.sensor_contact_supported,
                                "energy_kj": measurement.energy_expended_kj,
                                "rr_ms": list(measurement.rr_intervals_ms),
                            },
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                elif char == "pmd_data":
                    measurement_type = payload[0] & 0x3F
                    if measurement_type not in (MEASUREMENT_ECG, MEASUREMENT_ACC):
                        continue
                    stream = settings.get(measurement_type) or PmdStreamSettings(
                        sample_rate=130 if measurement_type == MEASUREMENT_ECG else 50,
                        resolution=14 if measurement_type == MEASUREMENT_ECG else 16,
                        channels=DEFAULT_CHANNELS[measurement_type],
                    )
                    frame = parse_pmd_frame(payload, stream)
                    if not frame.samples:
                        continue
                    name = MEASUREMENT_NAMES[measurement_type]
                    previous = previous_timestamp[measurement_type]
                    t0_ns, dt_ns = sample_times_ns(frame.timestamp_ns, previous, len(frame.samples), stream.sample_rate)
                    if previous is not None:
                        expected = len(frame.samples) * 1e9 / stream.sample_rate
                        jump = frame.timestamp_ns - previous
                        if jump > 1.5 * expected:
                            gaps[name].append({"sensor_ns": previous, "seconds": (jump - expected) / 1e9})
                    previous_timestamp[measurement_type] = frame.timestamp_ns
                    row: Dict[str, object] = {
                        "seq": record["seq"],
                        "host_wall": record["wall"],
                        "host_mono": record["mono"],
                        "sensor_ns": frame.timestamp_ns,
                        "t0_ns": t0_ns,
                        "dt_ns": dt_ns,
                        "n": len(frame.samples),
                    }
                    if measurement_type == MEASUREMENT_ECG:
                        row["uv"] = [sample[0] for sample in frame.samples]
                    else:
                        row["x"] = [sample[0] for sample in frame.samples]
                        row["y"] = [sample[1] for sample in frame.samples]
                        row["z"] = [sample[2] for sample in frame.samples]
                    outputs[name].write(json.dumps(row, separators=(",", ":")) + "\n")
                    counts[f"{name}_frames"] += 1
                    counts[f"{name}_samples"] += len(frame.samples)
            except Exception as exc:
                key = f"{char}:{type(exc).__name__}"
                errors[key] = errors.get(key, 0) + 1
    finally:
        for handle in outputs.values():
            handle.close()
    for name, filename in (("hr", "hr_rr.jsonl"), ("ecg", "ecg.jsonl"), ("acc", "acc.jsonl")):
        os.replace(polar_dir / f"{filename}.tmp", polar_dir / filename)

    result = {
        "counts": counts,
        "errors": errors,
        "gaps": {name: {"count": len(items), "seconds": sum(item["seconds"] for item in items)} for name, items in gaps.items()},
        "stream_settings": {MEASUREMENT_NAMES[key]: value.to_dict() for key, value in settings.items()},
    }
    (polar_dir / "decode_summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
