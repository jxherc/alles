"""andromeda's translator: libretranslate, an open-source machine translation engine.

libretranslate (agpl, built on argos translate's open models) runs as its own service, by default
on this machine at http://127.0.0.1:5000. it is not a language model: a short phrase comes back in
a fraction of a second, and the text only travels to that service. `andromeda_translate_url`
points alles at another instance, such as one on the tailnet.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit

import httpx

DEFAULT_URL = "http://127.0.0.1:5000"
SOURCE = "LibreTranslate"

# alles language names -> libretranslate codes
CODES = {
    "arabic": "ar",
    "chinese": "zh-Hans",
    "dutch": "nl",
    "english": "en",
    "french": "fr",
    "german": "de",
    "greek": "el",
    "hebrew": "he",
    "hindi": "hi",
    "indonesian": "id",
    "italian": "it",
    "japanese": "ja",
    "korean": "ko",
    "persian": "fa",
    "polish": "pl",
    "portuguese": "pt",
    "russian": "ru",
    "spanish": "es",
    "swedish": "sv",
    "thai": "th",
    "turkish": "tr",
    "ukrainian": "uk",
    "vietnamese": "vi",
}
NAMES = {code: name for name, code in CODES.items()} | {"zh": "chinese"}
_LANGUAGES: dict = {"at": 0.0, "url": "", "names": []}


class Unavailable(Exception):
    """the translator service is not running or not answering."""


def base_url(settings: dict) -> str:
    value = str(settings.get("andromeda_translate_url") or "").strip().rstrip("/")
    return value or DEFAULT_URL


def valid_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and parts.username is None
        and parts.password is None
    )


async def _call(settings: dict, path: str, payload: dict | None = None, timeout: float = 6):
    url = base_url(settings) + path
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = (
                await client.post(url, json=payload)
                if payload is not None
                else await client.get(url)
            )
    except httpx.HTTPError as exc:
        raise Unavailable(str(exc)) from exc
    if response.status_code >= 500 or response.status_code in (404, 429):
        raise Unavailable(f"http {response.status_code}")
    return response


async def languages(settings: dict) -> list[str]:
    """the languages this instance has models for, as alles names, cached for ten minutes."""
    url = base_url(settings)
    if _LANGUAGES["url"] == url and time.monotonic() - _LANGUAGES["at"] < 600:
        return _LANGUAGES["names"]
    response = await _call(settings, "/languages", timeout=4)
    names = sorted({NAMES[row["code"]] for row in response.json() if row.get("code") in NAMES})
    _LANGUAGES.update(at=time.monotonic(), url=url, names=names)
    return names


async def translate(text: str, source: str, target: str, settings: dict) -> dict:
    """{"translation", "from", "from_detected"}. raises Unavailable when the service is down,
    ValueError when it refuses the language pair or the text."""
    if target not in CODES or (source and source not in CODES):
        raise ValueError("that language isn't available in the translator")
    response = await _call(
        settings,
        "/translate",
        {
            "q": text,
            "source": CODES[source] if source else "auto",
            "target": CODES[target],
            "format": "text",
        },
    )
    body = response.json() if response.content else {}
    if response.status_code >= 400:
        raise ValueError(str(body.get("error") or "the translator refused this text")[:200])
    detected = (body.get("detectedLanguage") or {}).get("language") or ""
    return {
        "translation": str(body.get("translatedText") or "").strip()[:5000],
        "from": source or NAMES.get(detected, detected),
        "from_detected": not source,
    }
