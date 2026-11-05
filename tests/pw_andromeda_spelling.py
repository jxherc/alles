"""A typo in an andromeda search is fixed the way google does it, in the real page, in WebKit.

A loopback search engine and a loopback model stand in for the web and the overview model. The gate
types "achievemenst" and checks: the box shows "achievements", one line says "showing results for"
it with "search instead for" the typed words, the engine, the answer request and the overview all
got the fixed words, and the link searches the typed words exactly. It measures that the line
overlaps nothing, fits the screen, has a 44px target, and that hover and keyboard focus move
nothing, at desktop, both ipad sizes and phone, in the dark and the light theme.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import HOME, _require_throwaway_data_root, api

sys.path.insert(0, str(Path.cwd()))
from services.appearance import from_legacy  # noqa: E402

SIZES = {
    "desktop": {"viewport": {"width": 1280, "height": 800}},
    "ipad-landscape": {"viewport": {"width": 1180, "height": 820}, "has_touch": True},
    "ipad-portrait": {"viewport": {"width": 820, "height": 1180}, "has_touch": True},
    "phone": {"viewport": {"width": 390, "height": 844}, "has_touch": True, "is_mobile": True},
}
TYPED = "achievemenst"
FIXED = "achievements"


class Web(BaseHTTPRequestHandler):
    """a search engine that answers every query with results named after it."""

    queries = []
    # the overview is cached by its sources, so each profile gets its own links
    tag = "x"

    def log_message(self, *_args):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        if url.path != "/search":
            self.send_error(404)
            return
        query = parse_qs(url.query).get("q", [""])[0]
        Web.queries.append(query)
        # slow enough that the loading lines are on screen for a while before the results land
        time.sleep(0.7)
        rows = [
            {
                "url": f"https://example.com/{Web.tag}/{n}",
                "title": f"{query} result {n}",
                "content": f"Minecraft has 122 achievements players can earn. result {n} for {query}.",
                "engines": ["fixture"],
            }
            for n in range(1, 7)
        ]
        payload = json.dumps({"query": query, "results": rows, "corrections": []}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class Model(BaseHTTPRequestHandler):
    """a model that writes one sentence and keeps what it was asked."""

    protocol_version = "HTTP/1.1"
    asked = []

    def log_message(self, *_args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        Model.asked.append(json.dumps(request.get("messages", [])))
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        text = "Minecraft Java has 122 achievements that players can earn. [1]"
        for chunk in (
            {"choices": [{"delta": {"content": text}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ):
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


SAMPLER = """() => {
  window.__frames = [];
  const tick = () => {
    const card = document.getElementById('andromeda-overview');
    const line = document.getElementById('andromeda-spelling');
    if (card && !card.hidden && card.getBoundingClientRect().height > 0) {
      window.__frames.push({
        top: card.getBoundingClientRect().top,
        line: !line.hidden && line.getBoundingClientRect().height > 0,
        lineTop: line.getBoundingClientRect().top,
        above: [...card.parentElement.children].filter(n => n.getBoundingClientRect().height > 0)
          .map(n => `${n.id || n.className}:${Math.round(n.getBoundingClientRect().top)}`),
      });
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}"""


def rect(page, selector):
    return page.evaluate(
        """selector => {
          const node = document.querySelector(selector);
          if (!node) return null;
          const r = node.getBoundingClientRect();
          return { x: r.x, y: r.y, w: r.width, h: r.height, b: r.bottom, r: r.right };
        }""",
        selector,
    )


def same(a, b):
    return a and b and all(abs(a[k] - b[k]) < 0.5 for k in ("x", "y", "w", "h"))


def overlaps(page):
    """every visible block in the result column that touches the spelling line."""
    return page.evaluate(
        """() => {
          const line = document.getElementById('andromeda-spelling').getBoundingClientRect();
          const column = document.querySelector('.andromeda-result-column');
          const hits = [];
          for (const node of column.children) {
            if (node.id === 'andromeda-spelling' || node.hidden) continue;
            const r = node.getBoundingClientRect();
            if (!r.width || !r.height) continue;
            const across = Math.min(line.right, r.right) - Math.max(line.left, r.left);
            const down = Math.min(line.bottom, r.bottom) - Math.max(line.top, r.top);
            if (across > 0.5 && down > 0.5) hits.push(node.id || node.className);
          }
          const form = document.getElementById('andromeda-form').getBoundingClientRect();
          if (line.top < form.bottom - 0.5) hits.push('andromeda-form');
          return hits;
        }"""
    )


def run():
    _require_throwaway_data_root()
    out = Path(os.environ.get("ALLES_BROWSER_ARTIFACTS") or tempfile.mkdtemp())
    out.mkdir(parents=True, exist_ok=True)
    only = [s for s in os.environ.get("SPELLING_SIZES", ",".join(SIZES)).split(",") if s]
    web = ThreadingHTTPServer(("127.0.0.1", 0), Web)
    model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    for server in (web, model):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = api(
        "POST",
        "/api/models/endpoint",
        {
            "name": "spelling fixture",
            "base_url": f"http://127.0.0.1:{model.server_port}/v1",
            "provider_adapter": "manual",
        },
    )["id"]
    api("PATCH", f"/api/models/endpoint/{endpoint}", {"models": ["fixture"]})
    api("POST", "/api/setup/dismiss", {})
    # settings only take an https searxng, but a custom engine may sit on this machine
    engine = api(
        "POST",
        "/api/search/custom",
        {
            "name": "web fixture",
            "url": f"http://127.0.0.1:{web.server_port}/search?q={{query}}",
            "results": "results",
            "snippet_field": "content",
        },
    )["id"]
    api(
        "PATCH",
        "/api/settings",
        {
            "search_provider": engine,
            "search_fallback_chain": [],
            "andromeda_normal_results": True,
            "andromeda_overview": True,
            "andromeda_confirm_remote": False,
            "andromeda_model_band": "standard",
            "model_roles": {"andromeda_answer": {"endpoint_id": endpoint, "model": "fixture"}},
            "andromeda_recent_searches": [],
        },
    )
    rows = []

    def recent():
        return api("GET", "/api/settings").get("andromeda_recent_searches", [])

    try:
        with sync_playwright() as pw:
            browser = pw.webkit.launch()
            for size in only:
                for theme in ("dark", "light"):
                    profile = f"webkit-{size}-{theme}"
                    record = {"profile": profile, "status": "failed"}
                    rows.append(record)
                    api("PUT", "/api/appearance", from_legacy(theme, None))
                    api("PATCH", "/api/settings", {"andromeda_recent_searches": []})
                    context = browser.new_context(service_workers="block", **SIZES[size])
                    page = context.new_page()
                    page.set_default_timeout(15000)
                    errors = []
                    sent = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.on(
                        "console",
                        lambda m: (
                            errors.append(m.text)
                            if m.type == "error" and "Failed to load resource" not in m.text
                            else None
                        ),
                    )
                    page.on(
                        "request",
                        lambda r: (
                            sent.append((urlparse(r.url).path, r.post_data_json or {}))
                            if urlparse(r.url).path.startswith("/api/andromeda/")
                            and r.method == "POST"
                            else None
                        ),
                    )

                    def shot(name):
                        page.screenshot(path=str(out / f"{profile}-{name}.png"))

                    try:
                        Web.queries.clear()
                        Model.asked.clear()
                        Web.tag = profile
                        page.goto(f"{HOME}/?app=andromeda", wait_until="networkidle")
                        shown = page.evaluate("document.documentElement.dataset.theme || 'dark'")
                        assert shown == theme, (shown, theme)
                        # the dataset flag alone changes nothing: the page colour must follow
                        light = page.evaluate(
                            "(() => { const c = getComputedStyle(document.body).backgroundColor"
                            ".match(/\\d+/g).map(Number); return (c[0] + c[1] + c[2]) / 3 > 128; })()"
                        )
                        assert light == (theme == "light"), ("page colour", theme)
                        box = page.locator("#andromeda-query")
                        box.fill(TYPED)
                        # every frame: where the overview card and the line are once drawn
                        page.evaluate(SAMPLER)
                        page.keyboard.press("Enter")

                        # 1. the fixed words are searched and shown
                        line = page.locator("#andromeda-spelling")
                        expect(line).to_be_visible()
                        expect(line).to_contain_text(f"showing results for {FIXED}")
                        expect(line).to_contain_text(f"search instead for {TYPED}")
                        expect(box).to_have_value(FIXED)
                        expect(page.locator("#andromeda-results")).to_contain_text(
                            f"{FIXED} result 1"
                        )
                        assert page.locator("#andromeda-results").inner_text().count(TYPED) == 0
                        assert Web.queries == [FIXED], Web.queries
                        # the local fix is asked first; the search then runs on the fixed words
                        asked = [b for p, b in sent if p == "/api/andromeda/correct"]
                        assert asked and asked[0]["query"] == TYPED, asked
                        search = [b for p, b in sent if p == "/api/andromeda/search"]
                        assert search[0]["query"] == FIXED and search[0]["exact"] is True, search
                        answers = [b for p, b in sent if p == "/api/andromeda/answer"]
                        assert answers[0]["query"] == FIXED, answers
                        # the overview was asked for the fixed words, and so was the model
                        expect(page.locator("#andromeda-overview")).to_contain_text(
                            "122 achievements", timeout=20000
                        )
                        overview = [b for p, b in sent if p == "/api/andromeda/overview"]
                        assert overview and overview[0]["query"] == FIXED, overview
                        assert Model.asked and all(
                            FIXED in m and TYPED not in m for m in Model.asked
                        ), "the model saw the typo"
                        # nothing moved after it was drawn: the line was there with the first
                        # loading lines, and the overview card kept its top to within 1px
                        seen = page.evaluate("window.__frames")
                        assert seen, "the overview never drew"
                        assert seen[0]["line"], ("the line came after the overview", seen[0])
                        tops = [f["top"] for f in seen]
                        lines = [f["lineTop"] for f in seen]
                        record["overview_top"] = {
                            "first": round(tops[0], 1),
                            "last": round(tops[-1], 1),
                            "spread": round(max(tops) - min(tops), 2),
                            "frames": len(seen),
                        }
                        assert max(tops) - min(tops) <= 1, (seen[0]["above"], seen[-1]["above"])
                        assert max(lines) - min(lines) <= 1, (min(lines), max(lines))
                        assert f"q={FIXED}" in page.url and "exact" not in page.url, page.url
                        deadline = time.time() + 5
                        while FIXED not in recent() and time.time() < deadline:
                            time.sleep(0.2)
                        assert FIXED in recent() and TYPED not in recent(), recent()

                        # 2. the line fits, touches nothing, and is a real target
                        assert not overlaps(page), overlaps(page)
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth + 1"
                        )
                        line_box = rect(page, "#andromeda-spelling")
                        link_box = rect(page, "#andromeda-spelling button")
                        assert line_box["r"] <= SIZES[size]["viewport"]["width"] + 0.5, line_box
                        assert link_box["h"] >= 43.5, link_box
                        assert link_box["r"] <= SIZES[size]["viewport"]["width"] + 0.5, link_box
                        assert (
                            page.evaluate(
                                "getComputedStyle(document.querySelector('#andromeda-spelling button')).fontStyle"
                            )
                            == "normal"
                        )
                        first = rect(page, "#andromeda-results a")
                        shot("fixed")

                        # 3. hover and keyboard focus move nothing
                        link = page.locator("#andromeda-spelling button")
                        link.hover()
                        assert same(rect(page, "#andromeda-spelling"), line_box)
                        assert same(rect(page, "#andromeda-results a"), first)
                        link.focus()
                        assert same(rect(page, "#andromeda-spelling"), line_box)
                        assert same(rect(page, "#andromeda-results a"), first)
                        shot("focused")

                        # 4. search instead: the typed words, exactly, with no fix and no line
                        Web.queries.clear()
                        Model.asked.clear()
                        link.click()
                        expect(page.locator("#andromeda-results")).to_contain_text(
                            f"{TYPED} result 1"
                        )
                        expect(box).to_have_value(TYPED)
                        expect(line).to_be_hidden()
                        assert Web.queries == [TYPED], Web.queries
                        search = [b for p, b in sent if p == "/api/andromeda/search"]
                        assert search[-1]["query"] == TYPED and search[-1]["exact"] is True, search
                        answers = [b for p, b in sent if p == "/api/andromeda/answer"]
                        assert answers[-1]["exact"] is True, answers
                        assert f"q={TYPED}" in page.url and "exact=1" in page.url, page.url
                        deadline = time.time() + 5
                        while TYPED not in recent() and time.time() < deadline:
                            time.sleep(0.2)
                        assert recent()[0] == TYPED, recent()
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth + 1"
                        )
                        shot("exact")

                        # 5. another tab keeps the exact words (no second fix)
                        page.locator('[data-andromeda-category="news"]').first.click()
                        page.wait_for_timeout(800)
                        assert TYPED in Web.queries[-1], Web.queries
                        expect(box).to_have_value(TYPED)
                        assert not errors, errors
                        record["status"] = "passed"
                    except Exception as exc:
                        where = traceback.extract_tb(exc.__traceback__)[-1].lineno
                        record["error"] = f"line {where} {type(exc).__name__}: {exc}"[:900]
                        try:
                            page.screenshot(path=str(out / f"{profile}-failed.png"))
                        except Exception:
                            pass
                    finally:
                        context.close()
            browser.close()
    finally:
        for server in (web, model):
            server.shutdown()
            server.server_close()
        for path in (f"/api/models/endpoint/{endpoint}", f"/api/search/custom/{engine}"):
            try:
                api("DELETE", path)
            except Exception:
                pass
    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=1))
    shutil.rmtree(out / "tmp", ignore_errors=True)
    if any(r["status"] != "passed" for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
