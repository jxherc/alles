"""Screen style isolation and Finance summary reflow on an owned server."""

import json
import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    artifacts = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    observations = []
    focus_observations = []
    settings_observations = []
    finance_observations = []
    actual_ready = {
        "service": {
            "available": True,
            "installed": True,
            "running": True,
            "healthy": True,
            "version": "26.7.0",
        },
        "ledger": {
            "mode": "alles",
            "base_currency_code": "CAD",
            "run": {"status": "ready", "links": 2},
        },
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        api = playwright.request.new_context(base_url=base)
        assert api.post("/api/setup/dismiss").ok
        assert api.post(
            "/api/money/accounts",
            data={"name": "long summary amount", "currency": "CAD", "opening": 12345678.90},
        ).ok
        for width in (1440, 390):
            for theme in ("dark", "light"):
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    reduced_motion="reduce",
                    service_workers="block",
                )
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        errors.append(message.text) if message.type == "error" else None
                    ),
                )
                page.goto(
                    f"http://finance.localhost:{os.environ['PORT']}", wait_until="networkidle"
                )
                tab = page.locator('#finance-tabs [data-group-section="money"]')
                if tab.get_attribute("aria-selected") != "true":
                    tab.click()
                expect(page.locator(".money-summary .ms-card")).to_have_count(5)
                page.evaluate(
                    """async theme => {
                    const { applyAppearance, PRESETS } = await import('/static/js/theme.js');
                    applyAppearance({ preset: theme, colors: PRESETS[theme].colors });
                }""",
                    theme,
                )
                isolation = page.evaluate("""() => {
                    const probe = document.createElement('div');
                    probe.style.width = '270px';
                    probe.innerHTML = `<div class="ms-card"><span class="ms-val">outside finance</span></div>
                        <div class="today-inner">outside home</div><div class="s-pane">outside settings</div>
                        <div class="finance-actual-panel">outside authority panel</div>
                        <div class="txn-add"><span>outside transaction editor</span></div>
                        <div class="money-alerts">outside money alerts</div>
                        <span class="tx-tags"><span>outside tag</span></span>
                        <div class="goal-row">outside goal</div>
                        <div class="s-card">shared project card</div>
                        <div class="s-field"><label>shared editor field</label><input class="settings-input"></div>
                        <button class="s-switch" type="button" role="switch" aria-checked="false">shared switch</button>`;
                    document.body.append(probe);
                    const owned = document.createElement('div');
                    owned.innerHTML = '<span class="tx-tags"><span>inside tag</span></span>' +
                        '<div class="goal-row">inside goal</div>';
                    document.querySelector('#money-view').append(owned);
                    const readFinance = host => {
                        const tags = getComputedStyle(host.querySelector('.tx-tags'));
                        const goal = getComputedStyle(host.querySelector('.goal-row'));
                        return {tags: {display: tags.display, wrap: tags.flexWrap,
                            maxWidth: tags.maxWidth, overflow: tags.overflow},
                            goalMargin: goal.marginBottom};
                    };
                    const style = selector => getComputedStyle(probe.querySelector(selector));
                    const result = {finance: style('.ms-card').display, home: style('.today-inner').width,
                        settings: style('.s-pane').display,
                        authority: style('.finance-actual-panel').borderTopWidth,
                        transaction: style('.txn-add > span').height,
                        alerts: style('.money-alerts').display,
                        card: style('.s-card').borderTopWidth, field: style('.s-field').flexDirection,
                        switch: style('.s-switch').height,
                        financePrivate: {outside: readFinance(probe), inside: readFinance(owned)}};
                    owned.remove(); probe.remove(); return result;
                }""")
                assert isolation["finance"] == "block", isolation
                assert isolation["settings"] == "block", isolation
                assert isolation["home"] == "270px", isolation
                assert isolation["authority"] == "0px", isolation
                assert isolation["transaction"] == "auto", isolation
                assert isolation["alerts"] == "block", isolation
                assert isolation["card"] == "1px", isolation
                assert isolation["field"] == "column", isolation
                assert isolation["switch"] == "44px", isolation
                finance_private = isolation["financePrivate"]
                finance_observations.append({"width": width, "theme": theme, **finance_private})
                (artifacts / "finance-private-style-ownership.json").write_text(
                    json.dumps(finance_observations, indent=2)
                )
                assert finance_private["outside"]["tags"] == {
                    "display": "inline",
                    "wrap": "nowrap",
                    "maxWidth": "none",
                    "overflow": "visible",
                }, finance_private
                assert finance_private["outside"]["goalMargin"] == "0px", finance_private
                assert finance_private["inside"]["tags"] == {
                    "display": "flex",
                    "wrap": "wrap",
                    "maxWidth": "150px",
                    "overflow": "hidden",
                }, finance_private
                assert finance_private["inside"]["goalMargin"] == "9.6px", finance_private
                for zoom in (1, 2):
                    page.evaluate(
                        "zoom => document.documentElement.style.zoom = String(zoom)", zoom
                    )
                    page.locator(".money-summary").scroll_into_view_if_needed()
                    measured = page.locator(".money-summary").evaluate("""summary => {
                        const bounds = summary.getBoundingClientRect();
                        return {width: bounds.width, cards: [...summary.children].map(card => {
                            const box = card.getBoundingClientRect();
                            return {width: box.width, scroll: card.scrollWidth, client: card.clientWidth,
                                inside: box.left >= bounds.left - 1 && box.right <= bounds.right + 1,
                                text: [...card.querySelectorAll('.ms-label, .ms-val')].map(node => {
                                    const range = document.createRange(); range.selectNodeContents(node);
                                    const rects = [...range.getClientRects()];
                                    return {text: node.textContent, inside: rects.every(r =>
                                        r.left >= box.left - 1 && r.right <= box.right + 1 &&
                                        r.top >= box.top - 1 && r.bottom <= box.bottom + 1)};
                                })};
                        })};
                    }""")
                    observations.append({"width": width, "theme": theme, "zoom": zoom, **measured})
                    (artifacts / "style-ownership.json").write_text(
                        json.dumps(observations, indent=2)
                    )
                    page.screenshot(
                        path=str(artifacts / f"finance-summary-{width}-{theme}-{zoom}.png")
                    )
                    assert all(
                        card["inside"]
                        and card["scroll"] <= card["client"] + 1
                        and all(text["inside"] for text in card["text"])
                        for card in measured["cards"]
                    ), measured

                page.evaluate("document.documentElement.style.zoom = '1'")
                if width == 390:
                    page.set_viewport_size({"width": width, "height": 844})
                actual_mutations = []

                def actual_route(route):
                    request = route.request
                    if request.method != "GET":
                        actual_mutations.append({"method": request.method, "url": request.url})
                        route.fulfill(status=418, json={"detail": "style QA forbids Actual writes"})
                    elif request.url.split("?")[0].endswith("/api/finance/actual"):
                        route.fulfill(json=actual_ready)
                    else:
                        route.continue_()

                page.route("**/api/finance/actual**", actual_route)
                page.get_by_role("tab", name="overview", exact=True).click()
                review = page.get_by_role("button", name="review cutover", exact=True)
                review.click()
                cancel = page.get_by_role("button", name="keep current authority", exact=True)
                expect(cancel).to_be_focused()
                page.keyboard.press("Escape")
                expect(review).to_be_focused()
                page.keyboard.press("Enter")
                expect(cancel).to_be_focused()
                focus_bounds = """button => {
                    const style = getComputedStyle(button), box = button.getBoundingClientRect();
                    const scroller = button.closest('.specialist-group-overview');
                    const port = scroller.getBoundingClientRect();
                    const extent = parseFloat(style.outlineWidth) + Math.max(0, parseFloat(style.outlineOffset));
                    return {label: button.textContent.trim(), outline: style.outlineStyle,
                        ring: {left: box.left - extent, right: box.right + extent,
                            top: box.top - extent, bottom: box.bottom + extent},
                        scrollport: {left: port.left + scroller.clientLeft,
                            right: port.left + scroller.clientLeft + scroller.clientWidth,
                            top: port.top + scroller.clientTop,
                            bottom: port.top + scroller.clientTop + scroller.clientHeight},
                        viewport: {left: 0, right: innerWidth, top: 0, bottom: innerHeight}};
                }"""
                cancel_bounds = cancel.evaluate(focus_bounds)
                page.screenshot(
                    path=str(artifacts / f"finance-confirmation-focus-{width}-{theme}.png")
                )
                page.keyboard.press("Escape")
                expect(cancel).to_have_count(0)
                expect(review).to_be_focused()
                review_bounds = review.evaluate(focus_bounds)
                focus_observations.append(
                    {
                        "width": width,
                        "theme": theme,
                        "cancel": cancel_bounds,
                        "review": review_bounds,
                        "actual_mutations": actual_mutations,
                    }
                )
                (artifacts / "finance-confirmation-focus.json").write_text(
                    json.dumps(focus_observations, indent=2)
                )
                for focused in (cancel_bounds, review_bounds):
                    assert focused["outline"] == "solid", focused
                    ring = focused["ring"]
                    for boundary in (focused["scrollport"], focused["viewport"]):
                        assert (
                            ring["left"] >= boundary["left"] - 0.5
                            and ring["right"] <= boundary["right"] + 0.5
                            and ring["top"] >= boundary["top"] - 0.5
                            and ring["bottom"] <= boundary["bottom"] + 0.5
                        ), focused
                assert actual_mutations == [], actual_mutations
                page.goto(base + "/?view=today", wait_until="networkidle")
                page.evaluate(
                    """async theme => {
                    const { applyAppearance, PRESETS } = await import('/static/js/theme.js');
                    applyAppearance({ preset: theme, colors: PRESETS[theme].colors });
                }""",
                    theme,
                )
                page.locator("#today-settings").click()
                page.locator('.s-nav-item[data-pane="tools"]').click()
                private_styles = page.evaluate("""() => {
                    document.body.classList.add('theme-frosted');
                    const host = document.createElement('div');
                    host.innerHTML = '<div class="jarvis-pairing"></div>' +
                        '<div class="jarvis-quiet-row"></div>' +
                        '<div class="jarvis-quiet-fields"></div><div class="s-modal"></div>';
                    document.body.append(host);
                    const quiet = document.querySelector('#settings-modal .jarvis-quiet-fields');
                    const wasHidden = quiet.hidden;
                    quiet.hidden = false;
                    const read = el => {
                        const s = getComputedStyle(el);
                        return {display: s.display, border: s.borderTopWidth,
                            padding: s.paddingTop, filter: s.backdropFilter,
                            columns: s.gridTemplateColumns};
                    };
                    const result = Object.fromEntries([...host.children].map(el =>
                        [el.className, {outside: read(el),
                            inside: read(document.querySelector('#settings-modal .' + el.className))}]));
                    quiet.hidden = true;
                    result.hiddenQuietDisplay = getComputedStyle(quiet).display;
                    quiet.hidden = wasHidden;
                    host.remove();
                    return result;
                }""")
                for name in ("jarvis-pairing", "jarvis-quiet-row", "jarvis-quiet-fields"):
                    assert private_styles[name]["outside"]["display"] == "block", private_styles
                    assert private_styles[name]["outside"]["border"] == "0px", private_styles
                    assert private_styles[name]["outside"]["padding"] == "0px", private_styles
                assert private_styles["jarvis-pairing"]["inside"]["display"] == "grid", (
                    private_styles
                )
                assert private_styles["jarvis-pairing"]["inside"]["border"] == "1px", private_styles
                assert private_styles["jarvis-quiet-row"]["inside"]["display"] == "flex", (
                    private_styles
                )
                assert private_styles["jarvis-quiet-row"]["inside"]["border"] == "1px", (
                    private_styles
                )
                assert private_styles["jarvis-quiet-fields"]["inside"]["display"] == "grid", (
                    private_styles
                )
                assert private_styles["hiddenQuietDisplay"] == "none", private_styles
                assert private_styles["s-modal"]["outside"]["filter"] == "none", private_styles
                assert (
                    private_styles["s-modal"]["inside"]["filter"] == "blur(13px) saturate(1.25)"
                ), private_styles
                settings_observations.append({"width": width, "theme": theme, **private_styles})
                (artifacts / "settings-style-ownership.json").write_text(
                    json.dumps(settings_observations, indent=2)
                )
                page.screenshot(path=str(artifacts / f"settings-frosted-{width}-{theme}.png"))
                assert errors == [], errors
                context.close()
        api.dispose()
        browser.close()


if __name__ == "__main__":
    run()
