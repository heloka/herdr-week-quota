#!/usr/bin/env python3
"""Show this week's used quota in Herdr's Agent sidebar (Windows).

Publishes "7d 40% · reset 1d18h" under the ``week_used`` token from local data:
- Claude: rate_limits that statusline/claude.js saves per session.
- Agy: weekly quota that statusline/agy.js saves per pane.
- Codex: the latest rate_limits in the session's rollout JSONL.
"""

from __future__ import annotations

import json
import msvcrt
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, TextIO

SOURCE = "herdr-week-quota"
TOKEN = "week_used"
POLL_SECONDS = 15
MAX_FAILURES = 5
WEEK_MINUTES = 7 * 24 * 60
TAIL_BYTES = 1024 * 1024
HERDR = os.environ.get("HERDR_BIN_PATH") or "herdr"
STATE = Path(os.environ["LOCALAPPDATA"], SOURCE)
CODEX_SESSIONS = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
codex_paths: dict[str, Path] = {}


def herdr(*args: str) -> dict[str, Any] | None:
    try:
        done = subprocess.run(
            [HERDR, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout or "{}")
    except ValueError:
        return {}


def week_label(used: Any, resets_at: Any) -> str | None:
    try:
        left = int(float(resets_at) - time.time())
        used = float(used)
    except (TypeError, ValueError):
        return None
    if left <= 0:
        return None  # window already reset; wait for a fresh reading
    days, hours, minutes = left // 86400, left % 86400 // 3600, left % 3600 // 60
    reset = f"{days}d{hours}h" if days else f"{hours}h{minutes}m" if hours else f"{minutes}m"
    return f"7d {used:.0f}% · reset {reset}"


def observed_week(agent: str, key: str) -> str | None:
    """Read the {"seven_day": {...}} file an agent's statusLine script saved."""
    name = re.sub(r"[^\w.-]", "_", key)
    try:
        week = json.loads((STATE / agent / f"{name}.json").read_text("utf-8"))["seven_day"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return week_label(week.get("used_percentage"), week.get("resets_at"))


def codex_week(session_id: str) -> str | None:
    path = codex_paths.get(session_id)
    if path is None:
        path = next(CODEX_SESSIONS.glob(f"**/rollout-*-{session_id}.jsonl"), None)
        if path is None:
            return None
        codex_paths[session_id] = path
    try:
        with open(path, "rb") as handle:
            handle.seek(max(0, path.stat().st_size - TAIL_BYTES))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for raw in reversed(lines):
        if '"rate_limits"' not in raw:
            continue
        try:
            limits = json.loads(raw)["payload"]["rate_limits"] or {}
        except (ValueError, KeyError, TypeError):
            continue
        for window in (limits.get("primary"), limits.get("secondary")):
            if window and window.get("window_minutes") == WEEK_MINUTES:
                return week_label(window.get("used_percent"), window.get("resets_at"))
        return None
    return None


def pane_label(pane: dict[str, Any]) -> str | None:
    agent = str(pane.get("agent") or "").lower()
    session_id = str((pane.get("agent_session") or {}).get("value") or "")
    if agent == "claude" and session_id:
        return observed_week("claude", session_id)
    if agent == "codex" and session_id:
        return codex_week(session_id)
    if agent == "agy":
        return observed_week("agy", str(pane["pane_id"]))
    return None


def refresh(published: dict[str, str | None]) -> bool:
    """Publish changed labels; return False when Herdr is unreachable."""
    response = herdr("pane", "list")
    if response is None:
        return False
    live: dict[str, str | None] = {}
    for pane in (response.get("result") or {}).get("panes") or []:
        pane_id = pane.get("pane_id")
        if not pane_id:
            continue
        label = live[pane_id] = pane_label(pane)
        if pane_id in published and published[pane_id] == label:
            continue
        args = ["pane", "report-metadata", pane_id, "--source", SOURCE]
        args += ["--seq", str(time.time_ns())]
        args += ["--token", f"{TOKEN}={label}"] if label else ["--clear-token", TOKEN]
        herdr(*args)
    published.clear()
    published.update(live)
    return True


def try_lock() -> TextIO | None:
    # Fixed path so manual runs and Herdr-launched runs share one daemon.
    STATE.mkdir(parents=True, exist_ok=True)
    handle = open(STATE / "daemon.lock", "a+")
    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


def ensure() -> int:
    probe = try_lock()
    if probe is None:
        return 0  # daemon already running
    probe.seek(0)
    msvcrt.locking(probe.fileno(), msvcrt.LK_UNLCK, 1)
    probe.close()
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "daemon"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS,
    )
    return 0


def daemon() -> int:
    lock = try_lock()
    if lock is None:
        return 0
    published: dict[str, str | None] = {}
    failures = 0
    while failures < MAX_FAILURES:
        failures = 0 if refresh(published) else failures + 1
        time.sleep(POLL_SECONDS)
    return 0


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "ensure"
    if command == "ensure":
        return ensure()
    if command == "daemon":
        return daemon()
    if command == "refresh":
        return 0 if refresh({}) else 1
    print(f"Unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
