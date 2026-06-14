"""
LIVE usage test — actually USES the app against real AI (not the terminal/unit
harness). drives the real running server: a real chat, an agent that writes and
RUNS a small program, real web research, and real app data (sub/day/task/calendar/
memory). everything it creates stays in the db so you SEE it in the UI.

writes evidence (prompts, replies, the generated program + its output, the research
report, ids of created records) to ~/alles-test-evidence/live_<ts>/.

prereq: a server running with auth off, e.g.  AUTH_ENABLED=false PORT=8099 python app.py
run:  python scripts/live_usage.py [base_url]
"""
import io
import os
import sys
import json
import uuid
import time
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8099"
OUT = Path.home() / "alles-test-evidence" / ("live_" + datetime.now().strftime("%Y-%m-%d_%H%M%S"))
OUT.mkdir(parents=True, exist_ok=True)
_log = []


def say(m):
    print(m, flush=True)
    _log.append(m)


def write(name, text):
    (OUT / name).write_text(text, "utf-8")


def endpoints():
    return httpx.get(f"{BASE}/api/models", timeout=20).json()


def pick(preferred=("DeepSeek", "deepseek-v4-pro")):
    """return (endpoint_id, model, name). prefer the user's pick, else anything usable."""
    eps = endpoints()
    order = [preferred, ("Moonshot", "kimi-k2.5"), ("Anthropic", "claude-opus-4-8")]
    for nm, model in order:
        for e in eps:
            if e["name"] == nm and model in (e.get("cached_models") or e.get("models") or []):
                return e["id"], model, nm
    if eps:  # fall back to the first endpoint's first model
        e = eps[0]
        ms = e.get("cached_models") or e.get("models") or []
        if ms:
            return e["id"], ms[0], e["name"]
    return None, None, None


def new_session(name, model, endpoint_id, working_dir="", mode="chat"):
    r = httpx.post(f"{BASE}/api/sessions", json={
        "name": name, "model": model, "endpoint_id": endpoint_id,
        "working_dir": working_dir, "mode": mode}, timeout=20)
    return r.json()["id"]


def stream_chat(session_id, message, mode="chat", permission_mode="", timeout=180):
    """POST /api/chat and consume the SSE; returns (text, tool_steps, error)."""
    text, tools, err = [], [], None
    body = {"session_id": session_id, "message": message, "mode": mode}
    if permission_mode:
        body["permission_mode"] = permission_mode
    with httpx.stream("POST", f"{BASE}/api/chat", json=body, timeout=timeout) as r:
        for line in r.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                ev = json.loads(data)
            except Exception:
                continue
            if "delta" in ev:
                text.append(ev["delta"])
            elif ev.get("type") in ("tool_start", "tool_result") or "tool_step" in ev:
                tools.append(ev)
            elif "error" in ev:
                err = ev["error"]
    return "".join(text), tools, err


# ── phase 1: a real chat ──────────────────────────────────────────────────────
def phase_chat(eid, model, name):
    say(f"\n[1] CHAT via {name}/{model}")
    sid = new_session(f"live-test chat ({name})", model, eid)
    q = "In one sentence, what is alles? Answer plainly."
    text, _, err = stream_chat(sid, q, timeout=90)
    ok = bool(text.strip()) and not err
    say(f"    Q: {q}")
    say(f"    A: {text.strip()[:300] or ('ERROR ' + str(err))}")
    write("01_chat.md", f"# live chat\n\nendpoint: {name}/{model}\nsession: {sid}\n\n**Q:** {q}\n\n**A:**\n\n{text or err}\n")
    return ok, sid


# ── phase 2: the agent writes AND runs a small program ────────────────────────
def phase_agent(eid, model, name):
    say(f"\n[2] AGENT builds + runs a program via {name}/{model}")
    ws = Path(tempfile.mkdtemp(prefix="alles-agent-"))
    sid = new_session(f"live-test agent ({name})", model, eid, working_dir=str(ws), mode="agent")
    task = ("Create a Python file called fizzbuzz.py in the current directory that prints FizzBuzz "
            "for the numbers 1 to 15 (multiples of 3 -> 'Fizz', of 5 -> 'Buzz', of both -> 'FizzBuzz'), "
            "then run it with python and show me the output.")
    say(f"    task: {task}")
    text, tools, err = stream_chat(sid, task, mode="agent", permission_mode="full_auto", timeout=240)
    # the SSE shapes vary; pull the authoritative tool steps from the run record
    try:
        runs = httpx.get(f"{BASE}/api/agent/runs?limit=10", timeout=20).json()
        run = next((r for r in runs if r.get("session_id") == sid), None)
        if run:
            tools = [e for e in run.get("events", []) if e.get("type") in ("tool_start", "tool_result")]
    except Exception:
        pass
    # verify the program got built + actually works
    fizz = ws / "fizzbuzz.py"
    built = fizz.exists()
    run_out = ""
    correct = False
    if built:
        try:
            run_out = subprocess.run([sys.executable, str(fizz)], capture_output=True, text=True, timeout=15).stdout
            correct = "FizzBuzz" in run_out and "Fizz\n" in run_out and "Buzz" in run_out
        except Exception as e:
            run_out = f"(run failed: {e})"
    say(f"    file written: {built}   runs correctly: {correct}")
    say(f"    tool steps captured: {len(tools)}")
    write("02_agent.md",
          f"# live agent — build & run a program\n\nendpoint: {name}/{model}\nsession: {sid}\nworkspace: {ws}\n\n"
          f"**task:** {task}\n\n**file written:** {built}\n**runs correctly:** {correct}\n\n"
          f"**fizzbuzz.py:**\n```python\n{fizz.read_text() if built else '(not created)'}\n```\n\n"
          f"**program output:**\n```\n{run_out}\n```\n\n**assistant said:**\n\n{text[:1500]}\n\n"
          f"**tool steps:** {len(tools)}\n```json\n{json.dumps(tools[:8], indent=2)[:2000]}\n```\n")
    return (built and correct), sid


