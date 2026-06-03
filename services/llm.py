"""
provider-agnostic streaming LLM client.
yields dicts: {"delta": str} | {"thinking": str} | {"done": True, "usage": {...}}
"""
import json, time, asyncio
from typing import AsyncGenerator
import httpx

_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, read=120.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _client


# dead host cooldown — 2 failures → 20s pause
_fail_counts: dict[str, int] = {}
_cooldowns: dict[str, float] = {}

def _host(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname or url
    except Exception:
        return url

def _is_cooling(url: str) -> bool:
    h = _host(url)
    if h in _cooldowns and time.time() < _cooldowns[h]:
        return True
    return False

def _mark_fail(url: str):
    h = _host(url)
    _fail_counts[h] = _fail_counts.get(h, 0) + 1
    if _fail_counts[h] >= 2:
        _cooldowns[h] = time.time() + 20

def _mark_ok(url: str):
    h = _host(url)
    _fail_counts.pop(h, None)
    _cooldowns.pop(h, None)


def detect_provider(base_url: str) -> str:
    url = base_url.lower()
    if "deepseek.com" in url:   return "deepseek"
    if "anthropic.com" in url:  return "anthropic"
    if "openrouter.ai" in url:  return "openrouter"
    if "groq.com" in url:       return "groq"
    if ":11434" in url or "ollama" in url: return "ollama"
    return "openai"  # openai-compat fallback


def _build_openai_payload(messages, model, stream=True, **kw) -> dict:
    p = {"model": model, "messages": messages, "stream": stream}
    if "max_tokens" in kw:   p["max_tokens"] = kw["max_tokens"]
    if "temperature" in kw:  p["temperature"] = kw["temperature"]
    return p

def _build_ollama_payload(messages, model, stream=True, **kw) -> dict:
    return {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": {k: v for k, v in kw.items() if k in ("temperature", "num_predict", "num_ctx")},
    }

def _build_anthropic_payload(messages, model, stream=True, **kw) -> dict:
    # anthropic wants system separate from messages
    sys_msgs = [m for m in messages if m["role"] == "system"]
    other = [m for m in messages if m["role"] != "system"]
    p = {
        "model": model,
        "messages": other,
        "max_tokens": kw.get("max_tokens", 8192),
        "stream": stream,
    }
    if sys_msgs:
        p["system"] = "\n\n".join(m["content"] for m in sys_msgs)
    return p


async def stream_chat(
    messages: list[dict],
    base_url: str,
    api_key: str,
    model: str,
    **kw
) -> AsyncGenerator[dict, None]:

    if _is_cooling(base_url):
        yield {"error": f"endpoint cooling down, retry in a moment"}
        return

    provider = detect_provider(base_url)
    client = _get_client()

    # build url + headers + payload
    if provider == "anthropic":
        url = base_url.rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = _build_anthropic_payload(messages, model, **kw)
    elif provider == "ollama":
        url = base_url.rstrip("/") + "/api/chat"
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        payload = _build_ollama_payload(messages, model, **kw)
    else:
        url = base_url.rstrip("/") + "/v1/chat/completions"
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        payload = _build_openai_payload(messages, model, **kw)

    try:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                _mark_fail(base_url)
                yield {"error": f"HTTP {resp.status_code}: {body.decode('utf-8','replace')[:300]}"}
                return

            _mark_ok(base_url)

            if provider == "ollama":
                async for chunk in _parse_ollama(resp):
                    yield chunk
            elif provider == "anthropic":
                async for chunk in _parse_anthropic(resp):
                    yield chunk
            else:
                async for chunk in _parse_openai(resp):
                    yield chunk

    except httpx.ConnectError as e:
        _mark_fail(base_url)
        yield {"error": f"can't connect to {base_url}: {e}"}
    except Exception as e:
        _mark_fail(base_url)
        yield {"error": str(e)}


async def _parse_openai(resp) -> AsyncGenerator[dict, None]:
    usage = {}
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw == "[DONE]":
            yield {"done": True, "usage": usage}
            return
        try:
            d = json.loads(raw)
        except Exception:
            continue

        if "usage" in d:
            usage = d["usage"]
            continue

        choices = d.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta", {})

        # reasoning/thinking tokens (deepseek-r1, qwen3, etc.)
        thinking = delta.get("reasoning_content") or delta.get("reasoning") or ""
        if thinking:
            yield {"thinking": thinking}

        content = delta.get("content") or ""
        if content:
            yield {"delta": content}

        if choices[0].get("finish_reason"):
            yield {"done": True, "usage": usage}
            return

    yield {"done": True, "usage": usage}


async def _parse_ollama(resp) -> AsyncGenerator[dict, None]:
    async for line in resp.aiter_lines():
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        msg = d.get("message", {})
        content = msg.get("content", "")
        if content:
            yield {"delta": content}
        if d.get("done"):
            yield {"done": True, "usage": {
                "prompt_tokens": d.get("prompt_eval_count", 0),
                "completion_tokens": d.get("eval_count", 0),
            }}
            return
    yield {"done": True, "usage": {}}


async def _parse_anthropic(resp) -> AsyncGenerator[dict, None]:
    usage = {}
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        try:
            d = json.loads(raw)
        except Exception:
            continue
        etype = d.get("type", "")

        if etype == "content_block_delta":
            delta = d.get("delta", {})
            if delta.get("type") == "thinking_delta":
                yield {"thinking": delta.get("thinking", "")}
            elif delta.get("type") == "text_delta":
                yield {"delta": delta.get("text", "")}

        elif etype == "message_delta":
            usage = d.get("usage", {})

        elif etype == "message_stop":
            yield {"done": True, "usage": usage}
            return

    yield {"done": True, "usage": usage}


async def simple_complete(
    messages: list[dict],
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int = 256,
) -> str:
    """non-streaming, returns full text. for things like auto-naming sessions."""
    out = []
    async for chunk in stream_chat(messages, base_url, api_key, model, max_tokens=max_tokens):
        if "delta" in chunk:
            out.append(chunk["delta"])
        elif "error" in chunk:
            break
    return "".join(out).strip()
