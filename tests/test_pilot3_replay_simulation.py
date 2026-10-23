import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import muse_athena_protocol as proto
import numpy as np
from muse_raw_stream import MuseRawStream

from muse_tmr.audio import CueLibrary, CueMetadata
from muse_tmr.cli.main import main as cli_main
from muse_tmr.data.sample_types import EEGSample, HeartRateSample, IMUSample, MuseFrame, PPGSample
from muse_tmr.features import EpochBuilder, EpochConfig
from muse_tmr.models import RemGateConfig
from muse_tmr.protocol import (
    NightPuzzleSession,
    PuzzleCatalog,
    PuzzleCueAssignment,
    PuzzleTask,
    TmrSchedulerConfig,
)
from muse_tmr.validation import pilot3 as pilot3_module
from muse_tmr.validation import simulate_cue_plan_from_epochs, simulate_replay_cue_plan
from tests.rem_event_synthetic import rem_deflection_train


EEG_RATE_HZ = 256
IMU_RATE_HZ = 52
PPG_RATE_HZ = 64


def sine_values(frequency_hz, *, seconds=30.0, sample_rate_hz=EEG_RATE_HZ, amplitude=10.0):
    timestamps = np.arange(0, seconds, 1 / sample_rate_hz)
    return amplitude * np.sin(2 * np.pi * frequency_hz * timestamps)


def rem_like_eeg_channels():
    theta = sine_values(6.0, amplitude=12.0)
    alpha = sine_values(10.0, amplitude=1.0)
    eye = rem_deflection_train()
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


def build_rem_epoch(index, *, with_optics=True):
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
            ppg=(
                PPGSample(timestamp, {"LO_NIR": synthetic_ppg(72.0)}, source="test")
                if with_optics
                else None
            ),
            source="test",
        )
    ]
    for sample_index in range(30 if with_optics else 0):
        frames.append(
            MuseFrame(
                timestamp=timestamp + sample_index,
                heart_rate=HeartRateSample(
                    timestamp + sample_index,
                    bpm=68.0 + (sample_index % 5),
                    source="test",
                ),
                source="test",
            )
        )
    return EpochBuilder(EpochConfig(epoch_seconds=30, stride_seconds=30))._build_epoch(
        index,
        timestamp,
        tuple(frames),
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
        library_id="pilot3-test",
        cues=(
            CueMetadata("cue-p1", "generated_tone", 1.0, protocol="puzzle", frequency_hz=440.0),
            CueMetadata("cue-p3", "generated_tone", 1.0, protocol="puzzle", frequency_hz=660.0),
        ),
    )
    return catalog, session, assignment, cue_library


def build_tag_packet(first_tag, first_data):
    header = bytearray(14)
    header[9] = first_tag
    return bytes(header) + first_data


def write_synthetic_recording(recording_dir: Path) -> Path:
    recording_dir.mkdir(parents=True, exist_ok=True)
    raw_path = recording_dir / "raw_amused.bin"
    stream = MuseRawStream(str(raw_path))
    stream.open_write()
    base_time = stream.session_start
    stream.write_packet(build_tag_packet(proto.TAG_EEG_4CH, bytes(28)), base_time)
    stream.write_packet(
        build_tag_packet(proto.TAG_ACCGYRO, bytes(36)),
        base_time + dt.timedelta(seconds=10),
    )
    stream.write_packet(
        build_tag_packet(proto.TAG_OPTICS_8CH, bytes(60)),
        base_time + dt.timedelta(seconds=40),
    )
    stream.close()
    return raw_path


def pack_eeg_4ch(rows_uv):
    """Pack 4 samples x 4 channels of microvolts into one 28-byte EEG subpacket."""
    counts = np.clip(
        np.round(np.asarray(rows_uv) / proto.EEG_SCALE_UV_PER_COUNT) + proto.EEG_MID_COUNT,
        0,
        proto.EEG_MAX_COUNT,
    ).astype(int)
    packed = 0
    for index, count in enumerate(counts.ravel()):
        packed |= int(count) << (proto.EEG_BITS * index)
    return packed.to_bytes(28, "little")


def still_accgyro_subpacket():
    rows = [[0, 0, round(1.0 / proto.ACC_SCALE), 0, 0, 0]] * 3
    return np.asarray(rows, dtype="<i2").tobytes()


def eeg_only_epoch_uv(kind):
    timestamps = np.arange(0, 30.0, 1 / EEG_RATE_HZ)
    if kind == "rem":
        background = sine_values(6.0, amplitude=12.0) + sine_values(10.0, amplitude=1.0)
        eye = sine_values(1.0, amplitude=8.0)
        return np.stack([background, background + eye, background - eye, background], axis=1)
    slow = 40.0 * np.sin(2 * np.pi * 1.5 * timestamps) + 4.0 * np.sin(2 * np.pi * 6.0 * timestamps)
    return np.stack([slow] * 4, axis=1)


