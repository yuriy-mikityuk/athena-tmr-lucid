#!/usr/bin/env python3
"""Fail when a built wheel leaves out a file from src/muse_tmr.

An editable install runs straight from the checkout, so a subpackage or an app
page file missing from the wheel only shows up after a regular `pip install .`
(muse_tmr.validation and muse_tmr.annotations were missing until #183).
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path
from typing import List

SRC = Path(__file__).resolve().parents[1] / "src"


def expected_files(src: Path = SRC) -> List[str]:
    return sorted(
        path.relative_to(src).as_posix()
        for path in (src / "muse_tmr").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and not path.name.startswith(".")
    )


def missing_files(wheel: Path, src: Path = SRC) -> List[str]:
    with zipfile.ZipFile(wheel) as archive:
        shipped = set(archive.namelist())
    return [name for name in expected_files(src) if name not in shipped]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a built wheel against src/muse_tmr.")
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()

    missing = missing_files(args.wheel)
    for name in missing:
        print(f"missing from {args.wheel.name}: {name}")
    if missing:
        return 1
    print(f"{args.wheel.name} has all {len(expected_files())} files from src/muse_tmr")
    return 0


if __name__ == "__main__":
    sys.exit(main())
