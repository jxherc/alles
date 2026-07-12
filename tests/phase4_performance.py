"""Deterministic Phase 4 timing probe; live network timing is recorded separately."""

from __future__ import annotations

import asyncio
import json
import math
import platform
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import andromeda
from services.llm import simple_complete

ITERATIONS = 60
QUOTE = "Version 4.0.0 was released on 2026-07-12 with stable links."
RAW = json.dumps(
    {
        "claims": [
            {
                "text": "Version 4.0.0 is the latest release with stable links.",
                "citations": [{"source_id": "s1", "quote": QUOTE}],
            }
        ]
    }
)
EVIDENCE = [
    {
        "id": "s1",
        "title": "release notes",
        "url": "https://docs.example.test/releases/4.0.0",
        "publisher": "docs.example.test",
        "source_kind": "release notes",
        "source_quality": 2,
        "dates": ["2026-07-12"],
        "versions": ["4.0.0"],
        "passages": [QUOTE],
    }
]


class ModelStub(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        self.rfile.read(length)
        payload = json.dumps({"choices": [{"delta": {"content": RAW}}]})
        body = f"data: {payload}\n\ndata: [DONE]\n\n".encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def percentile(values: list[float], value: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * value) - 1)]


async def measure(base_url: str) -> dict:
    async def search_fixture(_query: str, *, max_results: int):
        return (
            [
                {
                    "url": f"https://docs.example.test/docs/{index}",
                    "title": f"result {index}",
                    "snippet": "current official documentation",
                }
                for index in range(max_results)
            ],
            "fixture",
            "",
        )

    links = []
    with mock.patch("services.research.search.search_chain", side_effect=search_fixture):
        for _ in range(ITERATIONS):
            started = time.perf_counter()
            result = await andromeda.normal_search("current docs", max_results=10)
            links.append((time.perf_counter() - started) * 1000)
            if result["status"] != "ready" or len(result["results"]) != 10:
                raise RuntimeError("links fixture did not produce ten stable results")

    overview = []
    for _ in range(ITERATIONS):
        started = time.perf_counter()
        raw = await simple_complete(
            andromeda.overview_prompt(
                "latest software version",
                EVIDENCE,
                andromeda.freshness_summary("latest software version", EVIDENCE),
            ),
            base_url,
            "",
            "phase4-loopback-stub",
            max_tokens=1_200,
        )
        checked = andromeda.verify_overview(raw, "latest software version", EVIDENCE)
        overview.append((time.perf_counter() - started) * 1000)
        if checked["status"] != "ready" or not checked["claims"]:
            raise RuntimeError("loopback model fixture did not produce a verified claim")

    return {
        "iterations": ITERATIONS,
        "links_ms": {
            "min": round(min(links), 3),
            "median": round(percentile(links, 0.5), 3),
            "p95": round(percentile(links, 0.95), 3),
            "max": round(max(links), 3),
            "budget_p95": 1500,
            "passed": percentile(links, 0.95) < 1500,
        },
        "standard_local_first_verified_text_ms": {
            "min": round(min(overview), 3),
            "median": round(percentile(overview, 0.5), 3),
            "p95": round(percentile(overview, 0.95), 3),
            "max": round(max(overview), 3),
            "budget_p95": 5000,
            "passed": percentile(overview, 0.95) < 5000,
        },
        "fixture": "deterministic search provider plus loopback OpenAI-compatible HTTP model stub",
        "hardware": {"machine": platform.machine(), "platform": platform.platform()},
    }


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = asyncio.run(measure(f"http://127.0.0.1:{server.server_port}"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    print(json.dumps(result, indent=2, sort_keys=True))
    return (
        0
        if all(
            result[key]["passed"] for key in ("links_ms", "standard_local_first_verified_text_ms")
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
