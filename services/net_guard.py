"""shared SSRF guard for server-side URL fetches (feeds, calendar ics, research, agent web_fetch).

a single chokepoint that blocks http(s) requests to loopback, link-local/cloud-metadata,
reserved, multicast, and unspecified addresses, so a user/model-supplied url (incl. one
reached via a redirect, since we resolve the host) can't make the server read itself or
the cloud metadata endpoint (169.254.169.254). private LAN addresses are allowed on purpose
for self-hosted installs.
"""

import ipaddress
import socket
from urllib.parse import urlparse


def _blocked_ip(ip_str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # can't parse -> refuse
    # block the addresses that are NEVER a legitimate fetch target: the app itself (loopback), the
    # cloud metadata + link-local range (169.254/16, credential theft), 0.0.0.0, multicast/reserved.
    # private LAN (10/192.168/172.16) is ALLOWED on purpose: this is a self-hosted app and the owner
    # legitimately integrates with their own LAN services (a home calendar server, an internal feed).
    return (
        ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def is_safe_url(url: str) -> bool:
    """True only for an http(s) url whose host resolves without blocked addresses."""
    try:
        resolve_safe_url(url)
    except ValueError:
        return False
    return True


def resolve_safe_url(url: str) -> tuple[object, tuple[str, ...]]:
    """Resolve one allowed integration URL and return the exact validated addresses."""
    try:
        parsed = urlparse((url or "").strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("invalid url")
        parsed.port
    except ValueError as exc:
        raise ValueError("invalid url") from exc
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if _blocked_ip(str(literal)):
            raise ValueError("url host is blocked")
        return parsed, (str(literal),)
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except OSError as exc:
        raise ValueError("url host did not resolve") from exc
    if not infos:
        raise ValueError("url host did not resolve")
    addresses = []
    for *_, sockaddr in infos:
        address = str(sockaddr[0])
        if _blocked_ip(address):
            raise ValueError("url host is blocked")
        normalized = str(ipaddress.ip_address(address))
        if normalized not in addresses:
            addresses.append(normalized)
    return parsed, tuple(addresses)


def resolve_loopback_url(url: str) -> tuple[object, tuple[str, ...]]:
    """Resolve an explicitly local HTTP integration endpoint to loopback only."""
    try:
        parsed = urlparse((url or "").strip())
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("invalid loopback url")
        parsed.port
    except ValueError as exc:
        raise ValueError("invalid loopback url") from exc
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        return parsed, (str(literal),)
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except OSError as exc:
        raise ValueError("loopback url host did not resolve") from exc
    addresses = []
    for *_, sockaddr in infos:
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise ValueError("loopback url host did not resolve") from exc
        if not address.is_loopback:
            raise ValueError("loopback url resolved outside loopback")
        normalized = str(address)
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise ValueError("loopback url host did not resolve")
    return parsed, tuple(addresses)


def is_public_url(url: str) -> bool:
    """Return True only when every resolved address is public.

    Search-result images are fetched on behalf of the browser, so unlike normal
    self-hosted integrations they must never be allowed to reach the owner's LAN.
    """
    try:
        _resolve_public_url(url)
    except ValueError:
        return False
    return True


def _resolve_public_url(url: str) -> tuple[object, tuple[str, ...]]:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError as exc:
        raise ValueError("invalid public url") from exc
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("invalid public url")
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise ValueError("url host is not public")
        return parsed, (str(literal),)
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except OSError:
        raise ValueError("public url host did not resolve")
    if not infos:
        raise ValueError("public url host did not resolve")
    addresses = []
    for *_, sockaddr in infos:
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            raise ValueError("public url host did not resolve")
        if not address.is_global:
            raise ValueError("url host is not public")
        normalized = str(address)
        if normalized not in addresses:
            addresses.append(normalized)
    return parsed, tuple(addresses)


def _bound_url(parsed, address: str) -> str:
    host = f"[{address}]" if ":" in address else address
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or "/"
    if parsed.params:
        path = f"{path};{parsed.params}"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://{host}{port}{path}{query}"


def assert_safe_url(url: str):
    if not is_safe_url(url):
        raise ValueError(f"refusing to fetch a blocked url: {url!r}")


def safe_get(url: str, *, timeout=20, headers=None, max_redirects=6):
    """httpx.get with the SSRF guard re-checked on EVERY redirect hop — plain
    follow_redirects=True is bypassable: a public url can 302 to http://169.254.169.254/
    or localhost and the original-url check never sees it. raises ValueError on a blocked
    hop. returns the final httpx.Response."""
    import httpx

    cur = url
    with httpx.Client(timeout=timeout, follow_redirects=False) as c:
        for _ in range(max_redirects):
            assert_safe_url(cur)
            r = c.get(cur, headers=headers or {})
            loc = r.headers.get("location") if r.is_redirect else None
            if not loc:
                return r
            cur = str(httpx.URL(cur).join(loc))  # resolve relative redirects
    raise ValueError("too many redirects")


async def safe_get_async(url: str, *, timeout=20, headers=None, max_redirects=6):
    """async twin of safe_get — SSRF guard re-checked on every redirect hop."""
    import httpx

    cur = url
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as c:
        for _ in range(max_redirects):
            assert_safe_url(cur)
            r = await c.get(cur, headers=headers or {})
            loc = r.headers.get("location") if r.is_redirect else None
            if not loc:
                return r
            cur = str(httpx.URL(cur).join(loc))
    raise ValueError("too many redirects")


async def safe_get_public_async(
    url: str,
    *,
    timeout=20,
    headers=None,
    max_redirects=6,
    max_bytes: int | None = None,
):
    """Fetch public data from the exact address that passed validation on each hop."""
    import httpx

    cur = url
    for _ in range(max_redirects):
        try:
            parsed, addresses = _resolve_public_url(cur)
        except ValueError as exc:
            raise ValueError(f"refusing to fetch a non-public url: {cur!r}") from exc
        request_headers = dict(headers or {})
        source_host = parsed.hostname or ""
        try:
            ascii_host = source_host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError(f"refusing to fetch an invalid hostname: {source_host!r}") from exc
        host = ascii_host
        if ":" in host:
            host = f"[{host}]"
        if parsed.port:
            host = f"{host}:{parsed.port}"
        request_headers["host"] = host
        last_transport_error = None
        # Each validated hop gets a fresh pool. An IP-bound TLS connection from a
        # previous hostname must never bypass the new hop's SNI verification.
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for address in addresses:
                request = client.build_request(
                    "GET",
                    _bound_url(parsed, address),
                    headers=request_headers,
                    extensions={"sni_hostname": ascii_host.encode("ascii")},
                )
                try:
                    response = await client.send(request, stream=max_bytes is not None)
                    break
                except httpx.TransportError as exc:
                    last_transport_error = exc
            else:
                assert last_transport_error is not None
                raise last_transport_error
            location = response.headers.get("location") if response.is_redirect else None
            if location:
                await response.aclose()
                cur = str(httpx.URL(cur).join(location))
                continue
            if max_bytes is None:
                return response
            content = bytearray()
            try:
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise ValueError("public response exceeded the byte limit")
            finally:
                await response.aclose()
            decoded_headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() not in {"content-encoding", "content-length", "transfer-encoding"}
            }
            return httpx.Response(
                response.status_code,
                headers=decoded_headers,
                content=bytes(content),
                request=httpx.Request("GET", cur),
            )
    raise ValueError("too many redirects")
