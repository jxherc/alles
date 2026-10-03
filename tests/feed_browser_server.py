"""Start the owned test server with synthetic feed HTTP responses only."""

import os
import runpy
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

root = Path(os.environ["ALLES_DATA"]).resolve()
assert os.environ.get("ALLES_TEST_DATA") == "1"
assert Path(tempfile.gettempdir()).resolve() in root.parents
assert (root / ".alles-test-owner").read_text().strip() == os.environ["ALLES_TEST_RUN_ID"]
assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"
sys.path.insert(0, str(Path.cwd()))
from services import net_guard  # noqa: E402


async def synthetic_feed(url, **kwargs):
    parsed = urlparse(url)
    if parsed.hostname != "feeds.example.invalid":
        raise RuntimeError("unconfigured synthetic feed; external requests forbidden")
    if parsed.path.startswith("/bad"):
        return httpx.Response(503, text="synthetic feed outage", request=httpx.Request("GET", url))
    if not parsed.path.startswith("/good"):
        raise RuntimeError("unknown feed fixture")
    prefix = parsed.path.strip("/")
    body = (
        "<rss><channel><title>Local test feed</title>"
        + "".join(
            f"<item><title>Local post {i} {prefix}</title><link>https://articles.example.invalid/{prefix}/{i}</link></item>"
            for i in (1, 2)
        )
        + "</channel></rss>"
    )
    return httpx.Response(200, text=body, request=httpx.Request("GET", url))


net_guard.safe_get_async = synthetic_feed
runpy.run_path("app.py", run_name="__main__")
