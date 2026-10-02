import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from core import database, settings
from core.build_info import SQLITE_APPLICATION_ID
from core.migrations import runner
from services import secretstore
from services.recovery_consistency import recovery_consistency_lock
from tests._client import ApiTest


class SchemaOwnershipTest(ApiTest):
    def test_schema_import_registers_all_models_without_creating_database_infrastructure(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from core.schema.finance import Account; "
                "from core.schema import Base; "
                "from sqlalchemy.orm import configure_mappers; configure_mappers(); "
                "assert 'core.database' not in sys.modules; "
                "assert len(Base.metadata.tables) == 126; "
                "assert Account.metadata is Base.metadata",
            ],
            env=dict(os.environ, PYTHON_DOTENV_DISABLED="1"),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_exports_share_the_complete_registry_and_relationships(self):
        self.assertEqual(len(database.Base.registry.mappers), 126)
        for mapper in database.Base.registry.mappers:
            self.assertIs(getattr(database, mapper.class_.__name__), mapper.class_)
            self.assertIs(mapper.local_table.metadata, database.Base.metadata)
        with self.db() as session:
            endpoint = database.ModelEndpoint(name="provider", base_url="https://example.test")
            project = database.Project(name="project")
            chat = database.Session(name="chat", endpoint=endpoint, project=project)
            chat.messages.append(database.Message(role="user", content="hello"))
            session.add(chat)
            session.commit()
            self.assertEqual(session.get(database.Session, chat.id).endpoint.name, "provider")
            self.assertEqual(project.sessions[0].messages[0].content, "hello")
            session.delete(chat)
            session.commit()
            self.assertEqual(session.query(database.Message).count(), 0)
        with self.eng.connect() as connection:
            triggers = (
                connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))
                .scalars()
                .all()
            )
        self.assertEqual(
            set(triggers),
            {
                "trg_file_operation_path_claim_overlap_insert",
                "trg_file_operation_path_claim_overlap_update",
                "trg_file_operation_source_claim_overlap_insert",
                "trg_file_operation_source_claim_overlap_update",
            },
        )


