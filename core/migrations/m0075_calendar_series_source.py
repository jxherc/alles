"""m0075 - calendar rows remember where an .ics series came from.

source_zone: the IANA zone a repeating series was written in, when neither the owner's wall time
nor a fixed offset shows every time the way the source does (a london meeting seen from toronto).
the rule repeats in that zone and each time is read in the owner's. empty keeps the old reading.

ics_uid / ics_rid: the UID and RECURRENCE-ID an imported event had, so importing the same file
again replaces those events instead of adding every one twice. caldav_uid stays CalDAV's own.

existing rows get empty values, so they read exactly as before. running it again changes nothing.
"""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 75
NAME = "calendar_series_source"


def up(conn):
    have = {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }
    if "calendar_events" not in have:
        return
    for column in ("source_zone", "ics_uid", "ics_rid"):
        add_column(conn, "calendar_events", column, "VARCHAR")
