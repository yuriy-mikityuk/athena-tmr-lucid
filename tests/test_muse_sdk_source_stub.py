import unittest
from pathlib import Path

from muse_tmr.sources.base_source import BaseMuseSource
from muse_tmr.sources.muse_sdk_source_stub import (
    MuseSdkSourceConfig,
    MuseSdkSourceStub,
    MuseSdkUnavailableError,
)


class TestMuseSdkSourceStub(unittest.IsolatedAsyncioTestCase):
    async def test_stub_imports_without_sdk_and_implements_source_contract(self):
        source = MuseSdkSourceStub(MuseSdkSourceConfig(sdk_path=Path("~/local-muse-sdk")))

        self.assertIsInstance(source, BaseMuseSource)
        self.assertEqual(source.source_name, "muse-sdk")
        self.assertEqual(source.strategy, "optional-proprietary-sdk-stub")

    async def test_stub_metadata_template_documents_expected_capabilities(self):
        source = MuseSdkSourceStub()

        metadata = source.metadata_template()

        self.assertEqual(metadata.source_name, "muse-sdk")
        self.assertTrue(metadata.capabilities["eeg"])
        self.assertTrue(metadata.capabilities["imu"])
        self.assertFalse(metadata.capabilities["raw_packets"])
        self.assertEqual(metadata.metadata["policy"], "docs/sdk_policy.md")

    async def test_runtime_methods_fail_with_policy_message(self):
        source = MuseSdkSourceStub()

        with self.assertRaises(MuseSdkUnavailableError) as ctx:
            await source.connect()

        message = str(ctx.exception)
        self.assertIn("optional and local-only", message)
        self.assertIn("scripts/check_forbidden_files.py", message)

    async def test_stop_is_safe_without_sdk(self):
        source = MuseSdkSourceStub()

        await source.stop()

        self.assertTrue(source.stopped)


if __name__ == "__main__":
    unittest.main()
