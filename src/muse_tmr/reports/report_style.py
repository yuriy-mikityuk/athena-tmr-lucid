"""What the reports share with the app and the meditation guide.

Every report is one self-contained HTML file: its fonts are the system's and its
mark is inline, so it opens from disk and loads nothing over the network.
"""

from __future__ import annotations

import datetime as dt
import html
from typing import Optional

BRAND = "Athena TMR"

# The app's tokens, light first and then the same names in dark mode. The practices
# keep their guide colours (focus teal, open orange) and the night its indigo.
TOKENS_CSS = """
:root {
  --paper: #faf8f4; --sheet: #ffffff; --ink: #1b232d; --muted: #5d6874; --line: #e7e2d9;
  --focus: #0f766e; --open: #b45309; --sleep: #4b5694; --warn: #b45309; --ok: #15803d;
  --warn-bg: #fcefe0; --warn-line: #f2d3ad;
  --serif: "Iowan Old Style", Charter, Georgia, "Times New Roman", serif;
  --sans: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #131615; --sheet: #1b1f1e; --ink: #ecebe6; --muted: #a3a29b; --line: #33322e;
    --focus: #2dd4bf; --open: #f59e0b; --sleep: #a5adf0; --warn: #f59e0b; --ok: #4ade80;
    --warn-bg: #2a2210; --warn-line: #5b4413;
  }
}
.brand {
  display: flex; align-items: center; gap: 8px; margin: 0 0 10px; color: var(--muted);
  font: 700 0.75rem/1.2 var(--sans); letter-spacing: 0.08em; text-transform: uppercase;
}
.brand svg { width: 22px; height: 22px; flex: none; }
h1, h2 { font-family: var(--serif); font-weight: 600; }
a { color: var(--focus); }
"""

MARK_SVG = (
    '<svg viewBox="0 0 32 32" aria-hidden="true">'
    '<path d="M5 23 C6 13 11 7 16 7 C21 7 26 13 27 23" fill="none" stroke="#0f766e" stroke-width="3.2" stroke-linecap="round"/>'
    '<circle cx="5" cy="23.5" r="2.6" fill="#4b5694"/><circle cx="27" cy="23.5" r="2.6" fill="#4b5694"/>'
    '<circle cx="16" cy="7" r="2.2" fill="#b45309"/></svg>'
)


def brand_line(kind: str) -> str:
    """The line above a report's title: the mark, the app's name and the kind of report."""
    return f'<p class="brand">{MARK_SVG}<span>{html.escape(BRAND)} · {html.escape(kind)}</span></p>'


def format_braces(css: str) -> str:
    """CSS made safe to sit inside a str.format template."""
    return css.replace("{", "{{").replace("}", "}}")


def readable_time(value: Optional[str]) -> str:
    """An ISO timestamp as the local 'Sat 17 Oct 2026, 16:22'; anything else as given."""
    if not value:
        return ""
    try:
        moment = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return f"{moment:%a} {moment.day} {moment:%b %Y, %H:%M}"
