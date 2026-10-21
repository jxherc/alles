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
        fake = str(fake_bin(root))
        self.env = mock.patch.dict(
            os.environ,
            {"ALLES_PI_BIN": fake, "ALLES_OMP_BIN": fake, "ALLES_PI_WORKSPACE": str(root / "aide")},
        )
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


class OmpAndAcpTest(PiTest):
    def project(self):
        return SimpleNamespace(id="proj1", path=str(self.project_dir))

    def test_omp_runs_through_the_same_driver(self):
        self.add_endpoint()

        async def flow():
            with self.db() as session:
                choice = pi_agent.resolve_choice(session)
                chat = await pi_agent.open_chat(session, self.project(), None, choice, "omp")
            seen = asyncio.Queue()
            chat.listeners.add(seen)
            await chat.send("tidy up")
            while (await asyncio.wait_for(seen.get(), 10))["kind"] != "idle":
                pass
            await chat.close()
            return chat.id

        chat_id = asyncio.run(flow())
        models = json.loads((pi_agent.agent_dir("omp") / "models.yml").read_text())
        provider = next(iter(models["providers"].values()))
        self.assertTrue(
            provider["apiKey"].startswith("ALLES_PI_KEY_")
        )  # an env var name, not a key
        self.assertNotIn("sk-test-secret", (pi_agent.agent_dir("omp") / "models.yml").read_text())
        self.assertEqual(pi_agent.find_chat("proj1", chat_id)[1], "omp")
        saved = pi_agent.transcript("proj1", chat_id)
        self.assertEqual(
            (saved["harness"], saved["items"][-1]["text"]), ("omp", "done with tidy up")
        )
        self.assertEqual(pi_agent.list_chats("proj1")[0]["harness"], "omp")

    def acp_entry(self):
        return {"id": "fake-acp", "name": "Fake ACP"}, [
            sys.executable,
            "-I",
            str(FAKE.parent / "fake_acp.py"),
        ]

    def test_an_acp_harness_streams_asks_and_switches_models(self):
        from services import acp_agent

        entry, command = self.acp_entry()

        async def flow():
            chat = acp_agent.AcpChat(self.project(), entry, command, {})
            await chat.start()
            seen = asyncio.Queue()
            chat.listeners.add(seen)
            await chat.send("ask then read")
            events = []
            while (event := await asyncio.wait_for(seen.get(), 10))["kind"] != "idle":
                events.append(event)
                if event["kind"] == "question":
                    await chat.answer(event["id"], "Allow once")
            models = [m["model"] for m in chat.models]
            await chat.set_model({"model": "fake-large"})
            await chat.send("again")
            while (await asyncio.wait_for(seen.get(), 10))["kind"] != "idle":
                pass
            await chat.close()
            return chat.id, events, models, chat.stats

        chat_id, events, models, stats = asyncio.run(flow())
        kinds = [e["kind"] for e in events]
        self.assertIn("question", kinds)
        self.assertEqual(
            next(e for e in events if e["kind"] == "question")["options"], ["Allow once", "Reject"]
        )
        self.assertIn("tool", kinds)
        self.assertEqual(
            next(e for e in events if e["kind"] == "tool_done")["output"], "hello from notes"
        )
        self.assertEqual(models, ["fake-small", "fake-large"])
        self.assertEqual(stats["context_percent"], 2.0)
        saved = pi_agent.transcript("proj1", chat_id)
        self.assertEqual(saved["harness"], "fake-acp")
        texts = [i["text"] for i in saved["items"] if i["kind"] == "assistant"]
        # text before a tool call is its own block, like the live view shows it
        self.assertEqual(
            texts[:2], ["looking. ", "done with ask then read allowed=yes on fake-small"]
        )
        self.assertTrue(texts[-1].endswith("on fake-large"))
        listed = pi_agent.list_chats("proj1")
        self.assertEqual((listed[0]["harness"], listed[0]["title"]), ("fake-acp", "ask then read"))

    def test_acp_stop_and_resume(self):
        from services import acp_agent

        entry, command = self.acp_entry()

        async def flow():
            chat = acp_agent.AcpChat(self.project(), entry, command, {})
            await chat.start()
            await chat.send("slow job")
            await asyncio.sleep(0.3)
            busy = chat.busy
            await chat.stop()
            for _ in range(50):
                if not chat.busy:
                    break
                await asyncio.sleep(0.05)
            first_session = chat.acp_session
            chat_id = chat.id
            await chat.close()
            again = acp_agent.AcpChat(self.project(), entry, command, {})
            await again.start({"chat_id": chat_id, "acp_session": first_session})
            same = (again.id, again.acp_session) == (chat_id, first_session)
            await again.close()
            return busy, same, chat_id

        busy, same, chat_id = asyncio.run(flow())
        self.assertTrue(busy)
        self.assertTrue(same)
        notes = [
            i["text"] for i in pi_agent.transcript("proj1", chat_id)["items"] if i["kind"] == "note"
        ]
        self.assertIn("stopped", notes)


