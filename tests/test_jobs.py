import asyncio
import unittest

from services import jobs


class JobRegistryTests(unittest.TestCase):
    def setUp(self):
        for j in jobs.all_jobs():
            jobs.unregister(j.name)

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
            async def boom(): raise RuntimeError("nope")
            async def ok(): order.append("ok")
            jobs.register("boom", boom, 10)
            jobs.register("ok", ok, 10)
            ran = await jobs.run_due(now=0)
            self.assertEqual(ran, 1)            # only the good one counts
            self.assertEqual(order, ["ok"])
            self.assertEqual(jobs._jobs["boom"].fails, 1)
        asyncio.run(go())

    def test_event_bus_dispatch(self):
        async def go():
            got = []
            def sync_h(**d): got.append(("sync", d.get("x")))
            async def async_h(**d): got.append(("async", d.get("x")))
            jobs.on("ping", sync_h)
            jobs.on("ping", async_h)
            ran = await jobs.emit("ping", x=5)
            self.assertEqual(ran, 2)
            self.assertIn(("sync", 5), got)
            self.assertIn(("async", 5), got)
            jobs.off("ping", sync_h)
            await jobs.emit("ping", x=9)
            self.assertEqual(sum(1 for g in got if g[0] == "sync"), 1)   # sync handler removed
        asyncio.run(go())


async def _noop():
    return None


if __name__ == "__main__":
    unittest.main()
