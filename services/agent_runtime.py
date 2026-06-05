"""
First-class autonomous agent runtime for aide.
"""
import json
import shutil
from typing import AsyncGenerator

from core.database import ModelEndpoint
from services.agent_tools import TOOL_DEFS, stream_execute
from services.agent_state import start_run, record_event, update_run, finish_run
from services.llm import stream_chat


def merge_usage(total: dict, part: dict) -> dict:
    if not part:
        return total
    merged = dict(total or {})
    for k, v in part.items():
        if isinstance(v, (int, float)):
            merged[k] = merged.get(k, 0) + v
        else:
            merged[k] = v
    return merged


def agent_system_note(settings: dict) -> str:
    max_turns = int(settings.get("agent_max_turns", 24) or 24)
    opencode = "installed" if shutil.which("opencode") else (
        "available through npx fallback" if shutil.which("npx.cmd") or shutil.which("npx") else "not available"
    )
    return (
        "Agent mode is enabled. You are aide Agent, a fully autonomous local operator inspired by "
        "Claude Code, Codex, OpenCode, and Odysseus.\n\n"
        "Capabilities: shell, files, exact edits, unified patches, grep/glob, git status/diff/branch/commit, "
        "web search, web fetch, MCP tools, skills, long-term memory, durable run logs, checklists, "
        "and optional OpenCode delegation.\n\n"
        "Operating rules:\n"
        "- Own the whole task. Plan briefly, inspect what you need, act, verify, and report the result.\n"
        "- For multi-step work, call todo_update early and keep it current.\n"
        "- Use tools aggressively when they help. Do not pretend to know local state; inspect it.\n"
        "- For code work, read before editing, prefer apply_patch or exact edits, run relevant checks, inspect git diff, and keep going after tool results.\n"
        "- Use git_status/git_diff before summarizing code changes. Use git_branch/git_commit only when the user asks to create branches or commits.\n"
        "- Use web_search/web_fetch for current information, documentation, or anything likely to have changed.\n"
        "- Use memory_search when preferences or prior context may matter, and memory_add only for durable user facts/preferences.\n"
        "- Use skill_list/skill_load when a task matches a reusable skill or cookbook workflow.\n"
        "- Use mcp_list_tools/mcp_call_tool for external tool surfaces.\n"
        "- Use opencode_run for coding subtasks when OpenCode is installed and a delegated coding pass is useful.\n"
        "- Stream concise progress before and after major tool use. Avoid dumping huge output unless it is the deliverable.\n"
        "- Ask the user only if blocked, if credentials/approval are missing, or if the next action is genuinely risky.\n"
        f"- OpenCode delegation status: {opencode}.\n"
        f"- Continue for up to {max_turns} agent turns, then summarize what remains."
    )


async def run_agent(
    messages: list[dict],
    ep: ModelEndpoint,
    model: str,
    stop_event,
    settings: dict,
    accumulated: list[str],
    thinking_acc: list[str],
    tool_steps: list[dict],
    session_id: str = "",
) -> AsyncGenerator[dict, None]:
    max_turns = int(settings.get("agent_max_turns", 24) or 24)
    run = start_run(session_id=session_id, model=model, max_turns=max_turns, cwd=settings.get("agent_cwd", ""))
    run_id = run["id"]
    yield {"agent_run": {"id": run_id, "status": "running", "max_turns": max_turns}}

    agent_messages = [dict(m) for m in messages]
    if agent_messages and agent_messages[0].get("role") == "system":
        agent_messages[0]["content"] = agent_messages[0].get("content", "").rstrip() + "\n\n" + agent_system_note(settings)
    else:
        agent_messages.insert(0, {"role": "system", "content": agent_system_note(settings)})

    usage = {}
    try:
        for turn in range(max_turns):
            if stop_event.is_set():
                break

            turn_text = []
            tool_calls = []
            llm_kwargs = {"tools": TOOL_DEFS}
            if settings.get("agent_max_tokens"):
                llm_kwargs["max_tokens"] = settings["agent_max_tokens"]

            update_run(run_id, turn=turn + 1)
            record_event(run_id, "turn", {"index": turn + 1, "max": max_turns})
            yield {"agent_turn": {"index": turn + 1, "max": max_turns}}
            async for chunk in stream_chat(
                agent_messages, ep.base_url, ep.api_key, model,
                **llm_kwargs,
            ):
                if stop_event.is_set():
                    break
                if "error" in chunk:
                    record_event(run_id, "error", chunk)
                    yield chunk
                    finish_run(run_id, "error")
                    return
                if "thinking" in chunk:
                    thinking_acc.append(chunk["thinking"])
                    yield chunk
                elif "delta" in chunk:
                    turn_text.append(chunk["delta"])
                    accumulated.append(chunk["delta"])
                    yield chunk
                elif "tool_call" in chunk:
                    tool_calls.append(chunk["tool_call"])
                elif "done" in chunk:
                    usage = merge_usage(usage, chunk.get("usage", {}))

            if stop_event.is_set():
                break

            if not tool_calls:
                yield {"done": True, "usage": usage}
                finish_run(run_id, "done")
                return

            agent_messages.append({
                "role": "assistant",
                "content": "".join(turn_text),
                "tool_calls": tool_calls,
            })

            for call in tool_calls:
                if stop_event.is_set():
                    break
                call_id = call.get("call_id") or f"tool-{turn}"
                name = call.get("name", "")
                args = call.get("args") or {}
                step = {"call_id": call_id, "name": name, "args": args, "output": "", "error": False}
                tool_steps.append(step)
                record_event(run_id, "tool_start", step)
                yield {"tool_start": {"call_id": call_id, "name": name, "args": args}}

                result = {"output": "", "error": False}
                async for event in stream_execute(name, args):
                    if stop_event.is_set():
                        break
                    if event["type"] == "output":
                        text = event.get("text", "")
                        step["output"] = (step.get("output", "") + text)[-12000:]
                        yield {"tool_delta": {"call_id": call_id, "text": text}}
                    elif event["type"] == "result":
                        result = event.get("result", result)

                step["output"] = result.get("output", step.get("output", ""))
                step["error"] = bool(result.get("error"))
                record_event(run_id, "tool_result", step)
                update_run(run_id, tool_steps=tool_steps)
                if name == "todo_update" and not step["error"]:
                    try:
                        todos = json.loads(step["output"]).get("todos", [])
                        update_run(run_id, todos=todos)
                        yield {"todo_update": {"items": todos}}
                    except Exception:
                        pass
                yield {"tool_result": {
                    "call_id": call_id,
                    "name": name,
                    "output": step["output"],
                    "error": step["error"],
                }}
                agent_messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result),
                })

        status = "stopped" if stop_event.is_set() else "turn_limit"
        msg = "\n\nAgent stopped after reaching the turn limit. Send \"continue\" and I can keep going from here."
        if stop_event.is_set():
            msg = "\n\nAgent stopped."
        accumulated.append(msg)
        yield {"delta": msg}
        yield {"done": True, "usage": usage}
        finish_run(run_id, status)
    except Exception as e:
        record_event(run_id, "error", {"error": str(e)})
        finish_run(run_id, "error")
        raise
