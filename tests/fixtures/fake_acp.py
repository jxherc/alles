"""a stand-in ACP harness: json-rpc over stdio, no model.

a prompt streams two text chunks, one finished tool call and a usage update, then ends the turn.
"ask" in the prompt sends a permission request first; "slow" waits for session/cancel.
"""

import json
import sys
import threading
import uuid

state = {"cancel": threading.Event(), "model": "fake-small", "next": 1000}
pending = {}


def out(record):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", **record}) + "\n")
    sys.stdout.flush()


def update(session_id, body):
    out({"method": "session/update", "params": {"sessionId": session_id, "update": body}})


def options():
    return [
        {
            "id": "model",
            "name": "Model",
            "category": "model",
            "type": "select",
            "currentValue": state["model"],
            "options": [
                {"value": "fake-small", "name": "Fake small"},
                {"value": "fake-large", "name": "Fake large"},
            ],
        }
    ]


def ask(session_id):
    state["next"] += 1
    request_id = state["next"]
    waiter = threading.Event()
    pending[request_id] = [waiter, None]
    out(
        {
            "id": request_id,
            "method": "session/request_permission",
            "params": {
                "sessionId": session_id,
                "toolCall": {"toolCallId": "t0", "title": "run make test", "kind": "execute"},
                "options": [
                    {"optionId": "yes", "name": "Allow once", "kind": "allow_once"},
                    {"optionId": "no", "name": "Reject", "kind": "reject_once"},
                ],
            },
        }
    )
    waiter.wait(10)
    return pending.pop(request_id)[1]


def prompt(request_id, params):
    session_id = params["sessionId"]
    text = "".join(block.get("text", "") for block in params["prompt"])
    reason = "end_turn"
    if "ask" in text:
        answer = ask(session_id) or {}
        text += f" allowed={answer.get('outcome', {}).get('optionId')}"
    if "slow" in text:
        state["cancel"].wait(10)
        state["cancel"].clear()
        reason = "cancelled"
    else:
        update(
            session_id,
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "looking. "},
            },
        )
        update(
            session_id,
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "t1",
                "title": "Read notes.txt",
                "kind": "read",
                "status": "pending",
                "rawInput": {"path": "notes.txt"},
            },
        )
        update(
            session_id,
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "t1",
                "status": "completed",
                "content": [
                    {"type": "content", "content": {"type": "text", "text": "hello from notes"}}
                ],
            },
        )
        update(
            session_id,
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": f"done with {text} on {state['model']}"},
            },
        )
        update(session_id, {"sessionUpdate": "usage_update", "used": 2000, "size": 100000})
    out({"id": request_id, "result": {"stopReason": reason}})


for raw in sys.stdin:
    message = json.loads(raw)
    method, request_id, params = (
        message.get("method"),
        message.get("id"),
        message.get("params") or {},
    )
    if method is None and request_id in pending:
        pending[request_id][1] = message.get("result")
        pending[request_id][0].set()
    elif method == "initialize":
        out(
            {
                "id": request_id,
                "result": {
                    "protocolVersion": 1,
                    "agentCapabilities": {
                        "loadSession": False,
                        "sessionCapabilities": {"resume": {}},
                    },
                    "authMethods": [],
                },
            }
        )
    elif method in ("session/new", "session/resume"):
        session_id = params.get("sessionId") or str(uuid.uuid4())
        out({"id": request_id, "result": {"sessionId": session_id, "configOptions": options()}})
    elif method == "session/prompt":
        threading.Thread(target=prompt, args=(request_id, params), daemon=True).start()
    elif method == "session/cancel":
        state["cancel"].set()
    elif method == "session/set_config_option":
        state["model"] = params["value"]
        out({"id": request_id, "result": {"configOptions": options()}})
    elif request_id is not None:
        out({"id": request_id, "error": {"code": -32601, "message": f"unknown {method}"}})
