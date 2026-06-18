"""drive the aide agent to build a real app, streaming the run. evidence kept."""

import os, sys, json, time

os.environ["NO_PROXY"] = "localhost,127.0.0.1," + os.environ.get("NO_PROXY", "")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import httpx
from pathlib import Path
from datetime import datetime

BASE = "http://localhost:8099"
WS = Path(r"C:/Users/jxh/agent-builds/termdeck")
WS.mkdir(parents=True, exist_ok=True)
EV = (
    Path.home()
    / "alles-test-evidence"
    / ("agentbuild_" + datetime.now().strftime("%Y-%m-%d_%H%M%S"))
)
EV.mkdir(parents=True, exist_ok=True)

TASK = """Build a polished terminal markdown slide presenter in Python — a real CLI tool, standard library ONLY (no third-party deps). Project name: deck.

Deliverables in the current working directory:
1. deck.py — the CLI. `python deck.py <file.md>` opens the deck fullscreen in the terminal.
2. sample.md — a 5-7 slide sample deck showing off the features.
3. test_deck.py — a unittest suite for the PURE logic.
4. README.md — brief usage.

Features:
- Parse markdown into slides split on lines that are exactly `---`.
- Render each slide CENTERED inside a rounded box (using ╭╮╰╯─│) sized to the terminal (shutil.get_terminal_size). Support `# H1` (bold, accent colour), `## H2`, `- ` bullets, `> ` quotes, ``` fenced code blocks (dim), `**bold**` and `inline code`. Use ANSI escape codes. Word-wrap long lines to the box width.
- A footer with `‹ n/total ›` and the deck title, plus a thin progress bar.
- Keyboard nav that works on BOTH Windows (msvcrt.getch) and Unix (termios/tty): right/space/n = next, left/p = prev, number then Enter = jump, q/Esc = quit. Clear the screen between slides.
- A non-interactive flag `--print N` (and `--print all`) that renders slide N to stdout and exits (no raw input) — for testing and piping.

Engineering rules:
- Stdlib only. Keep the layout/render logic PURE and testable: functions like split_slides(text)->list, render_slide(slide, width, height)->list[str], style_inline(text)->str must take args and return strings with NO terminal side-effects, so test_deck.py can test them without a TTY.
- test_deck.py (unittest) must cover: split_slides (--- handling, leading/trailing), style_inline (bold/code → ANSI), word-wrap at a given width, render_slide returning exactly `height` lines each of visible width `width`, and the --print path.
- After writing everything, RUN `python -m unittest -q` and FIX failures until ALL pass. Then run `python deck.py sample.md --print 1` to confirm rendering works without a TTY. Only finish when the tests pass and --print works.
- Match a clean terminal-tool style; no AI-boilerplate comments, no license headers."""


def models():
    return httpx.get(f"{BASE}/api/models", timeout=20).json()


def main():
    eps = models()
    ep = next((e for e in eps if e["name"] == "Anthropic"), eps[0])
    ms = ep.get("models") or []
    pref = ["claude-sonnet-4-6", "claude-opus-4-8", "claude-sonnet-4-5-20250929"]
    model = next((m for m in pref if m in ms), (ms[0] if ms else "claude-sonnet-4-6"))
    print(f"agent: {ep['name']}/{model}  workspace: {WS}")
    sid = httpx.post(
        f"{BASE}/api/sessions",
        json={
            "name": "agent-build termdeck",
            "model": model,
            "endpoint_id": ep["id"],
            "working_dir": str(WS),
            "mode": "agent",
        },
        timeout=20,
    ).json()["id"]

    all_tools = []
    msg = TASK
    for attempt in range(4):  # send 'continue' if it hits the turn limit
        body = {
            "session_id": sid,
            "message": msg,
            "mode": "agent",
            "permission_mode": "full_auto",
            "effort": "high",
            "model": model,
            "endpoint_id": ep["id"],
        }
        status = "running"
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
                    hint = a.get("path") or a.get("command") or a.get("pattern") or ""
                    print(f"  · {t['name']}  {str(hint)[:70]}", flush=True)
                    all_tools.append(t["name"])
                if "done" in ch:
                    status = "done"
        # check run status
        try:
            runs = httpx.get(f"{BASE}/api/agent/runs?limit=1&summary=1", timeout=20).json()
            st = runs[0].get("status") if runs else ""
        except Exception:
            st = ""
        print(f"  [turn {attempt + 1}] run status: {st}")
        if st != "turn_limit":
            break
        msg = "continue"

    files = sorted(p.name for p in WS.glob("*") if p.is_file())
    print(f"\nfiles created: {files}")
    print(f"tool calls ({len(all_tools)}): {all_tools}")
    (EV / "run.md").write_text(
        f"# agent build — terminal slide presenter\n\nworkspace: {WS}\nsession: {sid}\n\n"
        f"files: {files}\n\ntool sequence ({len(all_tools)}):\n"
        + "\n".join(f"- {t}" for t in all_tools),
        encoding="utf-8",
    )
    print(f"evidence: {EV}")


if __name__ == "__main__":
    main()
