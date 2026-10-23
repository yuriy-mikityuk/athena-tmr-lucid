"""First-cue latency of the REM gate at strides of 30, 10 and 5 s (#225, #167).

Synthetic input, not sleep. A scripted frame stream as on p21: EEG and a still IMU, no
optics. NREM-like EEG (a 40 µV 1.5 Hz wave with a little 6 Hz) turns REM-like (12 µV
6 Hz theta, 1 µV alpha, eye-movement deflections of opposite sign on AF7 and AF8) at a
known onset. The stream goes through EpochBuilder, the heuristic detector, the p21 gate
(0.90/0.85, 60 s stable, 120 s cooldown), the arousal guard and the scheduler, in Pilot 3
and in Pilot 4 with mock audio. The latency is from the REM onset to the end of the epoch
whose decision first opened the gate or first played a cue.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

import numpy as np

from muse_tmr.audio import MockAudioBackend, VolumeCalibration
from muse_tmr.data.sample_types import EEGSample, IMUSample, MuseFrame
from muse_tmr.features import EpochBuilder, EpochConfig
from muse_tmr.models import RemGateConfig
from muse_tmr.presets import preset_gate_thresholds, preset_provides_optics
from muse_tmr.protocol import TmrSchedulerConfig
from muse_tmr.validation import (
    Pilot4CueingConfig,
    run_pilot4_cueing_night,
    simulate_cue_plan_from_epochs,
)
from tests.rem_event_synthetic import rem_deflection_train
from tests.test_pilot3_replay_simulation import protocol_fixture
from tests.test_pilot4_cueing import FakeMuseSource

EEG_RATE_HZ = 256
IMU_RATE_HZ = 52
EEG_SAMPLES_PER_FRAME = 12
IMU_SAMPLES_PER_FRAME = 3
START_TIME = 1_700_000_000.0
NREM_SECONDS = 120.0
REM_SECONDS = 180.0
STRIDES = (30.0, 10.0, 5.0)
# REM onsets this far past a 30 s epoch boundary.
ONSET_PHASES = (0.0, 5.0, 10.0, 15.0, 20.0, 25.0)

# Seconds from REM onset to the first gate opening, which here is also the first play,
# per onset phase. At 30 s the window that holds only REM counts 30 s towards the 60 s,
# at 10 or 5 s only its stride, and a window that is still partly NREM is not REM-like.
EXPECTED_LATENCY = {
    30.0: (60.0, 85.0, 80.0, 75.0, 70.0, 65.0),
    10.0: (80.0, 85.0, 80.0, 85.0, 80.0, 85.0),
    5.0: (85.0, 85.0, 85.0, 85.0, 85.0, 85.0),
}


def scripted_channels(nrem_seconds, rem_seconds):
    n = int(round((nrem_seconds + rem_seconds) * EEG_RATE_HZ))
    t = np.arange(n) / EEG_RATE_HZ
    rem = t >= nrem_seconds
    nrem_wave = 40.0 * np.sin(2 * np.pi * 1.5 * t) + 4.0 * np.sin(2 * np.pi * 6.0 * t)
    rem_wave = 12.0 * np.sin(2 * np.pi * 6.0 * t) + 1.0 * np.sin(2 * np.pi * 10.0 * t)
    background = np.where(rem, rem_wave, nrem_wave)
    eye = np.zeros(n)
    train = rem_deflection_train()
    start = int(round(nrem_seconds * EEG_RATE_HZ))
    while start < n:
        piece = train[: n - start]
        eye[start:start + piece.size] = piece
        start += train.size
    return {
        "TP9": background,
        "AF7": background + eye,
        "AF8": background - eye,
        "TP10": background,
    }


def scripted_frames(nrem_seconds, rem_seconds):
    """EEG frames of 12 samples and IMU frames of 3, in time order."""
    channels = scripted_channels(nrem_seconds, rem_seconds)
    frames = []
    total = channels["AF7"].size
    for offset in range(0, total - EEG_SAMPLES_PER_FRAME + 1, EEG_SAMPLES_PER_FRAME):
        timestamp = START_TIME + offset / EEG_RATE_HZ
        eeg = {
            name: tuple(values[offset:offset + EEG_SAMPLES_PER_FRAME].tolist())
            for name, values in channels.items()
        }
        frames.append(
            MuseFrame(timestamp=timestamp, eeg=EEGSample(timestamp, eeg, source="synthetic"), source="synthetic")
        )
    still_accel = [{"x": 0.0, "y": 0.0, "z": 1.0}] * IMU_SAMPLES_PER_FRAME
    still_gyro = [{"x": 0.0, "y": 0.0, "z": 0.0}] * IMU_SAMPLES_PER_FRAME
    imu_total = int(round((nrem_seconds + rem_seconds) * IMU_RATE_HZ))
    for offset in range(0, imu_total - IMU_SAMPLES_PER_FRAME + 1, IMU_SAMPLES_PER_FRAME):
        timestamp = START_TIME + offset / IMU_RATE_HZ
        frames.append(
            MuseFrame(
                timestamp=timestamp,
                imu=IMUSample(
                    timestamp,
                    accelerometer_g=still_accel,
                    gyroscope_dps=still_gyro,
                    source="synthetic",
                ),
                source="synthetic",
            )
        )
    frames.sort(key=lambda frame: frame.timestamp)
    return frames


def p21_gate_config():
    enter, exit_ = preset_gate_thresholds("p21")
    return RemGateConfig(
        enter_threshold=enter,
        exit_threshold=exit_,
        optics_capable=preset_provides_optics("p21"),
    )


async def _aiter(frames):
    for frame in frames:
        yield frame


async def _build_epochs(frames, stride_seconds):
    builder = EpochBuilder(EpochConfig(epoch_seconds=30.0, stride_seconds=stride_seconds))
    return [epoch async for epoch in builder.build(_aiter(frames))]


def pilot3_report(epochs, stride_seconds):
    catalog, session, assignment, cue_library = protocol_fixture()
    return simulate_cue_plan_from_epochs(
        epochs,
        catalog=catalog,
        session=session,
        assignment=assignment,
        cue_library=cue_library,
        gate_config=p21_gate_config(),
        scheduler_config=TmrSchedulerConfig(enable_tlr_block=False),
        stride_seconds=stride_seconds,
    )


def latency_table():
    """{stride: [(gate-open latency, play latency) per onset phase]}."""
    table = {stride: [] for stride in STRIDES}
    for phase in ONSET_PHASES:
        onset = NREM_SECONDS + phase
        frames = scripted_frames(onset, REM_SECONDS)
        for stride in STRIDES:
            epochs = asyncio.run(_build_epochs(frames, stride))
            metrics = pilot3_report(epochs, stride).metrics
            table[stride].append(
                (
                    metrics["first_gate_open_seconds"] - onset,
                    metrics["first_play_seconds"] - onset,
                )
            )
    return table


def format_latency_table(table):
    """A Markdown table: seconds from REM onset to the first gate opening / first play,
    one column per onset phase past a 30 s epoch boundary."""
    lines = [
        "First-cue latency (s) after REM onset, synthetic input, not sleep. "
        "p21 gate 0.90/0.85, 60 s stable; first gate opening / first play.",
        "",
        "| Stride | " + " | ".join(f"onset +{phase:.0f} s" for phase in ONSET_PHASES) + " |",
        "|---|" + "---|" * len(ONSET_PHASES),
    ]
    for stride in STRIDES:
        cells = " | ".join(f"{opened:.0f} / {played:.0f}" for opened, played in table[stride])
        lines.append(f"| {stride:.0f} s | {cells} |")
    return "\n".join(lines)


class TestFirstCueLatency(unittest.TestCase):
    def test_latency_table_for_strides_30_10_5(self):
        table = latency_table()
        print("\n" + format_latency_table(table))

        for stride in STRIDES:
            with self.subTest(stride=stride):
                self.assertEqual(
                    tuple(opened for opened, _ in table[stride]), EXPECTED_LATENCY[stride]
                )
                self.assertEqual(
                    tuple(played for _, played in table[stride]), EXPECTED_LATENCY[stride]
                )

    def test_nrem_and_rem_halves_are_what_the_gate_expects(self):
        frames = scripted_frames(NREM_SECONDS, REM_SECONDS)
        report = pilot3_report(asyncio.run(_build_epochs(frames, 30.0)), 30.0)
        probabilities = [result.prediction.probability for result in report.epoch_results]
        actions = {result.arousal_guard_decision.action for result in report.epoch_results}

        self.assertTrue(all(p < 0.85 for p in probabilities[:4]))
        self.assertTrue(all(p >= 0.90 for p in probabilities[4:10]))
        self.assertEqual(actions, {"allow"})
        self.assertEqual(report.metrics["uncued_puzzle_play_count"], 0)


class TestPilot4FirstCueLatency(unittest.IsolatedAsyncioTestCase):
    async def test_pilot4_summary_matches_pilot3(self):
        frames = scripted_frames(NREM_SECONDS, REM_SECONDS)
        catalog, session, assignment, cue_library = protocol_fixture()
        for stride in STRIDES:
            with self.subTest(stride=stride), tempfile.TemporaryDirectory() as tmpdir:
                summary = await run_pilot4_cueing_night(
                    FakeMuseSource(frames),
                    config=Pilot4CueingConfig(
                        output_dir=Path(tmpdir),
                        duration_seconds=600.0,
                        allow_short=True,
                        audio_backend_name="mock",
                        epoch_config=EpochConfig(epoch_seconds=30.0, stride_seconds=stride),
                        gate_config=p21_gate_config(),
                    ),
                    catalog=catalog,
                    session=session,
                    assignment=assignment,
                    cue_library=cue_library,
                    calibration=VolumeCalibration("Sleep Headphones", 0.01, 0.02, 0.04),
                    backend=MockAudioBackend(),
                )
                expected = pilot3_report(await _build_epochs(frames, stride), stride).metrics

                self.assertEqual(summary.stride_seconds, stride)
                self.assertEqual(summary.first_gate_open_seconds, expected["first_gate_open_seconds"])
                self.assertEqual(summary.first_play_seconds, expected["first_play_seconds"])
                self.assertEqual(
                    summary.first_gate_open_seconds - NREM_SECONDS, EXPECTED_LATENCY[stride][0]
                )
                self.assertEqual(summary.uncued_puzzle_play_count, 0)
                self.assertTrue(summary.passed)


if __name__ == "__main__":
    unittest.main()
