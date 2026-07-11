import os


def bind_host() -> str:
    """Network address for the Alles server; fresh installs stay on this device."""
    return os.environ.get("ALLES_HOST", "").strip() or "127.0.0.1"
