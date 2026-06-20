import asyncio
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

# this dev box keeps %TEMP% under a parent git repo, so `git rev-parse` would walk up and
# treat every throwaway dir as a repo. cap the search at the temp root for these tests.
os.environ["GIT_CEILING_DIRECTORIES"] = tempfile.gettempdir()

from services import worktrees


class _Stop:
    def is_set(self):
        return False


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _mkrepo():
    d = tempfile.mkdtemp(prefix="wt-")
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    Path(d, "a.txt").write_text("hello\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-qm", "init")
    return d


class WorktreeServiceTests(unittest.TestCase):
    def test_is_git_repo_true(self):
        self.assertTrue(worktrees.is_git_repo(_mkrepo()))

    def test_is_git_repo_false(self):
        self.assertFalse(worktrees.is_git_repo(tempfile.mkdtemp()))

    def test_setup_creates_worktree(self):
        d = _mkrepo()
        wt = worktrees.setup(d, "run1")
        self.assertTrue(wt and Path(wt).is_dir())
        worktrees.teardown(d, wt)

    def test_setup_has_repo_files(self):
        d = _mkrepo()
        wt = worktrees.setup(d, "run2")
        self.assertTrue((Path(wt) / "a.txt").is_file())
        worktrees.teardown(d, wt)

    def test_setup_non_repo_returns_none(self):
        self.assertIsNone(worktrees.setup(tempfile.mkdtemp(), "x"))

    def test_teardown_removes_worktree(self):
        d = _mkrepo()
        wt = worktrees.setup(d, "run3")
        worktrees.teardown(d, wt)
        self.assertFalse(Path(wt).exists())

    def test_edits_in_worktree_isolated(self):
        d = _mkrepo()
        wt = worktrees.setup(d, "run4")
        (Path(wt) / "a.txt").write_text("CHANGED\n")
        self.assertEqual((Path(d) / "a.txt").read_text(), "hello\n")  # root untouched
        worktrees.teardown(d, wt)


class WorktreeRuntimeTests(unittest.TestCase):
    def _drive(self, settings):
        from services import agent_runtime as ar
        from services import agent_state

        async def fake(messages, base_url, api_key, model, **kw):
            yield {"done": True, "usage": {}}

        ep = SimpleNamespace(base_url="http://x/", api_key="k")
        with tempfile.TemporaryDirectory() as dd:
            with (
                mock.patch.object(agent_state, "DATA_DIR", Path(dd)),
                mock.patch.object(ar, "stream_chat", fake),
                mock.patch.object(ar, "LLM_RETRY_BASE", 0),
            ):

                async def go():
                    rid = None
                    async for ch in ar.run_agent(
                        [{"role": "user", "content": "hi"}],
                        ep,
                        "m",
                        _Stop(),
                        settings,
                        [],
                        [],
                        [],
                        session_id="s",
                    ):
                        if "agent_run" in ch:
                            rid = ch["agent_run"]["id"]
                    return agent_state.get_run(rid)

                return asyncio.run(go())

    def test_runtime_repoints_cwd(self):
        d = _mkrepo()
        run = self._drive({"agent_context_files": False, "agent_worktree": True, "agent_cwd": d})
        self.assertTrue(run.get("worktree"))
        self.assertEqual(run.get("cwd"), run.get("worktree"))

    def test_runtime_teardown_after_run(self):
        d = _mkrepo()
        run = self._drive({"agent_context_files": False, "agent_worktree": True, "agent_cwd": d})
        self.assertFalse(Path(run["worktree"]).exists())  # cleaned up in finally

    def test_runtime_skips_when_not_repo(self):
        d = tempfile.mkdtemp()
        run = self._drive({"agent_context_files": False, "agent_worktree": True, "agent_cwd": d})
        self.assertFalse(run.get("worktree"))

    def test_runtime_skips_when_flag_off(self):
        d = _mkrepo()
        run = self._drive({"agent_context_files": False, "agent_cwd": d})
        self.assertFalse(run.get("worktree"))
