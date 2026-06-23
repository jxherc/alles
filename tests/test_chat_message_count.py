"""a normal chat turn saves a user + an assistant message, so message_count
must advance by 2 (it used to bump by 1 and drift behind the real row count)."""

import asyncio
from unittest import mock

from core.database import Message, ModelEndpoint, Session
from routes import chat as chat_mod
from tests._client import ApiTest


def _fake_stream(text):
    async def gen(messages, base_url, api_key, model, **kw):
        yield {"delta": text}
        yield {"done": True, "usage": {}}

    return gen


async def _drive(**kw):
    stop = asyncio.Event()
    async for _ in chat_mod._stream_and_save(stop_event=stop, **kw):
        pass


class MessageCountTests(ApiTest):
    def _seed(self):
        d = self.db()
        ep = ModelEndpoint(name="e", base_url="http://x", api_key="")
        d.add(ep)
        d.flush()
        s = Session(name="c", model="m", endpoint_id=ep.id)
        d.add(s)
        d.commit()
        sid, epid = s.id, ep.id
        d.close()
        return sid, epid

    def test_one_turn_counts_two_messages(self):
        sid, epid = self._seed()
        ep = self.db().get(ModelEndpoint, epid)
        with mock.patch.object(chat_mod, "stream_chat", _fake_stream("hello")):
            asyncio.run(_drive(
                session_id=sid, user_text="hi", messages=[{"role": "user", "content": "hi"}],
                ep=ep, model="m", db_factory=self.db,
            ))
        d = self.db()
        s = d.get(Session, sid)
        msgs = d.query(Message).filter(Message.session_id == sid).all()
        self.assertEqual(len(msgs), 2)            # user + assistant rows
        self.assertEqual(s.message_count, 2)      # count matches the rows

    def test_errored_turn_counts_only_user(self):
        # model returns nothing -> only the user message is saved, count == 1
        sid, epid = self._seed()
        ep = self.db().get(ModelEndpoint, epid)

        async def empty(messages, base_url, api_key, model, **kw):
            yield {"error": "boom"}

        with mock.patch.object(chat_mod, "stream_chat", empty):
            asyncio.run(_drive(
                session_id=sid, user_text="hi", messages=[{"role": "user", "content": "hi"}],
                ep=ep, model="m", db_factory=self.db,
            ))
        d = self.db()
        s = d.get(Session, sid)
        msgs = d.query(Message).filter(Message.session_id == sid).all()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(s.message_count, 1)