def write_eeg_only_recording(recording_dir: Path, epoch_kinds) -> Path:
    """A p21-style recording: EEG and IMU notifications, no TAG_OPTICS_* packets."""
    recording_dir.mkdir(parents=True, exist_ok=True)
    raw_path = recording_dir / "raw_amused.bin"
    channels_uv = np.concatenate([eeg_only_epoch_uv(kind) for kind in epoch_kinds])
    stream = MuseRawStream(str(raw_path))
    stream.open_write()
    base_time = stream.session_start
    eeg_counter = 0
    for notification, start in enumerate(range(0, channels_uv.shape[0], 16)):
        header = bytearray(14)
        header[9] = proto.TAG_EEG_4CH
        header[10] = eeg_counter % 256
        payload = bytes(header) + pack_eeg_4ch(channels_uv[start:start + 4])
        eeg_counter += 1
        for offset in (4, 8, 12):
            payload += bytes([proto.TAG_EEG_4CH, eeg_counter % 256, 0, 0, 0])
            payload += pack_eeg_4ch(channels_uv[start + offset:start + offset + 4])
            eeg_counter += 1
        payload += bytes([proto.TAG_ACCGYRO, notification % 256, 0, 0, 0])
        payload += still_accgyro_subpacket()
        stream.write_packet(payload, base_time + dt.timedelta(seconds=start / EEG_RATE_HZ))
    stream.close()
    return raw_path


