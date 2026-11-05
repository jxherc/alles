import asyncio
import json
from unittest import mock

from core.database import JarvisRun, JarvisRunPrompt
from core.settings import save_settings
from services import photon_channel
from tests._client import ApiTest


class PhotonTest(ApiTest):
    def setUp(self):
        super().setUp()
        photon_channel._runs.clear()
        photon_channel._seen.clear()
        photon_channel._told_text_only.clear()
        photon_channel.state.update(ignored=0, handled=0, last_ignored="")
        save_settings({"photon_owner_handles": ["+1 (555) 010-0199", "me@example.test"]})
        self.sent = []

        async def reply(space, text):
            self.sent.append((space, text))

        async def typing(space, on):
            pass

        patches = [
            mock.patch.object(photon_channel, "reply", side_effect=reply),
            mock.patch.object(photon_channel, "_typing", side_effect=typing),
            mock.patch("services.jarvis_handoff.launch"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        save_settings({"photon_owner_handles": [], "photon_enabled": False})
        super().tearDown()

    def message(self, text, sender="+15550100199", message_id="m1"):
        return {
            "type": "message",
            "id": message_id,
            "space": "chat-1",
            "sender": sender,
            "text": text,
        }

    def test_only_the_owner_is_answered_and_texts_become_aide_work(self):
        asyncio.run(
            photon_channel.handle_message(
                self.message("hi", sender="+19998887777", message_id="m0")
            )
        )
        self.assertEqual(photon_channel.state["ignored"], 1)
        with self.db() as db:
            self.assertEqual(db.query(JarvisRun).count(), 0)

        asyncio.run(photon_channel.handle_message(self.message("what's on today?")))
        asyncio.run(photon_channel.handle_message(self.message("what's on today?")))  # a resend
        with self.db() as db:
            runs = db.query(JarvisRun).all()
            self.assertEqual(len(runs), 1)
            session_id = runs[0].session_id
        from services.aide_conversation import get_or_create_primary

        with self.db() as db:
            self.assertEqual(session_id, get_or_create_primary(db).id)  # the one main conversation
        self.assertIn(runs[0].id, photon_channel._runs)

    def test_typing_bubbles_get_no_answer_and_photos_one_a_minute(self):
        for n, kind in enumerate(["typing", "typing", "reaction", "effect"]):
            record = {**self.message("", message_id=f"t{n}"), "kind": kind}
            asyncio.run(photon_channel.handle_message(record))
        self.assertEqual(self.sent, [])
        for n in range(3):
            record = {**self.message("", message_id=f"p{n}"), "kind": "attachment"}
            asyncio.run(photon_channel.handle_message(record))
        self.assertEqual(self.sent, [("chat-1", "I can only read text here for now.")])

    def test_email_handles_and_number_formats_match(self):
        self.assertTrue(photon_channel.is_owner("ME@example.test", ["me@example.test"]))
        self.assertTrue(photon_channel.is_owner("+15550100199", ["(555) 010-0199"]))
        self.assertFalse(photon_channel.is_owner("", ["me@example.test"]))

    def run_watch_once(self):
        async def once():
            with mock.patch.object(photon_channel, "POLL_SECONDS", 0):
                task = asyncio.create_task(photon_channel._watch_runs())
                await asyncio.sleep(0.05)
                task.cancel()

        asyncio.run(once())

    def test_answers_questions_and_keeps_approvals_inside_alles(self):
        asyncio.run(photon_channel.handle_message(self.message("plan my week")))
        run_id = next(iter(photon_channel._runs))
        with self.db() as db:
            db.add(
                JarvisRunPrompt(
                    run_id=run_id,
                    kind="choice",
                    question="which week?",
                    options=json.dumps(["this", "next"]),
                )
            )
            db.add(
                JarvisRunPrompt(
                    run_id=run_id, kind="approval", question="send mail", action="mail_send"
                )
            )
            db.commit()
        self.run_watch_once()
        texts = [text for _, text in self.sent]
        self.assertTrue(any("which week?" in t and "2. next" in t for t in texts))
        self.assertTrue(any("approvals only happen inside alles" in t for t in texts))

        with mock.patch(
            "services.agent_runtime.resolve_user_question_from_jarvis", return_value=True
        ):
            asyncio.run(photon_channel.handle_message(self.message("2", message_id="m2")))
        with self.db() as db:
            choice = db.query(JarvisRunPrompt).filter_by(kind="choice").one()
            self.assertEqual((choice.state, choice.answer), ("answered", "next"))
            self.assertEqual(
                db.query(JarvisRunPrompt).filter_by(kind="approval").one().state, "pending"
            )
            self.assertEqual(
                db.query(JarvisRun).count(), 1
            )  # "2" answered; it didn't start new work

        with self.db() as db:
            run = db.get(JarvisRun, run_id)
            run.state, run.result_summary = "succeeded", "your week looks clear"
            db.commit()
        self.run_watch_once()
        self.assertEqual(self.sent[-1], ("chat-1", "your week looks clear"))
        self.assertNotIn(run_id, photon_channel._runs)

    def test_a_tool_waiting_for_your_ok_is_texted_once(self):
        from datetime import UTC, datetime, timedelta

        from core.database import DelegatedAction

        asyncio.run(photon_channel.handle_message(self.message("testing")))
        run_id = next(iter(photon_channel._runs))
        with self.db() as db:
            run = db.get(JarvisRun, run_id)
            db.add(
                DelegatedAction(
                    origin="aide",
                    session_id=run.session_id,
                    scope_kind="general",
                    capability="shell",
                    action="shell",
                    target="Project shell",
                    exact_hash="a" * 64,
                    pending_key="a" * 64,
                    state="pending",
                    expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10),
                )
            )
            db.commit()
        self.run_watch_once()
        self.run_watch_once()
        asks = [t for _, t in self.sent if "needs your ok in Aide: shell" in t]
        self.assertEqual(len(asks), 1)

    def test_settings_need_an_owner_and_never_return_the_secret(self):
        bad = self.client.put(
            "/api/aide/channels/photon", json={"enabled": True, "project_id": "p"}
        )
        self.assertEqual(bad.status_code, 400)
        with (
            mock.patch.object(photon_channel, "restart", new=mock.AsyncMock()),
            mock.patch.object(
                photon_channel, "register_numbers", new=mock.AsyncMock()
            ) as registered,
        ):
            ok = self.client.put(
                "/api/aide/channels/photon",
                json={
                    "enabled": True,
                    "project_id": "p1",
                    "project_secret": "s3cret-value",
                    "owner_handles": ["me@example.test"],
                },
            )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertTrue(ok.json()["has_secret"])
        registered.assert_awaited_once()  # saving lets the owner's numbers through at Photon
        self.assertNotIn("s3cret-value", ok.text)
        self.assertNotIn("s3cret-value", self.client.get("/api/aide/channels/photon").text)

    def test_the_general_settings_api_never_shows_the_secret(self):
        save_settings({"photon_project_secret": "s3cret-value"})
        self.assertNotIn("s3cret-value", self.client.get("/api/settings").text)


class PhotonSetupTest(ApiTest):
    """the hermes-style setup: register owner numbers, and a device login that does the rest."""

    def fake_photon(self, users=None, pending=1):
        import httpx

        users = users if users is not None else []
        calls = {"posted_users": [], "polls": 0, "projects": [], "regenerated": 0}

        def handle(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/users/") and request.method == "GET":
                return httpx.Response(
                    200, json={"succeed": True, "data": {"users": users, "total": len(users)}}
                )
            if path.endswith("/users/") and request.method == "POST":
                body = json.loads(request.content)
                calls["posted_users"].append(body["phoneNumber"])
                user = {"phoneNumber": body["phoneNumber"], "assignedPhoneNumber": "+15550100754"}
                users.append(user)
                return httpx.Response(200, json={"succeed": True, "data": user})
            if path == "/api/auth/device/code":
                return httpx.Response(
                    200,
                    json={
                        "device_code": "dev-1",
                        "user_code": "ABCD-EFGH",
                        "verification_uri": "https://app.photon.codes/device",
                        "verification_uri_complete": "https://app.photon.codes/device?code=ABCD-EFGH",
                        "interval": 0,
                        "expires_in": 60,
                    },
                )
            if path == "/api/auth/device/token":
                calls["polls"] += 1
                if calls["polls"] <= pending:
                    return httpx.Response(400, json={"error": "authorization_pending"})
                return httpx.Response(200, json={"access_token": "dash-token"})
            if path == "/api/auth/get-session":
                return httpx.Response(200, json={"user": {"email": "me@example.test"}})
            if path == "/api/projects" and request.method == "GET":
                return httpx.Response(200, json={"data": calls["projects"]})
            if path == "/api/projects" and request.method == "POST":
                project = {"id": "proj-1", "name": json.loads(request.content)["name"]}
                calls["projects"].append(project)
                return httpx.Response(200, json={"succeed": True, "data": project})
            if path.endswith("/regenerate-secret"):
                calls["regenerated"] += 1
                return httpx.Response(200, json={"projectSecret": "fresh-secret"})
            return httpx.Response(404, json={"message": "not found"})

        real = httpx.AsyncClient
        patch = mock.patch(
            "services.photon_setup.httpx.AsyncClient",
            side_effect=lambda *a, **k: real(*a, transport=httpx.MockTransport(handle), **k),
        )
        patch.start()
        self.addCleanup(patch.stop)
        return calls, users

    def test_numbers_photon_does_not_know_get_registered_once(self):
        from services import photon_setup

        calls, _users = self.fake_photon(
            users=[{"phoneNumber": "+15550100924", "assignedPhoneNumber": "+15550100754"}]
        )
        out = asyncio.run(
            photon_setup.ensure_numbers(
                "proj-1", "secret", ["+1 (437) 340-5952", "me@example.test", "15550100924"]
            )
        )
        self.assertEqual(
            calls["posted_users"], ["+14373405952"]
        )  # only the unknown number, in E.164
        self.assertEqual(
            out["lines"], {"+14373405952": "+15550100754", "+15550100924": "+15550100754"}
        )
        again = asyncio.run(photon_setup.ensure_numbers("proj-1", "secret", ["+1 (437) 340-5952"]))
        self.assertEqual(calls["posted_users"], ["+14373405952"])  # idempotent
        self.assertEqual(again["added"], [])

    def test_phone_handles_become_e164(self):
        from services import photon_setup

        self.assertEqual(photon_setup.e164("4373405952"), "+14373405952")
        self.assertEqual(photon_setup.e164("+81 90 1234 5678"), "+819012345678")
        self.assertEqual(photon_setup.e164("me@example.test"), "")
        self.assertEqual(photon_setup.e164("123"), "")

    def test_one_sign_in_sets_up_project_secret_and_number(self):
        from core.settings import load_settings
        from services import photon_setup

        save_settings(
            {
                "photon_owner_handles": ["+1 (437) 340-5952"],
                "photon_project_id": "",
                "photon_project_secret": "",
            }
        )
        calls, _users = self.fake_photon(pending=2)
        photon_setup.login.clear()

        async def run():
            with mock.patch.object(photon_channel, "restart", new=mock.AsyncMock()):
                started = photon_setup.start_login()
                self.assertEqual(started["state"], "starting")
                await photon_setup._login_task

        asyncio.run(run())
        self.assertEqual(photon_setup.login["state"], "done", photon_setup.login)
        saved = load_settings()
        self.assertEqual(
            (saved["photon_project_id"], saved["photon_project_secret"]), ("proj-1", "fresh-secret")
        )
        self.assertTrue(saved["photon_enabled"])
        self.assertEqual(calls["projects"][0]["name"], "alles")
        self.assertEqual(calls["posted_users"], ["+14373405952"])
        self.assertEqual(photon_setup.login["lines"], {"+14373405952": "+15550100754"})
        # the dashboard token is a credential: never shown by either settings api
        self.assertNotIn("dash-token", self.client.get("/api/settings").text)
        self.assertNotIn("dash-token", self.client.get("/api/aide/channels/photon").text)
        self.assertNotIn("fresh-secret", self.client.get("/api/aide/channels/photon").text)


class NotifyByMessageTest(ApiTest):
    """notify.send also texts the owner, through a fake sidecar that answers like the real one:
    a first message to a number is refused on a shared line (hermes adapter.py:85)."""

    message = PhotonTest.message

    def setUp(self):
        super().setUp()
        photon_channel._seen.clear()
        photon_channel._runs.clear()
        save_settings(
            {
                "photon_owner_handles": ["+1 (555) 010-0199"],
                "photon_enabled": True,
                "photon_project_id": "p1",
                "photon_project_secret": "s1",
                "photon_owner_space": "",
                "photon_owner_by": "",
            }
        )
        self.commands = []
        self.dedicated = False  # a dedicated line may start a chat; a shared one may not
        self.live = {"chat-1"}  # spaces the helper has seen since it started

        async def fake_send(command):
            self.commands.append(command)
            if command["type"] != "send" or not command.get("resolve"):
                return
            space = command["space"]
            if space in self.live or self.dedicated:
                answer = {"type": "sent", "id": command["id"], "space": space}
            else:
                answer = {
                    "type": "error",
                    "id": command["id"],
                    "class": "target_not_allowed",
                    "message": "Target not allowed for this project",
                }
            asyncio.get_running_loop().call_soon(
                lambda: asyncio.ensure_future(photon_channel._handle(answer))
            )

        patches = [
            mock.patch.object(photon_channel, "_send", side_effect=fake_send),
            mock.patch.object(photon_channel, "_proc", mock.Mock(returncode=None)),
            mock.patch.object(photon_channel, "reply"),
            mock.patch.object(photon_channel, "_typing"),
            mock.patch("services.jarvis_handoff.launch"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        photon_channel.state.update(state="ready", notify_note="")

    def tearDown(self):
        photon_channel.state.update(state="off", notify_note="")
        save_settings({"photon_owner_space": "", "photon_owner_by": "", "photon_enabled": False})
        super().tearDown()

    def texts(self):
        return [c for c in self.commands if c.get("resolve")]

    def test_a_notification_goes_into_the_dm_the_owner_texted_from(self):
        from services import notify

        asyncio.run(photon_channel.handle_message(self.message("hi")))
        res = asyncio.run(notify.send("aide finished"))
        self.assertIs(res["imessage"], True)
        self.assertEqual(self.texts()[0]["space"], "chat-1")
        self.assertEqual(self.texts()[0]["text"], "aide finished")
        self.assertTrue(notify.configured())

    def test_the_dm_survives_a_restart(self):
        from services import notify

        asyncio.run(photon_channel.handle_message(self.message("hi")))
        photon_channel._seen.clear()
        self.live.clear()  # a new helper process has seen no chat yet
        self.dedicated = True  # (so space.get / space.create can find it again)
        asyncio.run(notify.send("after restart"))
        self.assertEqual(self.texts()[0]["space"], "chat-1")
        self.assertTrue(self.texts()[0]["resolve"])  # the helper resolves an id it hasn't seen

    def test_a_group_chat_is_never_remembered_as_the_dm(self):
        record = {**self.message("hi"), "space": "any;+;group-1"}
        asyncio.run(photon_channel.handle_message(record))
        from core.settings import load_settings

        self.assertEqual(load_settings().get("photon_owner_space"), "")

    def test_a_shared_line_refusal_leaves_a_note_not_a_crash(self):
        from services import notify

        res = asyncio.run(notify.send("first"))  # the owner never texted; only a number is known
        self.assertIs(res["imessage"], False)
        self.assertEqual(self.texts()[0]["space"], "+15550100199")
        self.assertEqual(photon_channel.public()["notify_note"], "text_first")
        asyncio.run(photon_channel.handle_message(self.message("hello", message_id="m9")))
        self.assertEqual(photon_channel.state["notify_note"], "")  # texting it once clears it
        self.assertIs(asyncio.run(notify.send("second"))["imessage"], True)

    def test_only_the_owner_is_ever_texted(self):
        from services import notify

        asyncio.run(photon_channel.handle_message(self.message("hi", sender="+19998887777")))
        asyncio.run(notify.send("secret"))
        self.assertTrue(all(c["space"] != "chat-1" for c in self.texts()))
        self.assertEqual([c["space"] for c in self.texts()], ["+15550100199"])
        # a remembered chat stops counting once its number is no longer one of the owner's
        asyncio.run(photon_channel.handle_message(self.message("hi", message_id="m5")))
        save_settings({"photon_owner_handles": ["+1 (555) 010-0123"]})
        self.assertEqual(photon_channel._owner_target(), "+15550100123")

    def test_nothing_is_sent_while_photon_is_off(self):
        from services import notify

        save_settings({"photon_enabled": False})
        res = asyncio.run(notify.send("x"))
        self.assertIsNone(res["imessage"])
        self.assertEqual(self.commands, [])

    def test_the_test_route_covers_imessage(self):
        asyncio.run(photon_channel.handle_message(self.message("hi")))
        r = self.client.post("/api/notify/test")
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.json()["sent"]["imessage"], True)
