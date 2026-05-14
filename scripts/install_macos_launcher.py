#!/usr/bin/env python3
"""Install a local macOS launcher for the Muse TMR setup app."""

from __future__ import annotations

import argparse
import plistlib
import shutil
import stat
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from shlex import quote
from typing import Iterable, Tuple


DEFAULT_APP_NAME = "Muse TMR Setup"
DEFAULT_PORT = 8765


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a clickable macOS .app launcher for the local Muse TMR setup app."
    )
    parser.add_argument("--address", help="Muse BLE address to bake into the launcher.")
    parser.add_argument("--source", choices=("amused", "mock"), default="amused")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--app-name", default=DEFAULT_APP_NAME)
    parser.add_argument(
        "--target",
        type=Path,
        help="Output .app path. Defaults to ~/Desktop/<app-name>.app.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project checkout path to launch from.",
    )
    parser.add_argument("--force", action="store_true", help="Replace an existing launcher.")
    args = parser.parse_args()

    repo_root = args.repo_root.expanduser().resolve()
    target = (
        args.target.expanduser()
        if args.target
        else Path.home() / "Desktop" / f"{args.app_name}.app"
    )
    target = target.resolve()
    if target.exists():
        if not args.force:
            raise SystemExit(f"{target} already exists; rerun with --force to replace it")
        shutil.rmtree(target)

    create_launcher_app(
        target=target,
        app_name=args.app_name,
        repo_root=repo_root,
        source=args.source,
        address=args.address or "",
        host=args.host,
        port=args.port,
    )
    print(f"Installed launcher: {target}")
    return 0


def create_launcher_app(
    *,
    target: Path,
    app_name: str,
    repo_root: Path,
    source: str,
    address: str,
    host: str,
    port: int,
) -> None:
    contents = target / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    url = f"http://{host}:{port}"
    runner = resources / "run-local-app.command"
    launcher = macos / "launch"
    python_bin = repo_root / ".venv" / "bin" / "python"
    log_path = Path.home() / "Library" / "Logs" / "Muse TMR Setup.log"

    runner.write_text(
        _runner_script(
            app_name=app_name,
            repo_root=repo_root,
            python_bin=python_bin,
            source=source,
            address=address,
            host=host,
            port=port,
            url=url,
            log_path=log_path,
        ),
        encoding="utf-8",
    )
    launcher.write_text(
        _launcher_script(app_name=app_name, url=url),
        encoding="utf-8",
    )
    _make_executable(runner)
    _make_executable(launcher)
    icon_installed = _install_icon(resources)

    bundle_id = "dev.muse-tmr.local-setup"
    plist = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": app_name,
        "CFBundleExecutable": "launch",
        "CFBundleIdentifier": bundle_id,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": app_name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "11.0",
    }
    if icon_installed:
        plist["CFBundleIconFile"] = "muse-tmr"
    (contents / "Info.plist").write_bytes(plistlib.dumps(plist, sort_keys=True))


def _launcher_script(*, app_name: str, url: str) -> str:
    return f"""#!/bin/zsh
set -u

URL={quote(url)}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
RUNNER="$SCRIPT_DIR/../Resources/run-local-app.command"

if /usr/bin/curl -fsS --max-time 0.6 "$URL/api/health" >/dev/null 2>&1; then
  /usr/bin/open "$URL"
  exit 0
fi

/usr/bin/open -a Terminal "$RUNNER"
/usr/bin/osascript -e {quote(f'display notification "Starting local app..." with title "{app_name}"')} >/dev/null 2>&1 || true
exit 0
"""


def _runner_script(
    *,
    app_name: str,
    repo_root: Path,
    python_bin: Path,
    source: str,
    address: str,
    host: str,
    port: int,
    url: str,
    log_path: Path,
) -> str:
    app_args = [
        "-m",
        "muse_tmr.cli.main",
        "app",
        "--source",
        source,
        "--host",
        host,
        "--port",
        str(port),
    ]
    if source == "amused" and address:
        app_args.extend(["--address", address])
    command = " ".join(quote(part) for part in app_args)
    return f"""#!/bin/zsh
set -u

APP_NAME={quote(app_name)}
REPO_ROOT={quote(str(repo_root))}
PYTHON_BIN={quote(str(python_bin))}
URL={quote(url)}
LOG_PATH={quote(str(log_path))}

mkdir -p "$(dirname "$LOG_PATH")"

if /usr/bin/curl -fsS --max-time 0.6 "$URL/api/health" >/dev/null 2>&1; then
  echo "$APP_NAME is already running at $URL"
  /usr/bin/open "$URL"
  exit 0
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python virtualenv not found at: $PYTHON_BIN"
  echo "Create it first, then rerun this launcher."
  /usr/bin/osascript -e 'display alert "Muse TMR Setup" message "Python virtualenv not found. Create .venv first."' >/dev/null 2>&1 || true
  read -k 1 "?Press any key to close..."
  exit 1
fi

(
  for _ in {{1..80}}; do
    if /usr/bin/curl -fsS --max-time 0.6 "$URL/api/health" >/dev/null 2>&1; then
      /usr/bin/open "$URL"
      exit 0
    fi
    sleep 0.25
  done
  /usr/bin/osascript -e 'display notification "Server did not become ready; check Terminal logs." with title "Muse TMR Setup"' >/dev/null 2>&1 || true
) &

cd "$REPO_ROOT" || exit 1
export PYTHONPATH="$REPO_ROOT:$REPO_ROOT/src:${{PYTHONPATH:-}}"

echo "Starting $APP_NAME"
echo "URL: $URL"
echo "Log: $LOG_PATH"
echo "Press Ctrl-C in this Terminal window to stop the local app."
echo

"$PYTHON_BIN" {command} 2>&1 | /usr/bin/tee -a "$LOG_PATH"
"""


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _install_icon(resources: Path) -> bool:
    if not shutil.which("sips") or not shutil.which("iconutil"):
        return False

    try:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_png = temp_dir / "muse-tmr-1024.png"
            iconset = temp_dir / "muse-tmr.iconset"
            iconset.mkdir()
            _write_icon_png(source_png, 1024)

            for size in (16, 32, 128, 256, 512):
                _resize_icon(source_png, iconset / f"icon_{size}x{size}.png", size)
                _resize_icon(source_png, iconset / f"icon_{size}x{size}@2x.png", size * 2)

            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset), "-o", str(resources / "muse-tmr.icns")],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Warning: could not create app icon: {exc}")
        return False
    return True