class TestPilot3ReplaySimulation(unittest.TestCase):
    def test_replay_cue_plan_uses_mock_audio_and_only_cued_puzzles(self):
        catalog, session, assignment, cue_library = protocol_fixture()
        report = simulate_cue_plan_from_epochs(
            [build_rem_epoch(index) for index in range(4)],
            catalog=catalog,
            session=session,
            assignment=assignment,
            cue_library=cue_library,
            recording_input="synthetic-replay",
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

        self.assertTrue(report.passed)
        self.assertFalse(report.audio_playback_executed)
        self.assertEqual(report.audio_backend, "mock")
        self.assertEqual(report.metrics["uncued_puzzle_play_count"], 0)
        self.assertEqual([event.puzzle_id for event in report.cue_plan], ["p1", "p3"])
        self.assertGreaterEqual(report.metrics["scheduler_event_count"], 4)

    def test_report_and_scheduler_events_are_inspectable_files(self):
        catalog, session, assignment, cue_library = protocol_fixture()
        report = simulate_cue_plan_from_epochs(
            [build_rem_epoch(0), build_rem_epoch(1)],
            catalog=catalog,
            session=session,
            assignment=assignment,
            cue_library=cue_library,
            gate_config=RemGateConfig(
                enter_threshold=0.60,
                exit_threshold=0.45,
                min_stable_seconds=60.0,
                epoch_seconds=30.0,
                cooldown_seconds=0.0,
            ),
            scheduler_config=TmrSchedulerConfig(enable_tlr_block=False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = report.save(Path(tmpdir) / "pilot3_report.json")
            events_path = report.save_scheduler_events(Path(tmpdir) / "events.jsonl")

            saved = json.loads(report_path.read_text(encoding="utf-8"))
            event_lines = events_path.read_text(encoding="utf-8").splitlines()

        self.assertTrue(saved["passed"])
        self.assertEqual(saved["audio_backend"], "mock")
        self.assertFalse(saved["audio_playback_executed"])
        self.assertGreaterEqual(len(saved["scheduler_events"]), 2)
        self.assertGreaterEqual(len(event_lines), 2)

    def test_one_rem_event_tracker_for_the_whole_replay(self):
        catalog, session, assignment, cue_library = protocol_fixture()
        trackers = []
        extract = pilot3_module.extract_eeg_features

        def recording_extract(epoch, *args, **kwargs):
            trackers.append(kwargs.get("rem_tracker"))
            return extract(epoch, *args, **kwargs)

        with mock.patch.object(pilot3_module, "extract_eeg_features", recording_extract):
            report = simulate_cue_plan_from_epochs(
                [build_rem_epoch(index) for index in range(4)],
                catalog=catalog,
                session=session,
                assignment=assignment,
                cue_library=cue_library,
            )

        self.assertEqual(len(trackers), 4)
        self.assertIsNotNone(trackers[0])
        self.assertTrue(all(tracker is trackers[0] for tracker in trackers))
        counts = [result.prediction.feature_values["rem_event_count"] for result in report.epoch_results]
        self.assertEqual(counts, [8.0] * 4)

    def test_empty_replay_epochs_fail_without_calling_audio(self):
        catalog, session, assignment, cue_library = protocol_fixture()
        report = simulate_cue_plan_from_epochs(
            [],
            catalog=catalog,
            session=session,
            assignment=assignment,
            cue_library=cue_library,
        )

        self.assertFalse(report.passed)
        self.assertIn("epochs_present", report.failed_criteria)
        self.assertFalse(report.audio_playback_executed)


class TestPilot3ReplayPipeline(unittest.IsolatedAsyncioTestCase):
    async def test_replay_recording_generates_mocked_plan_report(self):
        catalog, session, assignment, cue_library = protocol_fixture()
        with tempfile.TemporaryDirectory() as tmpdir:
            recording_dir = Path(tmpdir) / "recording"
            write_synthetic_recording(recording_dir)

            report = await simulate_replay_cue_plan(
                recording_dir,
                catalog=catalog,
                session=session,
                assignment=assignment,
                cue_library=cue_library,
                scheduler_config=TmrSchedulerConfig(enable_tlr_block=False),
            )

        self.assertTrue(report.passed)
        self.assertGreater(report.metrics["epoch_count"], 0)
        self.assertGreater(report.metrics["scheduler_event_count"], 0)
        self.assertFalse(report.audio_playback_executed)


class TestPilot3EegOnlyPreset(unittest.TestCase):
    """A p21 night has no optics by design; the guard must not pause it for that."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmpdir.name)
        write_eeg_only_recording(cls.root / "recording", ["nrem"] * 3 + ["rem"] * 5)
        catalog, session, assignment, cue_library = protocol_fixture()
        catalog.save(cls.root / "catalog.json")
        session.save(cls.root / "session.json")
        assignment.save(cls.root / "assignment.json")
        cue_library.save(cls.root / "cues.json")

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def _simulate(self, preset):
        output = self.root / f"report_{preset}.json"
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = cli_main([
                "simulate-replay-cues", str(self.root / "recording"),
                "--catalog", str(self.root / "catalog.json"),
                "--session", str(self.root / "session.json"),
                "--assignment", str(self.root / "assignment.json"),
                "--cue-library", str(self.root / "cues.json"),
                "--output", str(output),
                "--preset", preset,
            ])
        self.assertEqual(exit_code, 0)
        return json.loads(output.read_text(encoding="utf-8"))

    def test_recording_has_no_optics_packets(self):
        stream = MuseRawStream(str(self.root / "recording" / "raw_amused.bin"))
        stream.open_read()
        try:
            tags = set()
            for packet in stream.read_packets():
                tags.update(proto.inspect_payload(packet.data)["tags"])
        finally:
            stream.close()
        self.assertEqual(tags, {proto.TAG_EEG_4CH, proto.TAG_ACCGYRO})

    def test_p21_replay_plays_cues_without_repeated_artifact_pauses(self):
        report = self._simulate("p21")
        guard = [epoch["arousal_guard_decision"] for epoch in report["epochs"]]

        repeated_artifact_pauses = [
            decision for decision in guard
            if decision["action"] == "pause"
            and "repeated_artifact_quality" in decision["reason_codes"]
        ]
        self.assertEqual(repeated_artifact_pauses, [])
        self.assertTrue(all(decision["action"] == "allow" for decision in guard))
        self.assertTrue(all(decision["metadata"]["ppg_absent_by_design"] for decision in guard))
        self.assertGreaterEqual(report["metrics"]["cue_plan_count"], 1)
        self.assertEqual(report["metrics"]["uncued_puzzle_play_count"], 0)
        self.assertTrue(report["passed"])

    def test_optics_preset_still_pauses_when_optics_are_missing(self):
        report = self._simulate("p1034")
        actions = [epoch["arousal_guard_decision"]["action"] for epoch in report["epochs"]]

        self.assertEqual(actions, ["lower_volume"] * 2 + ["pause"] * 6)
        for epoch in report["epochs"][2:]:
            self.assertIn(
                "repeated_artifact_quality", epoch["arousal_guard_decision"]["reason_codes"]
            )
        self.assertEqual(report["metrics"]["uncued_puzzle_play_count"], 0)

    def test_guard_default_follows_gate_optics_capable(self):
        catalog, session, assignment, cue_library = protocol_fixture()
        report = simulate_cue_plan_from_epochs(
            [build_rem_epoch(index, with_optics=False) for index in range(4)],
            catalog=catalog,
            session=session,
            assignment=assignment,
            cue_library=cue_library,
            gate_config=RemGateConfig(
                enter_threshold=0.60,
                exit_threshold=0.45,
                min_stable_seconds=60.0,
                epoch_seconds=30.0,
                cooldown_seconds=0.0,
                optics_capable=False,
            ),
            scheduler_config=TmrSchedulerConfig(enable_tlr_block=False),
        )

        decisions = [result.arousal_guard_decision for result in report.epoch_results]
        self.assertEqual([decision.action for decision in decisions], ["allow"] * 4)
        self.assertTrue(all(decision.metadata["ppg_absent_by_design"] for decision in decisions))


if __name__ == "__main__":
    unittest.main()
