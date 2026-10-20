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

    def test_settings_need_an_owner_and_never_return_the_secret(self):
        bad = self.client.put(
            "/api/aide/channels/photon", json={"enabled": True, "project_id": "p"}
        )
        self.assertEqual(bad.status_code, 400)
        with mock.patch.object(photon_channel, "restart", new=mock.AsyncMock()):
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
        self.assertNotIn("s3cret-value", ok.text)
        self.assertNotIn("s3cret-value", self.client.get("/api/aide/channels/photon").text)

    def test_the_general_settings_api_never_shows_the_secret(self):
        save_settings({"photon_project_secret": "s3cret-value"})
        self.assertNotIn("s3cret-value", self.client.get("/api/settings").text)
