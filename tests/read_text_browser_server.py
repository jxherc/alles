"""Owned article workflow server; fetches only configured synthetic responses."""

import json
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


def synthetic_article(url, **kwargs):
    assert urlparse(url).hostname == "articles.example.invalid", "external fetch forbidden"
    fixtures = json.loads((root / "article-fixtures.json").read_text())
    result = fixtures[url]  # Unknown URLs fail closed; never fall through to HTTP.
    with (root / "article-requests.jsonl").open("a") as log:
        log.write(json.dumps({"url": url}) + "\n")
    return httpx.Response(
        result["status"],
        text=result["html"],
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", url),
    )


async def synthetic_feed(url, **kwargs):
    assert urlparse(url).hostname == "feeds.example.invalid", "external fetch forbidden"
    path = urlparse(url).path
    return httpx.Response(
        200,
        text=f"<rss><channel><title>Local feed</title><item><title>Feed article</title>"
        f"<link>https://articles.example.invalid{path}</link></item></channel></rss>",
        request=httpx.Request("GET", url),
    )


net_guard.safe_get = synthetic_article
net_guard.safe_get_async = synthetic_feed
runpy.run_path("app.py", run_name="__main__")
