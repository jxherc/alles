"""audit fix: deleting a contact must not orphan its fields, group memberships, or links."""

from core.database import ContactField, ContactGroupMember, ContactLink
from tests._client import ApiTest


class ContactExtraTests(ApiTest):
    def test_get_single_contact(self):
        c = self.client.post("/api/contacts", json={"name": "Solo"}).json()
        r = self.client.get(f"/api/contacts/{c['id']}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "Solo")
        self.assertEqual(self.client.get("/api/contacts/nope").status_code, 404)

    def test_merge_repoints_links_away_from_deleted(self):
        a = self.client.post("/api/contacts", json={"name": "A"}).json()
        b = self.client.post("/api/contacts", json={"name": "B"}).json()
        x = self.client.post("/api/contacts", json={"name": "X"}).json()
        self.client.post(f"/api/contacts/{x['id']}/links", json={"to_id": b["id"], "kind": "colleague"})
        self.client.post("/api/contacts/merge", json={"primary_id": a["id"], "other_id": b["id"]})
        db = self.db()
        dangling = (
            db.query(ContactLink)
            .filter((ContactLink.from_id == b["id"]) | (ContactLink.to_id == b["id"]))
            .count()
        )
        db.close()
        self.assertEqual(dangling, 0)


class ContactDeleteCascadeTests(ApiTest):
    def test_delete_contact_clears_children(self):
        c = self.client.post("/api/contacts", json={"name": "Ada"}).json()
        other = self.client.post("/api/contacts", json={"name": "Bob"}).json()
        cid = c["id"]
        # a labeled field, a group membership, a relationship link
        self.client.post(f"/api/contacts/{cid}/fields", json={"kind": "email", "value": "a@x.com"})
        g = self.client.post("/api/contacts/groups", json={"name": "friends"}).json()
        self.client.post(f"/api/contacts/groups/{g['id']}/members", json={"contact_id": cid})
        self.client.post(f"/api/contacts/{cid}/links", json={"to_id": other["id"], "kind": "colleague"})

        db = self.db()
        assert db.query(ContactField).filter_by(contact_id=cid).count() >= 1
        db.close()

        self.assertEqual(self.client.delete(f"/api/contacts/{cid}").status_code, 200)

        db = self.db()
        self.assertEqual(db.query(ContactField).filter_by(contact_id=cid).count(), 0)
        self.assertEqual(db.query(ContactGroupMember).filter_by(contact_id=cid).count(), 0)
        n_links = (
            db.query(ContactLink)
            .filter((ContactLink.from_id == cid) | (ContactLink.to_id == cid))
            .count()
        )
        self.assertEqual(n_links, 0)
        db.close()
