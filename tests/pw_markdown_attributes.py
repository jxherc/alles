"""Markdown attributes regression on an owned localhost server with synthetic data."""

import json
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import HOME, _require_throwaway_data_root, api


def run():
    _require_throwaway_data_root()
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    api("POST", "/api/setup/dismiss", {})
    content = "\n\n".join(
        [
            "# source",
            r"![x](/missing/\[x\]\(onerror=window.name=7331//\))",
            "![normal](/fixture/image.png)",
            "[normal link](/fixture/source)",
            "[**bold** *italic* ==marked==](/fixture/formatted)",
            r"[escaped](/fixture/source\(1\)?a=1&b=2)",
            r"![escaped image](/fixture/image\(1\).png?a=1&b=2)",
            "![price $x$](/fixture/cost$x$.png)",
            "[$x$](/fixture/cost$x$)",
            r"[blocked](javascript\:alert\(1\))",
            r"![blocked image](data\:text/html,payload)",
        ]
    )
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
            )

            def local_only(route):
                url = urlsplit(route.request.url)
                if url.hostname != "127.0.0.1":
                    route.abort()
                elif url.path.startswith("/fixture/") and ".png" in url.path:
                    route.fulfill(
                        content_type="image/svg+xml",
                        body=(
                            '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
                            '<rect width="40" height="20" fill="#888"/></svg>'
                        ),
                    )
                else:
                    route.continue_()

            context.route("**/*", local_only)
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            errors = []
            console = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    console.append(
                        {
                            "type": message.type,
                            "text": message.text,
                        }
                    )
                    if message.type == "error"
                    else None
                ),
            )
            record = {
                "scenario_id": "knowledge.markdown-attributes",
                "profile": str(width),
                "status": "failed",
            }
            records.append(record)
            path = f"security-{width}/escape.md"
            api("POST", "/api/vault-md/file", {"path": path, "content": content})
            try:
                page.goto(HOME + "/?app=docs&doc=" + quote(path, safe=""), wait_until="networkidle")
                preview = page.locator("#wiki-preview")
                expect(preview).to_contain_text("source")
                actual = preview.evaluate("""el => ({
                    html: el.innerHTML, executed: window.name,
                    handlers: [...el.querySelectorAll('*')].flatMap(node =>
                        [...node.attributes].filter(a => a.name.startsWith('on')).map(a => [a.name, a.value]))
                })""")
                (output / f"{width}-attributes.json").write_text(json.dumps(actual, indent=2))
                assert actual["executed"] != "7331", actual
                assert actual["handlers"] == [], actual
                expect(preview.locator('img[alt="normal"]')).to_have_attribute(
                    "src", "/fixture/image.png"
                )
                assert preview.locator('img[alt="normal"]').evaluate(
                    "el => el.complete && el.naturalWidth > 0"
                )
                expect(
                    preview.get_by_role("link", name="normal link", exact=True)
                ).to_have_attribute("href", "/fixture/source")
                formatted = preview.locator('a[href="/fixture/formatted"]')
                expect(formatted.locator("strong")).to_have_text("bold")
                expect(formatted.locator("em")).to_have_text("italic")
                expect(formatted.locator("mark")).to_have_text("marked")
                expect(preview.get_by_role("link", name="escaped", exact=True)).to_have_attribute(
                    "href", "/fixture/source(1)?a=1&b=2"
                )
                expect(preview.locator('img[alt="escaped image"]')).to_have_attribute(
                    "src", "/fixture/image(1).png?a=1&b=2"
                )
                expect(preview.locator('img[alt="price $x$"]')).to_have_attribute(
                    "src", "/fixture/cost$x$.png"
                )
                expect(
                    preview.locator('a[href="/fixture/cost$x$"] .md-math-inline')
                ).to_have_attribute("data-tex", "x")
                expect(preview.get_by_role("link", name="blocked", exact=True)).to_have_attribute(
                    "href", "#"
                )
                expect(preview.locator('img[alt="blocked image"]')).to_have_attribute("src", "#")
                assert not errors, errors
                record["status"] = "passed"
            except Exception as error:
                record["error"] = str(error)
            finally:
                (output / f"{width}-console.json").write_text(
                    json.dumps({"page_errors": errors, "console": console}, indent=2)
                )
                page.screenshot(path=str(output / f"{width}-attributes.png"), full_page=True)
                context.tracing.stop(path=str(output / f"{width}-attributes.zip"))
                context.close()
        browser.close()
    (output / "scenarios.json").write_text(json.dumps({"scenarios": records}, indent=2))
    print(json.dumps(records))
    return 0 if all(record["status"] == "passed" for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(run())
