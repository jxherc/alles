"""
provider-agnostic streaming LLM client.
yields dicts: {"delta": str} | {"thinking": str} | {"done": True, "usage": {...}}
"""

import asyncio
import contextvars
import json
import time
from typing import AsyncGenerator
from urllib.parse import urlsplit, urlunsplit

import httpx

from services.model_capabilities import (
    anthropic_budget_thinking,
    anthropic_effort_api,
    effort_levels,
)

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


def _openai_chat_url(base_url: str) -> str:
    parsed = urlsplit((base_url or "").rstrip("/"))
    path = parsed.path.rstrip("/")
    suffix = (
        "/chat/completions" if path.endswith(("/v1", "/v1beta/openai")) else "/v1/chat/completions"
    )
    return urlunsplit((parsed.scheme, parsed.netloc, path + suffix, "", ""))


def _ollama_chat_url(base_url: str) -> str:
    # an ollama url saved with its openai-style /v1 still means the native api at the root
    parsed = urlsplit((base_url or "").rstrip("/"))
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urlunsplit((parsed.scheme, parsed.netloc, path + "/api/chat", "", ""))


def _provider_error(value) -> str:
    """The provider's own words for an error it sent mid-stream."""
    if isinstance(value, dict):
        value = value.get("message") or value.get("error") or value.get("type") or ""
    text = str(value or "").strip()
    return text[:300] or "the model reported an error"


def detect_provider(base_url: str) -> str:
    url = base_url.lower()
    if "anthropic.com" in url:
        return "anthropic"
    if "deepseek.com" in url:
        return "deepseek"
    if "openrouter.ai" in url:
        return "openrouter"
    if "groq.com" in url:
        return "groq"
    if "moonshot.cn" in url or "moonshot.ai" in url or "kimi.ai" in url:
        return "moonshot"
    if "api.x.ai" in url:
        return "xai"
    if "googleapis.com" in url:
        return "gemini"
    if "mistral.ai" in url:
        return "mistral"
    if "perplexity.ai" in url:
        return "perplexity"
    if "together.xyz" in url or "togetherai.com" in url:
        return "together"
    if "fireworks.ai" in url:
        return "fireworks"
    if "cohere.ai" in url or "api.cohere.com" in url:
        return "cohere"
    if "openai.com" in url:
        return "openai"
    if ":11434" in url or "ollama" in url:
        return "ollama"
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
                calls.append(
                    {
                        "id": tc.get("call_id") or tc.get("id") or "",
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(tc.get("args", {})),
                        },
                    }
                )
            msg["tool_calls"] = calls
            msg["content"] = msg.get("content") or ""
        normalized.append(msg)
    return normalized


# providers whose OpenAI-compatible API honors stream_options.include_usage, so we
# get token counts back on streamed replies (which the usage page reads). others can
# error on the field, so keep them off it.
_USAGE_OK = {"openai", "deepseek", "openrouter", "groq", "together", "fireworks", "moonshot", "xai"}

# thinking budgets for claude models that think only through an explicit budget. which levels a
# model takes, and through which field, comes from services.model_capabilities.
_THINK_BUDGET = {"high": 8000, "xhigh": 16000, "max": 24000}


def reasoning_control_supported(base_url: str, model: str, metadata: dict | None = None) -> bool:
    """Whether Alles can honestly force reasoning on or off for this endpoint.

    Automatic mode remains available for every provider. Explicit controls are
    only offered when this client sends a documented provider field.
    """
    provider = detect_provider(base_url)
    if provider == "deepseek":
        return True
    if provider == "ollama":
        # The tags catalog does not prove the selected model exposes Ollama's
        # thinking capability. Keep explicit on/off unavailable until a live
        # capability probe is part of the endpoint metadata.
        return False
    if provider == "anthropic":
        return anthropic_budget_thinking(model, metadata)
    if provider == "openai":
        # Chat Completions exposes effort for reasoning models, but not a portable
        # explicit on/off field. Keep the separate effort control honest.
        return False
    return False


