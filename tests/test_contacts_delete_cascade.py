"""audit fix: deleting a contact must not orphan its fields, group memberships, or links."""

from core.database import ContactField, ContactGroupMember, ContactLink
from tests._client import ApiTest


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
