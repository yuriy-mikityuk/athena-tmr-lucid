import unittest
import time
from types import SimpleNamespace

from muse_tmr.sources.brainflow_source import BrainFlowSource, BrainFlowSourceConfig


class FakeBrainFlowBoard:
    def __init__(self, data_by_preset, *, prepare_delay_seconds=0.0):
        self.data_by_preset = {key: list(value) for key, value in data_by_preset.items()}
        self.prepare_delay_seconds = prepare_delay_seconds
        self.prepared = False
        self.started = False
        self.stopped = False
        self.released = False

    def prepare_session(self):
        if self.prepare_delay_seconds:
            time.sleep(self.prepare_delay_seconds)
        self.prepared = True

    def start_stream(self, buffer_size=450000, streamer_params=""):
        self.started = True
        self.buffer_size = buffer_size
        self.streamer_params = streamer_params

    def get_board_data(self, max_samples, preset):
        batches = self.data_by_preset.get(preset, [])
        if not batches:
            return []
        return batches.pop(0)

    def stop_stream(self):
        self.stopped = True

    def release_session(self):
        self.released = True


class FakeBrainFlowBackend:
    name = "fake-brainflow"
    DEFAULT_PRESET = 0
    AUXILIARY_PRESET = 1
    ANCILLARY_PRESET = 2

    def __init__(self, board):
        self.board = board
        self.params = None

    def board_id_value(self, name):
        self.board_name = name
        return 9001

    def preset_value(self, name):
        return getattr(self, name)

    def input_params(self):
        self.params = SimpleNamespace()
        return self.params

    def board_shim(self, board_id, params):
        self.board_id = board_id
        self.params = params
        return self.board

    def eeg_channels(self, board_id, preset):
        return (1, 2, 3, 4)

    def eeg_names(self, board_id, preset):
        return ("TP9", "AF7", "AF8", "TP10")

    def other_channels(self, board_id, preset):
        return (5,)

    def accel_channels(self, board_id, preset):
        return (1, 2, 3)

    def gyro_channels(self, board_id, preset):
        return (4, 5, 6)

    def optical_channels(self, board_id, preset):
        return (1, 2)

    def battery_channel(self, board_id, preset):
        return 3

    def timestamp_channel(self, board_id, preset):
        return 0


class TestBrainFlowSource(unittest.IsolatedAsyncioTestCase):
    async def test_import_and_instantiation_do_not_require_brainflow_dependency(self):
        source = BrainFlowSource()

        self.assertEqual(source.source_name, "brainflow")
        self.assertEqual(source.strategy, "optional-brainflow")

    async def test_discover_returns_configured_brainflow_pseudo_device(self):
        backend = FakeBrainFlowBackend(FakeBrainFlowBoard({}))
        source = BrainFlowSource(
            BrainFlowSourceConfig(address="AA:BB", preset="p1041"),
            brainflow_backend=backend,
        )

        devices = await source.discover()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].name, "BrainFlow Muse S Athena (MUSE_S_ATHENA_BOARD)")
        self.assertEqual(devices[0].address, "AA:BB")
        self.assertEqual(devices[0].metadata["source"], "brainflow")
        self.assertEqual(devices[0].metadata["preset"], "p1041")

    async def test_connect_and_stream_maps_brainflow_batches_to_muse_frames(self):
        board = FakeBrainFlowBoard(
            {
                0: [
                    [
                        [1000.0, 1000.1],
                        [1.0, 2.0],
                        [3.0, 4.0],
                        [5.0, 6.0],
                        [7.0, 8.0],
                        [9.0, 10.0],
                    ]
                ],
                1: [
                    [
                        [1001.0, 1001.1],
                        [0.1, 0.2],
                        [0.3, 0.4],
                        [0.5, 0.6],
                        [1.1, 1.2],
                        [1.3, 1.4],
                        [1.5, 1.6],
                    ]
                ],
                2: [
                    [
                        [1002.0, 1002.1],
                        [11.0, 12.0],
                        [13.0, 14.0],
                        [88.0, 89.0],
                    ]
                ],
            }
        )
        backend = FakeBrainFlowBackend(board)
        source = BrainFlowSource(
            BrainFlowSourceConfig(
                address="AA:BB",
                serial_number="Muse-Test",
                duration_seconds=0.0,
                max_chunk_samples=2,
                session_cooldown_seconds=0.0,
            ),
            brainflow_backend=backend,
        )

        metadata = await source.connect()
        stream = source.stream().__aiter__()
        eeg_frame = await stream.__anext__()
        imu_frame = await stream.__anext__()
        ppg_frame = await stream.__anext__()
        await source.stop()

        self.assertEqual(metadata.source_name, "brainflow")
        self.assertEqual(metadata.device_id, "AA:BB")
        self.assertEqual(metadata.metadata["preset"], "p1041")
        self.assertEqual(backend.params.mac_address, "AA:BB")
        self.assertEqual(backend.params.serial_number, "Muse-Test")
        self.assertEqual(backend.params.timeout, 20)
        self.assertEqual(backend.params.other_info, "preset=p1041;low_latency=true")

        self.assertEqual(eeg_frame.timestamp, 1000.1)
        self.assertEqual(eeg_frame.source, "brainflow")
        self.assertEqual(eeg_frame.eeg.channels_uv["TP9"], (1.0, 2.0))
        self.assertEqual(eeg_frame.eeg.channels_uv["TP10"], (7.0, 8.0))
        self.assertEqual(eeg_frame.eeg.channels_uv["OTHER_0"], (9.0, 10.0))

        self.assertEqual(imu_frame.imu.accelerometer_g[1]["z"], 0.6)
        self.assertEqual(imu_frame.imu.gyroscope_dps[1]["z"], 1.6)

        self.assertEqual(ppg_frame.ppg.channels["OPTICAL_0"], (11.0, 12.0))
        self.assertEqual(ppg_frame.ppg.channels["OPTICAL_1"], (13.0, 14.0))
        self.assertEqual(ppg_frame.battery.percent, 89.0)

        self.assertTrue(board.prepared)
        self.assertTrue(board.started)
        self.assertTrue(board.stopped)
        self.assertTrue(board.released)

    async def test_connect_timeout_fails_without_hanging_event_loop(self):
        board = FakeBrainFlowBoard({}, prepare_delay_seconds=0.2)
        backend = FakeBrainFlowBackend(board)
        source = BrainFlowSource(
            BrainFlowSourceConfig(
                connect_timeout_seconds=0.01,
                session_cooldown_seconds=0.0,
            ),
            brainflow_backend=backend,
        )

        with self.assertRaisesRegex(RuntimeError, "prepare_session timed out"):
            await source.connect()

        self.assertEqual(source.disconnect_reason, "connect_timeout")

    async def test_stop_applies_configured_session_cooldown(self):
        board = FakeBrainFlowBoard({})
        backend = FakeBrainFlowBackend(board)
        source = BrainFlowSource(
            BrainFlowSourceConfig(
                session_cooldown_seconds=0.01,
            ),
            brainflow_backend=backend,
        )
        await source.connect()

        started = time.monotonic()
        await source.stop()

        self.assertGreaterEqual(time.monotonic() - started, 0.01)


if __name__ == "__main__":
    unittest.main()
