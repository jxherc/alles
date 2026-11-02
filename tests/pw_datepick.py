"""pick a day in alles' date field (datepick.js) the way a person does: open it, type the year,
step to the month, click the day. the field is a button, not an <input>, so .fill() can't set it."""

import re

from playwright.sync_api import expect

MONTHS = (
    "january february march april may june july august september october november december".split()
)


def pick_date(field, iso: str) -> None:
    page = field.page
    year, month, day = (int(part) for part in iso.split("-"))
    field.click()
    panel = page.locator(".date-panel")
    panel.locator(".dp-year").fill(str(year))
    panel.locator(".dp-year").press("Enter")
    for _ in range(24):
        shown = panel.locator(".dp-head span").inner_text().strip().lower().split()[0]
        current = MONTHS.index(shown) + 1
        if current == month:
            break
        panel.locator(f'[data-nav="{1 if current < month else -1}"]').click()
    else:
        raise AssertionError(f"the picker never reached {iso}")
    panel.locator(f'.dp-day[data-d="{day}"]').click()
    # a date closes on the click; a due date or a date with time stays open for its time
    if panel.count():
        panel.locator(".dp-day.sel").press("Escape")
    expect(field).to_have_attribute("data-value", re.compile("^" + re.escape(iso)))


def expect_date(field, iso: str) -> None:
    expect(field).to_have_attribute("data-value", re.compile("^" + re.escape(iso)))
