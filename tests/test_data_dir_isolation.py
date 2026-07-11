import os
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

import routes.backup as backup
import routes.compare as compare
import routes.gallery as gallery
import routes.uploads as uploads
import services.agent_state as agent_state
import services.agent_tools as agent_tools
import services.cal_notify as cal_notify
import services.caldav_sync as caldav_sync
import services.local_models as local_models
import services.photo_sync as photo_sync
import services.secretstore as secretstore
import services.skills_store as skills_store
import services.webpush as webpush
from core.database import Session, Upload
from routes import personas
from services.recovery_crypto import decrypt_recovery_container, load_recovery_key
from services.research import handler as research_handler
from tests._client import ApiTest


class DataDirIsolationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "alles-data"
        self.root.mkdir()
        self.old_env = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = str(self.root)

        self.orig = {
            "backup": backup.DATA_DIR,
            "uploads": uploads.UPLOAD_DIR,
            "gallery": gallery.GALLERY_DIR,
            "compare": compare._COMPARE_DIR,
            "caldav_cfg": caldav_sync.CFG_PATH,
            "persona_seed": personas._SEED_SENTINEL,
            "skills": skills_store.SKILLS_DIR,
            "secret_key": secretstore._KEY_FILE,
            "secret_cache": secretstore._key,
            "secret_path": secretstore._key_path,
            "vapid_key": webpush._KEY_FILE,
            "vapid_cache": webpush._vapid_key,
            "vapid_path": webpush._vapid_path,
            "fires": cal_notify._FIRES,
            "fired": cal_notify._fired,
            "fired_path": cal_notify._fired_path,
            "photo_state": photo_sync._STATE,
            "agent_runs": agent_state.DATA_DIR,
            "research": research_handler.DATA_DIR,
            "local_models": local_models.DATA_DIR,
        }
        backup.DATA_DIR = None
        uploads.UPLOAD_DIR = None
        gallery.GALLERY_DIR = None
        compare._COMPARE_DIR = None
        caldav_sync.CFG_PATH = None
        personas._SEED_SENTINEL = None
        skills_store.SKILLS_DIR = None
        secretstore._KEY_FILE = None
        secretstore._key = None
        secretstore._key_path = None
        webpush._KEY_FILE = None
        webpush._vapid_key = None
        webpush._vapid_path = None
        cal_notify._FIRES = None
        cal_notify._fired = None
        cal_notify._fired_path = None
        photo_sync._STATE = None
        agent_state.DATA_DIR = None
        research_handler.DATA_DIR = None
        local_models.DATA_DIR = None

    def tearDown(self):
        backup.DATA_DIR = self.orig["backup"]
        uploads.UPLOAD_DIR = self.orig["uploads"]
        gallery.GALLERY_DIR = self.orig["gallery"]
        compare._COMPARE_DIR = self.orig["compare"]
        caldav_sync.CFG_PATH = self.orig["caldav_cfg"]
        personas._SEED_SENTINEL = self.orig["persona_seed"]
        skills_store.SKILLS_DIR = self.orig["skills"]
        secretstore._KEY_FILE = self.orig["secret_key"]
        secretstore._key = self.orig["secret_cache"]
        secretstore._key_path = self.orig["secret_path"]
        webpush._KEY_FILE = self.orig["vapid_key"]
        webpush._vapid_key = self.orig["vapid_cache"]
        webpush._vapid_path = self.orig["vapid_path"]
        cal_notify._FIRES = self.orig["fires"]
        cal_notify._fired = self.orig["fired"]
        cal_notify._fired_path = self.orig["fired_path"]
        photo_sync._STATE = self.orig["photo_state"]
        agent_state.DATA_DIR = self.orig["agent_runs"]
        research_handler.DATA_DIR = self.orig["research"]
        local_models.DATA_DIR = self.orig["local_models"]
        if self.old_env is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self.old_env
        self.tmp.cleanup()

    def test_file_roots_follow_alles_data(self):
        self.assertEqual(backup._data_dir(), self.root)
        self.assertEqual(uploads.upload_dir(), self.root / "uploads")
        self.assertEqual(gallery.gallery_dir(), self.root / "gallery")
        self.assertEqual(compare.compare_dir(), self.root / "compare")
        self.assertEqual(caldav_sync._cfg_path(), self.root / "caldav.json")
        self.assertEqual(personas.seed_sentinel(), self.root / ".personas_seeded")
        self.assertEqual(skills_store.skills_dir(), self.root / "skills")
        self.assertEqual(secretstore._key_file(), self.root / "secret.key")
        self.assertEqual(webpush._key_file(), self.root / "vapid.pem")
        self.assertEqual(cal_notify._fires_file(), self.root / "cal_fires.json")
        self.assertEqual(photo_sync._state_file(), self.root / "photo_sync_state.json")
        self.assertEqual(agent_state.run_dir(), self.root / "agent_runs")
        self.assertEqual(research_handler.task_dir(), self.root / "research")
        self.assertEqual(local_models._data_dir(), self.root)
        self.assertEqual(agent_tools._shots_dir(), self.root / "agent_shots")

    def test_secret_and_push_keys_are_written_under_alles_data(self):
        secretstore.seal("token")
        webpush.public_key_b64u()
        self.assertTrue((self.root / "secret.key").exists())
        self.assertTrue((self.root / "vapid.pem").exists())

    def test_caldav_and_skills_write_under_alles_data(self):
        caldav_sync.save_cfg({"url": "https://cal.example", "username": "me", "password": "pw"})
        skills_store.upsert_skill("Temp Skill", "desc", "", "steps")
        self.assertTrue((self.root / "caldav.json").exists())
        self.assertTrue((self.root / "skills" / "temp-skill" / "SKILL.md").exists())


