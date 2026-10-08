"""Keep the local app on the latest origin/main.

The launcher runs the app straight from the repo checkout, so a merged PR only
reaches the app after a pull and a restart. With ``app --auto-update`` the app
fast-forwards a clean ``main`` checkout and re-execs itself once it is idle.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

REMOTE = "origin"
BRANCH = "main"
CHECK_INTERVAL_SECONDS = 120.0
PENDING_RESTART_POLL_SECONDS = 5.0
GIT_TIMEOUT_SECONDS = 30.0


def _git(repo_root: Path, *args: str) -> Optional[str]:
    env = dict(os.environ)
    # Never block on a credential or passphrase prompt from a background thread.
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def current_build(repo_root: Path) -> Optional[str]:
    return _git(repo_root, "rev-parse", "--short", "HEAD")


def pull_if_behind(repo_root: Path) -> Optional[str]:
    """Fast-forward a clean main checkout to origin/main.

    Returns the new short sha when HEAD moved, else None. A checkout on another
    branch or with tracked changes is someone's work in progress, so it is left
    alone; untracked files do not block the update.
    """
    if _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD") != BRANCH:
        return None
    if _git(repo_root, "status", "--porcelain", "--untracked-files=no") != "":
        return None
    if _git(repo_root, "fetch", "--quiet", REMOTE, BRANCH) is None:
        return None
    head = _git(repo_root, "rev-parse", "HEAD")
    upstream = _git(repo_root, "rev-parse", f"{REMOTE}/{BRANCH}")
    if head is None or upstream is None or head == upstream:
        return None
    # A local main that is ahead of origin also differs from it, and
    # `merge --ff-only` is then a successful no-op; reporting that as an update
    # would restart the app in a loop.
    if _git(repo_root, "merge-base", "--is-ancestor", head, upstream) is None:
        return None
    if _git(repo_root, "merge", "--ff-only", "--quiet", upstream) is None:
        return None
    if _git(repo_root, "rev-parse", "HEAD") != upstream:
        return None
    return current_build(repo_root)


def reexec_current_process() -> None:
    """Replace this process with a fresh run of the same command line."""
    argv = list(getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv])
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, *argv[1:]])


class AutoUpdater:
    """Background loop: pull when idle, then restart when still idle."""

    def __init__(
        self,
        repo_root: Path,
        *,
        is_idle: Callable[[], bool],
        restart: Callable[[], None] = reexec_current_process,
        pull: Callable[[Path], Optional[str]] = pull_if_behind,
        interval_seconds: float = CHECK_INTERVAL_SECONDS,
    ) -> None:
        self.repo_root = Path(repo_root)
        self._is_idle = is_idle
        self._restart = restart
        self._pull = pull
        self._interval_seconds = interval_seconds
        self._pending_build: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="auto-update", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def check_once(self) -> bool:
        """Returns True when it restarted (only observable with a fake restart)."""
        if not self._is_idle():
            return False
        if self._pending_build is None:
            self._pending_build = self._pull(self.repo_root)
            if self._pending_build is None:
                return False
        # Pulling takes a few seconds; the user may have started something.
        if not self._is_idle():
            return False
        print(f"Updated to {self._pending_build}; restarting the local app", flush=True)
        self._restart()
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            self.check_once()
            wait = (
                PENDING_RESTART_POLL_SECONDS
                if self._pending_build is not None
                else self._interval_seconds
            )
            if self._stop.wait(wait):
                return
