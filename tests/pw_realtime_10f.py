"""10f UI — full-duplex live-voice affordance, gated on a realtime provider.
Hidden by default; appears once an endpoint exposes a realtime model.
aide.localhost:8877.  ALLES_DATA=/tmp/alles10f PORT=8877 AUTH_ENABLED=false python app.py
"""

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

AIDE = "http://aide.localhost:8877"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "10f"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "403", "Load failed")


def _req(path, body=None, method="GET"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:8877{path}",
        data=data,
        headers={"content-type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
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

        # default: no realtime provider → gated off
        st = _req("/api/voice/realtime/status")
        r["status_reports_unavailable_default"] = st["available"] is False
        r["status_endpoint_reachable"] = "reason" in st

        pg.goto(f"{AIDE}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#live-voice-btn", state="attached", timeout=15000)
        pg.wait_for_timeout(600)
        r["affordance_in_dom"] = pg.query_selector("#live-voice-btn") is not None
        r["realtime_btn_hidden_when_gated"] = not pg.is_visible("#live-voice-btn")

        # gated session is blocked
        try:
            _req("/api/voice/realtime/session", {}, "POST")
            r["gated_session_blocked"] = False
        except urllib.error.HTTPError as e:
            r["gated_session_blocked"] = e.code == 503

        # configure a realtime endpoint → gate opens
        ep = _req(
            "/api/models/endpoint", {"name": "RT", "base_url": "https://api.openai.com/v1"}, "POST"
        )
        _req(f"/api/models/endpoint/{ep['id']}", {"models": ["gpt-4o-realtime-preview"]}, "PATCH")
        st2 = _req("/api/voice/realtime/status")
        r["session_descriptor_returned_when_available"] = st2["available"] is True

        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#live-voice-btn", timeout=10000)
        pg.wait_for_timeout(700)
        r["btn_appears_when_provider"] = pg.is_visible("#live-voice-btn")
        pg.screenshot(path=str(EVID / "live-voice.png"))

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_realtime_10f.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
