"""CLI entry point for the Muse REM-TMR project."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence

from muse_tmr import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="muse-tmr",
        description="Muse S Athena REM-TMR/TLR research tooling.",
    )
    parser.add_argument("--version", action="version", version=f"muse-tmr {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show project status and configured components.")

    app_parser = subparsers.add_parser("app", help="Run the local Muse setup web app.")
    app_parser.add_argument("--source", choices=("mock", "amused"), default="mock")
    app_parser.add_argument("--host", default="127.0.0.1")
    app_parser.add_argument("--port", type=int, default=8765)
    app_parser.add_argument("--address", help="Muse BLE address. If omitted, discovery is used.")
    app_parser.add_argument("--name-filter", default="Muse")
    app_parser.add_argument("--preset", default="p1034")
    app_parser.add_argument(
        "--mock-scenario",
        default="mixed_fair_good",
        help="Mock contact scenario for local UI development.",
    )
    app_parser.add_argument("--mock-interval-seconds", type=float, default=1.0)
    app_parser.add_argument("--contact-stability-seconds", type=float, default=5.0)

    discover_parser = subparsers.add_parser("discover", help="Discover Muse devices.")
    discover_parser.add_argument("--source", choices=("amused", "openmuse", "sdk"), default="amused")
    discover_parser.add_argument("--name-filter", default="Muse")
    _add_openmuse_lsl_args(discover_parser)
    _add_muse_sdk_args(discover_parser)

    stream_parser = subparsers.add_parser("stream", help="Stream Muse frames from a source.")
    stream_parser.add_argument("--source", choices=("amused", "openmuse", "sdk"), default="amused")
    stream_parser.add_argument("--address", help="Muse BLE address. If omitted, discovery is used.")
    stream_parser.add_argument("--name-filter", default="Muse")
    stream_parser.add_argument("--preset", default="p1034")
    stream_parser.add_argument("--duration-seconds", type=int, default=3600)
    stream_parser.add_argument("--quiet", action="store_true")
    _add_openmuse_lsl_args(stream_parser)
    _add_muse_sdk_args(stream_parser)

    replay_parser = subparsers.add_parser("replay", help="Replay a recorded Muse session.")
    replay_parser.add_argument("input", type=Path, help="Recording directory or raw_amused.bin path.")
    replay_parser.add_argument(
        "--speed",
        type=float,
        default=0.0,
        help="Replay speed multiplier. 1.0 is real time; 0.0 replays as fast as possible.",
    )
    replay_parser.add_argument("--start-seconds", type=float, help="Relative replay start offset.")
    replay_parser.add_argument("--end-seconds", type=float, help="Relative replay end offset.")

    annotate_parser = subparsers.add_parser(
        "annotate-template",
        help="Generate an editable REM annotation template from replayed epochs.",
    )
    annotate_parser.add_argument("input", type=Path, help="Recording directory or raw_amused.bin path.")
    annotate_parser.add_argument("--output", type=Path, required=True, help="Output .csv or .json path.")
    annotate_parser.add_argument("--epoch-seconds", type=float, default=30.0)
    annotate_parser.add_argument("--stride-seconds", type=float, default=30.0)
    annotate_parser.add_argument("--start-seconds", type=float, help="Relative replay start offset.")
    annotate_parser.add_argument("--end-seconds", type=float, help="Relative replay end offset.")
    annotate_parser.add_argument(
        "--label",
        choices=("wake", "nrem", "probable_rem", "unknown"),
        default="unknown",
        help="Initial label for generated rows. Use unknown for manual labeling templates.",
    )

    train_parser = subparsers.add_parser(
        "train-rem-classifier",
        help="Train a personal REM classifier from labeled annotation rows.",
    )
    train_parser.add_argument("annotations", type=Path, help="Input annotation .csv or .json path.")
    train_parser.add_argument("--output", type=Path, required=True, help="Output model .json path.")
    train_parser.add_argument(
        "--feature",
        action="append",
        dest="features",
        help="Feature column to use. Repeat to override the default feature set.",
    )
    train_parser.add_argument("--min-training-rows", type=int, default=4)
    train_parser.add_argument("--epochs", type=int, default=1200)
    train_parser.add_argument("--learning-rate", type=float, default=0.05)
    train_parser.add_argument("--l2-penalty", type=float, default=0.01)
    train_parser.add_argument("--threshold", type=float, default=0.5)

    play_parser = subparsers.add_parser("play-test-cue", help="Play a low-volume test cue.")
    play_parser.add_argument("--frequency-hz", type=float, default=440.0)
    play_parser.add_argument("--duration-seconds", type=float, default=1.0)
    play_parser.add_argument("--volume", type=float, default=0.05)
    play_parser.add_argument("--max-volume", type=float, default=0.20)
    play_parser.add_argument("--fade-in-seconds", type=float, default=0.25)
    play_parser.add_argument("--fade-out-seconds", type=float, default=0.25)
    play_parser.add_argument("--device-name")
    play_parser.add_argument("--log-path", type=Path)
    play_parser.add_argument(
        "--calibration",
        type=Path,
        help="Volume calibration metadata .json. Uses --device-name when provided, else the latest record.",
    )
    play_parser.add_argument(
        "--backend",
        choices=("system", "afplay", "dry-run", "mock"),
        default="system",
        help="Playback backend. system uses afplay on macOS when available, else dry-run.",
    )
    play_parser.add_argument(
        "--emergency-stop",
        action="store_true",
        help="Trigger and log emergency stop instead of playing a cue.",
    )

    calibrate_parser = subparsers.add_parser(
        "calibrate-volume",
        help="Save pre-sleep volume calibration metadata for one playback device.",
    )
    calibrate_parser.add_argument("--device-name", required=True)
    calibrate_parser.add_argument("--output", type=Path, required=True, help="Output calibration .json path.")
    calibrate_parser.add_argument("--detectable-volume", type=float, required=True)
    calibrate_parser.add_argument("--identifiable-volume", type=float, required=True)
    calibrate_parser.add_argument("--comfortable-volume", type=float, required=True)
    calibrate_parser.add_argument("--cue-id", default="test-cue")
    calibrate_parser.add_argument(
        "--backend",
        choices=("system", "afplay", "dry-run", "mock"),
        default="dry-run",
    )
    calibrate_parser.add_argument("--notes", default="")
    calibrate_parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace the calibration file instead of appending/updating one device record.",
    )

    create_cues_parser = subparsers.add_parser(
        "create-cue-library",
        help="Create a starter cue metadata library.",
    )
    create_cues_parser.add_argument("--output", type=Path, required=True, help="Output cue library .json path.")

    validate_cues_parser = subparsers.add_parser(
        "validate-cue-library",
        help="Validate cue metadata and pre-session file availability.",
    )
    validate_cues_parser.add_argument("input", type=Path, help="Input cue library .json path.")
    validate_cues_parser.add_argument(
        "--skip-file-check",
        action="store_true",
        help="Validate metadata only; do not fail on missing sound cue files.",
    )

    pilot1_parser = subparsers.add_parser(
        "validate-pilot1-recording",
        help="Validate an M8 Pilot 1 no-audio overnight recording summary.",
    )
    pilot1_parser.add_argument("input", type=Path, help="Recording directory or summary.json path.")
    pilot1_parser.add_argument("--output", type=Path, help="Optional output validation report .json path.")
    pilot1_parser.add_argument("--min-duration-hours", type=float, default=6.0)
    pilot1_parser.add_argument(
        "--required-modality",
        action="append",
        dest="required_modalities",
        help="Required nonzero modality in summary.modality_counts. Repeat to override defaults.",
    )
    pilot1_parser.add_argument("--max-downtime-fraction", type=float, default=0.05)

    pilot2_parser = subparsers.add_parser(
        "validate-pilot2-calibration",
        help="Validate an M8 Pilot 2 audio calibration and cap-probe log.",
    )
    pilot2_parser.add_argument("calibration", type=Path, help="Volume calibration .json path.")
    pilot2_parser.add_argument(
        "--playback-log",
        type=Path,
        help="Dry-run play-test-cue JSONL log proving the calibration cap was used.",
    )
    pilot2_parser.add_argument("--device-name", help="Selected calibration device. Defaults to latest.")
    pilot2_parser.add_argument("--output", type=Path, help="Optional output validation report .json path.")
    pilot2_parser.add_argument("--hard-max-volume", type=float, default=0.20)

    pilot3_parser = subparsers.add_parser(
        "simulate-replay-cues",
        help="Generate an M8 Pilot 3 replay-only cue plan with mocked audio.",
    )
    pilot3_parser.add_argument("input", type=Path, help="Recording directory or raw_amused.bin path.")
    pilot3_parser.add_argument("--catalog", type=Path, required=True, help="Puzzle catalog .json path.")
    pilot3_parser.add_argument("--session", type=Path, required=True, help="Night puzzle session .json path.")
    pilot3_parser.add_argument("--assignment", type=Path, required=True, help="Cued/uncued assignment .json path.")
    pilot3_parser.add_argument("--cue-library", type=Path, required=True, help="Cue metadata library .json path.")
    pilot3_parser.add_argument("--output", type=Path, required=True, help="Output simulation report .json path.")
    pilot3_parser.add_argument("--scheduler-events-output", type=Path, help="Optional scheduler events .jsonl path.")
    pilot3_parser.add_argument("--start-seconds", type=float, help="Relative replay start offset.")
    pilot3_parser.add_argument("--end-seconds", type=float, help="Relative replay end offset.")
    pilot3_parser.add_argument("--epoch-seconds", type=float, default=30.0)
    pilot3_parser.add_argument("--stride-seconds", type=float, default=30.0)
    pilot3_parser.add_argument("--enter-threshold", type=float, default=0.70)
    pilot3_parser.add_argument("--exit-threshold", type=float, default=0.45)
    pilot3_parser.add_argument("--min-stable-seconds", type=float, default=60.0)
    pilot3_parser.add_argument("--gate-cooldown-seconds", type=float, default=120.0)
    pilot3_parser.add_argument("--puzzle-cue-interval-seconds", type=float, default=30.0)
    pilot3_parser.add_argument("--scheduler-cooldown-seconds", type=float, default=120.0)
    pilot3_parser.add_argument("--max-puzzle-cues-per-block", type=int, default=4)
    pilot3_parser.add_argument("--disable-arousal-guard", action="store_true")

    pilot4_parser = subparsers.add_parser(
        "run-pilot4-cueing",
        help="Run an M8 Pilot 4 low-volume REM-gated cueing night.",
    )
    pilot4_parser.add_argument("--source", choices=("amused", "openmuse", "sdk"), default="amused")
    pilot4_parser.add_argument("--address", help="Muse BLE address. If omitted, discovery is used.")
    pilot4_parser.add_argument("--name-filter", default="Muse")
    pilot4_parser.add_argument("--preset", default="p1034")
    pilot4_parser.add_argument("--duration-hours", type=float, default=8.0)
    pilot4_parser.add_argument("--duration-seconds", type=float)
    pilot4_parser.add_argument("--output-dir", type=Path, required=True, help="Pilot output directory.")
    pilot4_parser.add_argument("--catalog", type=Path, required=True, help="Puzzle catalog .json path.")
    pilot4_parser.add_argument("--session", type=Path, required=True, help="Night puzzle session .json path.")
    pilot4_parser.add_argument("--assignment", type=Path, required=True, help="Cued/uncued assignment .json path.")
    pilot4_parser.add_argument("--cue-library", type=Path, required=True, help="Cue metadata library .json path.")
    pilot4_parser.add_argument("--calibration", type=Path, required=True, help="Volume calibration .json path.")
    pilot4_parser.add_argument("--device-name", help="Selected calibration device. Defaults to latest.")
    pilot4_parser.add_argument(
        "--backend",
        choices=("system", "afplay", "dry-run", "mock"),
        default="dry-run",
        help="Playback backend. Use system for the actual Pilot 4 sleep run.",
    )
    pilot4_parser.add_argument("--hard-max-volume", type=float, default=0.20)
    pilot4_parser.add_argument("--default-volume", type=float, default=0.02)
    pilot4_parser.add_argument("--fade-in-seconds", type=float, default=0.25)
    pilot4_parser.add_argument("--fade-out-seconds", type=float, default=0.25)
    pilot4_parser.add_argument("--emergency-stop-file", type=Path)
    pilot4_parser.add_argument("--epoch-seconds", type=float, default=30.0)
    pilot4_parser.add_argument("--stride-seconds", type=float, default=30.0)
    pilot4_parser.add_argument("--enter-threshold", type=float, default=0.70)
    pilot4_parser.add_argument("--exit-threshold", type=float, default=0.45)
    pilot4_parser.add_argument("--min-stable-seconds", type=float, default=60.0)
    pilot4_parser.add_argument("--gate-cooldown-seconds", type=float, default=120.0)
    pilot4_parser.add_argument("--puzzle-cue-interval-seconds", type=float, default=30.0)
    pilot4_parser.add_argument("--scheduler-cooldown-seconds", type=float, default=120.0)
    pilot4_parser.add_argument("--max-puzzle-cues-per-block", type=int, default=4)
    pilot4_parser.add_argument("--allow-short", action="store_true", help="Allow short smoke-test cueing runs.")
    pilot4_parser.add_argument("--quiet", action="store_true")
    _add_openmuse_lsl_args(pilot4_parser)
    _add_muse_sdk_args(pilot4_parser)

    pilot5_parser = subparsers.add_parser(
        "run-pilot5-full-night",
        help="Run an M8 Pilot 5 full night with TLR block plus puzzle cues.",
    )
    pilot5_parser.add_argument("--source", choices=("amused", "openmuse", "sdk"), default="amused")
    pilot5_parser.add_argument("--address", help="Muse BLE address. If omitted, discovery is used.")
    pilot5_parser.add_argument("--name-filter", default="Muse")
    pilot5_parser.add_argument("--preset", default="p1034")
    pilot5_parser.add_argument("--duration-hours", type=float, default=8.0)
    pilot5_parser.add_argument("--duration-seconds", type=float)
    pilot5_parser.add_argument("--output-dir", type=Path, required=True, help="Pilot output directory.")
    pilot5_parser.add_argument("--catalog", type=Path, required=True, help="Puzzle catalog .json path.")
    pilot5_parser.add_argument("--session", type=Path, required=True, help="Night puzzle session .json path.")
    pilot5_parser.add_argument("--assignment", type=Path, required=True, help="Cued/uncued assignment .json path.")
    pilot5_parser.add_argument("--cue-library", type=Path, required=True, help="Cue metadata library .json path.")
    pilot5_parser.add_argument("--tlr-block", type=Path, required=True, help="TLR block plan .json path.")
    pilot5_parser.add_argument("--calibration", type=Path, required=True, help="Volume calibration .json path.")
    pilot5_parser.add_argument("--device-name", help="Selected calibration device. Defaults to latest.")
    pilot5_parser.add_argument(
        "--backend",
        choices=("system", "afplay", "dry-run", "mock"),
        default="dry-run",
        help="Playback backend. Use system for the actual Pilot 5 sleep run.",
    )
    pilot5_parser.add_argument("--hard-max-volume", type=float, default=0.20)
    pilot5_parser.add_argument("--default-volume", type=float, default=0.02)
    pilot5_parser.add_argument("--fade-in-seconds", type=float, default=0.25)
    pilot5_parser.add_argument("--fade-out-seconds", type=float, default=0.25)
    pilot5_parser.add_argument("--emergency-stop-file", type=Path)
    pilot5_parser.add_argument("--epoch-seconds", type=float, default=30.0)
    pilot5_parser.add_argument("--stride-seconds", type=float, default=30.0)
    pilot5_parser.add_argument("--enter-threshold", type=float, default=0.70)
    pilot5_parser.add_argument("--exit-threshold", type=float, default=0.45)
    pilot5_parser.add_argument("--min-stable-seconds", type=float, default=60.0)
    pilot5_parser.add_argument("--gate-cooldown-seconds", type=float, default=120.0)
    pilot5_parser.add_argument("--puzzle-cue-interval-seconds", type=float, default=30.0)
    pilot5_parser.add_argument("--scheduler-cooldown-seconds", type=float, default=120.0)
    pilot5_parser.add_argument("--max-puzzle-cues-per-block", type=int, default=4)
    pilot5_parser.add_argument("--allow-short", action="store_true", help="Allow short smoke-test cueing runs.")
    pilot5_parser.add_argument("--quiet", action="store_true")
    _add_openmuse_lsl_args(pilot5_parser)
    _add_muse_sdk_args(pilot5_parser)

    awakening_parser = subparsers.add_parser(
        "log-pilot4-awakening",
        help="Append a manual awakening marker to a Pilot 4 awakening_events.jsonl file.",
    )
    awakening_parser.add_argument("output", type=Path, help="awakening_events.jsonl path.")
    awakening_parser.add_argument("--event-type", default="awakening")
    awakening_parser.add_argument("--notes", default="")
    awakening_parser.add_argument("--timestamp-utc", default="")

    list_cues_parser = subparsers.add_parser("list-cues", help="List cues from a cue metadata library.")
    list_cues_parser.add_argument("input", type=Path, help="Input cue library .json path.")
    list_cues_parser.add_argument("--protocol", choices=("puzzle", "tlr", "test", "generic"))
    list_cues_parser.add_argument("--tag")

    create_tlr_parser = subparsers.add_parser(
        "create-tlr-cue",
        help="Create a default generated TLR cue library.",
    )
    create_tlr_parser.add_argument("--output", type=Path, required=True, help="Output cue library .json path.")
    create_tlr_parser.add_argument("--cue-id", default="tlr_soft_tone")
    create_tlr_parser.add_argument("--frequency-hz", type=float, default=396.0)
    create_tlr_parser.add_argument("--duration-seconds", type=float, default=1.0)
    create_tlr_parser.add_argument("--volume-hint", type=float, default=0.05)

    train_tlr_parser = subparsers.add_parser(
        "train-tlr-cue",
        help="Run pre-sleep TLR cue training and write structured events.",
    )
    train_tlr_parser.add_argument("cue_library", type=Path, help="Input TLR cue library .json path.")
    train_tlr_parser.add_argument("--cue-id", default="tlr_soft_tone")
    train_tlr_parser.add_argument("--output", type=Path, required=True, help="Output training summary .json path.")
    train_tlr_parser.add_argument("--event-log", type=Path, required=True, help="Output training events .jsonl path.")
    train_tlr_parser.add_argument("--session-id", default="tlr-training")
    train_tlr_parser.add_argument("--repetitions", type=int, default=3)
    train_tlr_parser.add_argument("--interval-seconds", type=float, default=2.0)
    train_tlr_parser.add_argument("--volume", type=float)
    train_tlr_parser.add_argument("--max-volume", type=float, default=0.20)
    train_tlr_parser.add_argument("--device-name")
    train_tlr_parser.add_argument(
        "--backend",
        choices=("system", "afplay", "dry-run", "mock"),
        default="dry-run",
    )

    plan_tlr_parser = subparsers.add_parser(
        "plan-tlr-block",
        help="Plan a configurable TLR block before REM-gated puzzle cues.",
    )
    plan_tlr_parser.add_argument("cue_library", type=Path, help="Input TLR cue library .json path.")
    plan_tlr_parser.add_argument("--cue-id", default="tlr_soft_tone")
    plan_tlr_parser.add_argument("--output", type=Path, required=True, help="Output TLR block plan .json path.")
    plan_tlr_parser.add_argument("--repetitions", type=int, default=3)
    plan_tlr_parser.add_argument("--interval-seconds", type=float, default=8.0)
    plan_tlr_parser.add_argument("--post-block-pause-seconds", type=float, default=10.0)
    plan_tlr_parser.add_argument("--disabled", action="store_true")

    import_puzzles_parser = subparsers.add_parser(
        "import-puzzles",
        help="Import puzzle tasks from .csv or .json into a versioned puzzle catalog.",
    )
    import_puzzles_parser.add_argument("input", type=Path, help="Input .csv or .json puzzle task file.")
    import_puzzles_parser.add_argument("--output", type=Path, required=True, help="Output catalog .json path.")

    generate_puzzle_session_parser = subparsers.add_parser(
        "generate-puzzle-session",
        help="Generate a pre-sleep night puzzle session from eligible unsolved tasks.",
    )
    generate_puzzle_session_parser.add_argument("catalog", type=Path, help="Input puzzle catalog .json path.")
    generate_puzzle_session_parser.add_argument("--output", type=Path, required=True, help="Output session .json path.")
    generate_puzzle_session_parser.add_argument("--session-id", required=True)
    generate_puzzle_session_parser.add_argument("--count", type=int, default=4)
    generate_puzzle_session_parser.add_argument("--seed", type=int)
    generate_puzzle_session_parser.add_argument(
        "--include-known",
        action="store_true",
        help="Allow known-but-unsolved tasks in the generated session.",
    )

    attempt_parser = subparsers.add_parser(
        "record-puzzle-attempt",
        help="Append a timed pre-sleep puzzle attempt to a puzzle catalog.",
    )
    attempt_parser.add_argument("catalog", type=Path, help="Input puzzle catalog .json path.")
    attempt_parser.add_argument("--output", type=Path, help="Output catalog .json path. Defaults to input.")
    attempt_parser.add_argument("--puzzle-id", required=True)
    attempt_parser.add_argument("--response", required=True)
    attempt_parser.add_argument("--duration-seconds", type=float, required=True)
    attempt_parser.add_argument("--solved", action="store_true")
    attempt_parser.add_argument("--known-after", action="store_true")
    attempt_parser.add_argument("--notes", default="")

    association_parser = subparsers.add_parser(
        "record-association-check",
        help="Append a cue-to-puzzle association result to a generated puzzle session.",
    )
    association_parser.add_argument("session", type=Path, help="Input night puzzle session .json path.")
    association_parser.add_argument("--catalog", type=Path, required=True, help="Puzzle catalog .json path.")
    association_parser.add_argument("--output", type=Path, help="Output session .json path. Defaults to input.")
    association_parser.add_argument("--puzzle-id", required=True)
    association_parser.add_argument("--response", required=True)
    association_parser.add_argument("--notes", default="")

    dream_report_parser = subparsers.add_parser(
        "record-dream-report",
        help="Capture a structured morning dream report for a night puzzle session.",
    )
    dream_report_parser.add_argument("session", type=Path, help="Input night puzzle session .json path.")
    dream_report_parser.add_argument("--output", type=Path, required=True, help="Output dream report .json path.")
    dream_report_parser.add_argument("--lucid", choices=("yes", "no"), required=True)
    dream_report_parser.add_argument("--cues-heard", choices=("yes", "no"), required=True)
    dream_report_parser.add_argument("--confidence", type=float, required=True, help="Self-report confidence 0.0-1.0.")
    dream_report_parser.add_argument("--dream-text", required=True, help="Free-text dream recall.")
    dream_report_parser.add_argument(
        "--puzzle-link",
        action="append",
        default=[],
        metavar="PUZZLE_ID=TEXT",
        help="Link a session puzzle to dream content. Repeat for multiple puzzles.",
    )
    dream_report_parser.add_argument("--catalog", type=Path, help="Optional puzzle catalog for cue IDs.")
    dream_report_parser.add_argument("--report-id", default="")
    dream_report_parser.add_argument("--notes", default="")

    retest_parser = subparsers.add_parser(
        "record-puzzle-retest",
        help="Capture morning puzzle retest results for a night puzzle session.",
    )
    retest_parser.add_argument("session", type=Path, help="Input night puzzle session .json path.")
    retest_parser.add_argument("--catalog", type=Path, required=True, help="Puzzle catalog .json path.")
    retest_parser.add_argument("--assignment", type=Path, required=True, help="Cued/uncued assignment .json path.")
    retest_parser.add_argument("--output", type=Path, required=True, help="Output morning retest .json path.")
    retest_parser.add_argument(
        "--result",
        action="append",
        default=[],
        metavar="PUZZLE_ID=RESPONSE",
        help="Retest response. Repeat once per session puzzle; empty response is allowed.",
    )
    retest_parser.add_argument(
        "--solved",
        action="append",
        default=[],
        metavar="PUZZLE_ID",
        help="Mark a retest puzzle as solved. Unlisted result puzzles are saved as unsolved.",
    )
    retest_parser.add_argument(
        "--duration",
        action="append",
        default=[],
        metavar="PUZZLE_ID=SECONDS",
        help="Retest duration in seconds. Repeat once per result puzzle.",
    )
    retest_parser.add_argument(
        "--confidence",
        action="append",
        default=[],
        metavar="PUZZLE_ID=0.0-1.0",
        help="Self-report confidence. Repeat once per result puzzle.",
    )
    retest_parser.add_argument(
        "--note",
        action="append",
        default=[],
        metavar="PUZZLE_ID=TEXT",
        help="Optional per-puzzle retest note.",
    )
    retest_parser.add_argument("--retest-id", default="")
    retest_parser.add_argument("--notes", default="")

    analysis_parser = subparsers.add_parser(
        "analyze-cued-uncued",
        help="Generate a cued-vs-uncued morning analysis report.",
    )
    analysis_parser.add_argument("session", type=Path, help="Input night puzzle session .json path.")
    analysis_parser.add_argument("--assignment", type=Path, required=True, help="Cued/uncued assignment .json path.")
    analysis_parser.add_argument("--retest", type=Path, required=True, help="Morning puzzle retest .json path.")
    analysis_parser.add_argument("--output", type=Path, required=True, help="Output analysis report .json path.")
    analysis_parser.add_argument("--dream-report", type=Path, help="Optional morning dream report .json path.")
    analysis_parser.add_argument("--scheduler-events", type=Path, help="Optional TMR scheduler events .jsonl path.")
    analysis_parser.add_argument("--markdown-output", type=Path, help="Optional human-readable .md report path.")
    analysis_parser.add_argument("--analysis-id", default="")
    analysis_parser.add_argument("--min-group-size", type=int, default=5)

    assignment_parser = subparsers.add_parser(
        "assign-puzzle-cues",
        help="Randomize a night puzzle session into cued and uncued groups.",
    )
    assignment_parser.add_argument("session", type=Path, help="Input night puzzle session .json path.")
    assignment_parser.add_argument("--output", type=Path, required=True, help="Output cue assignment .json path.")
    assignment_parser.add_argument("--seed", type=int, required=True)
    assignment_parser.add_argument(
        "--cued-count",
        type=int,
        help="Override the number of cued puzzles. Defaults to half of the session tasks.",
    )

    record_parser = subparsers.add_parser("record", help="Record an overnight Muse session.")
    record_parser.add_argument("--source", choices=("amused", "openmuse", "sdk"), default="amused")
    record_parser.add_argument("--address", help="Muse BLE address. If omitted, discovery is used.")
    record_parser.add_argument("--name-filter", default="Muse")
    record_parser.add_argument("--preset", default="p1034")
    record_parser.add_argument("--duration-hours", type=float, default=8.0)
    record_parser.add_argument("--duration-seconds", type=float)
    record_parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Recording directory. Relative paths resolve under the current working "
            "directory, or under the project checkout when launched via macOS Python.app."
        ),
    )
    record_parser.add_argument("--allow-short", action="store_true", help="Allow short smoke-test recordings.")
    record_parser.add_argument("--quiet", action="store_true")
    _add_openmuse_lsl_args(record_parser)
    _add_muse_sdk_args(record_parser)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        print("Muse REM-TMR project scaffold is installed.")
        return 0
    if args.command == "app":
        return _run_app(args)
    if args.command == "discover":
        return asyncio.run(_discover(args))
    if args.command == "stream":
        return asyncio.run(_stream(args))
    if args.command == "replay":
        return asyncio.run(_replay(args))
    if args.command == "annotate-template":
        return asyncio.run(_annotate_template(args))
    if args.command == "train-rem-classifier":
        return _train_rem_classifier(args)
    if args.command == "play-test-cue":
        return _play_test_cue(args)
    if args.command == "calibrate-volume":
        return _calibrate_volume(args)
    if args.command == "create-cue-library":
        return _create_cue_library(args)
    if args.command == "validate-cue-library":
        return _validate_cue_library(args)
    if args.command == "validate-pilot1-recording":
        return _validate_pilot1_recording(args)
    if args.command == "validate-pilot2-calibration":
        return _validate_pilot2_calibration(args)
    if args.command == "simulate-replay-cues":
        return asyncio.run(_simulate_replay_cues(args))
    if args.command == "run-pilot4-cueing":
        return asyncio.run(_run_pilot4_cueing(args))
    if args.command == "run-pilot5-full-night":
        return asyncio.run(_run_pilot5_full_night(args))
    if args.command == "log-pilot4-awakening":
        return _log_pilot4_awakening(args)
    if args.command == "list-cues":
        return _list_cues(args)
    if args.command == "create-tlr-cue":
        return _create_tlr_cue(args)
    if args.command == "train-tlr-cue":
        return _train_tlr_cue(args)
    if args.command == "plan-tlr-block":
        return _plan_tlr_block(args)
    if args.command == "import-puzzles":
        return _import_puzzles(args)
    if args.command == "generate-puzzle-session":
        return _generate_puzzle_session(args)
    if args.command == "record-puzzle-attempt":
        return _record_puzzle_attempt(args)
    if args.command == "record-association-check":
        return _record_association_check(args)
    if args.command == "record-dream-report":
        return _record_dream_report(args)
    if args.command == "record-puzzle-retest":
        return _record_puzzle_retest(args)
    if args.command == "analyze-cued-uncued":
        return _analyze_cued_uncued(args)
    if args.command == "assign-puzzle-cues":
        return _assign_puzzle_cues(args)
    if args.command == "record":
        return asyncio.run(_record(args))

    parser.print_help()
    return 0


def _run_app(args: argparse.Namespace) -> int:
    from muse_tmr.app import AppConfig, run_local_app

    return run_local_app(
        AppConfig(
            host=args.host,
            port=args.port,
            source=args.source,
            address=args.address,
            name_filter=args.name_filter,
            preset=args.preset,
            mock_scenario=args.mock_scenario,
            mock_interval_seconds=args.mock_interval_seconds,
            gate_stability_seconds=args.contact_stability_seconds,
        )
    )


async def _discover(args: argparse.Namespace) -> int:
    source = _build_source(args, duration_seconds=0)
    devices = await source.discover()
    for device in devices:
        print(f"{device.name}\t{device.address}\trssi={device.rssi}")
    return 0 if devices else 1


async def _stream(args: argparse.Namespace) -> int:
    source = _build_source(args, duration_seconds=args.duration_seconds)
    metadata = await source.connect()
    frame_count = 0
    modality_counts = {}
    try:
        async for frame in source.stream():
            frame_count += 1
            for modality in frame.modalities():
                modality_counts[modality] = modality_counts.get(modality, 0) + 1
    finally:
        await source.stop()

    print(
        f"stream complete source={metadata.source_name} "
        f"device={metadata.device_name} frames={frame_count} modalities={modality_counts}"
    )
    return 0


async def _replay(args: argparse.Namespace) -> int:
    from muse_tmr.data.replay import ReplayConfig, ReplaySession

    session = ReplaySession(
        ReplayConfig(
            input_path=args.input,
            speed=args.speed,
            start_seconds=args.start_seconds,
            end_seconds=args.end_seconds,
        )
    )
    metadata = await session.connect()
    frame_count = 0
    modality_counts = {}
    try:
        async for frame in session.stream():
            frame_count += 1
            for modality in frame.modalities():
                modality_counts[modality] = modality_counts.get(modality, 0) + 1
    finally:
        await session.stop()

    print(
        f"replay complete source={metadata.source_name} "
        f"input={session.raw_path} frames={frame_count} modalities={modality_counts}"
    )
    return 0


async def _record(args: argparse.Namespace) -> int:
    from muse_tmr.data.recorder import OvernightRecorder, RecordingConfig

    duration_seconds = (
        args.duration_seconds
        if args.duration_seconds is not None
        else args.duration_hours * 3600
    )
    output_dir = _resolve_output_dir(args.output_dir) if args.output_dir else _default_recording_dir()
    source = _build_source(args, duration_seconds=0)
    recorder = OvernightRecorder(
        RecordingConfig(
            output_dir=output_dir,
            duration_seconds=duration_seconds,
            source_name=args.source,
            allow_short=args.allow_short,
        )
    )
    summary = await recorder.record(source)
    print(f"recording complete summary={summary.summary_path}")
    return 0


async def _annotate_template(args: argparse.Namespace) -> int:
    from muse_tmr.annotations import build_rem_annotation_rows, export_rem_annotations
    from muse_tmr.data.replay import ReplayConfig, ReplaySession
    from muse_tmr.features.epochs import EpochBuilder, EpochConfig
    from muse_tmr.models import HeuristicRemDetector

    session = ReplaySession(
        ReplayConfig(
            input_path=args.input,
            speed=0.0,
            start_seconds=args.start_seconds,
            end_seconds=args.end_seconds,
        )
    )
    await session.connect()
    try:
        builder = EpochBuilder(
            EpochConfig(
                epoch_seconds=args.epoch_seconds,
                stride_seconds=args.stride_seconds,
            )
        )
        epochs = [epoch async for epoch in builder.build(session.stream())]
    finally:
        await session.stop()

    rows = build_rem_annotation_rows(
        epochs,
        detector=HeuristicRemDetector(),
        recording_id=str(session.recording_dir),
        label=args.label,
    )
    output_path = export_rem_annotations(rows, _resolve_output_path(args.output))
    print(f"annotation template complete rows={len(rows)} output={output_path}")
    return 0


def _train_rem_classifier(args: argparse.Namespace) -> int:
    from muse_tmr.annotations import load_rem_annotations
    from muse_tmr.models import (
        DEFAULT_PERSONAL_REM_FEATURES,
        PersonalRemClassifierConfig,
        train_personal_rem_classifier,
    )

    annotations = load_rem_annotations(_resolve_output_path(args.annotations))
    feature_names = tuple(args.features) if args.features else DEFAULT_PERSONAL_REM_FEATURES
    config = PersonalRemClassifierConfig(
        feature_names=feature_names,
        learning_rate=args.learning_rate,
        epochs=args.epochs,
        l2_penalty=args.l2_penalty,
        decision_threshold=args.threshold,
        min_training_rows=args.min_training_rows,
    )
    model = train_personal_rem_classifier(annotations, config=config)
    output_path = model.save(_resolve_output_path(args.output))
    summary = model.training_summary
    metrics = summary.metrics if summary is not None else {}
    group_metrics = summary.group_holdout_metrics if summary is not None else {}
    print(
        "personal REM classifier trained "
        f"rows={summary.training_rows if summary else 0} "
        f"positive={summary.positive_rows if summary else 0} "
        f"negative={summary.negative_rows if summary else 0} "
        f"skipped_unknown={summary.skipped_unknown_rows if summary else 0} "
        f"accuracy={metrics.get('accuracy', 'nan')} "
        f"balanced_accuracy={metrics.get('balanced_accuracy', 'nan')} "
        f"brier={metrics.get('brier_score', 'nan')} "
        f"group_holdout={group_metrics.get('status', 'nan')} "
        f"output={output_path}"
    )
    return 0


def _play_test_cue(args: argparse.Namespace) -> int:
    from muse_tmr.audio import (
        AudioCuePlayer,
        AudioPlaybackConfig,
        TestCue,
        audio_config_with_calibration,
        create_audio_backend,
        load_volume_calibrations,
    )

    config = AudioPlaybackConfig(
        max_volume=args.max_volume,
        default_volume=args.volume,
        fade_in_seconds=args.fade_in_seconds,
        fade_out_seconds=args.fade_out_seconds,
        device_name=args.device_name,
        log_path=_resolve_output_path(args.log_path) if args.log_path else None,
    )
    if args.calibration:
        try:
            store = load_volume_calibrations(_resolve_output_path(args.calibration))
            calibration = (
                store.latest_for_device(args.device_name)
                if args.device_name
                else store.latest()
            )
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"volume calibration error: {exc}", file=sys.stderr)
            return 1
        config = audio_config_with_calibration(config, calibration)

    player = AudioCuePlayer(config, backend=create_audio_backend(args.backend))
    if args.emergency_stop:
        result = player.emergency_stop()
    else:
        result = player.play_test_cue(
            TestCue(
                cue_id="test-cue",
                frequency_hz=args.frequency_hz,
                duration_seconds=args.duration_seconds,
            ),
            volume=args.volume,
        )
    print(
        "test cue "
        f"status={result.status} "
        f"backend={result.backend_name} "
        f"volume={result.effective_volume} "
        f"requested_volume={result.requested_volume} "
        f"volume_capped={result.volume_capped} "
        f"reasons={','.join(result.reason_codes)}"
    )
    return 0 if result.status in {"played", "stopped", "skipped"} else 1


def _calibrate_volume(args: argparse.Namespace) -> int:
    from muse_tmr.audio import VolumeCalibration, save_volume_calibration

    calibration = VolumeCalibration(
        device_name=args.device_name,
        detectable_volume=args.detectable_volume,
        identifiable_volume=args.identifiable_volume,
        comfortable_volume=args.comfortable_volume,
        cue_id=args.cue_id,
        backend_name=args.backend,
        notes=args.notes,
    )
    output_path = save_volume_calibration(
        calibration,
        _resolve_output_path(args.output),
        append=not args.replace,
    )
    print(
        "volume calibration saved "
        f"device={calibration.device_name} "
        f"detectable={calibration.detectable_volume} "
        f"identifiable={calibration.identifiable_volume} "
        f"comfortable={calibration.comfortable_volume} "
        f"scheduler_max={calibration.scheduler_max_volume} "
        f"output={output_path}"
    )
    return 0


def _create_cue_library(args: argparse.Namespace) -> int:
    from muse_tmr.audio import default_cue_library, export_cue_library

    output_path = export_cue_library(default_cue_library(), _resolve_output_path(args.output))
    print(f"cue library created output={output_path}")
    return 0


def _validate_cue_library(args: argparse.Namespace) -> int:
    import json

    from muse_tmr.audio import validate_cue_library_file

    input_path = _resolve_output_path(args.input)
    report = validate_cue_library_file(
        input_path,
        check_files=not args.skip_file_check,
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.is_valid else 1


def _validate_pilot1_recording(args: argparse.Namespace) -> int:
    import json

    from muse_tmr.validation import (
        DEFAULT_PILOT1_REQUIRED_MODALITIES,
        validate_pilot1_recording,
    )

    required_modalities = (
        tuple(args.required_modalities)
        if args.required_modalities
        else DEFAULT_PILOT1_REQUIRED_MODALITIES
    )
    report = validate_pilot1_recording(
        _resolve_output_path(args.input),
        min_duration_seconds=args.min_duration_hours * 3600,
        required_modalities=required_modalities,
        max_downtime_fraction=args.max_downtime_fraction,
    )
    if args.output is not None:
        report.save(_resolve_output_path(args.output))
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


def _validate_pilot2_calibration(args: argparse.Namespace) -> int:
    import json

    from muse_tmr.validation import validate_pilot2_calibration

    report = validate_pilot2_calibration(
        _resolve_output_path(args.calibration),
        device_name=args.device_name,
        playback_log_path=(
            _resolve_output_path(args.playback_log)
            if args.playback_log is not None
            else None
        ),
        hard_max_volume=args.hard_max_volume,
    )
    if args.output is not None:
        report.save(_resolve_output_path(args.output))
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


async def _simulate_replay_cues(args: argparse.Namespace) -> int:
    from muse_tmr.audio import load_cue_library
    from muse_tmr.features import EpochConfig
    from muse_tmr.models import RemGateConfig
    from muse_tmr.protocol import (
        TmrSchedulerConfig,
        load_night_puzzle_session,
        load_puzzle_catalog,
        load_puzzle_cue_assignment,
    )
    from muse_tmr.protocol.arousal_guard import ArousalGuardConfig
    from muse_tmr.validation import simulate_replay_cue_plan

    report = await simulate_replay_cue_plan(
        _resolve_output_path(args.input),
        catalog=load_puzzle_catalog(_resolve_output_path(args.catalog)),
        session=load_night_puzzle_session(_resolve_output_path(args.session)),
        assignment=load_puzzle_cue_assignment(_resolve_output_path(args.assignment)),
        cue_library=load_cue_library(_resolve_output_path(args.cue_library)),
        start_seconds=args.start_seconds,
        end_seconds=args.end_seconds,
        epoch_config=EpochConfig(
            epoch_seconds=args.epoch_seconds,
            stride_seconds=args.stride_seconds,
        ),
        gate_config=RemGateConfig(
            enter_threshold=args.enter_threshold,
            exit_threshold=args.exit_threshold,
            min_stable_seconds=args.min_stable_seconds,
            epoch_seconds=args.epoch_seconds,
            cooldown_seconds=args.gate_cooldown_seconds,
        ),
        scheduler_config=TmrSchedulerConfig(
            puzzle_cue_interval_seconds=args.puzzle_cue_interval_seconds,
            cooldown_seconds=args.scheduler_cooldown_seconds,
            max_puzzle_cues_per_block=args.max_puzzle_cues_per_block,
            enable_tlr_block=False,
        ),
        arousal_guard_config=ArousalGuardConfig(enabled=not args.disable_arousal_guard),
    )
    output_path = report.save(_resolve_output_path(args.output))
    scheduler_events_output = None
    if args.scheduler_events_output is not None:
        scheduler_events_output = report.save_scheduler_events(
            _resolve_output_path(args.scheduler_events_output)
        )

    print(
        "pilot3 replay cue simulation complete "
        f"passed={report.passed} "
        f"epochs={report.metrics.get('epoch_count', 0)} "
        f"gate_open={report.metrics.get('gate_open_count', 0)} "
        f"cue_plan={report.metrics.get('cue_plan_count', 0)} "
        f"audio_playback_executed={report.audio_playback_executed} "
        f"output={output_path}"
    )
    if scheduler_events_output is not None:
        print(f"scheduler_events={scheduler_events_output}")
    return 0 if report.passed else 1


async def _run_pilot4_cueing(args: argparse.Namespace) -> int:
    return await _run_live_cueing_pilot(
        args,
        command_label="pilot4 cueing",
        pilot_id="m8_pilot4_low_volume_rem_gated_cueing",
        summary_filename="pilot4_summary.json",
        enable_tlr_block=False,
        require_tlr_block=False,
    )


async def _run_pilot5_full_night(args: argparse.Namespace) -> int:
    return await _run_live_cueing_pilot(
        args,
        command_label="pilot5 full-night",
        pilot_id="m8_pilot5_full_night_tlr_puzzle_cueing",
        summary_filename="pilot5_summary.json",
        enable_tlr_block=True,
        require_tlr_block=True,
    )


async def _run_live_cueing_pilot(
    args: argparse.Namespace,
    *,
    command_label: str,
    pilot_id: str,
    summary_filename: str,
    enable_tlr_block: bool,
    require_tlr_block: bool,
) -> int:
    from muse_tmr.audio import load_cue_library, load_volume_calibrations
    from muse_tmr.features import EpochConfig
    from muse_tmr.models import RemGateConfig
    from muse_tmr.protocol import (
        TmrSchedulerConfig,
        load_night_puzzle_session,
        load_puzzle_catalog,
        load_puzzle_cue_assignment,
        load_tlr_block_plan,
    )
    from muse_tmr.protocol.arousal_guard import ArousalGuardConfig
    from muse_tmr.validation import Pilot4CueingConfig, run_pilot4_cueing_night

    duration_seconds = (
        args.duration_seconds
        if args.duration_seconds is not None
        else args.duration_hours * 3600
    )
    store = load_volume_calibrations(_resolve_output_path(args.calibration))
    calibration = (
        store.latest_for_device(args.device_name)
        if args.device_name is not None
        else store.latest()
    )
    output_dir = _resolve_output_dir(args.output_dir)
    config = Pilot4CueingConfig(
        output_dir=output_dir,
        duration_seconds=duration_seconds,
        source_name=args.source,
        allow_short=args.allow_short,
        hard_max_volume=args.hard_max_volume,
        default_volume=args.default_volume,
        fade_in_seconds=args.fade_in_seconds,
        fade_out_seconds=args.fade_out_seconds,
        audio_backend_name=args.backend,
        emergency_stop_path=(
            _resolve_output_path(args.emergency_stop_file)
            if args.emergency_stop_file is not None
            else None
        ),
        epoch_config=EpochConfig(
            epoch_seconds=args.epoch_seconds,
            stride_seconds=args.stride_seconds,
        ),
        gate_config=RemGateConfig(
            enter_threshold=args.enter_threshold,
            exit_threshold=args.exit_threshold,
            min_stable_seconds=args.min_stable_seconds,
            epoch_seconds=args.epoch_seconds,
            cooldown_seconds=args.gate_cooldown_seconds,
        ),
        scheduler_config=TmrSchedulerConfig(
            puzzle_cue_interval_seconds=args.puzzle_cue_interval_seconds,
            cooldown_seconds=args.scheduler_cooldown_seconds,
            max_puzzle_cues_per_block=args.max_puzzle_cues_per_block,
            enable_tlr_block=enable_tlr_block,
        ),
        arousal_guard_config=ArousalGuardConfig(),
        pilot_id=pilot_id,
        summary_filename=summary_filename,
        require_tlr_block=require_tlr_block,
    )
    tlr_block_plan = (
        load_tlr_block_plan(_resolve_output_path(args.tlr_block))
        if enable_tlr_block
        else None
    )
    source = _build_source(args, duration_seconds=int(duration_seconds))
    summary = await run_pilot4_cueing_night(
        source,
        config=config,
        catalog=load_puzzle_catalog(_resolve_output_path(args.catalog)),
        session=load_night_puzzle_session(_resolve_output_path(args.session)),
        assignment=load_puzzle_cue_assignment(_resolve_output_path(args.assignment)),
        cue_library=load_cue_library(_resolve_output_path(args.cue_library)),
        calibration=calibration,
        tlr_block_plan=tlr_block_plan,
    )
    print(
        f"{command_label} complete "
        f"passed={summary.passed} "
        f"epochs={summary.epoch_count} "
        f"scheduler_play={summary.cue_play_count} "
        f"tlr_play={summary.tlr_cue_play_count} "
        f"puzzle_play={summary.puzzle_cue_play_count} "
        f"audio_status={dict(summary.audio_status_counts)} "
        f"max_effective_volume={summary.max_effective_volume} "
        f"emergency_stop={summary.emergency_stop_path} "
        f"summary={summary.summary_path}"
    )
    return 0 if summary.passed else 1


def _log_pilot4_awakening(args: argparse.Namespace) -> int:
    from muse_tmr.validation import AwakeningEvent, append_awakening_event

    output_path = append_awakening_event(
        _resolve_output_path(args.output),
        AwakeningEvent(
            event_type=args.event_type,
            timestamp_utc=args.timestamp_utc,
            notes=args.notes,
        ),
    )
    print(f"awakening event logged output={output_path}")
    return 0


def _list_cues(args: argparse.Namespace) -> int:
    from muse_tmr.audio import load_cue_library

    library = load_cue_library(_resolve_output_path(args.input))
    cues = library.filter(protocol=args.protocol, tag=args.tag)
    for cue in cues:
        print(
            f"{cue.cue_id}\t{cue.cue_type}\t{cue.protocol}\t"
            f"{cue.duration_seconds}s\ttags={','.join(cue.tags)}"
        )
    return 0


def _create_tlr_cue(args: argparse.Namespace) -> int:
    from muse_tmr.protocol import TlrCueConfig, default_tlr_cue_library

    library = default_tlr_cue_library(
        TlrCueConfig(
            cue_id=args.cue_id,
            frequency_hz=args.frequency_hz,
            duration_seconds=args.duration_seconds,
            volume_hint=args.volume_hint,
        )
    )
    output_path = library.save(_resolve_output_path(args.output))
    cue = library.cues[0]
    print(
        "TLR cue created "
        f"cue={cue.cue_id} "
        f"frequency_hz={cue.frequency_hz} "
        f"duration_seconds={cue.duration_seconds} "
        f"volume_hint={cue.volume_hint} "
        f"output={output_path}"
    )
    return 0


def _train_tlr_cue(args: argparse.Namespace) -> int:
    from muse_tmr.audio import AudioCuePlayer, AudioPlaybackConfig, create_audio_backend, load_cue_library
    from muse_tmr.protocol import TlrTrainingConfig, train_tlr_cue

    library = load_cue_library(_resolve_output_path(args.cue_library))
    cue = library.by_id(args.cue_id)
    default_volume = args.volume if args.volume is not None else (cue.volume_hint or 0.05)
    player = AudioCuePlayer(
        AudioPlaybackConfig(
            max_volume=args.max_volume,
            default_volume=default_volume,
            device_name=args.device_name,
        ),
        backend=create_audio_backend(args.backend),
    )
    session = train_tlr_cue(
        cue,
        player,
        config=TlrTrainingConfig(
            repetitions=args.repetitions,
            interval_seconds=args.interval_seconds,
            volume=args.volume,
            backend_name=args.backend,
        ),
        session_id=args.session_id,
        event_log_path=_resolve_output_path(args.event_log),
    )
    output_path = session.save(_resolve_output_path(args.output))
    print(
        "TLR training complete "
        f"session={session.session_id} "
        f"cue={session.cue_id} "
        f"events={session.event_count} "
        f"output={output_path} "
        f"event_log={_resolve_output_path(args.event_log)}"
    )
    return 0


def _plan_tlr_block(args: argparse.Namespace) -> int:
    from muse_tmr.audio import load_cue_library
    from muse_tmr.protocol import TlrBlockConfig, plan_tlr_block

    library = load_cue_library(_resolve_output_path(args.cue_library))
    cue = library.by_id(args.cue_id)
    plan = plan_tlr_block(
        cue,
        config=TlrBlockConfig(
            enabled=not args.disabled,
            repetitions=args.repetitions,
            interval_seconds=args.interval_seconds,
            post_block_pause_seconds=args.post_block_pause_seconds,
        ),
    )
    output_path = plan.save(_resolve_output_path(args.output))
    print(
        "TLR block planned "
        f"cue={plan.cue_id} "
        f"events={len(plan.events)} "
        f"puzzle_start_offset={plan.puzzle_cue_start_offset_seconds} "
        f"output={output_path}"
    )
    return 0


def _import_puzzles(args: argparse.Namespace) -> int:
    from muse_tmr.protocol import import_puzzle_file

    catalog = import_puzzle_file(_resolve_output_path(args.input))
    output_path = catalog.save(_resolve_output_path(args.output))
    print(f"puzzle catalog imported puzzles={catalog.puzzle_count} output={output_path}")
    return 0


def _generate_puzzle_session(args: argparse.Namespace) -> int:
    from muse_tmr.protocol import load_puzzle_catalog

    catalog = load_puzzle_catalog(_resolve_output_path(args.catalog))
    session = catalog.generate_night_session(
        session_id=args.session_id,
        puzzle_count=args.count,
        selection_seed=args.seed,
        include_known=args.include_known,
    )
    output_path = session.save(_resolve_output_path(args.output))
    print(
        "puzzle session generated "
        f"session={session.session_id} "
        f"puzzles={len(session.puzzle_ids)} "
        f"eligible={session.metadata.get('eligible_count')} "
        f"output={output_path}"
    )
    return 0


def _record_puzzle_attempt(args: argparse.Namespace) -> int:
    from muse_tmr.protocol import PuzzleAttempt, load_puzzle_catalog

    input_path = _resolve_output_path(args.catalog)
    output_path = _resolve_output_path(args.output) if args.output else input_path
    catalog = load_puzzle_catalog(input_path)
    attempt = PuzzleAttempt(
        puzzle_id=args.puzzle_id,
        response=args.response,
        duration_seconds=args.duration_seconds,
        solved=args.solved,
        known_after=args.known_after,
        notes=args.notes,
    )
    updated = catalog.with_attempt(attempt)
    updated.save(output_path)
    print(
        "puzzle attempt recorded "
        f"puzzle={attempt.puzzle_id} "
        f"duration_seconds={attempt.duration_seconds} "
        f"solved={attempt.solved} "
        f"known_after={attempt.known_after} "
        f"output={output_path}"
    )
    return 0


def _record_association_check(args: argparse.Namespace) -> int:
    from muse_tmr.protocol import load_night_puzzle_session, load_puzzle_catalog

    input_path = _resolve_output_path(args.session)
    output_path = _resolve_output_path(args.output) if args.output else input_path
    catalog = load_puzzle_catalog(_resolve_output_path(args.catalog))
    session = load_night_puzzle_session(input_path)
    result = catalog.check_association(
        args.puzzle_id,
        args.response,
        notes=args.notes,
    )
    updated = session.with_association_result(result)
    updated.save(output_path)
    print(
        "association check recorded "
        f"session={updated.session_id} "
        f"puzzle={result.puzzle_id} "
        f"matched={result.matched} "
        f"output={output_path}"
    )
    return 0


def _record_dream_report(args: argparse.Namespace) -> int:
    from muse_tmr.protocol import load_night_puzzle_session, load_puzzle_catalog
    from muse_tmr.reports import build_dream_report

    session = load_night_puzzle_session(_resolve_output_path(args.session))
    catalog = (
        load_puzzle_catalog(_resolve_output_path(args.catalog))
        if args.catalog is not None
        else None
    )
    report = build_dream_report(
        session,
        catalog=catalog,
        report_id=args.report_id,
        lucid=_yes_no(args.lucid),
        cues_heard=_yes_no(args.cues_heard),
        confidence=args.confidence,
        dream_text=args.dream_text,
        puzzle_incorporation_text=_parse_puzzle_links(args.puzzle_link),
        notes=args.notes,
    )
    output_path = report.save(_resolve_output_path(args.output))
    print(
        "dream report recorded "
        f"session={report.session_id} "
        f"lucid={report.lucid} "
        f"cues_heard={report.cues_heard} "
        f"linked_puzzles={report.puzzle_incorporation_count} "
        f"output={output_path}"
    )
    return 0


def _record_puzzle_retest(args: argparse.Namespace) -> int:
    from muse_tmr.protocol import (
        load_night_puzzle_session,
        load_puzzle_catalog,
        load_puzzle_cue_assignment,
    )
    from muse_tmr.reports import MorningRetestResult, build_morning_retest

    session = load_night_puzzle_session(_resolve_output_path(args.session))
    catalog = load_puzzle_catalog(_resolve_output_path(args.catalog))
    assignment = load_puzzle_cue_assignment(_resolve_output_path(args.assignment))
    responses = _parse_key_values(args.result, "--result", allow_empty_value=True)
    durations = _parse_float_key_values(args.duration, "--duration")
    confidences = _parse_float_key_values(args.confidence, "--confidence")
    notes = _parse_key_values(args.note, "--note", allow_empty_value=True)

    result_ids = set(responses)
    if not result_ids:
        raise ValueError("record-puzzle-retest requires at least one --result")
    solved_ids = set(args.solved)
    extra_solved = tuple(sorted(solved_ids - result_ids))
    if extra_solved:
        raise ValueError(f"--solved references puzzles without --result: {extra_solved}")
    _require_matching_keys("--duration", durations, result_ids)
    _require_matching_keys("--confidence", confidences, result_ids)

    results = tuple(
        MorningRetestResult(
            puzzle_id=puzzle_id,
            response=response,
            solved=puzzle_id in solved_ids,
            duration_seconds=durations[puzzle_id],
            confidence=confidences[puzzle_id],
            notes=notes.get(puzzle_id, ""),
        )
        for puzzle_id, response in responses.items()
    )
    retest = build_morning_retest(
        session,
        results,
        catalog=catalog,
        assignment=assignment,
        retest_id=args.retest_id,
        notes=args.notes,
    )
    output_path = retest.save(_resolve_output_path(args.output))
    print(
        "morning puzzle retest recorded "
        f"session={retest.session_id} "
        f"results={len(retest.results)} "
        f"solved={retest.solved_count} "
        f"unsolved={retest.unsolved_count} "
        f"output={output_path}"
    )
    return 0


def _analyze_cued_uncued(args: argparse.Namespace) -> int:
    from muse_tmr.protocol import (
        load_night_puzzle_session,
        load_puzzle_cue_assignment,
        load_tmr_scheduler_events,
    )
    from muse_tmr.reports import (
        build_cued_uncued_analysis,
        load_dream_report,
        load_morning_retest,
    )

    session = load_night_puzzle_session(_resolve_output_path(args.session))
    assignment = load_puzzle_cue_assignment(_resolve_output_path(args.assignment))
    retest = load_morning_retest(_resolve_output_path(args.retest))
    dream_report = (
        load_dream_report(_resolve_output_path(args.dream_report))
        if args.dream_report is not None
        else None
    )
    scheduler_events = (
        load_tmr_scheduler_events(_resolve_output_path(args.scheduler_events))
        if args.scheduler_events is not None
        else ()
    )
    report = build_cued_uncued_analysis(
        session,
        assignment,
        retest,
        dream_report=dream_report,
        scheduler_events=scheduler_events,
        analysis_id=args.analysis_id,
        min_group_size=args.min_group_size,
    )
    output_path = report.save(_resolve_output_path(args.output))
    markdown_path = None
    if args.markdown_output is not None:
        markdown_path = report.save_markdown(_resolve_output_path(args.markdown_output))

    print(
        "cued-vs-uncued analysis complete "
        f"session={report.session_id} "
        f"rows={len(report.rows)} "
        f"limitations={','.join(report.limitation_codes)} "
        f"output={output_path}"
        + (f" markdown={markdown_path}" if markdown_path is not None else "")
    )
    return 0


def _assign_puzzle_cues(args: argparse.Namespace) -> int:
    from muse_tmr.protocol import assign_cued_uncued_puzzles, load_night_puzzle_session

    session = load_night_puzzle_session(_resolve_output_path(args.session))
    assignment = assign_cued_uncued_puzzles(
        session,
        seed=args.seed,
        cued_count=args.cued_count,
    )
    output_path = assignment.save(_resolve_output_path(args.output))
    print(
        "puzzle cue assignment generated "
        f"session={assignment.session_id} "
        f"seed={assignment.seed} "
        f"cued={len(assignment.cued_puzzle_ids)} "
        f"uncued={len(assignment.uncued_puzzle_ids)} "
        f"scheduled={len(assignment.scheduled_puzzle_ids)} "
        f"output={output_path}"
    )
    return 0


def _parse_puzzle_links(values: Sequence[str]) -> dict:
    return _parse_key_values(values, "--puzzle-link", allow_empty_value=False)


def _parse_key_values(
    values: Sequence[str],
    option_name: str,
    *,
    allow_empty_value: bool = False,
) -> dict:
    parsed = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option_name} must use PUZZLE_ID=VALUE")
        puzzle_id, text = value.split("=", 1)
        puzzle_id = puzzle_id.strip()
        text = text.strip()
        if not puzzle_id or (not text and not allow_empty_value):
            raise ValueError(f"{option_name} must include non-empty puzzle ID and value")
        if puzzle_id in parsed:
            raise ValueError(f"duplicate {option_name} for puzzle_id={puzzle_id}")
        parsed[puzzle_id] = text
    return parsed


def _parse_float_key_values(values: Sequence[str], option_name: str) -> dict:
    parsed = _parse_key_values(values, option_name, allow_empty_value=False)
    return {key: float(value) for key, value in parsed.items()}


def _require_matching_keys(option_name: str, values: Mapping[str, object], expected_keys: set) -> None:
    missing = tuple(sorted(expected_keys - set(values)))
    extra = tuple(sorted(set(values) - expected_keys))
    if missing or extra:
        raise ValueError(f"{option_name} keys must match --result keys: missing={missing} extra={extra}")


def _yes_no(value: str) -> bool:
    return value == "yes"


def _build_source(args: argparse.Namespace, duration_seconds: int):
    if getattr(args, "source", "amused") == "sdk":
        from muse_tmr.sources.muse_sdk_source_stub import MuseSdkSourceConfig, MuseSdkSourceStub

        return MuseSdkSourceStub(
            MuseSdkSourceConfig(
                sdk_path=getattr(args, "sdk_path", None),
                metadata={"duration_seconds": str(duration_seconds)},
            )
        )

    if getattr(args, "source", "amused") == "openmuse":
        from muse_tmr.sources.openmuse_lsl_source import OpenMuseLslConfig, OpenMuseLslSource

        return OpenMuseLslSource(
            OpenMuseLslConfig(
                stream_names=_openmuse_stream_names(args),
                required_modalities=tuple(getattr(args, "require_lsl_stream", ()) or ()),
                resolve_timeout_seconds=getattr(args, "lsl_resolve_timeout", 5.0),
                pull_timeout_seconds=getattr(args, "lsl_pull_timeout", 0.0),
                poll_interval_seconds=getattr(args, "lsl_poll_interval", 0.01),
                duration_seconds=duration_seconds,
            )
        )

    from muse_tmr.sources.amused_source import AmusedSource

    return AmusedSource(
        address=getattr(args, "address", None),
        name_filter=getattr(args, "name_filter", "Muse"),
        preset=getattr(args, "preset", "p1034"),
        duration_seconds=duration_seconds,
        verbose=not getattr(args, "quiet", False),
    )


def _add_openmuse_lsl_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lsl-resolve-timeout", type=float, default=5.0)
    parser.add_argument("--lsl-pull-timeout", type=float, default=0.0)
    parser.add_argument("--lsl-poll-interval", type=float, default=0.01)
    parser.add_argument(
        "--require-lsl-stream",
        action="append",
        choices=("eeg", "imu", "ppg", "heart_rate", "battery"),
        default=[],
        help="Require an OpenMuse LSL modality before connect succeeds. Repeat as needed.",
    )
    parser.add_argument("--openmuse-eeg-stream", default="Muse_EEG")
    parser.add_argument("--openmuse-imu-stream", default="Muse_ACCGYRO")
    parser.add_argument("--openmuse-ppg-stream", default="Muse_PPG")
    parser.add_argument("--openmuse-heart-rate-stream", default="Muse_HR")
    parser.add_argument("--openmuse-battery-stream", default="Muse_BATT")


def _add_muse_sdk_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--sdk-path",
        type=Path,
        help="Local official Muse SDK path for future adapter work. Never commit this path or its contents.",
    )


def _openmuse_stream_names(args: argparse.Namespace) -> Mapping[str, tuple]:
    return {
        "eeg": (args.openmuse_eeg_stream, "Muse-EEG"),
        "imu": (args.openmuse_imu_stream, "Muse-ACCGYRO"),
        "ppg": (args.openmuse_ppg_stream, "Muse-PPG"),
        "heart_rate": (args.openmuse_heart_rate_stream, "Muse_HEART", "Muse_HEART_RATE"),
        "battery": (args.openmuse_battery_stream, "Muse_BATTERY", "Muse-Telemetry"),
    }


def _default_recording_dir() -> Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _default_path_base() / "data" / "recordings" / timestamp


def _resolve_output_dir(output_dir: Path) -> Path:
    output_dir = output_dir.expanduser()
    if output_dir.is_absolute():
        return output_dir
    return _default_path_base() / output_dir


def _resolve_output_path(output_path: Path) -> Path:
    output_path = output_path.expanduser()
    if output_path.is_absolute():
        return output_path
    return _default_path_base() / output_path


def _default_path_base() -> Path:
    cwd = Path.cwd()
    if _is_writable_non_root(cwd):
        return cwd.resolve()

    project_root = _find_project_root(Path(__file__).resolve())
    if project_root is not None:
        return project_root

    return Path.home().resolve()


def _is_writable_non_root(path: Path) -> bool:
    if path.parent == path:
        return False
    return os.access(path, os.W_OK)


def _find_project_root(start: Path) -> Optional[Path]:
    current = start if start.is_dir() else start.parent
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "src" / "muse_tmr").exists():
            return candidate
    return None


if __name__ == "__main__":
    raise SystemExit(main())
