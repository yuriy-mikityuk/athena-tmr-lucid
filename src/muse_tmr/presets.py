"""Muse preset capability helpers.

Single source of truth for what a device preset actually streams. The REM gate
uses this to decide whether a missing cardiac (PPG/HR) signal reflects a sensor
that is *off by design* (EEG-only presets) versus one that is *expected but
dropped out* -- only the latter should lower REM confidence.

Note: this is preset-derived, not source-derived. Sources advertise a static
capability map (e.g. amused reports ``heart_rate: True``) regardless of the
preset in use, so ``MuseSourceMetadata.capabilities`` cannot tell you that a p21
night carries no optics. The preset is the authoritative signal.
"""

from __future__ import annotations

from typing import Optional

# Presets that stream EEG (+ IMU) only, with the optics/PPG LED stack powered
# off. Everything else drives the full 8-channel optics payload, from which both
# PPG heart rate and fNIRS are derived (they are not separable by preset).
NO_OPTICS_PRESETS = frozenset({"p21"})


def preset_provides_optics(preset: Optional[str]) -> bool:
    """Whether ``preset`` streams the optics/PPG stack.

    Unknown or empty presets conservatively return ``True`` (assume optics is
    present), so the REM gate keeps its cardiac-coverage confidence cap unless we
    positively know the preset is EEG-only.
    """
    if not preset:
        return True
    return preset.strip().lower() not in NO_OPTICS_PRESETS
