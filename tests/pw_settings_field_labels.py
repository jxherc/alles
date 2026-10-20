"""Audit persistent field names in the actual Settings panes without saving."""

import base64
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402
from pw_credits_detail import owned_context  # noqa: E402
from pw_settings_helpers import choose_settings_section  # noqa: E402
from test_settings_field_labels import SettingsFieldLabels  # noqa: E402

from services.appearance import from_legacy  # noqa: E402

DOM_NAME = """el => {
  const ids=el.getAttribute('aria-labelledby');
  const name=ids ? ids.split(/\\s+/).map(id=>document.getElementById(id)?.textContent||'').join(' ')
    : el.getAttribute('aria-label') || [...el.labels||[]].map(label=>label.textContent).join(' ');
  return {name:name.trim().replace(/\\s+/g,' '), id:el.id, type:el.type,
    visible:!!el.getClientRects().length && getComputedStyle(el).visibility!=='hidden',
    disabled:el.disabled, labels:[...el.labels||[]].map(l=>({text:l.textContent.trim(),for:l.htmlFor,
      visible:!!l.getClientRects().length && l.getBoundingClientRect().width>8 && l.getBoundingClientRect().height>8}))};
}"""


def registry():
    SettingsFieldLabels.setUpClass()
    fields = []
    for node in SettingsFieldLabels.fields:
        ancestor = node.parent
        while ancestor and "s-pane" not in ancestor.attrs.get("class", "").split():
            ancestor = ancestor.parent
        assert ancestor, node.attrs
        ident = node.attrs.get("id")
        selector = "#" + ident if ident else '[data-shortcut="' + node.attrs["data-shortcut"] + '"]'
        fields.append({"selector": selector, "pane": ancestor.attrs["id"].removeprefix("s-pane-")})
    return fields


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert Path(tempfile.gettempdir()).resolve() in data.parents
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    fields = registry()
    assert len(fields) == 93
    profiles = [(w, t, False) for w in (1440, 768, 390) for t in ("light", "dark")]
    profiles += [(1440, t, True) for t in ("light", "dark")]
    rows = []
    with sync_playwright() as pw:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            row = {
                "profile": label,
                "status": "failed",
                "panes": [],
                "fields": [],
                "draft_checks": [],
                "page_errors": [],
                "console_errors": [],
                "blocked_writes": [],
                "external": [],
            }
            rows.append(row)
            context = owned_context(pw, width, theme, zoom)

            def boundary(route):
                url = urlsplit(route.request.url)
                if url.scheme + "://" + url.netloc != base:
                    row["external"].append(route.request.url)
                    return route.abort()
                if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
                    row["blocked_writes"].append({"url": url.path, "method": route.request.method})
                    return route.abort()
                return route.continue_()

            context.route("**/*", boundary)
            context.route_web_socket("**/*", lambda ws: ws.close())
            page = context.new_page()
            page.set_default_timeout(8000)
            page.on("pageerror", lambda err: row["page_errors"].append(str(err)))
            page.on(
                "console",
                lambda msg: row["console_errors"].append(msg.text) if msg.type == "error" else None,
            )
            cdp = context.new_cdp_session(page)

            def ax_name(selector):
                root = cdp.send("DOM.getDocument")["root"]["nodeId"]
                node = cdp.send("DOM.querySelector", {"nodeId": root, "selector": selector})[
                    "nodeId"
                ]
                backend = cdp.send("DOM.describeNode", {"nodeId": node})["node"]["backendNodeId"]
                tree = cdp.send(
                    "Accessibility.getPartialAXTree",
                    {"backendNodeId": backend, "fetchRelatives": False},
                )["nodes"]
                actual = next(n for n in tree if n.get("backendDOMNodeId") == backend)
                return {
                    "name": actual.get("name", {}).get("value", ""),
                    "role": actual.get("role", {}).get("value", ""),
                    "ignored": actual.get("ignored", False),
                }

            def capture(name):
                png = base64.b64decode(
                    cdp.send(
                        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                    )["data"]
                )
                (out / f"{label}-{name}.png").write_bytes(png)

            def inspect(field):
                control = page.locator(field["selector"])
                expect(control).to_have_count(1)
                info = control.evaluate(DOM_NAME)
                info["visible"] = control.is_visible()
                assert info["name"], (field, info)
                result = {**field, **info, "evidence": "DOM association only; hidden field"}
                if info["visible"]:
                    page.wait_for_function(
                        "selector => !document.querySelector(selector).closest('[inert]')",
                        arg=field["selector"],
                    )
                    actual = ax_name(field["selector"])
                    assert not actual["ignored"] and actual["name"].strip(), (field, actual)
                    result.update(ax=actual, evidence="actual browser accessibility tree")
                    matching = page.get_by_label(actual["name"], exact=True)
                    assert matching.evaluate_all(
                        "(nodes, selector) => nodes.includes(document.querySelector(selector))",
                        field["selector"],
                    ), (field, actual)
                    for assoc in info["labels"]:
                        if assoc["visible"] and assoc["for"] and not info["disabled"]:
                            label_locator = page.locator('label[for="' + assoc["for"] + '"]')
                            label_locator.click()
                            expect(control).to_be_focused()
                            result["visible_label_focus"] = True
                            break
                row["fields"].append(result)

            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                before = context.request.get(base + "/api/settings").json()
                page.goto(base + "/?view=today", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                            base,
                        )
                        == 2
                    )
                    page.wait_for_function(
                        "innerWidth===720 && innerHeight===450 && devicePixelRatio===2"
                    )
                page.locator("#today-settings").click()
                panes = page.locator(".s-nav-item[data-pane]").evaluate_all(
                    "nodes=>nodes.map(n=>n.dataset.pane)"
                )
                assert len(panes) == 19
                for pane in panes:
                    choose_settings_section(page, pane, touch=width == 390)
                    expect(page.locator("#s-pane-" + pane)).to_be_visible()
                    page.wait_for_load_state("networkidle")
                    for field in [f for f in fields if f["pane"] == pane]:
                        inspect(field)
                    if pane == "models":
                        page.locator("#s-gemini-oauth-toggle").click()
                        expect(page.locator("#s-gemini-oauth-panel")).to_be_visible()
                        for ident in (
                            "s-gemini-client-id",
                            "s-gemini-client-secret",
                            "s-gemini-project-id",
                        ):
                            inspect(
                                {
                                    "selector": "#" + ident,
                                    "pane": pane,
                                    "state": "OAuth disclosure only; authorization not started",
                                }
                            )
                    sample = (
                        "#settings-context-limit"
                        if pane == "ai"
                        else "#s-gemini-client-id"
                        if pane == "models"
                        else None
                    )
                    if sample:
                        control = page.locator(sample)
                        original = control.input_value()
                        first = ax_name(sample)
                        control.fill("57" if pane == "ai" else "owned unsaved client id")
                        assert ax_name(sample) == first
                        control.fill(original)
                        row["draft_checks"].append(
                            {"selector": sample, "name": first["name"], "restored": True}
                        )
                    if pane in {"ai", "proactive", "models"}:
                        target = (
                            "#s-prox-hours"
                            if pane == "proactive"
                            else "#s-gemini-client-id"
                            if pane == "models"
                            else "#settings-context-limit"
                        )
                        page.locator(target).scroll_into_view_if_needed()
                        capture(pane)
                        (out / f"{label}-{pane}-accessibility.txt").write_text(
                            page.locator("#s-pane-" + pane).aria_snapshot()
                        )
                    metrics = page.evaluate(
                        """() => { const content=document.querySelector('#settings-modal .s-content');return {viewport:[innerWidth,innerHeight,devicePixelRatio],pageOverflow:document.documentElement.scrollWidth>innerWidth,contentOverflow:content.scrollWidth>content.clientWidth}; }"""
                    )
                    assert not metrics["pageOverflow"] and not metrics["contentOverflow"], (
                        pane,
                        metrics,
                    )
                    row["panes"].append({"pane": pane, **metrics})
                assert len(row["fields"]) == len(fields) + 3
                assert context.request.get(base + "/api/settings").json() == before
                assert (
                    not row["blocked_writes"]
                    and not row["external"]
                    and not row["page_errors"]
                    and not row["console_errors"]
                ), row
                row["status"] = "passed"
            except Exception:
                row["error"] = traceback.format_exc()
                try:
                    capture("failure")
                except Exception:
                    pass
                raise
            finally:
                cdp.detach()
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    run()
