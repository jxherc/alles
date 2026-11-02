"""Open optional Money sections when a Finance workflow needs their controls."""

from playwright.sync_api import expect


def pick_money_task(page, task, tap=False):
    """Money's four plan tasks are one dropdown: open it and pick the task by its name."""
    control = page.locator("#money-task-pick")
    if control.get_attribute("data-value") == task:
        control.focus()
    else:
        control.tap() if tap else control.press("Enter")
        option = page.get_by_role("option", name=task, exact=True)
        option.tap() if tap else option.click()
    expect(control).to_have_attribute("data-value", task)
    return control


def show_money_sections(page, task="accounts"):
    page.locator('[data-money-section="plans"]').or_(page.locator("#af-name")).first.wait_for(
        state="visible"
    )
    for name in ("plans", "analytics"):
        toggle = page.locator(f'[data-money-section="{name}"]')
        if toggle.count() and toggle.get_attribute("aria-expanded") == "false":
            toggle.click()
    totals = page.locator("#money-summary-toggle")
    if totals.is_visible() and totals.get_attribute("aria-expanded") == "false":
        totals.click()
    if (
        page.locator("#money-task-pick").count()
        and page.locator("#money-task-pick").get_attribute("data-value") != task
    ):
        pick_money_task(page, task)
