import json
import os
import subprocess
import sys
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from services import document_safety, vault_md
from tests._client import VaultApiTest


class DocumentCreateApiTests(VaultApiTest):
    def setUp(self):
        super().setUp()
        self.state = tempfile.TemporaryDirectory(prefix="alles-create-state-")
        self.addCleanup(self.state.cleanup)
        patch = mock.patch.object(document_safety, "_state_root", lambda: Path(self.state.name))
        patch.start()
        self.addCleanup(patch.stop)
        self.body = {
            "path": "captured note",
            "content": "original source\r\n\n",
            "unique": True,
            "request_id": str(uuid.uuid4()),
        }

    def create(self, **changes):
        return self.client.post("/api/vault-md/file", json={**self.body, **changes})

    def test_lost_reply_reuses_one_note_and_exact_bytes(self):
        first = self.create()
        self.assertEqual(first.status_code, 200, first.text)
        second = self.create()
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["path"], first.json()["path"])
        self.assertEqual(second.json()["request_id"], self.body["request_id"])
        self.assertEqual(len(list(Path(self._vault_tmp).glob("*.md"))), 1)
        self.assertEqual(
            (Path(self._vault_tmp) / first.json()["path"]).read_bytes(),
            self.body["content"].encode(),
        )

    def test_changed_intent_is_rejected_without_another_file(self):
        original = self.create().json()
        for changes in ({"content": "changed"}, {"path": "other"}):
            response = self.create(**changes)
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(len(list(Path(self._vault_tmp).glob("*.md"))), 1)
        self.assertEqual(vault_md.read(original["path"])["content"], self.body["content"])

    def test_deleted_or_edited_result_is_not_recreated(self):
        first = self.create().json()
        path = Path(self._vault_tmp) / first["path"]
        path.write_text("new owner content")
        changed = self.create()
        self.assertEqual(changed.status_code, 409, changed.text)
        self.assertEqual(changed.json()["detail"]["path"], first["path"])
        self.assertEqual(path.read_text(), "new owner content")
        path.unlink()
        missing = self.create()
        self.assertEqual(missing.status_code, 410, missing.text)
        self.assertEqual(list(Path(self._vault_tmp).glob("*.md")), [])

    def test_new_request_and_legacy_clients_still_get_distinct_names(self):
        first = self.create().json()
        second = self.create(request_id=str(uuid.uuid4())).json()
        legacy = self.create(request_id="").json()
        self.assertEqual(len({first["path"], second["path"], legacy["path"]}), 3)
        ordinary = self.client.post("/api/vault-md/file", json={"path": first["path"]})
        self.assertTrue(ordinary.json()["existed"])

    def test_invalid_request_identity_or_nonunique_receipt_does_not_write(self):
        for changes in ({"request_id": "bad"}, {"unique": False}):
            response = self.create(**changes)
            self.assertIn(response.status_code, {400, 422}, response.text)
        self.assertEqual(list(Path(self._vault_tmp).glob("*.md")), [])

    def test_receipt_contains_no_note_body(self):
        response = self.create()
        self.assertEqual(response.status_code, 200, response.text)
        receipts = list(Path(self.state.name).rglob("*.json"))
        self.assertTrue(receipts)
        for path in receipts:
            data = json.loads(path.read_text())
            self.assertNotIn("content", data)
            self.assertNotIn(self.body["content"], path.read_text())

    def test_pending_storage_scope_is_private_and_survives_key_rotation(self):
        with (
            mock.patch("services.secretstore.active_key_id", return_value="current"),
            mock.patch("services.secretstore.key_ids", return_value={"current", "previous"}),
        ):
            response = self.client.get("/api/vault-md/create-scope")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")
            scopes = response.json()["scopes"]
            self.assertEqual(len(scopes), 2)
            for scope in scopes:
                self.assertRegex(scope, r"^[a-f0-9]{64}$")
        with (
            mock.patch("services.secretstore.active_key_id", return_value="next"),
            mock.patch(
                "services.secretstore.key_ids", return_value={"next", "current", "previous"}
            ),
        ):
            rotated = self.client.get("/api/vault-md/create-scope").json()["scopes"]
            self.assertEqual(rotated[1:], scopes)

    def test_vault_change_rejects_first_write_and_allows_return_to_original(self):
        context = self.client.get("/api/vault-md/create-scope").json()
        expected = context["vault_scopes"][0]
        with tempfile.TemporaryDirectory(prefix="alles-other-note-vault-") as other:
            with mock.patch.object(vault_md, "vault_dir", return_value=Path(other)):
                changed = self.client.get("/api/vault-md/create-scope").json()
                self.assertEqual(changed["scopes"], context["scopes"])
                self.assertNotIn(expected, changed["vault_scopes"])
                response = self.create(expected_vault=expected)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(list(Path(other).iterdir()), [])
                self.assertEqual(list(Path(self.state.name).rglob("*.json")), [])
        first = self.create(expected_vault=expected)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.create(expected_vault=expected).json(), first.json())
        self.assertEqual(len(list(Path(self._vault_tmp).glob("*.md"))), 1)

    def test_published_note_retry_cannot_cross_vault_and_retained_key_still_retries(self):
        with (
            mock.patch("services.secretstore.active_key_id", return_value="old"),
            mock.patch("services.secretstore.key_ids", return_value={"old"}),
        ):
            expected = self.client.get("/api/vault-md/create-scope").json()["vault_scopes"][0]
            first = self.create(expected_vault=expected)
            self.assertEqual(first.status_code, 200, first.text)
        with (
            mock.patch("services.secretstore.active_key_id", return_value="next"),
            mock.patch("services.secretstore.key_ids", return_value={"old", "next"}),
        ):
            self.assertEqual(self.create(expected_vault=expected).json(), first.json())
            with tempfile.TemporaryDirectory(prefix="alles-other-note-vault-") as other:
                with mock.patch.object(vault_md, "vault_dir", return_value=Path(other)):
                    response = self.create(expected_vault=expected)
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(list(Path(other).iterdir()), [])
        self.assertEqual(len(list(Path(self._vault_tmp).glob("*.md"))), 1)

    def test_destination_requires_valid_scope_and_request_identity(self):
        for changes in (
            {"expected_vault": "bad"},
            {"expected_vault": "a" * 64, "request_id": ""},
        ):
            response = self.create(**changes)
            self.assertIn(response.status_code, {400, 422}, response.text)
        self.assertEqual(list(Path(self._vault_tmp).glob("*.md")), [])

    def test_replay_survives_a_new_process(self):
        first = self.create().json()
        script = """
import json, sys
from pathlib import Path
from services import document_safety, vault_md
vault_md.vault_dir = lambda: Path(sys.argv[1])
document_safety._state_root = lambda: Path(sys.argv[2])
body = json.loads(sys.argv[3])
print(json.dumps(document_safety.create_document(body['path'], body['content'], body['request_id'])))
"""
        result = subprocess.run(
            [sys.executable, "-c", script, self._vault_tmp, self.state.name, json.dumps(self.body)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout)["path"], first["path"])
        self.assertEqual(len(list(Path(self._vault_tmp).glob("*.md"))), 1)

    def test_concurrent_retries_publish_only_one_note(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.service_create(), range(12)))
        self.assertEqual(len({result["path"] for result in results}), 1)
        self.assertEqual(len(list(Path(self._vault_tmp).glob("*.md"))), 1)

    def service_create(self):
        return document_safety.create_document(
            self.body["path"], self.body["content"], self.body["request_id"]
        )

    def test_interrupted_staging_or_intent_write_can_resume(self):
        for phase in ("before-intent", "after-intent"):
            with self.subTest(phase=phase):
                self.body.update(path=phase, request_id=str(uuid.uuid4()))
                write_json = document_safety._write_json

                def interrupt(path, value):
                    if phase == "after-intent":
                        write_json(path, value)
                    raise SystemExit("interrupted intent")

                with mock.patch.object(document_safety, "_write_json", side_effect=interrupt):
                    with self.assertRaisesRegex(SystemExit, "interrupted intent"):
                        self.service_create()
                self.assertFalse((Path(self._vault_tmp) / f"{phase}.md").exists())
                result = self.service_create()
                self.assertEqual(result["path"], f"{phase}.md")
                self.assertEqual(vault_md.read(result["path"])["content"], self.body["content"])
        self.assertEqual(len(list(Path(self._vault_tmp).glob("*.md"))), 2)

    def test_interrupted_final_receipt_preserves_note_for_inspection(self):
        write_json = document_safety._write_json

        def interrupt(path, value):
            if value["state"] == "published":
                raise SystemExit("interrupted receipt")
            write_json(path, value)

        with mock.patch.object(document_safety, "_write_json", side_effect=interrupt):
            with self.assertRaisesRegex(SystemExit, "interrupted receipt"):
                self.service_create()
        result = self.create()
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(result.json()["detail"]["path"], "captured note.md")
        self.assertEqual(vault_md.read("captured note.md")["content"], self.body["content"])
        self.assertEqual(len(list(Path(self._vault_tmp).glob("*.md"))), 1)

    def test_deleted_after_publication_before_receipt_never_recreates(self):
        publish = document_safety._publish_exclusive

        def interrupt(source, target):
            publish(source, target)
            target.unlink()
            raise SystemExit("deleted before acknowledgment")

        with mock.patch.object(document_safety, "_publish_exclusive", side_effect=interrupt):
            with self.assertRaises(SystemExit):
                self.service_create()
        response = self.create()
        self.assertEqual(response.status_code, 410, response.text)
        self.assertEqual(list(Path(self._vault_tmp).glob("*.md")), [])

    def test_concurrent_filename_collision_preserves_external_file(self):
        publish = document_safety._publish_exclusive
        collided = False

        def race(source, target):
            nonlocal collided
            if not collided:
                target.write_text("external note")
                collided = True
            publish(source, target)

        with mock.patch.object(document_safety, "_publish_exclusive", side_effect=race):
            result = self.service_create()
        self.assertEqual(result["path"], "captured note 2.md")
        self.assertEqual(vault_md.read("captured note.md")["content"], "external note")
        self.assertEqual(self.service_create()["path"], result["path"])

    def test_interrupted_link_fallback_does_not_duplicate(self):
        def interrupt(source, target):
            os.link(source, target)
            raise SystemExit("interrupted unlink")

        with mock.patch.object(document_safety, "_publish_exclusive", side_effect=interrupt):
            with self.assertRaises(SystemExit):
                self.service_create()
        response = self.create()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(vault_md.read("captured note.md")["content"], self.body["content"])
        self.assertEqual(len(list(Path(self._vault_tmp).glob("*.md"))), 1)
        self.assertEqual(len(list(Path(self._vault_tmp).glob(".alles-*.create"))), 1)

    def test_changed_vault_root_is_not_a_new_acceptance(self):
        first = self.create().json()
        with tempfile.TemporaryDirectory() as another:
            with mock.patch.object(vault_md, "vault_dir", lambda: Path(another)):
                response = self.create()
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(list(Path(another).iterdir()), [])
        self.assertEqual(vault_md.read(first["path"])["content"], self.body["content"])

    def test_changed_or_missing_staging_cannot_overwrite_owner_content(self):
        write_json = document_safety._write_json

        def interrupt(path, value):
            write_json(path, value)
            raise SystemExit("prepared")

        with mock.patch.object(document_safety, "_write_json", side_effect=interrupt):
            with self.assertRaises(SystemExit):
                self.service_create()
        staging = next(Path(self._vault_tmp).glob(".alles-*.create"))
        staging.write_text("different staging bytes")
        changed = self.create()
        self.assertEqual(changed.status_code, 409, changed.text)
        self.assertEqual(staging.read_text(), "different staging bytes")
        staging.unlink()
        missing = self.create()
        self.assertEqual(missing.status_code, 409, missing.text)
        self.assertEqual(list(Path(self._vault_tmp).glob("*.md")), [])

    def test_ambiguous_link_publication_never_recreates_deleted_or_replaced_notes(self):
        for action in ("delete", "replace"):
            with self.subTest(action=action):
                self.body.update(path=action, request_id=str(uuid.uuid4()))

                def interrupt(source, target):
                    os.link(source, target)
                    raise SystemExit("interrupted unlink")

                with mock.patch.object(
                    document_safety, "_publish_exclusive", side_effect=interrupt
                ):
                    with self.assertRaises(SystemExit):
                        self.service_create()
                target = Path(self._vault_tmp) / f"{action}.md"
                if action == "delete":
                    target.unlink()
                else:
                    edited = target.with_suffix(".tmp")
                    edited.write_text("owner edit")
                    os.replace(edited, target)
                response = self.create()
                self.assertEqual(
                    response.status_code, 410 if action == "delete" else 409, response.text
                )
                self.assertFalse((target.parent / f"{action} 2.md").exists())
                if action == "delete":
                    self.assertFalse(target.exists())
                else:
                    self.assertEqual(target.read_text(), "owner edit")

    def test_missing_staging_never_confirms_an_unrelated_identical_file(self):
        target = Path(self._vault_tmp) / "captured note.md"
        target.write_bytes(self.body["content"].encode())
        write_json = document_safety._write_json

        def interrupt(path, value):
            write_json(path, value)
            raise SystemExit("prepared")

        with mock.patch.object(document_safety, "_write_json", side_effect=interrupt):
            with self.assertRaises(SystemExit):
                self.service_create()
        next(target.parent.glob(".alles-*.create")).unlink()
        response = self.create()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(target.read_bytes(), self.body["content"].encode())
        self.assertEqual(len(list(target.parent.glob("*.md"))), 1)
