"""Real Settings navigation shared by desktop and compact browser checks."""


def choose_settings_section(page, name, *, touch=False):
    trigger = page.locator("#settings-section-trigger")
    if trigger.is_visible() and trigger.get_attribute("aria-expanded") != "true":
        trigger.tap() if touch else trigger.click()
    target = page.locator(f'.s-nav-item[data-pane="{name}"]')
    target.tap() if touch else target.click()


def settings_section_focus_target(page, name):
    trigger = page.locator("#settings-section-trigger")
    return trigger if trigger.is_visible() else page.locator(f'.s-nav-item[data-pane="{name}"]')
