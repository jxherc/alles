"""4a CRM-lite: a contact's shared calendar events (matched via event attendees)."""

from core.database import CalendarEvent, ContactField, EventAttendee
from tests._client import ApiTest


class ContactEventsTests(ApiTest):
    def _contact(self, name, email=""):
        return self.client.post("/api/contacts", json={"name": name, "email": email}).json()["id"]

    def _event(self, title, start, attendee_email="", attendee_name="", status="invited"):
        db = self.db()
        ev = CalendarEvent(title=title, start_dt=start, end_dt=start)
        db.add(ev)
        db.commit()
        eid = ev.id
        if attendee_email or attendee_name:
            db.add(EventAttendee(event_id=eid, name=attendee_name, email=attendee_email, status=status))
            db.commit()
        db.close()
        return eid

    def _events(self, cid):
        return self.client.get(f"/api/contacts/{cid}/events").json()["events"]

    def test_matches_by_email(self):
        cid = self._contact("Ann", "ann@x.com")
        self._event("Lunch", "2026-07-01T12:00:00", attendee_email="ann@x.com", status="accepted")
        out = self._events(cid)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Lunch")
        self.assertEqual(out[0]["status"], "accepted")

    def test_matches_by_email_field(self):
        cid = self._contact("Ann", "ann@home.com")
        db = self.db()
        db.add(ContactField(contact_id=cid, kind="email", value="ann@work.com"))
        db.commit()
        db.close()
        self._event("Standup", "2026-07-02T09:00:00", attendee_email="ann@work.com")
        self.assertEqual(len(self._events(cid)), 1)

    def test_name_match_only_when_invite_has_no_email(self):
        cid = self._contact("Bob Stark", "bob@x.com")
        # an invite with a DIFFERENT email but the same name = a different person, not a match
        self._event("Other", "2026-07-03T10:00:00", attendee_email="someoneelse@x.com", attendee_name="Bob Stark")
        self.assertEqual(self._events(cid), [])
        # an invite with no email but the same name = a match
        self._event("Theirs", "2026-07-04T10:00:00", attendee_name="Bob Stark")
        self.assertEqual([e["title"] for e in self._events(cid)], ["Theirs"])

    def test_sorted_by_start(self):
        cid = self._contact("Ann", "ann@x.com")
        self._event("Later", "2026-08-01T10:00:00", attendee_email="ann@x.com")
        self._event("Earlier", "2026-07-01T10:00:00", attendee_email="ann@x.com")
        self.assertEqual([e["title"] for e in self._events(cid)], ["Earlier", "Later"])

    def test_no_events(self):
        cid = self._contact("Loner", "loner@x.com")
        self.assertEqual(self._events(cid), [])

    def test_unknown_contact_404(self):
        self.assertEqual(self.client.get("/api/contacts/nope/events").status_code, 404)
