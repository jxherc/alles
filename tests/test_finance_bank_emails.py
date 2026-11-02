"""bank alert emails (27.41) go through finance's reviewed import: preview, confirm the card
ending, apply, undo. every example here is synthetic; unknown layouts reach the review with
the raw email, never a guessed value."""

import json
import time
from unittest import mock

from core.database import CachedMessage, MailAccount, Transaction
from services import finance_imports, mail_cache
from services import mail as mailsvc
from tests._client import ApiTest

SENT = "Mon, 02 Nov 2026 09:14:00 -0500"


def _email(text, subject="Northwind Bank transaction alert", **extra):
    return {
        "from": "Northwind Bank <alerts@northwind-bank.test>",
        "subject": subject,
        "date": SENT,
        "message_id": extra.pop("message_id", f"<{abs(hash(text))}@northwind-bank.test>"),
        "text": text,
    } | extra


SHAPES = [
    (
        "A purchase of $42.18 was made at CORNER MARKET on your card ending in 4821 on Oct 30, 2026.",
        ("2026-10-30", "-42.18", "CORNER MARKET", "4821", "CAD"),
    ),
    (
        "You spent $7.45 at BLUE BOTTLE COFFEE with your Northwind Visa ending 4821.",
        ("2026-11-02", "-7.45", "BLUE BOTTLE COFFEE", "4821", "CAD"),
    ),
    (
        "Transaction alert: a deposit of $1,250.00 to your account ending 7730 on Nov 01, 2026.",
        ("2026-11-01", "1250.00", "deposit", "7730", "CAD"),
    ),
    (
        "We noticed a payment of US$89.99 to STREAMBOX ANNUAL on card ending in 4821.",
        ("2026-11-02", "-89.99", "STREAMBOX ANNUAL", "4821", "USD"),
    ),
    (
        "Your card ending 4821 was charged $15.00 at CITY PARKING on 2026-10-29.\n\n"
        "Available balance: $3,210.55\nIf you don't recognize this, call us.",
        ("2026-10-29", "-15.00", "CITY PARKING", "4821", "CAD"),
    ),
    (
        "Purchase on your card\nMerchant: GREEN GROCER\nAmount: $23.10\nCard: ****4821\nDate: 2026-10-28",
        ("2026-10-28", "-23.10", "GREEN GROCER", "4821", "CAD"),
    ),
    (
        "A refund of $12.00 from BOOK NOOK was credited to your credit card ending 4821.",
        ("2026-11-02", "12.00", "BOOK NOOK", "4821", "CAD"),
    ),
]


class BankEmailParsingTest(ApiTest):
    def parse(self, *emails, currency="CAD"):
        return finance_imports.parse(
            "bank-email",
            json.dumps(list(emails)),
            account_id="acct",
            requested_currency=currency,
            statement_identity="mail:abc",
        )

    def test_common_alert_shapes(self):
        for text, (day, amount, payee, suffix, currency) in SHAPES:
            with self.subTest(text=text[:40]):
                row = self.parse(_email(text))[0]
                self.assertEqual(row["error"], "")
                parsed = row["parsed"]
                self.assertEqual(
                    (
                        parsed["date"],
                        parsed["amount_text"],
                        parsed["payee"],
                        parsed["account_suffix"],
                        parsed["currency_code"],
                    ),
                    (day, amount, payee, suffix, currency),
                )
                self.assertTrue(row["stable_identity"])

    def test_unknown_or_unclear_emails_keep_the_raw_text_and_guess_nothing(self):
        cases = [
            ("Your statement is ready to view.", finance_imports.EMAIL_SHAPE_UNKNOWN),
            ("You paid $5.00 and $6.00 at TWO PLACES with card ending 4821.", "more than one"),
            ("A purchase of $9.00 was made at SHOP.", "account suffix is missing"),
            ("Payment of $500.00 received on your card ending 4821.", "direction"),
        ]
        for text, reason in cases:
            with self.subTest(text=text):
                row = self.parse(_email(text))[0]
                self.assertIn(reason, row["error"])
                self.assertEqual(row["parsed"], {})
                self.assertEqual(row["raw"]["email_text"], text)
                self.assertEqual(
                    row["raw"]["email_from"], "Northwind Bank <alerts@northwind-bank.test>"
                )

    def test_a_bare_dollar_needs_an_account_currency(self):
        row = self.parse(_email(SHAPES[1][0]), currency="")[0]
        self.assertEqual(row["error"], "currency is missing or ambiguous")

    def test_the_same_email_twice_keeps_one_identity(self):
        one = self.parse(_email(SHAPES[0][0], message_id="<same@x>"))[0]
        two = self.parse(_email(SHAPES[0][0], message_id="<same@x>"))[0]
        self.assertEqual(one["stable_identity"], two["stable_identity"])

    def test_a_saved_eml_file_reads_as_one_email(self):
        eml = (
            "From: Northwind Bank <alerts@northwind-bank.test>\r\n"
            "Subject: Purchase alert\r\nDate: Mon, 02 Nov 2026 09:14:00 -0500\r\n"
            "Message-ID: <eml-1@northwind-bank.test>\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n" + SHAPES[0][0] + "\r\n"
        )
        rows = finance_imports.parse(
            "bank-email", eml, account_id="a", requested_currency="CAD", statement_identity="f"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["parsed"]["payee"], "CORNER MARKET")
        self.assertEqual(rows[0]["parsed"]["external_id"], "<eml-1@northwind-bank.test>")


