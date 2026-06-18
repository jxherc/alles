"""drive the aide agent through a real app build with a chosen model. diagnostic."""

import os, sys, json

os.environ["NO_PROXY"] = "localhost,127.0.0.1," + os.environ.get("NO_PROXY", "")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import httpx
from pathlib import Path
from datetime import datetime

BASE = "http://localhost:8099"
WANT_ENDPOINT = os.environ.get("AGENT_ENDPOINT", "DeepSeek")
WANT_MODELS = os.environ.get("AGENT_MODELS", "deepseek-v4-pro,deepseek-v4-flash").split(",")
WS = Path(os.environ.get("AGENT_WS", r"C:/Users/jxh/agent-builds/shenzhen-gems"))
WS.mkdir(parents=True, exist_ok=True)
EV = (
    Path.home() / "alles-test-evidence" / ("appbuild_" + datetime.now().strftime("%Y-%m-%d_%H%M%S"))
)
EV.mkdir(parents=True, exist_ok=True)

TASK = """Create a localized discovery app focused on Shenzhen. Include a map interface where users can find 'Hidden Gems' or local favorite spots. Users should be able to click on a location to see a brief description, why it's worth visiting, and a walking distance calculation.

Build it as a single self-contained web app in the current directory (index.html + script.js + style.css, or one index.html) — plain HTML/CSS/JS, NO paid API keys and NO build step. For the map you may use Leaflet via its CDN with free OpenStreetMap tiles. Curate 8-12 REAL Shenzhen hidden-gem spots (name, lat/lng, category, a brief description, and why it's worth visiting) as data in the app. Clicking a marker opens a panel with the description, the 'why visit', and the WALKING DISTANCE from a user-chosen reference point (the user sets their location by clicking the map) computed with the haversine formula (assume ~1.4 m/s walking speed for an ETA).

Engineering: keep the distance/haversine + data logic in a small testable JS module; write a Node test (test.js using node:assert) for the haversine distance against a couple of known coordinate pairs and run it with `node test.js` until it passes. Run `node --check` on every JS file. Style it cleanly. Finish only when the tests pass and node --check is clean."""


def main():
    eps = httpx.get(f"{BASE}/api/models", timeout=20).json()
    ep = next((e for e in eps if e["name"] == WANT_ENDPOINT), eps[0])
    ms = ep.get("models") or []
    model = next((m for m in WANT_MODELS if m in ms), (ms[0] if ms else WANT_MODELS[0]))
    print(f"agent: {ep['name']}/{model}  workspace: {WS}")
    sid = httpx.post(
        f"{BASE}/api/sessions",
        json={
            "name": f"appbuild {ep['name']}",
            "model": model,
            "endpoint_id": ep["id"],
            "working_dir": str(WS),
            "mode": "agent",
        },
        timeout=20,
    ).json()["id"]

    tools, last_status, runid = [], "", ""
    msg = TASK
    for attempt in range(4):
        body = {
            "session_id": sid,
            "message": msg,
            "mode": "agent",
            "permission_mode": "full_auto",
            "effort": "high",
            "model": model,
            "endpoint_id": ep["id"],
        }
        err_seen = None
        try:
            with httpx.stream("POST", f"{BASE}/api/chat", json=body, timeout=900) as r:
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    d = line[5:].strip()
                    if d == "[DONE]":
                        break
                    try:
                        ch = json.loads(d)
                    except Exception:
                        continue
                    if "tool_start" in ch:
                        t = ch["tool_start"]
                        a = t.get("args", {})
                        print(
                            f"  · {t['name']}  {str(a.get('path') or a.get('command') or a.get('pattern') or '')[:60]}",
                            flush=True,
                        )
                        tools.append(t["name"])
                    if "llm_retry" in ch:
                        print(
                            f"  ↻ retry #{ch['llm_retry']['attempt']} (transient error)", flush=True
                        )
                    if "error" in ch:
                        err_seen = ch["error"]
                        print(f"  ✗ error chunk: {str(ch['error'])[:160]}", flush=True)
        except Exception as e:
            print(f"  ✗ stream exception: {e}", flush=True)
        try:
            runs = httpx.get(f"{BASE}/api/agent/runs?limit=1", timeout=20).json()
            last_status = runs[0].get("status") if runs else "?"
            runid = runs[0].get("id") if runs else ""
            errs = [
                e for e in (runs[0].get("events", []) if runs else []) if e.get("type") == "error"
            ]
            if errs:
                print(f"  run error event: {errs[-1].get('data')}")
        except Exception:
            pass
        print(f"  [turn {attempt + 1}] status: {last_status}")
        if last_status != "turn_limit":
            break
        msg = "continue"

    files = sorted(p.name for p in WS.glob("**/*") if p.is_file())
    print(f"\nfinal status: {last_status}")
    print(f"files: {files}")
    print(f"tools ({len(tools)}): {tools}")
    (EV / "run.md").write_text(
        f"# agent app build — {ep['name']}/{model}\nstatus: {last_status}\nworkspace: {WS}\nrun: {runid}\n\n"
        f"files: {files}\n\ntools ({len(tools)}):\n" + "\n".join(f"- {t}" for t in tools),
        encoding="utf-8",
    )
    print(f"evidence: {EV}")


if __name__ == "__main__":
    main()
