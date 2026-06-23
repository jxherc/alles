"""regression test for the 11th bug-hunt iteration:
a partial PATCH to a cookbook entry must not wipe the fields it doesn't send.
"""

import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db


class CookbookPatchTests(unittest.TestCase):
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

    def test_partial_patch_keeps_description(self):
        eid = self.c.post(
            "/api/cookbook",
            json={"name": "summarize", "description": "shorten text", "prompt": "tl;dr this"},
        ).json()["id"]
        # patch only the prompt; description must survive
        self.c.patch(f"/api/cookbook/{eid}", json={"prompt": "make it shorter"})
        got = self.c.get("/api/cookbook").json()
        entry = next(x for x in got if x["id"] == eid)
        self.assertEqual(entry["description"], "shorten text")  # not wiped
        self.assertEqual(entry["prompt"], "make it shorter")


if __name__ == "__main__":
    unittest.main()