class SecretsAndBridgeTest(PiTest):
    def project(self):
        return SimpleNamespace(id="proj1", path=str(self.project_dir))

    def test_marked_and_known_secrets_never_reach_pi_or_the_saved_chat(self):
        self.add_endpoint()

        async def flow():
            with self.db() as session:
                choice = pi_agent.resolve_choice(session)
                chat = await pi_agent.open_chat(session, self.project(), None, choice, "pi")
            seen = asyncio.Queue()
            chat.listeners.add(seen)
            await chat.send("save ||hunter2-pass|| and sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz012345")
            events = []
            while (event := await asyncio.wait_for(seen.get(), 10))["kind"] != "idle":
                events.append(event)
            await chat.close()
            return chat.id, events, chat.secrets

        chat_id, events, secrets = asyncio.run(flow())
        self.assertEqual(
            set(secrets.values()), {"hunter2-pass", "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz012345"}
        )
        shown = json.dumps(events)
        self.assertNotIn("hunter2", shown)
        self.assertIn("{{secret:secret_1}}", shown)
        saved = pi_agent.find_chat("proj1", chat_id)[0].read_text()
        self.assertNotIn("hunter2", saved)
        sealed = pi_agent._secrets_file(chat_id).read_text()
        self.assertNotIn("hunter2", sealed)
        self.assertEqual(pi_agent.load_secrets(chat_id), secrets)
        self.assertIn("{{secret:NAME}}", (pi_agent.agent_dir("pi") / "SYSTEM.md").read_text())

    def test_the_bridge_needs_a_live_chat_token_from_this_machine(self):
        chat = SimpleNamespace(last_active=0)
        pi_agent._chats["c1"] = chat
        pi_agent._bridge_tokens["tok"] = "c1"
        remote = self.client.post(
            "/pi-bridge/search", json={"query": "x"}, headers={"authorization": "Bearer tok"}
        )
        self.assertEqual(remote.status_code, 403)  # the test client isn't this machine
        local = mock.patch("routes.aide._LOCAL_CLIENTS", {"testclient"})
        local.start()
        self.addCleanup(local.stop)
        try:
            bad = self.client.post(
                "/pi-bridge/search", json={"query": "x"}, headers={"authorization": "Bearer nope"}
            )
            self.assertEqual(bad.status_code, 401)

            async def found(query, max_results=6):
                return {
                    "results": [
                        {"title": "t", "url": "https://e.test", "snippet": "s", "extra": 1}
                    ],
                    "provider": "fake",
                }

            with mock.patch("services.andromeda.normal_search", side_effect=found):
                ok = self.client.post(
                    "/pi-bridge/search",
                    json={"query": "x", "count": 2},
                    headers={"authorization": "Bearer tok"},
                )
            self.assertEqual(ok.status_code, 200, ok.text)
            self.assertEqual(
                ok.json()["results"], [{"title": "t", "url": "https://e.test", "snippet": "s"}]
            )
            private = self.client.post(
                "/pi-bridge/fetch",
                json={"url": "http://127.0.0.1:22/"},
                headers={"authorization": "Bearer tok"},
            )
            self.assertEqual(private.status_code, 400)
        finally:
            pi_agent._chats.pop("c1", None)
            pi_agent._bridge_tokens.pop("tok", None)

    def test_pi_can_use_alles_tools_and_changes_need_an_ok(self):
        names = {t["name"]: t for t in pi_agent.bridge_tools()}
        self.assertIn("alles_docs_write", names)
        self.assertTrue(names["alles_docs_write"]["changes"])
        self.assertFalse(names["alles_docs_read"]["changes"])
        for kept_with_aide in (
            "alles_mail_send",
            "alles_browse_open",
            "alles_server_service_control",
        ):
            self.assertNotIn(kept_with_aide, names)

        chat = SimpleNamespace(last_active=0, writes="ask")
        pi_agent._chats["c2"] = chat
        pi_agent._bridge_tokens["tok2"] = "c2"
        local = mock.patch("routes.aide._LOCAL_CLIENTS", {"testclient"})
        local.start()
        self.addCleanup(local.stop)
        ran = []

        async def fake_execute(name, args):
            ran.append((name, args))
            return {"output": f"ran {name}"}

        auth = {"authorization": "Bearer tok2"}
        try:
            with mock.patch("services.agent_tools.execute", side_effect=fake_execute):
                unknown = self.client.post(
                    "/pi-bridge/tool", json={"name": "alles_mail_send"}, headers=auth
                )
                self.assertEqual(unknown.status_code, 404)
                read = self.client.post(
                    "/pi-bridge/tool",
                    json={"name": "alles_docs_read", "args": {"path": "a.md"}},
                    headers=auth,
                )
                self.assertEqual(read.json(), {"output": "ran docs_read", "error": False})
                write = {"name": "alles_docs_write", "args": {"path": "a.md", "content": "x"}}
                held = self.client.post("/pi-bridge/tool", json=write, headers=auth)
                self.assertEqual(held.status_code, 403)  # pi has to ask the owner first
                ok = self.client.post(
                    "/pi-bridge/tool", json={**write, "confirmed": True}, headers=auth
                )
                self.assertEqual(ok.status_code, 200, ok.text)
                chat.writes = "allow"  # handed over by Aide, or code on auto
                handed = self.client.post("/pi-bridge/tool", json=write, headers=auth)
                self.assertEqual(handed.status_code, 200)
            self.assertEqual([name for name, _ in ran], ["docs_read", "docs_write", "docs_write"])
        finally:
            pi_agent._chats.pop("c2", None)
            pi_agent._bridge_tokens.pop("tok2", None)


