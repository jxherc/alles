# in-process API harness: drives the REAL FastAPI app against a throwaway
# in-memory sqlite, no server / no port / no touching data/aide.db. underscore
# name keeps unittest from collecting it as a test module.
import logging
import os
import tempfile
import unittest

_TEST_DATA = None
if not os.environ.get("ALLES_DATA"):
    _TEST_DATA = tempfile.TemporaryDirectory(prefix="alles-api-tests-")
    os.environ["ALLES_DATA"] = _TEST_DATA.name
os.environ["AUTH_ENABLED"] = "false"  # set before app import so dotenv can't flip it on us
logging.getLogger("httpx").setLevel(logging.WARNING)  # quiet the per-request request log

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import core.database as db  # noqa: E402
from app import app  # noqa: E402


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


class VaultApiTest(ApiTest):
    """ApiTest + a throwaway vault dir per test. ApiTest only isolates the DB; the vault
    is real files on disk (vault_dir()), so without this any test that writes notes/docs
    would clobber data/vault."""

    def setUp(self):
        super().setUp()
        import shutil
        import tempfile
        from pathlib import Path

        from services import vault_md

        self._vault_tmp = tempfile.mkdtemp()
        self._vault_cleanup = shutil.rmtree
        self._orig_vault_dir = vault_md.vault_dir
        vault_md.vault_dir = lambda: Path(self._vault_tmp).resolve()

    def tearDown(self):
        from services import vault_md

        vault_md.vault_dir = self._orig_vault_dir
        self._vault_cleanup(self._vault_tmp, ignore_errors=True)
        super().tearDown()
