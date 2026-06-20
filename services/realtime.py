"""10f — realtime (full-duplex) voice gate.

Full-duplex voice needs a realtime-capable provider. We detect one honestly: an ENABLED endpoint
exposing a model whose id matches /realtime/i (the OpenAI Realtime convention). With none configured
the feature is gated off — no fake shell. When present, the session endpoint hands the client the real
connection descriptor it needs to negotiate with the provider.
"""

import re

from core.database import ModelEndpoint

_RT = re.compile(r"realtime", re.I)


def find_realtime_endpoint(db):
    """(endpoint, model) for the first enabled endpoint with a realtime model, else (None, '')."""
    for ep in db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all():  # noqa: E712
        for m in ep.models_list():
            if _RT.search(m or ""):
                return ep, m
    return None, ""


def status(db) -> dict:
    ep, model = find_realtime_endpoint(db)
    if not ep:
        return {
            "available": False,
            "reason": "no realtime-capable model configured — add an endpoint with a "
            "realtime model (e.g. gpt-4o-realtime-preview) to enable live voice",
            "model": "",
        }
    return {"available": True, "reason": "", "model": model}
