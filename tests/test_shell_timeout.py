"""shell/python exec endpoints must reject a non-positive timeout — a 0/negative value makes
asyncio.wait_for 'time out' instantly, so the command never runs while reporting 'timed out
after -5s'. validation should 422 it up front instead."""

from tests._client import ApiTest


class ShellTimeoutTest(ApiTest):
    def test_exec_rejects_nonpositive_timeout(self):
        for t in (-5, 0):
            r = self.client.post("/api/shell/exec", json={"command": "echo hi", "timeout": t})
            self.assertEqual(r.status_code, 422, t)

    def test_stream_rejects_nonpositive_timeout(self):
        r = self.client.post("/api/shell/stream", json={"command": "echo hi", "timeout": 0})
        self.assertEqual(r.status_code, 422)

    def test_python_rejects_nonpositive_timeout(self):
        r = self.client.post("/api/execute/python", json={"code": "print(1)", "timeout": -1})
        self.assertEqual(r.status_code, 422)

    def test_default_timeout_is_accepted(self):
        # omitting timeout uses the default (positive) — must NOT 422 on validation
        r = self.client.post("/api/shell/exec", json={"command": "echo hi", "timeout": 5})
        self.assertNotEqual(r.status_code, 422)
