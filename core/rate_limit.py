import math
import threading
import time

from fastapi import Request

from core.api_errors import ApiError

_events: dict[tuple[str, str], tuple[int, list[float]]] = {}
_lock = threading.Lock()


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check_rate_limit(
    action: str,
    client: str,
    *,
    limit: int,
    window_seconds: int,
    now: float | None = None,
) -> int:
    """Record an attempt and return retry seconds, or zero when allowed."""
    current = time.monotonic() if now is None else now
    cutoff = current - window_seconds
    key = (action, client)
    with _lock:
        if len(_events) > 4096:
            expired = [
                stored_key
                for stored_key, (stored_window, stamps) in _events.items()
                if not stamps or stamps[-1] <= current - stored_window
            ]
            for stored_key in expired:
                _events.pop(stored_key, None)
        _, stored = _events.get(key, (window_seconds, []))
        recent = [stamp for stamp in stored if stamp > cutoff]
        if len(recent) >= limit:
            _events[key] = (window_seconds, recent)
            return max(1, math.ceil(window_seconds - (current - recent[0])))
        recent.append(current)
        _events[key] = (window_seconds, recent)
    return 0


def enforce_rate_limit(
    request: Request,
    action: str,
    *,
    limit: int,
    window_seconds: int,
) -> None:
    retry_after = check_rate_limit(
        action,
        _client_key(request),
        limit=limit,
        window_seconds=window_seconds,
    )
    if retry_after:
        raise ApiError(
            429,
            "rate_limited",
            "too many requests; wait and try again",
            headers={"Retry-After": str(retry_after)},
        )
