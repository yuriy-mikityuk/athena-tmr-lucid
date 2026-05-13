"""Optional official Muse SDK adapter stub.

This module intentionally imports no SDK package, framework, header, or binary.
It exists only to reserve the source contract and to make SDK policy failures
explicit until a legally redistributable integration path is chosen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Mapping, Optional, Sequence

from muse_tmr.data.sample_types import MuseFrame
from muse_tmr.sources.base_source import BaseMuseSource, MuseDeviceInfo, MuseSourceMetadata

MUSE_SDK_SOURCE_NAME = "muse-sdk"
MUSE_SDK_POLICY_DOC = "docs/sdk_policy.md"


class MuseSdkUnavailableError(RuntimeError):
    """Raised when official Muse SDK access is requested from the stub."""


@dataclass(frozen=True)
class MuseSdkSourceConfig:
    """Configuration placeholder for a future local-only SDK adapter."""

    sdk_path: Optional[Path] = None
    device_name: str = "Muse SDK"
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sdk_path is not None:
            object.__setattr__(self, "sdk_path", self.sdk_path.expanduser())
        object.__setattr__(self, "device_name", self.device_name.strip() or "Muse SDK")
        object.__setattr__(
            self,
            "metadata",
            {str(key): str(value) for key, value in self.metadata.items()},
        )


class MuseSdkSourceStub(BaseMuseSource):
    """Non-functional official SDK source stub that preserves the source API."""

    source_name = MUSE_SDK_SOURCE_NAME
    strategy = "optional-proprietary-sdk-stub"

    def __init__(self, config: Optional[MuseSdkSourceConfig] = None) -> None:
        self.config = config or MuseSdkSourceConfig()
        self.stopped = False

    async def discover(self) -> Sequence[MuseDeviceInfo]:
        raise MuseSdkUnavailableError(self.policy_message("discover"))

    async def connect(self, device: Optional[MuseDeviceInfo] = None) -> MuseSourceMetadata:
        raise MuseSdkUnavailableError(self.policy_message("connect"))

    async def stream(self) -> AsyncIterator[MuseFrame]:
        raise MuseSdkUnavailableError(self.policy_message("stream"))
        if False:
            yield  # pragma: no cover

    async def stop(self) -> None:
        self.stopped = True

    def metadata_template(self) -> MuseSourceMetadata:
        """Return the metadata shape a future SDK adapter must preserve."""

        return MuseSourceMetadata(
            source_name=self.source_name,
            device_name=self.config.device_name,
            device_id="sdk-local-only",
            capabilities={
                "eeg": True,
                "imu": True,
                "ppg": True,
                "heart_rate": True,
                "battery": True,
                "raw_packets": False,
            },
            metadata={
                "strategy": self.strategy,
                "policy": MUSE_SDK_POLICY_DOC,
                **dict(self.config.metadata),
            },
        )

    def policy_message(self, operation: str) -> str:
        sdk_path = str(self.config.sdk_path) if self.config.sdk_path is not None else "<unset>"
        return (
            f"Official Muse SDK source cannot {operation} yet. SDK support must remain "
            f"optional and local-only; do not commit SDK binaries, headers, archives, "
            f"installers, docs, or copied SDK code. Configured sdk_path={sdk_path}. "
            f"See {MUSE_SDK_POLICY_DOC} and run scripts/check_forbidden_files.py."
        )
