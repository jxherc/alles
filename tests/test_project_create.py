"""aide's project_create tool: a folder anywhere in the owner's home or on a drive becomes a
Project, and a General chat moves into it so the next write in the same turn lands there."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import services.agent_tools as at
from core.database import Project, Session
from services import agent_runtime as ar
from services import agent_state
from tests._client import ApiTest


class ProjectCreateTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.home = root / "home"
        self.drive = root / "drive"
        self.home.mkdir()
        self.drive.mkdir()
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        # a mounted drive is any folder under the fake drive folder
        mount = mock.patch.object(at, "_DRIVE_FOLDERS", (str(self.drive) + "/",))
        mount.start()
        self.addCleanup(mount.stop)
        self.addCleanup(at.set_agent_ctx, {})

    def chat(self, **fields):
        with self.db() as session:
            row = Session(name="chat", **fields)
            session.add(row)
            session.commit()
            return row.id

    def run_tool(self, args, *, session_id="", settings=None):
        settings = settings if settings is not None else {"agent_environment": "general"}
        at.set_agent_ctx(settings, session_id=session_id)
        return asyncio.run(at.execute("project_create", args)), settings

    def project_rows(self):
        with self.db() as session:
            return session.query(Project).all()

    def test_home_path_makes_the_folder_and_the_project(self):
        target = self.home / "work" / "test1"
        sid = self.chat()
        out, settings = self.run_tool({"path": "~/work/test1"}, session_id=sid)
        self.assertFalse(out.get("error"), out)
        self.assertTrue(target.is_dir())
        (project,) = self.project_rows()
        self.assertEqual((project.name, project.working_dir), ("test1", str(target)))
        self.assertEqual(
            out["output"], f"made project test1 at {target}. this chat now works in it."
        )
        self.assertEqual(settings["agent_environment"], "project")

    def test_drive_path_and_custom_name(self):
        target = self.drive / "Alles" / "test1"
        out, _ = self.run_tool({"path": str(target), "name": "trial"})
        self.assertFalse(out.get("error"), out)
        self.assertTrue(target.is_dir())
        self.assertEqual([p.name for p in self.project_rows()], ["trial"])

    def test_refuses_root_and_system_folders(self):
        for path in ("/", "/etc", "/usr/local/x"):
            out, _ = self.run_tool({"path": path})
            self.assertTrue(out["error"], path)
        self.assertEqual(self.project_rows(), [])

    def test_refuses_the_home_folder_itself_and_outside_paths(self):
        for path in (str(self.home), str(self.home.parent / "elsewhere")):
            out, _ = self.run_tool({"path": path})
            self.assertTrue(out["error"], out)
        self.assertFalse((self.home.parent / "elsewhere").exists())

    def test_refuses_secret_paths(self):
        for path in (self.home / ".ssh" / "proj", self.home / "keys" / "server.pem"):
            out, _ = self.run_tool({"path": str(path)})
            self.assertIn("secret", out["output"])
            self.assertTrue(out["error"])
            self.assertFalse(path.exists())

    def test_relative_and_file_paths_are_errors(self):
        out, _ = self.run_tool({"path": "projects/x"})
        self.assertTrue(out["error"])
        afile = self.home / "note.txt"
        afile.write_text("hi")
        out, _ = self.run_tool({"path": str(afile)})
        self.assertIn("is a file", out["output"])
        self.assertTrue(out["error"])

    def test_existing_folder_becomes_the_project_untouched(self):
        target = self.home / "old"
        target.mkdir()
        (target / "keep.txt").write_text("mine")
        out, _ = self.run_tool({"path": str(target)})
        self.assertFalse(out.get("error"), out)
        self.assertEqual((target / "keep.txt").read_text(), "mine")
        self.assertEqual(len(self.project_rows()), 1)

    def test_existing_project_is_reused(self):
        target = self.home / "again"
        first, _ = self.run_tool({"path": str(target)})
        second, _ = self.run_tool({"path": str(target), "name": "other"})
        self.assertFalse(second.get("error"), second)
        self.assertIn("was already the project again", second["output"])
        self.assertEqual(len(self.project_rows()), 1)
        self.assertFalse(first.get("error"))

    def test_general_chat_moves_and_the_next_write_lands_in_the_folder(self):
        target = self.home / "moved"
        sid = self.chat()
        settings = {"agent_environment": "general", "agent_cwd": ""}
        before = asyncio.run(self._write(settings, sid, target / "a.txt"))
        self.assertTrue(before["error"])  # General has no writable folder
        out, settings = self.run_tool({"path": str(target)}, session_id=sid, settings=settings)
        self.assertFalse(out.get("error"), out)
        with self.db() as session:
            row = session.get(Session, sid)
            self.assertEqual(row.project_id, self.project_rows()[0].id)
        self.assertEqual(settings["agent_cwd"], str(target))
        self.assertEqual(settings["agent_project_id"], self.project_rows()[0].id)
        after = asyncio.run(self._write(settings, sid, target / "a.txt"))
        self.assertFalse(after["error"], after)
        self.assertEqual((target / "a.txt").read_text(), "hello")

    async def _write(self, settings, sid, path):
        at.set_agent_ctx(settings, session_id=sid)
        return await at.execute("write_file", {"path": str(path), "content": "hello"})

    def test_project_chat_stays_where_it_is(self):
        with self.db() as session:
            mine = Project(name="mine", working_dir=str(self.home / "mine"))
            session.add(mine)
            session.commit()
            mine_id = mine.id
        sid = self.chat(project_id=mine_id)
        settings = {"agent_environment": "project", "agent_cwd": str(self.home / "mine")}
        out, settings = self.run_tool(
            {"path": str(self.home / "new")}, session_id=sid, settings=settings
        )
        self.assertFalse(out.get("error"), out)
        self.assertIn("stays in its own project", out["output"])
        with self.db() as session:
            self.assertEqual(session.get(Session, sid).project_id, mine_id)
        self.assertEqual(settings["agent_cwd"], str(self.home / "mine"))
        self.assertEqual(len(self.project_rows()), 2)

    def test_incognito_chat_is_not_moved(self):
        sid = self.chat(incognito=True)
        out, settings = self.run_tool(
            {"path": str(self.home / "quiet")},
            session_id=sid,
            settings={"agent_environment": "general", "incognito": True},
        )
        self.assertFalse(out.get("error"), out)
        self.assertIn("isn't saved", out["output"])
        with self.db() as session:
            self.assertIsNone(session.get(Session, sid).project_id)
        self.assertEqual(settings["agent_environment"], "general")

    def test_it_follows_the_permission_mode_like_a_write(self):
        self.assertEqual(at.TOOL_PERMISSION["project_create"], "write")
        self.assertIn("project_create", at.MUTATING_TOOLS)
        plan = {
            d["function"]["name"] for d in at.build_tool_defs({"agent_permission_mode": "plan"})
        }
        self.assertNotIn("project_create", plan)

    def test_a_whole_turn_makes_the_project_then_writes_in_it(self):
        """the runtime's approval scope follows the chat into the project, or the write is refused"""
        target = self.home / "turn"
        sid = self.chat()
        steps = [
            [
                {
                    "tool_call": {
                        "call_id": "c1",
                        "name": "project_create",
                        "args": {"path": str(target)},
                    }
                },
                {"done": True},
            ],
            [
                {
                    "tool_call": {
                        "call_id": "c2",
                        "name": "write_file",
                        "args": {"path": str(target / "a.txt"), "content": "hi"},
                    }
                },
                {"done": True},
            ],
            [{"delta": "ok"}, {"done": True}],
        ]
        calls = {"n": 0}

        async def fake(messages, base_url, api_key, model, **kw):
            n = calls["n"]
            calls["n"] += 1
            for chunk in steps[min(n, len(steps) - 1)]:
                yield chunk

        class Stop:
            def is_set(self):
                return False

        async def go():
            chunks = []
            settings = {"agent_context_files": False, "agent_environment": "general"}
            async for chunk in ar.run_agent(
                [{"role": "user", "content": "go"}],
                SimpleNamespace(base_url="http://x/", api_key="k"),
                "m",
                Stop(),
                settings,
                [],
                [],
                [],
                session_id=sid,
            ):
                chunks.append(chunk)
            return chunks

        with (
            tempfile.TemporaryDirectory() as runs,
            mock.patch.object(agent_state, "DATA_DIR", Path(runs)),
            mock.patch.object(ar, "stream_chat", fake),
            mock.patch.object(ar, "LLM_RETRY_BASE", 0),
        ):
            chunks = asyncio.run(go())
        outputs = [c["tool_result"] for c in chunks if "tool_result" in c]
        self.assertEqual([o.get("error") for o in outputs], [False, False], outputs)
        self.assertEqual((target / "a.txt").read_text(), "hi")


if __name__ == "__main__":
    unittest.main()
