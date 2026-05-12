"""CLI entry point for the Muse REM-TMR project."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
from pathlib import Path
from typing import Optional, Sequence

from muse_tmr import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="muse-tmr",
        description="Muse S Athena REM-TMR/TLR research tooling.",
    )
    parser.add_argument("--version", action="version", version=f"muse-tmr {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show project status and configured components.")

    discover_parser = subparsers.add_parser("discover", help="Discover Muse devices.")
    discover_parser.add_argument("--source", choices=("amused",), default="amused")
    discover_parser.add_argument("--name-filter", default="Muse")

    stream_parser = subparsers.add_parser("stream", help="Stream Muse frames from a source.")
    stream_parser.add_argument("--source", choices=("amused",), default="amused")
    stream_parser.add_argument("--address", help="Muse BLE address. If omitted, discovery is used.")
    stream_parser.add_argument("--name-filter", default="Muse")
    stream_parser.add_argument("--preset", default="p1034")
    stream_parser.add_argument("--duration-seconds", type=int, default=3600)
    stream_parser.add_argument("--quiet", action="store_true")

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

    record_parser = subparsers.add_parser("record", help="Record an overnight Muse session.")
    record_parser.add_argument("--source", choices=("amused",), default="amused")
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
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        print("Muse REM-TMR project scaffold is installed.")
        return 0
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
    if args.command == "record":
        return asyncio.run(_record(args))

    parser.print_help()
    return 0


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
        create_audio_backend,
    )

    player = AudioCuePlayer(
        AudioPlaybackConfig(
            max_volume=args.max_volume,
            default_volume=args.volume,
            fade_in_seconds=args.fade_in_seconds,
            fade_out_seconds=args.fade_out_seconds,
            device_name=args.device_name,
            log_path=_resolve_output_path(args.log_path) if args.log_path else None,
        ),
        backend=create_audio_backend(args.backend),
    )
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


def _build_source(args: argparse.Namespace, duration_seconds: int):
    from muse_tmr.sources.amused_source import AmusedSource

    return AmusedSource(
        address=getattr(args, "address", None),
        name_filter=getattr(args, "name_filter", "Muse"),
        preset=getattr(args, "preset", "p1034"),
        duration_seconds=duration_seconds,
        verbose=not getattr(args, "quiet", False),
    )


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
