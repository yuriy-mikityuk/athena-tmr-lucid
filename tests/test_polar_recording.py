import asyncio
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from muse_tmr.data.polar_recorder import PolarRecorder, PolarRecordingConfig, decode_polar_session
from muse_tmr.data.polar_session import fit_clock_mapping, load_polar_session
from muse_tmr.data.recorder import CompanionProcess, OvernightRecorder, RecordingConfig
from muse_tmr.features.cardio_resp_features import extract_cardio_resp_features
from muse_tmr.sources.polar_h10 import (
    HEART_RATE_MEASUREMENT,
    PMD_CONTROL_POINT,
    PMD_DATA,
    PmdStreamSettings,
    start_command,
)

from muse_tmr.data.sample_types import EEGSample, MuseFrame
from tests.polar_synthetic import acc_frame_delta, ecg_frame, hr_measurement, write_raw_session
from tests.test_recorder import RecordingFakeSource


class ClockMappingTest(unittest.TestCase):
    def test_offset_drift_and_positive_delays_recovered_within_10_ms(self):
        rng = np.random.default_rng(11)
        true_host = np.sort(rng.uniform(0, 8 * 3600, 20000))
        drift = 50e-6
        sensor = 599_616_000.0 + true_host * (1 + drift)
        received = 5000.0 + true_host + rng.exponential(0.03, true_host.size)
        mapping = fit_clock_mapping(sensor, received)
        error_ms = np.abs(mapping.to_host(sensor) - (5000.0 + true_host)) * 1000.0
        self.assertLess(error_ms.max(), 10.0)
        self.assertAlmostEqual(mapping.drift * 1e6, -50.0, delta=1.0)
        self.assertGreater(mapping.delay_p95_ms, mapping.delay_median_ms)


class LoadPolarSessionTest(unittest.TestCase):
    def test_decode_align_and_window_features(self):
        rng = np.random.default_rng(4)
        with tempfile.TemporaryDirectory() as tmp:
            truth = write_raw_session(tmp, 240, rng, breaths_per_min=6.0)
            decoded = decode_polar_session(Path(tmp))
            self.assertEqual(decoded["errors"], {})
            self.assertGreater(decoded["counts"]["acc_samples"], 0)

            session = load_polar_session(Path(tmp))
            beats = truth["beats_wall"]
            peaks = session.r_peaks["time"].to_numpy()
            errors = np.array([peaks[np.argmin(np.abs(peaks - beat))] - beat for beat in beats[1:-1]])
            self.assertLess(np.abs(errors).max() * 1000.0, 10.0)
            aligned = session.rr["aligned_to"] == "ecg_r_peak"
            self.assertGreater(aligned.mean(), 0.95)
            self.assertLess(session.alignment["rr"]["rr_agreement_ms"], 2.0)
            self.assertEqual(set(session.acc.columns), {"time", "x", "y", "z"})

            features = extract_cardio_resp_features(session, truth["wall0"] + 10, truth["wall0"] + 230)
            self.assertAlmostEqual(features["resp_rate_bpm"], 6.0, delta=0.5)
            self.assertAlmostEqual(features["edr_rate_bpm"], 6.0, delta=0.5)
            self.assertEqual(features["hf_band_valid"], 0.0)
            self.assertTrue(math.isfinite(features["rmssd_ms"]))

    def test_without_ecg_rr_keeps_receive_time_estimate(self):
        rng = np.random.default_rng(5)
        with tempfile.TemporaryDirectory() as tmp:
            write_raw_session(tmp, 90, rng, with_ecg=False)
            session = load_polar_session(Path(tmp))
            self.assertTrue((session.rr["aligned_to"] == "host_receive").all())
            self.assertIn("note", session.alignment["rr"])


