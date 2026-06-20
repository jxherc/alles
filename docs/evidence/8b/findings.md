# 8b — calendar: invites & booking — findings

Audited by running an isolated server (`ALLES_DATA=/tmp/alles8b PORT=8865`) with curl + Playwright.

## Audit — state before the build
- Events had only a freeform `guests` text field — no structured attendees, no RSVP, no video link.
- `services/mail.send_mail` exists (SMTP) so invite email is possible (best-effort; mocked in tests).
- `share.VALID_KINDS` includes `event` but `/s/{token}` didn't render it; no RSVP/booking pages.
- `/calendar/free` already computes open slots (reused for booking availability).

## Built (gaps only)
- **8b-1 invites + RSVP + video** (`core/database.py`, `routes/calendar.py`, `routes/shared.py`,
  `services/meet.py`): `EventAttendee` model + `CalendarEvent.meeting_url`; `POST /calendar/{eid}/invite`
  (best-effort email, never fails the create), `GET /calendar/{eid}/attendees`,
  `DELETE /calendar/attendees/{aid}`, `POST /calendar/{eid}/meeting-link` (Jitsi room); public
  `GET/POST /rsvp/{token}` (a small RSVP page + status set). `services/meet.jitsi_url` mints a room.
- **8b-2 booking pages** (`core/database.py`, `routes/calendar.py`, `routes/shared.py`): `BookingPage`
  model + CRUD; `compute_booking_slots` steps the free windows into discrete slots; public
  `GET /book/{token}` (slot picker page), `GET /book/{token}/slots`, `POST /book/{token}` → creates an
  event (default duration) + an accepted attendee; rejects taken slots with 409.
- **8b-3 frontend** (`static/js/calendar.js`, `index.html`, `style.css`): event editor gains a video-call
  link + "add" generator, and an invites/RSVP list (add by name/email, per-person status badge, remove);
  sidebar gains a booking-page manager (create → copy public link → delete). Stamps → v65 / SW v39.

## Exercised with real input
- Invites: create attendee, token minted, list, delete, RSVP sets status, unknown 404, bad status 400,
  meeting_url roundtrip, jitsi url shape, best-effort email (unit `test_calendar_invites`, 12/12).
- Booking: create page, slots exclude busy + respect work hours, book creates event with the right
  duration + an accepted attendee, unknown token 404, taken slot 409, delete (unit `test_booking`, 10/10).
- UI (Playwright `pw_calendar_invites_8b`, 8/8): video button fills the link, invite adds an attendee with
  a status badge, public RSVP flips the status, booking page created + listed, public page lists 30-min
  slots and a booking creates an event. Screenshots `event-invites.png`, `booking-page.png`.

## Bugs / imperfections found
- **App bugs: none.** Test-only fixes: open the agenda event by `data-id` (prior-run events accumulate on a
  shared dev DB) and reload after seeding so the in-memory event list includes it.

## Evidence
`pw_calendar_invites_8b.txt` (8/8), `event-invites.png`, `booking-page.png`. Unit: 22 tests across two files.
