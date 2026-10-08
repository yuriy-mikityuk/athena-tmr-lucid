"""Polar H10 heart rate, HRV and breathing over a night, for the nightly report.

Builds an HTML section (inline SVG, no scripts or external assets) on the same
time axis as the REM-probability chart: hours since the first Muse epoch.
"""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

WINDOW_SECONDS = 300.0


def night_cardio_windows(session, start_time: float, end_time: float, window_seconds: float = WINDOW_SECONDS) -> List[Dict[str, float]]:
    """Cardio/breathing features per window from ``start_time`` (wall clock)."""
    from muse_tmr.features.cardio_resp_features import extract_cardio_resp_features

    windows = []
    start = start_time
    while start < end_time:
        end = min(start + window_seconds, end_time)
        if end - start >= window_seconds / 2:
            features = extract_cardio_resp_features(session, start, end)
            windows.append({"t_hours": (start - start_time) / 3600.0, **features})
        start += window_seconds
    return windows


def night_cardio_section(recording_dir: Path, start_time: float, end_time: float) -> str:
    """The report section, or "" when there is no Polar data; never raises."""
    if not (Path(recording_dir) / "polar" / "raw_notifications.jsonl").exists():
        return ""
    try:
        from muse_tmr.data.polar_session import load_polar_session

        session = load_polar_session(Path(recording_dir))
        windows = night_cardio_windows(session, start_time, end_time)
    except Exception as exc:  # a broken Polar log must not cost the REM report
        return _section(f"<p class='chart-sub'>Polar H10 data is present but could not be read: {_e(str(exc))}</p>")
    if not windows:
        return ""
    return _section(_summary(windows, _rr_match(session, start_time, end_time)) + _chart(windows) + _table(windows))


def _rr_match(session, start_time: float, end_time: float) -> Dict[str, int]:
    """RR beats inside the reported interval and how many matched an ECG R-peak."""
    rr = session.rr
    if rr is None or len(rr) == 0:
        return {"beats": 0, "matched": 0}
    inside = rr[(rr["time"] >= start_time) & (rr["time"] < end_time)]
    return {"beats": int(len(inside)), "matched": int((inside["aligned_to"] == "ecg_r_peak").sum())}


def _summary(windows: Sequence[Dict[str, float]], rr: Dict[str, int]) -> str:
    hr = _finite(window.get("mean_hr_bpm") for window in windows)
    rmssd = _finite(window.get("rmssd_ms") for window in windows)
    trusted = [window for window in windows if window.get("resp_reliable") == 1.0]
    breathing = _finite(window.get("resp_rate_bpm") for window in trusted)
    parts = []
    if hr.size:
        parts.append(f"Heart rate averaged <b>{hr.mean():.0f} bpm</b>, lowest 5-min window {hr.min():.0f} bpm.")
    if rmssd.size:
        parts.append(f"RMSSD median {np.median(rmssd):.0f} ms.")
    if breathing.size:
        parts.append(
            f"Breathing median <b>{np.median(breathing):.1f}/min</b> over {len(trusted)} of {len(windows)} windows "
            "where the chest was still and both estimates agreed."
        )
    else:
        parts.append("No window had a trustworthy breathing estimate (movement or disagreeing estimates).")
    if rr.get("beats"):
        parts.append(f"{rr.get('matched', 0)} of {rr['beats']} RR beats matched an ECG R-peak.")
    return f"<p class='chart-sub'>{' '.join(parts)}</p>"


