"""Open optional Money sections when a Finance workflow needs their controls."""


def show_money_sections(page):
    page.locator('[data-money-section="plans"]').or_(page.locator("#af-name")).first.wait_for(
        state="visible"
    )
    for name in ("plans", "analytics"):
        toggle = page.locator(f'[data-money-section="{name}"]')
        if toggle.count() and toggle.get_attribute("aria-expanded") == "false":
            toggle.click()
