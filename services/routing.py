"""
endpoint routing. when 'prefer_local_models' is on, the fallback endpoint
resolution favors a local model (ollama / localhost) so cheap/private chats stay
on-device — but only if a local endpoint actually exists, otherwise nothing
changes. an explicitly chosen endpoint on a session always wins over this.
"""
_LOCAL_HINTS = ("localhost", "127.0.0.1", "0.0.0.0", "11434", "ollama")


def is_local_endpoint(ep) -> bool:
    url = (getattr(ep, "base_url", "") or "").lower()
    return any(h in url for h in _LOCAL_HINTS)


def pick_endpoint(endpoints, prefer_local: bool = False):
    enabled = [e for e in endpoints if getattr(e, "enabled", True)]
    if not enabled:
        return None
    if prefer_local:
        local = next((e for e in enabled if is_local_endpoint(e)), None)
        if local:
            return local
    return enabled[0]
