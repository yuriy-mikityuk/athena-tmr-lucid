"""Morning dream report data capture."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from muse_tmr.protocol import NightPuzzleSession, PuzzleCatalog

DREAM_REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DreamPuzzleIncorporation:
    puzzle_id: str
    dream_content: str
    incorporated: bool = True
    cue_id: str = ""
    confidence: float = 1.0
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "puzzle_id", _required_str(self.puzzle_id, "puzzle_id"))
        object.__setattr__(self, "dream_content", str(self.dream_content).strip())
        object.__setattr__(self, "cue_id", str(self.cue_id).strip())
        object.__setattr__(self, "notes", str(self.notes))
        _validate_confidence(self.confidence, "confidence")
        if self.incorporated and not self.dream_content:
            raise ValueError("incorporated puzzle links require dream_content")

    def to_dict(self) -> Dict[str, object]:
        return {
            "puzzle_id": self.puzzle_id,
            "cue_id": self.cue_id,
            "incorporated": self.incorporated,
            "dream_content": self.dream_content,
            "confidence": self.confidence,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DreamPuzzleIncorporation":
        return cls(
            puzzle_id=str(payload["puzzle_id"]),
            cue_id=str(payload.get("cue_id", "")),
            incorporated=_boolish(payload.get("incorporated", True)),
            dream_content=str(payload.get("dream_content", "")),
            confidence=float(payload.get("confidence", 1.0)),
            notes=str(payload.get("notes", "")),
        )


@dataclass(frozen=True)
class DreamReport:
    session_id: str
    lucid: bool
    cues_heard: bool
    confidence: float
    dream_text: str
    puzzle_incorporations: Tuple[DreamPuzzleIncorporation, ...] = ()
    report_id: str = ""
    reported_at_utc: str = ""
    notes: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)
    schema_version: int = DREAM_REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _required_str(self.session_id, "session_id"))
        object.__setattr__(self, "dream_text", str(self.dream_text))
        object.__setattr__(self, "notes", str(self.notes))
        object.__setattr__(self, "puzzle_incorporations", tuple(self.puzzle_incorporations))
        _validate_confidence(self.confidence, "confidence")
        if not self.report_id:
            object.__setattr__(self, "report_id", f"{self.session_id}-dream-report")
        if not self.reported_at_utc:
            object.__setattr__(self, "reported_at_utc", _utc_now())
        puzzle_ids = [link.puzzle_id for link in self.puzzle_incorporations]
        if len(set(puzzle_ids)) != len(puzzle_ids):
            raise ValueError("puzzle_incorporations cannot contain duplicate puzzle IDs")

    @property
    def incorporated_puzzle_ids(self) -> Tuple[str, ...]:
        return tuple(
            link.puzzle_id
            for link in self.puzzle_incorporations
            if link.incorporated
        )

    @property
    def puzzle_incorporation_count(self) -> int:
        return len(self.incorporated_puzzle_ids)

    def validate_against_session(self, session: NightPuzzleSession) -> "DreamReport":
        if self.session_id != session.session_id:
            raise ValueError("dream report session_id does not match night puzzle session")
        session_puzzle_ids = set(session.puzzle_ids)
        unknown = tuple(
            sorted(
                link.puzzle_id
                for link in self.puzzle_incorporations
                if link.puzzle_id not in session_puzzle_ids
            )
        )
        if unknown:
            raise ValueError(f"dream report links unknown session puzzles: {unknown}")
        return self

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "session_id": self.session_id,
            "reported_at_utc": self.reported_at_utc,
            "lucid": self.lucid,
            "cues_heard": self.cues_heard,
            "confidence": self.confidence,
            "dream_text": self.dream_text,
            "puzzle_incorporation_count": self.puzzle_incorporation_count,
            "puzzle_incorporations": [
                link.to_dict() for link in self.puzzle_incorporations
            ],
            "notes": self.notes,
            "metadata": dict(self.metadata),
        }

    def save(self, output_path: Path) -> Path:
        output_path = output_path.expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return output_path

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DreamReport":
        return cls(
            schema_version=int(payload.get("schema_version", DREAM_REPORT_SCHEMA_VERSION)),
            report_id=str(payload.get("report_id", "")),
            session_id=str(payload["session_id"]),
            reported_at_utc=str(payload.get("reported_at_utc", "")),
            lucid=_boolish(payload["lucid"]),
            cues_heard=_boolish(payload["cues_heard"]),
            confidence=float(payload["confidence"]),
            dream_text=str(payload.get("dream_text", "")),
            puzzle_incorporations=tuple(
                DreamPuzzleIncorporation.from_dict(item)
                for item in payload.get("puzzle_incorporations", ())
            ),
            notes=str(payload.get("notes", "")),
            metadata=dict(payload.get("metadata", {}) or {}),
        )

    @classmethod
    def load(cls, input_path: Path) -> "DreamReport":
        return cls.from_dict(json.loads(input_path.expanduser().read_text(encoding="utf-8")))


def build_dream_report(
    session: NightPuzzleSession,
    *,
    lucid: bool,
    cues_heard: bool,
    confidence: float,
    dream_text: str,
    puzzle_incorporation_text: Optional[Mapping[str, str]] = None,
    catalog: Optional[PuzzleCatalog] = None,
    report_id: str = "",
    reported_at_utc: str = "",
    notes: str = "",
) -> DreamReport:
    links = []
    for puzzle_id, text in (puzzle_incorporation_text or {}).items():
        cue_id = catalog.get_puzzle(puzzle_id).cue_id if catalog is not None else ""
        links.append(
            DreamPuzzleIncorporation(
                puzzle_id=puzzle_id,
                cue_id=cue_id,
                dream_content=text,
                incorporated=True,
            )
        )
    report = DreamReport(
        report_id=report_id,
        session_id=session.session_id,
        reported_at_utc=reported_at_utc,
        lucid=lucid,
        cues_heard=cues_heard,
        confidence=confidence,
        dream_text=dream_text,
        puzzle_incorporations=tuple(links),
        notes=notes,
        metadata={
            "session_puzzle_count": len(session.puzzle_ids),
            "linked_puzzle_count": len(links),
        },
    )
    return report.validate_against_session(session)


def load_dream_report(input_path: Path) -> DreamReport:
    return DreamReport.load(input_path)


def _required_str(value: object, name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _validate_confidence(value: float, name: str) -> None:
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"expected yes/no boolean value, got {value!r}")


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()
