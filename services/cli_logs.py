"""Reading alles's log for `alles logs`: filters, and one readable line per json record.

The filters follow hermes's `hermes logs` (hermes-agent 0.22.2+1885.g20acba0,
hermes_cli/logs.py and hermes_cli/subcommands/logs.py): --level is a floor, --since takes
30m / 1h / 2d, and a line with no time or level of its own (a traceback frame) goes with the
record above it. alles writes one json object per line (services/observability.py JsonFormatter),
so the time, level and logger come from the record instead of a regex.
"""

from __future__ import annotations

import json
import re
from collections import deque
from datetime import UTC, datetime, timedelta

LEVELS = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}
_ALIASES = {"warn": "warning", "err": "error", "fatal": "critical"}


class FilterError(ValueError):
    pass


def level_floor(text: str | None) -> int | None:
    if not text:
        return None
    name = _ALIASES.get(text.lower(), text.lower())
    if name not in LEVELS:
        raise FilterError(f"unknown level '{text}': use debug, info, warning or error")
    return LEVELS[name]


def since_cutoff(text: str | None, now: datetime | None = None) -> datetime | None:
    if not text:
        return None
    match = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", text.lower())
    if not match:
        raise FilterError(f"can't read '{text}': use 30m, 1h or 2d")
    unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[match.group(2)]
    return (now or datetime.now(UTC)) - timedelta(**{unit: int(match.group(1))})


_SERVER_LINE = re.compile(r"(DEBUG|INFO|WARNING|ERROR|CRITICAL):\s+(.*)")


def parse(line: str) -> dict | None:
    """The json record on this line, or None for plain text.

    uvicorn's own lines ("INFO:     Application startup complete.") count as records with a level
    and no time, so --level keeps or drops them too.
    """
    if not line.startswith("{"):
        server = _SERVER_LINE.fullmatch(line)
        if server:
            return {
                "level": server.group(1).lower(),
                "logger": "server",
                "message": server.group(2),
            }
        return None
    try:
        row = json.loads(line)
    except ValueError:
        return None
    return row if isinstance(row, dict) else None


def _when(row: dict) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(row.get("ts", "")))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


class LineFilter:
    """One verdict per record; plain lines after a record share its verdict."""

    def __init__(self, *, level=None, since=None, grep=None):
        self.floor = level_floor(level)
        self.cutoff = since_cutoff(since)
        self.grep = (grep or "").lower() or None
        self._carry: bool | None = None

    @property
    def active(self) -> bool:
        return any(value is not None for value in (self.floor, self.cutoff, self.grep))

    def _record_passes(self, row: dict, line: str) -> bool:
        if self.floor is not None and LEVELS.get(str(row.get("level", "")).lower(), 1) < self.floor:
            return False
        when = _when(row)
        if self.cutoff is not None and when is not None and when < self.cutoff:
            return False
        return self.grep is None or self.grep in line.lower()

    def __call__(self, line: str) -> bool:
        row = parse(line)
        if row is not None:
            self._carry = self._record_passes(row, line)
            return self._carry
        if self._carry is not None:
            return self._carry
        # before the first record its time and level aren't known
        timed = self.floor is not None or self.cutoff is not None
        return not timed and (self.grep is None or self.grep in line.lower())


def last_lines(lines, count: int, keep: LineFilter) -> list[str]:
    """The newest `count` lines that pass, reading the whole file once."""
    return list(deque((line for line in lines if keep(line)), maxlen=max(count, 0)))


def render(line: str, ui) -> str:
    """A json record as `14:02:11  warn   logger  message`; plain lines stay as they are."""
    row = parse(line)
    if row is None:
        return line
    when = _when(row)
    clock = when.astimezone().strftime("%H:%M:%S") if when else "--:--:--"
    level = str(row.get("level", "info")).lower()
    tag = {"warning": "warn", "critical": "crit"}.get(level, level)[:5].ljust(5)
    if LEVELS.get(level, 1) >= LEVELS["error"]:
        tag = ui.bad(tag)
    elif level == "warning":
        tag = ui.warn(tag)
    else:
        tag = ui.dim(tag)
    message = str(row.get("message", ""))
    error = row.get("exception")
    if isinstance(error, dict):
        message = f"{message}  {error.get('type', '')}: {error.get('message', '')}".rstrip(": ")
    logger = str(row.get("logger", ""))
    return f"{ui.dim(clock)}  {tag}  {ui.dim(logger)}  {message}"
