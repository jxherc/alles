"""Own Chromium page/worker network emulation as one offline-test fixture.

Playwright updates page targets before worker targets on reconnect. That emits
online while worker replay is still forcibly offline. Release the worker first,
prove its real GET connectivity, then let Chromium emit the page's online event.
No app events or queue messages are synthesized and no writes are retried here.
"""

from __future__ import annotations

import json
import time


class OfflineNetwork:
    def __init__(self, browser, context, page, worker):
        self.page = page
        self.worker = worker
        self.page_session = context.new_cdp_session(page)
        self.browser_session = browser.new_browser_cdp_session()
        info = self.page_session.send("Target.getTargetInfo")["targetInfo"]
        targets = self.browser_session.send("Target.getTargets")["targetInfos"]
        matches = [
            target
            for target in targets
            if target["type"] == "service_worker"
            and target["url"] == worker.url
            and target.get("browserContextId") == info.get("browserContextId")
        ]
        assert len(matches) == 1, matches
        self.session_id = self.browser_session.send(
            "Target.attachToTarget", {"targetId": matches[0]["targetId"], "flatten": False}
        )["sessionId"]
        self.messages = {}
        self.message_id = 0
        self.browser_session.on("Target.receivedMessageFromTarget", self._receive)
        self.transitions = []

    def _receive(self, event):
        if event["sessionId"] == self.session_id:
            message = json.loads(event["message"])
            if "id" in message:
                self.messages[message["id"]] = message

    def _worker_network(self, offline):
        self.message_id += 1
        self.browser_session.send(
            "Target.sendMessageToTarget",
            {
                "sessionId": self.session_id,
                "message": json.dumps(
                    {
                        "id": self.message_id,
                        "method": "Network.emulateNetworkConditionsByRule",
                        "params": self._rules(offline),
                    }
                ),
            },
        )
        deadline = time.monotonic() + 5
        while self.message_id not in self.messages and time.monotonic() < deadline:
            self.page.wait_for_timeout(10)
        response = self.messages.pop(self.message_id, None)
        assert response is not None and "error" not in response, response

    @staticmethod
    def _conditions(offline):
        return {"offline": offline, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1}

    @classmethod
    def _rules(cls, offline):
        return {"matchedNetworkConditions": [{"urlPattern": "", **cls._conditions(offline)}]}

    def set_offline(self, offline):
        self._worker_network(offline)
        self.page_session.send("Network.emulateNetworkConditionsByRule", self._rules(offline))
        record = {"offline": offline}
        if not offline:
            assert self.page.evaluate("navigator.onLine") is False
            readiness = self.worker.evaluate("""async () => {
              const response = await fetch('/health', { cache: 'no-store' });
              return { status: response.status, body: await response.json() };
            }""")
            assert readiness == {"status": 200, "body": {"ok": True}}, readiness
            record["worker_ready_before_page_online"] = readiness
        self.page_session.send("Network.overrideNetworkState", self._conditions(offline))
        self.page.wait_for_function("expected => navigator.onLine === expected", arg=not offline)
        self.transitions.append(record)

    def close(self):
        self.browser_session.send("Target.detachFromTarget", {"sessionId": self.session_id})
        self.browser_session.detach()
        self.page_session.detach()
