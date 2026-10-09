"""How big the ~64 Hz line is in a recording, to tell headband presets apart.

The optics stream runs at 63.92 Hz in EEG-sample terms on the first three p1034
sessions (counted from the packet counters), which is where the line sits. A
recording with the optics on (p1034) next to one without them (p21) shows
whether the optics put it there.
"""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

import numpy as np
from scipy.signal import detrend, welch

from muse_tmr.features.complexity_features import remove_lines

LINE_HZ = 64.0
SEARCH_HZ = 0.5
WINDOW_SECONDS = 10.0
# Line bin over the 58-62 / 66-70 Hz median in a 10 s spectrum. On p1034 it was
# 23-45 dB; plain EEG noise stays within a few dB.
PRESENT_DB = 10.0
CHANNELS = ("AF7", "AF8", "TP9", "TP10")


def line_levels(
    channels: Mapping[str, Sequence[float]],
    fs: float = 256.0,
    window_s: float = WINDOW_SECONDS,
) -> Dict[str, Dict[str, float]]:
    """Per channel, medians over 10 s windows: the fitted line amplitude in µV and
    the line's height over its neighbours in dB."""
    size = int(round(window_s * fs))
    levels: Dict[str, Dict[str, float]] = {}
    for channel, values in channels.items():
        x = np.asarray(values, dtype=float)
        x = x[np.isfinite(x)]
        amplitudes, heights = [], []
        for start in range(0, x.size - size + 1, size):
            segment = detrend(x[start : start + size])
            if float(np.std(segment)) <= 0:
                continue
            fitted = segment - remove_lines(segment, fs, (LINE_HZ,), SEARCH_HZ)
            amplitudes.append(float(np.std(fitted) * math.sqrt(2.0)))
            freqs, psd = welch(segment, fs=fs, nperseg=size)
            peak = psd[(freqs >= LINE_HZ - SEARCH_HZ) & (freqs <= LINE_HZ + SEARCH_HZ)].max()
            near = np.median(psd[((freqs >= 58.0) & (freqs < 62.0)) | ((freqs > 66.0) & (freqs <= 70.0))])
            if peak > 0 and near > 0:
                heights.append(10.0 * math.log10(peak / near))
        levels[channel] = {
            "amplitude_uv": float(np.median(amplitudes)) if amplitudes else math.nan,
            "height_db": float(np.median(heights)) if heights else math.nan,
            "windows": float(len(amplitudes)),
        }
    return levels


async def measure_recording(recording_dir: Path) -> Dict[str, Dict[str, float]]:
    from muse_tmr.data.replay import ReplayConfig, ReplaySession

    session = ReplaySession(ReplayConfig(input_path=Path(recording_dir), speed=0.0))
    await session.connect()
    channels: Dict[str, List[float]] = {}
    try:
        async for frame in session.stream():
            if frame.eeg is None:
                continue
            for channel, values in frame.eeg.channels_uv.items():
                channels.setdefault(channel, []).extend(values)
    finally:
        await session.stop()
    return line_levels({channel: channels[channel] for channel in CHANNELS if channel in channels})


def summarize(segments: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    """Segments carry index, preset, recording and channels (from line_levels).

    The verdict: "optics" when every p1034 segment has the line and no p21 one
    does, "not_optics" when a p21 segment has it, otherwise "unclear".
    """
    rows = []
    for segment in segments:
        heights = [_num(level.get("height_db")) for level in (segment.get("channels") or {}).values()]
        heights = [value for value in heights if math.isfinite(value)]
        median_height = float(np.median(heights)) if heights else math.nan
        rows.append({**segment, "median_height_db": median_height, "line_present": median_height >= PRESENT_DB})
    with_optics = [row for row in rows if row.get("preset") == "p1034" and math.isfinite(row["median_height_db"])]
    without = [row for row in rows if row.get("preset") == "p21" and math.isfinite(row["median_height_db"])]
    if without and any(row["line_present"] for row in without):
        verdict = "not_optics"
    elif with_optics and without and all(row["line_present"] for row in with_optics):
        verdict = "optics"
    else:
        verdict = "unclear"
    return {"segments": rows, "verdict": verdict, "present_db": PRESENT_DB}


VERDICT_TEXT = {
    "optics": "The line is there with the optics on (p1034) and gone without them (p21): the optics put it there.",
    "not_optics": "The line is there without the optics too (p21), so they are not (or not the only) source.",
    "unclear": "No clear answer: a segment is missing or the line was absent with the optics on too.",
}


def render_section(summary: Mapping[str, object]) -> str:
    rows = []
    for segment in summary.get("segments") or ():
        levels = segment.get("channels") or {}
        cells = []
        for channel in CHANNELS:
            level = levels.get(channel) or {}
            cells.append(f"{_fmt(level.get('amplitude_uv'), 1)} µV / {_fmt(level.get('height_db'), 0)} dB")
        rows.append(
            "<tr>"
            + f"<td>{int(segment.get('index', 0))}</td><td>{html.escape(str(segment.get('preset', '')))}</td>"
            + "".join(f"<td>{cell}</td>" for cell in cells)
            + "</tr>"
        )
    header = "".join(f"<th>{name}</th>" for name in ("Segment", "Preset", *CHANNELS))
    return (
        "<section><h2>64 Hz line by headband mode</h2>"
        f"<p>{html.escape(VERDICT_TEXT.get(str(summary.get('verdict')), ''))}</p>"
        "<p class=muted>Two minutes each, eyes closed, the headband on throughout. Fitted line amplitude and its "
        f"height over the neighbouring frequencies, medians over 10 s windows; present from {PRESENT_DB:g} dB.</p>"
        f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        "</section>"
    )


def _num(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number


def _fmt(value, digits: int) -> str:
    number = _num(value)
    return "–" if not math.isfinite(number) else f"{number:.{digits}f}"
