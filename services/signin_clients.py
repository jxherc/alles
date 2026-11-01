"""the client ids alles ships for the two providers that need no secret.

github's device flow and microsoft's device code flow are public-client flows: there is a
client id, no client secret. the owner registers each application once. until that happens
the id is empty and the provider is "not ready" with a plain reason, never an error.

override order: environment, then the saved setting, then the shipped default. client ids
are not secrets, so they are safe in a settings response or a log.
"""

from __future__ import annotations

import os

# fill these in once the owner has registered the two applications
DEFAULT_GITHUB_CLIENT_ID = ""
DEFAULT_MICROSOFT_CLIENT_ID = ""


def _chosen(setting: str, env: str, default: str) -> str:
    from_env = os.environ.get(env, "").strip()
    if from_env:
        return from_env
    try:
        from core.settings import load_settings

        saved = str(load_settings().get(setting, "") or "").strip()
    except Exception:
        saved = ""
    return saved or default


def github_client_id() -> str:
    return _chosen("signin_github_client_id", "ALLES_GITHUB_CLIENT_ID", DEFAULT_GITHUB_CLIENT_ID)


def microsoft_client_id() -> str:
    return _chosen(
        "signin_microsoft_client_id",
        "ALLES_MICROSOFT_CLIENT_ID",
        DEFAULT_MICROSOFT_CLIENT_ID,
    )