def _resize_icon(source_png: Path, output_png: Path, size: int) -> None:
    subprocess.run(
        ["sips", "-z", str(size), str(size), str(source_png), "--out", str(output_png)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _write_icon_png(path: Path, size: int) -> None:
    pixels = bytearray([0, 0, 0, 0] * size * size)
    _draw_rounded_background(pixels, size)
    _draw_headband(pixels, size)
    _draw_check(pixels, size)
    _write_png(path, size, size, pixels)


def _draw_rounded_background(pixels: bytearray, size: int) -> None:
    radius = int(size * 0.22)
    for y in range(size):
        t = y / max(1, size - 1)
        bg = (
            int(15 + 4 * t),
            int(23 + 52 * t),
            int(42 + 48 * t),
            255,
        )
        for x in range(size):
            if _inside_rounded_rect(x, y, size, radius):
                _set_pixel(pixels, size, x, y, bg)


def _draw_headband(pixels: bytearray, size: int) -> None:
    center = size * 0.5
    cx, cy = center, size * 0.59
    rx, ry = size * 0.36, size * 0.29
    teal = (45, 212, 191, 255)
    dark = (15, 23, 42, 255)
    outline = (226, 232, 240, 255)

    for angle in range(205, 336):
        point = _ellipse_point(cx, cy, rx, ry, angle)
        _draw_circle(pixels, size, point, int(size * 0.032), outline)
    for angle in range(208, 333):
        point = _ellipse_point(cx, cy, rx, ry, angle)
        _draw_circle(pixels, size, point, int(size * 0.024), teal)

    for angle in (218, 250, 290, 322):
        point = _ellipse_point(cx, cy, rx * 0.78, ry * 0.72, angle)
        _draw_circle(pixels, size, point, int(size * 0.047), dark)
        _draw_circle(pixels, size, point, int(size * 0.036), teal)


def _draw_check(pixels: bytearray, size: int) -> None:
    teal = (20, 184, 166, 255)
    points = (
        (int(size * 0.37), int(size * 0.56)),
        (int(size * 0.47), int(size * 0.66)),
        (int(size * 0.66), int(size * 0.43)),
    )
    _draw_line(pixels, size, points[0], points[1], int(size * 0.035), teal)
    _draw_line(pixels, size, points[1], points[2], int(size * 0.035), teal)


def _inside_rounded_rect(x: int, y: int, size: int, radius: int) -> bool:
    edge = size - 1
    cx = min(max(x, radius), edge - radius)
    cy = min(max(y, radius), edge - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2


def _ellipse_point(cx: float, cy: float, rx: float, ry: float, degrees: int) -> Tuple[int, int]:
    import math

    radians = math.radians(degrees)
    return int(cx + rx * math.cos(radians)), int(cy + ry * math.sin(radians))


def _draw_circle(
    pixels: bytearray,
    size: int,
    center: Tuple[int, int],
    radius: int,
    color: Tuple[int, int, int, int],
) -> None:
    cx, cy = center
    radius_sq = radius * radius
    for y in range(max(0, cy - radius), min(size, cy + radius + 1)):
        for x in range(max(0, cx - radius), min(size, cx + radius + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius_sq:
                _set_pixel(pixels, size, x, y, color)


def _draw_line(
    pixels: bytearray,
    size: int,
    start: Tuple[int, int],
    end: Tuple[int, int],
    width: int,
    color: Tuple[int, int, int, int],
) -> None:
    x0, y0 = start
    x1, y1 = end
    steps = max(abs(x1 - x0), abs(y1 - y0))
    for step in range(steps + 1):
        t = step / max(1, steps)
        x = int(x0 + (x1 - x0) * t)
        y = int(y0 + (y1 - y0) * t)
        _draw_circle(pixels, size, (x, y), width // 2, color)


def _set_pixel(
    pixels: bytearray,
    size: int,
    x: int,
    y: int,
    color: Tuple[int, int, int, int],
) -> None:
    offset = (y * size + x) * 4
    pixels[offset:offset + 4] = bytes(color)


def _write_png(path: Path, width: int, height: int, rgba: Iterable[int]) -> None:
    rows = []
    raw = bytes(rgba)
    stride = width * 4
    for y in range(height):
        rows.append(b"\x00" + raw[y * stride:(y + 1) * stride])
    payload = b"".join(rows)
    path.write_bytes(
        _png_signature()
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(payload, level=9))
        + _png_chunk(b"IEND", b"")
    )


def _png_signature() -> bytes:
    return b"\x89PNG\r\n\x1a\n"


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


if __name__ == "__main__":
    raise SystemExit(main())
