"""a stand-in for `pi --mode rpc`: same jsonl records, real session files, no model.

a prompt reads back as one tool call (read) and one answer. "slow" in the prompt keeps the
run open until abort; "ask" sends a confirm dialog first.
"""

import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime

args = sys.argv[1:]


def flag(name):
    return args[args.index(name) + 1] if name in args else None


provider, model = flag("--provider"), flag("--model")
session_file = flag("--session")
if session_file:
    head = json.loads(open(session_file).readline())
    session_id = head["id"]
else:
    session_id = str(uuid.uuid4())
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S-000Z")
    session_file = os.path.join(flag("--session-dir"), f"{stamp}_{session_id}.jsonl")
    with open(session_file, "w") as handle:
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
    out({"type": "tool_execution_start", "toolCallId": "call-1", "toolName": "read", "args": {}})
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
    out({"type": "agent_settled"})


busy = False
for raw in sys.stdin:
    request = json.loads(raw)
    kind = request["type"]
    if kind == "get_state":
        reply(request, {"sessionId": session_id, "sessionFile": session_file, "isStreaming": busy})
    elif kind == "prompt":
        text = request["message"]
        if busy and not request.get("streamingBehavior"):
            reply(request, ok=False, error="agent is streaming")
            continue
        reply(request, {"disposition": "queued" if busy else "started"})
        if "ask" in text:
            out(
                {"type": "extension_ui_request", "id": "q1", "method": "confirm", "title": "trust?"}
            )
            answer = json.loads(sys.stdin.readline())
            text = f"{text} trusted={answer.get('confirmed')}"
        if "slow" in text:
            busy = True
            out({"type": "agent_start"})
            save({"role": "user", "content": [{"type": "text", "text": text}]})
            continue
        run(text)
    elif kind == "abort":
        if busy:
            busy = False
            out({"type": "agent_end"})
            out({"type": "agent_settled"})
        reply(request)
    elif kind == "set_model":
        provider, model = request["provider"], request["modelId"]
        reply(request, {"id": model})
    elif kind == "get_session_stats":
        tokens = {"input": 100, "output": 35, "cacheRead": 300, "cacheWrite": 0}
        reply(request, {"tokens": tokens, "cost": 0, "contextUsage": {"percent": 4}})
    else:
        reply(request, ok=False, error=f"unknown command {kind}")
