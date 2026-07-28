import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, text

from core.database import ModelEndpoint, Project, Session
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

    def test_aide_terminal_uses_the_selected_project_folder(self):
        folder = self.root / "terminal project"
        folder.mkdir()
        project = self.client.post(
            "/api/projects", json={"name": "terminal", "working_dir": str(folder)}
        ).json()
        session = self.client.post(
            "/api/sessions", json={"name": "terminal", "project_id": project["id"]}
        ).json()

        for context in ({"session_id": session["id"]}, {"project_id": project["id"]}):
            with self.subTest(context=context):
                response = self.client.post("/api/shell/exec", json={"command": "pwd", **context})
                self.assertEqual(response.status_code, 200)
                actual = Path(response.json()["stdout"].strip()).resolve()
                self.assertEqual(actual, folder.resolve())

    def test_aide_agent_uses_the_selected_project_folder(self):
        folder = self.root / "agent project"
        folder.mkdir()
        project = self.client.post(
            "/api/projects", json={"name": "agent", "working_dir": str(folder)}
        ).json()
        db = self.db()
        endpoint = ModelEndpoint(
            name="local",
            base_url="http://127.0.0.1:11434",
            cached_models=json.dumps(["test-model"]),
        )
        db.add(endpoint)
        db.commit()
        db.refresh(endpoint)
        endpoint_id = endpoint.id
        db.close()
        session = self.client.post(
            "/api/sessions",
            json={
                "name": "agent",
                "project_id": project["id"],
                "endpoint_id": endpoint_id,
                "model": "test-model",
            },
        ).json()
        captured = {}

        async def run_agent(
            messages,
            endpoint,
            model,
            stop_event,
            settings,
            accumulated,
            thinking,
            steps,
            session_id="",
        ):
            captured.update(settings)
            accumulated.append("done")
            yield {"delta": "done"}
            yield {"done": True, "usage": {}}

        with (
            mock.patch("routes.chat.load_settings", return_value={}),
            mock.patch("routes.chat.inject_memories", return_value=("", [])),
            mock.patch("routes.chat.run_agent", run_agent),
        ):
            response = self.client.post(
                "/api/chat",
                json={
                    "session_id": session["id"],
                    "message": "check this project",
                    "mode": "agent",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["agent_cwd"], str(folder.resolve()))
        self.assertEqual(captured["agent_environment"], "project")
        self.assertEqual(captured["agent_project_id"], project["id"])

    def test_project_git_branches_can_be_listed_and_switched_safely(self):
        repo = self.root / "branch project"
        repo.mkdir()

        def git(*args):
            return subprocess.run(
                ["git", "-C", str(repo), *args],
                check=True,
                capture_output=True,
                text=True,
            )

        git("init", "-q", "-b", "main")
        git("config", "user.name", "alles test")
        git("config", "user.email", "alles@example.invalid")
        (repo / "README.md").write_text("main\n")
        git("add", "README.md")
        git("commit", "-qm", "initial")
        git("branch", "dev-afterlife")

        project = self.client.post(
            "/api/projects", json={"name": "branches", "working_dir": str(repo)}
        ).json()
        endpoint = f"/api/projects/{project['id']}/git/branches"

        listed = self.client.get(endpoint)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["current"], "main")
        self.assertEqual(listed.json()["branches"], ["main", "dev-afterlife"])

        switched = self.client.post(endpoint, json={"branch": "dev-afterlife"})
        self.assertEqual(switched.status_code, 200)
        self.assertEqual(switched.json()["current"], "dev-afterlife")
        self.assertEqual(git("branch", "--show-current").stdout.strip(), "dev-afterlife")

        (repo / "dirty.txt").write_text("keep me\n")
        carried = self.client.post(endpoint, json={"branch": "main"})
        self.assertEqual(carried.status_code, 200)
        self.assertEqual(carried.json()["current"], "main")
        self.assertTrue(carried.json()["dirty"])
        self.assertEqual((repo / "dirty.txt").read_text(), "keep me\n")

        git("switch", "dev-afterlife")
        (repo / "README.md").write_text("dev\n")
        git("add", "README.md")
        git("commit", "-qm", "change on dev")
        git("switch", "main")
        (repo / "README.md").write_text("local work\n")
        refused = self.client.post(endpoint, json={"branch": "dev-afterlife"})
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["code"], "project_git_switch_failed")
        self.assertEqual(git("branch", "--show-current").stdout.strip(), "main")
        self.assertEqual((repo / "README.md").read_text(), "local work\n")

    def test_non_git_project_has_no_branch_context(self):
        project = self.client.post(
            "/api/projects", json={"name": "plain", "working_dir": str(self.root)}
        ).json()
        response = self.client.get(f"/api/projects/{project['id']}/git/branches")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"repository": False, "current": "", "branches": [], "dirty": False},
        )

    def test_git_timeout_returns_a_controlled_non_repository_state(self):
        timeout = subprocess.TimeoutExpired(["git"], 15)
        with mock.patch("services.project_git.subprocess.run", side_effect=timeout):
            project = self.client.post(
                "/api/projects", json={"name": "slow", "working_dir": str(self.root)}
            ).json()
            response = self.client.get(f"/api/projects/{project['id']}/git/branches")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["repository"])

    def test_git_helper_decodes_unusual_ref_bytes_and_terminates_switch_options(self):
        from services import project_git

        completed = subprocess.CompletedProcess(["git"], 0, stdout="main\ufffd\n", stderr="")
        with mock.patch("services.project_git.subprocess.run", return_value=completed) as run:
            result = project_git._git(str(self.root), "branch", "--show-current")
        self.assertEqual(result.stdout, "main\ufffd\n")
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

        state = {
            "repository": True,
            "current": "main",
            "branches": ["main", "--option-shaped"],
            "dirty": False,
        }
        switched = {**state, "current": "--option-shaped"}
        with (
            mock.patch("services.project_git.branch_state", side_effect=[state, switched]),
            mock.patch(
                "services.project_git._git",
                return_value=subprocess.CompletedProcess(["git"], 0, stdout="", stderr=""),
            ) as git,
        ):
            self.assertEqual(
                project_git.switch_branch(str(self.root), "--option-shaped")["current"],
                "--option-shaped",
            )
        git.assert_called_once_with(
            str(self.root),
            "switch",
            "--no-guess",
            "--",
            "--option-shaped",
            timeout=120,
        )

    def test_branch_switch_timeout_reconciles_a_completed_checkout(self):
        from services import project_git

        state = {
            "repository": True,
            "current": "main",
            "branches": ["main", "next"],
            "dirty": False,
        }
        switched = {**state, "current": "next"}
        timed_out = subprocess.CompletedProcess(["git"], 124, stdout="", stderr="timed out")
        with (
            mock.patch("services.project_git.branch_state", side_effect=[state, switched]),
            mock.patch("services.project_git._git", return_value=timed_out) as git,
        ):
            self.assertEqual(project_git.switch_branch(str(self.root), "next"), switched)
        git.assert_called_once_with(
            str(self.root), "switch", "--no-guess", "--", "next", timeout=120
        )

    def test_task_session_remembers_a_temporary_folder_without_a_project(self):
        folder = self.root / "temporary work"
        folder.mkdir()
        created = self.client.post(
            "/api/sessions",
            json={"name": "task folder", "working_dir": str(folder)},
        )
        self.assertEqual(created.status_code, 200)
        session = created.json()
        self.assertIsNone(session["project_id"])
        self.assertEqual(session["environment"]["kind"], "legacy_folder")
        self.assertEqual(session["environment"]["cwd"], str(folder.resolve()))

        history = self.client.get(f"/api/sessions/{session['id']}/history").json()
        self.assertEqual(history["session"]["environment"]["cwd"], str(folder.resolve()))

    def test_task_session_git_branch_can_be_selected_safely(self):
        repo = self.root / "task repo"
        repo.mkdir()

        def git(*args, check=True):
            return subprocess.run(
                ["git", "-C", str(repo), *args],
                check=check,
                capture_output=True,
                text=True,
            )

        git("init", "-q", "-b", "main")
        git("config", "user.name", "alles test")
        git("config", "user.email", "alles@example.invalid")
        (repo / "README.md").write_text("main\n")
        git("add", "README.md")
        git("commit", "-qm", "initial")
        git("branch", "dev-afterlife")
        session = self.client.post(
            "/api/sessions", json={"name": "task repo", "working_dir": str(repo)}
        ).json()
        endpoint = f"/api/sessions/{session['id']}/git/branches"

        listed = self.client.get(endpoint)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["current"], "main")
        switched = self.client.post(endpoint, json={"branch": "dev-afterlife"})
        self.assertEqual(switched.status_code, 200)
        self.assertEqual(git("branch", "--show-current").stdout.strip(), "dev-afterlife")

        git("switch", "main")
        git("switch", "dev-afterlife")
        (repo / "README.md").write_text("dev\n")
        git("add", "README.md")
        git("commit", "-qm", "change on dev")
        git("switch", "main")
        (repo / "README.md").write_text("dirty\n")
        refused = self.client.post(endpoint, json={"branch": "dev-afterlife"})
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["code"], "session_git_switch_failed")
        self.assertEqual((repo / "README.md").read_text(), "dirty\n")

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