# ── phase 3: real web research ────────────────────────────────────────────────
def phase_research():
    say("\n[3] RESEARCH (live web)")
    rid = str(uuid.uuid4())
    q = "What is the FizzBuzz programming problem and why is it used in interviews?"
    got = ""
    try:
        with httpx.stream("POST", f"{BASE}/api/research",
                          json={"query": q, "session_id": rid, "max_rounds": 3}, timeout=240) as r:
            for line in r.iter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    pass  # progress events; we read the final result below
        res = httpx.get(f"{BASE}/api/research/{rid}/result", timeout=30).json()
        got = res.get("report") or res.get("result") or json.dumps(res)[:2000]
    except Exception as e:
        got = f"(research error: {e})"
    ok = bool(got and len(got) > 80 and "error" not in got[:20].lower())
    say(f"    query: {q}")
    say(f"    report chars: {len(got)}")
    write("03_research.md", f"# live research\n\nsession: {rid}\n\n**query:** {q}\n\n**report:**\n\n{got[:4000]}\n")
    return ok


# ── phase 4: real app data (shows up in the UI) ───────────────────────────────
def phase_app_data():
    say("\n[4] APP DATA (real records you'll see in the UI)")
    made = {}
    try:
        made["subscription"] = httpx.post(f"{BASE}/api/subscriptions", json={
            "name": "Spotify", "amount": 11.99, "cycle": "monthly", "next_due": "2026-07-01"}, timeout=15).status_code
    except Exception as e:
        made["subscription"] = str(e)
    try:
        made["day_counter"] = httpx.post(f"{BASE}/api/days", json={
            "name": "alles shipped", "date": "2026-06-15"}, timeout=15).status_code
    except Exception as e:
        made["day_counter"] = str(e)
    try:
        made["task"] = httpx.post(f"{BASE}/api/tasks/quick", json={"text": "review alles build tomorrow !"}, timeout=15).json()
    except Exception as e:
        made["task"] = str(e)
    try:
        made["calendar"] = httpx.post(f"{BASE}/api/calendar/quick", json={"text": "demo alles friday 2pm"}, timeout=15).json()
    except Exception as e:
        made["calendar"] = str(e)
    try:
        made["memory"] = httpx.post(f"{BASE}/api/memories", json={"text": "I shipped alles with a full autonomous build pass"}, timeout=15).json()
    except Exception as e:
        made["memory"] = str(e)
    say("    " + json.dumps({k: (v if isinstance(v, int) else "created") for k, v in made.items()}))
    write("04_app_data.md", "# live app data\n\n" + "```json\n" + json.dumps(made, indent=2, default=str)[:3000] + "\n```\n")
    return all(not isinstance(v, str) or v.isdigit() for v in
               [made.get("subscription"), made.get("day_counter")])


def phase_more_apps():
    say("\n[5] MORE APPS (notes / journal / contacts / money — real records)")
    made = {}
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        made["note"] = httpx.post(f"{BASE}/api/vault-md/file",
                                  json={"path": "live-test-note", "content": "# live test\n\nthis note was created by the live usage test."}, timeout=15).status_code
    except Exception as e:
        made["note"] = str(e)
    try:
        made["journal"] = httpx.put(f"{BASE}/api/journal/{today}",
                                    json={"content": "shipped a full autonomous build + live test pass today.", "mood": "🚀", "tags": "build"}, timeout=15).status_code
    except Exception as e:
        made["journal"] = str(e)
    try:
        made["contact"] = httpx.post(f"{BASE}/api/contacts",
                                     json={"name": "Odysseus Ref", "email": "ody@example.com", "notes": "voice clone source (future)"}, timeout=15).json().get("id", "?")
    except Exception as e:
        made["contact"] = str(e)
    try:
        acct = httpx.post(f"{BASE}/api/money/accounts", json={"name": "Live Test Checking", "opening": 500.0}, timeout=15).json()
        httpx.post(f"{BASE}/api/money/transactions",
                   json={"account_id": acct["id"], "date": today, "amount": -42.0, "category": "tools", "payee": "github"}, timeout=15)
        bal = httpx.get(f"{BASE}/api/money/accounts", timeout=15).json()
        made["money"] = f"account+txn ok, balance {next((a['balance'] for a in bal if a['id']==acct['id']), '?')}"
    except Exception as e:
        made["money"] = str(e)
    say("    " + json.dumps(made, default=str)[:300])
    write("05_more_apps.md", "# live: notes / journal / contacts / money\n\n```json\n" + json.dumps(made, indent=2, default=str) + "\n```\n")
    return all(not (isinstance(v, str) and ("Error" in v or "error" in v)) for v in made.values())


