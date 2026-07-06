"""Overnight recording orchestration."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from muse_raw_stream import MuseRawStream

from muse_tmr.data.sample_types import MuseFrame
from muse_tmr.data.watchdog import RecordingWatchdog, WatchdogEvent
from muse_tmr.sources.base_source import BaseMuseSource, MuseSourceMetadata


@dataclass(frozen=True)
class RecordingConfig:
    output_dir: Path
    duration_seconds: float
    source_name: str = "amused"
    no_data_timeout_seconds: float = 30.0
    modality_timeout_seconds: float = 120.0
    max_reconnect_attempts: int = 5
    allow_short: bool = False

    def validate(self) -> None:
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if not self.allow_short and not 7200 <= self.duration_seconds <= 28800:
            raise ValueError("overnight recordings must be between 2 and 8 hours")


@dataclass(frozen=True)
class RecordingSummary:
    output_dir: str
    raw_path: str
    decoded_frames_path: str
    metadata_path: str
    events_path: str
    summary_path: str
    started_at: str
    ended_at: str
    duration_seconds: float
    frame_count: int
    raw_packet_count: int
    decoded_frame_count: int
    modality_counts: Dict[str, int]
    reconnect_attempts: int
    downtime_seconds: float
    stop_reason: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "output_dir": self.output_dir,
            "raw_path": self.raw_path,
            "decoded_frames_path": self.decoded_frames_path,
            "metadata_path": self.metadata_path,
            "events_path": self.events_path,
            "summary_path": self.summary_path,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "frame_count": self.frame_count,
            "raw_packet_count": self.raw_packet_count,
            "decoded_frame_count": self.decoded_frame_count,
            "modality_counts": self.modality_counts,
            "reconnect_attempts": self.reconnect_attempts,
            "downtime_seconds": self.downtime_seconds,
            "stop_reason": self.stop_reason,
        }


class OvernightRecorder:
    """Record MuseFrames, raw packets, metadata, events, and a summary."""

    def __init__(
        self,
        config: RecordingConfig,
        watchdog: Optional[RecordingWatchdog] = None,
    ) -> None:
        config.validate()
        self.config = config
        self.watchdog = watchdog or RecordingWatchdog(
            no_data_timeout_seconds=config.no_data_timeout_seconds,
            modality_timeout_seconds=config.modality_timeout_seconds,
        )

    async def record(self, source: BaseMuseSource) -> RecordingSummary:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        raw_path = self.config.output_dir / "raw_amused.bin"
        decoded_frames_path = self.config.output_dir / "decoded_frames.jsonl"
        metadata_path = self.config.output_dir / "metadata.json"
        events_path = self.config.output_dir / "events.jsonl"
        summary_path = self.config.output_dir / "summary.json"

        started_at_dt = dt.datetime.now(dt.timezone.utc)
        started_monotonic = time.monotonic()
        deadline = started_monotonic + self.config.duration_seconds

        metadata = await source.connect()
        self._write_metadata(metadata_path, metadata, started_at_dt)

        frame_count = 0
        raw_packet_count = 0
        decoded_frame_count = 0
        reconnect_attempts = 0
        downtime_seconds = 0.0
        modality_counts: Dict[str, int] = {}
        stop_reason = "duration_complete"

        raw_stream = MuseRawStream(str(raw_path))
        raw_stream.open_write()

        with events_path.open("w", encoding="utf-8") as events_file, decoded_frames_path.open(
            "w", encoding="utf-8"
        ) as decoded_frames_file:
            self._write_event(
                events_file,
                WatchdogEvent(
                    event="recording_started",
                    timestamp=started_monotonic,
                    details={"source": metadata.source_name},
                ),
            )

            try:
                stream = source.stream().__aiter__()
                while time.monotonic() < deadline:
                    timeout = min(
                        self.config.no_data_timeout_seconds,
                        max(0.01, deadline - time.monotonic()),
                    )
                    try:
                        frame = await asyncio.wait_for(stream.__anext__(), timeout=timeout)
                    except asyncio.TimeoutError:
                        now = time.monotonic()
                        if now >= deadline:
                            break
                        event = self.watchdog.no_data_event(now)
                        if event:
                            self._write_event(events_file, event)

                        new_stream, reconnect_attempts, exhausted, added_downtime = (
                            await self._reconnect_until_ready(
                                source, events_file, reconnect_attempts, deadline
                            )
                        )
                        downtime_seconds += added_downtime
                        if new_stream is None:
                            if exhausted:
                                stop_reason = "max_reconnect_attempts"
                            break
                        stream = new_stream
                        continue
                    except StopAsyncIteration:
                        stop_reason = "source_ended"
                        break
                    except Exception as exc:
                        now = time.monotonic()
                        self._write_event(
                            events_file,
                            WatchdogEvent(
                                event="stream_error",
                                timestamp=now,
                                details={"error": str(exc)},
                            ),
                        )

                        new_stream, reconnect_attempts, exhausted, added_downtime = (
                            await self._reconnect_until_ready(
                                source, events_file, reconnect_attempts, deadline
                            )
                        )
                        downtime_seconds += added_downtime
                        if new_stream is None:
                            if exhausted:
                                stop_reason = "max_reconnect_attempts"
                            break
                        stream = new_stream
                        continue

                    frame_count += 1
                    for modality in frame.modalities():
                        modality_counts[modality] = modality_counts.get(modality, 0) + 1

                    if frame.raw_packet:
                        packet_timestamp = dt.datetime.fromtimestamp(frame.timestamp)
                        if packet_timestamp < raw_stream.session_start:
                            packet_timestamp = raw_stream.session_start
                        raw_stream.write_packet(
                            frame.raw_packet,
                            packet_timestamp,
                        )
                        raw_packet_count += 1

                    decoded_frames_file.write(frame.to_json(include_raw=False) + "\n")
                    decoded_frames_file.flush()
                    decoded_frame_count += 1

                    for event in self.watchdog.observe_frame(frame, time.monotonic()):
                        self._write_event(events_file, event)
            finally:
                raw_stream.close()
                await source.stop()

            ended_at_dt = dt.datetime.now(dt.timezone.utc)
            self._write_event(
                events_file,
                WatchdogEvent(
                    event="recording_stopped",
                    timestamp=time.monotonic(),
                    details={"reason": stop_reason},
                ),
            )

        summary = RecordingSummary(
            output_dir=str(self.config.output_dir),
            raw_path=str(raw_path),
            decoded_frames_path=str(decoded_frames_path),
            metadata_path=str(metadata_path),
            events_path=str(events_path),
            summary_path=str(summary_path),
            started_at=started_at_dt.isoformat(),
            ended_at=ended_at_dt.isoformat(),
            duration_seconds=(ended_at_dt - started_at_dt).total_seconds(),
            frame_count=frame_count,
            raw_packet_count=raw_packet_count,
            decoded_frame_count=decoded_frame_count,
            modality_counts=modality_counts,
            reconnect_attempts=reconnect_attempts,
            downtime_seconds=downtime_seconds,
            stop_reason=stop_reason,
        )
        summary_path.write_text(
            json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return summary

    async def _reconnect_until_ready(
        self,
        source: BaseMuseSource,
        events_file,
        reconnect_attempts: int,
        deadline: float,
    ) -> Tuple[Optional[Any], int, bool, float]:
        """Retry connecting to `source` until it succeeds, the reconnect
        budget is exhausted, or the recording deadline passes.

        A failure raised by `source.stop()`/`source.connect()` during a
        reconnect attempt (e.g. the device is genuinely gone) is treated as
        just another failed attempt instead of being allowed to propagate
        and crash the whole recording.

        Returns (new_stream_or_None, updated_reconnect_attempts,
        budget_exhausted, downtime_seconds_added).
        """
        downtime_added = 0.0
        while True:
            if reconnect_attempts >= self.config.max_reconnect_attempts:
                return None, reconnect_attempts, True, downtime_added
            if time.monotonic() >= deadline:
                return None, reconnect_attempts, False, downtime_added

            reconnect_attempts += 1
            backoff = self.watchdog.reconnect_backoff(reconnect_attempts)
            downtime_start = time.monotonic()
            self._write_event(
                events_file,
                WatchdogEvent(
                    event="reconnect_scheduled",
                    timestamp=downtime_start,
                    details={"attempt": reconnect_attempts, "backoff_seconds": backoff},
                ),
            )
            try:
                await source.stop()
                await asyncio.sleep(backoff)
                await source.connect()
                stream = source.stream().__aiter__()
            except Exception as exc:
                downtime_added += time.monotonic() - downtime_start
                self._write_event(
                    events_file,
                    WatchdogEvent(
                        event="reconnect_failed",
                        timestamp=time.monotonic(),
                        details={"attempt": reconnect_attempts, "error": str(exc)},
                    ),
                )
                continue

            downtime_added += time.monotonic() - downtime_start
            return stream, reconnect_attempts, False, downtime_added

    def _write_metadata(
        self,
        metadata_path: Path,
        metadata: MuseSourceMetadata,
        started_at: dt.datetime,
    ) -> None:
        payload = {
            "started_at": started_at.isoformat(),
            "source": {
                "source_name": metadata.source_name,
                "device_name": metadata.device_name,
                "device_id": metadata.device_id,
                "capabilities": dict(metadata.capabilities),
                "metadata": dict(metadata.metadata or {}),
            },
            "config": {
                "duration_seconds": self.config.duration_seconds,
                "source_name": self.config.source_name,
                "no_data_timeout_seconds": self.config.no_data_timeout_seconds,
                "modality_timeout_seconds": self.config.modality_timeout_seconds,
                "max_reconnect_attempts": self.config.max_reconnect_attempts,
            },
        }
        metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _write_event(self, events_file, event: WatchdogEvent) -> None:
        events_file.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        events_file.flush()
