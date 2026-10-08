"""
endpoint routing. when 'prefer_local_models' is on, the fallback endpoint
resolution favors a local model (ollama / localhost) so cheap/private chats stay
on-device — but only if a local endpoint actually exists, otherwise nothing
changes. an explicitly chosen endpoint on a session always wins over this.
"""

import ipaddress
from urllib.parse import urlsplit

_LOCAL_NAMES = {"localhost", "ollama"}


def is_local_endpoint(ep) -> bool:
    url = (getattr(ep, "base_url", "") or "").strip()
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if host in _LOCAL_NAMES:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def pick_endpoint(endpoints, prefer_local: bool = False):
    enabled = [e for e in endpoints if getattr(e, "enabled", True)]
    if not enabled:
        return None
    if prefer_local:
        local = next((e for e in enabled if is_local_endpoint(e)), None)
        if local:
            return local
    return enabled[0]
