import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from muse_tmr.audio import CueLibrary, CueMetadata, MockAudioBackend, VolumeCalibration
from muse_tmr.data.sample_types import EEGSample, HeartRateSample, IMUSample, MuseFrame, PPGSample
from muse_tmr.features import EpochConfig
from muse_tmr.models import RemGateConfig
from muse_tmr.protocol import (
    NightPuzzleSession,
    PuzzleCatalog,
    PuzzleCueAssignment,
    PuzzleTask,
    TmrSchedulerConfig,
)
from muse_tmr.sources.base_source import MuseDeviceInfo, MuseSourceMetadata
from muse_tmr.validation import (
    AwakeningEvent,
    Pilot4CueingConfig,
    append_awakening_event,
    run_pilot4_cueing_night,
)


EEG_RATE_HZ = 256
IMU_RATE_HZ = 52
PPG_RATE_HZ = 64


class FakeMuseSource:
    def __init__(self, frames):
        self.frames = tuple(frames)
        self.stop_calls = 0

    async def discover(self):
        return (MuseDeviceInfo(name="Fake Muse", address="fake", rssi=0),)

    async def connect(self, device=None):
        return MuseSourceMetadata(
            source_name="fake",
            device_name="Fake Muse",
            device_id="fake-device",
            capabilities={"eeg": True, "imu": True, "ppg": True, "raw_packets": True},
        )

    async def stream(self):
        for frame in self.frames:
            await asyncio.sleep(0)
            yield frame

    async def stop(self):
        self.stop_calls += 1


class TestPilot4Cueing(unittest.IsolatedAsyncioTestCase):
    async def test_low_volume_cueing_plays_only_cued_puzzles_with_calibration_cap(self):
        catalog, session, assignment, cue_library = protocol_fixture()
        backend = MockAudioBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = await run_pilot4_cueing_night(
                FakeMuseSource(rem_frames(4)),
                config=pilot4_config(Path(tmpdir)),
                catalog=catalog,
                session=session,
                assignment=assignment,
                cue_library=cue_library,
                calibration=VolumeCalibration("Sleep Headphones", 0.01, 0.02, 0.04),
                backend=backend,
            )

            audio_events = [
                json.loads(line)
                for line in Path(summary.audio_log_path).read_text(encoding="utf-8").splitlines()
            ]
            scheduler_events = [
                json.loads(line)
                for line in Path(summary.scheduler_events_path).read_text(encoding="utf-8").splitlines()
            ]

        self.assertTrue(summary.passed)
        self.assertEqual(summary.cue_play_count, 2)
        self.assertEqual(summary.uncued_puzzle_play_count, 0)
        self.assertEqual([event["puzzle_id"] for event in scheduler_events if event["event_type"] == "play"], ["p1", "p3"])
        self.assertEqual(len(backend.requests), 2)
        self.assertLessEqual(summary.max_effective_volume, 0.04)
        self.assertTrue(all(event["effective_volume"] <= 0.04 for event in audio_events))
        self.assertTrue(all(event["backend_name"] == "mock" for event in audio_events))

    async def test_emergency_stop_file_blocks_audio_backend_requests(self):
        catalog, session, assignment, cue_library = protocol_fixture()
        backend = MockAudioBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            emergency_stop_path = output_dir / "STOP_AUDIO"
            emergency_stop_path.touch()
            summary = await run_pilot4_cueing_night(
                FakeMuseSource(rem_frames(4)),
                config=pilot4_config(output_dir, emergency_stop_path=emergency_stop_path),
                catalog=catalog,
                session=session,
                assignment=assignment,
                cue_library=cue_library,
                calibration=VolumeCalibration("Sleep Headphones", 0.01, 0.02, 0.04),
                backend=backend,
            )

        self.assertTrue(summary.passed)
        self.assertTrue(summary.emergency_stop_triggered)
        self.assertEqual(backend.stop_calls, 1)
        self.assertEqual(backend.requests, [])
        self.assertEqual(summary.audio_status_counts.get("blocked"), 2)

    async def test_awakening_events_append_jsonl_markers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "awakening_events.jsonl"
            append_awakening_event(
                output_path,
                AwakeningEvent(
                    event_type="awakening",
                    timestamp_utc="2026-05-13T22:00:00+00:00",
                    notes="woke briefly",
                ),
            )
            event = json.loads(output_path.read_text(encoding="utf-8").strip())

        self.assertEqual(event["event_type"], "awakening")
        self.assertEqual(event["notes"], "woke briefly")