def _chart(windows: Sequence[Dict[str, float]]) -> str:
    width, height, pad_left, pad_right, pad_top, pad_bottom = 880, 220, 44, 44, 14, 28
    plot_w, plot_h = width - pad_left - pad_right, height - pad_top - pad_bottom
    t_max = max(window["t_hours"] for window in windows) + WINDOW_SECONDS / 3600.0
    hr = _finite(window.get("mean_hr_bpm") for window in windows)
    resp = _finite(window.get("resp_rate_bpm") for window in windows)
    hr_low, hr_high = (math.floor(hr.min() / 5) * 5 - 5, math.ceil(hr.max() / 5) * 5 + 5) if hr.size else (40, 100)
    resp_high = max(20.0, math.ceil(resp.max() / 5) * 5) if resp.size else 20.0

    half_window_hours = WINDOW_SECONDS / 7200.0

    def x(t: float) -> float:
        return pad_left + t / t_max * plot_w

    def x_window(start_hours: float) -> float:  # windows are drawn at their centre
        return x(start_hours + half_window_hours)

    def y_hr(value: float) -> float:
        return pad_top + (1 - (value - hr_low) / (hr_high - hr_low)) * plot_h

    def y_resp(value: float) -> float:
        return pad_top + (1 - value / resp_high) * plot_h

    # One polyline per run of windows with HR, so a dropout shows as a gap, not a straight line.
    hr_runs: List[List[str]] = [[]]
    for w in windows:
        if _ok(w.get("mean_hr_bpm")):
            hr_runs[-1].append(f"{x_window(w['t_hours']):.1f},{y_hr(w['mean_hr_bpm']):.1f}")
        elif hr_runs[-1]:
            hr_runs.append([])
    hr_lines = "".join(
        f'<polyline points="{" ".join(run)}" class="hr"/>' if len(run) > 1 else
        f'<circle cx="{run[0].split(",")[0]}" cy="{run[0].split(",")[1]}" r="2.5" class="hrdot"/>'
        for run in hr_runs if run
    )
    dots = []
    for w in windows:
        if not _ok(w.get("resp_rate_bpm")):
            continue
        trusted = w.get("resp_reliable") == 1.0
        css = "resp" if trusted else "resp untrusted"
        dots.append(
            f'<circle cx="{x_window(w["t_hours"]):.1f}" cy="{y_resp(w["resp_rate_bpm"]):.1f}" r="3.5" class="{css}">'
            f'<title>{w["t_hours"]:.2f} h: breathing {w["resp_rate_bpm"]:.1f}/min{"" if trusted else " (not trusted)"}</title></circle>'
        )
    hour_ticks = "".join(
        f'<line x1="{x(h):.1f}" x2="{x(h):.1f}" y1="{pad_top}" y2="{pad_top + plot_h}" class="grid"/>'
        f'<text x="{x(h):.1f}" y="{height - 8}" class="tick" text-anchor="middle">{h:g}h</text>'
        for h in np.arange(0, t_max + 1e-9, 1.0 if t_max > 2 else 0.25)
    )
    axes = (
        f'<text x="{pad_left - 6}" y="{pad_top + 10}" class="tick hrc" text-anchor="end">{hr_high:.0f}</text>'
        f'<text x="{pad_left - 6}" y="{pad_top + plot_h}" class="tick hrc" text-anchor="end">{hr_low:.0f}</text>'
        f'<text x="{width - pad_right + 6}" y="{pad_top + 10}" class="tick respc">{resp_high:.0f}</text>'
        f'<text x="{width - pad_right + 6}" y="{pad_top + plot_h}" class="tick respc">0</text>'
    )
    legend = (
        "<p class='chart-sub legend'><span class='hrc'>━ heart rate (bpm, left)</span> · "
        "<span class='respc'>● breathing (/min, right)</span> · <span class='respc'>○ not trusted</span></p>"
    )
    return (
        legend
        + f'<svg viewBox="0 0 {width} {height}" class="cardio" role="img" aria-label="Heart rate and breathing over the night">'
        + hour_ticks
        + axes
        + hr_lines
        + "".join(dots)
        + "</svg>"
    )


def _table(windows: Sequence[Dict[str, float]]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{w['t_hours']:.2f}h</td><td>{_fmt(w.get('mean_hr_bpm'), 0)}</td><td>{_fmt(w.get('rmssd_ms'), 0)}</td>"
        f"<td>{_fmt(w.get('resp_rate_bpm'), 1)}</td><td>{'yes' if w.get('resp_reliable') == 1.0 else 'no'}</td>"
        "</tr>"
        for w in windows
    )
    return (
        "<details><summary>Table view &mdash; 5-minute windows</summary><table><thead><tr>"
        "<th>From</th><th>HR</th><th>RMSSD ms</th><th>Breathing /min</th><th>Trusted</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></details>"
    )


def _section(body: str) -> str:
    style = (
        "<style>.cardio{width:100%;height:auto;margin-top:6px}.cardio .grid{stroke:var(--gridline)}"
        ".cardio .tick{fill:var(--text-muted);font-size:11px}.cardio .hr{fill:none;stroke:#d64545;stroke-width:2}"
        ".cardio .hrdot{fill:#d64545}"
        ".cardio .resp{fill:#2a9d8f}.cardio .resp.untrusted{fill:none;stroke:#2a9d8f;stroke-width:1.2}"
        ".hrc{color:#d64545;fill:#d64545}.respc{color:#2a9d8f;fill:#2a9d8f}.cardio-card{margin-top:20px}</style>"
    )
    return (
        f"{style}<div class='chart-card cardio-card'><p class='chart-title'>Heart and breathing (Polar H10)</p>"
        f"{body}</div>"
    )


def _finite(values) -> np.ndarray:
    array = np.asarray([value for value in values if _ok(value)], dtype=float)
    return array


def _ok(value) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _fmt(value, digits: int) -> str:
    return f"{float(value):.{digits}f}" if _ok(value) else "–"


def _e(text: str) -> str:
    return html.escape(text, quote=True)
