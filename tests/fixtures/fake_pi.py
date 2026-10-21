"""a stand-in for `pi --mode rpc` and `omp --mode rpc`: same jsonl records, real session
files, no model. omp's flags (--model provider/model, --resume, --approval-mode) work too.

a prompt reads back as one tool call (read) and one answer. "slow" in the prompt keeps the
run open until abort; "ask" sends a confirm dialog first.
"""

import json
import os
import re
import sys
import time
import uuid
from datetime import UTC, datetime

args = sys.argv[1:]


def flag(name):
    return args[args.index(name) + 1] if name in args else None


provider, model = flag("--provider"), flag("--model")
if provider is None and model and "/" in model:  # omp: --model provider/model
    provider, model = model.split("/", 1)
session_file = flag("--session") or flag("--resume")
settled = "session_settled" if "--approval-mode" in args else "agent_settled"
if session_file:
    head = json.loads(open(session_file).readline())
    session_id = head["id"]
else:
    session_id = str(uuid.uuid4())
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S-000Z")
    session_file = os.path.join(flag("--session-dir"), f"{stamp}_{session_id}.jsonl")
    with open(session_file, "w") as handle:
        if settled == "session_settled":  # omp starts its files with a title line
            handle.write(json.dumps({"type": "title", "v": 1, "title": ""}) + "\n")
        header = {"type": "session", "version": 3, "id": session_id, "cwd": os.getcwd()}
        handle.write(json.dumps({**header, "timestamp": datetime.now(UTC).isoformat()}) + "\n")
        handle.write(
            json.dumps(
                {
                    "type": "model_change",
                    "id": uuid.uuid4().hex[:8],
                    "parentId": None,
                    "provider": provider,
                    "modelId": model,
                }
            )
            + "\n"
        )

last = None
with open(session_file) as handle:
    for line in handle:
        entry = json.loads(line)
        last = entry.get("id") if entry.get("type") != "session" else last


def out(record):
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()


def save(message):
    global last
    entry = {"type": "message", "id": uuid.uuid4().hex[:8], "parentId": last, "message": message}
    last = entry["id"]
    with open(session_file, "a") as handle:
        handle.write(json.dumps(entry) + "\n")


def reply(request, data=None, ok=True, error=""):
    record = {"id": request.get("id"), "type": "response", "command": request["type"]}
    out({**record, "success": ok, **({"data": data} if ok else {"error": error})})


def run(text):
    out({"type": "agent_start"})
    save({"role": "user", "content": [{"type": "text", "text": text}]})
    call = {"type": "toolCall", "id": "call-1", "name": "read", "arguments": {"path": "notes.txt"}}
    tool_message = {"role": "assistant", "content": [call], "usage": {"output": 5}}
    out({"type": "message_end", "message": tool_message})
    save(tool_message)
    start = {"type": "tool_execution_start", "toolCallId": "call-1", "toolName": "read"}
    out({**start, "args": {"path": "notes.txt"}})
    result = {"content": [{"type": "text", "text": "hello from notes"}]}
    out({"type": "tool_execution_end", "toolCallId": "call-1", "result": result, "isError": False})
    save({"role": "toolResult", "toolCallId": "call-1", "content": result["content"]})
    for word in ["done ", "with ", text]:
        time.sleep(0.15)
        update = {"type": "text_delta", "contentIndex": 0, "delta": word}
        out({"type": "message_update", "assistantMessageEvent": update})
    answer = {
        "role": "assistant",
        "content": [{"type": "text", "text": "done with " + text}],
        "usage": {"input": 100, "output": 30, "cacheRead": 300, "cacheWrite": 0},
    }
    out({"type": "message_end", "message": answer})
    save(answer)
    out({"type": "agent_end"})
    out({"type": settled})


busy = False
handled = []
# a model with "think" in its name takes effort levels, like a reasoning model in models.json
thinking = flag("--thinking") or "medium"


def levels():
    return ["off", "minimal", "low", "medium", "high"] if "think" in (model or "") else ["off"]


for raw in sys.stdin:
    request = json.loads(raw)
    kind = request["type"]
    if kind == "get_state":
        level = thinking if thinking in levels() else "off"
        reply(
            request,
            {
                "sessionId": session_id,
                "sessionFile": session_file,
                "isStreaming": busy,
                "thinkingLevel": level,
            },
        )
    elif kind == "get_available_thinking_levels":
        reply(request, {"levels": levels()})
    elif kind == "set_thinking_level":
        thinking = request["level"]
        reply(request)
    elif kind == "get_commands":
        commands = [
            {"name": "fix-tests", "description": "Fix failing tests", "source": "prompt"},
            {"name": "alles-secret", "description": "internal", "source": "extension"},
        ]
        reply(request, {"commands": commands})
    elif kind == "compact":
        reply(
            request,
            {
                "summary": "kept: " + (request.get("customInstructions") or "everything"),
                "tokensBefore": 9000,
                "estimatedTokensAfter": 1200,
            },
        )
    elif kind == "prompt" and request["message"].startswith("/"):
        # extension commands (alles's /alles-secret) are handled without a model or a saved message
        handled.append(request["message"])
        reply(request, {"disposition": "handled"})
    elif kind == "prompt":
        text = request["message"]
        if busy and not request.get("streamingBehavior"):
            reply(request, ok=False, error="agent is streaming")
            continue
        reply(request, {"disposition": "queued" if busy else "started"})
        if re.search(r"\bask\b", text):
            out(
                {"type": "extension_ui_request", "id": "q1", "method": "confirm", "title": "trust?"}
            )
            answer = json.loads(sys.stdin.readline())
            text = f"{text} trusted={answer.get('confirmed')}"
        if re.search(r"\bslow\b", text):
            busy = True
            out({"type": "agent_start"})
            save({"role": "user", "content": [{"type": "text", "text": text}]})
            continue
        run(text)
    elif kind == "abort":
        if busy:
            busy = False
            out({"type": "agent_end"})
            out({"type": settled})
        reply(request)
    elif kind == "set_model":
        provider, model = request["provider"], request["modelId"]
        reply(request, {"id": model})
    elif kind == "get_session_stats":
        tokens = {"input": 100, "output": 35, "cacheRead": 300, "cacheWrite": 0}
        usage = {"percent": 4, "tokens": 4000, "contextWindow": 100000}
        reply(request, {"tokens": tokens, "cost": 0, "contextUsage": usage, "toolCalls": 1})
    else:
        reply(request, ok=False, error=f"unknown command {kind}")
