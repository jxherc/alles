# in-process API harness: drives the REAL FastAPI app against a throwaway
# in-memory sqlite, no server / no port / no touching data/aide.db. underscore
# name keeps unittest from collecting it as a test module.
import os
import logging
import unittest

os.environ["AUTH_ENABLED"] = "false"  # set before app import so dotenv can't flip it on us
logging.getLogger("httpx").setLevel(logging.WARNING)  # quiet the per-request request log

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

import core.database as db
from app import app


class ApiTest(unittest.TestCase):
    def setUp(self):
        os.environ["AUTH_ENABLED"] = "false"
        # StaticPool = one shared connection, so the schema survives across the
        # threadpool fastapi runs sync routes in (a plain :memory: engine wouldn't)
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(
            bind=self.eng
        )  # shared sessionmaker → every route + get_db follows
        self.client = TestClient(app)

    def tearDown(self):
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    # convenience: open a session bound to the test db (for seeding rows directly)
    def db(self):
        return db.SessionLocal()
