from core.database import Contact
from tests._client import ApiTest

REPORT_XML = """<?xml version="1.0"?>
<multistatus xmlns="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
  <response>
    <href>/addressbooks/u/default/abc.vcf</href>
    <propstat><prop>
      <getetag>"etag-1"</getetag>
      <card:address-data>BEGIN:VCARD
VERSION:3.0
UID:remote-1
FN:Remote Person
EMAIL:remote@x.com
END:VCARD</card:address-data>
    </prop></propstat>
  </response>
  <response>
    <href>/addressbooks/u/default/def.vcf</href>
    <propstat><prop>
      <getetag>"etag-2"</getetag>
      <card:address-data>BEGIN:VCARD
VERSION:3.0
UID:remote-2
FN:Second Person
END:VCARD</card:address-data>
    </prop></propstat>
  </response>
</multistatus>"""


class FakeClient:
    """stands in for the real DAV client; records puts."""

    def __init__(self, entries):
        self._entries = entries
        self.puts = []

    def list(self):
        return self._entries

    def put(self, uid, text):
        href = f"/addressbooks/u/default/{uid}.vcf"
        self.puts.append((uid, text, href))
        self._entries.append({"href": href, "etag": '"new"', "vcard": text})
        return href


class CardDavTests(ApiTest):
    def _entries_from_report(self):
        from services import carddav_sync

        return carddav_sync.parse_report(REPORT_XML)

    def test_parse_report_extracts(self):
        entries = self._entries_from_report()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["etag"], "etag-1")
        self.assertIn("Remote Person", entries[0]["vcard"])

    def test_vcard_uid(self):
        from services import carddav_sync

        self.assertEqual(carddav_sync.vcard_uid("BEGIN:VCARD\nUID:abc-123\nEND:VCARD"), "abc-123")

    def test_build_vcard_has_fn_uid(self):
        from services import carddav_sync

        v = carddav_sync.build_vcard({"name": "Jane Q", "email": "j@x.com"}, "u-9")
        self.assertIn("FN:Jane Q", v)
        self.assertIn("UID:u-9", v)

    def test_build_vcard_round_trips_all_fields(self):
        # a pushed contact must keep title/address/birthday/website/notes — the pull side
        # (parse_vcards) reads them, so build_vcard must emit them or they're lost on sync
        from services import carddav_sync
        from services.vcard import parse_vcards

        c = {
            "name": "Ada", "email": "a@x.com", "phone": "123", "company": "Analytical",
            "title": "Countess", "address": "12 Baker St", "birthday": "1815-12-10",
            "website": "https://ada.example", "notes": "first programmer",
        }
        got = parse_vcards(carddav_sync.build_vcard(c, "u-1"))[0]
        for k in ("title", "birthday", "website", "notes"):
            self.assertEqual(got[k], c[k])
        self.assertIn("Baker St", got["address"])

    def test_sync_pull_creates(self):
        from services import carddav_sync

        client = FakeClient(self._entries_from_report())
        res = carddav_sync.sync(client=client, db=self.db())
        self.assertEqual(res["pulled"], 2)
        names = [c.name for c in self.db().query(Contact).all()]
        self.assertIn("Remote Person", names)

    def test_sync_pull_updates(self):
        from services import carddav_sync

        carddav_sync.sync(client=FakeClient(self._entries_from_report()), db=self.db())
        changed = [
            {
                "href": "/a.vcf",
                "etag": "e3",
                "vcard": "BEGIN:VCARD\nUID:remote-1\nFN:Renamed Person\nEND:VCARD",
            }
        ]
        carddav_sync.sync(client=FakeClient(changed), db=self.db())
        db = self.db()
        row = db.query(Contact).filter(Contact.carddav_uid == "remote-1").first()
        self.assertEqual(row.name, "Renamed Person")
        # not duplicated
        self.assertEqual(db.query(Contact).filter(Contact.carddav_uid == "remote-1").count(), 1)

    def test_sync_push_local_only(self):
        from services import carddav_sync

        db = self.db()
        db.add(Contact(name="Local Only", email="lo@x.com"))
        db.commit()
        client = FakeClient([])
        res = carddav_sync.sync(client=client, db=self.db())
        self.assertEqual(res["pushed"], 1)
        self.assertEqual(len(client.puts), 1)

    def test_push_sets_uid(self):
        from services import carddav_sync

        db = self.db()
        db.add(Contact(name="Local Two"))
        db.commit()
        carddav_sync.sync(client=FakeClient([]), db=self.db())
        row = self.db().query(Contact).filter(Contact.name == "Local Two").first()
        self.assertTrue(row.carddav_uid)
        self.assertTrue(row.carddav_href)

    def test_sync_idempotent(self):
        from services import carddav_sync

        carddav_sync.sync(client=FakeClient(self._entries_from_report()), db=self.db())
        carddav_sync.sync(client=FakeClient(self._entries_from_report()), db=self.db())
        n = self.db().query(Contact).filter(Contact.carddav_uid == "remote-1").count()
        self.assertEqual(n, 1)

    def test_not_configured_error(self):
        from services import carddav_sync

        res = carddav_sync.sync(db=self.db())  # no client + no config
        self.assertIn("error", res)

    def test_status_shape(self):
        from services import carddav_sync

        st = carddav_sync.status()
        for k in ("connected", "url", "username"):
            self.assertIn(k, st)
