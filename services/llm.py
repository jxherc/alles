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
        # proxies come from env (trust_env default) which honors NO_PROXY.
        # passing proxy= explicitly here used to force even localhost
        # (ollama / lm studio) through clash and broke local streaming.
        direct = httpx.AsyncHTTPTransport()
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, read=120.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            mounts={"all://localhost": direct, "all://127.0.0.1": direct, "all://[::1]": direct},
            follow_redirects=True,
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


def clear_cooldown(url: str):
    """drop the fail/cooldown state for a host so a deliberate retry actually hits
    it (the agent loop uses this when retrying a transient error mid-run)."""
    _mark_ok(url)


def detect_provider(base_url: str) -> str:
    url = base_url.lower()
    if "anthropic.com" in url:      return "anthropic"
    if "deepseek.com" in url:       return "deepseek"
    if "openrouter.ai" in url:      return "openrouter"
    if "groq.com" in url:           return "groq"
    if "moonshot.cn" in url:        return "moonshot"
    if "api.x.ai" in url:           return "xai"
    if "googleapis.com" in url:     return "gemini"
    if "mistral.ai" in url:         return "mistral"
    if "perplexity.ai" in url:      return "perplexity"
    if "together.xyz" in url or "togetherai.com" in url: return "together"
    if "fireworks.ai" in url:       return "fireworks"
    if "cohere.ai" in url or "api.cohere.com" in url: return "cohere"
    if "openai.com" in url:         return "openai"
    if ":11434" in url or "ollama" in url: return "ollama"
    return "openai"  # openai-compat fallback


def _normalize_openai_messages(messages: list[dict]) -> list[dict]:
    normalized = []
    for m in messages:
        msg = dict(m)
        if "tool_calls" in msg:
            calls = []
            for tc in msg.get("tool_calls") or []:
                if "function" in tc:
                    calls.append(tc)
                    continue
                calls.append({
                    "id": tc.get("call_id") or tc.get("id") or "",
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": json.dumps(tc.get("args", {})),
                    },
                })
            msg["tool_calls"] = calls
            msg["content"] = msg.get("content") or ""
        normalized.append(msg)
    return normalized


# providers whose OpenAI-compatible API honors stream_options.include_usage, so we
# get token counts back on streamed replies (which the usage page reads). others can
# error on the field, so keep them off it.
_USAGE_OK = {"openai", "deepseek", "openrouter", "groq", "together", "fireworks", "moonshot", "xai"}

def _build_openai_payload(messages, model, stream=True, provider="openai", **kw) -> dict:
    p = {"model": model, "messages": _normalize_openai_messages(messages), "stream": stream}
    if stream and provider in _USAGE_OK:
        p["stream_options"] = {"include_usage": True}
    if "max_tokens" in kw:   p["max_tokens"] = kw["max_tokens"]
    if "temperature" in kw:  p["temperature"] = kw["temperature"]
    if "tools" in kw and kw["tools"]:
        p["tools"] = kw["tools"]
        p["tool_choice"] = "auto"
    return p

def _build_ollama_payload(messages, model, stream=True, **kw) -> dict:
    return {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": {k: v for k, v in kw.items() if k in ("temperature", "num_predict", "num_ctx")},
    }

def _anthropic_blocks(content):
    """convert openai-style content (str or list with image_url) to anthropic blocks"""
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        t = b.get("type")
        if t == "text":
            out.append({"type": "text", "text": b.get("text", "")})
        elif t == "image_url":
            url = (b.get("image_url") or {}).get("url", "")
            if url.startswith("data:"):
                try:
                    head, data = url.split(",", 1)
                    media = head.split(":", 1)[1].split(";", 1)[0]
                    out.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
                except Exception:
                    pass
            elif url:
                out.append({"type": "image", "source": {"type": "url", "url": url}})
    return out


