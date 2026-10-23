import tempfile
import unittest
from pathlib import Path

from muse_tmr.data.replay import ReplayConfig, ReplaySession
from muse_tmr.data.sample_types import EEGSample, HeartRateSample, IMUSample, MuseFrame, PPGSample
from muse_tmr.features.epochs import EpochBuilder, EpochConfig, epoch_step_seconds
from muse_tmr.features.sleep_feature_extractor import EpochBuilder as CoordinatorEpochBuilder
from muse_tmr.testing import generate_night


async def async_frames(frames):
    for frame in frames:
        yield frame


def frame_at(
    timestamp: float,
    *,
    eeg_samples: int = 256,
    imu_samples: int = 52,
    ppg_samples: int = 64,
    heart_rate: bool = True,
) -> MuseFrame:
    eeg = (
        EEGSample(
            timestamp=timestamp,
            channels_uv={
                "TP9": [1.0] * eeg_samples,
                "AF7": [2.0] * eeg_samples,
                "AF8": [3.0] * eeg_samples,
                "TP10": [4.0] * eeg_samples,
            },
            source="test",
        )
        if eeg_samples
        else None
    )
    imu = (
        IMUSample(
            timestamp=timestamp,
            accelerometer_g=[{"x": 0.0, "y": 0.0, "z": 1.0}] * imu_samples,
            gyroscope_dps=[{"x": 0.0, "y": 0.0, "z": 0.0}] * imu_samples,
            source="test",
        )
        if imu_samples
        else None
    )
    ppg = (
        PPGSample(
            timestamp=timestamp,
            channels={"ch0": [10.0] * ppg_samples},
            source="test",
        )
        if ppg_samples
        else None
    )
    hr = HeartRateSample(timestamp=timestamp, bpm=60.0, source="test") if heart_rate else None
    return MuseFrame(timestamp=timestamp, eeg=eeg, imu=imu, ppg=ppg, heart_rate=hr, source="test")


class FakeLiveSource:
    def __init__(self, frames):
        self.frames = frames

    async def stream(self):
        for frame in self.frames:
            yield frame


