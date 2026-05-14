import asyncio
import datetime as dt
import subprocess
import unittest
from unittest.mock import patch

from muse_realtime_decoder import DecodedData
from muse_tmr.data.sample_types import EEGSample, MuseFrame
from muse_tmr.sources.amused_source import AmusedSource
from muse_tmr.sources.base_source import BaseMuseSource, MuseDeviceInfo, MuseSourceMetadata


class FakeMuseSource(BaseMuseSource):
    def __init__(self):
        self.connected = False
        self.stopped = False

    async def discover(self):
        return [MuseDeviceInfo(name="Muse Test", address="test-address", rssi=-40)]

    async def connect(self, device=None):
        self.connected = True
        return MuseSourceMetadata(
            source_name="fake",
            device_name="Muse Test",
            device_id="test-address",
            capabilities={"eeg": True},
        )

    async def stream(self):
        yield MuseFrame(
            timestamp=1.0,
            eeg=EEGSample(timestamp=1.0, channels_uv={"TP9": [0.1]}),
            source="fake",
            raw_packet=b"\x01",
        )

    async def stop(self):
        self.stopped = True


class FakeStreamClient:
    def __init__(self, **kwargs):
        from muse_realtime_decoder import MuseRealtimeDecoder

        self.decoder = MuseRealtimeDecoder()
        self.packet_callback = None

    def on_packet(self, callback):
        self.packet_callback = callback

    async def connect_and_stream(self, address, duration_seconds=30, preset="p1034"):
        raw = b"\x11\x22"
        if self.packet_callback:
            self.packet_callback(raw)
        decoded = DecodedData(
            timestamp=dt.datetime.fromtimestamp(3.0),
            packet_type="EEG",
            eeg={"TP9": [0.25]},
            raw_bytes=raw,
        )
        for callback in self.decoder.callbacks["any"]:
            callback(decoded)
        await asyncio.sleep(0)
        return True


class TestSources(unittest.IsolatedAsyncioTestCase):
    async def test_fake_source_implements_contract(self):
        source = FakeMuseSource()

        devices = await source.discover()
        metadata = await source.connect(devices[0])
        frames = [frame async for frame in source.stream()]
        await source.stop()

        self.assertEqual(metadata.source_name, "fake")
        self.assertEqual(frames[0].modalities(), ("eeg",))
        self.assertTrue(source.stopped)

    async def test_amused_source_converts_callbacks_to_frames(self):
        source = AmusedSource(
            address="test-address",
            stream_client_factory=FakeStreamClient,
            duration_seconds=1,
            verbose=False,
        )

        metadata = await source.connect()
        frames = [frame async for frame in source.stream()]
        await source.stop()

        self.assertEqual(metadata.source_name, "amused")
        self.assertEqual(source.packet_count, 1)
        self.assertEqual(source.frame_count, 1)
        self.assertEqual(frames[0].eeg.channels_uv["TP9"], (0.25,))
        self.assertEqual(frames[0].raw_packet, b"\x11\x22")

    async def test_amused_discover_reports_corebluetooth_child_crash(self):
        completed = subprocess.CompletedProcess(
            args=["python", "-c", "..."],
            returncode=137,
            stdout="",
            stderr="Fatal Python error: Aborted\n",
        )
        source = AmusedSource(verbose=False)

        with patch("muse_tmr.sources.amused_source.sys.platform", "darwin"), patch(
            "muse_tmr.sources.amused_source.subprocess.run",
            return_value=completed,
        ):
            with self.assertRaisesRegex(RuntimeError, "Muse BLE discovery crashed"):
                await source.discover()


if __name__ == "__main__":
    unittest.main()
