"""10b UI — reattach to a durable background run on (re)load. We seed a 'running' run on
disk for a real session, then confirm aide picks it up and tails its progress, and clears it
when the run finishes.  aide.localhost:8873.  ALLES_DATA=/tmp/alles10b PORT=8873 ... python app.py
"""

import json
import sys
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

AIDE = "http://aide.localhost:8873"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "10b"
RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "agent_runs"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "403", "Load failed")


def _post(path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:8873{path}",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _seed_run(session_id, status="running", text="drafting the answer to your question"):
    rid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / f"{rid}.json").write_text(
        json.dumps(
            {
                "id": rid,
                "session_id": session_id,
                "model": "m",
                "status": status,
                "max_turns": 6,
                "turn": 1,
                "text": text,
                "todos": [],
                "events": [{"time": now, "type": "turn", "data": {"i": 0}}],
                "tool_steps": [],
                "checkpoints": [],
                "started_at": now,
                "updated_at": now,
                "finished_at": None if status == "running" else now,
            }
        ),
        "utf-8",
    )
    return rid


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    seeded = []
    try:
        sid = _post("/api/sessions", {"name": "bg reattach test"})["id"]
        rid = _seed_run(sid)
        seeded.append(rid)
        sid2 = _post("/api/sessions", {"name": "no run here"})["id"]

        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_context().new_page()
            pg.on(
                "console",
                lambda m: (
                    errs.append(m.text)
                    if m.type == "error" and not any(x in m.text for x in IGNORE)
                    else None
                ),
            )
            pg.on(
                "pageerror",
                lambda e: errs.append(str(e)) if not any(x in str(e) for x in IGNORE) else None,
            )

            # open the session that has a live background run
            pg.goto(f"{AIDE}/#{sid}", wait_until="domcontentloaded")
            pg.wait_for_selector("#bg-reattach", timeout=12000)
            r["reattach_finds_live_run"] = pg.is_visible("#bg-reattach")
            status = pg.text_content(".bg-reattach-status") or ""
            text = pg.text_content(".bg-reattach-text") or ""
            r["reattach_indicator_shows"] = "running" in status
            r["reattach_renders_progress"] = "drafting the answer" in text
            pg.screenshot(path=str(EVID / "reattach.png"))

            # reload — the run is durable, so it must reattach again
            pg.goto(f"{AIDE}/#{sid}", wait_until="domcontentloaded")
            pg.wait_for_selector("#bg-reattach", timeout=12000)
            r["reattach_survives_reload"] = pg.is_visible("#bg-reattach")

            # finish the run on disk → the tail should clear the indicator
            (RUNS_DIR / f"{rid}.json").write_text(
                json.dumps(
                    {
                        **json.loads((RUNS_DIR / f"{rid}.json").read_text("utf-8")),
                        "status": "done",
                        "finished_at": datetime.utcnow().isoformat(),
                    }
                ),
                "utf-8",
            )
            try:
                pg.wait_for_selector("#bg-reattach", state="detached", timeout=8000)
                r["done_clears_indicator"] = True
            except Exception:
                r["done_clears_indicator"] = False

            # a session with no live run shows no reattach block
            pg.goto(f"{AIDE}/#{sid2}", wait_until="domcontentloaded")
            pg.wait_for_timeout(1500)
            r["no_live_run_no_reattach"] = not pg.query_selector("#bg-reattach")

            r["zero_console_errors"] = len(errs) == 0
            b.close()
    finally:
        for rid in seeded:
            (RUNS_DIR / f"{rid}.json").unlink(missing_ok=True)

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_agent_bg_10b.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
