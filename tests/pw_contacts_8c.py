"""Owned Contacts labeled fields, avatar, Me badge, smart groups and duplicate merge."""

import io
import json
import os
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from PIL import Image
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    stream = io.BytesIO()
    Image.new("RGB", (24, 24), "blue").save(stream, format="PNG")
    avatar = stream.getvalue()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, theme in [(1440, "dark"), (390, "light")]:
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
                has_touch=width == 390,
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(8000)
            errors, console, external = [], [], []
            record = {"profile": f"{width}-{theme}", "status": "failed", "checks": []}
            records.append(record)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )

            def boundary(route):
                if urlsplit(route.request.url).netloc == urlsplit(base).netloc:
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort("blockedbyclient")

            context.route("**/*", boundary)
            context.route_web_socket("**/*", lambda socket: socket.close())
            api = context.request

            def post(path, body):
                response = api.post(base + path, data=body)
                assert response.ok, response.text()
                return response.json()

            def read(path):
                response = api.get(base + path)
                assert response.ok, response.text()
                return response.json()

            def click(target):
                target.tap() if width == 390 else target.click()

            try:
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.patch(base + "/api/settings", data={"theme": theme, "language": "en"}).ok
                ada = post(
                    "/api/contacts",
                    {
                        "name": f"Ada {width}",
                        "address": "12 Baker St, London",
                        "tags": [f"vip-{width}"],
                    },
                )
                jane = post(
                    "/api/contacts",
                    {"name": f"Jane {width}", "email": f"jane-{width}@example.invalid"},
                )
                duplicate = post(
                    "/api/contacts",
                    {"name": f"jane {width}", "email": f"jane2-{width}@example.invalid"},
                )
                page.goto(base + "/?view=contacts", wait_until="networkidle")
                click(page.locator(f'[data-open="{ada["id"]}"]'))
                expect(page.locator(".contact-detail")).to_be_visible()
                expect(page.locator(".contact-map")).to_be_visible()
                click(page.locator("#cd-fkind"))
                click(page.get_by_role("option", name="phone", exact=True))
                page.locator("#cd-flabel").fill("mobile")
                page.locator("#cd-fvalue").fill("555-9000")
                click(page.locator("#cd-fadd"))
                expect(page.locator("#cd-fields")).to_contain_text("555-9000")
                expect(page.locator("#cd-fields")).to_contain_text("mobile")
                fields = read(f"/api/contacts/{ada['id']}/fields")
                assert any(
                    field["kind"] == "phone"
                    and field["label"] == "mobile"
                    and field["value"] == "555-9000"
                    for field in fields
                )
                record["checks"].append(
                    "real custom choice and labeled phone field saved; address map link visible"
                )
                page.locator("#cd-avatar").set_input_files(
                    {"name": "avatar.png", "mimeType": "image/png", "buffer": avatar}
                )
                picture = page.locator(".contact-detail-head img.contact-av-lg")
                expect(picture).to_be_visible()
                response = api.get(base + picture.get_attribute("src"))
                assert response.ok and response.body() == avatar
                click(page.locator("#cd-me"))
                expect(page.locator("#cd-me")).to_have_attribute("aria-pressed", "true")
                click(page.locator("#cd-back"))
                expect(
                    page.locator(f'.contact-item[data-id="{ada["id"]}"] .contact-me-badge')
                ).to_be_visible()
                assert read(f"/api/contacts/{ada['id']}")["is_me"] is True
                record["checks"].append(
                    "avatar exact bytes reopen; Me flag persists and renders badge"
                )
                page.screenshot(path=str(output / f"{width}-contacts.png"))

                click(page.locator("#contacts-groups-btn"))
                click(page.locator("#cg-add"))
                page.get_by_role("textbox", name="group name:", exact=True).fill(f"VIPs {width}")
                click(page.locator("[data-dialog-confirm]"))
                page.get_by_role(
                    "textbox",
                    name="smart rule: tag to auto-include (blank for a manual group)",
                    exact=True,
                ).fill(f"vip-{width}")
                click(page.locator("[data-dialog-confirm]"))
                expect(page.locator("#cg-list")).to_contain_text(f"VIPs {width}")
                group = next(
                    item for item in read("/api/contacts/groups") if item["name"] == f"VIPs {width}"
                )
                members = read(f"/api/contacts/groups/{group['id']}/members")
                assert group["smart"] and [item["id"] for item in members] == [ada["id"]]
                record["checks"].append(
                    "smart group created via dialogs and exact tag membership verified"
                )
                page.screenshot(path=str(output / f"{width}-groups.png"))

                click(page.locator("#contacts-dups-btn"))
                cluster = page.locator(".dup-cluster").filter(has_text=f"Jane {width}")
                expect(cluster).to_be_visible()
                before = len(read("/api/contacts"))
                with page.expect_response(
                    lambda response: (
                        response.url == base + "/api/contacts/merge"
                        and response.request.method == "POST"
                    )
                ) as merged:
                    click(cluster.locator("[data-merge]"))
                assert merged.value.ok
                expect(cluster).to_have_count(0)
                contacts = read("/api/contacts")
                assert len(contacts) == before - 1
                assert sum(item["id"] in {jane["id"], duplicate["id"]} for item in contacts) == 1
                record["checks"].append(
                    "duplicate merge removes one contact and keeps one original identity"
                )
                page.screenshot(path=str(output / f"{width}-merged.png"))
                assert not errors and not console and not external, (errors, console, external)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                record["status"] = "passed"
            except Exception:
                record["error"] = traceback.format_exc()
                page.screenshot(path=str(output / f"{width}-failure.png"))
            finally:
                record.update(errors=errors, console=console, external=external)
                (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                context.tracing.stop(path=str(output / f"contacts-{width}-trace.zip"))
                context.close()
        browser.close()
    print(json.dumps(records, indent=2))
    assert all(record["status"] == "passed" for record in records)


if __name__ == "__main__":
    run()
