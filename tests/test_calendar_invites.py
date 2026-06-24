from unittest import mock

from core.database import CalendarEvent, EventAttendee
from tests._client import ApiTest


class CalendarInvitesTests(ApiTest):
    def _event(self, title="Launch", start="2026-07-01T10:00:00"):
        db = self.db()
        e = CalendarEvent(title=title, start_dt=start, end_dt="2026-07-01T11:00:00")
        db.add(e)
        db.commit()
        eid = e.id
        db.close()
        return eid

    def _invite(self, eid, name="Sam", email="sam@example.com"):
        # email send is best-effort; stub it so tests never touch SMTP
        with mock.patch("routes.calendar._send_invite_email", return_value=False):
            return self.client.post(
                f"/api/calendar/{eid}/invite", json={"name": name, "email": email}
            )

    def test_invite_creates_attendee(self):
        eid = self._event()
        r = self._invite(eid)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "Sam")

    def test_attendee_has_token(self):
        eid = self._event()
        self.assertTrue(self._invite(eid).json()["token"])

    def test_list_attendees(self):
        eid = self._event()
        self._invite(eid, "A", "a@x.com")
        self._invite(eid, "B", "b@x.com")
        lst = self.client.get(f"/api/calendar/{eid}/attendees").json()
        self.assertEqual(len(lst), 2)

    def test_rsvp_sets_status(self):
        eid = self._event()
        tok = self._invite(eid).json()["token"]
        r = self.client.post(f"/rsvp/{tok}", json={"status": "accepted"})
        self.assertEqual(r.status_code, 200)
        db = self.db()
        a = db.query(EventAttendee).filter_by(token=tok).first()
        self.assertEqual(a.status, "accepted")
        db.close()

    def test_rsvp_unknown_404(self):
        self.assertEqual(
            self.client.post("/rsvp/nope", json={"status": "accepted"}).status_code, 404
        )

    def test_rsvp_bad_status_400(self):
        eid = self._event()
        tok = self._invite(eid).json()["token"]
        self.assertEqual(
            self.client.post(f"/rsvp/{tok}", json={"status": "maybe-ish"}).status_code, 400
        )

    def test_delete_attendee(self):
        eid = self._event()
        aid = self._invite(eid).json()["id"]
        self.client.delete(f"/api/calendar/attendees/{aid}")
        self.assertEqual(len(self.client.get(f"/api/calendar/{eid}/attendees").json()), 0)

    def test_meeting_url_roundtrip(self):
        r = self.client.post(
            "/api/calendar",
            json={
                "title": "Sync",
                "start_dt": "2026-07-02T09:00:00",
                "meeting_url": "https://meet.example/x",
            },
        ).json()
        self.assertEqual(r["meeting_url"], "https://meet.example/x")

    def test_jitsi_url_shape(self):
        from services.meet import jitsi_url

        u = jitsi_url("Project Sync")
        self.assertTrue(u.startswith("https://meet.jit.si/"))
        self.assertNotIn(" ", u)

    def test_fmt_has_meeting_url(self):
        r = self.client.post(
            "/api/calendar", json={"title": "x", "start_dt": "2026-07-03T09:00:00"}
        ).json()
        self.assertIn("meeting_url", r)

    def test_invite_email_best_effort(self):
        # even if sending raises, the invite still succeeds (best-effort)
        eid = self._event()
        with mock.patch("routes.calendar._send_invite_email", side_effect=RuntimeError("no smtp")):
            r = self.client.post(
                f"/api/calendar/{eid}/invite", json={"name": "Z", "email": "z@x.com"}
            )
        self.assertEqual(r.status_code, 200)

    def test_rsvp_rtentative_ok(self):
        eid = self._event()
        tok = self._invite(eid).json()["token"]
        self.assertEqual(
            self.client.post(f"/rsvp/{tok}", json={"status": "tentative"}).status_code, 200
        )

    # ── 4a smart-invite suggestions ─────────────────────────────────────────
    def _contact(self, name, email=""):
        return self.client.post("/api/contacts", json={"name": name, "email": email}).json()["id"]

    def _link(self, a, b, kind):
        self.client.post(f"/api/contacts/{a}/links", json={"to_id": b, "kind": kind})

    def _suggest(self, eid):
        return self.client.get(f"/api/calendar/{eid}/invite-suggestions").json()["suggestions"]

    def test_suggests_contact_linked_to_an_invitee(self):
        eid = self._event()
        ann = self._contact("Ann", "ann@x.com")
        bob = self._contact("Bob", "bob@x.com")
        self._link(ann, bob, "spouse")
        self._invite(eid, "Ann", "ann@x.com")  # matched to the Ann contact by email
        sugg = self._suggest(eid)
        self.assertEqual([(s["name"], s["kind"]) for s in sugg], [("Bob", "spouse")])

    def test_suggestion_excludes_already_invited(self):
        eid = self._event()
        ann = self._contact("Ann", "ann@x.com")
        bob = self._contact("Bob", "bob@x.com")
        self._link(ann, bob, "colleague")
        self._invite(eid, "Ann", "ann@x.com")
        self._invite(eid, "Bob", "bob@x.com")  # bob is already on the event
        self.assertEqual(self._suggest(eid), [])

    def test_no_suggestions_when_invitee_unknown(self):
        eid = self._event()
        self._invite(eid, "Stranger", "stranger@nowhere.com")  # not a contact
        self.assertEqual(self._suggest(eid), [])

    def test_suggestion_matches_invitee_by_name(self):
        eid = self._event()
        ann = self._contact("Ann Smith")  # no email on file
        cara = self._contact("Cara", "cara@x.com")
        self._link(ann, cara, "friend")
        self._invite(eid, "Ann Smith", "")  # matched by name
        self.assertEqual([s["name"] for s in self._suggest(eid)], ["Cara"])

    def test_invite_suggestions_unknown_event_404(self):
        self.assertEqual(self.client.get("/api/calendar/nope/invite-suggestions").status_code, 404)