class HarnessCatalogTest(PiTest):
    def test_catalog_marks_open_source_and_installs_safely(self):
        from services import harnesses

        registry = [
            {"id": "pi-acp", "license": "MIT", "distribution": {"npx": {"package": "pi-acp@1"}}},
            {
                "id": "qwen-code",
                "name": "Qwen Code",
                "license": "Apache-2.0",
                "version": "0.25.3",
                "distribution": {
                    "npx": {"package": "@qwen-code/qwen-code@0.25.3", "args": ["--acp"]}
                },
            },
            {"id": "closed", "license": "proprietary", "distribution": {}},
        ]
        rows = {e["id"]: harnesses.public(e) for e in harnesses.catalog(registry)}
        self.assertNotIn("pi-acp", rows)  # pi runs natively instead
        self.assertEqual(list(rows)[:2], ["pi", "omp"])
        self.assertIn("deepseek-harness", rows)
        self.assertTrue(rows["qwen-code"]["open_source"])
        self.assertFalse(rows["closed"]["open_source"])
        self.assertEqual(
            (rows["qwen-code"]["state"], rows["closed"]["state"]), ("missing", "unavailable")
        )
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.data)}):
            entry = harnesses.find(registry, "qwen-code")
            home = harnesses._home(entry)
            (home / "node_modules/@qwen-code/qwen-code").mkdir(parents=True)
            (home / "node_modules/@qwen-code/qwen-code/package.json").write_text(
                json.dumps({"bin": {"qwen": "cli.js"}})
            )
            (home / "node_modules/.bin").mkdir()
            (home / "node_modules/.bin/qwen").write_text("")
            command, _env = harnesses.launch(entry)
            self.assertEqual(command[1:], ["--acp"])
            self.assertTrue(command[0].endswith("node_modules/.bin/qwen"))
            escape = {
                "id": "evil",
                "version": "1",
                "distribution": {"binary": {harnesses.platform_key(): {"cmd": "../../etc/x"}}},
            }
            self.assertIsNone(harnesses.launch(escape))

    def test_default_harness_setting(self):
        self.add_endpoint()
        status = self.client.get("/api/aide/code/status").json()
        self.assertEqual(
            status["settings"], {"harness": "pi", "approval": "auto", "guard": True, "thinking": ""}
        )
        self.assertEqual([n["harness"] for n in status["native"]], ["pi", "omp"])
        changed = self.client.put(
            "/api/aide/code/settings", json={"harness": "omp", "approval": "ask"}
        )
        self.assertEqual(
            changed.json(), {"harness": "omp", "approval": "ask", "guard": True, "thinking": ""}
        )
        unknown = self.client.put("/api/aide/code/settings", json={"harness": "nope"})
        self.assertEqual(unknown.status_code, 404)
        self.client.put("/api/aide/code/settings", json={"harness": "pi"})


