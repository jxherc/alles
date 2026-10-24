"""Edit, regenerate and retry ask again with exactly the notes and files the question first had."""

import json
from unittest import mock

from core.database import ModelEndpoint
from routes import chat
from services import incognito, vault_md
from tests._client import VaultApiTest


class ResendContextTests(VaultApiTest):
    def setUp(self):
        super().setUp()
        incognito.clear_for_tests()
        self.addCleanup(incognito.clear_for_tests)
        settings = {
            "memory_policy": "off",
            "memory_auto_inject": False,
            "auto_compact": False,
            "agent_context_files": False,
            "agent_permission_mode": "approve",
        }
        patch = mock.patch.object(chat, "load_settings", lambda: dict(settings))
        patch.start()
        self.addCleanup(patch.stop)
        with self.db() as db:
            ep = ModelEndpoint(
                name="fixture", base_url="http://127.0.0.1:1", cached_models='["fixture"]'
            )
            db.add(ep)
            db.commit()
            self.endpoint = ep.id
        self.captured = []
        self.failure = False

        async def provider(messages, *args, **kwargs):
            self.captured.append(messages)
            if self.failure:
                yield {"error": "HTTP 503: synthetic unavailable model"}
            else:
                yield {"delta": "synthetic reply"}
                yield {"done": True, "usage": {}}

        for patch in (
            mock.patch("services.chat_turn.stream_chat", provider),
            mock.patch("services.chat_turn._fire_message_hook", new_callable=mock.AsyncMock),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def session(self, private=False):
        response = self.client.post(
            "/api/sessions",
            json={
                "name": "resend",
                "model": "fixture",
                "endpoint_id": self.endpoint,
                "incognito": private,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def send(self, sid, **extra):
        return self.client.post(
            "/api/chat",
            json={"session_id": sid, "message": "what changed?", "simple": True, **extra},
        )

    def history(self, sid):
        return self.client.get(f"/api/sessions/{sid}/history").json()["messages"]

    def asked(self):
        # the newest question as the model got it
        return str([m for m in self.captured[-1] if m["role"] == "user"][-1]["content"])

    def regenerate(self, sid, **extra):
        history = self.history(sid)
        question = [m for m in history if m["role"] == "user"][-1]
        return self.send(
            sid,
            **{
                "message": question["content"],
                "regenerate_message_id": question["id"],
                "newest_id": history[-1]["id"],
                **extra,
            },
        )

    def note(self, path, content):
        written = self.client.post("/api/vault-md/file", json={"path": path, "content": content})
        self.assertEqual(written.status_code, 200, written.text)
        return self.client.get("/api/vault-md/file", params={"path": written.json()["path"]}).json()

    def scope(self, *notes):
        return {
            "kind": "vault_documents",
            "documents": [{"path": n["path"], "expected_hash": n["hash"]} for n in notes],
        }

    def upload(self, name, content):
        response = self.client.post("/api/uploads", files={"file": (name, content, "text/plain")})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def assert_refused(self, response, sid, before, code):
        # refused before the cut: the old answer stays and the model never hears of it
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], code)
        self.assertEqual(self.history(sid), before)

    def test_selected_notes_come_back_on_regenerate_and_edit(self):
        for private in (False, True):
            with self.subTest(private=private):
                scope = self.scope(self.note("plans.md", "the meeting moved to friday"))
                sid = self.session(private)
                first = self.send(sid, context_scope=scope)
                self.assertEqual(first.status_code, 200, first.text)
                self.assertIn("the meeting moved to friday", self.asked())
                # the question keeps what it was asked with, so a reload can show it too
                self.assertEqual(self.history(sid)[0]["meta"]["context_scope"], scope)

                # the tab sends no scope: the stored one is used
                again = self.regenerate(sid)
                self.assertEqual(again.status_code, 200, again.text)
                self.assertIn("the meeting moved to friday", self.asked())
                self.assertEqual(
                    self.history(sid)[-1]["meta"]["context_provenance"]["document"]["kind"],
                    "vault_documents",
                )

                # an edit keeps the notes with the new words
                history = self.history(sid)
                edited = self.send(
                    sid,
                    message="when is it now?",
                    edit_message_id=history[0]["id"],
                    newest_id=history[-1]["id"],
                )
                self.assertEqual(edited.status_code, 200, edited.text)
                self.assertIn("the meeting moved to friday", self.asked())
                self.assertIn("when is it now?", self.asked())
                self.assertEqual(self.history(sid)[0]["meta"]["context_scope"], scope)

    def test_the_tab_cannot_widen_or_swap_the_stored_notes_or_files(self):
        plans = self.note("plans.md", "the meeting moved to friday")
        other = self.note("other.md", "unrelated OTHERNOTE")
        scope = self.scope(plans)
        sid = self.session()
        self.assertEqual(self.send(sid, context_scope=scope).status_code, 200)
        before = self.history(sid)
        calls = len(self.captured)
        for sent in (
            self.scope(plans, other),
            {"kind": "vault_document", "path": other["path"], "expected_hash": other["hash"]},
        ):
            self.assert_refused(
                self.regenerate(sid, context_scope=sent), sid, before, "context_changed"
            )
        # the same scope sent back is fine; the stored one is never replaced
        self.assertEqual(self.regenerate(sid, context_scope=scope).status_code, 200)
        self.assertEqual(self.history(sid)[0]["meta"]["context_scope"], scope)
        self.assertNotIn("OTHERNOTE", json.dumps(self.captured[calls:]))

        first = self.upload("report.txt", b"FILECONTENT alpha")
        swapped = self.upload("other.txt", b"OTHERFILE beta")
        sid = self.session()
        self.assertEqual(self.send(sid, file_ids=[first]).status_code, 200)
        before = self.history(sid)
        self.assert_refused(
            self.regenerate(sid, file_ids=[swapped]), sid, before, "context_changed"
        )
        private_upload = incognito.put_upload("p.txt", "text/plain", b"PRIVATE")
        self.assert_refused(
            self.regenerate(sid, file_ids=[private_upload.id]), sid, before, "context_changed"
        )
        again = self.regenerate(sid)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertIn("FILECONTENT", self.asked())
        self.assertNotIn("OTHERFILE", json.dumps(self.captured))
        self.assertEqual(self.history(sid)[0]["meta"]["file_ids"], [first])

    def test_a_changed_note_refuses_before_anything_is_cut(self):
        note = self.note("trip.md", "flight at 9am")
        sid = self.session()
        self.assertEqual(self.send(sid, context_scope=self.scope(note)).status_code, 200)
        before = self.history(sid)
        calls = len(self.captured)
        vault_md.write(note["path"], "flight moved to 11am", expected_hash=note["hash"])
        refused = self.regenerate(sid)
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(refused.json()["code"], "document_scope_changed")
        # asked again: there's no selection to review
        self.assertEqual(
            refused.json()["detail"], "this question's note changed. ask it again as a new message."
        )
        # the old answer is still there, ready for another try
        self.assertEqual(self.history(sid), before)
        self.assertEqual(len(self.captured), calls)

    def test_a_deleted_or_private_file_refuses_with_plain_words(self):
        gone = self.upload("gone.txt", b"GONECONTENT")
        sid = self.session()
        self.assertEqual(self.send(sid, file_ids=[gone]).status_code, 200)
        before = self.history(sid)
        self.assertEqual(self.client.delete(f"/api/uploads/{gone}").status_code, 200)
        refused = self.regenerate(sid)
        self.assert_refused(refused, sid, before, "file_gone")
        self.assertEqual(
            refused.json()["detail"],
            "this question's file was deleted. ask again with it attached.",
        )
        history = self.history(sid)
        edit = self.send(
            sid,
            message="new words",
            edit_message_id=history[0]["id"],
            newest_id=history[-1]["id"],
        )
        self.assert_refused(edit, sid, before, "file_gone")

        # a private turn's file is gone once it was read: say so instead of answering without it
        sid = self.session(True)
        upload = incognito.put_upload("secret.txt", "text/plain", b"PRIVATEFILE")
        first = self.send(sid, file_ids=[upload.id], incognito=True)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertIn("PRIVATEFILE", self.asked())
        before = self.history(sid)
        self.assertEqual(before[0]["meta"]["file_ids"], [upload.id])
        self.assert_refused(self.regenerate(sid, incognito=True), sid, before, "file_gone")

    def test_a_failed_regenerate_keeps_the_answer_and_can_be_asked_again_with_its_notes(self):
        scope = self.scope(self.note("plans.md", "the meeting moved to friday"))
        sid = self.session()
        self.assertEqual(self.send(sid, context_scope=scope).status_code, 200)
        before = self.history(sid)
        self.failure = True
        failed = self.regenerate(sid)
        self.assertEqual(failed.status_code, 200, failed.text)
        self.assertIn("synthetic unavailable model", failed.text)
        # the model was down: the answer it had is still the answer, with nothing to recover
        self.assertEqual(self.history(sid), before)
        self.failure = False
        again = self.regenerate(sid)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertIn("the meeting moved to friday", self.asked())
        after = self.history(sid)
        self.assertEqual([m["role"] for m in after], ["user", "assistant"])
        self.assertEqual(after[0]["id"], before[0]["id"])
        self.assertNotEqual(after[1]["id"], before[1]["id"])

    def test_attachments_come_back_on_regenerate(self):
        upload = self.upload("brief.txt", b"synthetic attachment text")
        sid = self.session()
        first = self.send(sid, file_ids=[upload])
        self.assertEqual(first.status_code, 200, first.text)
        self.assertIn("synthetic attachment text", self.asked())
        self.assertEqual(self.history(sid)[0]["meta"]["file_ids"], [upload])
        again = self.regenerate(sid)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertIn("synthetic attachment text", self.asked())
        self.assertEqual(len([m for m in self.history(sid) if m["role"] == "user"]), 1)

    def test_a_question_asked_plainly_stays_plain(self):
        sid = self.session()
        self.assertEqual(self.send(sid).status_code, 200)
        meta = self.history(sid)[0]["meta"]
        self.assertNotIn("context_scope", meta)
        self.assertNotIn("file_ids", meta)
        again = self.regenerate(sid)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(self.asked(), "what changed?")
        self.assertEqual(self.history(sid)[0]["meta"], {})