class TestEpochBuilder(unittest.IsolatedAsyncioTestCase):
    async def test_builds_two_30_second_epochs(self):
        frames = [frame_at(1000.0 + second) for second in range(60)]
        builder = EpochBuilder(EpochConfig(epoch_seconds=30, stride_seconds=30))

        epochs = [epoch async for epoch in builder.build(async_frames(frames))]

        self.assertEqual(len(epochs), 2)
        self.assertEqual([epoch.start_time for epoch in epochs], [1000.0, 1030.0])
        self.assertEqual([epoch.frame_count for epoch in epochs], [30, 30])
        self.assertEqual(epochs[0].sample_counts["eeg"], 30 * 256)
        self.assertEqual(epochs[0].sample_counts["imu"], 30 * 52)
        self.assertEqual(epochs[0].sample_counts["ppg"], 30 * 64)
        self.assertEqual(epochs[0].coverage["eeg"], 1.0)
        self.assertEqual(epochs[0].quality_flags, ())

    async def test_stride_builds_overlapping_epochs(self):
        frames = [frame_at(1000.0 + second) for second in range(60)]
        builder = EpochBuilder(EpochConfig(epoch_seconds=30, stride_seconds=10))

        epochs = [epoch async for epoch in builder.build(async_frames(frames))]

        self.assertEqual([epoch.start_time for epoch in epochs], [1000.0, 1010.0, 1020.0, 1030.0])
        self.assertTrue(all(epoch.frame_count == 30 for epoch in epochs))

    async def test_overlapping_epochs_step_by_the_stride_not_their_length(self):
        frames = [frame_at(1_700_000_000.25 + second) for second in range(90)]
        builder = EpochBuilder(EpochConfig(epoch_seconds=30, stride_seconds=10))

        epochs = [epoch async for epoch in builder.build(async_frames(frames))]
        steps = []
        previous = None
        for epoch in epochs:
            steps.append(epoch_step_seconds(epoch.start_time, previous, 10.0))
            previous = epoch.start_time

        self.assertEqual(len(epochs), 7)
        self.assertEqual(steps, [10.0] * 7)
        self.assertTrue(all(epoch.duration_seconds == 30.0 for epoch in epochs))

    async def test_missing_modalities_are_quality_flags_not_errors(self):
        frames = [
            frame_at(
                1000.0 + second,
                imu_samples=0,
                ppg_samples=0,
                heart_rate=False,
            )
            for second in range(30)
        ]
        builder = EpochBuilder(EpochConfig(epoch_seconds=30, stride_seconds=30))

        epochs = [epoch async for epoch in builder.build(async_frames(frames))]

        self.assertEqual(len(epochs), 1)
        self.assertEqual(epochs[0].coverage["eeg"], 1.0)
        self.assertIn("missing_imu", epochs[0].quality_flags)
        self.assertIn("missing_ppg", epochs[0].quality_flags)
        self.assertIn("missing_heart_rate", epochs[0].quality_flags)

    async def test_low_sample_coverage_is_flagged(self):
        frames = [frame_at(1000.0 + second, eeg_samples=64) for second in range(30)]
        builder = EpochBuilder(
            EpochConfig(
                epoch_seconds=30,
                stride_seconds=30,
                min_coverage=0.5,
            )
        )

        epochs = [epoch async for epoch in builder.build(async_frames(frames))]

        self.assertAlmostEqual(epochs[0].coverage["eeg"], 0.25)
        self.assertIn("low_eeg_coverage", epochs[0].quality_flags)

    async def test_builder_accepts_live_source_stream(self):
        source = FakeLiveSource([frame_at(1000.0 + second) for second in range(31)])
        builder = EpochBuilder(EpochConfig(epoch_seconds=30, stride_seconds=30))

        epochs = [epoch async for epoch in builder.build(source.stream())]

        self.assertEqual(len(epochs), 2)
        self.assertEqual(epochs[0].frame_count, 30)

    async def test_builder_accepts_replay_session_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            recording_dir = Path(tmp)
            generate_night(output_dir=recording_dir, scenario="short_allow_short", hours=1 / 60)
            session = ReplaySession(ReplayConfig(input_path=recording_dir, speed=0.0))
            builder = EpochBuilder(EpochConfig(epoch_seconds=30, stride_seconds=30))

            epochs = [epoch async for epoch in builder.build(session.stream())]

            self.assertEqual(len(epochs), 2)
            for epoch in epochs:
                self.assertTrue({"eeg", "imu", "ppg"} <= set(epoch.modality_counts))
            # A full epoch, less the 1 % of EEG subpackets the scenario loses.
            self.assertGreater(epochs[0].coverage["eeg"], 0.97)
            self.assertEqual(epochs[0].quality_flags, ())


class TestEpochConfig(unittest.TestCase):
    def test_sleep_feature_extractor_reexports_epoch_builder(self):
        self.assertIs(CoordinatorEpochBuilder, EpochBuilder)

    def test_rejects_invalid_stride(self):
        with self.assertRaises(ValueError):
            EpochConfig(stride_seconds=0).validate()

    def test_epoch_to_dict_omits_frames_by_default(self):
        epoch = EpochBuilder(EpochConfig())._build_epoch(
            0,
            1000.0,
            (frame_at(1000.0),),
        )

        payload = epoch.to_dict()

        self.assertNotIn("frames", payload)
        self.assertEqual(payload["frame_count"], 1)


class TestEpochStepSeconds(unittest.TestCase):
    def test_first_epoch_counts_one_stride(self):
        self.assertEqual(epoch_step_seconds(1000.0, None, 10.0), 10.0)
        self.assertEqual(epoch_step_seconds(1000.0, None, 30.0), 30.0)

    def test_later_epochs_count_the_time_since_the_previous_start(self):
        self.assertEqual(epoch_step_seconds(1010.0, 1000.0, 10.0), 10.0)
        self.assertEqual(epoch_step_seconds(1040.0, 1010.0, 10.0), 30.0)

    def test_float_error_in_the_starts_is_rounded_away(self):
        self.assertEqual(epoch_step_seconds(30.0 + 0.3, 0.1 + 0.2, 30.0), 30.0)
        self.assertEqual(epoch_step_seconds(1_700_000_030.0000002, 1_700_000_000.0, 30.0), 30.0)

    def test_start_times_must_increase(self):
        with self.assertRaises(ValueError):
            epoch_step_seconds(1000.0, 1000.0, 30.0)
        with self.assertRaises(ValueError):
            epoch_step_seconds(990.0, 1000.0, 30.0)

    def test_stride_must_be_positive(self):
        with self.assertRaises(ValueError):
            epoch_step_seconds(1000.0, None, 0.0)


if __name__ == "__main__":
    unittest.main()
