import asyncio
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.database import CodingProject, ModelEndpoint
from services import pi_agent
from tests._client import ApiTest

FAKE = Path(__file__).parent / "fixtures" / "fake_pi.py"


def fake_bin(folder: Path) -> Path:
    wrapper = folder / "pi"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    return wrapper


class PiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.project_dir = root / "work" / "site"
        self.project_dir.mkdir(parents=True)
        (self.project_dir / "notes.txt").write_text("hello")
        self.data = root / "data"
        self.data.mkdir()
        # only pi's own folder moves; alles's data dir (and its secret key) stays put
        self.env = mock.patch.dict(os.environ, {"ALLES_PI_BIN": str(fake_bin(root))})
        self.env.start()
        self.home = mock.patch.object(pi_agent, "data_dir", lambda: self.data)
        self.home.start()

    def tearDown(self):
        asyncio.run(pi_agent.close_all())
        pi_agent._chats.clear()
        self.home.stop()
        self.env.stop()
        self.tmp.cleanup()
        super().tearDown()

    def add_endpoint(self, **fields):
        row = ModelEndpoint(
            name=fields.pop("name", "proxy"),
            base_url=fields.pop("base_url", "http://127.0.0.1:8317"),
            api_key=fields.pop("api_key", "sk-test-secret"),
            cached_models=json.dumps(fields.pop("models", ["coder-1", "coder-2"])),
            **fields,
        )
        with self.db() as session:
            session.add(row)
            session.commit()
            return row.id


class FolderAndModelTest(PiTest):
    def test_project_folders_must_be_real_and_outside_alles_data(self):
        self.assertEqual(pi_agent.check_folder(str(self.project_dir)), self.project_dir.resolve())
        for bad in ("relative/path", str(self.project_dir / "missing"), "/"):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                pi_agent.check_folder(bad)
        private = self.data / "vault"
        private.mkdir()
        with self.assertRaises(ValueError):
            pi_agent.check_folder(str(private))

    def test_models_json_names_keys_by_env_var_only(self):
        self.add_endpoint()
        self.add_endpoint(name="claude", base_url="https://api.anthropic.com", models=["claude-x"])
        self.add_endpoint(name="signed in", auth_type="oauth", models=["gemini-x"])
        with self.db() as session:
            config, env, choices = pi_agent.model_config(session)
        dumped = json.dumps(config)
        self.assertNotIn("sk-test-secret", dumped)
        self.assertIn("sk-test-secret", env.values())
        apis = {p["api"]: p["baseUrl"] for p in config["providers"].values()}
        self.assertEqual(apis["openai-completions"], "http://127.0.0.1:8317/v1")
        self.assertEqual(apis["anthropic-messages"], "https://api.anthropic.com")
        self.assertEqual({c["model"] for c in choices}, {"coder-1", "coder-2", "claude-x"})

    def test_pi_gets_no_alles_secrets(self):
        with mock.patch.dict(os.environ, {"ALLES_SECRET_KEY": "x", "HOME": "/home/me"}):
            env = pi_agent._clean_env({"ALLES_PI_KEY_0": "k"})
        self.assertNotIn("ALLES_SECRET_KEY", env)
        self.assertEqual(env["ALLES_PI_KEY_0"], "k")
        self.assertEqual(env["HOME"], "/home/me")

    def test_status_is_ready_with_a_pinned_binary(self):
        self.assertEqual(pi_agent.status()["state"], "ready")


class ChatRuntimeTest(PiTest):
    def project(self):
        return SimpleNamespace(id="proj1", path=str(self.project_dir))

    def test_a_chat_streams_saves_and_resumes(self):
        self.add_endpoint()

        async def flow():
            with self.db() as session:
                choice = pi_agent.resolve_choice(session)
                chat = await pi_agent.open_chat(session, self.project(), None, choice)
            seen = asyncio.Queue()
            chat.listeners.add(seen)
            await chat.send("fix the header")
            kinds = []
            while (event := await asyncio.wait_for(seen.get(), 10))["kind"] != "idle":
                kinds.append(event["kind"])
            chat_id, stats = chat.id, chat.stats
            await chat.close()
            with self.db() as session:
                again = await pi_agent.open_chat(session, self.project(), chat_id, choice)
            same = again.id == chat_id
            await again.close()
            return chat_id, kinds, stats, same

        chat_id, kinds, stats, same = asyncio.run(flow())
        self.assertEqual(kinds[:2], ["user", "busy"])
        self.assertIn("tool", kinds)
        self.assertIn("delta", kinds)
        self.assertEqual(kinds[-1], "stats")
        self.assertGreater(stats["tokens_per_second"], 0)
        self.assertEqual(stats["cache_hit_rate"], 0.75)
        self.assertTrue(same)
        saved = pi_agent.transcript("proj1", chat_id)
        self.assertEqual(
            [item["kind"] for item in saved["items"]],
            ["user", "assistant", "tool_done", "assistant"],
        )
        self.assertEqual(saved["items"][-1]["text"], "done with fix the header")
        self.assertEqual(saved["model"]["model"], "coder-1")
        self.assertEqual(pi_agent.list_chats("proj1")[0]["title"], "fix the header")

    def test_stop_ends_a_long_run_and_questions_go_to_the_owner(self):
        self.add_endpoint()

        async def flow():
            with self.db() as session:
                choice = pi_agent.resolve_choice(session)
                chat = await pi_agent.open_chat(session, self.project(), None, choice)
            await chat.send("slow job")
            await asyncio.sleep(0.3)
            busy_before = chat.busy
            await chat.stop()
            await asyncio.sleep(0.2)
            busy_after = chat.busy
            await chat.send("ask first")
            for _ in range(50):
                if chat.questions:
                    break
                await asyncio.sleep(0.05)
            question = next(iter(chat.questions.values()))
            await chat.answer(question["id"], True)
            for _ in range(80):
                if not chat.busy and any(e["kind"] == "stats" for e in chat.log[-3:]):
                    break
                await asyncio.sleep(0.05)
            await chat.close()
            return busy_before, busy_after, question, chat.id

        busy_before, busy_after, question, chat_id = asyncio.run(flow())
        self.assertTrue(busy_before)
        self.assertFalse(busy_after)
        self.assertEqual(question["title"], "trust?")
        saved = pi_agent.transcript("proj1", chat_id)
        self.assertEqual(saved["items"][-1]["text"], "done with ask first trusted=True")


