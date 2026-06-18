from core.database import Message, Session
from tests._client import ApiTest


class SessionForkTests(ApiTest):
    def _make_session(self, n_msgs=4, **kw):
        d = self.db()
        s = Session(name="orig", model="m1", endpoint_id=None, mode="chat", **kw)
        d.add(s)
        d.flush()
        ids = []
        for i in range(n_msgs):
            role = "user" if i % 2 == 0 else "assistant"
            m = Message(session_id=s.id, role=role, content=f"msg{i}", meta='{"i": %d}' % i)
            d.add(m)
            d.flush()
            ids.append(m.id)
        s.message_count = n_msgs
        d.commit()
        sid = s.id
        d.close()
        return sid, ids

    def _fork(self, sid, msg_id):
        return self.client.post(f"/api/sessions/{sid}/fork", json={"msg_id": msg_id})

    def test_fork_returns_new_session(self):
        sid, ids = self._make_session()
        r = self._fork(sid, ids[1])
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.json()["id"], sid)

    def test_fork_copies_up_to_and_including(self):
        sid, ids = self._make_session()
        new = self._fork(sid, ids[1]).json()
        hist = self.client.get(f"/api/sessions/{new['id']}/history").json()["messages"]
        self.assertEqual([m["content"] for m in hist], ["msg0", "msg1"])

    def test_fork_excludes_later_messages(self):
        sid, ids = self._make_session()
        new = self._fork(sid, ids[1]).json()
        hist = self.client.get(f"/api/sessions/{new['id']}/history").json()["messages"]
        self.assertNotIn("msg2", [m["content"] for m in hist])
        self.assertNotIn("msg3", [m["content"] for m in hist])

    def test_original_untouched(self):
        sid, ids = self._make_session()
        self._fork(sid, ids[1])
        hist = self.client.get(f"/api/sessions/{sid}/history").json()["messages"]
        self.assertEqual(len(hist), 4)

    def test_fork_preserves_roles(self):
        sid, ids = self._make_session()
        new = self._fork(sid, ids[2]).json()
        hist = self.client.get(f"/api/sessions/{new['id']}/history").json()["messages"]
        self.assertEqual([m["role"] for m in hist], ["user", "assistant", "user"])

    def test_fork_preserves_meta(self):
        sid, ids = self._make_session()
        new = self._fork(sid, ids[0]).json()
        hist = self.client.get(f"/api/sessions/{new['id']}/history").json()["messages"]
        self.assertEqual(hist[0]["meta"], {"i": 0})

    def test_fork_inherits_model_and_mode(self):
        sid, ids = self._make_session()
        new = self._fork(sid, ids[1]).json()
        self.assertEqual(new["model"], "m1")
        self.assertEqual(new["mode"], "chat")

    def test_fork_message_count(self):
        sid, ids = self._make_session()
        new = self._fork(sid, ids[2]).json()
        self.assertEqual(new["message_count"], 3)

    def test_fork_copies_are_new_rows(self):
        sid, ids = self._make_session()
        new = self._fork(sid, ids[1]).json()
        d = self.db()
        new_ids = {m.id for m in d.query(Message).filter(Message.session_id == new["id"]).all()}
        d.close()
        self.assertTrue(new_ids.isdisjoint(set(ids)))  # fresh message ids

    def test_fork_unknown_session_404(self):
        sid, ids = self._make_session()
        self.assertEqual(self._fork("nope", ids[0]).status_code, 404)

    def test_fork_unknown_message_404(self):
        sid, ids = self._make_session()
        self.assertEqual(self._fork(sid, "nope").status_code, 404)

    def test_fork_message_from_other_session_404(self):
        sid1, ids1 = self._make_session()
        sid2, ids2 = self._make_session()
        # msg from session2 can't fork session1
        self.assertEqual(self._fork(sid1, ids2[0]).status_code, 404)

    def test_fork_name_marks_branch(self):
        sid, ids = self._make_session()
        new = self._fork(sid, ids[1]).json()
        self.assertIn("orig", new["name"])
