import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, text

from core.database import Project, Session
from core.migrations import m0025_project_environments
from routes.chat import _resolve_mentions, _resolve_working_dir
from services import agent_tools
from services.agent_runtime import _load_project_context
from services.project_environment import canonical_folder, folder_state, session_environment
from tests._client import ApiTest


class ProjectEnvironmentApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self.folder = tempfile.TemporaryDirectory(prefix="alles-project-")
        self.root = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()
        super().tearDown()

    def test_general_is_an_explicit_no_folder_environment(self):
        response = self.client.get("/api/projects/general")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "id": "general",
                "name": "General",
                "kind": "general",
                "working_dir": "",
                "folder_state": "none",
                "relink_required": False,
            },
        )
        session = self.client.post("/api/sessions", json={"name": "standalone"}).json()
        self.assertEqual(session["environment"]["kind"], "general")
        self.assertEqual(session["environment"]["cwd"], "")
        self.assertEqual(
            self.client.get(f"/api/agent/files?session_id={session['id']}").json(),
            {"files": []},
        )

    def test_project_uses_canonical_existing_server_folder(self):
        nested = self.root / "folder"
        nested.mkdir()
        response = self.client.post(
            "/api/projects",
            json={"working_dir": str(nested / ".." / "folder"), "scratchpad": "keep me"},
        )
        self.assertEqual(response.status_code, 200)
        project = response.json()
        self.assertEqual(project["name"], "folder")
        self.assertEqual(project["working_dir"], str(nested.resolve()))
        self.assertEqual(project["folder_state"], "available")
        self.assertFalse(project["relink_required"])
        self.assertEqual(project["scratchpad"], "keep me")

    def test_empty_legacy_project_requires_relink(self):
        project = self.client.post("/api/projects", json={"name": "old"}).json()
        self.assertEqual(project["folder_state"], "relink_required")
        self.assertTrue(project["relink_required"])
        files = self.client.get(f"/api/projects/{project['id']}/files").json()
        self.assertEqual(
            files,
            {"files": [], "working_dir": "", "folder_state": "relink_required"},
        )
        opened = self.client.post(f"/api/projects/{project['id']}/open").json()
        self.assertIsNotNone(opened["last_opened_at"])

    def test_disappeared_folder_keeps_project_and_threads(self):
        folder = self.root / "movable"
        folder.mkdir()
        project = self.client.post(
            "/api/projects", json={"name": "move", "working_dir": str(folder)}
        ).json()
        session = self.client.post(
            "/api/sessions", json={"name": "kept", "project_id": project["id"]}
        ).json()
        folder.rmdir()

        missing = self.client.get(f"/api/projects/{project['id']}").json()
        self.assertEqual(missing["folder_state"], "missing")
        self.assertEqual(missing["session_count"], 1)
        history = self.client.get(f"/api/sessions/{session['id']}/history").json()
        self.assertEqual(history["session"]["environment"]["folder_state"], "missing")

        replacement = self.root / "replacement"
        replacement.mkdir()
        relinked = self.client.post(
            f"/api/projects/{project['id']}/relink",
            json={"working_dir": str(replacement)},
        ).json()
        self.assertEqual(relinked["folder_state"], "available")
        self.assertEqual(relinked["working_dir"], str(replacement.resolve()))
        self.assertEqual(relinked["session_count"], 1)

    def test_folder_input_rejects_relative_missing_and_filesystem_root(self):
        cases = [
            ("relative/path", "project_folder_must_be_absolute"),
            (str(self.root / "missing"), "project_folder_unavailable"),
            (Path(self.root.anchor).as_posix(), "project_folder_is_filesystem_root"),
        ]
        for value, code in cases:
            with self.subTest(value=value):
                response = self.client.post(
                    "/api/projects", json={"name": "bad", "working_dir": value}
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], code)

    def test_project_folder_wins_over_hidden_legacy_session_folder(self):
        project_root = self.root / "project"
        legacy_root = self.root / "legacy"
        project_root.mkdir()
        legacy_root.mkdir()
        db = self.db()
        project = Project(name="p", working_dir=str(project_root))
        db.add(project)
        db.flush()
        session = Session(name="s", project_id=project.id, working_dir=str(legacy_root))
        db.add(session)
        db.commit()
        db.refresh(session)
        self.assertEqual(_resolve_working_dir(session), str(project_root.resolve()))
        self.assertEqual(session_environment(session)["kind"], "project")
        db.close()

    def test_unlinked_legacy_session_folder_is_preserved_and_labeled(self):
        session = self.client.post(
            "/api/sessions", json={"name": "legacy", "working_dir": str(self.root)}
        ).json()
        self.assertEqual(session["environment"]["kind"], "legacy_folder")
        self.assertEqual(session["environment"]["cwd"], str(self.root.resolve()))

    def test_new_session_rejects_a_missing_project(self):
        response = self.client.post(
            "/api/sessions", json={"name": "dangling", "project_id": "missing"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "project not found")

    def test_relink_requires_a_recent_owner_session_when_login_is_enabled(self):
        from core import auth

        project = self.client.post("/api/projects", json={"name": "locked"}).json()
        token = auth.create_session_token()
        auth.store_token(token)
        auth._recent_auth[token] = 0
        self.client.cookies.set("aide_session", token)
        try:
            with (
                mock.patch("app.auth_enabled", return_value=True),
                mock.patch("core.settings.auth_enabled", return_value=True),
            ):
                response = self.client.post(
                    f"/api/projects/{project['id']}/relink",
                    json={"working_dir": str(self.root)},
                )
        finally:
            self.client.cookies.clear()
            auth.revoke_token(token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "recent_auth_required")


class GeneralToolBoundaryTest(unittest.TestCase):
    def test_general_relative_paths_do_not_fall_back_to_source_tree(self):
        settings = {"agent_environment": "general", "agent_cwd": ""}
        with mock.patch.object(agent_tools, "_settings", lambda: settings):
            with self.assertRaisesRegex(ValueError, "select a Project"):
                agent_tools._resolve("anything.txt")
            self.assertEqual(agent_tools.workspace_files(), [])

    def test_general_has_no_implicit_write_root(self):
        settings = {"agent_environment": "general", "agent_cwd": ""}
        error = agent_tools._guard_path("/tmp/output.txt", write=True, settings=settings)
        self.assertIn("General has no writable folder", error)

    def test_general_does_not_load_repo_context_or_mentions(self):
        self.assertEqual(_load_project_context(""), "")
        self.assertEqual(_resolve_mentions("read @AGENTS.md", ""), "read @AGENTS.md")


class ProjectEnvironmentHelperTest(unittest.TestCase):
    def test_folder_state_does_not_guess_relative_paths(self):
        self.assertEqual(folder_state("relative"), "relink_required")

    def test_canonical_folder_rejects_root(self):
        with self.assertRaisesRegex(ValueError, "filesystem_root"):
            canonical_folder(Path(os.sep).as_posix(), must_exist=True)


class ProjectEnvironmentMigrationTest(unittest.TestCase):
    def test_migration_preserves_tasks_and_maps_done_state_idempotently(self):
        with tempfile.TemporaryDirectory(prefix="alles-project-migration-") as temp:
            engine = create_engine(f"sqlite:///{Path(temp) / 'old.db'}")
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE projects ("
                        "id TEXT PRIMARY KEY, name TEXT, working_dir TEXT, description TEXT)"
                    )
                )
                conn.execute(
                    text("INSERT INTO projects VALUES ('p','old','/missing','legacy notes')")
                )
                conn.execute(
                    text("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, done BOOLEAN)")
                )
                conn.execute(text("INSERT INTO tasks VALUES ('a','active',0),('d','finished',1)"))
                m0025_project_environments.up(conn)
                m0025_project_environments.up(conn)
                columns = {row[1] for row in conn.execute(text("PRAGMA table_info(projects)"))}
                rows = dict(conn.execute(text("SELECT id,stage FROM tasks ORDER BY id")).all())
                scratchpad = conn.execute(
                    text("SELECT scratchpad FROM projects WHERE id='p'")
                ).scalar_one()
            engine.dispose()
        self.assertTrue({"scratchpad", "last_opened_at"}.issubset(columns))
        self.assertEqual(rows, {"a": "backlog", "d": "done"})
        self.assertEqual(scratchpad, "legacy notes")