class PiRunToolTest(PiTest):
    def test_chat_hands_a_task_to_pi_and_gets_the_answer(self):
        from services import agent_tools

        self.add_endpoint()
        none = asyncio.run(agent_tools._pi_run("fix it"))
        self.assertTrue(none["error"])
        with self.db() as session:
            session.add(CodingProject(path=str(self.project_dir), name="site"))
            session.commit()
        result = asyncio.run(
            agent_tools._pi_run("tidy the readme", project="site", wait_seconds=30)
        )
        self.assertIn("done with tidy the readme", result["output"])
        self.assertIn("tools used: read", result["output"])
        self.assertEqual(result["project"], "site")
        self.assertTrue(pi_agent.transcript(result["project_id"], result["chat_id"]))


class CodeRoutesTest(PiTest):
    def test_projects_folders_and_saved_chats(self):
        self.add_endpoint()
        status = self.client.get("/api/aide/code/status").json()
        self.assertEqual(status["pi"]["state"], "ready")
        self.assertEqual(status["default"]["model"], "coder-1")
        self.assertNotIn("provider", status["default"])

        listing = self.client.get(
            "/api/aide/code/folders", params={"path": str(self.project_dir.parent)}
        )
        self.assertEqual(listing.json()["folders"], ["site"])

        bad = self.client.post("/api/aide/code/projects", json={"path": str(self.data)})
        self.assertEqual(bad.status_code, 400)
        made = self.client.post("/api/aide/code/projects", json={"path": str(self.project_dir)})
        self.assertEqual(made.status_code, 200, made.text)
        project = made.json()
        self.assertEqual(project["name"], "site")
        again = self.client.post("/api/aide/code/projects", json={"path": str(self.project_dir)})
        self.assertEqual(again.json()["id"], project["id"])

        folder = pi_agent.sessions_dir(project["id"])
        folder.mkdir(parents=True)
        chat_id = "01a15525-c31e-7005-a844-42724e273385"
        lines = [
            {"type": "session", "id": chat_id, "timestamp": "2026-10-19T17:00:00Z"},
            {
                "type": "message",
                "id": "a",
                "parentId": None,
                "message": {"role": "user", "content": "hi pi"},
            },
        ]
        (folder / f"2026-10-19_{chat_id}.jsonl").write_text("\n".join(map(json.dumps, lines)))
        chats = self.client.get(f"/api/aide/code/projects/{project['id']}/chats").json()["items"]
        self.assertEqual([(c["id"], c["title"]) for c in chats], [(chat_id, "hi pi")])
        chat = self.client.get(f"/api/aide/code/projects/{project['id']}/chats/{chat_id}").json()
        self.assertEqual(chat["items"], [{"kind": "user", "text": "hi pi"}])
        self.assertFalse(chat["live"])

        gone = self.client.delete(f"/api/aide/code/projects/{project['id']}")
        self.assertEqual(gone.status_code, 200)
        self.assertFalse(folder.exists())
        with self.db() as session:
            self.assertEqual(session.query(CodingProject).count(), 0)

    def test_new_chat_needs_a_usable_model(self):
        project = self.client.post(
            "/api/aide/code/projects", json={"path": str(self.project_dir)}
        ).json()
        reply = self.client.post(
            f"/api/aide/code/projects/{project['id']}/chats", json={"text": "go"}
        )
        self.assertEqual(reply.status_code, 409)
        self.assertEqual(reply.json()["code"], "coding_model_missing")


if __name__ == "__main__":
    unittest.main()