class DataDirIsolationApiTest(ApiTest):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "api-data"
        self.root.mkdir()
        self.old_env = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = str(self.root)
        self.orig_backup = backup.DATA_DIR
        self.orig_uploads = uploads.UPLOAD_DIR
        self.orig_gallery = gallery.GALLERY_DIR
        self.orig_compare = compare._COMPARE_DIR
        backup.DATA_DIR = None
        uploads.UPLOAD_DIR = None
        gallery.GALLERY_DIR = None
        compare._COMPARE_DIR = None
        super().setUp()

    def tearDown(self):
        super().tearDown()
        backup.DATA_DIR = self.orig_backup
        uploads.UPLOAD_DIR = self.orig_uploads
        gallery.GALLERY_DIR = self.orig_gallery
        compare._COMPARE_DIR = self.orig_compare
        if self.old_env is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self.old_env
        self.tmp.cleanup()

    def test_backup_export_uses_alles_data(self):
        with closing(sqlite3.connect(self.root / "aide.db")) as conn:
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT)")
            conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
            conn.execute(
                "CREATE TABLE schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
            )
            conn.execute("INSERT INTO schema_migrations VALUES (1, 'baseline', '')")
            conn.execute("CREATE TABLE isolated_backup (value TEXT)")
            conn.commit()
        (self.root / "settings.json").write_text('{"marker":"isolated"}')
        r = self.client.get("/api/backup")
        self.assertEqual(r.status_code, 200)
        encrypted = Path(self.tmp.name) / "isolated.alles-backup"
        plaintext = Path(self.tmp.name) / "isolated.zip"
        encrypted.write_bytes(r.content)
        decrypt_recovery_container(
            encrypted, plaintext, load_recovery_key(self.root / "recovery.key")
        )
        with zipfile.ZipFile(plaintext) as zf:
            self.assertEqual(zf.read("payload/data/settings.json"), b'{"marker":"isolated"}')

    def test_upload_and_gallery_write_under_alles_data(self):
        r = self.client.post("/api/uploads", files={"file": ("a.txt", b"a", "text/plain")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(list((self.root / "uploads").iterdir())), 1)

        g = self.client.post(
            "/api/gallery/upload",
            files={"file": ("pic.png", b"\x89PNG\r\n\x1a\n", "image/png")},
            data={"prompt": "", "tags": ""},
        )
        self.assertEqual(g.status_code, 200)
        self.assertEqual(len([p for p in (self.root / "gallery").iterdir() if p.is_file()]), 1)

    def test_chat_attachment_reads_from_alles_data_uploads(self):
        from routes.chat import _build_messages

        db = self.db()
        try:
            sess = Session(name="s")
            rec = Upload(
                filename="note.txt", original_name="note.txt", mime_type="text/plain", size=4
            )
            db.add_all([sess, rec])
            db.commit()
            (self.root / "uploads").mkdir()
            (self.root / "uploads" / "note.txt").write_text("from isolated upload", "utf-8")

            msgs = _build_messages(
                sess,
                "read this",
                {
                    "memory_auto_inject": False,
                    "session_context_inject": False,
                    "artifacts_enabled": False,
                },
                db=db,
                file_ids=[rec.id],
            )
            self.assertIn("from isolated upload", msgs[-1]["content"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
