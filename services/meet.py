"""8b — video-meeting links. no account needed: a Jitsi Meet room is just a URL,
so we mint a hard-to-guess room name from the event title."""

import re
import uuid


def jitsi_url(title: str = "") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "", (title or "").title())[:24] or "Meet"
    return f"https://meet.jit.si/{slug}-{uuid.uuid4().hex[:10]}"
