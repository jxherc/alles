"""Confirmed Aide sources, using only synthetic run state and local tool doubles."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from services import agent_runtime as runtime
from services import agent_state as state


class SourceOutcomesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-source-outcome-")
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(state, "DATA_DIR", Path(self.tmp.name))
        patch.start()
        self.addCleanup(patch.stop)
        self.run = state.start_run("synthetic", "synthetic", 4)
        self.rid = self.run["id"]
        self.addCleanup(state._active.pop, self.rid, None)
        self.steps = []

    def completed(self, name, args, output="synthetic result", error=False, **extra):
        step = dict(call_id=f"call-{len(self.steps)}", name=name, args=args, output="", error=False)
        state.record_event(self.rid, "tool_start", step)
        step.update(output=output, error=error, **extra)
        self.steps.append(step)
        state.record_event(self.rid, "tool_result", step, tool_steps=self.steps)
        return step

    def reload(self):
        state.finish_run(self.rid, "done")
        state._active.pop(self.rid, None)
        return state.run_sources(self.rid)

    def test_document_read_keeps_actual_path_and_version(self):
        self.completed(
            "note_read",
            {"name": "one"},
            json.dumps(
                {"path": "Notes/one.md", "hash": "a" * 64, "content": "Synthetic local source."}
            ),
        )
        sources = self.reload()
        self.assertEqual(sources["files"], ["Notes/one.md"])
        self.assertIn(
            {"kind": "document", "tool": "note_read", "path": "Notes/one.md", "hash": "a" * 64},
            sources["sources"],
        )

    def test_failed_and_unfinished_calls_are_not_sources(self):
        self.completed("read_file", {"path": "missing.txt"}, "not found", error=True)
        state.record_event(
            self.rid,
            "tool_start",
            {"call_id": "unfinished", "name": "read_file", "args": {"path": "not-read.txt"}},
        )
        sources = self.reload()
        self.assertEqual(sources["files"], [])
        self.assertEqual(
            sources["outcomes"], {"succeeded": 0, "failed": 1, "unfinished": 1, "unknown": 0}
        )

    def test_completed_and_unfinished_calls_survive_event_rotation(self):
        self.completed("read_file", {"path": "actual.txt"})
        state.record_event(
            self.rid,
            "tool_start",
            {"call_id": "unfinished", "name": "read_file", "args": {"path": "not-read.txt"}},
        )
        for number in range(305):
            state.record_event(self.rid, "status", {"number": number})
        sources = self.reload()
        self.assertEqual(sources["files"], ["actual.txt"])
        self.assertEqual(sources["outcomes"]["unfinished"], 1)

    def test_tool_start_snapshot_does_not_change_when_result_arrives(self):
        self.completed("read_file", {"path": "actual.txt"})
        start = state.get_run(self.rid)["events"][0]["data"]
        self.assertEqual(start["output"], "")

    def test_writes_and_commands_are_separate_from_reads(self):
        self.completed("read_file", {"path": "source.txt"})
        self.completed("write_file", {"path": "answer.txt"})
        self.completed("shell", {"command": "synthetic command"})
        sources = self.reload()
        self.assertEqual([s["tool"] for s in sources["sources"]], ["read_file"])
        self.assertEqual([a["tool"] for a in sources["actions"]], ["write_file", "shell"])
        self.assertEqual(sources["files"], ["answer.txt", "source.txt"])
        self.assertEqual(sources["commands"], ["synthetic command"])
        self.assertEqual(sources["outcomes"]["succeeded"], 3)

    def test_metadata_keeps_search_results_separate_from_full_reads(self):
        source = {
            "kind": "search",
            "query": "owned",
            "results": [{"kind": "document", "path": "Notes/match.md", "label": "match"}],
        }
        self.completed("docs_search", {"query": "owned"}, source=source)
        sources = self.reload()
        self.assertEqual(sources["files"], [])
        self.assertEqual(sources["sources"], [{**source, "tool": "docs_search"}])

    def test_legacy_success_needs_a_result_event_not_just_output(self):
        self.run.pop("source_tracking")
        step = {
            "call_id": "old",
            "name": "read_file",
            "args": {"path": "old.txt"},
            "output": "might be partial",
            "error": False,
        }
        state.update_run(self.rid, tool_steps=[step])
        sources = self.reload()
        self.assertEqual(sources["files"], [])
        self.assertEqual(sources["outcomes"]["unknown"], 1)
        self.assertFalse(sources["history_complete"])
        run = state.get_run(self.rid)
        run["events"] = [{"type": "tool_result", "data": step}]
        state.update_run(self.rid, **run)
        sources = self.reload()
        self.assertEqual(sources["files"], ["old.txt"])
        self.assertEqual(sources["outcomes"]["succeeded"], 1)
        self.assertFalse(sources["history_complete"])

    def test_old_stopped_stream_is_not_a_confirmed_read(self):
        self.run.pop("source_tracking")
        step = {
            "call_id": "old",
            "name": "read_file",
            "args": {"path": "partial.txt"},
            "output": "partial",
            "error": False,
        }
        state.update_run(
            self.rid, tool_steps=[step], events=[{"type": "tool_result", "data": step}]
        )
        state.finish_run(self.rid, "stopped")
        sources = state.run_sources(self.rid)
        self.assertEqual(sources["files"], [])
        self.assertEqual(sources["outcomes"]["unknown"], 1)

    def test_private_sources_stay_in_memory_and_expire_with_session(self):
        from services import incognito

        private_session = incognito.create_session()
        self.addCleanup(incognito.delete_session, private_session.id)
        run = state.start_run(private_session.id, "synthetic", 4, incognito=True)
        files_before = list(Path(self.tmp.name).glob("*.json"))
        step = {
            "call_id": "private",
            "name": "read_file",
            "args": {"path": "private.txt"},
            "output": "private synthetic data",
            "error": False,
        }
        state.record_event(run["id"], "tool_result", step)
        state.finish_run(run["id"])
        self.assertEqual(state.run_sources(run["id"])["files"], ["private.txt"])
        self.assertEqual(list(Path(self.tmp.name).glob("*.json")), files_before)
        incognito.delete_session(private_session.id)
        self.assertEqual(state.run_sources(run["id"]), {})
        self.assertNotIn(run["id"], state._private)


class RuntimeSourceOutcomesTest(unittest.TestCase):
    def drive(self, *, stop_early=False, stop_with_result=False):
        stop = asyncio.Event()
        call = {"call_id": "synthetic-read", "name": "docs_read", "args": {"path": "one.md"}}

        async def model(*args, **kwargs):
            if any(m.get("role") == "tool" for m in args[0]):
                yield {"done": True}
            else:
                yield {"tool_call": call}
                yield {"done": True}

        async def execute(name, args):
            yield {"type": "output", "text": "partial content"}
            if stop_early:
                stop.set()
                return
            if stop_with_result:
                stop.set()
            yield {
                "type": "result",
                "result": {
                    "output": json.dumps(
                        {"path": "one.md", "hash": "a" * 64, "content": "owned fixture"}
                    ),
                    "path": "one.md",
                    "hash": "a" * 64,
                },
            }

        async def run():
            return [
                chunk
                async for chunk in runtime.run_agent(
                    [{"role": "user", "content": "read owned fixture"}],
                    SimpleNamespace(base_url="http://127.0.0.1:1", api_key=""),
                    "synthetic",
                    stop,
                    {"agent_context_files": False},
                    [],
                    [],
                    [],
                )
            ]

        with (
            tempfile.TemporaryDirectory(prefix="alles-source-runtime-") as directory,
            mock.patch.object(state, "DATA_DIR", Path(directory)),
            mock.patch.object(runtime, "stream_chat", model),
            mock.patch.object(runtime, "stream_execute", execute),
            mock.patch("services.automations.on_agent_tool", new=mock.AsyncMock()),
        ):
            chunks = asyncio.run(run())
            rid = next(c["agent_run"]["id"] for c in chunks if "agent_run" in c)
            self.addCleanup(state._active.pop, rid, None)
            state._active.pop(rid, None)
            return chunks, state.get_run(rid), state.run_sources(rid)

    def test_completed_runtime_read_survives_disk_reload(self):
        _, run, sources = self.drive()
        self.assertEqual(run["status"], "done")
        self.assertEqual(sources["files"], ["one.md"])

    def test_stopped_stream_does_not_become_a_successful_result(self):
        chunks, run, sources = self.drive(stop_early=True)
        self.assertEqual(run["status"], "stopped")
        result = next(c["tool_result"] for c in chunks if "tool_result" in c)
        self.assertTrue(result["error"])
        self.assertEqual(sources["files"], [])
        self.assertEqual(sources["outcomes"]["unfinished"], 1)

    def test_stop_racing_with_an_explicit_result_keeps_the_confirmed_source(self):
        chunks, run, sources = self.drive(stop_with_result=True)
        self.assertEqual(run["status"], "stopped")
        result = next(c["tool_result"] for c in chunks if "tool_result" in c)
        self.assertFalse(result["error"])
        self.assertTrue(result["completed"])
        self.assertEqual(sources["files"], ["one.md"])
        self.assertEqual(sources["outcomes"]["unfinished"], 0)


if __name__ == "__main__":
    unittest.main()
