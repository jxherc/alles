"""audit fix: renaming a FOLDER must carry every child doc's revision history (and not pollute
the search index with a bogus '<folder>.md' entry)."""

import tempfile
from pathlib import Path
from unittest import mock

import services.vault_md as vm
from core.database import DocRevision
from tests._client import ApiTest


class VaultMdFolderRenameTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(vm, "vault_dir", lambda: Path(self.tmp.name))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_folder_rename_carries_child_revisions(self):
        vm.write("folder1/note.md", "hello world")
        db = self.db()
        db.add(DocRevision(path="folder1/note.md", content="v1"))
        db.commit()
        db.close()

        r = self.client.post(
            "/api/vault-md/rename", json={"path": "folder1", "new_path": "folder2"}
        )
        self.assertEqual(r.status_code, 200)

        db = self.db()
        self.assertEqual(db.query(DocRevision).filter_by(path="folder1/note.md").count(), 0)
        self.assertEqual(db.query(DocRevision).filter_by(path="folder2/note.md").count(), 1)
        db.close()
