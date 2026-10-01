"""Browser gate for repeatable Aide speech recording and transcription."""

import json
import os

from playwright.sync_api import Route, sync_playwright

PORT = os.environ.get("PORT", "8870")
URL = f"http://aide.localhost:{PORT}/"


def settings_route(route: Route) -> None:
    if route.request.method != "GET":
        route.continue_()
        return
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"stt_provider": "local", "stt_language": "en"}),
    )


def denied_case(browser) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844})
    context.add_init_script(
        """
        Object.defineProperty(navigator, 'mediaDevices', {
          configurable: true,
          value: {getUserMedia: async () => { throw new DOMException('denied', 'NotAllowedError'); }},
        });
        """
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )
    page.route("**/api/settings", settings_route)
    page.goto(URL, wait_until="networkidle")
    page.mouse.click(380, 420)
    page.wait_for_selector("body.sidebar-hidden")
    page.locator("#mic-btn").click()
    page.wait_for_selector("#toast-container .toast.error")
    assert page.locator("#toast-container .toast.error").last.inner_text() == "mic access denied"
    assert not page.locator(".composer-box").evaluate(
        "el => el.classList.contains('mic-recording')"
    )
    assert not errors, errors
    context.close()


def recording_case(browser) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000},
        permissions=["microphone"],
    )
    page = context.new_page()
    errors: list[str] = []
    transcripts = [
        (200, {"text": "first take"}),
        (503, {"detail": "transcription unavailable"}),
        (200, {"text": "second take"}),
    ]
    requests: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )
    page.route("**/api/settings", settings_route)

    def transcribe(route: Route) -> None:
        requests.append(route.request.method)
        status, payload = transcripts.pop(0)
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    page.route("**/api/stt", transcribe)
    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector("#mic-btn")

    page.locator("#mic-btn").click()
    page.wait_for_function(
        "document.querySelector('.composer-box')?.classList.contains('mic-recording')"
    )
    page.wait_for_timeout(1_200)
    painted = page.locator("#mic-wave").evaluate(
        """canvas => {
          const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
          let visible = 0;
          let red = 0;
          for (let index = 0; index < data.length; index += 4) {
            if (data[index + 3] > 0) visible += 1;
            if (data[index] > 150 && data[index + 1] < 120 && data[index + 3] > 0) red += 1;
          }
          return {visible, red};
        }"""
    )
    assert painted["visible"] > 50
    assert painted["red"] > 10
    page.locator("#mic-btn").click()
    page.wait_for_function("document.querySelector('#composer-ta')?.value.includes('first take')")
    assert requests == ["POST"]

    page.locator("#mic-btn").click()
    page.wait_for_function(
        "document.querySelector('.composer-box')?.classList.contains('mic-recording')"
    )
    page.keyboard.press("Escape")
    page.wait_for_function(
        "!document.querySelector('.composer-box')?.classList.contains('mic-recording')"
    )
    page.wait_for_timeout(150)
    assert requests == ["POST"]
    assert "recording cancelled" in page.locator("#toast-container").inner_text()

    page.locator("#mic-btn").click()
    page.wait_for_function(
        "document.querySelector('.composer-box')?.classList.contains('mic-recording')"
    )
    page.locator("#mic-btn").click()
    page.wait_for_function("document.querySelectorAll('#toast-container .toast.error').length > 0")
    assert "transcription unavailable" in page.locator("#toast-container").inner_text()
    errors[:] = [
        error
        for error in errors
        if error
        != "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
    ]

    page.locator("#mic-btn").click()
    page.wait_for_function(
        "document.querySelector('.composer-box')?.classList.contains('mic-recording')"
    )
    page.locator("#mic-btn").click()
    page.wait_for_function("document.querySelector('#composer-ta')?.value.includes('second take')")
    assert requests == ["POST", "POST", "POST"]
    assert not page.locator(".composer-box").evaluate(
        "el => el.classList.contains('mic-recording')"
    )
    assert not errors, errors
    page.screenshot(path="/tmp/alles-voice-recording.png", full_page=True)
    context.close()


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
            ],
        )
        denied_case(browser)
        recording_case(browser)
        browser.close()
    print("speech browser gate passed: denial, waveform, stop, cancel, failure, and retry")


if __name__ == "__main__":
    main()
