"""stored mail bodies (27.34): an opened or prefetched message opens from the database, and a
stored body never outlives its message on the server."""

from unittest import mock

from sqlalchemy import create_engine, inspect, text

from core.database import MailAccount, MailBody
from core.migrations import m0080_mail_bodies
from routes import mail as mail_routes
from services import mail as mailsvc
from services import mail_cache
from tests._client import ApiTest


def _listed(uid, mid, validity="7"):
    return {
        "uid": uid,
        "from": "Maya <maya@friends.test>",
        "subject": f"notes {uid}",
        "date": "Mon, 02 Nov 2026 09:00:00 -0500",
        "date_ts": 1000 + int(uid),
        "message_id": mid,
        "uidvalidity": validity,
    }


def _read(uid, mid, validity="7", **extra):
    return {
        "uid": uid,
        "from": "Maya <maya@friends.test>",
        "to": "eric@home.test",
        "subject": f"notes {uid}",
        "date": "Mon, 02 Nov 2026 09:00:00 -0500",
        "message_id": mid,
        "references": "",
        "has_attachment": False,
        "text": f"body of {uid}",
        "html": f"<p>body of {uid}</p>",
        "uidvalidity": validity,
    } | extra


class StoredBodyTest(ApiTest):
    def setUp(self):
        super().setUp()
        with self.db() as d:
            a = MailAccount(name="home", email="eric@home.test", imap_host="127.0.0.1", imap_port=1)
            d.add(a)
            d.commit()
            self.aid = a.id
            mail_cache.save(d, self.aid, "INBOX", [_listed("11", "<a@x>"), _listed("12", "<b@x>")])

    def bodies(self):
        with self.db() as d:
            return {row.uid: row.message_id for row in d.query(MailBody).all()}

    def test_a_listed_message_is_kept_and_served(self):
        with self.db() as d:
            self.assertTrue(mail_cache.keep_body(d, self.aid, "INBOX", _read("11", "<a@x>")))
            got = mail_cache.stored_body(d, self.aid, "INBOX", "11")
        self.assertEqual(got["text"], "body of 11")
        self.assertEqual(got["html"], "<p>body of 11</p>")
        self.assertEqual(got["uid"], "11")
        self.assertTrue(got["stored"])

    def test_an_unlisted_or_different_message_is_not_kept(self):
        with self.db() as d:
            self.assertFalse(mail_cache.keep_body(d, self.aid, "INBOX", _read("99", "<z@x>")))
            self.assertFalse(mail_cache.keep_body(d, self.aid, "INBOX", _read("11", "<other@x>")))
            self.assertFalse(mail_cache.keep_body(d, self.aid, "Archive", _read("11", "<a@x>")))
            self.assertFalse(
                mail_cache.keep_body(d, self.aid, "INBOX", {"uid": "11", "error": "gone"})
            )
        self.assertEqual(self.bodies(), {})

    def test_a_reused_uid_is_not_served_the_old_body(self):
        with self.db() as d:
            mail_cache.keep_body(d, self.aid, "INBOX", _read("11", "<a@x>"))
            # the server handed uid 11 to another message (same uidvalidity, so no prune)
            mail_cache.save(
                d, self.aid, "INBOX", [_listed("11", "<new@x>"), _listed("12", "<b@x>")]
            )
            self.assertIsNone(mail_cache.stored_body(d, self.aid, "INBOX", "11"))
        self.assertEqual(self.bodies(), {})

    def test_a_message_gone_from_the_server_drops_its_body(self):
        with self.db() as d:
            mail_cache.keep_body(d, self.aid, "INBOX", _read("11", "<a@x>"))
            mail_cache.keep_body(d, self.aid, "INBOX", _read("12", "<b@x>"))
            mail_cache.save(d, self.aid, "INBOX", [_listed("12", "<b@x>")])
        self.assertEqual(self.bodies(), {"12": "<b@x>"})

    def test_a_new_uidvalidity_drops_every_body_in_the_folder(self):
        with self.db() as d:
            mail_cache.keep_body(d, self.aid, "INBOX", _read("11", "<a@x>"))
            mail_cache.keep_body(d, self.aid, "INBOX", _read("12", "<b@x>"))
            mail_cache.save(
                d, self.aid, "INBOX", [_listed("11", "<a@x>", "8"), _listed("12", "<b@x>", "8")]
            )
        self.assertEqual(self.bodies(), {})

    def test_archive_and_account_removal_drop_bodies(self):
        with self.db() as d:
            mail_cache.keep_body(d, self.aid, "INBOX", _read("11", "<a@x>"))
            mail_cache.keep_body(d, self.aid, "INBOX", _read("12", "<b@x>"))
            mail_cache.archive(d, self.aid, "INBOX", "11")
        self.assertEqual(self.bodies(), {"12": "<b@x>"})
        self.assertEqual(self.client.delete(f"/api/mail/accounts/{self.aid}").status_code, 200)
        self.assertEqual(self.bodies(), {})

    def test_opening_twice_asks_the_server_once(self):
        url = f"/api/mail/message/{self.aid}?uid=11&folder=INBOX"
        with mock.patch.object(mailsvc, "fetch_message", return_value=_read("11", "<a@x>")) as live:
            first = self.client.get(url).json()
            second = self.client.get(url).json()
        live.assert_called_once()
        self.assertEqual(first["text"], "body of 11")
        self.assertEqual(second["text"], "body of 11")
        self.assertTrue(second["stored"])

    def test_a_failed_read_is_not_kept(self):
        url = f"/api/mail/message/{self.aid}?uid=11&folder=INBOX"
        with mock.patch.object(mailsvc, "fetch_message", side_effect=OSError("timed out")):
            self.assertIn("error", self.client.get(url).json())
        self.assertEqual(self.bodies(), {})

    def test_attachments_answer_from_the_stored_body(self):
        with self.db() as d:
            mail_cache.keep_body(d, self.aid, "INBOX", _read("11", "<a@x>"))
            mail_cache.keep_body(d, self.aid, "INBOX", _read("12", "<b@x>", has_attachment=True))
        found = [
            {"index": 3, "filename": "notes.pdf", "content_type": "application/pdf", "size": 9}
        ]
        with mock.patch.object(mailsvc, "list_attachments", return_value=found) as live:
            none = self.client.get(f"/api/mail/attachments/{self.aid}?uid=11").json()
            first = self.client.get(f"/api/mail/attachments/{self.aid}?uid=12").json()
            again = self.client.get(f"/api/mail/attachments/{self.aid}?uid=12").json()
        self.assertEqual(none, {"attachments": []})
        self.assertEqual(first, {"attachments": found})
        self.assertEqual(again, {"attachments": found})
        live.assert_called_once()

    def test_prefetch_reads_only_what_is_missing(self):
        with self.db() as d:
            mail_cache.keep_body(d, self.aid, "INBOX", _read("12", "<b@x>"))
        acct = {"imap_host": "127.0.0.1"}
        with mock.patch.object(
            mailsvc, "fetch_bodies", return_value=[_read("11", "<a@x>")]
        ) as live:
            mail_routes._prefetch_bodies(acct, self.aid, "INBOX")
        self.assertEqual(live.call_args.args[1], ["11"])
        self.assertEqual(self.bodies(), {"11": "<a@x>", "12": "<b@x>"})
        with mock.patch.object(mailsvc, "fetch_bodies") as live:
            mail_routes._prefetch_bodies(acct, self.aid, "INBOX")
        live.assert_not_called()


