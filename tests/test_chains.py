"""stage 3c - composable tool chains / macros. tests first (RED)."""

import asyncio
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import chains


def _run(steps, invoke):
    return asyncio.run(chains.run_chain(steps, invoke=invoke))


class RunTests(unittest.TestCase):
    def test_runs_in_order(self):
        seen = []

        async def inv(name, args, kind="tool"):
            seen.append(name)
            return {"ok": True, "name": name}

        out = _run([{"name": "a"}, {"name": "b"}], inv)
        self.assertTrue(out["ok"])
        self.assertEqual(seen, ["a", "b"])
        self.assertEqual(len(out["results"]), 2)

    def test_templating_from_prior_step(self):
        captured = {}

        async def inv(name, args, kind="tool"):
            if name == "second":
                captured["args"] = args
                return {"done": True}
            return {"value": "hello"}

        steps = [
            {"name": "first"},
            {"name": "second", "args": {"q": "{{0.value}}"}},
        ]
        _run(steps, inv)
        self.assertEqual(captured["args"]["q"], "hello")

    def test_whole_result_reference(self):
        captured = {}

        async def inv(name, args, kind="tool"):
            if name == "b":
                captured["args"] = args
                return {}
            return {"x": 1}

        _run([{"name": "a"}, {"name": "b", "args": {"prev": "{{0}}"}}], inv)
        self.assertIn("x", captured["args"]["prev"])  # serialized prior result

    def test_error_stops_chain(self):
        seen = []

        async def inv(name, args, kind="tool"):
            seen.append(name)
            if name == "boom":
                raise RuntimeError("kaboom")
            return {"ok": True}

        out = _run([{"name": "a"}, {"name": "boom"}, {"name": "never"}], inv)
        self.assertFalse(out["ok"])
        self.assertEqual(seen, ["a", "boom"])  # third never ran
        self.assertIn("kaboom", out["results"][-1].get("error", ""))

    def test_empty_chain(self):
        async def inv(name, args, kind="tool"):
            return {}

        out = _run([], inv)
        self.assertTrue(out["ok"])
        self.assertEqual(out["results"], [])

    def test_kind_passthrough(self):
        seen = {}

        async def inv(name, args, kind="tool"):
            seen["kind"] = kind
            return {}

        _run([{"name": "x", "kind": "action"}], inv)
        self.assertEqual(seen["kind"], "action")

    def test_missing_ref_left_intact(self):
        captured = {}

        async def inv(name, args, kind="tool"):
            captured["args"] = args
            return {}

        _run([{"name": "x", "args": {"q": "{{9.nope}}"}}], inv)
        self.assertEqual(captured["args"]["q"], "{{9.nope}}")  # no such step -> unchanged

    def test_non_string_args_untouched(self):
        captured = {}

        async def inv(name, args, kind="tool"):
            captured["args"] = args
            return {}

        _run([{"name": "x", "args": {"n": 5, "flag": True}}], inv)
        self.assertEqual(captured["args"], {"n": 5, "flag": True})


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        from fastapi.testclient import TestClient

        from app import app

        self.c = TestClient(app)

    def tearDown(self):
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_crud(self):
        r = self.c.post(
            "/api/chains",
            json={"name": "m1", "steps": [{"name": "recall", "args": {"query": "x"}}]},
        )
        self.assertEqual(r.status_code, 200)
        cid = r.json()["id"]
        self.assertTrue(any(x["id"] == cid for x in self.c.get("/api/chains").json()["chains"]))
        self.assertEqual(self.c.delete(f"/api/chains/{cid}").status_code, 200)
        self.assertFalse(any(x["id"] == cid for x in self.c.get("/api/chains").json()["chains"]))

    def test_run_endpoint(self):
        import services.capabilities as cap

        async def fake(name, args, kind="tool"):
            return {"echoed": name}

        orig = cap.invoke
        cap.invoke = fake
        try:
            cid = self.c.post(
                "/api/chains", json={"name": "m", "steps": [{"name": "recall"}]}
            ).json()["id"]
            out = self.c.post(f"/api/chains/{cid}/run").json()
        finally:
            cap.invoke = orig
        self.assertTrue(out["ok"])
        self.assertEqual(out["results"][0]["echoed"], "recall")


if __name__ == "__main__":
    unittest.main()
