"""Conditional local uploads and recoverable version replacement on owned SQLite/files."""

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from starlette.testclient import TestClient

from core import database
from core.database import FileOperation, FileVersion, StorageLocation
from services import file_operations, fileversions
from services import files_store as fs
from tests._client import ApiTest, app


class FilesUploadRecoveryTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-upload-recovery-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.files = self.root / "files"
        self.files.mkdir()
        self.eng.dispose()
        self.eng = create_engine(
            f"sqlite:///{self.root / 'api.sqlite'}", connect_args={"check_same_thread": False}
        )
        database.Base.metadata.create_all(self.eng)
        database.engine = self.eng
        database.SessionLocal.configure(bind=self.eng)
        self.patches = [
            mock.patch.object(fs, "files_dir", return_value=self.files),
            mock.patch.object(fileversions, "data_dir", return_value=self.root / "versions-data"),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.client.get("/api/storage-locations").raise_for_status()

    def upload(self, content, name="draft.txt", expected=None, client=None, location=None):
        fields = {}
        if expected is not None:
            fields["expected_etag"] = expected
        if location:
            fields["location_id"] = location
        return (client or self.client).post(
            "/api/files/upload", data=fields, files={"file": (name, content, "text/plain")}
        )

    def token(self, name="draft.txt"):
        listed = self.client.get("/api/files/list").json()["items"]
        return next(item["etag"] for item in listed if item["name"] == name)

    def versions(self, name="draft.txt"):
        return self.client.get("/api/files/versions", params={"path": name}).json()

    def seed(self, content=b"original", name="draft.txt"):
        target = self.files / name
        target.write_bytes(content)
        return target

    def test_new_upload_keeps_legacy_create_contract(self):
        response = self.upload(b"new")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((self.files / "draft.txt").read_bytes(), b"new")
        self.assertEqual(response.json()["etag"], self.token())
        self.assertEqual(self.versions(), [])

    def test_missing_review_never_replaces_an_existing_file(self):
        target = self.seed()
        response = self.upload(b"replacement")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["expected_etag"], self.token())
        self.assertTrue(response.json()["detail"]["can_replace"])
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(self.versions(), [])

    def test_approved_replacement_preserves_exact_original_version(self):
        target = self.seed()
        response = self.upload(b"replacement", expected=self.token())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(target.read_bytes(), b"replacement")
        with self.db() as db:
            self.assertEqual(fileversions.content(db.query(FileVersion).one()), b"original")
        self.assertEqual(response.json()["etag"], self.token())

    def test_lost_ack_retry_is_a_noop_even_with_the_old_identity(self):
        self.seed()
        expected = self.token()
        first = self.upload(b"saved", expected=expected)
        retry = self.upload(b"saved", expected=expected)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertTrue(retry.json()["unchanged"])
        self.assertEqual(len(self.versions()), 1)
        self.assertEqual(first.json()["etag"], retry.json()["etag"])

    def test_changed_file_rejects_stale_approval(self):
        target = self.seed()
        expected = self.token()
        target.write_bytes(b"other writer")
        response = self.upload(b"replacement", expected=expected)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(target.read_bytes(), b"other writer")
        self.assertEqual(self.versions(), [])
        self.assertNotEqual(response.json()["detail"]["expected_etag"], expected)

    def test_removal_after_review_does_not_resurrect_the_file(self):
        target = self.seed()
        expected = self.token()
        target.unlink()
        response = self.upload(b"replacement", expected=expected)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(target.exists())

    def test_large_original_is_blocked_even_with_its_valid_identity(self):
        target = self.seed(b"123456")
        expected = self.token()
        with mock.patch.object(fileversions, "CAP_BYTES", 4):
            review = self.upload(b"new")
            response = self.upload(b"new", expected=expected)
        self.assertFalse(review.json()["detail"]["can_replace"])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(target.read_bytes(), b"123456")
        self.assertEqual(self.versions(), [])

    def test_snapshot_failure_cannot_replace_original(self):
        target = self.seed()
        with mock.patch.object(fileversions, "snapshot", side_effect=OSError("full")):
            response = self.upload(b"new", expected=self.token())
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(target.read_bytes(), b"original")

    def test_publish_failure_keeps_original_and_verified_history(self):
        target = self.seed()
        expected = self.token()
        with mock.patch.object(fs.os, "replace", side_effect=OSError("disk full")):
            response = self.upload(b"new", expected=expected)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual([p.name for p in self.files.iterdir()], ["draft.txt"])
        with self.db() as db:
            self.assertEqual(fileversions.content(db.query(FileVersion).one()), b"original")

    def test_snapshot_must_remain_recoverable_when_prior_blob_is_missing(self):
        target = self.seed()
        with self.db() as db:
            first = fileversions.snapshot(db, "draft.txt", target)
            (fileversions.versions_dir() / first.stored).unlink()
        response = self.upload(b"new", expected=self.token())
        self.assertEqual(response.status_code, 200, response.text)
        with self.db() as db:
            newest = db.query(FileVersion).order_by(FileVersion.created_at.desc()).first()
            self.assertEqual(fileversions.content(newest), b"original")

    def test_external_change_during_snapshot_is_preserved(self):
        target = self.seed()
        expected = self.token()
        snapshot = fileversions.snapshot

        def changed(*args, **kwargs):
            version = snapshot(*args, **kwargs)
            target.write_bytes(b"external change")
            return version

        with mock.patch.object(fileversions, "snapshot", side_effect=changed):
            response = self.upload(b"new", expected=expected)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(target.read_bytes(), b"external change")

    def test_new_file_publish_is_atomic_no_clobber(self):
        link = fs.os.link
        target = self.files / "draft.txt"

        injected = []

        def appear_before_publish(source, destination, *args, **kwargs):
            if Path(destination).resolve() == target:
                injected.append(True)
                target.write_bytes(b"concurrent creator")
            return link(source, destination, *args, **kwargs)

        with mock.patch.object(fs.os, "link", side_effect=appear_before_publish):
            response = self.upload(b"new")
        self.assertEqual(injected, [True])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(target.read_bytes(), b"concurrent creator")
        self.assertEqual([p.name for p in self.files.iterdir()], ["draft.txt"])

    def _race(self, alias=False):
        target = self.seed()
        expected = self.token()
        if alias:
            with self.db() as db:
                db.add(
                    StorageLocation(
                        id="alias",
                        name="alias",
                        kind="local",
                        access="managed",
                        root_path=str(self.files),
                        enabled=True,
                    )
                )
                db.commit()
        entered = threading.Event()
        release = threading.Event()
        snapshot = fileversions.snapshot
        claim = file_operations.direct_mutation_claim
        sessions = []
        connections = []

        @contextmanager
        def observed_claim(db, *args, **kwargs):
            sessions.append(id(db))
            connections.append(id(db.connection().connection.driver_connection))
            with claim(db, *args, **kwargs) as row:
                yield row

        def held_snapshot(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError("race release did not arrive")
            return snapshot(*args, **kwargs)

        def first_upload():
            client = TestClient(app)
            try:
                return self.upload(b"winner", expected=expected, client=client)
            finally:
                client.close()

        with (
            mock.patch.object(fileversions, "snapshot", side_effect=held_snapshot),
            mock.patch.object(file_operations, "direct_mutation_claim", side_effect=observed_claim),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            first = pool.submit(first_upload)
            try:
                self.assertTrue(entered.wait(5))
                client = TestClient(app)
                try:
                    second = self.upload(
                        b"loser",
                        expected=expected,
                        client=client,
                        location="alias" if alias else None,
                    )
                finally:
                    client.close()
                self.assertEqual(second.status_code, 409, second.text)
                self.assertEqual(target.read_bytes(), b"original")
            finally:
                release.set()
            winner = first.result(timeout=5)
        self.assertEqual(winner.status_code, 200, winner.text)
        self.assertEqual(len(set(sessions)), 2)
        self.assertEqual(len(set(connections)), 2)
        self.assertEqual(target.read_bytes(), b"winner")
        self.assertEqual(len(self.versions()), 1)
        with self.db() as db:
            self.assertEqual(db.query(FileOperation).count(), 0)
        stale_retry = self.upload(b"loser", expected=expected)
        self.assertEqual(stale_retry.status_code, 409)
        self.assertEqual(target.read_bytes(), b"winner")

    def test_separate_sessions_racing_same_file_only_one_can_replace(self):
        self._race()

    def test_aliased_connected_location_uses_the_same_physical_claim(self):
        self._race(alias=True)

    def test_restore_requires_current_identity_and_keeps_the_replaced_version(self):
        target = self.seed()
        self.upload(b"new", expected=self.token()).raise_for_status()
        version = self.versions()[0]
        payload = {"path": "draft.txt", "id": version["id"]}
        review = self.client.post("/api/files/versions/restore", json=payload)
        self.assertEqual(review.status_code, 409)
        self.assertEqual(target.read_bytes(), b"new")
        payload["expected_etag"] = self.token()
        restored = self.client.post("/api/files/versions/restore", json=payload)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(restored.json()["etag"], self.token())
        with self.db() as db:
            contents = {fileversions.content(v) for v in db.query(FileVersion).all()}
        self.assertEqual(contents, {b"original", b"new"})

    def test_restore_pins_oldest_version_before_history_pruning(self):
        target = self.seed(b"old")
        self.upload(b"current", expected=self.token()).raise_for_status()
        oldest = self.versions()[0]["id"]
        with mock.patch.object(fileversions, "KEEP", 1):
            response = self.client.post(
                "/api/files/versions/restore",
                json={"path": "draft.txt", "id": oldest, "expected_etag": self.token()},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(target.read_bytes(), b"old")
        with self.db() as db:
            self.assertEqual(fileversions.content(db.query(FileVersion).one()), b"current")

    def test_restore_cannot_discard_large_current_file(self):
        target = self.seed(b"old")
        self.upload(b"new", expected=self.token()).raise_for_status()
        oldest = self.versions()[0]["id"]
        target.write_bytes(b"large current")
        with mock.patch.object(fileversions, "CAP_BYTES", 4):
            response = self.client.post(
                "/api/files/versions/restore",
                json={"path": "draft.txt", "id": oldest, "expected_etag": self.token()},
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(target.read_bytes(), b"large current")

    def test_restore_rejects_damaged_version_without_changing_current(self):
        target = self.seed()
        self.upload(b"new", expected=self.token()).raise_for_status()
        with self.db() as db:
            version = db.query(FileVersion).one()
            version_id = version.id
            (fileversions.versions_dir() / version.stored).write_bytes(b"bad")
        response = self.client.post(
            "/api/files/versions/restore",
            json={"path": "draft.txt", "id": version_id, "expected_etag": self.token()},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(target.read_bytes(), b"new")
