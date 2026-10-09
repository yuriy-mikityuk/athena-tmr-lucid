"""Meditation A/B block protocol and complexity analysis.

A meditation session is an ordinary recording plus a sidecar blocks JSON that
says which condition ran when. The analysis cuts 10 s epochs, computes the
metrics from ``muse_tmr.features.complexity_features``, averages them per
block and contrasts the two conditions. Because Muse temporal channels sit over
the temporalis, every contrast is reported next to an EMG check.

Inference is across sessions only (``aggregate_meditation_summaries``): epochs
within a session are autocorrelated and would inflate significance.

Kept separate from REM detection, gating, scheduling and audio.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import math
import platform
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import AsyncIterable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import scipy
from scipy.stats import spearmanr

from muse_tmr.data.sample_types import MuseFrame
from muse_tmr.features.complexity_features import (
    CHANNEL_GROUPS,
    EPOCH_METRICS,
    ComplexityConfig,
    block_dfa,
    dfa_metric_names,
    extract_complexity_features,
)
from muse_tmr.features.eeg_features import _collect_epoch_eeg
from muse_tmr.features.epochs import EpochBuilder, EpochConfig, SleepEpoch

MEDITATION_BLOCKS_SCHEMA_VERSION = 1
MEDITATION_SUMMARY_SCHEMA_VERSION = 1
MEDITATION_AGGREGATE_SCHEMA_VERSION = 1
TIME_BASE = "seconds_from_recording_start"
PRIMARY_METRIC = "lzc"
PRIMARY_GROUP = "all"
# The one predeclared test: raw (not EMG-residualized) contrast on clean epochs.
PRIMARY_VARIANT = "clean"
VARIANTS = ("all", "clean")
# Power metrics are contrasted, correlated and residualized on log10.
LOG10_METRICS = frozenset(
    {
        "band_power_delta",
        "band_power_theta",
        "band_power_alpha",
        "band_power_beta",
        "band_power_gamma",
        "emg_power_30_45",
        "emg_power_55_95",
    }
)
EMG_INDICATORS = ("emg_power_55_95", "emg_power_30_45")
# Per-block Polar H10 features (blocks.csv columns cardio_<name>, contrast group "chest").
CARDIO_METRICS = (
    "resp_rate_bpm",
    "resp_rate_breath_bpm",
    "edr_rate_bpm",
    "mean_hr_bpm",
    "rmssd_ms",
    "sdnn_ms",
    "rsa_power_ms2",
    "lf_power_ms2",
    "hf_power_ms2",
    "hf_band_valid",
    "rr_corrected_pct",
    "ecg_rr_matched_pct",
    "resp_reliable",
    "acc_posture_change_pct",
)
# Contrasted only over blocks whose breathing estimate is reliable.
CARDIO_BREATHING_METRICS = frozenset({"resp_rate_bpm", "resp_rate_breath_bpm", "edr_rate_bpm", "rsa_power_ms2", "hf_band_valid"})


# --- blocks file -------------------------------------------------------------


@dataclass(frozen=True)
class MeditationBlock:
    index: int
    condition: str
    start_s: float
    end_s: float
    depth: Optional[float] = None
    sensory_fading: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "index": self.index,
            "condition": self.condition,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "depth": self.depth,
            "sensory_fading": self.sensory_fading,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "MeditationBlock":
        return cls(
            index=int(data["index"]),
            condition=str(data["condition"]),
            start_s=float(data["start_s"]),
            end_s=float(data["end_s"]),
            depth=_optional_float(data.get("depth")),
            sensory_fading=_optional_float(data.get("sensory_fading")),
            notes=str(data.get("notes") or ""),
        )


@dataclass(frozen=True)
class MeditationBlocks:
    blocks: Tuple[MeditationBlock, ...]
    settle_seconds: float = 0.0
    order: Tuple[str, ...] = ()
    conditions: Tuple[str, ...] = ()
    seed: Optional[int] = None
    schema_version: int = MEDITATION_BLOCKS_SCHEMA_VERSION
    time_base: str = TIME_BASE

    def condition_pair(self) -> Tuple[str, str]:
        """(A, B); contrasts are A - B."""
        conditions = list(self.conditions) or list(dict.fromkeys(block.condition for block in self.blocks))
        if len(conditions) != 2 or conditions[0] == conditions[1]:
            raise ValueError("a meditation blocks file needs exactly two distinct conditions")
        return conditions[0], conditions[1]

    def validate(self) -> None:
        if self.schema_version != MEDITATION_BLOCKS_SCHEMA_VERSION:
            raise ValueError(f"unsupported blocks schema_version {self.schema_version}")
        if self.time_base != TIME_BASE:
            raise ValueError(f"time_base must be {TIME_BASE}")
        if not self.blocks:
            raise ValueError("blocks file has no blocks")
        pair = self.condition_pair()
        previous_end = -math.inf
        for block in sorted(self.blocks, key=lambda item: item.start_s):
            if block.end_s <= block.start_s:
                raise ValueError(f"block {block.index} ends before it starts")
            if block.start_s < previous_end:
                raise ValueError(f"block {block.index} overlaps the previous block")
            if block.condition not in pair:
                raise ValueError(f"block {block.index} has unknown condition {block.condition}")
            previous_end = block.end_s

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "schema_version": self.schema_version,
            "time_base": self.time_base,
            "settle_seconds": self.settle_seconds,
            "conditions": list(self.conditions),
            "order": list(self.order),
            "blocks": [block.to_dict() for block in self.blocks],
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "MeditationBlocks":
        blocks = cls(
            blocks=tuple(MeditationBlock.from_dict(item) for item in data.get("blocks", ())),
            settle_seconds=float(data.get("settle_seconds", 0.0)),
            order=tuple(str(item) for item in data.get("order", ())),
            conditions=tuple(str(item) for item in data.get("conditions", ())),
            seed=int(data["seed"]) if data.get("seed") is not None else None,
            schema_version=int(data.get("schema_version", MEDITATION_BLOCKS_SCHEMA_VERSION)),
            time_base=str(data.get("time_base", TIME_BASE)),
        )
        blocks.validate()
        return blocks


def build_meditation_plan(
    conditions: Sequence[str],
    *,
    blocks: int = 4,
    block_minutes: float = 8.0,
    settle_seconds: float = 60.0,
    seed: int,
) -> MeditationBlocks:
    """ABBA BAAB... (Thue-Morse) order, or its mirror BAAB ABBA..., picked by seed.

    With alternating ABAB, A runs half a block earlier on average, so any
    monotonic drift (relaxing, drowsiness, dry electrodes settling) lands in the
    A - B contrast. Thue-Morse order cancels linear drift within each group of
    four blocks and quadratic drift within eight; other counts leave some drift
    in (see ``check_drift_cancelling``). Ratings are left null.
    """
    conditions = tuple(str(condition).strip() for condition in conditions)
    if len(conditions) != 2 or not all(conditions) or conditions[0] == conditions[1]:
        raise ValueError("meditation-plan needs exactly two distinct conditions")
    if blocks < 2:
        raise ValueError("meditation-plan needs at least two blocks")
    if block_minutes <= 0 or settle_seconds < 0:
        raise ValueError("block_minutes must be positive and settle_seconds non-negative")
    first, second = conditions
    if random.Random(seed).random() >= 0.5:
        first, second = second, first
    order = tuple(first if bin(index).count("1") % 2 == 0 else second for index in range(blocks))
    block_seconds = block_minutes * 60.0
    plan = MeditationBlocks(
        blocks=tuple(
            MeditationBlock(
                index=index,
                condition=condition,
                start_s=settle_seconds + index * block_seconds,
                end_s=settle_seconds + (index + 1) * block_seconds,
            )
            for index, condition in enumerate(order)
        ),
        settle_seconds=settle_seconds,
        order=order,
        conditions=conditions,
        seed=seed,
    )
    plan.validate()
    return plan


def check_drift_cancelling(blocks: int) -> None:
    """Only whole groups of four cancel linear drift (ABBABA leaves a third of a
    block's drift in A - B), so plans for real sessions must use 4, 8, 12... blocks.
    ``build_meditation_plan`` itself still takes any count, for tests and quick checks."""
    if blocks < 4 or blocks % 4:
        raise ValueError("use a multiple of 4 blocks (4, 8, 12): only whole ABBA groups cancel drift")


def load_meditation_blocks(path: Path) -> MeditationBlocks:
    return MeditationBlocks.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def write_meditation_blocks(blocks: MeditationBlocks, path: Path) -> Path:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blocks.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def assign_block(
    start_s: float,
    end_s: float,
    blocks: MeditationBlocks,
    trim_block_start_seconds: float,
) -> Optional[MeditationBlock]:
    """The block an epoch sits wholly inside, after trimming the block start."""
    if start_s < blocks.settle_seconds:
        return None
    for block in blocks.blocks:
        if start_s >= block.start_s + trim_block_start_seconds - 1e-9 and end_s <= block.end_s + 1e-9:
            return block
    return None


# --- analysis ----------------------------------------------------------------


@dataclass(frozen=True)
class MeditationAnalysisConfig:
    epoch_seconds: float = 10.0
    trim_block_start_seconds: float = 30.0
    # "auto": 55-95 Hz when it sits above the near-Nyquist floor, else 30-45 Hz.
    emg_indicator: str = "auto"
    emg_band_min_over_floor_db: float = 3.0
    # |A - B| of the log10 EMG indicator above this marks the session confounded.
    emg_confound_log10_threshold: float = 0.1
    # |A - B| of the Polar breathing rate above this marks breathing as a confound.
    breathing_confound_bpm: float = 1.0
    complexity: ComplexityConfig = field(default_factory=ComplexityConfig)

    def validate(self) -> None:
        if self.epoch_seconds <= 0:
            raise ValueError("epoch_seconds must be positive")
        if self.trim_block_start_seconds < 0:
            raise ValueError("trim_block_start_seconds must be non-negative")
        if self.emg_indicator not in ("auto", *EMG_INDICATORS):
            raise ValueError(f"emg_indicator must be auto or one of {EMG_INDICATORS}")
        self.complexity.validate()

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["complexity"] = self.complexity.to_dict()
        return payload


@dataclass(frozen=True)
class EpochRecord:
    block: MeditationBlock
    start_s: float
    end_s: float
    features: Mapping[str, object]
    channels: Mapping[str, np.ndarray]


@dataclass
class MeditationAnalysis:
    epochs: pd.DataFrame
    blocks: pd.DataFrame
    summary: Dict[str, object]

    def write(self, output_dir: Path) -> Dict[str, Path]:
        output_dir = Path(output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "epochs": output_dir / "epochs.csv",
            "blocks": output_dir / "blocks.csv",
            "summary": output_dir / "summary.json",
            "report": output_dir / "report.html",
        }
        self.epochs.to_csv(paths["epochs"], index=False)
        self.blocks.to_csv(paths["blocks"], index=False)
        paths["summary"].write_text(
            json.dumps(json_safe(self.summary), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        from muse_tmr.reports.meditation_report import render_meditation_report

        paths["report"].write_text(
            render_meditation_report(self.summary, self.blocks.to_dict("records")), encoding="utf-8"
        )
        return paths


async def analyze_meditation_frames(
    frames: AsyncIterable[MuseFrame],
    blocks: MeditationBlocks,
    config: Optional[MeditationAnalysisConfig] = None,
    *,
    recording: str = "",
    polar=None,
    polar_error: Optional[str] = None,
) -> MeditationAnalysis:
    """``polar`` is an optional ``PolarSession`` on the same wall-clock base."""
    config = config or MeditationAnalysisConfig()
    config.validate()
    blocks.validate()
    builder = EpochBuilder(
        EpochConfig(
            epoch_seconds=config.epoch_seconds,
            stride_seconds=config.epoch_seconds,
            emit_partial=False,
        )
    )
    records: List[EpochRecord] = []
    origin: Optional[float] = None
    async for epoch in builder.build(frames):
        if origin is None:
            origin = epoch.start_time
        start_s = epoch.start_time - origin
        end_s = start_s + config.epoch_seconds
        block = assign_block(start_s, end_s, blocks, config.trim_block_start_seconds)
        if block is None:
            continue
        records.append(_epoch_record(epoch, block, start_s, end_s, config))
    return build_meditation_analysis(
        records,
        blocks,
        config,
        recording=recording,
        polar=polar,
        origin_time=origin,
        polar_error=polar_error,
    )


async def analyze_meditation_recording(
    recording_dir: Path,
    blocks: MeditationBlocks,
    config: Optional[MeditationAnalysisConfig] = None,
    *,
    use_polar: bool = True,
) -> MeditationAnalysis:
    """Analyze a recording; a ``polar/`` folder from ``record --with-polar`` is used when present."""
    from muse_tmr.data.replay import ReplayConfig, ReplaySession

    polar, polar_error = None, None
    if use_polar and (Path(recording_dir) / "polar" / "raw_notifications.jsonl").exists():
        from muse_tmr.data.polar_session import load_polar_session

        try:
            polar = load_polar_session(Path(recording_dir))
        except Exception as exc:  # a broken Polar log must not stop the EEG analysis
            polar_error = f"{type(exc).__name__}: {exc}"

    session = ReplaySession(ReplayConfig(input_path=Path(recording_dir), speed=0.0))
    await session.connect()
    try:
        return await analyze_meditation_frames(
            session.stream(),
            blocks,
            config,
            recording=str(recording_dir),
            polar=polar,
            polar_error=polar_error,
        )
    finally:
        await session.stop()


def _epoch_record(
    epoch: SleepEpoch,
    block: MeditationBlock,
    start_s: float,
    end_s: float,
    config: MeditationAnalysisConfig,
) -> EpochRecord:
    channels = _collect_epoch_eeg(epoch)
    row = extract_complexity_features(epoch, config.complexity, channels=channels)
    features = row.to_dict()
    features.update(
        {
            "start_s": start_s,
            "end_s": end_s,
            "block_index": block.index,
            "condition": block.condition,
        }
    )
    return EpochRecord(block=block, start_s=start_s, end_s=end_s, features=features, channels=channels)


def build_meditation_analysis(
    records: Sequence[EpochRecord],
    blocks: MeditationBlocks,
    config: MeditationAnalysisConfig,
    *,
    recording: str = "",
    polar=None,
    origin_time: Optional[float] = None,
    polar_error: Optional[str] = None,
) -> MeditationAnalysis:
    condition_a, condition_b = blocks.condition_pair()
    epochs = pd.DataFrame([record.features for record in records])
    if epochs.empty:
        raise ValueError("no epochs fell inside the blocks; check the blocks file timings")
    leading = ["epoch_index", "start_s", "end_s", "block_index", "condition", "is_artifact", "artifact_flags"]
    epochs = epochs[leading + [column for column in epochs.columns if column not in leading]]
    clean_mask = ~epochs["is_artifact"].astype(bool)

    epoch_columns = [f"{metric}_{group}" for metric in EPOCH_METRICS for group in CHANNEL_GROUPS]
    dfa_by_block = {
        block.index: block_dfa(_clean_runs(records, block.index, config.complexity), config.complexity)
        for block in blocks.blocks
    }
    dfa_columns = [f"{metric}_{group}" for metric in dfa_metric_names(config.complexity) for group in CHANNEL_GROUPS]
    cardio_by_block = _cardio_by_block(polar, origin_time, blocks, config)
    block_table = _block_table(epochs, clean_mask, blocks, epoch_columns, dfa_by_block, cardio_by_block)
    cardio_columns = [f"cardio_{metric}" for metric in CARDIO_METRICS] if cardio_by_block else []

    contrasts = []
    for variant in VARIANTS:
        rows = block_table[block_table["variant"] == variant]
        for column in epoch_columns + dfa_columns:
            metric, group = _split_column(column)
            contrasts.append(
                _contrast(rows, column, metric, group, variant, condition_a, condition_b)
            )
    # Chest data does not depend on EEG artifact flags: one variant is enough.
    all_rows = block_table[block_table["variant"] == "all"]
    reliable_rows = all_rows
    if cardio_columns:
        reliable_rows = all_rows.copy()
        unreliable = reliable_rows["cardio_resp_reliable"] != 1.0
        for metric in CARDIO_BREATHING_METRICS:
            reliable_rows.loc[unreliable, f"cardio_{metric}"] = math.nan
    for column in cardio_columns:
        rows = reliable_rows if column[len("cardio_"):] in CARDIO_BREATHING_METRICS else all_rows
        contrasts.append(_contrast(rows, column, column, "chest", "all", condition_a, condition_b))

    emg = _emg_section(epochs, clean_mask, block_table, epoch_columns, condition_a, condition_b, config)
    counts = {
        "epochs_in_blocks": int(len(epochs)),
        "clean_epochs": int(clean_mask.sum()),
        "artifact_epochs": int((~clean_mask).sum()),
        "blocks": len(blocks.blocks),
        "blocks_with_epochs": int(epochs["block_index"].nunique()),
    }
    summary: Dict[str, object] = {
        "schema_version": MEDITATION_SUMMARY_SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "recording": recording,
        "conditions": [condition_a, condition_b],
        "contrast": f"{condition_a} - {condition_b}",
        "primary_metric": {
            "metric": PRIMARY_METRIC,
            "group": PRIMARY_GROUP,
            "variant": PRIMARY_VARIANT,
            "kind": "raw",
            "note": "Declared before analysis. Every other metric, group, variant and the "
            "EMG-residualized contrasts are exploratory.",
        },
        "config": config.to_dict(),
        "versions": _versions(),
        "blocks_file": blocks.to_dict(),
        "counts": counts,
        "ratings": _ratings(blocks, condition_a, condition_b),
        "condition_means": _condition_means(
            block_table, epoch_columns + dfa_columns + cardio_columns, condition_a, condition_b
        ),
        "contrasts": contrasts,
        "emg": emg,
    }
    cardio = _cardio_section(polar, polar_error, block_table, contrasts, config)
    summary["cardio"] = cardio
    summary["limitations"] = _limitations(counts, emg, config) + cardio.pop("limitations", [])
    return MeditationAnalysis(epochs=epochs, blocks=block_table, summary=summary)


def _cardio_by_block(
    polar,
    origin_time: Optional[float],
    blocks: MeditationBlocks,
    config: MeditationAnalysisConfig,
) -> Dict[int, Dict[str, float]]:
    """Polar features over each block's analysed window (block start + trim to block end).

    Block times are seconds from the first Muse frame; Muse replay and the
    Polar loader both use host wall-clock, so origin + offset lines them up.
    """
    if polar is None or origin_time is None:
        return {}
    from muse_tmr.features.cardio_resp_features import extract_cardio_resp_features

    by_block = {}
    for block in blocks.blocks:
        start = origin_time + block.start_s + config.trim_block_start_seconds
        end = origin_time + block.end_s
        features = extract_cardio_resp_features(polar, start, end) if end > start else {}
        by_block[block.index] = {metric: float(features.get(metric, math.nan)) for metric in CARDIO_METRICS}
    return by_block


def _cardio_section(
    polar,
    polar_error: Optional[str],
    block_table: pd.DataFrame,
    contrasts: Sequence[Mapping[str, object]],
    config: MeditationAnalysisConfig,
) -> Dict[str, object]:
    if polar is None:
        section: Dict[str, object] = {"available": False}
        if polar_error:
            section["error"] = polar_error
            section["limitations"] = [f"Polar data present but could not be loaded: {polar_error}"]
        return section
    breathing = next(
        (item for item in contrasts if item["metric"] == "cardio_resp_rate_bpm" and item["group"] == "chest"),
        None,
    )
    difference = float(breathing["difference"]) if breathing else math.nan
    confounded = math.isfinite(difference) and abs(difference) > config.breathing_confound_bpm
    all_rows = block_table[block_table["variant"] == "all"]
    reliable = all_rows["cardio_resp_reliable"] == 1.0
    invalid_hf = int(((all_rows["cardio_hf_band_valid"] == 0) & reliable).sum())
    unreliable_blocks = [int(index) for index in all_rows.loc[~reliable, "block_index"]]
    limitations = []
    if unreliable_blocks:
        limitations.append(
            f"Breathing rate not trusted in block(s) {unreliable_blocks}: posture changes or the "
            "spectral and breath-by-breath estimates disagree; those blocks are left out of the "
            "breathing contrasts and the confound check."
        )
    if confounded:
        limitations.append(
            f"Conditions differ in breathing rate by {difference:+.1f} breaths/min (Polar H10); "
            "slower breathing can itself shift EEG and HRV, so read the EEG contrasts with that in mind."
        )
    if invalid_hf:
        limitations.append(
            f"{invalid_hf} block(s) breathe slower than 9/min, where classic HF misses the RSA; "
            "use cardio_rsa_power_ms2 there."
        )
    alignment = polar.alignment or {}
    return {
        "available": True,
        "source": "polar_h10",
        "breathing_difference_bpm": difference,
        "breathing_confound_threshold_bpm": config.breathing_confound_bpm,
        "breathing_confounded": confounded,
        "breathing_unreliable_blocks": unreliable_blocks,
        "hf_band_invalid_blocks": invalid_hf,
        "quality": dict(polar.quality or {}),
        "alignment": {
            "mapping": alignment.get("mapping"),
            "clock_segments": len(alignment.get("clock_segments") or []),
            "rr": alignment.get("rr"),
        },
        "limitations": limitations,
    }


def _clean_runs(
    records: Sequence[EpochRecord],
    block_index: int,
    config: ComplexityConfig,
) -> Dict[str, List[np.ndarray]]:
    """Per channel, contiguous runs of clean epochs in one block, as arrays."""
    runs: Dict[str, List[List[np.ndarray]]] = {channel: [] for channel in config.channels}
    previous_index: Optional[int] = None
    for record in records:
        if record.block.index != block_index:
            continue
        clean = not bool(record.features.get("is_artifact"))
        epoch_index = int(record.features["epoch_index"])
        if not clean:
            previous_index = None
            continue
        contiguous = previous_index is not None and epoch_index == previous_index + 1
        for channel in config.channels:
            values = record.channels.get(channel)
            if values is None:
                continue
            if contiguous and runs[channel]:
                runs[channel][-1].append(values)
            else:
                runs[channel].append([values])
        previous_index = epoch_index
    return {
        channel: [np.concatenate(parts) for parts in channel_runs]
        for channel, channel_runs in runs.items()
    }


def _block_table(
    epochs: pd.DataFrame,
    clean_mask: pd.Series,
    blocks: MeditationBlocks,
    epoch_columns: Sequence[str],
    dfa_by_block: Mapping[int, Mapping[str, float]],
    cardio_by_block: Optional[Mapping[int, Mapping[str, float]]] = None,
) -> pd.DataFrame:
    rows = []
    for block in blocks.blocks:
        in_block = epochs["block_index"] == block.index
        for variant in VARIANTS:
            selected = epochs[in_block & clean_mask] if variant == "clean" else epochs[in_block]
            row: Dict[str, object] = {
                "block_index": block.index,
                "condition": block.condition,
                "variant": variant,
                "start_s": block.start_s,
                "end_s": block.end_s,
                "depth": block.depth,
                "sensory_fading": block.sensory_fading,
                "epochs": int(len(selected)),
            }
            for column in epoch_columns:
                values = _transformed(selected[column], column) if len(selected) else pd.Series(dtype=float)
                row[column] = float(values.mean()) if values.notna().any() else math.nan
            # DFA always uses clean segments only, so both variants carry the same values.
            row.update(dfa_by_block.get(block.index, {}))
            if cardio_by_block:
                row.update({f"cardio_{name}": value for name, value in cardio_by_block.get(block.index, {}).items()})
            rows.append(row)
    return pd.DataFrame(rows)


def is_primary(metric: str, group: str, variant: str, kind: str = "raw") -> bool:
    return (metric, group, variant, kind) == (PRIMARY_METRIC, PRIMARY_GROUP, PRIMARY_VARIANT, "raw")


def _contrast(
    block_rows: pd.DataFrame,
    column: str,
    metric: str,
    group: str,
    variant: str,
    condition_a: str,
    condition_b: str,
) -> Dict[str, object]:
    a = block_rows.loc[block_rows["condition"] == condition_a, column].dropna()
    b = block_rows.loc[block_rows["condition"] == condition_b, column].dropna()
    a_mean = float(a.mean()) if len(a) else math.nan
    b_mean = float(b.mean()) if len(b) else math.nan
    primary = is_primary(metric, group, variant)
    return {
        "metric": metric,
        "group": group,
        "variant": variant,
        "transform": "log10" if metric in LOG10_METRICS else "none",
        "primary": primary,
        "label": "primary" if primary else "exploratory",
        "a_mean": a_mean,
        "b_mean": b_mean,
        "difference": a_mean - b_mean,
        "n_blocks_a": int(len(a)),
        "n_blocks_b": int(len(b)),
    }


def _emg_section(
    epochs: pd.DataFrame,
    clean_mask: pd.Series,
    block_table: pd.DataFrame,
    epoch_columns: Sequence[str],
    condition_a: str,
    condition_b: str,
    config: MeditationAnalysisConfig,
) -> Dict[str, object]:
    over_floor = epochs["emg_high_band_over_floor_db_all"].dropna()
    over_floor_median = float(over_floor.median()) if len(over_floor) else math.nan
    if config.emg_indicator != "auto":
        indicator, reason = config.emg_indicator, "set explicitly"
    elif math.isfinite(over_floor_median) and over_floor_median < config.emg_band_min_over_floor_db:
        indicator = "emg_power_30_45"
        reason = (
            f"55-95 Hz is only {over_floor_median:.1f} dB above the near-Nyquist floor "
            f"(< {config.emg_band_min_over_floor_db} dB), so it carries no usable signal"
        )
    else:
        indicator = "emg_power_55_95"
        reason = (
            "55-95 Hz sits above the near-Nyquist floor"
            if math.isfinite(over_floor_median)
            else "near-Nyquist floor not measurable at this sample rate"
        )
    indicator_column = f"{indicator}_all"

    differences = {}
    for variant in VARIANTS:
        rows = block_table[block_table["variant"] == variant]
        contrast = _contrast(rows, indicator_column, indicator, "all", variant, condition_a, condition_b)
        differences[variant] = {
            "a_mean_log10": contrast["a_mean"],
            "b_mean_log10": contrast["b_mean"],
            "difference_log10": contrast["difference"],
            "ratio": 10 ** contrast["difference"] if math.isfinite(contrast["difference"]) else math.nan,
        }
    confounded = any(
        math.isfinite(item["difference_log10"])
        and abs(item["difference_log10"]) > config.emg_confound_log10_threshold
        for item in differences.values()
    )

    correlations = []
    residualized = []
    for variant in VARIANTS:
        selected = epochs[clean_mask] if variant == "clean" else epochs
        emg_values = _transformed(selected[indicator_column], indicator_column)
        for column in epoch_columns:
            metric, group = _split_column(column)
            if metric.startswith("emg_"):
                continue
            values = _transformed(selected[column], column)
            correlations.append(
                {"metric": metric, "group": group, "variant": variant, **_spearman(emg_values, values)}
            )
            residualized.append(
                {
                    "metric": metric,
                    "group": group,
                    "variant": variant,
                    "primary": False,
                    **_residualized_contrast(selected, values, emg_values, condition_a, condition_b),
                }
            )
    return {
        "indicator": indicator,
        "indicator_reason": reason,
        "high_band_over_floor_db_median": over_floor_median,
        "confound_threshold_log10": config.emg_confound_log10_threshold,
        "emg_confounded": confounded,
        "condition_difference": differences,
        "correlations": correlations,
        "residualized_contrasts": residualized,
    }


def _spearman(x: pd.Series, y: pd.Series) -> Dict[str, object]:
    pair = pd.concat([x, y], axis=1).dropna()
    if len(pair) < 5 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
        return {"spearman_rho": math.nan, "n_epochs": int(len(pair))}
    rho = spearmanr(pair.iloc[:, 0], pair.iloc[:, 1]).correlation
    # No p-value: epochs are autocorrelated, so it would overstate certainty.
    return {"spearman_rho": float(rho), "n_epochs": int(len(pair))}


def _residualized_contrast(
    selected: pd.DataFrame,
    values: pd.Series,
    emg_values: pd.Series,
    condition_a: str,
    condition_b: str,
) -> Dict[str, object]:
    """A - B of block means after regressing the metric on log10 EMG (OLS)."""
    frame = pd.DataFrame(
        {
            "value": values,
            "emg": emg_values,
            "condition": selected["condition"],
            "block_index": selected["block_index"],
        }
    ).dropna()
    nan = {"raw_difference": math.nan, "residualized_difference": math.nan, "n_epochs": int(len(frame))}
    if len(frame) < 5 or frame["emg"].nunique() < 2:
        return nan
    design = np.column_stack([np.ones(len(frame)), frame["emg"].to_numpy()])
    coefficients, *_ = np.linalg.lstsq(design, frame["value"].to_numpy(), rcond=None)
    frame["residual"] = frame["value"] - design @ coefficients + frame["value"].mean()

    def difference(column: str) -> float:
        block_means = frame.groupby(["block_index", "condition"])[column].mean().reset_index()
        a = block_means.loc[block_means["condition"] == condition_a, column]
        b = block_means.loc[block_means["condition"] == condition_b, column]
        if not len(a) or not len(b):
            return math.nan
        return float(a.mean() - b.mean())

    return {
        "raw_difference": difference("value"),
        "residualized_difference": difference("residual"),
        "emg_slope": float(coefficients[1]),
        "n_epochs": int(len(frame)),
    }


def _condition_means(
    block_table: pd.DataFrame,
    columns: Sequence[str],
    condition_a: str,
    condition_b: str,
) -> Dict[str, Dict[str, Dict[str, float]]]:
    means: Dict[str, Dict[str, Dict[str, float]]] = {}
    for variant in VARIANTS:
        rows = block_table[block_table["variant"] == variant]
        means[variant] = {}
        for condition in (condition_a, condition_b):
            selected = rows[rows["condition"] == condition]
            means[variant][condition] = {
                column: float(selected[column].mean()) if selected[column].notna().any() else math.nan
                for column in columns
            }
    return means


def _ratings(blocks: MeditationBlocks, condition_a: str, condition_b: str) -> Dict[str, object]:
    ratings: Dict[str, object] = {}
    for condition in (condition_a, condition_b):
        selected = [block for block in blocks.blocks if block.condition == condition]
        ratings[condition] = {
            name: _mean_or_nan(getattr(block, name) for block in selected)
            for name in ("depth", "sensory_fading")
        }
    return ratings


def _limitations(
    counts: Mapping[str, int],
    emg: Mapping[str, object],
    config: MeditationAnalysisConfig,
) -> List[str]:
    limitations = [
        "Single session: no inference here. Use aggregate-meditation across sessions; "
        "epochs are autocorrelated and must not be treated as independent samples.",
        "Primary metric is all-channel mean LZC; every other metric and group is exploratory "
        "and p-values are not corrected across metrics.",
        "Four channels (TP9, AF7, AF8, TP10) referenced at Fpz; TP9/TP10 sit over the temporalis, "
        "so gamma, entropy and 1/f slope can move with jaw or scalp muscle tension.",
        "Lyapunov exponent on 10 s windows is noisy and parameter-sensitive; treat it as experimental.",
        "Criticality markers are still debated; the reference paper (Mago et al. 2025, "
        "arXiv:2511.20990) is a preprint.",
        "MMN and neuronal avalanches from the paper are not possible on this setup.",
    ]
    if emg.get("emg_confounded"):
        limitations.append(
            "Conditions differ in the EMG indicator beyond the threshold; read the "
            "EMG-residualized contrasts before the raw ones."
        )
    if emg.get("indicator") == "emg_power_30_45":
        limitations.append(
            "EMG indicator fell back to 30-45 Hz, which overlaps the EEG gamma band and is a weaker check."
        )
    if counts.get("clean_epochs", 0) < counts.get("epochs_in_blocks", 0) / 2:
        limitations.append("More than half of the in-block epochs are artifact-flagged.")
    if not config.complexity.lyapunov_enabled:
        limitations.append("Lyapunov exponent skipped (--no-lyapunov).")
    return limitations


# --- cross-session aggregation -----------------------------------------------


def aggregate_meditation_summaries(
    summaries: Sequence[Mapping[str, object]],
    *,
    labels: Optional[Sequence[str]] = None,
    min_sessions_for_inference: int = 8,
    permutations: int = 10000,
    bootstrap: int = 10000,
    seed: int = 0,
) -> Dict[str, object]:
    """One A - B difference per session per contrast; sign-flip test and bootstrap CI."""
    if not summaries:
        raise ValueError("no summaries to aggregate")
    if labels is None:
        labels = [str(item.get("recording") or index) for index, item in enumerate(summaries)]
    labels = list(labels)
    reference = tuple(summaries[0]["conditions"])
    # One slot per session, so differences[i] always belongs to sessions[i];
    # a session without a contrast (e.g. no Polar data) stays NaN / null.
    per_contrast: Dict[Tuple[str, str, str, str], List[float]] = {}
    for position, summary in enumerate(summaries):
        conditions = tuple(summary["conditions"])
        if set(conditions) != set(reference):
            raise ValueError(f"session conditions {conditions} do not match {reference}")
        sign = 1.0 if conditions == reference else -1.0
        values = [
            ((item["metric"], item["group"], item["variant"], "raw"), item["difference"])
            for item in summary.get("contrasts", ())
        ] + [
            ((item["metric"], item["group"], item["variant"], "emg_residualized"), item["residualized_difference"])
            for item in summary.get("emg", {}).get("residualized_contrasts", ())
        ]
        for key, value in values:
            slots = per_contrast.setdefault(key, [math.nan] * len(summaries))
            slots[position] = sign * _to_float(value)

    n_sessions = len(summaries)
    inference = n_sessions >= min_sessions_for_inference
    rows = []
    for (metric, group, variant, kind), differences in sorted(per_contrast.items()):
        finite = np.asarray([value for value in differences if math.isfinite(value)], dtype=float)
        primary = is_primary(metric, group, variant, kind)
        row: Dict[str, object] = {
            "metric": metric,
            "group": group,
            "variant": variant,
            "kind": kind,
            "primary": primary,
            "label": "primary" if primary else "exploratory",
            "n_sessions": int(finite.size),
            "mean_difference": float(finite.mean()) if finite.size else math.nan,
            "sd_difference": float(finite.std(ddof=1)) if finite.size > 1 else math.nan,
            "differences": [float(value) for value in differences],
        }
        if inference and finite.size >= min_sessions_for_inference:
            row["p_sign_flip"] = sign_flip_p_value(finite, permutations=permutations, seed=seed)
            row["ci95"] = list(bootstrap_ci(finite, resamples=bootstrap, seed=seed))
        rows.append(row)

    warnings = []
    if not inference:
        warnings.append(
            f"Only {n_sessions} session(s); at least {min_sessions_for_inference} are needed "
            "before any p-value or confidence interval is reported. Descriptives only."
        )
    return {
        "schema_version": MEDITATION_AGGREGATE_SCHEMA_VERSION,
        "conditions": list(reference),
        "contrast": f"{reference[0]} - {reference[1]}",
        "sessions": labels,
        "n_sessions": n_sessions,
        "min_sessions_for_inference": min_sessions_for_inference,
        "primary_metric": {
            "metric": PRIMARY_METRIC,
            "group": PRIMARY_GROUP,
            "variant": PRIMARY_VARIANT,
            "kind": "raw",
        },
        "emg_confounded_sessions": [
            label for label, summary in zip(labels, summaries) if summary.get("emg", {}).get("emg_confounded")
        ],
        "warnings": warnings,
        "rows": rows,
    }


def sign_flip_p_value(differences: np.ndarray, *, permutations: int = 10000, seed: int = 0) -> float:
    """Two-sided sign-flip permutation p-value for the mean difference."""
    differences = np.asarray(differences, dtype=float)
    observed = abs(differences.mean())
    n = differences.size
    if n <= 16:
        signs = np.array(list(itertools.product((1.0, -1.0), repeat=n)))
    else:
        signs = np.random.default_rng(seed).choice((1.0, -1.0), size=(permutations, n))
    means = np.abs((signs * differences).mean(axis=1))
    return float(np.mean(means >= observed - 1e-12))


def bootstrap_ci(
    differences: np.ndarray,
    *,
    resamples: int = 10000,
    seed: int = 0,
    level: float = 0.95,
) -> Tuple[float, float]:
    differences = np.asarray(differences, dtype=float)
    rng = np.random.default_rng(seed)
    means = differences[rng.integers(0, differences.size, size=(resamples, differences.size))].mean(axis=1)
    tail = (1.0 - level) / 2.0
    return float(np.quantile(means, tail)), float(np.quantile(means, 1.0 - tail))


# --- helpers -----------------------------------------------------------------


def _transformed(values: pd.Series, column: str) -> pd.Series:
    metric, _group = _split_column(column)
    values = pd.to_numeric(values, errors="coerce")
    if metric in LOG10_METRICS:
        return np.log10(values.where(values > 0))
    return values


def _split_column(column: str) -> Tuple[str, str]:
    metric, _, group = column.rpartition("_")
    return metric, group


def _to_float(value) -> float:
    # summary.json stores NaN as null.
    return math.nan if value is None else float(value)


def _optional_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def _mean_or_nan(values: Iterable[Optional[float]]) -> float:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return float(np.mean(finite)) if finite else math.nan


def _versions() -> Dict[str, str]:
    try:
        from importlib.metadata import version

        package = version("amused")
    except Exception:
        package = "unknown"
    return {
        "amused": package,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "pandas": pd.__version__,
    }


def json_safe(value):
    """NaN and inf become null so the output is strict JSON."""
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value
