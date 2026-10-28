import json
from unittest import mock

from core.database import ModelEndpoint
from tests._client import ApiTest


class MailDigestTest(ApiTest):
    def setUp(self):
        super().setUp()
        with self.db() as db:
            db.add(
                ModelEndpoint(
                    name="digest test",
                    base_url="http://127.0.0.1:9/v1",
                    api_key="",
                    cached_models=json.dumps(["small"]),
                    enabled=True,
                )
            )
            db.commit()

    def test_unread_digest_is_one_overview_and_a_single_mail_keeps_its_bullets(self):
        seen = []

        async def fake(prompt, *args, **kwargs):
            seen.append((prompt, kwargs.get("max_tokens")))
            return "reply to sam about friday. two newsletters."

        unread = "\n\n".join(f"from: s{i}\nsubject: thing {i}\npreview: hello" for i in range(30))
        with mock.patch("services.llm.simple_complete", new=fake):
            digest = self.client.post(
                "/api/mail/summarize", json={"kind": "digest", "body": unread}
            )
            single = self.client.post("/api/mail/summarize", json={"subject": "hi", "body": "x"})
        self.assertEqual(digest.status_code, 200, digest.text)
        self.assertEqual(digest.json()["summary"], "reply to sam about friday. two newsletters.")
        (digest_prompt, digest_tokens), (single_prompt, _) = seen
        self.assertIn("unread emails", digest_prompt[0]["content"])
        self.assertIn("thing 29", digest_prompt[1]["content"])
        self.assertEqual(digest_tokens, 600)
        self.assertIn("bullet points", single_prompt[0]["content"])
        self.assertEqual(single.status_code, 200)

    def test_unknown_kind_is_refused(self):
        response = self.client.post("/api/mail/summarize", json={"kind": "novel", "body": "x"})
        self.assertEqual(response.status_code, 422)