def pilot4_config(output_dir: Path, *, emergency_stop_path=None):
    return Pilot4CueingConfig(
        output_dir=output_dir,
        duration_seconds=1.0,
        allow_short=True,
        audio_backend_name="mock",
        hard_max_volume=0.20,
        default_volume=0.02,
        emergency_stop_path=emergency_stop_path,
        epoch_config=EpochConfig(epoch_seconds=30, stride_seconds=30),
        gate_config=RemGateConfig(
            enter_threshold=0.60,
            exit_threshold=0.45,
            min_stable_seconds=60.0,
            epoch_seconds=30.0,
            cooldown_seconds=0.0,
        ),
        scheduler_config=TmrSchedulerConfig(
            puzzle_cue_interval_seconds=30.0,
            cooldown_seconds=30.0,
            max_puzzle_cues_per_block=4,
            enable_tlr_block=False,
        ),
    )


def protocol_fixture():
    catalog = PuzzleCatalog(
        puzzles=(
            PuzzleTask("p1", "one", "one", cue_id="cue-p1"),
            PuzzleTask("p2", "two", "two", cue_id="cue-p2"),
            PuzzleTask("p3", "three", "three", cue_id="cue-p3"),
            PuzzleTask("p4", "four", "four", cue_id="cue-p4"),
        )
    )
    session = NightPuzzleSession(
        session_id="night-001",
        puzzle_ids=("p1", "p2", "p3", "p4"),
        puzzle_count=4,
    )
    assignment = PuzzleCueAssignment(
        session_id="night-001",
        cued_puzzle_ids=("p1", "p3"),
        uncued_puzzle_ids=("p2", "p4"),
        seed=17,
    )
    cue_library = CueLibrary(
        library_id="pilot4-test",
        cues=(
            CueMetadata(
                "cue-p1",
                "generated_tone",
                0.01,
                protocol="puzzle",
                frequency_hz=440.0,
                volume_hint=0.10,
            ),
            CueMetadata(
                "cue-p3",
                "generated_tone",
                0.01,
                protocol="puzzle",
                frequency_hz=660.0,
                volume_hint=0.10,
            ),
        ),
    )
    return catalog, session, assignment, cue_library


def rem_frames(count):
    frames = []
    for index in range(count):
        frames.extend(build_rem_frames(index))
    return frames


def build_rem_frames(index):
    timestamp = 1000.0 + index * 30.0
    frames = [
        MuseFrame(
            timestamp=timestamp,
            eeg=EEGSample(timestamp, rem_like_eeg_channels(), source="test"),
            imu=IMUSample(
                timestamp,
                accelerometer_g=still_accel_rows(),
                gyroscope_dps=still_gyro_rows(),
                source="test",
            ),
            ppg=PPGSample(timestamp, {"LO_NIR": synthetic_ppg(72.0)}, source="test"),
            source="test",
            raw_packet=b"pilot4",
        )
    ]
    for sample_index in range(30):
        frames.append(
            MuseFrame(
                timestamp=timestamp + sample_index,
                heart_rate=HeartRateSample(
                    timestamp + sample_index,
                    bpm=68.0 + (sample_index % 5),
                    source="test",
                ),
                source="test",
                raw_packet=b"pilot4-hr",
            )
        )
    return frames


def sine_values(frequency_hz, *, seconds=30.0, sample_rate_hz=EEG_RATE_HZ, amplitude=10.0):
    timestamps = np.arange(0, seconds, 1 / sample_rate_hz)
    return amplitude * np.sin(2 * np.pi * frequency_hz * timestamps)


def rem_like_eeg_channels():
    theta = sine_values(6.0, amplitude=12.0)
    alpha = sine_values(10.0, amplitude=1.0)
    eye = sine_values(1.0, amplitude=4.5)
    return {
        "TP9": (theta + alpha).tolist(),
        "AF7": (theta + alpha + eye).tolist(),
        "AF8": (theta + alpha - eye).tolist(),
        "TP10": (theta + alpha).tolist(),
    }


def synthetic_ppg(heart_rate_bpm, *, seconds=30.0):
    timestamps = np.arange(0, seconds, 1 / PPG_RATE_HZ)
    heart_hz = heart_rate_bpm / 60.0
    pulse = np.sin(2 * np.pi * heart_hz * timestamps)
    harmonic = 0.25 * np.sin(4 * np.pi * heart_hz * timestamps - np.pi / 4)
    return (50000.0 + 1000.0 * (pulse + harmonic)).tolist()


def still_accel_rows():
    return [{"x": 0.0, "y": 0.0, "z": 1.0}] * (30 * IMU_RATE_HZ)


def still_gyro_rows():
    return [{"x": 0.0, "y": 0.0, "z": 0.0}] * (30 * IMU_RATE_HZ)


if __name__ == "__main__":
    unittest.main()