class FetchParsingTest(ApiTest):
    def test_a_multi_message_fetch_splits_per_message(self):
        # the shapes imaplib hands back: the bodystructure before or after the literal
        data = [
            (
                b'4 (UID 11 BODYSTRUCTURE ("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "7BIT" 5 1) '
                b"BODY[HEADER] {20}",
                b"Subject: one\r\n\r\n",
            ),
            b")",
            (b"5 (UID 12 BODY[HEADER] {20}", b"Subject: two\r\n\r\n"),
            b' BODYSTRUCTURE (("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "7BIT" 5 1)'
            b'("TEXT" "HTML" ("CHARSET" "utf-8") NIL NIL "7BIT" 9 1) "ALTERNATIVE"))',
            b"6 (UID 13 FLAGS (\\Seen))",
        ]
        got = mailsvc._group_fetch(data)
        self.assertEqual(len(got), 3)
        self.assertIn("UID 11", got[0]["meta"])
        self.assertEqual(got[0]["literals"], [("BODY[HEADER]", b"Subject: one\r\n\r\n")])
        bs, want = mailsvc._wanted_parts(got[1]["meta"])
        self.assertEqual(sorted(want), ["html", "plain"])
        self.assertEqual(want["html"]["section"], "2")
        self.assertEqual(got[2]["literals"], [])

    def test_fetch_bodies_uses_two_round_trips_for_a_batch(self):
        head = b'BODYSTRUCTURE ("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "7BIT" 5 1) BODY[HEADER]'
        conn = mock.Mock()
        conn.untagged_responses = {"UIDVALIDITY": [b"42"]}
        conn.uid.side_effect = [
            (
                "OK",
                [
                    (b"1 (UID 11 " + head + b" {26}", b"Message-ID: <a@x>\r\n\r\n"),
                    b")",
                    (b"2 (UID 12 " + head + b" {26}", b"Message-ID: <b@x>\r\n\r\n"),
                    b")",
                ],
            ),
            (
                "OK",
                [
                    (b"1 (UID 11 BODY[1] {3}", b"one"),
                    b")",
                    (b"2 (UID 12 BODY[1] {3}", b"two"),
                    b")",
                ],
            ),
        ]
        with (
            mock.patch.object(mailsvc, "_imap", return_value=conn),
            mock.patch.object(mailsvc, "_release_imap"),
        ):
            got = mailsvc.fetch_bodies({}, ["11", "12"])
        self.assertEqual(conn.uid.call_count, 2)
        self.assertEqual(
            [(m["uid"], m["text"], m["message_id"]) for m in got],
            [("11", "one", "<a@x>"), ("12", "two", "<b@x>")],
        )
        self.assertEqual({m["uidvalidity"] for m in got}, {"42"})
        self.assertEqual(conn.uid.call_args_list[1].args[1], "11,12")

    def test_fetch_bodies_refuses_a_uid_that_is_not_one(self):
        with self.assertRaises(ValueError):
            mailsvc.fetch_bodies({}, ["11\r\nA1 LOGOUT"])


class MigrationTest(ApiTest):
    def test_m0080_creates_the_table_and_can_run_again(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            m0080_mail_bodies.up(conn)
            m0080_mail_bodies.up(conn)
            conn.execute(
                text(
                    "INSERT INTO mail_bodies (id, account_id, folder, uid) VALUES ('1','a','INBOX','5')"
                )
            )
        names = {c["name"] for c in inspect(engine).get_columns("mail_bodies")}
        model = {c.name for c in MailBody.__table__.columns}
        self.assertEqual(names, model)
        indexes = {i["name"]: i for i in inspect(engine).get_indexes("mail_bodies")}
        self.assertTrue(indexes["ux_mail_bodies_message"]["unique"])
