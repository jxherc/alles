import json

from core.database import Contact, ContactField
from tests._client import ApiTest


class ContactsGroupsTests(ApiTest):
    def _contact(self, name="Ada", **kw):
        db = self.db()
        c = Contact(name=name, **kw)
        db.add(c)
        db.commit()
        cid = c.id
        db.close()
        return cid

    def _group(self, **body):
        return self.client.post("/api/contacts/groups", json=body).json()

    def _members(self, gid):
        return self.client.get(f"/api/contacts/groups/{gid}/members").json()

    def test_create_group(self):
        g = self._group(name="Family")
        self.assertIn("id", g)
        self.assertEqual(g["name"], "Family")

    def test_manual_add_member(self):
        gid = self._group(name="Team")["id"]
        cid = self._contact("Bob")
        self.client.post(f"/api/contacts/groups/{gid}/members", json={"contact_id": cid})
        ids = [m["id"] for m in self._members(gid)]
        self.assertIn(cid, ids)

    def test_smart_group_by_tag(self):
        c1 = self._contact("Tagged", tags=json.dumps(["vip"]))
        self._contact("Untagged", tags=json.dumps(["other"]))
        gid = self._group(name="VIPs", smart=True, rule_tag="vip")["id"]
        ids = [m["id"] for m in self._members(gid)]
        self.assertEqual(ids, [c1])

    def test_smart_group_by_company(self):
        c1 = self._contact("Worker", company="Acme")
        self._contact("Other", company="Globex")
        gid = self._group(name="Acme", smart=True, rule_company="acme")["id"]
        ids = [m["id"] for m in self._members(gid)]
        self.assertEqual(ids, [c1])

    def test_delete_group(self):
        gid = self._group(name="Temp")["id"]
        self.client.delete(f"/api/contacts/groups/{gid}")
        self.assertEqual(
            len([g for g in self.client.get("/api/contacts/groups").json() if g["id"] == gid]), 0
        )

    def test_duplicates_by_name(self):
        self._contact("Jane Doe")
        self._contact("jane doe")
        dups = self.client.get("/api/contacts/duplicates").json()
        self.assertTrue(any(len(c["contacts"]) >= 2 for c in dups))

    def test_duplicates_by_email(self):
        self._contact("A", email="same@x.com")
        self._contact("B", email="same@x.com")
        dups = self.client.get("/api/contacts/duplicates").json()
        self.assertTrue(any(len(c["contacts"]) >= 2 for c in dups))

    def test_no_duplicates_empty(self):
        self._contact("Unique One", email="one@x.com")
        self._contact("Unique Two", email="two@x.com")
        self.assertEqual(self.client.get("/api/contacts/duplicates").json(), [])

    def test_duplicates_by_contactfield_email(self):
        # two contacts share an email stored as a ContactField (not the primary email
        # column) — they still cluster as duplicates
        a = self._contact("Different One")
        b = self._contact("Different Two")
        db = self.db()
        db.add(ContactField(contact_id=a, kind="email", label="work", value="shared@x.com"))
        db.add(ContactField(contact_id=b, kind="email", label="home", value="shared@x.com"))
        db.commit()
        db.close()
        dups = self.client.get("/api/contacts/duplicates").json()
        self.assertTrue(any(len(c["contacts"]) >= 2 for c in dups))

    def test_merge_combines_fields(self):
        a = self._contact("Primary", email="", tags=json.dumps(["x"]))
        b = self._contact("Other", email="b@x.com", tags=json.dumps(["y"]))
        db = self.db()
        db.add(ContactField(contact_id=b, kind="phone", label="mobile", value="555"))
        db.commit()
        db.close()
        self.client.post("/api/contacts/merge", json={"primary_id": a, "other_id": b})
        merged = next(c for c in self.client.get("/api/contacts").json() if c["id"] == a)
        self.assertEqual(merged["email"], "b@x.com")  # filled empty primary field
        self.assertIn("y", merged["tags"])  # tags unioned
        self.assertTrue(any(f["value"] == "555" for f in merged["fields"]))  # field moved

    def test_merge_deletes_other(self):
        a = self._contact("P")
        b = self._contact("O")
        self.client.post("/api/contacts/merge", json={"primary_id": a, "other_id": b})
        ids = [c["id"] for c in self.client.get("/api/contacts").json()]
        self.assertNotIn(b, ids)
        self.assertIn(a, ids)

    def test_merge_unknown_404(self):
        a = self._contact("P")
        r = self.client.post("/api/contacts/merge", json={"primary_id": a, "other_id": "nope"})
        self.assertEqual(r.status_code, 404)
