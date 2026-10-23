"""Named synthetic nights for tests and the demo. Synthetic input, not sleep.

Each scenario is a ``SyntheticNightConfig`` with a few fields changed; ``hours``
shortens or lengthens any of them. A recording takes about 12 MB an hour on ``p21``
(97 MB for 8 h) and 17 MB an hour on ``p1034``, whose battery empties after about
4.3 h, so scenarios are generated on demand into a temporary or gitignored directory
(``data/synthetic/``) and never committed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Mapping, Optional, Tuple

from muse_tmr.testing.synthetic import SyntheticNightConfig

# p1034 at 23.34 %/h (#108) empties a battery that starts at this level after 2 h 29 min.
BATTERY_DEATH_SECONDS = 2 * 3600 + 29 * 60
_P1034_DRAIN = 23.34


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    hours: float
    overrides: Mapping[str, object] = field(default_factory=dict)

    def config(self, *, seed: int = 0, hours: Optional[float] = None) -> SyntheticNightConfig:
        return replace(
            SyntheticNightConfig(),
            scenario=self.name,
            seed=int(seed),
            hours=float(self.hours if hours is None else hours),
            **dict(self.overrides),
        )


SCENARIOS: Dict[str, Scenario] = {
    scenario.name: scenario
    for scenario in (
        Scenario(
            "clean_night",
            "p21, 8 h: 4 or 5 sleep cycles, each ending in a REM period, few arousals",
            8.0,
            {"preset": "p21"},
        ),
        Scenario(
            "fragmented_rem",
            "p21, 8 h: every REM period broken by 3 brief awakenings, more arousals",
            8.0,
            {"preset": "p21", "rem_interruptions": 3, "arousals_per_hour": 12.0},
        ),
        Scenario(
            "no_rem_nap",
            "p1034, 1 h nap: wake, N1, N2 and N3, no REM",
            1.0,
            {"preset": "p1034", "rem_periods": 0},
        ),
        Scenario(
            "battery_death_2h29",
            "p1034 at 23.34 %/h from a battery that is empty after 2 h 29 min; the stream ends there",
            8.0,
            {
                "preset": "p1034",
                "battery_drain_percent_per_hour": _P1034_DRAIN,
                "battery_start_percent": _P1034_DRAIN * BATTERY_DEATH_SECONDS / 3600,
            },
        ),
        Scenario(
            "optics_line",
            "p1034, 2 h with the optics line at 40 µV on AF7",
            2.0,
            {"preset": "p1034", "line_uv": 40.0},
        ),
        Scenario(
            "bad_contact_af7",
            "p21, 2 h with AF7 off the skin from 25 % to 60 % of the night",
            2.0,
            {"preset": "p21", "bad_contact_channel": "AF7", "bad_contact_span": (0.25, 0.60)},
        ),
        Scenario(
            "movement_heavy",
            "p21, 2 h of restless sleep: 30 arousals an hour, most with movement",
            2.0,
            {"preset": "p21", "arousals_per_hour": 30.0, "movement_share": 0.8, "movement_scale": 1.5},
        ),
        Scenario(
            "short_allow_short",
            "p1034, 10 min, the length of a record --allow-short smoke test",
            10 / 60,
            {"preset": "p1034"},
        ),
    )
}


def scenario_names() -> Tuple[str, ...]:
    return tuple(SCENARIOS)


def scenario_config(name: str, *, seed: int = 0, hours: Optional[float] = None) -> SyntheticNightConfig:
    """The config of scenario ``name``; ``hours`` replaces its length."""
    try:
        scenario = SCENARIOS[name]
    except KeyError:
        raise ValueError(f"unknown scenario {name!r}; choose one of {', '.join(SCENARIOS)}") from None
    return scenario.config(seed=seed, hours=hours)