class MockPolarClient:
    """Streams HR/ECG/ACC notifications; can drop the link after a number of frames."""

    def __init__(self, frames_before_disconnect=(None,)):
        self.plan = list(frames_before_disconnect)
        self.disconnected = asyncio.Event()
        self.stream_settings = {}
        self.connects = 0
        self.stop_calls = 0
        self._task = None
        self._sensor_ns = 700_000_000_000_000_000

    async def connect(self, on_payload):
        limit = self.plan[min(self.connects, len(self.plan) - 1)]
        self.connects += 1
        self.disconnected = asyncio.Event()
        factor = bytes([0x05, 0x01, 0x00, 0x00, 0x80, 0x3F])  # 1.0f
        on_payload("tx", PMD_CONTROL_POINT, start_command(0, {0: 130, 1: 14}))
        on_payload("rx", PMD_CONTROL_POINT, bytes([0xF0, 0x02, 0x00, 0x00, 0x00]) + factor)
        on_payload("tx", PMD_CONTROL_POINT, start_command(2, {0: 50, 1: 16, 2: 2}))
        on_payload("rx", PMD_CONTROL_POINT, bytes([0xF0, 0x02, 0x02, 0x00, 0x00]) + factor)
        self.stream_settings = {
            "ecg": PmdStreamSettings(130, 14, 1, 1.0),
            "acc": PmdStreamSettings(50, 16, 3, 1.0, 2),
        }
        self._task = asyncio.ensure_future(self._stream(on_payload, limit))
        return {"device_name": "Polar H10 TEST", "model": "H10", "firmware": "x"}

    async def _stream(self, on_payload, limit):
        sent = 0
        while limit is None or sent < limit:
            self._sensor_ns += int(73 * 1e9 / 130)
            on_payload("rx", PMD_DATA, ecg_frame(self._sensor_ns, [100, 200, -50] * 24 + [7]))
            on_payload("rx", PMD_DATA, acc_frame_delta(self._sensor_ns, [(1, 2, 1000 + i) for i in range(36)]))
            on_payload("rx", HEART_RATE_MEASUREMENT, hr_measurement(60, (1000.0,), contact=True))
            sent += 1
            await asyncio.sleep(0.01)
        self.disconnected.set()

    async def stop(self):
        self.stop_calls += 1
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


class PolarRecorderTest(unittest.IsolatedAsyncioTestCase):
    def recorder(self, tmp, seconds):
        return PolarRecorder(
            PolarRecordingConfig(output_dir=Path(tmp), duration_seconds=seconds, backoff_base_seconds=0.01)
        )

    async def test_disconnect_mid_session_reconnects_and_files_are_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = MockPolarClient(frames_before_disconnect=(5, None))
            summary = await self.recorder(tmp, 0.6).record(client)

            self.assertEqual(summary["stop_reason"], "duration_complete")
            self.assertEqual(summary["reconnects"], 1)
            self.assertEqual(client.connects, 2)
            self.assertGreaterEqual(client.stop_calls, 2)
            polar = Path(tmp) / "polar"
            for name in ("raw_notifications.jsonl", "events.jsonl", "clock_anchors.jsonl", "metadata.json",
                         "summary.json", "hr_rr.jsonl", "ecg.jsonl", "acc.jsonl"):
                self.assertTrue((polar / name).exists(), name)
            events = [json.loads(line)["event"] for line in (polar / "events.jsonl").read_text().splitlines()]
            self.assertEqual(events.count("connected"), 2)
            self.assertIn("disconnected", events)
            self.assertEqual(events[-1], "recording_stopped")
            anchors = (polar / "clock_anchors.jsonl").read_text().splitlines()
            self.assertEqual([json.loads(line)["label"] for line in (anchors[0], anchors[-1])], ["start", "stop"])
            metadata = json.loads((polar / "metadata.json").read_text())
            self.assertEqual(metadata["streams"]["acc"]["sample_rate"], 50)
            self.assertNotIn("address", json.dumps(metadata))
            decode = summary["decode"]
            self.assertEqual(decode["errors"], {})
            self.assertEqual(decode["counts"]["ecg_frames"], decode["counts"]["acc_frames"])
            self.assertEqual(decode["counts"]["ecg_samples"], 73 * decode["counts"]["ecg_frames"])

            # decode-polar rebuilds the same files from the raw log alone.
            before = (polar / "acc.jsonl").read_text()
            (polar / "acc.jsonl").unlink()
            decode_polar_session(Path(tmp))
            self.assertEqual((polar / "acc.jsonl").read_text(), before)

    async def test_cancel_is_a_clean_user_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = MockPolarClient()
            task = asyncio.create_task(self.recorder(tmp, 60).record(client))
            await asyncio.sleep(0.2)
            task.cancel()
            summary = await task
            self.assertEqual(summary["stop_reason"], "user_stopped")
            self.assertGreaterEqual(client.stop_calls, 1)  # PMD streams always stopped

    async def test_failed_connects_end_at_attempt_limit(self):
        class Unreachable(MockPolarClient):
            async def connect(self, on_payload):
                raise RuntimeError("Polar H10 not found")

        with tempfile.TemporaryDirectory() as tmp:
            recorder = PolarRecorder(
                PolarRecordingConfig(
                    output_dir=Path(tmp), duration_seconds=5, max_reconnect_attempts=2, backoff_base_seconds=0.01
                )
            )
            summary = await recorder.record(Unreachable())
            self.assertEqual(summary["stop_reason"], "max_reconnect_attempts")
            self.assertEqual(summary["failed_connects"], 3)


