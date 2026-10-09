"""Readable HTML page for one analyze-meditation run.

Self-contained (inline CSS and SVG, no external assets) and built only from
``summary.json`` plus the ``blocks.csv`` rows, so it can be regenerated later.
"""

from __future__ import annotations

import html
import math
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

# Metrics compared in Mago et al. 2025, shown as a fixed, exploratory set.
PAPER_METRICS = (
    ("lzc", "Lempel-Ziv complexity"),
    ("sample_entropy", "Sample entropy"),
    ("permutation_entropy", "Permutation entropy"),
    ("hjorth_mobility", "Hjorth mobility"),
    ("aperiodic_exponent_2_20", "1/f exponent, 2-20 Hz"),
    ("aperiodic_exponent_2_40", "1/f exponent, 2-40 Hz"),
    ("lyapunov_max", "Largest Lyapunov exponent"),
    ("band_power_alpha", "Alpha power (log10)"),
    ("band_power_gamma", "Gamma power (log10)"),
    ("dfa_theta", "DFA theta envelope"),
    ("dfa_alpha", "DFA alpha envelope"),
    ("dfa_beta", "DFA beta envelope"),
    ("dfa_low_gamma", "DFA low-gamma envelope"),
)
BREATHING_COLUMNS = (
    ("cardio_resp_rate_bpm", "ACC spectral /min"),
    ("cardio_resp_rate_breath_bpm", "ACC breath-by-breath /min"),
    ("cardio_edr_rate_bpm", "ECG-derived /min"),
)
BREATHING_METHOD_LABELS = {"acc_spectral": "ACC spectral", "acc_breath": "ACC breath-by-breath", "edr": "ECG-derived"}
CARDIO_COLUMNS = (
    *BREATHING_COLUMNS,
    ("breathing_spread", "Spread /min"),
    ("cardio_mean_hr_bpm", "HR"),
    ("cardio_rmssd_ms", "RMSSD ms"),
    ("cardio_rsa_power_ms2", "RSA ms²"),
    ("cardio_resp_reliable", "Breathing trusted"),
)


def render_meditation_report(summary: Mapping[str, object], block_rows: Sequence[Mapping[str, object]]) -> str:
    condition_a, condition_b = summary["conditions"]
    recording = str(summary.get("recording") or "")
    name = recording.rstrip("/").split("/")[-1] or "session"
    clean_rows = [row for row in block_rows if row.get("variant") == "clean"]
    all_rows = [row for row in block_rows if row.get("variant") == "all"]
    contrasts = {
        (item["metric"], item["group"], item["variant"]): item for item in summary.get("contrasts", ())
    }
    primary = contrasts.get(("lzc", "all", "clean"), {})

    sections = [
        _header(name, summary, condition_a, condition_b),
        _primary_section(primary, clean_rows, condition_a, condition_b),
        _ratings_section(summary, condition_a, condition_b),
        _emg_section(summary.get("emg") or {}, condition_a, condition_b),
        _emg_timeline_section(summary, condition_a),
        _cardio_section(summary.get("cardio") or {}, all_rows),
        _paper_metrics_section(contrasts, condition_a, condition_b),
        _blocks_section(clean_rows, all_rows),
        _limitations_section(summary.get("limitations") or ()),
    ]
    body = "\n".join(section for section in sections if section)
    return _PAGE.format(title=_e(f"Meditation session {name}"), body=body)


# --- sections ---------------------------------------------------------------


def _header(name: str, summary: Mapping[str, object], condition_a: str, condition_b: str) -> str:
    counts = summary.get("counts") or {}
    return (
        f"<header><h1>Meditation session <span class=mono>{_e(name)}</span></h1>"
        f"<p class=muted>{_e(condition_a)} vs {_e(condition_b)} · contrasts are "
        f"<b>{_e(condition_a)} − {_e(condition_b)}</b> · {counts.get('blocks', '?')} blocks, "
        f"{counts.get('epochs_in_blocks', '?')} epochs in blocks ({counts.get('clean_epochs', '?')} clean) · "
        f"generated {_e(str(summary.get('generated_at', ''))[:16].replace('T', ' '))} UTC</p></header>"
    )


