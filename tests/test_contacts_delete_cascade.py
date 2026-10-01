"""audit fix: deleting a contact must not orphan its fields, group memberships, or links."""

import tempfile
from pathlib import Path
from unittest import mock

from core.database import ContactField, ContactGroupMember, ContactLink
from routes import contacts as contacts_route
from tests._client import ApiTest


class ContactExtraTests(ApiTest):
    def _upload_avatar(self, cid, name, data=b"img"):
        return self.client.post(
            f"/api/contacts/{cid}/avatar",
            files={"file": (name, data, "image/png")},
        )

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
        self.client.post(
            f"/api/contacts/{x['id']}/links", json={"to_id": b["id"], "kind": "colleague"}
        )
        self.client.post("/api/contacts/merge", json={"primary_id": a["id"], "other_id": b["id"]})
        db = self.db()
        dangling = (
            db.query(ContactLink)
            .filter((ContactLink.from_id == b["id"]) | (ContactLink.to_id == b["id"]))
            .count()
        )
        db.close()
        self.assertEqual(dangling, 0)

    def test_merge_removes_secondary_avatar_when_primary_has_one(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(contacts_route, "_avatar_dir", lambda: Path(tmp)),
        ):
            a = self.client.post("/api/contacts", json={"name": "A"}).json()
            b = self.client.post("/api/contacts", json={"name": "B"}).json()
            av = self._upload_avatar(a["id"], "a.png", b"a").json()["avatar"]
            bv = self._upload_avatar(b["id"], "b.jpg", b"b").json()["avatar"]

            r = self.client.post(
                "/api/contacts/merge", json={"primary_id": a["id"], "other_id": b["id"]}
            )

            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["avatar"], av)
            self.assertTrue((Path(tmp) / av).exists())
            self.assertFalse((Path(tmp) / bv).exists())

    def test_merge_keeps_secondary_avatar_when_primary_has_none(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(contacts_route, "_avatar_dir", lambda: Path(tmp)),
        ):
            a = self.client.post("/api/contacts", json={"name": "A"}).json()
            b = self.client.post("/api/contacts", json={"name": "B"}).json()
            bv = self._upload_avatar(b["id"], "b.jpg", b"b").json()["avatar"]

            r = self.client.post(
                "/api/contacts/merge", json={"primary_id": a["id"], "other_id": b["id"]}
            )

            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["avatar"], bv)
            self.assertTrue((Path(tmp) / bv).exists())
            self.assertEqual(self.client.get(f"/api/contacts/{a['id']}/avatar").status_code, 200)


class ContactDeleteCascadeTests(ApiTest):
    def test_delete_contact_clears_children(self):
        c = self.client.post("/api/contacts", json={"name": "Ada"}).json()
        other = self.client.post("/api/contacts", json={"name": "Bob"}).json()
        cid = c["id"]
        # a labeled field, a group membership, a relationship link
        self.client.post(f"/api/contacts/{cid}/fields", json={"kind": "email", "value": "a@x.com"})
        g = self.client.post("/api/contacts/groups", json={"name": "friends"}).json()
        self.client.post(f"/api/contacts/groups/{g['id']}/members", json={"contact_id": cid})
        self.client.post(
            f"/api/contacts/{cid}/links", json={"to_id": other["id"], "kind": "colleague"}
        )

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
