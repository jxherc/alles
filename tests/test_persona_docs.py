from core.database import Persona
from services import persona_docs as pd
from services import textindex
from tests._client import ApiTest


class PersonaDocsServiceTests(ApiTest):
    def _persona(self, name="Helper"):
        d = self.db()
        p = Persona(name=name)
        d.add(p)
        d.commit()
        d.refresh(p)
        pid = p.id
        d.close()
        return pid

    def test_attach_creates_and_indexes(self):
        pid = self._persona()
        d = self.db()
        pd.attach(d, pid, "OAuth notes", "login uses oauth2 with refresh tokens and pkce")
        self.assertEqual(len(pd.list_docs(d, pid)), 1)
        self.assertGreater(textindex.stats(d).get(f"persona:{pid}", 0), 0)
        d.close()

    def test_list_docs(self):
        pid = self._persona()
        d = self.db()
        pd.attach(d, pid, "A", "alpha content here")
        pd.attach(d, pid, "B", "beta content here")
        titles = {x.title for x in pd.list_docs(d, pid)}
        self.assertEqual(titles, {"A", "B"})
        d.close()

    def test_knowledge_block_matches(self):
        pid = self._persona()
        d = self.db()
        pd.attach(d, pid, "OAuth", "the login flow uses oauth2 and pkce for the handshake")
        block = pd.knowledge_block(d, pid, "how does oauth login work")
        d.close()
        self.assertIn("oauth", block.lower())

    def test_knowledge_block_empty_no_docs(self):
        pid = self._persona()
        d = self.db()
        self.assertEqual(pd.knowledge_block(d, pid, "anything"), "")
        d.close()

    def test_knowledge_block_empty_no_match(self):
        pid = self._persona()
        d = self.db()
        pd.attach(d, pid, "Cooking", "to bake bread you knead flour water yeast salt")
        block = pd.knowledge_block(d, pid, "quantum chromodynamics gluon")
        d.close()
        self.assertEqual(block, "")

    def test_detach_removes_doc_and_chunks(self):
        pid = self._persona()
        d = self.db()
        doc = pd.attach(d, pid, "Tmp", "some indexed content about widgets")
        self.assertTrue(pd.detach(d, pid, doc.id))
        self.assertEqual(len(pd.list_docs(d, pid)), 0)
        self.assertEqual(textindex.stats(d).get(f"persona:{pid}", 0), 0)
        d.close()

    def test_cross_persona_isolation(self):
        a = self._persona("A")
        b = self._persona("B")
        d = self.db()
        pd.attach(d, a, "Secret", "the launch code is hunter2 oauth widget")
        self.assertEqual(pd.knowledge_block(d, b, "launch code oauth widget"), "")
        d.close()

    def test_purge_clears(self):
        pid = self._persona()
        d = self.db()
        pd.attach(d, pid, "1", "one content")
        pd.attach(d, pid, "2", "two content")
        pd.purge(d, pid)
        self.assertEqual(len(pd.list_docs(d, pid)), 0)
        self.assertEqual(textindex.stats(d).get(f"persona:{pid}", 0), 0)
        d.close()


class PersonaDocsApiTests(ApiTest):
    def _persona(self, name="Helper"):
        return self.client.post("/api/personas", json={"name": name}).json()["id"]

    def test_api_attach_list_detach(self):
        pid = self._persona()
        r = self.client.post(
            f"/api/personas/{pid}/docs", json={"title": "Doc", "content": "indexed body text"}
        )
        self.assertEqual(r.status_code, 200)
        docs = self.client.get(f"/api/personas/{pid}/docs").json()
        self.assertEqual(len(docs), 1)
        did = docs[0]["id"]
        self.assertEqual(self.client.delete(f"/api/personas/{pid}/docs/{did}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/personas/{pid}/docs").json(), [])

    def test_delete_persona_purges_docs(self):
        pid = self._persona()
        self.client.post(f"/api/personas/{pid}/docs", json={"title": "D", "content": "body"})
        self.client.delete(f"/api/personas/{pid}")
        d = self.db()
        self.assertEqual(textindex.stats(d).get(f"persona:{pid}", 0), 0)
        from core.database import PersonaDoc

        self.assertEqual(d.query(PersonaDoc).filter(PersonaDoc.persona_id == pid).count(), 0)
        d.close()