class SlowFakeSource(RecordingFakeSource):
    async def stream(self):
        timestamp = 1.0
        while True:
            yield MuseFrame(timestamp=timestamp, eeg=EEGSample(timestamp=timestamp, channels_uv={"TP9": [0.1]}), source="fake")
            timestamp += 0.05
            await asyncio.sleep(0.05)


class CompanionTest(unittest.IsolatedAsyncioTestCase):
    async def test_crashing_companion_never_affects_the_muse_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            crashing = CompanionProcess(
                "polar", [sys.executable, "-c", "import sys; sys.exit(3)"], Path(tmp) / "polar" / "record-polar.log"
            )
            missing = CompanionProcess("broken", ["/nonexistent/binary"], Path(tmp) / "broken.log")
            recorder = OvernightRecorder(
                RecordingConfig(output_dir=Path(tmp), duration_seconds=2.5, allow_short=True),
                companions=[crashing, missing],
            )
            summary = await recorder.record(SlowFakeSource())

            self.assertEqual(summary.stop_reason, "duration_complete")
            events = [json.loads(line) for line in Path(summary.events_path).read_text().splitlines()]
            names = [(item["event"], item["details"].get("companion")) for item in events]
            self.assertIn(("companion_started", "polar"), names)
            self.assertIn(("companion_start_failed", "broken"), names)
            exited = [item for item in events if item["event"] == "companion_exited"]
            self.assertEqual(exited[0]["details"]["returncode"], 3)

    async def test_long_running_companion_gets_sigint_after_the_muse_summary(self):
        script = "import signal, sys, time\nsignal.signal(signal.SIGINT, lambda *a: sys.exit(0))\ntime.sleep(60)\n"
        with tempfile.TemporaryDirectory() as tmp:
            sleeper = CompanionProcess("polar", [sys.executable, "-c", script], Path(tmp) / "polar.log")
            recorder = OvernightRecorder(
                RecordingConfig(output_dir=Path(tmp), duration_seconds=1.5, allow_short=True), companions=[sleeper]
            )
            summary = await recorder.record(SlowFakeSource())
            self.assertEqual(summary.stop_reason, "duration_complete")
            self.assertTrue(Path(summary.summary_path).exists())
            events = [json.loads(line) for line in Path(summary.events_path).read_text().splitlines()]
            stopped = [item for item in events if item["event"] == "companion_stopped"]
            self.assertEqual(stopped[0]["details"]["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
