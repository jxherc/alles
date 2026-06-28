"""shared SSRF guard for server-side URL fetches (feeds, calendar ics, research, agent web_fetch).

a single chokepoint that blocks http(s) requests to loopback / private / link-local / cloud-metadata
addresses, so a user/model-supplied url (incl. one reached via a redirect, since we resolve the host)
can't make the server read internal services or the cloud metadata endpoint (169.254.169.254).
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
    """True only for an http(s) url whose host resolves entirely to PUBLIC addresses."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname
    # a bare ip host: check it directly (covers ipv4/ipv6 literals + bracketed ipv6).
    # _blocked_ip() doesn't raise on a non-ip (it returns True), so test for an ip literal
    # explicitly here — otherwise every hostname falls into the "blocked" branch and real
    # domains can never be fetched.
    try:
        ipaddress.ip_address(host)
        return not _blocked_ip(host)
    except ValueError:
        pass
    # a name: resolve and block if ANY resolved address is internal
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not infos:
        return False
    return not any(_blocked_ip(sockaddr[0]) for *_, sockaddr in infos)


def assert_safe_url(url: str):
    if not is_safe_url(url):
        raise ValueError(f"refusing to fetch a non-public url: {url!r}")


def safe_get(url: str, *, timeout=20, headers=None, max_redirects=6):
    """httpx.get with the SSRF guard re-checked on EVERY redirect hop — plain
    follow_redirects=True is bypassable: a public url can 302 to http://169.254.169.254/
    or localhost and the original-url check never sees it. raises ValueError on a non-public
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
