"""m0080 - mail keeps a message's text and html after it's read once.

mail_bodies: one row per (account, folder, uid) with the decoded text and html, the
headers the reader shows, the folder's uidvalidity and the message-id it was read with.
opening a message serves this row while its header row still matches, so a second open
or a prefetched one never waits on the mail server. rows go with their header row, and
every row of a folder goes when the server reports a new uidvalidity.

running it again changes nothing.
"""

from sqlalchemy import text

VERSION = 80
NAME = "mail_bodies"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS mail_bodies ("
            "id VARCHAR NOT NULL PRIMARY KEY, account_id VARCHAR NOT NULL, "
            "folder VARCHAR NOT NULL, uid VARCHAR NOT NULL, uidvalidity VARCHAR, "
            "message_id VARCHAR, sender TEXT, recipients TEXT, subject TEXT, date VARCHAR, "
            '"references" TEXT, has_attachment BOOLEAN, attachments TEXT, text TEXT, html TEXT, '
            "fetched_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_mail_bodies_message "
            "ON mail_bodies (account_id, folder, uid)"
        )
    )
