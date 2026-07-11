import ipaddress
import json


def _loopback_client(scope: dict) -> bool:
    client = scope.get("client")
    if not client:
        return False
    try:
        return ipaddress.ip_address(client[0]).is_loopback
    except ValueError:
        return False


class PublicHttpsMiddleware:
    """Reject cleartext public traffic while keeping local health checks usable."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope_type = scope.get("type")
        if scope_type not in {"http", "websocket"} or scope.get("scheme") == "https":
            await self.app(scope, receive, send)
            return
        if scope_type == "http" and scope.get("path") == "/health" and _loopback_client(scope):
            await self.app(scope, receive, send)
            return
        if scope_type == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": "HTTPS required"})
            return

        body = json.dumps(
            {"detail": "HTTPS required for public access", "code": "https_required"}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _host_without_port(value: str) -> str | None:
    raw = value.strip().lower()
    if not raw or "@" in raw or "/" in raw:
        return None
    if raw.startswith("["):
        end = raw.find("]")
        if end < 0:
            return None
        host = raw[: end + 1]
        rest = raw[end + 1 :]
        if rest and (not rest.startswith(":") or not rest[1:].isdigit()):
            return None
        if rest and not 0 < int(rest[1:]) <= 65535:
            return None
        return host
    if raw.count(":") > 1:
        return None
    if ":" in raw:
        host, port = raw.rsplit(":", 1)
        if not port.isdigit() or not 0 < int(port) <= 65535:
            return None
        return host.rstrip(".")
    return raw.rstrip(".")


class HostGuardMiddleware:
    """Allow only configured Host headers, including bracketed IPv6 correctly."""

    def __init__(self, app, allowed_hosts: list[str] | tuple[str, ...]):
        self.app = app
        self.allowed_hosts = tuple(host.lower() for host in allowed_hosts)

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        host = _host_without_port(headers.get(b"host", b"").decode("latin-1"))
        allowed = bool(host) and any(
            host == pattern
            or (pattern.startswith("*.") and host.endswith(pattern[1:]))
            for pattern in self.allowed_hosts
        )
        if allowed:
            await self.app(scope, receive, send)
            return
        if scope.get("type") == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": "invalid host"})
            return
        body = b"invalid host header"
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
