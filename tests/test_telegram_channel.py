import asyncio
import time
from unittest import mock

from core.database import JarvisRun
from core.settings import save_settings
from services import telegram_channel
from tests._client import ApiTest

TOKEN = "123456:" + "a" * 30


class TelegramChannelTest(ApiTest):
    def setUp(self):
        super().setUp()
        telegram_channel._runs.clear()
        telegram_channel._seen.clear()
        telegram_channel._told_text_only.clear()
        telegram_channel.state.update(handled=0, ignored=0, error="")
        save_settings({"notify_telegram_token": TOKEN, "notify_telegram_chat_id": "42"})
        self.sent = []

        async def call(method, timeout=15, **params):
            self.sent.append((method, params))
            return {}

        patches = [
            mock.patch.object(telegram_channel, "_call", side_effect=call),
            mock.patch.object(telegram_channel, "restart", new=mock.AsyncMock()),
            mock.patch("services.jarvis_handoff.launch"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        save_settings(
            {
                "telegram_chat_enabled": False,
                "notify_telegram_token": "",
                "notify_telegram_chat_id": "",
            }
        )
        super().tearDown()

    def update(self, text, chat=42, message_id=1, kind="private", age=0):
        return {
            "update_id": message_id,
            "message": {
                "message_id": message_id,
                "date": int(time.time()) - age,
                "chat": {"id": chat, "type": kind},
                "text": text,
            },
        }

    def texts(self):
        return [p["text"] for m, p in self.sent if m == "sendMessage"]

    def test_only_the_owner_chat_is_answered_and_texts_become_aide_work(self):
        asyncio.run(telegram_channel.handle_update(self.update("hi", chat=7)))
        asyncio.run(telegram_channel.handle_update(self.update("hi", kind="group", message_id=2)))
        self.assertEqual(telegram_channel.state["ignored"], 2)
        with self.db() as db:
            self.assertEqual(db.query(JarvisRun).count(), 0)

        asyncio.run(telegram_channel.handle_update(self.update("what's on today?", message_id=3)))
        asyncio.run(telegram_channel.handle_update(self.update("what's on today?", message_id=3)))
        with self.db() as db:
            runs = db.query(JarvisRun).all()
            self.assertEqual(len(runs), 1)
            run_id = runs[0].id
        self.assertIn(run_id, telegram_channel._runs)
        self.assertIn(("sendChatAction", {"chat_id": "42", "action": "typing"}), self.sent)

        with self.db() as db:
            run = db.get(JarvisRun, run_id)
            run.state, run.result_summary = "succeeded", "your day is clear"
            db.commit()

        async def once():
            with mock.patch.object(telegram_channel, "POLL_SECONDS", 0):
                task = asyncio.create_task(telegram_channel._watch_runs())
                await asyncio.sleep(0.05)
                task.cancel()

        asyncio.run(once())
        self.assertEqual(self.texts()[-1], "your day is clear")
        self.assertNotIn(run_id, telegram_channel._runs)

    def test_old_messages_from_an_outage_get_no_late_answer(self):
        asyncio.run(telegram_channel.handle_update(self.update("hello?", age=3600)))
        with self.db() as db:
            self.assertEqual(db.query(JarvisRun).count(), 0)
        self.assertEqual(self.sent, [])

    def test_photos_get_one_heads_up_a_minute(self):
        for n in range(3):
            asyncio.run(telegram_channel.handle_update(self.update("", message_id=10 + n)))
        self.assertEqual(self.texts(), ["I can only read text here for now."])

    def test_long_answers_are_split_under_telegrams_limit(self):
        asyncio.run(telegram_channel.reply("42", "x" * 9000))
        self.assertEqual([len(t) for t in self.texts()], [4000, 4000, 1000])

    def test_turning_it_on_finds_the_chat_and_never_returns_the_token(self):
        save_settings({"notify_telegram_chat_id": ""})
        bad = self.client.put("/api/aide/channels/telegram", json={"enabled": True, "token": "x"})
        self.assertEqual(bad.status_code, 400)

        found = mock.Mock(status_code=200)
        found.json.return_value = {
            "ok": True,
            "result": [{"message": {"chat": {"id": 99, "type": "private", "first_name": "e"}}}],
        }
        with mock.patch("httpx.get", return_value=found):
            ok = self.client.put(
                "/api/aide/channels/telegram", json={"enabled": True, "token": TOKEN}
            )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertTrue(ok.json()["enabled"])
        self.assertNotIn(TOKEN, ok.text)
        self.assertEqual(telegram_channel.settings()["chat_id"], "99")
        status = self.client.get("/api/aide/channels/telegram").json()
        self.assertEqual((status["has_token"], status["has_chat"]), (True, True))
