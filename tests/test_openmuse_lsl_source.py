import unittest

from muse_tmr.sources.openmuse_lsl_source import OpenMuseLslConfig, OpenMuseLslSource


class FakeStreamInfo:
    def __init__(self, name, channel_count, stream_type="Muse", source_id=None):
        self._name = name
        self._channel_count = channel_count
        self._type = stream_type
        self._source_id = source_id or f"{name}-uid"

    def name(self):
        return self._name

    def channel_count(self):
        return self._channel_count

    def type(self):
        return self._type

    def source_id(self):
        return self._source_id


class FakeInlet:
    def __init__(self, samples):
        self.samples = list(samples)
        self.closed = False
        self.opened = False

    def open_stream(self, timeout=0.0):
        self.opened = True

    def pull_sample(self, timeout=0.0):
        if not self.samples:
            return None, None
        return self.samples.pop(0)

    def time_correction(self, timeout=0.0):
        return 0.0

    def close_stream(self):
        self.closed = True


class FakeLslBackend:
    name = "fake-lsl"

    def __init__(self, infos, inlets):
        self.infos = tuple(infos)
        self.inlets = dict(inlets)

    def resolve_streams(self, timeout_seconds):
        return self.infos

    def resolve_by_name(self, name, timeout_seconds):
        return tuple(info for info in self.infos if info.name() == name)

    def stream_inlet(self, info, *, max_buffer_seconds):
        return self.inlets[info.name()]

    def local_clock(self):
        return 10.0


class TestOpenMuseLslSource(unittest.IsolatedAsyncioTestCase):
    async def test_import_and_instantiation_do_not_require_lsl_dependency(self):
        source = OpenMuseLslSource()

        self.assertEqual(source.source_name, "openmuse")
        self.assertEqual(source.strategy, "optional-lsl")

    async def test_discover_lists_openmuse_streams(self):
        backend = FakeLslBackend(
            infos=(
                FakeStreamInfo("Muse_EEG", 4),
                FakeStreamInfo("Unrelated", 1),
            ),
            inlets={},
        )
        source = OpenMuseLslSource(lsl_backend=backend)

        devices = await source.discover()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].name, "Muse_EEG")
        self.assertEqual(devices[0].metadata["modality"], "eeg")

    async def test_connect_and_stream_yields_eeg_and_imu_frames(self):
        eeg_info = FakeStreamInfo("Muse_EEG", 4)
        imu_info = FakeStreamInfo("Muse_ACCGYRO", 6)
        eeg_inlet = FakeInlet([([1.0, 2.0, 3.0, 4.0], 12.0)])
        imu_inlet = FakeInlet([([0.1, 0.2, 0.3, 1.1, 1.2, 1.3], 13.0)])
        backend = FakeLslBackend(
            infos=(eeg_info, imu_info),
            inlets={"Muse_EEG": eeg_inlet, "Muse_ACCGYRO": imu_inlet},
        )
        source = OpenMuseLslSource(
            OpenMuseLslConfig(required_modalities=("eeg", "imu")),
            lsl_backend=backend,
        )

        metadata = await source.connect()
        stream = source.stream().__aiter__()
        eeg_frame = await stream.__anext__()
        imu_frame = await stream.__anext__()
        await source.stop()

        self.assertEqual(metadata.source_name, "openmuse")
        self.assertTrue(metadata.capabilities["eeg"])
        self.assertTrue(metadata.capabilities["imu"])
        self.assertFalse(metadata.capabilities["raw_packets"])
        self.assertGreater(eeg_frame.timestamp, 1_000_000_000)
        self.assertEqual(eeg_frame.source, "openmuse")
        self.assertEqual(eeg_frame.eeg.channels_uv["TP9"], (1.0,))
        self.assertEqual(eeg_frame.eeg.channels_uv["TP10"], (4.0,))
        self.assertEqual(imu_frame.imu.accelerometer_g[0]["x"], 0.1)
        self.assertEqual(imu_frame.imu.gyroscope_dps[0]["z"], 1.3)
        self.assertTrue(eeg_inlet.closed)
        self.assertTrue(imu_inlet.closed)

    async def test_missing_required_stream_fails_connect(self):
        backend = FakeLslBackend(
            infos=(FakeStreamInfo("Muse_EEG", 4),),
            inlets={"Muse_EEG": FakeInlet([])},
        )
        source = OpenMuseLslSource(
            OpenMuseLslConfig(required_modalities=("eeg", "imu")),
            lsl_backend=backend,
        )

        with self.assertRaises(RuntimeError):
            await source.connect()


if __name__ == "__main__":
    unittest.main()