class BankEmailReviewTest(ApiTest):
    def setUp(self):
        super().setUp()
        self.account = self.client.post(
            "/api/money/accounts",
            json={"name": "Northwind Visa", "kind": "credit", "currency": "CAD", "opening": 0},
        ).json()

    def preview(self, **body):
        response = self.client.post(
            "/api/finance/imports/preview",
            json={
                "account_id": self.account["id"],
                "profile": "bank-email",
                "source_name": "bank emails",
            }
            | body,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def transactions(self):
        with self.db() as db:
            return db.query(Transaction).count()

    def test_preview_confirm_apply_and_undo(self):
        content = json.dumps([_email(SHAPES[0][0]), _email("Your statement is ready.")])
        receipt = self.preview(content=content)
        known, unknown = receipt["rows"]
        self.assertEqual(known["status"], "needs_review")
        self.assertTrue(known["conflict_reason"].startswith("confirm account ending 4821 "))
        self.assertEqual(unknown["status"], "needs_review")
        self.assertEqual(unknown["conflict_reason"], finance_imports.EMAIL_SHAPE_UNKNOWN)
        self.assertEqual(unknown["raw"]["email_text"], "Your statement is ready.")
        # nothing posts before the card ending is confirmed
        self.assertEqual(
            self.client.post(f"/api/finance/imports/{receipt['id']}/apply").status_code, 409
        )
        confirmed = self.client.post(
            f"/api/finance/imports/{receipt['id']}/rows/{known['id']}/confirm-account",
            json={"account_id": self.account["id"], "account_suffix": "4821"},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["rows"][0]["status"], "pending")
        # the unread email blocks apply until the owner leaves it out
        self.assertEqual(
            self.client.post(f"/api/finance/imports/{receipt['id']}/apply").status_code, 409
        )
        skipped = self.client.post(
            f"/api/finance/imports/{receipt['id']}/rows/{unknown['id']}/resolve-match",
            json={"decision": "skip"},
        )
        self.assertEqual(skipped.status_code, 200, skipped.text)
        self.assertEqual(skipped.json()["rows"][1]["status"], "skipped")
        applied = self.client.post(f"/api/finance/imports/{receipt['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(applied.json()["status"], "applied")
        self.assertEqual(self.transactions(), 1)
        undone = self.client.post(f"/api/finance/imports/{receipt['id']}/undo")
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(self.transactions(), 0)

    def test_the_bank_csv_of_the_same_purchase_goes_to_review_not_twice(self):
        receipt = self.preview(content=json.dumps([_email(SHAPES[5][0])]))
        row = receipt["rows"][0]
        self.client.post(
            f"/api/finance/imports/{receipt['id']}/rows/{row['id']}/confirm-account",
            json={"account_id": self.account["id"], "account_suffix": "4821"},
        )
        self.assertEqual(
            self.client.post(f"/api/finance/imports/{receipt['id']}/apply").status_code, 200
        )
        csv = self.client.post(
            "/api/finance/imports/preview",
            json={
                "account_id": self.account["id"],
                "profile": "cibc-csv",
                "source_name": "northwind.csv",
                "content": "Date,Description,Debit,Credit\n2026-10-28,GREEN GROCER,23.10,\n",
                "original_currency_code": "CAD",
            },
        ).json()
        self.assertEqual(csv["rows"][0]["status"], "needs_review")
        self.assertIn("match", csv["rows"][0]["conflict_reason"])
        self.assertEqual(self.transactions(), 1)

    def test_from_mail_reads_alert_emails_from_the_saved_inbox(self):
        with self.db() as db:
            mail = MailAccount(name="home", email="eric@home.test", imap_host="127.0.0.1")
            db.add(mail)
            db.commit()
            now = time.time()
            for uid, sender, subject in [
                ("31", "Northwind Bank <alerts@northwind-bank.test>", "Transaction alert"),
                ("32", "Maya <maya@friends.test>", "payment for the trip?"),
                ("33", "Receipts <receipts@shop.test>", "your receipt"),
            ]:
                db.add(
                    CachedMessage(
                        account_id=mail.id,
                        folder="INBOX",
                        uid=uid,
                        sender=sender,
                        subject=subject,
                        date=SENT,
                        date_ts=now - int(uid),
                        message_id=f"<{uid}@x>",
                    )
                )
            db.commit()
            mail_id = mail.id
        read = _email(SHAPES[1][0], message_id="<31@x>") | {"uid": "31", "html": ""}
        with mock.patch.object(mailsvc, "fetch_message", return_value=read) as live:
            receipt = self.preview(from_mail=True, mail_days=30)
            again = self.preview(from_mail=True, mail_days=30)
        live.assert_called_once()  # the body was kept, so the second read stays local
        self.assertEqual(
            [row["parsed"].get("payee") for row in receipt["rows"]], ["BLUE BOTTLE COFFEE"]
        )
        self.assertEqual(again["rows"][0]["stable_identity"], receipt["rows"][0]["stable_identity"])
        with self.db() as db:
            self.assertIsNotNone(mail_cache.stored_body(db, mail_id, "INBOX", "31"))

    def test_only_a_bank_email_row_can_be_left_out(self):
        csv = self.client.post(
            "/api/finance/imports/preview",
            json={
                "account_id": self.account["id"],
                "profile": "generic-csv",
                "source_name": "broken.csv",
                "content": "date,payee,amount\nnot a date,SHOP,-1.00\n",
                "original_currency_code": "CAD",
            },
        ).json()
        response = self.client.post(
            f"/api/finance/imports/{csv['id']}/rows/{csv['rows'][0]['id']}/resolve-match",
            json={"decision": "skip"},
        )
        self.assertEqual(response.status_code, 409)

    def test_from_mail_says_when_there_is_nothing(self):
        response = self.client.post(
            "/api/finance/imports/preview",
            json={
                "account_id": self.account["id"],
                "profile": "bank-email",
                "source_name": "bank emails",
                "from_mail": True,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("no bank alert emails", response.json()["detail"])
