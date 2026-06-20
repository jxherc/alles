from core.database import CachedMessage, MailAccount
from services import mail as mailsvc
from services import mail_cache
from tests._client import ApiTest


class CategorizeTests(ApiTest):
    def test_cat_promotions_unsubscribe(self):
        self.assertEqual(
            mailsvc.categorize("Shop <deals@shop.com>", "hi", "<https://x/u>"), "promotions"
        )

    def test_cat_promotions_words(self):
        self.assertEqual(mailsvc.categorize("a@b.com", "50% off Sale today"), "promotions")

    def test_cat_social_domain(self):
        self.assertEqual(mailsvc.categorize("LinkedIn <jobs@linkedin.com>", "news"), "social")

    def test_cat_updates_noreply(self):
        self.assertEqual(mailsvc.categorize("no-reply@bank.com", "statement"), "updates")

    def test_cat_primary_default(self):
        self.assertEqual(mailsvc.categorize("Alice <alice@friend.com>", "lunch?"), "primary")


class LabelsTests(ApiTest):
    def setUp(self):
        super().setUp()
        db = self.db()
        self.acct = MailAccount(
            name="Me", email="me@x.com", imap_host="i", smtp_host="s", username="me", password="p"
        )
        db.add(self.acct)
        db.commit()
        self.aid = self.acct.id
        db.close()

    def _msg(self, uid, sender="a@x.com", subject="m", lu=""):
        db = self.db()
        db.add(
            CachedMessage(
                account_id=self.aid,
                folder="INBOX",
                uid=str(uid),
                sender=sender,
                subject=subject,
                date="2026-06-10",
                date_ts=int(uid),
                seen=True,
                list_unsubscribe=lu,
            )
        )
        db.commit()
        db.close()

    def test_set_labels(self):
        self._msg(1)
        self.client.post(
            f"/api/mail/labels/{self.aid}", json={"uid": "1", "labels": ["Work", "Urgent"]}
        )
        msgs = self.client.get(f"/api/mail/cached/{self.aid}").json()["messages"]
        self.assertEqual(set(msgs[0]["labels"]), {"work", "urgent"})

    def test_labels_normalized(self):
        self._msg(1)
        self.client.post(
            f"/api/mail/labels/{self.aid}", json={"uid": "1", "labels": ["A", "a", " B "]}
        )
        msgs = self.client.get(f"/api/mail/cached/{self.aid}").json()["messages"]
        self.assertEqual(msgs[0]["labels"], ["a", "b"])

    def test_add_label_keeps_existing(self):
        self._msg(1)
        db = self.db()
        mail_cache.set_labels(db, self.aid, "INBOX", "1", ["work"])
        mail_cache.add_label(db, self.aid, "INBOX", "1", "later")
        db.close()
        msgs = self.client.get(f"/api/mail/cached/{self.aid}").json()["messages"]
        self.assertEqual(set(msgs[0]["labels"]), {"work", "later"})

    def test_by_label_filters(self):
        self._msg(1)
        self._msg(2)
        self.client.post(f"/api/mail/labels/{self.aid}", json={"uid": "1", "labels": ["work"]})
        d = self.client.get(f"/api/mail/by-label/{self.aid}", params={"label": "work"}).json()
        self.assertEqual([m["uid"] for m in d["messages"]], ["1"])

    def test_to_msg_labels_list(self):
        self._msg(1)
        self.client.post(f"/api/mail/labels/{self.aid}", json={"uid": "1", "labels": ["x"]})
        msgs = self.client.get(f"/api/mail/cached/{self.aid}").json()["messages"]
        self.assertIsInstance(msgs[0]["labels"], list)

    def test_by_category_filters(self):
        self._msg(1, sender="deals@shop.com", lu="<https://x/u>")  # promotions
        self._msg(2, sender="alice@friend.com", subject="lunch")  # primary
        d = self.client.get(f"/api/mail/category/{self.aid}", params={"cat": "promotions"}).json()
        self.assertEqual([m["uid"] for m in d["messages"]], ["1"])

    def test_cat_route(self):
        self._msg(1, sender="no-reply@bank.com", subject="statement")  # updates
        d = self.client.get(f"/api/mail/category/{self.aid}", params={"cat": "updates"}).json()
        self.assertEqual([m["uid"] for m in d["messages"]], ["1"])