class PiRunToolTest(PiTest):
    def test_chat_hands_a_task_to_pi_and_gets_the_answer(self):
        from services import agent_tools

        missing = asyncio.run(agent_tools._pi_run("fix it", project="nowhere"))
        self.assertTrue(missing["error"])
        self.add_endpoint()
        # no project: pi works in its own Aide folder, handed over so it doesn't ask again
        own = asyncio.run(agent_tools._pi_run("write a plan", wait_seconds=30))
        self.assertEqual(own["project"], "Aide")
        self.assertIn("done with write a plan", own["output"])
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

    def test_pi_steps_stream_into_the_aide_answer(self):
        from services import agent_tools

        self.add_endpoint()

        async def collect():
            return [event async for event in agent_tools.stream_execute("pi_run", {"task": "look"})]

        events = asyncio.run(collect())
        lines = "".join(e["text"] for e in events if e["type"] == "output")
        self.assertIn("pi is working in Aide", lines)
        self.assertIn("· read notes.txt", lines)
        self.assertEqual(events[-1]["type"], "result")


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


class EffortAndCommandsTest(PiTest):
    def test_reasoning_models_are_marked_for_pi(self):
        self.add_endpoint(models=["coder-thinking", "gemini-3.8-flash-high", "gpt-4o"])
        with self.db() as session:
            config, _, choices = pi_agent.model_config(session)
        listed = next(iter(config["providers"].values()))["models"]
        self.assertEqual([m.get("reasoning", False) for m in listed], [True, True, False])
        self.assertEqual([c["thinks"] for c in choices], [True, True, False])

    def test_effort_commands_context_compact_and_goal(self):
        self.add_endpoint(models=["coder-thinking"])
        project = SimpleNamespace(id="proj1", path=str(self.project_dir))

        async def flow():
            with self.db() as session:
                choice = pi_agent.resolve_choice(session)
                chat = await pi_agent.open_chat(session, project, None, choice)
            first = dict(chat.thinking)
            picked = await chat.set_thinking("high")
            names = [c["name"] for c in await chat.commands()]
            for text in ["/compact the tests", "/context", "/goal ship the header"]:
                self.assertIsNotNone(await chat.builtin(text))
            goal = pi_agent.load_goal(chat.id)
            await chat.builtin("/goal clear")
            plain = await chat.builtin("fix it")  # not a command: pi gets it as is
            await chat.close()
            return first, picked, names, chat.log, goal, plain, chat.id

        first, picked, names, log, goal, plain, chat_id = asyncio.run(flow())
        self.assertEqual(
            first, {"level": "medium", "levels": ["off", "minimal", "low", "medium", "high"]}
        )
        self.assertEqual(picked["level"], "high")
        self.assertEqual(names, ["fix-tests"])  # alles's own bridge command stays hidden
        kinds = {e["kind"]: e for e in log if e["kind"] in ("compacted", "context")}
        self.assertEqual((kinds["compacted"]["before"], kinds["compacted"]["after"]), (9000, 1200))
        self.assertEqual(kinds["compacted"]["summary"], "kept: the tests")
        self.assertEqual((kinds["context"]["tokens"], kinds["context"]["window"]), (4000, 100000))
        self.assertEqual([e["state"] for e in log if e["kind"] == "goal"], ["set", "cleared"])
        self.assertEqual((goal, pi_agent.load_goal(chat_id)), ("ship the header", ""))
        self.assertIsNone(plain)
        # the goal went to pi as work, without a user bubble of the instructions
        self.assertFalse(any(e["kind"] == "user" for e in log))

    def test_effort_route_saves_the_level_new_chats_start_with(self):
        from core.settings import save_settings

        self.addCleanup(save_settings, {"coding_thinking": ""})
        bad = self.client.put("/api/aide/code/thinking", json={"level": "ludicrous"})
        self.assertEqual(bad.status_code, 422)
        saved = self.client.put("/api/aide/code/thinking", json={"level": "low"}).json()
        self.assertEqual((saved["level"], saved["live"]), ("low", False))
        self.assertEqual(pi_agent.settings()["thinking"], "low")
        project = self.client.post(
            "/api/aide/code/projects", json={"path": str(self.project_dir)}
        ).json()
        idle = self.client.get(f"/api/aide/code/projects/{project['id']}/chats/nope/commands")
        self.assertEqual(idle.json(), {"items": []})


if __name__ == "__main__":
    unittest.main()