def phase_compare():
    say("\n[7] COMPARE — one prompt against two real models, side by side")
    eps = {e["name"]: e["id"] for e in endpoints()}
    pairs = [(eps.get("DeepSeek"), "deepseek-v4-flash"), (eps.get("Moonshot"), "kimi-k2.5"),
             (eps.get("Anthropic"), "claude-opus-4-8")]
    pairs = [(eid, m) for eid, m in pairs if eid][:2]
    if len(pairs) < 2:
        say("    need 2 endpoints — skipping"); return True
    r = httpx.post(f"{BASE}/api/compare", json={
        "message": "Say hi in exactly 3 words.",
        "models": [{"endpoint_id": e, "model": m} for e, m in pairs]}, timeout=20).json()
    cid, n = r["compare_id"], r["count"]
    replies = []
    for idx in range(n):
        txt = []
        with httpx.stream("GET", f"{BASE}/api/compare/{cid}/stream/{idx}", timeout=90) as s:
            for line in s.iter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    try:
                        ev = json.loads(line[6:])
                        if "delta" in ev:
                            txt.append(ev["delta"])
                    except Exception:
                        pass
        replies.append("".join(txt).strip())
    ok = all(replies)
    for i, rp in enumerate(replies):
        say(f"    model[{i}]: {rp[:80]}")
    write("07_compare.md", "# live compare\n\n" + "\n".join(f"**model {i}:** {rp}" for i, rp in enumerate(replies)) + "\n")
    return ok


def phase_chat_action(eid, model, name):
    say("\n[6] CHAT APP-ACTION — plain chat 'what's on my calendar?' should DO it, not just talk")
    sid = new_session(f"live-test chat-action ({name})", model, eid, mode="chat")
    msg = "What do I have on my calendar? Check it and tell me."
    text, _, err = stream_chat(sid, msg, mode="chat", permission_mode="full_auto", timeout=150)
    called = []
    try:
        runs = httpx.get(f"{BASE}/api/agent/runs?limit=10", timeout=20).json()
        run = next((r for r in runs if r.get("session_id") == sid), None)
        if run:
            called = [e.get("data", {}).get("name") for e in run.get("events", []) if e.get("type") == "tool_start"]
    except Exception:
        pass
    used_cal = any("calendar" in (c or "") for c in called)   # must actually CALL a calendar tool
    say(f"    reply: {text.strip()[:200]}")
    say(f"    tools the agent called: {called}")
    write("06_chat_action.md",
          f"# chat does app things (auto-intent promotion)\n\nmsg: {msg}\nsession: {sid}\n\n"
          f"**tools called:** {called}\n\n**reply:**\n\n{text}\n")
    return used_cal


def main():
    say(f"live usage run -> {OUT}\nbase: {BASE}")
    eid, model, name = pick()
    if not eid:
        say("no usable endpoint — aborting"); return 1
    results = {}
    c_ok, _ = phase_chat(eid, model, name)
    results["chat"] = c_ok
    a_ok, _ = phase_agent(eid, model, name)
    results["agent_program"] = a_ok
    results["research"] = phase_research()
    results["app_data"] = phase_app_data()
    results["more_apps"] = phase_more_apps()
    results["chat_app_action"] = phase_chat_action(eid, model, name)
    results["compare"] = phase_compare()

    lines = ["# alles LIVE usage run", f"_{datetime.now().isoformat()}_", "",
             f"endpoint used: **{name} / {model}**", "", "| flow | result |", "|---|---|"]
    for k, v in results.items():
        lines.append(f"| {k} | {'✅ worked' if v else '❌ failed'} |")
    lines += ["", "see the per-phase files for the actual prompts, replies, the generated",
              "program + its output, and the research report. the chat/agent sessions and",
              "the sub/day/task/calendar/memory are now in the app — open it to see them."]
    write("SUMMARY.md", "\n".join(lines) + "\n" + "\n".join(_log))
    say(f"\n{sum(results.values())}/{len(results)} live flows worked -> {OUT/'SUMMARY.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
