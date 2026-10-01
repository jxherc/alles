"""Real offline Health writes with explicitly simulated IndexedDB failures.

Use the owned browser runner. Storage denial/abort and notification failure are
injected into the real service worker; the UI, queue, replay and SQLite are real.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from browser_gate_safety import require_server_ownership
from browser_offline_network import OfflineNetwork
from playwright.sync_api import expect, sync_playwright

FEATURE = "extension-mobile.pwa-and-extension"


def run():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert Path(tempfile.gettempdir()).resolve() in data.parents
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for profile in ("desktop", "phone"):
            for mode in ("normal", "open-denied", "commit-aborted", "notification-failed"):
                failure = mode in {"open-denied", "commit-aborted"}
                record = {
                    "scenario_id": (
                        "pwa.queue-storage-failure" if failure else "pwa.queue-reconnect"
                    ),
                    "feature_id": FEATURE,
                    "profile": profile,
                    "mode": mode,
                    "status": "failed",
                    "detail": "workflow did not finish",
                    "browser": browser.version,
                    "simulated_fault": mode if mode != "normal" else "network offline only",
                }
                records.append(record)
                dest = output / f"{profile}-{mode}"
                dest.mkdir(parents=True, exist_ok=True)
                context = browser.new_context(
                    viewport={
                        "width": 390 if profile == "phone" else 1440,
                        "height": 844 if profile == "phone" else 900,
                    },
                    is_mobile=profile == "phone",
                    has_touch=profile == "phone",
                    reduced_motion="reduce",
                    locale="en-US",
                    timezone_id="UTC",
                )
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = context.new_page()
                page.set_default_timeout(15000)
                state = {"offline": False}
                events = {
                    "console": [],
                    "page_errors": [],
                    "failed_requests": [],
                    "http_errors": [],
                    "worker_failures": [],
                    "worker_health_posts": [],
                }
                page.on(
                    "console",
                    lambda msg: events["console"].append(
                        {"type": msg.type, "text": msg.text, "offline": state["offline"]}
                    ),
                )
                page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
                page.on(
                    "requestfailed",
                    lambda req: events["failed_requests"].append(
                        {
                            "url": req.url,
                            "method": req.method,
                            "failure": req.failure,
                            "offline": state["offline"],
                        }
                    ),
                )
                page.on(
                    "response",
                    lambda response: (
                        events["http_errors"].append(
                            {
                                "url": response.url,
                                "method": response.request.method,
                                "status": response.status,
                            }
                        )
                        if response.status >= 400
                        else None
                    ),
                )
                context.on(
                    "requestfailed",
                    lambda req: (
                        events["worker_failures"].append(
                            {
                                "url": req.url,
                                "method": req.method,
                                "failure": req.failure,
                                "offline": state["offline"],
                            }
                        )
                        if req.service_worker
                        else None
                    ),
                )
                context.on(
                    "request",
                    lambda req: (
                        events["worker_health_posts"].append(
                            {
                                "url": req.url,
                                "body": req.post_data,
                                "offline": state["offline"],
                            }
                        )
                        if req.service_worker
                        and req.method == "POST"
                        and req.url == base + "/api/health"
                        else None
                    ),
                )
                note = f"offline storage {profile} {mode} 中文"

                def saved():
                    # This process checks the owned server directly while the browser is offline.
                    with urlopen(base + "/api/health", timeout=10) as response:
                        entries = json.load(response)["entries"]
                    return [item for item in entries if item["note"] == note]

                def submit():
                    with page.expect_response(
                        lambda response: (
                            response.url.endswith("/api/health")
                            and response.request.method == "POST"
                        )
                    ) as response:
                        page.locator("#health-create").press("Enter")
                    result = response.value
                    return {
                        "status": result.status,
                        "body": result.json(),
                        "from_service_worker": result.from_service_worker,
                    }

                network = None
                try:
                    page.goto(base, wait_until="networkidle")
                    if page.locator("#setup-skip").is_visible():
                        page.locator("#setup-skip").click()
                    page.wait_for_function("navigator.serviceWorker.controller")
                    page.goto(base + "/?view=health-log", wait_until="networkidle")
                    worker = context.service_workers[0]
                    network = OfflineNetwork(browser, context, page, worker)
                    page.evaluate(
                        "window.__onlineEvents = 0; addEventListener('online', () => window.__onlineEvents++)"
                    )
                    assert worker.evaluate("async()=>await _all()") == []
                    page.locator("#health-add-toggle").click()
                    page.get_by_label("value", exact=True).fill("74.312")
                    page.get_by_label("note (optional)", exact=True).fill(note)
                    state["offline"] = True
                    network.set_offline(True)
                    if mode == "open-denied":
                        worker.evaluate(
                            """() => {
                              self.__faultCount = 0;
                              self.__originalOpen = indexedDB.open;
                              indexedDB.open = function(...args) {
                                if (args[0] === 'alles-sync') {
                                  self.__faultCount++;
                                  throw new DOMException('Simulated storage denial', 'SecurityError');
                                }
                                return self.__originalOpen.apply(this, args);
                              };
                            }"""
                        )
                    elif mode == "commit-aborted":
                        worker.evaluate(
                            """() => {
                              self.__faultCount = 0;
                              self.__originalAdd = IDBObjectStore.prototype.add;
                              IDBObjectStore.prototype.add = function(...args) {
                                const request = self.__originalAdd.apply(this, args);
                                if (this.name === 'outbox') {
                                  self.__faultCount++;
                                  this.transaction.abort();
                                }
                                return request;
                              };
                            }"""
                        )
                    elif mode == "notification-failed":
                        worker.evaluate(
                            """() => {
                              self.__faultCount = 0;
                              self.__originalNotify = notifyClients;
                              notifyClients = async () => {
                                self.__faultCount++;
                                throw new Error('Simulated page notification failure');
                              };
                            }"""
                        )
                    record["first_response"] = submit()
                    if failure:
                        assert record["first_response"]["status"] == 503
                        assert record["first_response"]["body"]["queued"] is False
                        assert record["first_response"]["from_service_worker"]
                        expect(page.locator("#health-entry-error")).to_contain_text(
                            "save failed (503). your input is kept"
                        )
                        expect(page.get_by_label("value", exact=True)).to_have_value("74.312")
                        expect(page.get_by_label("note (optional)", exact=True)).to_have_value(note)
                        expect(page.locator("#health-create")).to_be_enabled()
                        expect(page.locator("#health-create")).to_be_focused()
                        assert not saved()
                        page.screenshot(path=str(dest / "01-retained-error.png"), full_page=True)
                        if mode == "open-denied":
                            record["fault_count"] = worker.evaluate(
                                "() => { indexedDB.open = self.__originalOpen; return self.__faultCount; }"
                            )
                        else:
                            record["fault_count"] = worker.evaluate(
                                """() => {
                                  IDBObjectStore.prototype.add = self.__originalAdd;
                                  return self.__faultCount;
                                }"""
                            )
                        assert record["fault_count"] > 0
                        assert worker.evaluate("async()=>await _all()") == []
                        record["retry_response"] = submit()
                    accepted = record.get("retry_response", record["first_response"])
                    assert accepted == {
                        "status": 200,
                        "body": {"queued": True, "offline": True},
                        "from_service_worker": True,
                    }
                    expect(page.locator("#health-entry-form")).to_have_count(0)
                    if mode == "notification-failed":
                        record["fault_count"] = worker.evaluate(
                            "() => { notifyClients = self.__originalNotify; return self.__faultCount; }"
                        )
                        assert record["fault_count"] > 0
                    else:
                        expect(page.locator("#sync-indicator")).to_be_visible()
                        expect(page.locator("#sync-indicator")).to_contain_text("1 pending")
                    queued = worker.evaluate("async()=>await _all()")
                    assert len(queued) == 1, queued
                    assert json.loads(queued[0]["body"])["value"] == 74.312
                    assert json.loads(queued[0]["body"])["note"] == note
                    assert not saved()
                    record["outbox_before_reconnect"] = queued
                    page.screenshot(path=str(dest / "02-queued.png"), full_page=True)
                    network.set_offline(False)
                    state["offline"] = False
                    record["network_transitions"] = network.transitions
                    assert page.evaluate("window.__onlineEvents") == 1
                    # Only the app's real online listener flushes the outbox.
                    deadline = time.monotonic() + 10
                    entries, queued = [], queued
                    while time.monotonic() < deadline:
                        entries = saved()
                        queued = worker.evaluate("async()=>await _all()")
                        if entries and not queued:
                            break
                        page.wait_for_timeout(100)
                    assert len(entries) == 1 and entries[0]["value"] == 74.312, entries
                    assert queued == [], queued
                    expect(page.locator("#sync-indicator")).to_be_hidden()
                    page.reload(wait_until="networkidle")
                    expect(page.locator(".health-row").filter(has_text=note)).to_be_visible()
                    assert len(saved()) == 1
                    page.screenshot(path=str(dest / "03-persisted.png"), full_page=True)
                    record["saved_entry"] = entries[0]
                    expected_worker_failure = {
                        "url": base + "/api/health",
                        "method": "POST",
                        "failure": "net::ERR_INTERNET_DISCONNECTED",
                        "offline": True,
                    }
                    assert events["worker_failures"] == [expected_worker_failure] * (
                        2 if failure else 1
                    ), events
                    assert len(events["worker_health_posts"]) == (3 if failure else 2), events
                    assert (
                        events["worker_health_posts"][-1]["body"]
                        == record["outbox_before_reconnect"][0]["body"]
                    ), events
                    assert all(
                        item["body"] is None
                        or item["body"] == record["outbox_before_reconnect"][0]["body"]
                        for item in events["worker_health_posts"]
                    ), events
                    assert not events["page_errors"], events
                    assert all(
                        item["offline"]
                        and item["method"] == "GET"
                        and item["url"]
                        in {base + "/api/health", base + "/api/health/overview?days=30"}
                        and item["failure"] == "net::ERR_INTERNET_DISCONNECTED"
                        for item in events["failed_requests"]
                    ), events
                    expected_http = (
                        [{"url": base + "/api/health", "method": "POST", "status": 503}]
                        if failure
                        else []
                    )
                    assert events["http_errors"] == expected_http, events
                    errors = [item for item in events["console"] if item["type"] == "error"]
                    assert len(errors) == len(events["failed_requests"]) + len(expected_http), (
                        events
                    )
                    assert all(
                        item["offline"]
                        and (
                            item["text"]
                            == "Failed to load resource: net::ERR_INTERNET_DISCONNECTED"
                            or (
                                failure
                                and "503" in item["text"]
                                and "Failed to load resource" in item["text"]
                            )
                        )
                        for item in errors
                    ), events
                    record.update(
                        status="passed",
                        detail=(
                            "failed storage retained input; retry queued once and persisted after reconnect/reload"
                            if failure
                            else "one committed queue item persisted after reconnect/reload"
                        ),
                    )
                except Exception:
                    page.screenshot(path=str(dest / "failure.png"), full_page=True)
                    raise
                finally:
                    (dest / "events.json").write_text(json.dumps(events, indent=2))
                    (dest / "observations.json").write_text(json.dumps(record, indent=2))
                    (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                    context.tracing.stop(path=str(dest / "trace.zip"))
                    if network is not None:
                        network.close()
                    context.close()
        browser.close()
    print(json.dumps({"status": "passed", "scenarios": records}))


if __name__ == "__main__":
    run()
