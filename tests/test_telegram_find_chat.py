from unittest import mock

from core.settings import save_settings
from tests._client import ApiTest

TOKEN = "123456:" + "a" * 30


class Reply:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload


class TelegramFindChatTests(ApiTest):
    def find(self, reply, token=TOKEN):
        with mock.patch("httpx.get", return_value=reply) as get:
            response = self.client.post("/api/settings/telegram/find-chat", json={"token": token})
        return response, get

    def test_returns_the_newest_private_chat(self):
        updates = {
            "ok": True,
            "result": [
                {"message": {"chat": {"id": 11, "type": "private", "first_name": "old"}}},
                {"message": {"chat": {"id": -5, "type": "group", "title": "a group"}}},
                {"message": {"chat": {"id": 42, "type": "private", "first_name": "eric"}}},
                "not an update",
            ],
        }
        response, get = self.find(Reply(updates))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"chat_id": "42", "name": "eric"})
        self.assertIn(f"/bot{TOKEN}/getUpdates", get.call_args.args[0])

    def test_uses_the_saved_token_when_none_is_typed(self):
        save_settings({"notify_telegram_token": TOKEN})
        response, get = self.find(
            Reply({"result": [{"message": {"chat": {"id": 7, "type": "private"}}}]}), token=""
        )
        self.assertEqual(response.json()["chat_id"], "7")
        self.assertIn(TOKEN, get.call_args.args[0])

    def test_explains_each_way_it_can_fail(self):
        response, get = self.find(Reply({}), token="not a token")
        self.assertEqual(response.json()["code"], "telegram_token_missing")
        get.assert_not_called()
        response, _ = self.find(Reply({"ok": False}, status=401))
        self.assertEqual(response.json()["code"], "telegram_token_invalid")
        response, _ = self.find(Reply({"ok": True, "result": []}))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "telegram_no_message")
        with mock.patch("httpx.get", side_effect=OSError("offline")):
            response = self.client.post("/api/settings/telegram/find-chat", json={"token": TOKEN})
        self.assertEqual(response.json()["code"], "telegram_unreachable")
