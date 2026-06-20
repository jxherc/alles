import asyncio
import unittest

from services import jobs


class JobRegistryTests(unittest.TestCase):
    def setUp(self):
        for j in jobs.all_jobs():
            jobs.unregister(j.name)
        # also clear handlers added by tests
        jobs._handlers.clear()

    def test_runs_due_and_respects_interval(self):
        async def go():
            hits = []
            jobs.register("a", lambda: hits.append(1) or _noop(), 30)
            # first tick at t=0 → runs (run_at_start default)
            ran = await jobs.run_due(now=0)
            self.assertEqual(ran, 1)
            # not yet due at t=10
            self.assertEqual(await jobs.run_due(now=10), 0)
            # due again at t=40
            self.assertEqual(await jobs.run_due(now=40), 1)
            self.assertEqual(len(hits), 2)

        asyncio.run(go())

    def test_run_at_start_false_waits(self):
        async def go():
            jobs.register("b", _noop, 30, run_at_start=False)
            # last_run is set to ~now (monotonic); a tiny now won't be due
            self.assertEqual(await jobs.run_due(now=1), 0)

        asyncio.run(go())

    def test_failing_job_does_not_stall_others(self):
        async def go():
            order = []

            async def boom():
                raise RuntimeError("nope")

            async def ok():
                order.append("ok")

            jobs.register("boom", boom, 10)
            jobs.register("ok", ok, 10)
            ran = await jobs.run_due(now=0)
            self.assertEqual(ran, 1)  # only the good one counts
            self.assertEqual(order, ["ok"])
            self.assertEqual(jobs._jobs["boom"].fails, 1)

        asyncio.run(go())

    def test_event_bus_dispatch(self):
        async def go():
            got = []

            def sync_h(**d):
                got.append(("sync", d.get("x")))

            async def async_h(**d):
                got.append(("async", d.get("x")))

            jobs.on("ping", sync_h)
            jobs.on("ping", async_h)
            ran = await jobs.emit("ping", x=5)
            self.assertEqual(ran, 2)
            self.assertIn(("sync", 5), got)
            self.assertIn(("async", 5), got)
            jobs.off("ping", sync_h)
            await jobs.emit("ping", x=9)
            self.assertEqual(sum(1 for g in got if g[0] == "sync"), 1)  # sync handler removed

        asyncio.run(go())

    def test_register_returns_job(self):
        j = jobs.register("c", _noop, 60)
        self.assertEqual(j.name, "c")
        self.assertEqual(j.interval, 60)
        self.assertTrue(j.enabled)

    def test_unregister_removes_job(self):
        jobs.register("d", _noop, 5)
        jobs.unregister("d")
        names = {j.name for j in jobs.all_jobs()}
        self.assertNotIn("d", names)

    def test_job_run_count_increments(self):
        async def go():
            jobs.register("counter", _noop, 10)
            await jobs.run_due(now=0)
            await jobs.run_due(now=15)
            self.assertEqual(jobs._jobs["counter"].runs, 2)

        asyncio.run(go())

    def test_disabled_job_skipped(self):
        async def go():
            hits = []

            async def fn():
                hits.append(1)

            jobs.register("off", fn, 5)
            jobs._jobs["off"].enabled = False
            await jobs.run_due(now=0)
            self.assertEqual(hits, [])

        asyncio.run(go())

    def test_event_bus_no_handlers(self):
        # emit on unknown event → 0 ran, no error
        async def go():
            ran = await jobs.emit("ghost_event", foo=1)
            self.assertEqual(ran, 0)

        asyncio.run(go())

    def test_failing_handler_does_not_stall_next(self):
        async def go():
            results = []

            def bad(**d):
                raise ValueError("boom")

            def good(**d):
                results.append("ok")

            jobs.on("ev", bad)
            jobs.on("ev", good)
            ran = await jobs.emit("ev")
            # good handler still ran (bad is skipped, not counted)
            self.assertIn("ok", results)
            self.assertEqual(ran, 1)  # only the good handler counts

        asyncio.run(go())


async def _noop():
    return None


if __name__ == "__main__":
    unittest.main()