def _build_openai_payload(messages, model, stream=True, provider="openai", **kw) -> dict:
    p = {"model": model, "messages": _normalize_openai_messages(messages), "stream": stream}
    if stream and provider in _USAGE_OK:
        p["stream_options"] = {"include_usage": True}
    if "max_tokens" in kw:
        p["max_tokens"] = kw["max_tokens"]
    if "temperature" in kw:
        p["temperature"] = kw["temperature"]
    if provider == "deepseek" and isinstance(kw.get("thinking"), bool):
        p["thinking"] = {"type": "enabled" if kw["thinking"] else "disabled"}
    eff = kw.get("effort")
    if eff and eff in effort_levels(provider, model, kw.get("model_metadata")):
        if provider == "openrouter":
            p["reasoning"] = {"effort": eff}
        elif provider in {"openai", "gemini"}:
            p["reasoning_effort"] = eff
    if "tools" in kw and kw["tools"]:
        p["tools"] = kw["tools"]
        p["tool_choice"] = "auto"
    return p


def _build_ollama_payload(messages, model, stream=True, **kw) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": {k: v for k, v in kw.items() if k in ("temperature", "num_predict", "num_ctx")},
    }
    if isinstance(kw.get("thinking"), bool):
        payload["think"] = kw["thinking"]
    return payload


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
                    out.append(
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media, "data": data},
                        }
                    )
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
            other.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.get("tool_call_id", ""),
                            "content": m["content"],
                        }
                    ],
                }
            )
        elif "tool_calls" in m:
            content = []
            if m.get("content"):
                content.append({"type": "text", "text": m["content"]})
            for tc in m["tool_calls"]:
                content.append(
                    {
                        "type": "tool_use",
                        "id": tc["call_id"],
                        "name": tc["name"],
                        "input": tc["args"],
                    }
                )
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
    # only an effort the model takes is sent: through output_config where the model has that
    # field, else as a thinking budget. explicit reasoning wins over the effort default.
    meta = kw.get("model_metadata")
    eff = kw.get("effort")
    if eff not in effort_levels("anthropic", model, meta):
        eff = None
    api = anthropic_effort_api(model, meta)
    if eff and api == "effort":
        p["output_config"] = {"effort": eff}
    thinking = kw.get("thinking")
    should_think = thinking is True or (
        thinking is None and api == "budget" and eff in _THINK_BUDGET
    )
    if should_think and anthropic_budget_thinking(model, meta):
        budget = _THINK_BUDGET.get(eff, 8000)
        p["max_tokens"] = max(p.get("max_tokens", 8192), budget + 2048)
        p["thinking"] = {"type": "enabled", "budget_tokens": budget}
        p.pop("temperature", None)  # anthropic requires temp unset when thinking is on
    if kw.get("tools"):
        # convert openai tool format to anthropic format
        p["tools"] = [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            }
            for t in kw["tools"]
        ]
    return p


async def stream_chat(
    messages: list[dict], base_url: str, api_key: str, model: str, **kw
) -> AsyncGenerator[dict, None]:

    if _is_cooling(base_url):
        yield {"error": "endpoint cooling down, retry in a moment"}
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
        url = _ollama_chat_url(base_url)
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        payload = _build_ollama_payload(messages, model, **kw)
    else:
        url = _openai_chat_url(base_url)
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
            from services.model_auth import runtime_headers

            headers.update(runtime_headers(api_key))
        payload = _build_openai_payload(messages, model, provider=provider, **kw)

    try:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                _mark_fail(base_url)
                yield {"error": f"HTTP {resp.status_code}: {body.decode('utf-8', 'replace')[:300]}"}
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


async def until_stopped(stream, stop_event) -> AsyncGenerator[dict, None]:
    """The provider's chunks until it ends or the owner stops.

    A stop doesn't wait for the next chunk: a model that stalls mid-reply would otherwise keep
    the turn (and its save) going long after the page let go. The pending read is cancelled,
    which closes the provider's response.

    Every read runs in one copied context, so what the stream sets or reads in a contextvar
    holds from one chunk to the next (a fresh task per read would each start from a new copy).
    """
    if not hasattr(stop_event, "wait"):
        # a plain flag with nothing to wait on: read straight through
        async for chunk in stream:
            yield chunk
        return
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()

    async def step():
        return await stream.__anext__()

    stopped = asyncio.ensure_future(stop_event.wait())
    pending = None
    try:
        while True:
            pending = loop.create_task(step(), context=ctx)
            await asyncio.wait({pending, stopped}, return_when=asyncio.FIRST_COMPLETED)
            if not pending.done():
                return
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                return
            yield chunk
    finally:
        stopped.cancel()
        # a read still running (a stop, or this turn being closed) must end before the stream
        # is closed, or closing it fails as "already running"
        if pending is not None and not pending.done():
            pending.cancel()
            # starlette re-sends its cancel on every pass when the page goes away; passing those on
            # cut httpcore's own close short and left the provider connection stuck in the pool
            again = None
            while not pending.done():
                try:
                    await asyncio.wait({pending})
                except asyncio.CancelledError as exc:
                    again = exc
            if again is not None:
                raise again


