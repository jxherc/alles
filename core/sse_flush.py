"""Server-sent streams that WebKit can read as they go."""

import asyncio


class SseFlushMiddleware:
    """Safari and the other WebKit browsers hand a page only the first event of each network
    packet from a server-sent stream; the rest of that packet waits until the next one comes.
    A stream that then goes quiet (a tool waiting for approval, a question, a slow step) would
    hold back the very thing the owner has to answer. So once an event stream has been quiet
    for a moment, one empty comment goes out on its own, which makes WebKit hand over all it
    was holding. Pure ASGI, so the stream still passes through chunk by chunk."""

    QUIET = 0.1

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        loop = asyncio.get_running_loop()
        lock = asyncio.Lock()
        sent = asyncio.Event()
        state = {"sse": False, "done": False, "last": 0.0, "flushed": True}
        watcher = None

        async def watch():
            while not state["done"]:
                await sent.wait()
                wait = state["last"] + self.QUIET - loop.time()
                if wait > 0:
                    await asyncio.sleep(wait)
                    continue
                async with lock:
                    if state["done"] or state["flushed"]:
                        sent.clear()
                        continue
                    if loop.time() - state["last"] < self.QUIET:
                        continue
                    try:
                        await send(
                            {"type": "http.response.body", "body": b": \n\n", "more_body": True}
                        )
                    except Exception:
                        state["done"] = True  # the page went away; the app finds out on its own
                    state["flushed"] = True
                    sent.clear()

        async def send_with_flush(message):
            nonlocal watcher
            if message["type"] == "http.response.start":
                ctype = next(
                    (v for k, v in message.get("headers") or [] if k.lower() == b"content-type"),
                    b"",
                )
                state["sse"] = ctype.split(b";")[0].strip().lower() == b"text/event-stream"
            async with lock:
                if message["type"] == "http.response.body" and not message.get("more_body"):
                    state["done"] = True
                await send(message)
            if state["sse"] and message["type"] == "http.response.body" and not state["done"]:
                state["last"], state["flushed"] = loop.time(), False
                sent.set()
                if watcher is None:
                    watcher = asyncio.create_task(watch())

        try:
            await self.app(scope, receive, send_with_flush)
        finally:
            state["done"] = True
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
