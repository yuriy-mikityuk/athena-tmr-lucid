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

from typing import Optional, Tuple

# Presets that stream EEG (+ IMU) only, with the optics/PPG LED stack powered
# off. Everything else drives the full 8-channel optics payload, from which both
# PPG heart rate and fNIRS are derived (they are not separable by preset).
NO_OPTICS_PRESETS = frozenset({"p21"})

# Recalibrated (enter, exit) REM-gate thresholds by preset. The heuristic
# detector runs hot (p_rem pinned high in NREM), so the live gate over-fires at
# the historical 0.70/0.45. Raising EXIT is the dominant lever: NREM p_rem rarely
# drops below ~0.6, so a low exit never closes the gate.
#
#   - p21 (EEG-only): VALIDATED against a GSSC reference on one full night
#     (overnight_20260707, n=1). 0.90/0.85 cuts gate-open from ~75% to ~36% of
#     the night while holding REM recall ~0.80.
#   - Optics presets: PROVISIONAL. The only p1034 recording is a 0-REM nap, so
#     p1034 REM *recall* at these thresholds is UNVERIFIED (false-alarm collapse
#     only). 0.80/0.70 is the recall-protective (lower-enter) choice on purpose;
#     re-grid once a REM-bearing optics night is recorded.
_PRESET_GATE_THRESHOLDS = {
    "p21": (0.90, 0.85),
}
_DEFAULT_OPTICS_GATE_THRESHOLDS = (0.80, 0.70)


def preset_provides_optics(preset: Optional[str]) -> bool:
    """Whether ``preset`` streams the optics/PPG stack.

    Unknown or empty presets conservatively return ``True`` (assume optics is
    present), so the REM gate keeps its cardiac-coverage confidence cap unless we
    positively know the preset is EEG-only.
    """
    if not preset:
        return True
    return preset.strip().lower() not in NO_OPTICS_PRESETS


def preset_gate_thresholds(preset: Optional[str]) -> Tuple[float, float]:
    """Default ``(enter, exit)`` REM-gate thresholds for ``preset``.

    Unknown/None or any optics preset returns the conservative, recall-protective
    provisional point; only p21 (EEG-only) is validated against a reference.
    """
    if not preset:
        return _DEFAULT_OPTICS_GATE_THRESHOLDS
    return _PRESET_GATE_THRESHOLDS.get(preset.strip().lower(), _DEFAULT_OPTICS_GATE_THRESHOLDS)