def _primary_section(primary: Mapping[str, object], clean_rows, condition_a: str, condition_b: str) -> str:
    if not primary:
        return ""
    values = {
        condition: [
            (int(row["block_index"]), _num(row.get("lzc_all")))
            for row in clean_rows
            if row.get("condition") == condition and math.isfinite(_num(row.get("lzc_all")))
        ]
        for condition in (condition_a, condition_b)
    }
    return (
        "<section><h2>Primary result</h2>"
        "<p>All-channel mean Lempel-Ziv complexity on clean epochs, declared before the analysis. "
        "One session is a single data point: read this next to the other sessions in "
        "<code>aggregate-meditation</code>, not on its own.</p>"
        f"<div class=kpis>{_kpi(condition_a, primary.get('a_mean'))}{_kpi(condition_b, primary.get('b_mean'))}"
        f"{_kpi('difference', primary.get('difference'), signed=True)}</div>"
        f"{_dot_plot(values, condition_a, condition_b)}</section>"
    )


def _ratings_section(summary: Mapping[str, object], condition_a: str, condition_b: str) -> str:
    ratings = summary.get("ratings") or {}
    rows = []
    for condition in (condition_a, condition_b):
        item = ratings.get(condition) or {}
        rows.append([_e(condition), _fmt(item.get("depth"), 1), _fmt(item.get("sensory_fading"), 1)])
    if all(cell == "–" for row in rows for cell in row[1:]):
        return ""
    return "<section><h2>Ratings</h2>" + _table(["Condition", "Depth", "Sensory fading"], rows) + "</section>"


def _emg_section(emg: Mapping[str, object], condition_a: str, condition_b: str) -> str:
    if not emg:
        return ""
    difference = (emg.get("condition_difference") or {}).get("clean") or {}
    verdict = (
        "<span class=warn>Conditions differ in muscle activity</span>: read the EMG-residualized column first."
        if emg.get("emg_confounded")
        else "<span class=ok>No EMG difference beyond the threshold.</span>"
    )
    residualized = {
        (item["metric"], item["group"], item["variant"]): item for item in emg.get("residualized_contrasts", ())
    }
    correlations = {(item["metric"], item["group"], item["variant"]): item for item in emg.get("correlations", ())}
    rows = []
    for metric, label in PAPER_METRICS:
        item = residualized.get((metric, "all", "clean"))
        if item is None:
            continue
        rho = (correlations.get((metric, "all", "clean")) or {}).get("spearman_rho")
        rows.append(
            [
                _e(label),
                _fmt(item.get("raw_difference"), 4, signed=True),
                _fmt(item.get("residualized_difference"), 4, signed=True),
                _fmt(rho, 2, signed=True),
            ]
        )
    groups = (emg.get("group_difference_db") or {}).get("clean") or {}
    by_group = ""
    if groups:
        by_group = (
            " By channel group, A − B: "
            f"all {_fmt(groups.get('all'), 1, signed=True)} dB, "
            f"AF7/AF8 (forehead) {_fmt(groups.get('frontal'), 1, signed=True)} dB, "
            f"TP9/TP10 (jaw) {_fmt(groups.get('temporal'), 1, signed=True)} dB."
        )
    return (
        "<section><h2>Muscle (EMG) check</h2>"
        f"<p>{verdict} Indicator <code>{_e(str(emg.get('indicator', '')))}</code> "
        f"({_e(str(emg.get('indicator_reason', '')))}). {_e(condition_a)} vs {_e(condition_b)}: "
        f"{_fmt(difference.get('ratio'), 2)}× the EMG power on clean epochs.{by_group}</p>"
        + _table(["Metric (all channels, clean)", "Raw A−B", "After removing EMG", "ρ with EMG"], rows)
        + "</section>"
    )


def _emg_timeline_section(summary: Mapping[str, object], condition_a: str) -> str:
    blocks = (summary.get("blocks_file") or {}).get("blocks") or ()
    spans = [
        {
            "start_s": block["start_s"],
            "end_s": block["end_s"],
            "label": block["condition"],
            "shaded": block["condition"] == condition_a,
        }
        for block in blocks
    ]
    plot = emg_timeline_svg(summary.get("timeline") or (), spans, "EMG power over the session")
    if not plot:
        return ""
    return (
        "<section><h2>Muscle (EMG) over the session</h2>"
        "<p class=muted>55–95 Hz per 10 s epoch, dB: <span class=af>AF7/AF8</span> and <span class=tp>TP9/TP10</span>. "
        f"Shaded blocks are {_e(condition_a)}. The settle period and the trimmed block starts are shown but not "
        "analysed. ABBA cancels a linear drift, not a fast one at the start: if the level keeps falling through "
        "the first blocks, begin with a longer stretch of meditation that is not analysed.</p>"
        + plot
        + "</section>"
    )


