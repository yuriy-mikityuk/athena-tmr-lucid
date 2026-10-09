"""Voice-guided calibration run for the EMG and breathing checks.

One ~23 min recording with Muse and a Polar H10 that can be followed with eyes
closed: macOS ``say`` reads every step, paces the clenches and the breathing,
and asks for the H10 to be unclipped. Cue times are logged as they are spoken,
and analyze-meditation blocks files are cut from those actual times:

- relaxed vs slight jaw tension, vs slight forehead tension, vs 1 s clenches.
  Each tension segment sits between two relaxed windows of its own length, so
  linear drift cancels in tension - relaxed;
- 6/min vs 12/min paced breathing (inhale shorter than exhale), a known
  reference for the three breathing-rate estimates.

Times are seconds from the first Muse frame, the same base as blocks.json.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from muse_tmr.reports.meditation_analysis import MeditationBlock, MeditationBlocks, write_meditation_blocks

CALIBRATION_DIRNAME = "calibration"
CALIBRATION_SCHEMA_VERSION = 1
DEFAULT_VOICE = "Milena"
RELAXED = "relaxed"


@dataclass(frozen=True)
class Pace:
    """A cycle of spoken beats repeated through a segment."""

    period_s: float
    beats: Tuple[Tuple[float, str], ...]  # (offset in the cycle, word)
    lead_s: float  # the first cycle starts this long after the instruction
    rate_bpm: Optional[float] = None  # known breathing rate for paced breathing


@dataclass(frozen=True)
class Segment:
    name: str
    label: str  # short English text for the app
    start_s: float
    end_s: float
    say: str
    condition: Optional[str] = None
    pace: Optional[Pace] = None

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "name": self.name,
            "label": self.label,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "say": self.say,
            "condition": self.condition,
        }
        if self.pace is not None:
            payload["pace"] = {
                "period_s": self.pace.period_s,
                "beats": [list(beat) for beat in self.pace.beats],
                "lead_s": self.pace.lead_s,
                "rate_bpm": self.pace.rate_bpm,
            }
        return payload


PROTOCOL: Tuple[Segment, ...] = (
    Segment("settle", "Settle in, eyes closed", 0, 60,
            "Закрой глаза и сиди спокойно. Первая минута на привыкание."),
    Segment("relaxed_1", "Relaxed", 60, 180,
            "Просто расслабься. Лицо и челюсть мягкие.", RELAXED),
    Segment("jaw", "Jaw slightly tense, teeth lightly touching", 180, 300,
            "Чуть напряги челюсть, зубы слегка касаются. Держи так две минуты.", "jaw"),
    Segment("relaxed_2", "Relaxed", 300, 420,
            "Отпусти челюсть. Расслабься.", RELAXED),
    Segment("forehead", "Forehead slightly tense, brows a little up", 420, 540,
            "Чуть напряги лоб, брови слегка вверх. Держи две минуты.", "forehead"),
    Segment("relaxed_3", "Relaxed", 540, 660,
            "Отпусти лоб. Расслабься.", RELAXED),
    Segment("clench", "Clench 1 s every 3 s, on the voice", 660, 720,
            "Сейчас сжимай зубы на секунду, по команде.", "clench",
            Pace(3.0, ((0.0, "сжать"), (1.0, "отпустить")), lead_s=4.0)),
    Segment("relaxed_4", "Relaxed", 720, 780,
            "Хватит. Расслабься.", RELAXED),
    Segment("breath_6", "Paced breathing 6/min: in 4 s, out 6 s", 780, 960,
            "Дыши по голосу. Вдох четыре секунды, выдох шесть.", "breath_6",
            Pace(10.0, ((0.0, "вдох"), (4.0, "выдох")), lead_s=6.0, rate_bpm=6.0)),
    Segment("breath_12", "Paced breathing 12/min: in 2 s, out 3 s", 960, 1140,
            "Теперь быстрее. Вдох две секунды, выдох три.", "breath_12",
            Pace(5.0, ((0.0, "вдох"), (2.0, "выдох")), lead_s=5.0, rate_bpm=12.0)),
    Segment("h10_off", "Eyes open: unclip the H10 from the strap", 1140, 1200,
            "Дыши как обычно. Открой глаза, отстегни датчик H10 от ремня и положи рядом."),
    Segment("h10_back", "H10 back on the strap, eyes closed, sit still", 1200, 1380,
            "Пристегни датчик обратно. Закрой глаза и сиди спокойно до конца."),
)
END_SAY = "Всё, запись закончена. Можно открыть глаза."
PROTOCOL_SECONDS = PROTOCOL[-1].end_s
BATTERY_PULL_SAY = (
    "Дыши как обычно. Открой глаза, отстегни датчик H10 от ремня, открой крышку монеткой "
    "и вынь батарейку секунд на десять. Потом вставь её обратно и закрой крышку."
)
# The recorder runs a little past the protocol so the last epoch is complete.
RECORD_SECONDS = PROTOCOL_SECONDS + 20.0

# (pair, relaxed before, tension, relaxed after): contrasts are tension - relaxed.
TENSION_PAIRS = (
    ("jaw", "relaxed_1", "jaw", "relaxed_2"),
    ("forehead", "relaxed_2", "forehead", "relaxed_3"),
    ("clench", "relaxed_3", "clench", "relaxed_4"),
)
BREATHING_PAIR = ("breathing", "breath_6", "breath_12")

# Before a calibration run: the optics on and off, twice, while the 64 Hz line is
# still strong in the first minutes. Alternating keeps its own fading out of the
# comparison.
LINE_CHECK_PRESETS = ("p1034", "p21", "p1034", "p21")
LINE_CHECK_SECONDS = 120.0
LINE_CHECK_FILENAME = "line_check.json"
LINE_CHECK_INTRO_SAY = (
    "Сначала проверка помехи: четыре куска по две минуты, между ними обруч переподключается. "
    "Закрой глаза и сиди спокойно."
)
LINE_CHECK_SEGMENT_SAY = "Кусок {number} из четырёх."
LINE_CHECK_DONE_SAY = "Проверка помехи закончена. Дальше калибровка, сиди как сидишь."


def calibration_protocol(battery_pull: bool = False) -> Tuple[Segment, ...]:
    """The protocol; with battery_pull the H10 minute also takes its battery out
    for ~10 s, so the link really drops and the sensor clock restarts."""
    if not battery_pull:
        return PROTOCOL
    return tuple(
        replace(segment, label="Eyes open: unclip the H10, take its battery out for ~10 s", say=BATTERY_PULL_SAY)
        if segment.name == "h10_off"
        else segment
        for segment in PROTOCOL
    )


def run_line_check(
    directories: Sequence[Path],
    speaker,
    record: Callable[[Path, str], int],
    presets: Sequence[str] = LINE_CHECK_PRESETS,
    log: Callable[[str], None] = lambda message: None,
) -> List[Dict[str, object]]:
    """One short recording per preset, in order; ``record(directory, preset)``
    runs the recorder to the end and returns its exit code."""
    speaker.speak(LINE_CHECK_INTRO_SAY)
    results: List[Dict[str, object]] = []
    for number, (directory, preset) in enumerate(zip(directories, presets), start=1):
        speaker.speak(LINE_CHECK_SEGMENT_SAY.format(number=number))
        log(f"line check {number}/{len(presets)}: {preset} -> {directory}")
        code = record(Path(directory), preset)
        results.append({"index": number, "preset": preset, "recording": str(directory), "returncode": code})
    speaker.speak(LINE_CHECK_DONE_SAY)
    return results


@dataclass(frozen=True)
class Cue:
    planned_s: float
    kind: str  # segment | beat | end
    segment: str
    text: str
    cycle_start: bool = False


def schedule(protocol: Sequence[Segment] = PROTOCOL) -> List[Cue]:
    """Every spoken cue in time order; paced cycles never run past their segment."""
    cues: List[Cue] = []
    for segment in protocol:
        cues.append(Cue(segment.start_s, "segment", segment.name, segment.say))
        pace = segment.pace
        if pace is None:
            continue
        cycle = segment.start_s + pace.lead_s
        while cycle + pace.period_s <= segment.end_s + 1e-9:
            for offset, word in pace.beats:
                cues.append(Cue(cycle + offset, "beat", segment.name, word, cycle_start=offset == 0.0))
            cycle += pace.period_s
    cues.append(Cue(protocol[-1].end_s, "end", "end", END_SAY))
    return sorted(cues, key=lambda cue: cue.planned_s)


# --- speaking ------------------------------------------------------------------


def available_voices(command: str = "say") -> List[str]:
    if shutil.which(command) is None:
        return []
    try:
        output = subprocess.run([command, "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.split()[0] for line in output.splitlines() if line.strip()]


class SaySpeaker:
    """Speaks through macOS ``say`` without holding up the schedule.

    A new cue waits at most ``max_wait_s`` for the previous one to finish, so
    two cues never talk over each other but a slow one cannot drift the plan.
    """

    def __init__(
        self,
        voice: Optional[str] = DEFAULT_VOICE,
        rate: Optional[int] = None,
        command: str = "say",
        popen: Callable[..., object] = subprocess.Popen,
        max_wait_s: float = 2.0,
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.command = command
        self._popen = popen
        self._process = None
        self.max_wait_s = max_wait_s

    def speak(self, text: str) -> None:
        self._wait_previous(self.max_wait_s)
        argv = [self.command]
        if self.voice:
            argv += ["-v", self.voice]
        if self.rate:
            argv += ["-r", str(self.rate)]
        argv.append(text)
        self._process = self._popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    def close(self) -> None:
        self._wait_previous(10.0)

    def _wait_previous(self, timeout: float) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.terminate()


class SilentSpeaker:
    """For tests and dry runs: remembers what would have been said."""

    def __init__(self) -> None:
        self.spoken: List[str] = []

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def close(self) -> None:
        pass


# --- the guide -----------------------------------------------------------------


def calibration_dir(recording_dir: Path) -> Path:
    return Path(recording_dir) / CALIBRATION_DIRNAME


def first_frame_time(recording_dir: Path) -> Optional[float]:
    """Wall-clock timestamp of the first recorded Muse frame, once it is on disk."""
    try:
        with (Path(recording_dir) / "decoded_frames.jsonl").open("r", encoding="utf-8") as handle:
            line = handle.readline()
    except OSError:
        return None
    if not line.endswith("\n"):
        return None  # still being written
    try:
        return float(json.loads(line)["timestamp"])
    except (ValueError, KeyError, TypeError):
        return None


@dataclass
class GuideResult:
    stop_reason: str  # completed | recording_ended | no_first_frame | interrupted
    first_frame_time: Optional[float]
    cues_spoken: int
    segments: List[Dict[str, object]]
    blocks_files: Dict[str, str]


def run_guide(
    recording_dir: Path,
    speaker,
    *,
    protocol: Sequence[Segment] = PROTOCOL,
    recorder_alive: Callable[[], bool] = lambda: True,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    poll_seconds: float = 0.05,
    first_frame_timeout_s: float = 600.0,
    late_beat_drop_s: float = 1.0,
    log: Callable[[str], None] = lambda message: None,
) -> GuideResult:
    """Follow a recording that is starting up and speak the protocol on time.

    Waits for the first Muse frame, then speaks each cue when it is due. Stops
    early when the recording ends (summary.json appears or the recorder exits).
    Beats more than ``late_beat_drop_s`` late are dropped rather than rushed,
    and a guide started late only announces the step that is still running.
    Writes ``calibration/cues.jsonl`` as it goes and, at the end,
    ``segments.json`` plus a blocks file for every pair that completed.
    """
    recording_dir = Path(recording_dir)
    out_dir = calibration_dir(recording_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        out_dir / "plan.json",
        {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "time_base": "seconds_from_first_frame",
            "protocol_seconds": protocol[-1].end_s,
            "segments": [segment.to_dict() for segment in protocol],
        },
    )
    by_name = {segment.name: segment for segment in protocol}

    def ended() -> bool:
        return (recording_dir / "summary.json").exists() or not recorder_alive()

    _write_state(out_dir, "waiting", None, protocol)
    origin: Optional[float] = None
    stop_reason = "completed"
    spoken = 0
    stopped_at_s: Optional[float] = None
    try:
        waiting_since = clock()
        while origin is None:
            origin = first_frame_time(recording_dir)
            if origin is not None:
                break
            if ended():
                stop_reason = "recording_ended"
                break
            if clock() - waiting_since > first_frame_timeout_s:
                stop_reason = "no_first_frame"
                break
            sleep(0.2)
        if origin is not None:
            log("first frame received, starting the protocol")
            with (out_dir / "cues.jsonl").open("a", encoding="utf-8") as cues_file:
                for cue in schedule(protocol):
                    due = origin + cue.planned_s
                    while clock() < due and not ended():
                        sleep(max(0.0, min(poll_seconds, due - clock())))
                    if ended():
                        stop_reason = "recording_ended"
                        stopped_at_s = clock() - origin
                        break
                    now = clock()
                    if cue.kind == "beat" and now - due > late_beat_drop_s:
                        continue
                    if cue.kind == "segment" and now >= origin + by_name[cue.segment].end_s:
                        continue  # started late: only the current step is announced
                    speaker.speak(cue.text)
                    now = clock()  # after any wait for the previous cue to finish
                    spoken += 1
                    cues_file.write(
                        json.dumps(
                            {
                                "kind": cue.kind,
                                "segment": cue.segment,
                                "text": cue.text,
                                "cycle_start": cue.cycle_start,
                                "planned_s": cue.planned_s,
                                "elapsed_s": round(now - origin, 4),
                                "wall": now,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    cues_file.flush()
                    if cue.kind == "segment":
                        log(f"{cue.planned_s / 60:4.1f} min  {by_name[cue.segment].label}")
                        _write_state(out_dir, "running", by_name[cue.segment], protocol)
    except KeyboardInterrupt:
        stop_reason = "interrupted"
        if origin is not None:
            stopped_at_s = clock() - origin
    finally:
        speaker.close()

    cues = load_cues(recording_dir)
    segments = segments_from_cues(cues, protocol, stopped_at_s=stopped_at_s)
    blocks_files: Dict[str, str] = {}
    if origin is not None:
        _write_json(
            out_dir / "segments.json",
            {
                "schema_version": CALIBRATION_SCHEMA_VERSION,
                "time_base": "seconds_from_first_frame",
                "first_frame_time": origin,
                "stop_reason": stop_reason,
                "segments": segments,
            },
        )
        for name, blocks in pair_blocks(segments).items():
            path = write_meditation_blocks(blocks, out_dir / f"blocks_{name}.json")
            blocks_files[name] = str(path)
    _write_state(out_dir, "done" if stop_reason == "completed" else "stopped", None, protocol, stop_reason)
    return GuideResult(stop_reason, origin, spoken, segments, blocks_files)


def load_cues(recording_dir: Path) -> List[Dict[str, object]]:
    path = calibration_dir(recording_dir) / "cues.jsonl"
    cues = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            cues.append(json.loads(line))
        except ValueError:
            continue  # a torn last line from a killed guide
    return cues


def segments_from_cues(
    cues: Sequence[Mapping[str, object]],
    protocol: Sequence[Segment] = PROTOCOL,
    *,
    stopped_at_s: Optional[float] = None,
) -> List[Dict[str, object]]:
    """Actual segment times: each starts when its instruction was spoken and
    ends when the next one (or the closing words) was. A segment cut short by
    a stop is kept with ``completed`` false."""
    starts = {str(cue["segment"]): float(cue["elapsed_s"]) for cue in cues if cue.get("kind") == "segment"}
    end_cue = next((float(cue["elapsed_s"]) for cue in cues if cue.get("kind") == "end"), None)
    segments = []
    for index, segment in enumerate(protocol):
        if segment.name not in starts:
            continue
        start = starts[segment.name]
        following = [starts[item.name] for item in protocol[index + 1 :] if item.name in starts]
        completed = True
        if following:
            end = following[0]
        elif end_cue is not None:
            end = end_cue
        else:
            end = stopped_at_s if stopped_at_s is not None else segment.end_s
            completed = False
        cycle_starts = [
            float(cue["elapsed_s"])
            for cue in cues
            if cue.get("segment") == segment.name and cue.get("kind") == "beat" and cue.get("cycle_start")
        ]
        record: Dict[str, object] = {
            "name": segment.name,
            "label": segment.label,
            "condition": segment.condition,
            "planned_start_s": segment.start_s,
            "planned_end_s": segment.end_s,
            "start_s": start,
            "end_s": end,
            "completed": completed,
        }
        if segment.pace is not None:
            record.update(
                {
                    "pace_period_s": segment.pace.period_s,
                    "beats": [list(beat) for beat in segment.pace.beats],
                    "known_rate_bpm": segment.pace.rate_bpm,
                    "cycle_starts_s": cycle_starts,
                }
            )
        segments.append(record)
    return segments


def pair_blocks(segments: Sequence[Mapping[str, object]]) -> Dict[str, MeditationBlocks]:
    """analyze-meditation blocks for each pair whose segments all completed.

    Times are rounded to the second: cues land tens of ms after their slot, and
    without rounding the 10 s epoch grid would drop one epoch at every boundary.
    """
    done = {
        str(item["name"]): {**item, "start_s": float(round(float(item["start_s"]))), "end_s": float(round(float(item["end_s"])))}
        for item in segments
        if item.get("completed")
    }
    pairs: Dict[str, MeditationBlocks] = {}
    for name, before, tension, after in TENSION_PAIRS:
        if not all(key in done for key in (before, tension, after)):
            continue
        t_start, t_end = float(done[tension]["start_s"]), float(done[tension]["end_s"])
        length = t_end - t_start
        b_end = float(done[before]["end_s"])
        b_start = max(float(done[before]["start_s"]), b_end - length)
        a_start = float(done[after]["start_s"])
        a_end = min(float(done[after]["end_s"]), a_start + length)
        condition = str(done[tension]["condition"])
        pairs[name] = MeditationBlocks(
            blocks=(
                MeditationBlock(0, RELAXED, b_start, b_end),
                MeditationBlock(1, condition, t_start, t_end),
                MeditationBlock(2, RELAXED, a_start, a_end),
            ),
            settle_seconds=b_start,
            order=(RELAXED, condition, RELAXED),
            conditions=(condition, RELAXED),
        )
    name, first, second = BREATHING_PAIR
    if first in done and second in done:
        blocks = tuple(
            MeditationBlock(index, str(done[key]["condition"]), float(done[key]["start_s"]), float(done[key]["end_s"]))
            for index, key in enumerate((first, second))
        )
        pairs[name] = MeditationBlocks(
            blocks=blocks,
            settle_seconds=blocks[0].start_s,
            order=tuple(block.condition for block in blocks),
            conditions=tuple(block.condition for block in blocks),
        )
    return pairs


def read_state(recording_dir: Path) -> Optional[Dict[str, object]]:
    try:
        return json.loads((calibration_dir(recording_dir) / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_state(
    out_dir: Path,
    state: str,
    segment: Optional[Segment],
    protocol: Sequence[Segment],
    stop_reason: Optional[str] = None,
) -> None:
    names = [item.name for item in protocol]
    payload: Dict[str, object] = {
        "state": state,
        "protocol_seconds": protocol[-1].end_s,
        "steps": len(protocol),
        "updated_at": time.time(),
    }
    if segment is not None:
        payload.update(
            {
                "segment": segment.name,
                "label": segment.label,
                "step": names.index(segment.name) + 1,
                "start_s": segment.start_s,
                "end_s": segment.end_s,
            }
        )
    if stop_reason is not None:
        payload["stop_reason"] = stop_reason
    _write_json(out_dir / "state.json", payload)


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
