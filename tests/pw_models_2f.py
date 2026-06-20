"""ui-2f — glowing brand logos in the model lists + deepseek → v4 pro/flash. Mocks /api/models with
deepseek + anthropic endpoints and checks the rendered lists. Server on :8870."""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "ui-2"
ENDPOINTS = [
    {
        "id": "ds",
        "name": "DeepSeek",
        "provider": "deepseek",
        "models": ["deepseek-reasoner", "deepseek-chat"],
        "cached_models": ["deepseek-reasoner"],
        "enabled": True,
    },
    {
        "id": "an",
        "name": "Anthropic",
        "provider": "anthropic",
        "models": ["claude-opus-4-8"],
        "cached_models": ["claude-opus-4-8"],
        "enabled": True,
    },
]


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block")
        pg = ctx.new_page()
        pg.route(
            "**/api/models",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps(ENDPOINTS)
            ),
        )
        pg.goto("http://aide.localhost:8870/", wait_until="domcontentloaded")
        pg.wait_for_selector("#sidebar-model-list", state="attached", timeout=15000)
        pg.wait_for_function("() => (window._endpoints||[]).length >= 2", timeout=10000)
        pg.wait_for_timeout(500)

        modal = pg.eval_on_selector("#model-list", "el => el.innerHTML")
        side = pg.eval_on_selector("#sidebar-model-list", "el => el.innerHTML")
        r["modal_has_brand_logos"] = "brandlogo" in modal
        r["modal_logos_glow"] = "brandlogo-glow" in modal
        r["sidebar_has_brand_logos"] = "brandlogo" in side
        r["deepseek_reasoner_is_v4_pro"] = "v4 pro" in modal
        r["deepseek_chat_is_v4_flash"] = "v4 flash" in modal
        r["no_raw_deepseek_word"] = (
            "deepseek" not in modal.lower() or "v4" in modal
        )  # renamed, not raw
        r["claude_pretty"] = "opus 4.8" in modal
        r["no_plain_model_dot"] = 'class="model-dot"' not in modal

        # select a model → topbar shows a glowing brand logo instead of the plain dot
        pg.eval_on_selector("#model-list .model-row", "el => el.click()")
        pg.wait_for_timeout(300)
        dot = pg.eval_on_selector("#live-dot", "el => ({cls: el.className, html: el.innerHTML})")
        r["topbar_dot_has_logo"] = "has-logo" in dot["cls"] and "brandlogo" in dot["html"]

        pg.screenshot(path=str(EVID / "model-logos.png"))
        pg.close()
        b.close()

    ok = all(r.values())
    print("\n".join(f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()))
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