def _build_anthropic_payload(messages, model, stream=True, **kw) -> dict:
    sys_msgs = [m for m in messages if m["role"] == "system"]
    other = []
    for m in messages:
        if m["role"] == "system":
            continue
        # convert tool results from openai format to anthropic format
        if m["role"] == "tool":
            other.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""), "content": m["content"]}]
            })
        elif "tool_calls" in m:
            content = []
            if m.get("content"):
                content.append({"type": "text", "text": m["content"]})
            for tc in m["tool_calls"]:
                content.append({"type": "tool_use", "id": tc["call_id"], "name": tc["name"], "input": tc["args"]})
            other.append({"role": "assistant", "content": content})
        elif isinstance(m.get("content"), list):
            other.append({"role": m["role"], "content": _anthropic_blocks(m["content"])})
        else:
            other.append(m)
    p = {
        "model": model,
        "messages": other,
        "max_tokens": kw.get("max_tokens", 8192),
        "stream": stream,
    }
    if sys_msgs:
        p["system"] = "\n\n".join(m["content"] for m in sys_msgs)
    if "temperature" in kw:
        p["temperature"] = kw["temperature"]
    if kw.get("tools"):
        # convert openai tool format to anthropic format
        p["tools"] = [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
            }
            for t in kw["tools"]
        ]
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
        payload = _build_openai_payload(messages, model, provider=provider, **kw)

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
    # tool call accumulator: index -> {id, name, args_chunks}
    tool_acc: dict[int, dict] = {}

    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw == "[DONE]":
            # emit any accumulated tool calls before done
            for idx in sorted(tool_acc):
                tc = tool_acc[idx]
                try:
                    args = json.loads("".join(tc["args"]))
                except Exception:
                    args = {}
                yield {"tool_call": {"call_id": tc["id"], "name": tc["name"], "args": args}}
            yield {"done": True, "usage": usage}
            return
        try:
            d = json.loads(raw)
        except Exception:
            continue

        if "usage" in d and not d.get("choices"):
            usage = d["usage"]
            continue

        choices = d.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta", {})

        # reasoning tokens (deepseek-r1, qwen3, etc.)
        thinking = delta.get("reasoning_content") or delta.get("reasoning") or ""
        if thinking:
            yield {"thinking": thinking}

        content = delta.get("content") or ""
        if content:
            yield {"delta": content}

        # accumulate tool calls
        for tc_delta in (delta.get("tool_calls") or []):
            idx = tc_delta.get("index", 0)
            if idx not in tool_acc:
                tool_acc[idx] = {"id": "", "name": "", "args": []}
            if tc_delta.get("id"):
                tool_acc[idx]["id"] = tc_delta["id"]
            fn = tc_delta.get("function", {})
            if fn.get("name"):
                tool_acc[idx]["name"] = fn["name"]
            if fn.get("arguments"):
                tool_acc[idx]["args"].append(fn["arguments"])

        fr = choices[0].get("finish_reason")
        if fr and fr != "tool_calls":
            # emit tool calls if finish_reason came before [DONE]
            for idx in sorted(tool_acc):
                tc = tool_acc[idx]
                try:
                    args = json.loads("".join(tc["args"]))
                except Exception:
                    args = {}
                yield {"tool_call": {"call_id": tc["id"], "name": tc["name"], "args": args}}
            tool_acc.clear()
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
    # tool use accumulator: block_idx -> {id, name, input_chunks}
    tool_acc: dict[int, dict] = {}
    cur_idx = 0

    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        try:
            d = json.loads(raw)
        except Exception:
            continue
        etype = d.get("type", "")

        if etype == "content_block_start":
            blk = d.get("content_block", {})
            cur_idx = d.get("index", 0)
            if blk.get("type") == "tool_use":
                tool_acc[cur_idx] = {"id": blk.get("id", ""), "name": blk.get("name", ""), "args": []}

        elif etype == "content_block_delta":
            delta = d.get("delta", {})
            if delta.get("type") == "thinking_delta":
                yield {"thinking": delta.get("thinking", "")}
            elif delta.get("type") == "text_delta":
                yield {"delta": delta.get("text", "")}
            elif delta.get("type") == "input_json_delta":
                if cur_idx in tool_acc:
                    tool_acc[cur_idx]["args"].append(delta.get("partial_json", ""))

        elif etype == "content_block_stop":
            if cur_idx in tool_acc:
                tc = tool_acc.pop(cur_idx)
                try:
                    args = json.loads("".join(tc["args"]))
                except Exception:
                    args = {}
                yield {"tool_call": {"call_id": tc["id"], "name": tc["name"], "args": args}}

        elif etype == "message_delta":
            usage = d.get("usage", {})

        elif etype == "message_stop":
            yield {"done": True, "usage": usage}
            return

    yield {"done": True, "usage": usage}


async def compact_messages(
    messages: list[dict],
    ep,
    model: str,
    target_len: int = 20,
) -> list[dict]:
    """summarize old messages when context is too long"""
    # filter out the system message
    sys_msgs = [m for m in messages if m["role"] == "system"]
    chat_msgs = [m for m in messages if m["role"] != "system"]

    if len(chat_msgs) <= target_len:
        return messages

    keep = chat_msgs[-(target_len // 2):]
    summarize = chat_msgs[:-(target_len // 2)]

    conv_text = "\n".join(f"{m['role']}: {m['content'][:300]}" for m in summarize)
    summary = await simple_complete(
        [
            {"role": "system", "content": "Summarize this conversation history in 200 words or less. Be factual and concise."},
            {"role": "user", "content": conv_text},
        ],
        ep.base_url, ep.api_key, model, max_tokens=300,
    )
    compact_sys = {"role": "system", "content": f"[conversation summary]: {summary}"}
    return sys_msgs + [compact_sys] + keep


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
