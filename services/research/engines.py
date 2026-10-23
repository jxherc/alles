"""the one list of search engines alles can use, plus the owner's custom ones.

every picker and key field reads this, so adding an engine is one entry here
and one request function in search.py.
"""

from __future__ import annotations

import re
import secrets
import urllib.parse
from dataclasses import dataclass


@dataclass(frozen=True)
class Engine:
    id: str
    label: str
    note: str = ""
    key: str | None = None  # flat setting that holds its api key
    extra: tuple[str, ...] = ()  # other settings it needs before it can run
    signup: str = ""


# picker order: the free default first, then roughly best speed + results first
BUILTIN = (
    Engine("duckduckgo", "free search", "no key; asks several engines at once"),
    Engine(
        "exa", "Exa", "fastest with the best results", "exa_api_key", (), "https://dashboard.exa.ai"
    ),
    Engine(
        "brave",
        "Brave",
        "own index; monthly free credit",
        "brave_api_key",
        (),
        "https://brave.com/search/api/",
    ),
    Engine("serper", "Serper", "Google results", "serper_api_key", (), "https://serper.dev"),
    Engine(
        "deepseek",
        "DeepSeek",
        "cheapest per search; new",
        "deepseek_search_api_key",
        (),
        "https://platform.deepseek.com",
    ),
    Engine("firecrawl", "Firecrawl", "", "firecrawl_api_key", (), "https://www.firecrawl.dev"),
    Engine("you", "You.com", "", "you_api_key", (), "https://you.com/platform"),
    Engine(
        "perplexity",
        "Perplexity",
        "",
        "perplexity_api_key",
        (),
        "https://www.perplexity.ai/account/api",
    ),
    Engine("linkup", "Linkup", "", "linkup_api_key", (), "https://app.linkup.so"),
    Engine("jina", "Jina", "", "jina_api_key", (), "https://jina.ai"),
    Engine("tavily", "Tavily", "", "tavily_api_key", (), "https://tavily.com"),
    Engine("searxng", "SearXNG", "your own instance", None, ("searxng_url",)),
    Engine(
        "google_pse",
        "Google PSE",
        "Google ends this API on 2027-01-01",
        "google_pse_api_key",
        ("google_pse_cx",),
    ),
)
BY_ID = {engine.id: engine for engine in BUILTIN}
KEY_SETTINGS = tuple(engine.key for engine in BUILTIN if engine.key)

CUSTOM_PREFIX = "custom-"
CUSTOM_LIMIT = 12
_FIELD = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")
_HEADER = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def configured(engine: Engine, settings: dict) -> bool:
    needs = ([engine.key] if engine.key else []) + list(engine.extra)
    return all(settings.get(name) for name in needs)


def custom_engines(settings: dict) -> list[dict]:
    rows = settings.get("custom_search_engines")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def custom_engine(settings: dict, engine_id: str) -> dict | None:
    return next((row for row in custom_engines(settings) if row.get("id") == engine_id), None)


def known(settings: dict, engine_id: str) -> bool:
    return (
        engine_id in BY_ID or engine_id == "wikipedia" or bool(custom_engine(settings, engine_id))
    )


def listing(settings: dict) -> list[dict]:
    """every engine with what it needs and whether it is ready; never a secret."""
    out = [
        {
            "id": engine.id,
            "label": engine.label,
            "note": engine.note,
            "key_setting": engine.key,
            "extra": list(engine.extra),
            "signup": engine.signup,
            "configured": configured(engine, settings),
            "custom": False,
        }
        for engine in BUILTIN
    ]
    keys = (
        settings.get("custom_search_keys")
        if isinstance(settings.get("custom_search_keys"), dict)
        else {}
    )
    for row in custom_engines(settings):
        out.append(
            {
                "id": row["id"],
                "label": row.get("name") or row["id"],
                "note": "custom",
                "key_setting": None,
                "extra": [],
                "signup": "",
                "configured": True,
                "custom": True,
                "key_configured": bool(keys.get(row["id"])),
                "url": row.get("url", ""),
                "method": row.get("method", "GET"),
                "body": row.get("body", ""),
                "key_header": row.get("key_header", ""),
                "key_prefix": row.get("key_prefix", ""),
                "results": row.get("results", ""),
                "url_field": row.get("url_field", "url"),
                "title_field": row.get("title_field", "title"),
                "snippet_field": row.get("snippet_field", "snippet"),
            }
        )
    return out


