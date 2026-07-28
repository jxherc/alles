# in-process API harness: drives the REAL FastAPI app against a throwaway
# in-memory sqlite, no server / no port / no touching data/aide.db. underscore
# name keeps unittest from collecting it as a test module.
import atexit
import logging
import os
import tempfile
import unittest
from pathlib import Path


def _validated_inherited_test_root() -> Path | None:
    """Accept only a caller-owned temporary root with an exact ownership sentinel."""
    if os.environ.get("ALLES_TEST_DATA") != "1":
        return None
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "")
    if not run_id or len(run_id) > 128:
        return None
    raw = os.environ.get("ALLES_DATA", "")
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if root == temp_root or temp_root not in root.parents:
        return None
    owner = root / ".alles-test-owner"
    try:
        if owner.read_text(encoding="utf-8").strip() != run_id:
            return None
    except OSError:
        return None
    return root


# Never trust ALLES_DATA by itself: it may be the owner's live settings, vault, or backups. A caller
# can share an isolated root only by providing the temporary-path and ownership-sentinel proof above.
_INHERITED_TEST_DATA = _validated_inherited_test_root()
_TEST_DATA = None
if _INHERITED_TEST_DATA is None:
    _TEST_DATA = tempfile.TemporaryDirectory(prefix="alles-api-tests-")
    atexit.register(_TEST_DATA.cleanup)
    os.environ["ALLES_DATA"] = _TEST_DATA.name
else:
    os.environ["ALLES_DATA"] = str(_INHERITED_TEST_DATA)
os.environ["AUTH_ENABLED"] = "false"  # set before app import so dotenv can't flip it on us
logging.getLogger("httpx").setLevel(logging.WARNING)  # quiet the per-request request log

# Some test modules import core.settings before importing this harness. Rebind the one legacy
# import-time path and its key cache before importing the app so settings and encryption keys cannot
# split across the owner data root and this throwaway root.
import core.settings as _settings  # noqa: E402
import services.secretstore as _secretstore  # noqa: E402

_settings._SETTINGS_FILE = _settings.data_dir() / "settings.json"
_settings._clear_settings_cache()
_secretstore._KEY_FILE = None
_secretstore._key = None
_secretstore._key_path = None
_secretstore._keys = {}
_secretstore._active_id = ""

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import close_all_sessions  # noqa: E402
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
        # Subclasses commonly keep their own original module/path values. Use a specific field so a
        # subclass cannot accidentally orphan the shared SQLAlchemy engine during teardown.
        self._original_database_engine = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(
            bind=self.eng
        )  # shared sessionmaker → every route + get_db follows
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        close_all_sessions()
        db.SessionLocal.configure(bind=self._original_database_engine)
        db.engine = self._original_database_engine
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