# Rows written before end_s was recorded were all 10 s epochs.
_DEFAULT_EPOCH_SECONDS = 10.0


def emg_timeline_svg(rows: Sequence[Mapping[str, object]], spans: Sequence[Mapping[str, object]], label: str) -> str:
    """55-95 Hz dB per epoch for AF7/AF8 and TP9/TP10; spans get a label on top, shaded ones a band.

    Points sit at epoch midpoints; a missing value or a missing epoch breaks the line.
    """
    keys = (("emg_55_95_frontal_db", "af"), ("emg_55_95_temporal_db", "tp"))
    traces = {key: trace_segments(rows, key) for key, _css in keys}
    values = [value for segments in traces.values() for segment in segments for _middle, value in segment]
    if len(values) < 2:
        return ""
    width, height, left, top, bottom = 860, 220, 44, 26, 24
    end_s = max(
        max(_epoch_end(row) for row in rows),
        max((float(span["end_s"]) for span in spans), default=0.0),
    )
    low, high = min(values) - 1.0, max(values) + 1.0

    def x(seconds: float) -> float:
        return left + seconds / end_s * (width - left - 4)

    def y(value: float) -> float:
        return top + (high - value) / (high - low) * (height - top - bottom)

    shapes = []
    for span in spans:
        x0, x1 = x(float(span["start_s"])), x(float(span["end_s"]))
        if span.get("shaded"):
            shapes.append(
                f'<rect x="{x0:.1f}" y="{top}" width="{max(1.0, x1 - x0):.1f}" height="{height - top - bottom}" '
                f'class="band"><title>{_e(str(span.get("title") or span["label"]))}</title></rect>'
            )
        shapes.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{top - 8}" class="lbl" text-anchor="middle">{_e(str(span["label"]))}</text>')
    for key, css in keys:
        for segment in traces[key]:
            if len(segment) == 1:
                (middle, value), = segment
                shapes.append(f'<circle cx="{x(middle):.1f}" cy="{y(value):.1f}" r="1.8" class="dot {css}"/>')
                continue
            path = " ".join(f"{x(middle):.1f},{y(value):.1f}" for middle, value in segment)
            shapes.append(f'<polyline points="{path}" class="line {css}"/>')
    step = 2 if end_s <= 40 * 60 else 5
    for minute in range(0, int(end_s // 60) + 1, step):
        shapes.append(f'<text x="{x(minute * 60):.1f}" y="{height - 6}" class="lbl" text-anchor="middle">{minute}</text>')
    shapes.append(f'<text x="2" y="{y(high - 1):.1f}" class="lbl">{high - 1:.0f} dB</text>')
    shapes.append(f'<text x="2" y="{y(low + 1):.1f}" class="lbl">{low + 1:.0f} dB</text>')
    return (
        f'<svg viewBox="0 0 {width} {height}" class="timeline" role="img" aria-label="{_e(label)}">'
        + "".join(shapes)
        + "</svg>"
        "<style>.timeline{width:100%;height:auto}.timeline .band{fill:var(--line);opacity:.6}"
        ".timeline .line{fill:none;stroke-width:1.8}.timeline .af{stroke:var(--a)}.timeline .tp{stroke:var(--b)}"
        ".timeline .dot.af{fill:var(--a)}.timeline .dot.tp{fill:var(--b)}"
        ".timeline .lbl{fill:var(--muted);font-size:11px}span.af{color:var(--a);font-weight:600}span.tp{color:var(--b);font-weight:600}</style>"
    )


def trace_segments(rows: Sequence[Mapping[str, object]], key: str) -> List[List[Tuple[float, float]]]:
    """Runs of (epoch midpoint s, value); a missing value or a missing epoch ends a run."""
    segments: List[List[Tuple[float, float]]] = []
    current: List[Tuple[float, float]] = []
    previous_end: Optional[float] = None
    for row in sorted(rows, key=lambda item: float(item["start_s"])):
        start, end = float(row["start_s"]), _epoch_end(row)
        value = _num(row.get(key))
        if current and (not math.isfinite(value) or start > previous_end + 1e-6):
            segments.append(current)
            current = []
        if math.isfinite(value):
            current.append(((start + end) / 2.0, value))
        previous_end = end
    if current:
        segments.append(current)
    return segments


def _epoch_end(row: Mapping[str, object]) -> float:
    end = _num(row.get("end_s"))
    return end if math.isfinite(end) else float(row["start_s"]) + _DEFAULT_EPOCH_SECONDS


def _cardio_section(cardio: Mapping[str, object], all_rows) -> str:
    if not cardio.get("available"):
        error = cardio.get("error")
        return f"<section><h2>Breathing and HRV</h2><p class=muted>Polar H10 data could not be loaded: {_e(str(error))}</p></section>" if error else ""
    unreliable = cardio.get("breathing_unreliable_blocks") or []
    difference = cardio.get("breathing_difference_bpm")
    if difference is None or not math.isfinite(_num(difference)):
        verdict = "Breathing was not compared: no trusted blocks in one of the conditions."
    elif cardio.get("breathing_confounded"):
        verdict = f"<span class=warn>Breathing differs by {_fmt(difference, 1, signed=True)} /min</span>, a possible confound for the EEG contrasts."
    else:
        verdict = f"<span class=ok>Breathing differs by {_fmt(difference, 1, signed=True)} /min</span>, within the threshold."
    if unreliable:
        verdict += f" Not trusted (movement or disagreeing estimates): block(s) {', '.join(str(index) for index in unreliable)}."
    methods = cardio.get("breathing_methods") or {}
    method_line = ""
    if any(math.isfinite(_num(item.get("difference"))) for item in methods.values()):
        listed = ", ".join(
            f"{BREATHING_METHOD_LABELS.get(method, method)} {_fmt(item.get('difference'), 1, signed=True)}"
            for method, item in methods.items()
        )
        method_line = (
            f"<p>A − B by method: {listed} /min. The flag uses their median; none of them is checked "
            "against a known breathing rate yet."
        )
        if cardio.get("breathing_methods_disagree"):
            method_line += (
                f" <span class=warn>The methods disagree by {_fmt(cardio.get('breathing_methods_spread_bpm'), 1)} /min</span>, "
                "so the breathing check is uncertain."
            )
        method_line += "</p>"
    header = ["Block", "Condition"] + [label for _column, label in CARDIO_COLUMNS]
    rows = []
    for row in all_rows:
        cells = [str(row.get("block_index")), _e(str(row.get("condition")))]
        for column, _label in CARDIO_COLUMNS:
            value = row.get(column)
            if column == "cardio_resp_reliable":
                cells.append("yes" if _num(value) == 1.0 else "no")
            elif column == "breathing_spread":
                rates = [_num(row.get(name)) for name, _ in BREATHING_COLUMNS]
                rates = [rate for rate in rates if math.isfinite(rate)]
                cells.append(_fmt(max(rates) - min(rates), 1) if len(rates) >= 2 else "–")
            else:
                cells.append(_fmt(value, 1))
        rows.append(cells)
    return (
        "<section><h2>Breathing and HRV (Polar H10)</h2>"
        f"<p>{verdict}</p>{method_line}" + _table(header, rows) + "</section>"
    )


def _paper_metrics_section(contrasts, condition_a: str, condition_b: str) -> str:
    rows = []
    for metric, label in PAPER_METRICS:
        if metric == "lzc":
            continue  # the predeclared primary result has its own section
        item = contrasts.get((metric, "all", "clean"))
        if item is None:
            continue
        rows.append(
            [
                _e(label),
                _fmt(item.get("a_mean"), 4),
                _fmt(item.get("b_mean"), 4),
                _fmt(item.get("difference"), 4, signed=True),
            ]
        )
    if not rows:
        return ""
    return (
        "<section><h2>Metrics from the paper <span class=tag>exploratory</span></h2>"
        "<p class=muted>All-channel means of block means, clean epochs. Not corrected for multiple comparisons.</p>"
        + _table(["Metric", _e(condition_a), _e(condition_b), "A−B"], rows)
        + "</section>"
    )


def _blocks_section(clean_rows, all_rows) -> str:
    clean = {int(row["block_index"]): row for row in clean_rows}
    rows = []
    for row in all_rows:
        index = int(row["block_index"])
        start, end = _num(row.get("start_s")), _num(row.get("end_s"))
        rows.append(
            [
                str(index),
                _e(str(row.get("condition"))),
                f"{start / 60:.1f}–{end / 60:.1f} min",
                f"{int(_num(clean.get(index, {}).get('epochs', 0)))}/{int(_num(row.get('epochs')))}",
                _fmt(clean.get(index, {}).get("lzc_all"), 4),
                _fmt(row.get("depth"), 0),
                _fmt(row.get("sensory_fading"), 0),
            ]
        )
    return "<section><h2>Blocks</h2>" + _table(
        ["Block", "Condition", "Time", "Clean/all epochs", "LZC (clean)", "Depth", "Sensory fading"], rows
    ) + "</section>"


def _limitations_section(limitations: Sequence[str]) -> str:
    if not limitations:
        return ""
    items = "".join(f"<li>{_e(str(item))}</li>" for item in limitations)
    return f"<section><h2>Limitations</h2><ul>{items}</ul></section>"


# --- small pieces -------------------------------------------------------------


def _dot_plot(values: Mapping[str, List], condition_a: str, condition_b: str) -> str:
    points = [value for series in values.values() for _index, value in series]
    if not points:
        return ""
    low, high = min(points), max(points)
    pad = (high - low) * 0.15 or 0.01
    low, high = low - pad, high + pad
    width, height, left = 520, 120, 110
    rows_svg = []
    for row, (condition, css) in enumerate(((condition_a, "a"), (condition_b, "b"))):
        y = 35 + row * 50
        rows_svg.append(f'<text x="0" y="{y + 4}" class="lbl">{_e(condition)}</text>')
        rows_svg.append(f'<line x1="{left}" x2="{width}" y1="{y}" y2="{y}" class="grid"/>')
        for index, value in values.get(condition, []):
            x = left + (value - low) / (high - low) * (width - left)
            rows_svg.append(
                f'<circle cx="{x:.1f}" cy="{y}" r="6" class="dot {css}"><title>block {index}: {value:.4f}</title></circle>'
            )
    axis = f'<text x="{left}" y="{height - 4}" class="lbl">{low:.3f}</text><text x="{width}" y="{height - 4}" class="lbl" text-anchor="end">{high:.3f}</text>'
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="LZC per block by condition" class="plot">'
        + "".join(rows_svg)
        + axis
        + "</svg>"
    )


def _kpi(label: str, value, signed: bool = False) -> str:
    return f"<div class=kpi><span class=muted>{_e(label)}</span><b>{_fmt(value, 4, signed=signed)}</b></div>"


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{cell}</th>" for cell in header)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<div class=scroll><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def _num(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number


def _fmt(value, digits: int, signed: bool = False) -> str:
    number = _num(value)
    if not math.isfinite(number):
        return "–"
    return f"{number:+.{digits}f}" if signed else f"{number:.{digits}f}"


def _e(text: str) -> str:
    return html.escape(str(text), quote=True)


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#f7f7f5; --card:#ffffff; --text:#1c1c1a; --muted:#6b6a65; --line:#e3e2dc;
        --a:#2a78d6; --b:#d9822b; --warn:#b45309; --ok:#15803d; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#141413; --card:#1d1d1b; --text:#ecebe6; --muted:#a3a29b; --line:#33322e;
          --a:#6aa6ee; --b:#f0a65a; --warn:#f59e0b; --ok:#4ade80; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--text);
       font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
main {{ max-width:880px; margin:0 auto; }}
header h1 {{ margin:0 0 4px; font-size:1.5rem; }}
section {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px; margin:14px 0; }}
h2 {{ margin:0 0 8px; font-size:1.1rem; }}
.muted {{ color:var(--muted); }}
.mono, code {{ font-family:ui-monospace, Menlo, monospace; font-size:0.9em; }}
.tag {{ font-size:0.7rem; font-weight:600; color:var(--muted); border:1px solid var(--line); border-radius:999px; padding:1px 8px; vertical-align:middle; }}
.warn {{ color:var(--warn); font-weight:600; }}
.ok {{ color:var(--ok); font-weight:600; }}
.kpis {{ display:flex; gap:12px; flex-wrap:wrap; margin:8px 0; }}
.kpi {{ border:1px solid var(--line); border-radius:8px; padding:8px 12px; min-width:140px; display:flex; flex-direction:column; }}
.kpi b {{ font-size:1.25rem; font-variant-numeric:tabular-nums; }}
.scroll {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }}
th {{ color:var(--muted); font-weight:600; font-size:0.85rem; }}
.plot {{ width:100%; max-width:560px; height:auto; }}
.plot .grid {{ stroke:var(--line); }}
.plot .lbl {{ fill:var(--muted); font-size:12px; }}
.plot .dot.a {{ fill:var(--a); }}
.plot .dot.b {{ fill:var(--b); }}
ul {{ margin:0; padding-left:20px; }}
</style>
</head>
<body><main>
{body}
</main></body>
</html>
"""