async def _parse_openai(resp) -> AsyncGenerator[dict, None]:
    usage = {}
    # tool call accumulator: index -> {id, name, args_chunks}
    tool_acc: dict[int, dict] = {}
    # the model said it was finished: a finish reason (or [DONE]). a stream that just stops
    # without one was cut off, not done
    finished = False

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
        if isinstance(d, dict) and d.get("error"):
            # the provider gave up mid-reply and said why
            yield {"error": _provider_error(d["error"])}
            return

        # grab usage whenever it shows up — combined with the finish chunk OR in a
        # trailing usage-only chunk (deepseek/openai/groq send it after finish_reason).
        if d.get("usage"):
            usage = d["usage"]

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
        for tc_delta in delta.get("tool_calls") or []:
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
        if fr:
            finished = True
        if fr and fr != "tool_calls":
            # emit accumulated tool calls now, but DON'T return — OpenAI-compat sends the
            # usage in a trailing chunk after finish_reason (with include_usage), so
            # returning here dropped token counts for every provider but Anthropic.
            for idx in sorted(tool_acc):
                tc = tool_acc[idx]
                try:
                    args = json.loads("".join(tc["args"]))
                except Exception:
                    args = {}
                yield {"tool_call": {"call_id": tc["id"], "name": tc["name"], "args": args}}
            tool_acc.clear()
            # keep reading for the trailing usage chunk + [DONE]
            continue

    # stream ended without a [DONE] sentinel (some openai-compat servers skip it). that's done
    # only if the model gave a finish reason; otherwise the reply was cut off mid-way, and saying
    # done would pass a fragment off as a whole answer (a regenerate would swap the old one out)
    if not finished:
        return
    # flush any tool calls still accumulated, else a tool turn silently emits nothing.
    for idx in sorted(tool_acc):
        tc = tool_acc[idx]
        try:
            args = json.loads("".join(tc["args"]))
        except Exception:
            args = {}
        yield {"tool_call": {"call_id": tc["id"], "name": tc["name"], "args": args}}
    yield {"done": True, "usage": usage}


async def _parse_ollama(resp) -> AsyncGenerator[dict, None]:
    async for line in resp.aiter_lines():
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict) and d.get("error"):
            yield {"error": _provider_error(d["error"])}
            return
        msg = d.get("message", {})
        content = msg.get("content", "")
        if content:
            yield {"delta": content}
        if d.get("done"):
            yield {
                "done": True,
                "usage": {
                    "prompt_tokens": d.get("prompt_eval_count", 0),
                    "completion_tokens": d.get("eval_count", 0),
                },
            }
            return
    # ended without ollama's done: cut off, not finished


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
                tool_acc[cur_idx] = {
                    "id": blk.get("id", ""),
                    "name": blk.get("name", ""),
                    "args": [],
                }

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

        elif etype == "error":
            # e.g. overloaded_error part way through: say so instead of ending quietly
            yield {"error": _provider_error(d.get("error"))}
            return
    # ended without message_stop: cut off, not finished


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

    keep = chat_msgs[-(target_len // 2) :]
    summarize = chat_msgs[: -(target_len // 2)]

    conv_text = "\n".join(f"{m['role']}: {m['content'][:300]}" for m in summarize)
    summary = await simple_complete(
        [
            {
                "role": "system",
                "content": "Summarize this conversation history in 200 words or less. Be factual and concise.",
            },
            {"role": "user", "content": conv_text},
        ],
        ep.base_url,
        ep.api_key,
        model,
        max_tokens=300,
    )
    compact_sys = {"role": "system", "content": f"[conversation summary]: {summary}"}
    return sys_msgs + [compact_sys] + keep


async def simple_complete(
    messages: list[dict],
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int = 256,
    thinking: bool | None = None,
) -> str:
    """non-streaming, returns full text. for things like auto-naming sessions."""
    out = []
    options = {"max_tokens": max_tokens}
    if thinking is not None:
        options["thinking"] = thinking
    async for chunk in stream_chat(messages, base_url, api_key, model, **options):
        if "delta" in chunk:
            out.append(chunk["delta"])
        elif "error" in chunk:
            break
    return "".join(out).strip()
