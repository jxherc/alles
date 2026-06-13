"""
Lightweight background-job registry + event bus.

Jobs are async callables the app's periodic loop runs on an interval. The event
bus lets features react to things happening elsewhere ('doc.saved', etc.) without
importing each other. Both are process-local and best-effort: a failing job or
handler is logged and never stalls the others.
"""
import asyncio
import logging
import time
from dataclasses import dataclass

log = logging.getLogger("alles.jobs")


@dataclass
class Job:
    name: str
    fn: object            # async callable () -> awaitable
    interval: float       # seconds between runs
    last_run: float = 0.0
    enabled: bool = True
    runs: int = 0
    fails: int = 0


_jobs: dict[str, Job] = {}


def register(name, fn, interval, *, run_at_start=True):
    """register (or replace) an interval job. run_at_start=False makes it wait one
    full interval before its first run."""
    # -inf → always due on the first run_due tick; else start the clock now so it
    # waits a full interval before firing
    last = float("-inf") if run_at_start else time.monotonic()
    _jobs[name] = Job(name=name, fn=fn, interval=float(interval), last_run=last)
    return _jobs[name]


def unregister(name):
    _jobs.pop(name, None)


def all_jobs():
    return list(_jobs.values())


async def run_due(now=None):
    """run every job whose interval has elapsed. returns how many ran."""
    now = time.monotonic() if now is None else now
    ran = 0
    for job in list(_jobs.values()):
        if not job.enabled or (now - job.last_run) < job.interval:
            continue
        job.last_run = now
        try:
            await job.fn()
            job.runs += 1
            ran += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:
            job.fails += 1
            log.warning(f"job '{job.name}' failed: {e}")
    return ran


# ── event bus ────────────────────────────────────────────────────────────────
_handlers: dict[str, list] = {}


def on(event, handler):
    _handlers.setdefault(event, []).append(handler)


def off(event, handler):
    if event in _handlers:
        _handlers[event] = [h for h in _handlers[event] if h is not handler]


async def emit(event, **data):
    """fire every handler for an event. sync + async handlers both fine; one bad
    handler doesn't stop the rest. returns how many ran."""
    ran = 0
    for h in list(_handlers.get(event, [])):
        try:
            r = h(**data)
            if asyncio.iscoroutine(r):
                await r
            ran += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"handler for event '{event}' failed: {e}")
    return ran