class DatabaseStartupTest(ApiTest):
    def test_initialization_migrates_every_existing_connector_configuration(self):
        configs = {
            "settings.json": ("openai_api_key", "settings.openai_api_key", "legacy-key"),
            "caldav.json": ("password", "caldav.password", "legacy-calendar"),
            "carddav.json": ("password", "carddav.password", "legacy-contacts"),
            "webdav_backup.json": ("password", "backup.webdav.password", "legacy-webdav"),
            "s3_backup.json": (
                "credentials",
                "backup.s3.credentials",
                '{"access_key_id":"test-access","secret_access_key":"test-secret"}',
            ),
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, (field, _purpose, value) in configs.items():
                (root / name).write_text(json.dumps({field: value, "sentinel": name}), "utf-8")
            with (
                mock.patch.dict(os.environ, ALLES_DATA=temp),
                mock.patch.object(settings, "_SETTINGS_FILE", root / "settings.json"),
                mock.patch.multiple(
                    secretstore,
                    _KEY_FILE=root / "secret.key",
                    _key=None,
                    _key_path=None,
                    _keys={},
                    _active_id="",
                ),
            ):
                settings._clear_settings_cache()
                try:
                    database.init_db()
                    first_pass = {name: (root / name).read_bytes() for name in configs}
                    for name, (field, purpose, value) in configs.items():
                        sealed = json.loads(first_pass[name])
                        self.assertTrue(sealed[field].startswith("enc2:"), name)
                        self.assertEqual(secretstore.unseal(sealed[field], purpose), value)
                        self.assertEqual(sealed["sentinel"], name)
                    database.init_db()
                    self.assertEqual(
                        {name: (root / name).read_bytes() for name in configs}, first_pass
                    )
                finally:
                    settings._clear_settings_cache()

    def test_initialization_uses_the_current_engine_and_shared_session_factory(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "current.db")
            engine = create_engine(f"sqlite:///{path}")
            try:
                with (
                    mock.patch.object(database, "engine", engine),
                    mock.patch.object(database, "DB_PATH", path),
                ):
                    database.SessionLocal.configure(bind=engine)
                    database.init_db()
                    database.init_db()
                    generator = database.get_db()
                    session = next(generator)
                    try:
                        self.assertIs(session.get_bind(), engine)
                        session.add(database.Task(title="current engine"))
                        session.commit()
                    finally:
                        generator.close()
                    with engine.connect() as connection:
                        self.assertEqual(
                            connection.execute(text("PRAGMA application_id")).scalar(),
                            SQLITE_APPLICATION_ID,
                        )
                        self.assertEqual(
                            dict(
                                connection.execute(
                                    text("SELECT version,name FROM schema_migrations")
                                ).all()
                            ),
                            runner.migration_catalog(),
                        )
                        self.assertEqual(
                            connection.execute(text("SELECT title FROM tasks")).scalar(),
                            "current engine",
                        )
                with self.eng.connect() as connection:
                    self.assertEqual(
                        connection.execute(text("SELECT count(*) FROM tasks")).scalar(), 0
                    )
            finally:
                database.SessionLocal.configure(bind=self.eng)
                engine.dispose()

    def test_schema_failure_leaves_credentials_untouched_then_retry_seals_once(self):
        with self.eng.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO connections (id,service,token,meta) "
                    "VALUES ('legacy','github','plain-token','')"
                )
            )
        with (
            mock.patch("core.migrations.run_migrations", side_effect=RuntimeError("blocked")),
            mock.patch("core.settings.migrate_setting_secrets") as settings,
            mock.patch("services.caldav_sync.migrate_cfg_secrets") as caldav,
            mock.patch("services.carddav_sync.migrate_cfg_secrets") as carddav,
            mock.patch("services.s3_backup.migrate_config") as s3,
            mock.patch("services.webdav_backup.migrate_config") as webdav,
        ):
            with self.assertRaisesRegex(RuntimeError, "blocked"):
                database.init_db()
            for migration in (settings, caldav, carddav, s3, webdav):
                migration.assert_not_called()
        with self.eng.connect() as connection:
            self.assertEqual(
                connection.execute(text("SELECT token FROM connections")).scalar(), "plain-token"
            )
        database.init_db()
        with self.eng.connect() as connection:
            sealed = connection.execute(text("SELECT token FROM connections")).scalar()
        self.assertTrue(sealed.startswith("enc2:"))
        database.init_db()
        with self.eng.connect() as connection:
            self.assertEqual(
                connection.execute(text("SELECT token FROM connections")).scalar(), sealed
            )
        with self.db() as session:
            self.assertEqual(session.get(database.Connection, "legacy").token, "plain-token")

    def test_credential_reseal_compatibility_entrypoint_uses_the_rebound_engine(self):
        original = (
            secretstore._KEY_FILE,
            secretstore._key,
            secretstore._key_path,
            dict(secretstore._keys),
            secretstore._active_id,
        )
        with tempfile.TemporaryDirectory() as temp:
            secretstore._KEY_FILE = Path(temp) / "secret.key"
            secretstore._key = secretstore._key_path = None
            secretstore._keys = {}
            secretstore._active_id = ""
            try:
                with self.db() as session:
                    session.add(database.Connection(id="sealed", service="github", token="token"))
                    session.commit()
                with self.eng.connect() as connection:
                    before = connection.execute(text("SELECT token FROM connections")).scalar()
                active = secretstore.rotate_key()
                self.assertEqual(database._encrypt_plaintext_secrets(force_reseal=True), 2)
                with self.eng.connect() as connection:
                    after = connection.execute(text("SELECT token FROM connections")).scalar()
                self.assertNotEqual(before, after)
                self.assertEqual(secretstore.cipher_key_id(after), active)
                self.assertEqual(secretstore.unseal(after, "connections.token"), "token")
                self.assertEqual(database._encrypt_plaintext_secrets(), 0)
            finally:
                (
                    secretstore._KEY_FILE,
                    secretstore._key,
                    secretstore._key_path,
                    secretstore._keys,
                    secretstore._active_id,
                ) = original


class CredentialSessionLockTest(ApiTest):
    def _lock_available_in_another_thread(self):
        def try_lock():
            acquired = recovery_consistency_lock.acquire(blocking=False)
            if acquired:
                recovery_consistency_lock.release()
            return acquired

        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(try_lock).result(timeout=5)

    def test_nested_credential_transaction_retains_lock_until_outer_commit(self):
        with self.db() as session:
            session.add(database.Connection(id="one", service="github", token=""))
            session.flush()
            self.assertFalse(self._lock_available_in_another_thread())
            with session.begin_nested():
                session.get(database.Connection, "one").service = "gitlab"
                session.flush()
            self.assertFalse(self._lock_available_in_another_thread())
            session.commit()
            self.assertTrue(self._lock_available_in_another_thread())

    def test_failed_flush_retains_lock_until_rollback_and_close_releases_it(self):
        with self.db() as session:
            session.add(database.Connection(id="duplicate", service="github", token=""))
            session.commit()
            session.add(database.Connection(id="duplicate", service="gitlab", token=""))
            with self.assertRaises(IntegrityError):
                session.flush()
            self.assertFalse(self._lock_available_in_another_thread())
            session.rollback()
            self.assertTrue(self._lock_available_in_another_thread())
            session.add(database.Connection(id="closing", service="github", token=""))
            session.flush()
            self.assertFalse(self._lock_available_in_another_thread())
        self.assertTrue(self._lock_available_in_another_thread())

    def test_unrelated_changes_do_not_hold_the_credential_lock(self):
        with self.db() as session:
            session.add(database.Task(title="ordinary task"))
            session.flush()
            self.assertTrue(self._lock_available_in_another_thread())
