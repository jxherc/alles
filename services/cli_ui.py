"""Terminal output for the alles command.

Standard library only: `alles install` runs before alles has its own Python packages. A step
spins with its elapsed time while it runs and keeps a mark when it ends. Piped output, NO_COLOR
and dumb terminals get the same lines as plain text.
"""

from __future__ import annotations

import os
import sys
import threading
import time


class Style:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.tty = bool(getattr(self.stream, "isatty", lambda: False)()) and (
            os.environ.get("TERM") != "dumb"
        )
        self.color = self.tty and "NO_COLOR" not in os.environ
        encoding = (getattr(self.stream, "encoding", "") or "").lower()
        fancy = "utf" in encoding
        self.mark_ok = "✓" if fancy else "+"
        self.mark_bad = "✗" if fancy else "x"
        self.mark_warn = "!"
        self.mark_off = "·" if fancy else "-"
        self.frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" if fancy else "|/-\\"

    def _paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def accent(self, text: str) -> str:
        return self._paint(text, "1;38;5;147")  # alles purple

    def good(self, text: str) -> str:
        return self._paint(text, "32")

    def bad(self, text: str) -> str:
        return self._paint(text, "31")

    def warn(self, text: str) -> str:
        return self._paint(text, "33")

    def dim(self, text: str) -> str:
        return self._paint(text, "2")

    def bold(self, text: str) -> str:
        return self._paint(text, "1")

    def say(self, text: str = "") -> None:
        self.stream.write(text + "\n")
        self.stream.flush()

    def header(self, title: str) -> None:
        self.say()
        self.say(f"  {self.accent('alles')}  {title}")
        self.say()

    def rows(self, pairs: list[tuple[str, str]], *, dim_value: bool = False) -> None:
        width = max((len(key) for key, _ in pairs), default=0) + 2
        for key, value in pairs:
            self.say(f"  {key.ljust(width)}{self.dim(value) if dim_value else value}")

    def check(self, ok: bool | None, label: str, detail: str = "", width: int = 22) -> None:
        """One finished line: ✓ for ok, ✗ for a failure, ! (None) for a warning."""
        if ok is None:
            mark = self.warn(self.mark_warn)
        else:
            mark = self.good(self.mark_ok) if ok else self.bad(self.mark_bad)
        tail = self.dim(detail) if detail else ""
        self.say(f"  {mark} {label.ljust(width)}{tail}".rstrip())


def short_path(path) -> str:
    text = str(path)
    home = os.path.expanduser("~")
    return "~" + text[len(home) :] if home and text.startswith(home + os.sep) else text


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


class Steps:
    """A live list of named steps, driven by `handle(step, state, detail)` progress calls."""

    def __init__(self, labels: dict[str, str], style: Style | None = None):
        self.style = style or Style()
        self.labels = labels
        self.width = max(len(label) for label in labels.values()) + 2
        self.current: str | None = None
        self.detail = ""
        self.started = 0.0
        self.log = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._spinner: threading.Thread | None = None

    def handle(self, step: str, state: str, detail: str = "") -> None:
        if step not in self.labels:
            return
        if state == "start":
            self.start(step, detail)
        elif state == "update":
            with self._lock:
                self.detail = detail
        elif state == "log":
            self.log = detail
        elif state == "done":
            self.finish(True, step, short_path(detail) if detail.startswith(os.sep) else detail)
        elif state == "warn":
            self.finish(None, step, detail)

    def start(self, step: str, detail: str = "") -> None:
        with self._lock:
            self.current, self.detail, self.started = step, detail, time.monotonic()
        if self.style.tty and self._spinner is None:
            self._stop.clear()
            self._spinner = threading.Thread(target=self._spin, daemon=True)
            self._spinner.start()

    def _line(self, frame: str) -> str:
        label = self.labels[self.current or ""]
        tail = " · ".join(
            part for part in (self.detail, _clock(time.monotonic() - self.started)) if part
        )
        return f"  {self.style.accent(frame)} {label.ljust(self.width)}{self.style.dim(tail)}"

    def _spin(self) -> None:
        index = 0
        while not self._stop.wait(0.08):
            with self._lock:
                if self.current is None:
                    continue
                frame = self.style.frames[index % len(self.style.frames)]
                self.style.stream.write("\r\033[K" + self._line(frame))
                self.style.stream.flush()
            index += 1

    def _clear_line(self) -> None:
        if self.style.tty:
            self.style.stream.write("\r\033[K")

    def finish(self, ok: bool | None, step: str | None = None, detail: str = "") -> None:
        with self._lock:
            step = step or self.current
            if step is None:
                return
            self._clear_line()
            self.style.check(ok, self.labels[step], detail, self.width)
            if step == self.current:
                self.current = None

    def fail(self, message: str) -> None:
        """Mark the running step failed and say why, with the tool's last lines when there are any."""
        with self._lock:
            step = self.current
            self._clear_line()
            if step is not None:
                self.style.check(False, self.labels[step], "", self.width)
                self.current = None
        self.close()
        self.style.say()
        self.style.say(f"  {self.style.bad(message)}")
        if self.log:
            self.style.say()
            for line in self.log.splitlines()[-12:]:
                self.style.say(f"    {self.style.dim(line)}")

    def close(self) -> None:
        self._stop.set()
        if self._spinner is not None:
            self._spinner.join(timeout=1)
            self._spinner = None
