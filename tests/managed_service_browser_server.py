"""Owned synthetic search HTTP service; real Alles lifecycle/config, simulated Docker only."""

import functools
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def serve():
    ROOT = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert Path(tempfile.gettempdir()).resolve() in data.parents
    assert (data / ".alles-test-owner").read_text() == os.environ["ALLES_TEST_RUN_ID"]
    state = {
        "running": False,
        "pull_failure": True,
        "malformed": False,
        "queries": [],
        "commands": [],
        "blocked_providers": [],
        "starts": 0,
    }

    class Search(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            p = urlparse(self.path)
            if p.path == "/":
                payload = b"owned service ready"
                code = 200 if state["running"] else 503
            elif p.path == "/search":
                query = parse_qs(p.query).get("q", [""])[0]
                state["queries"].append(query)
                result = (
                    {"error": "owned malformed search result"}
                    if state["malformed"]
                    else {
                        "results": [
                            {
                                "title": "owned service result",
                                "url": "https://example.invalid/owned-service",
                                "content": "local synthetic result from the configured service",
                            }
                        ]
                    }
                )
                payload = json.dumps(result).encode()
                code = 200
            else:
                payload = b"not found"
                code = 404
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    search_server = ThreadingHTTPServer(("127.0.0.1", 0), Search)
    search_server.daemon_threads = True
    threading.Thread(target=search_server.serve_forever, daemon=True).start()
    os.environ["ALLES_SEARXNG_PORT"] = str(search_server.server_port)
    from pw_server_recovery import STATS

    from app import app
    from core.settings import save_settings
    from services import sysmon

    sysmon.snapshot = lambda: STATS
    from services import managed_companions, service_manager
    from services import managed_searxng as ms
    from services.research import search as research

    save_settings({"search_provider": "disabled", "search_fallback_chain": []})

    def runner(command, timeout=120):
        assert command[0] == "docker", command
        state["commands"].append(command[:3] + (["simulated"] if len(command) > 3 else []))
        if command[1:2] == ["version"]:
            return subprocess.CompletedProcess(command, 0, "owned Docker fixture\n", "")
        if "pull" in command and state["pull_failure"]:
            return subprocess.CompletedProcess(command, 1, "", "owned pull failure")
        if any(verb in command for verb in ["up", "start", "restart"]):
            state["running"] = True
            state["starts"] += 1
        if any(verb in command for verb in ["stop", "down"]):
            state["running"] = False
        output = "owned-container\n" if "ps" in command and state["running"] else ""
        return subprocess.CompletedProcess(command, 0, output, "")

    for name in [
        "status",
        "install",
        "control",
        "update",
        "rollback",
        "uninstall_keep_data",
        "json_search",
    ]:
        setattr(ms, name, functools.partial(getattr(ms, name), runner=runner))
    service_manager.list_services = functools.partial(
        service_manager.list_services, runner=lambda cmd: runner(cmd, 20)
    )
    managed_companions.statuses = lambda: []
    original_provider = research._search_provider

    async def local_provider(name, *args, **kwargs):
        if name != "searxng":
            state["blocked_providers"].append(name)
            raise research.SearchProviderFailure("configuration")
        return await original_provider(name, *args, **kwargs)

    research._search_provider = local_provider
    from fastapi import Body

    @app.get("/api/test-fixture/managed-search")
    def fixture_state():
        return state

    @app.post("/api/test-fixture/managed-search")
    def fixture_update(body: dict = Body(...)):
        assert set(body) <= {"pull_failure", "malformed"}
        state.update(body)
        return state

    import uvicorn

    try:
        uvicorn.run(app, host="127.0.0.1", port=int(os.environ["PORT"]), proxy_headers=False)
    finally:
        search_server.shutdown()
        search_server.server_close()


if __name__ == "__main__":
    serve()