def _allowed_address(url: str) -> bool:
    # same rule as searxng: https anywhere, plain http only on this machine
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and host:
        return True
    return parts.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}


def clean_custom(values: dict, existing_id: str | None = None) -> dict:
    """validate one custom engine from the settings form; raises ValueError with a plain reason."""

    def text(name, limit, default=""):
        value = values.get(name, default)
        value = "" if value is None else str(value).strip()
        if len(value) > limit:
            raise ValueError(f"{name.replace('_', ' ')} is too long")
        return value

    name = text("name", 40)
    if not name:
        raise ValueError("give the engine a name")
    url = text("url", 500)
    if "{query}" not in url and "{query}" not in text("body", 2000):
        raise ValueError("put {query} in the address or the body")
    if not _allowed_address(url.replace("{query}", "q").replace("{count}", "8")):
        raise ValueError("the address must start with https://, or http:// for this machine")
    method = text("method", 4, "GET").upper()
    if method not in {"GET", "POST"}:
        raise ValueError("method must be GET or POST")
    body = text("body", 2000) if method == "POST" else ""
    key_header = text("key_header", 64)
    if key_header and not _HEADER.match(key_header):
        raise ValueError("key header can only use letters, numbers and dashes")
    row = {
        "id": existing_id or CUSTOM_PREFIX + secrets.token_hex(4),
        "name": name,
        "url": url,
        "method": method,
        "body": body,
        "key_header": key_header,
        "key_prefix": text("key_prefix", 20),
        "results": text("results", 120),
        "url_field": text("url_field", 60, "url") or "url",
        "title_field": text("title_field", 60, "title") or "title",
        "snippet_field": text("snippet_field", 60, "snippet") or "snippet",
    }
    for field in ("results", "url_field", "title_field", "snippet_field"):
        if row[field] and not _FIELD.match(row[field]):
            raise ValueError(f"{field.replace('_', ' ')} must look like data.items or title")
    return row


def _dig(data, path: str):
    for part in [p for p in path.split(".") if p]:
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


def custom_request(row: dict, key: str, query: str, count: int) -> tuple[str, str, dict, str]:
    """method, url, headers and body for one search; {query} and {count} filled safely."""
    import json

    url = (
        row["url"].replace("{query}", urllib.parse.quote_plus(query)).replace("{count}", str(count))
    )
    body = ""
    if row.get("method") == "POST":
        escaped = json.dumps(query)[1:-1]
        body = (row.get("body") or "").replace("{query}", escaped).replace("{count}", str(count))
    headers = {"user-agent": "aide-research/1.0", "accept": "application/json"}
    if body:
        headers["content-type"] = "application/json"
    if key and row.get("key_header"):
        headers[row["key_header"]] = f"{row.get('key_prefix', '')}{key}"
    return row.get("method", "GET"), url, headers, body


def custom_results(row: dict, data, count: int) -> list[dict]:
    items = _dig(data, row.get("results", "")) if row.get("results") else data
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        link = _dig(item, row.get("url_field") or "url")
        if not isinstance(link, str) or not link.startswith(("http://", "https://")):
            continue
        title = _dig(item, row.get("title_field") or "title")
        snippet = _dig(item, row.get("snippet_field") or "snippet")
        out.append(
            {
                "url": link,
                "title": str(title or link)[:300],
                "snippet": str(snippet or "")[:500],
            }
        )
        if len(out) >= count:
            break
    return out
