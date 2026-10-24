"""An event stream that goes quiet sends one empty comment, so WebKit hands over what it holds."""

import asyncio
import unittest

from core.sse_flush import SseFlushMiddleware


def _run(app, quiet=0.05):
    sent = []

    async def go():
        loop = asyncio.get_running_loop()
        start = loop.time()

        async def send(message):
            sent.append((round(loop.time() - start, 3), message))

        async def receive():
            await asyncio.sleep(10)
            return {"type": "http.disconnect"}

        middleware = SseFlushMiddleware(app)
        middleware.QUIET = quiet
        await middleware({"type": "http"}, receive, send)

    asyncio.run(go())
    return sent


def _bodies(sent):
    return [m.get("body", b"") for _, m in sent if m["type"] == "http.response.body"]


def _app(content_type, plan):
    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", content_type)],
            }
        )
        for item in plan:
            if isinstance(item, float):
                await asyncio.sleep(item)
            else:
                await send({"type": "http.response.body", "body": item, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    return app


class SseFlushTests(unittest.TestCase):
    def test_a_quiet_stream_gets_one_comment_per_quiet_spell(self):
        plan = [b"data: 1\n\n", b"data: 2\n\n", 0.2, b"data: 3\n\n", 0.2]
        bodies = _bodies(_run(_app(b"text/event-stream; charset=utf-8", plan)))
        self.assertEqual(
            bodies,
            [b"data: 1\n\n", b"data: 2\n\n", b": \n\n", b"data: 3\n\n", b": \n\n", b""],
        )

    def test_a_busy_stream_gets_none(self):
        plan = [b"data: 1\n\n", 0.01, b"data: 2\n\n", 0.01, b"data: 3\n\n"]
        bodies = _bodies(_run(_app(b"text/event-stream", plan)))
        self.assertNotIn(b": \n\n", bodies)

    def test_nothing_follows_the_end_and_other_responses_are_left_alone(self):
        ended = _run(_app(b"text/event-stream", [b"data: 1\n\n"]))
        self.assertEqual(_bodies(ended), [b"data: 1\n\n", b""])
        json_reply = _bodies(_run(_app(b"application/json", [b"{}", 0.2])))
        self.assertEqual(json_reply, [b"{}", b""])

    def test_a_page_that_went_away_ends_the_watch(self):
        async def app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")],
                }
            )
            await send({"type": "http.response.body", "body": b"data: 1\n\n", "more_body": True})
            await asyncio.sleep(0.2)

        async def go():
            calls = []

            async def send(message):
                calls.append(message)
                if message.get("body") == b": \n\n":
                    raise OSError("connection closed")

            async def receive():
                return {"type": "http.disconnect"}

            middleware = SseFlushMiddleware(app)
            middleware.QUIET = 0.05
            await middleware({"type": "http"}, receive, send)
            return calls

        calls = asyncio.run(go())
        self.assertEqual([m.get("body") for m in calls[1:]], [b"data: 1\n\n", b": \n\n"])


if __name__ == "__main__":
    unittest.main()
