import tempfile
import threading
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.database import (
    DEFAULT_LOCAL_STORAGE_LOCATION_ID,
    FileOperation,
    IndexChunk,
    Share,
    StorageLocation,
    TrashItem,
)
from services import storage_locations
from tests._client import ApiTest


class StorageLocationApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()
        super().tearDown()

    def test_list_bootstraps_one_default_local_without_secrets(self):
        response = self.client.get("/api/storage-locations")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["locations"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "default-local")
        self.assertEqual(rows[0]["kind"], "local")
        self.assertTrue(rows[0]["is_default"])
        self.assertNotIn("secret", rows[0])
        self.assertNotIn("credentials", rows[0])

    def test_concurrent_first_access_creates_one_default_location(self):
        engine = create_engine(
            f"sqlite:///{self.root / 'concurrent.sqlite'}",
            connect_args={"check_same_thread": False, "timeout": 5},
        )
        StorageLocation.__table__.create(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        barrier = threading.Barrier(2)
        errors = []

        def worker():
            db = factory()
            original_get = db.get
            first_get = True

            def synchronized_get(entity, identity, *args, **kwargs):
                nonlocal first_get
                row = original_get(entity, identity, *args, **kwargs)
                if first_get:
                    first_get = False
                    barrier.wait(timeout=5)
                return row

            db.get = synchronized_get
            try:
                storage_locations.ensure_default_local(db)
            except Exception as exc:
                errors.append(exc)
            finally:
                db.close()

        with mock.patch("services.files_store.root_dir", return_value=self.root / "files"):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        try:
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            with factory() as db:
                self.assertEqual(
                    db.query(StorageLocation)
                    .filter_by(id=DEFAULT_LOCAL_STORAGE_LOCATION_ID)
                    .count(),
                    1,
                )
        finally:
            engine.dispose()

    def test_location_control_requires_recent_owner_auth(self):
        from core import auth

        created = self.client.post(
            "/api/storage-locations",
            json={
                "name": "guarded root",
                "kind": "local",
                "access": "managed",
                "root_path": str(self.root),
            },
        ).json()
        token = auth.create_session_token()
        auth.store_token(token)
        auth._recent_auth[token] = 0
        self.client.cookies.set("aide_session", token)
        requests = (
            (
                "post",
                "/api/storage-locations",
                {
                    "json": {
                        "name": "blocked root",
                        "kind": "local",
                        "access": "managed",
                        "root_path": str(self.root),
                    },
                },
            ),
            ("patch", f"/api/storage-locations/{created['id']}", {"json": {"name": "blocked"}}),
            ("delete", f"/api/storage-locations/{created['id']}", {}),
            ("post", f"/api/storage-locations/{created['id']}/test", {}),
            ("post", f"/api/storage-locations/{created['id']}/index", {}),
        )
        try:
            with (
                mock.patch("app.auth_enabled", return_value=True),
                mock.patch("core.settings.auth_enabled", return_value=True),
            ):
                for method, path, kwargs in requests:
                    with self.subTest(method=method, path=path):
                        response = getattr(self.client, method)(path, **kwargs)
                        self.assertEqual(response.status_code, 403, response.text)
                        self.assertEqual(response.json()["code"], "recent_auth_required")
        finally:
            auth._tokens.clear()
            auth._recent_auth.clear()

    def test_create_local_location_seals_secret_and_never_returns_it(self):
        response = self.client.post(
            "/api/storage-locations",
            json={
                "name": "archive",
                "kind": "local",
                "access": "read_only",
                "root_path": str(self.root),
                "credentials": {"token": "never-return-me"},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["name"], "archive")
        self.assertEqual(body["access"], "read_only")
        self.assertNotIn("credentials", body)
        self.assertNotIn("secret", body)

        with self.eng.connect() as conn:
            raw = conn.execute(
                text("SELECT secret FROM storage_locations WHERE id=:id"),
                {"id": body["id"]},
            ).scalar_one()
        self.assertNotIn("never-return-me", raw)
        self.assertTrue(raw.startswith("enc2:"))

    def test_connection_test_is_read_only_and_reports_local_state(self):
        created = self.client.post(
            "/api/storage-locations",
            json={
                "name": "local test",
                "kind": "local",
                "access": "managed",
                "root_path": str(self.root),
            },
        ).json()
        response = self.client.post(f"/api/storage-locations/{created['id']}/test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "state": "ready", "writable": True})
        self.assertEqual(list(self.root.iterdir()), [])

    def test_backend_coordinates_are_immutable_after_location_creation(self):
        created = self.client.post(
            "/api/storage-locations",
            json={
                "name": "fixed root",
                "kind": "local",
                "access": "managed",
                "root_path": str(self.root),
            },
        ).json()

        moved_root = self.root.parent / "different-root"
        response = self.client.patch(
            f"/api/storage-locations/{created['id']}",
            json={"root_path": str(moved_root)},
        )

        self.assertEqual(response.status_code, 409, response.text)
        current = self.client.get("/api/storage-locations").json()["locations"]
        row = next(item for item in current if item["id"] == created["id"])
        self.assertEqual(row["root_path"], str(self.root))

    def test_rejects_invalid_kind_access_and_relative_local_root(self):
        for payload in (
            {"name": "bad", "kind": "ftp", "access": "managed"},
            {"name": "bad", "kind": "local", "access": "owner"},
            {
                "name": "bad",
                "kind": "local",
                "access": "managed",
                "root_path": "relative/path",
            },
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    self.client.post("/api/storage-locations", json=payload).status_code,
                    400,
                )

    def test_create_rejects_escaping_prefix_and_stores_a_canonical_prefix(self):
        invalid = self.client.post(
            "/api/storage-locations",
            json={
                "name": "unsafe webdav",
                "kind": "webdav",
                "access": "managed",
                "endpoint": "https://dav.example.test",
                "prefix": "../private",
                "credentials": {"username": "user", "password": "secret"},
            },
        )
        valid = self.client.post(
            "/api/storage-locations",
            json={
                "name": "safe webdav",
                "kind": "webdav",
                "access": "managed",
                "endpoint": "https://dav.example.test",
                "prefix": "/team/./files/",
                "credentials": {"username": "user", "password": "secret"},
            },
        )

        self.assertEqual(invalid.status_code, 400, invalid.text)
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(valid.json()["prefix"], "team/files")

    def test_default_location_cannot_be_removed(self):
        self.client.get("/api/storage-locations")
        response = self.client.delete("/api/storage-locations/default-local")
        self.assertEqual(response.status_code, 409)
        db = self.db()
        self.assertIsNotNone(db.get(StorageLocation, "default-local"))
        db.close()

    def test_default_location_cannot_be_disabled(self):
        self.client.get("/api/storage-locations")

        response = self.client.patch(
            "/api/storage-locations/default-local",
            json={"enabled": False},
        )

        self.assertEqual(response.status_code, 409, response.text)
        db = self.db()
        self.assertTrue(db.get(StorageLocation, "default-local").enabled)
        db.close()

    def test_completed_operation_history_does_not_permanently_block_location_removal(self):
        created = self.client.post(
            "/api/storage-locations",
            json={
                "name": "finished work",
                "kind": "local",
                "access": "managed",
                "root_path": str(self.root),
            },
        ).json()
        db = self.db()
        db.add(
            FileOperation(
                action="copy",
                source_location_id=created["id"],
                source_path="old.txt",
                destination_location_id="default-local",
                destination_path="old.txt",
                state="completed",
            )
        )
        db.commit()
        db.close()

        response = self.client.delete(f"/api/storage-locations/{created['id']}")

        self.assertEqual(response.status_code, 200, response.text)

    def test_retryable_failed_operation_blocks_location_removal(self):
        for state in ("failed",):
            with self.subTest(state=state):
                root = self.root / state
                root.mkdir()
                created = self.client.post(
                    "/api/storage-locations",
                    json={
                        "name": f"{state} work",
                        "kind": "local",
                        "access": "managed",
                        "root_path": str(root),
                    },
                ).json()
                db = self.db()
                db.add(
                    FileOperation(
                        action="copy",
                        source_location_id=created["id"],
                        source_path="old.txt",
                        destination_location_id="default-local",
                        destination_path="old.txt",
                        state=state,
                    )
                )
                db.commit()
                db.close()

                response = self.client.delete(f"/api/storage-locations/{created['id']}")

                self.assertEqual(response.status_code, 409, response.text)

    def test_cancelled_operation_can_be_discarded_before_location_removal(self):
        root = self.root / "cancelled"
        root.mkdir()
        created = self.client.post(
            "/api/storage-locations",
            json={
                "name": "cancelled work",
                "kind": "local",
                "access": "managed",
                "root_path": str(root),
            },
        ).json()
        db = self.db()
        operation = FileOperation(
            action="copy",
            source_location_id=created["id"],
            source_path="never-started.txt",
            destination_location_id="default-local",
            destination_path="never-started.txt",
            state="cancelled",
        )
        db.add(operation)
        db.commit()
        operation_id = operation.id
        db.close()

        blocked = self.client.delete(f"/api/storage-locations/{created['id']}")
        discarded = self.client.delete(f"/api/files/operations/{operation_id}")
        removed = self.client.delete(f"/api/storage-locations/{created['id']}")

        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(discarded.status_code, 200, discarded.text)
        self.assertEqual(removed.status_code, 200, removed.text)

    def test_completed_operation_with_actionable_undo_blocks_location_removal(self):
        created = self.client.post(
            "/api/storage-locations",
            json={
                "name": "undoable work",
                "kind": "local",
                "access": "managed",
                "root_path": str(self.root),
            },
        ).json()
        db = self.db()
        db.add(
            FileOperation(
                action="copy",
                source_location_id=created["id"],
                source_path="kept.txt",
                destination_location_id="default-local",
                destination_path="kept.txt",
                state="completed",
                undo_json='{"undo":"remove_copy"}',
            )
        )
        db.commit()
        db.close()

        response = self.client.delete(f"/api/storage-locations/{created['id']}")
        operations = self.client.get("/api/files/operations").json()["operations"]
        operation_id = next(
            item["id"] for item in operations if item["source_location_id"] == created["id"]
        )
        self.assertTrue(
            next(item for item in operations if item["id"] == operation_id)["can_discard"]
        )
        discarded = self.client.delete(f"/api/files/operations/{operation_id}")
        removed = self.client.delete(f"/api/storage-locations/{created['id']}")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(discarded.status_code, 200, discarded.text)
        self.assertEqual(removed.status_code, 200, removed.text)

    def test_active_operation_still_blocks_location_removal(self):
        created = self.client.post(
            "/api/storage-locations",
            json={
                "name": "active work",
                "kind": "local",
                "access": "managed",
                "root_path": str(self.root),
            },
        ).json()
        db = self.db()
        db.add(
            FileOperation(
                action="copy",
                source_location_id=created["id"],
                source_path="work.txt",
                destination_location_id="default-local",
                destination_path="work.txt",
                state="queued",
            )
        )
        db.commit()
        db.close()

        response = self.client.delete(f"/api/storage-locations/{created['id']}")

        self.assertEqual(response.status_code, 409, response.text)

    def test_location_with_trash_or_share_identity_cannot_be_removed(self):
        for model, values in (
            (
                TrashItem,
                {
                    "kind": "file",
                    "ref": "kept.txt",
                    "location_id": "",
                    "normalized_path": "kept.txt",
                },
            ),
            (
                Share,
                {
                    "kind": "file",
                    "ref": "kept.txt",
                    "location_id": "",
                    "normalized_path": "kept.txt",
                },
            ),
        ):
            with self.subTest(model=model.__name__):
                created = self.client.post(
                    "/api/storage-locations",
                    json={
                        "name": f"{model.__name__} root",
                        "kind": "local",
                        "access": "read_only",
                        "root_path": str(self.root),
                    },
                ).json()
                values["location_id"] = created["id"]
                db = self.db()
                db.add(model(**values))
                db.commit()
                db.close()

                response = self.client.delete(f"/api/storage-locations/{created['id']}")
                self.assertEqual(response.status_code, 409, response.text)

    def test_location_with_only_derived_index_rows_can_be_removed(self):
        created = self.client.post(
            "/api/storage-locations",
            json={
                "name": "indexed root",
                "kind": "local",
                "access": "read_only",
                "root_path": str(self.root),
            },
        ).json()
        db = self.db()
        db.add(
            IndexChunk(
                kind="file",
                ref="kept.txt",
                location_id=created["id"],
                normalized_path="kept.txt",
                text="derived search text",
            )
        )
        db.commit()
        db.close()

        response = self.client.delete(f"/api/storage-locations/{created['id']}")

        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        self.assertEqual(
            db.query(IndexChunk).filter(IndexChunk.location_id == created["id"]).count(),
            0,
        )
        db.close()

    def test_webdav_location_test_reports_detected_capabilities(self):
        created = self.client.post(
            "/api/storage-locations",
            json={
                "name": "remote",
                "kind": "webdav",
                "access": "read_only",
                "endpoint": "https://dav.example.test/files",
                "credentials": {"username": "me", "password": "secret"},
            },
        ).json()
        with patch(
            "services.webdav_locations.capabilities",
            return_value={
                "ok": True,
                "state": "ready",
                "writable": False,
                "supports_etag": True,
                "supports_ranges": True,
            },
        ):
            response = self.client.post(f"/api/storage-locations/{created['id']}/test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "ready")
        self.assertTrue(response.json()["supports_etag"])

    def test_remote_public_config_cannot_echo_secrets(self):
        response = self.client.post(
            "/api/storage-locations",
            json={
                "name": "objects",
                "kind": "s3",
                "access": "read_only",
                "endpoint": "https://s3.example.test",
                "bucket": "files-bucket",
                "config": {
                    "region": "us-east-1",
                    "addressing_style": "path",
                },
                "credentials": {
                    "access_key_id": "test-key",
                    "secret_access_key": "real-secret",
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["config"], {"region": "us-east-1", "addressing_style": "path"})
        self.assertNotIn("real-secret", response.text)
        self.assertNotIn("test-key", response.text)

        rejected = self.client.post(
            "/api/storage-locations",
            json={
                "name": "invalid objects",
                "kind": "s3",
                "access": "read_only",
                "endpoint": "https://s3.example.test",
                "bucket": "files-bucket",
                "config": {"secret_access_key": "must-not-survive"},
                "credentials": {
                    "access_key_id": "test-key",
                    "secret_access_key": "real-secret",
                },
            },
        )
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertNotIn("must-not-survive", rejected.text)
        self.assertNotIn("real-secret", rejected.text)
        self.assertNotIn("test-key", rejected.text)

    def test_s3_location_rejects_invalid_config_before_persisting(self):
        for config in (
            {"addressing_style": "invalid"},
            {"addressing_style": 7},
            {"region": 7},
            {"unknown": "value"},
        ):
            with self.subTest(config=config):
                response = self.client.post(
                    "/api/storage-locations",
                    json={
                        "name": "invalid objects",
                        "kind": "s3",
                        "access": "read_only",
                        "endpoint": "https://s3.example.test",
                        "bucket": "files-bucket",
                        "config": config,
                        "credentials": {
                            "access_key_id": "test-key",
                            "secret_access_key": "real-secret",
                        },
                    },
                )
                self.assertEqual(response.status_code, 400, response.text)

    def test_webdav_creation_rejects_lookalike_loopback_host(self):
        response = self.client.post(
            "/api/storage-locations",
            json={
                "name": "bad",
                "kind": "webdav",
                "access": "read_only",
                "endpoint": "http://localhost.evil.test/files",
            },
        )
        self.assertEqual(response.status_code, 400)
