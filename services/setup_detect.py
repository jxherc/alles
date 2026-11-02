"""fill in mail and calendar servers from an email address, so setup asks for as little as possible.

known providers come from a table checked against each provider's own help page (linked per row).
any other domain is looked up the way mail apps do it:
- thunderbird's isp database, then the domain's own autoconfig file
  (https://wiki.mozilla.org/Thunderbird:Autoconfiguration). only the domain is sent, never the address.
- caldav through the domain's /.well-known/caldav (rfc 6764, section 5).
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import xml.etree.ElementTree as ET

import httpx

_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

# signin: the /api/signin provider that replaces the password for that address (oauth first)
KNOWN = {
    # https://support.google.com/mail/answer/7126229
    "gmail": {
        "domains": ("gmail.com", "googlemail.com"),
        "mail": ("imap.gmail.com", 993, "smtp.gmail.com", 587),
        "caldav": "",
        "signin": "google",
    },
    # https://support.microsoft.com/office/pop-imap-and-smtp-settings-for-outlook-com-d088b986-291d-42b8-9564-9c414e2aa040
    "outlook": {
        "domains": ("outlook.com", "hotmail.com", "live.com", "msn.com"),
        "mail": ("outlook.office365.com", 993, "smtp-mail.outlook.com", 587),
        "caldav": "",
        "signin": "microsoft",
    },
    # https://support.apple.com/102525
    "icloud": {
        "domains": ("icloud.com", "me.com", "mac.com"),
        "mail": ("imap.mail.me.com", 993, "smtp.mail.me.com", 587),
        "caldav": "https://caldav.icloud.com/",
        "signin": "",
    },
    # https://help.yahoo.com/kb/SLN4075.html
    "yahoo": {
        "domains": ("yahoo.com", "ymail.com"),
        "mail": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 587),
        "caldav": "https://caldav.calendar.yahoo.com/",
        "signin": "",
    },
    # https://www.fastmail.help/hc/en-us/articles/1500000278342
    "fastmail": {
        "domains": ("fastmail.com", "fastmail.fm"),
        "mail": ("imap.fastmail.com", 993, "smtp.fastmail.com", 587),
        "caldav": "https://caldav.fastmail.com/dav/",
        "signin": "",
    },
}


def domain_of(email: str) -> str:
    _, _, domain = (email or "").strip().lower().rpartition("@")
    return domain if _DOMAIN.match(domain) else ""


def _known(domain: str) -> tuple[str, dict] | None:
    for key, row in KNOWN.items():
        if domain in row["domains"]:
            return key, row
    return None


def _mail(imap: str, imap_port: int, smtp: str, smtp_port: int, source: str) -> dict:
    return {
        "imap_host": imap,
        "imap_port": imap_port,
        "smtp_host": smtp,
        "smtp_port": smtp_port,
        "source": source,
    }


def _public_host(host: str) -> bool:
    """only look up hosts on the public internet, so a typed domain can't reach the local network."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


def parse_autoconfig(text: str) -> dict | None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    imap = next((s for s in root.iter("incomingServer") if s.get("type") == "imap"), None)
    smtp = next((s for s in root.iter("outgoingServer") if s.get("type") == "smtp"), None)
    if imap is None or smtp is None:
        return None

    def host_port(server, default: int) -> tuple[str, int]:
        host = (server.findtext("hostname") or "").strip()
        try:
            port = int(server.findtext("port") or default)
        except ValueError:
            port = default
        return host, port

    imap_host, imap_port = host_port(imap, 993)
    smtp_host, smtp_port = host_port(smtp, 587)
    if not imap_host or not smtp_host or "%" in imap_host + smtp_host:
        return None
    return _mail(imap_host, imap_port, smtp_host, smtp_port, "autoconfig")


async def _get(client: httpx.AsyncClient, url: str, host: str) -> httpx.Response | None:
    if not await asyncio.to_thread(_public_host, host):
        return None
    try:
        return await client.get(url)
    except httpx.HTTPError:
        return None


async def _lookup_mail(client: httpx.AsyncClient, domain: str) -> dict | None:
    for url, host in (
        (f"https://autoconfig.thunderbird.net/v1.1/{domain}", "autoconfig.thunderbird.net"),
        (f"https://autoconfig.{domain}/mail/config-v1.1.xml", f"autoconfig.{domain}"),
    ):
        response = await _get(client, url, host)
        if response is not None and response.status_code == 200:
            found = parse_autoconfig(response.text)
            if found:
                return found
    return None


async def _lookup_caldav(client: httpx.AsyncClient, domain: str) -> str:
    url = f"https://{domain}/.well-known/caldav"
    response = await _get(client, url, domain)
    # rfc 6764: the well-known address asks to sign in there, or redirects to the real dav path.
    # a site that redirects every page (to www, to a home page) isn't a caldav server
    if response is None:
        return ""
    if response.status_code in (207, 401):
        return url
    if response.status_code in (301, 302, 307, 308):
        location = response.headers.get("location", "").lower()
        if "dav" in location:
            return url
    return ""


async def detect(email: str, *, client: httpx.AsyncClient | None = None) -> dict:
    domain = domain_of(email)
    if not domain:
        return {"domain": "", "provider": "", "signin": "", "mail": None, "caldav": None}
    known = _known(domain)
    if known:
        key, row = known
        return {
            "domain": domain,
            "provider": key,
            "signin": row["signin"],
            "mail": _mail(*row["mail"], "known"),
            "caldav": {"url": row["caldav"], "source": "known"} if row["caldav"] else None,
        }
    own = client or httpx.AsyncClient(timeout=4, follow_redirects=False)
    try:
        mail, caldav = await asyncio.gather(_lookup_mail(own, domain), _lookup_caldav(own, domain))
    finally:
        if client is None:
            await own.aclose()
    return {
        "domain": domain,
        "provider": "domain",
        "signin": "",
        # nothing published: the usual names are the best guess, and the form says it's a guess
        "mail": mail or _mail(f"imap.{domain}", 993, f"smtp.{domain}", 587, "guess"),
        "caldav": {"url": caldav, "source": "well-known"} if caldav else None,
    }
