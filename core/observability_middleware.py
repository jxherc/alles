"""Streaming-safe request logging and mutation audit middleware."""

import logging
import time

from services import audit, observability

log = logging.getLogger("alles.http")
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class ObservabilityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        started = time.monotonic()
        request_id = observability.new_request_id()
        status = 500

        async def send_with_id(message):
            nonlocal status
            if message.get("type") == "http.response.start":
                status = int(message.get("status", 500))
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            method = scope.get("method", "GET").upper()
            path = observability.route_name(scope)
            duration_ms = round((time.monotonic() - started) * 1000, 3)
            write_request = method in _WRITE_METHODS
            request_log = log.info if write_request or status >= 400 else log.debug
            request_log(
                "request completed",
                extra={
                    "event": "http.request",
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )
            if write_request and scope.get("path", "").startswith("/api/"):
                headers = dict(scope.get("headers") or [])
                audit.record(
                    action=f"http.{method.lower()}",
                    outcome="success" if status < 400 else "denied" if status < 500 else "error",
                    actor=observability.actor_kind(headers),
                    target=path,
                    request_id=request_id,
                    details={"status": status},
                )
