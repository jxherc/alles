"""4a - http tests for the contact relationship-graph routes, now that the UI surfaces them.
the service is covered in test_4a_depth; this locks the route contract (link/related/unlink)."""

from core.database import Contact
from tests._client import ApiTest


class ContactsGraphRoutesTests(ApiTest):
    def _contact(self, name):
        db = self.db()
        c = Contact(name=name)
        db.add(c)
        db.commit()
        cid = c.id
        db.close()
        return cid

    def _related(self, cid, kind=""):
        url = f"/api/contacts/{cid}/related" + (f"?kind={kind}" if kind else "")
        return self.client.get(url).json()["related"]

    def test_link_and_related(self):
        a, b = self._contact("Ann"), self._contact("Bob")
        r = self.client.post(f"/api/contacts/{a}/links", json={"to_id": b, "kind": "spouse"})
        self.assertEqual(r.status_code, 200)
        rel = self._related(a)
        self.assertEqual([(x["id"], x["kind"]) for x in rel], [(b, "spouse")])

    def test_reciprocal_inverse_kind(self):
        a, b = self._contact("Ann"), self._contact("Bob")
        self.client.post(f"/api/contacts/{a}/links", json={"to_id": b, "kind": "manager"})
        # bob's view of ann is "report"
        rel = self._related(b)
        self.assertEqual(rel[0]["id"], a)
        self.assertEqual(rel[0]["kind"], "report")

    def test_kind_filter(self):
        a, b, c = self._contact("Ann"), self._contact("Bob"), self._contact("Cara")
        self.client.post(f"/api/contacts/{a}/links", json={"to_id": b, "kind": "colleague"})
        self.client.post(f"/api/contacts/{a}/links", json={"to_id": c, "kind": "friend"})
        self.assertEqual(len(self._related(a)), 2)
        self.assertEqual([x["id"] for x in self._related(a, "friend")], [c])

    def test_relink_updates_kind(self):
        a, b = self._contact("Ann"), self._contact("Bob")
        self.client.post(f"/api/contacts/{a}/links", json={"to_id": b, "kind": "friend"})
        self.client.post(f"/api/contacts/{a}/links", json={"to_id": b, "kind": "spouse"})
        rel = self._related(a)
        self.assertEqual(len(rel), 1)
        self.assertEqual(rel[0]["kind"], "spouse")

    def test_unlink_removes_both_directions(self):
        a, b = self._contact("Ann"), self._contact("Bob")
        self.client.post(f"/api/contacts/{a}/links", json={"to_id": b, "kind": "spouse"})
        r = self.client.delete(f"/api/contacts/{a}/links/{b}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["removed"], 2)
        self.assertEqual(self._related(a), [])
        self.assertEqual(self._related(b), [])

    def test_link_unknown_contact_404(self):
        a = self._contact("Ann")
        r = self.client.post(f"/api/contacts/{a}/links", json={"to_id": "nope", "kind": "friend"})
        self.assertEqual(r.status_code, 404)

    def test_self_link_400(self):
        a = self._contact("Ann")
        r = self.client.post(f"/api/contacts/{a}/links", json={"to_id": a, "kind": "friend"})
        self.assertEqual(r.status_code, 400)

    def test_delete_contact_clears_edges(self):
        a, b = self._contact("Ann"), self._contact("Bob")
        self.client.post(f"/api/contacts/{a}/links", json={"to_id": b, "kind": "friend"})
        self.client.delete(f"/api/contacts/{b}")
        self.assertEqual(self._related(a), [])  # bob's deletion took the edge with it
