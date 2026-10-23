import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

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

    def _msg(self, uid, sender="a@x.com", subject="m", lu="", labels=""):
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
                labels=labels,
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

    def test_add_after_lost_reply_and_retry_preserves_saved_labels(self):
        self._msg(1, labels="existing")
        url = f"/api/mail/labels/{self.aid}"
        # The caller never receives the first result, then adds a different label.
        self.client.post(url, json={"uid": "1", "add_label": " Work "})
        result = self.client.post(url, json={"uid": "1", "add_label": "personal"})
        self.assertEqual(result.json(), {"ok": True, "labels": ["existing", "work", "personal"]})
        retry = self.client.post(url, json={"uid": "1", "add_label": "WORK"})
        self.assertEqual(retry.json(), result.json())
        saved = self.client.get(f"/api/mail/cached/{self.aid}").json()["messages"]
        self.assertEqual(saved[0]["labels"], result.json()["labels"])

    def test_add_targets_account_folder_and_uid(self):
        self._msg(1, labels="inbox")
        with self.db() as db:
            db.add_all(
                [
                    CachedMessage(account_id=self.aid, folder="Work", uid="1", labels="work"),
                    CachedMessage(account_id="other", folder="Work", uid="1", labels="other"),
                    CachedMessage(account_id=self.aid, folder="Work", uid="2", labels="two"),
                ]
            )
            db.commit()
        result = self.client.post(
            f"/api/mail/labels/{self.aid}",
            json={"uid": "1", "folder": "Work", "add_label": "new"},
        )
        self.assertEqual(result.json(), {"ok": True, "labels": ["work", "new"]})
        with self.db() as db:
            labels = {(r.account_id, r.folder, r.uid): r.labels for r in db.query(CachedMessage)}
        self.assertEqual(
            labels,
            {
                (self.aid, "INBOX", "1"): "inbox",
                (self.aid, "Work", "1"): "work,new",
                ("other", "Work", "1"): "other",
                (self.aid, "Work", "2"): "two",
            },
        )

    def test_add_missing_row_is_not_success(self):
        result = self.client.post(
            f"/api/mail/labels/{self.aid}", json={"uid": "missing", "add_label": "work"}
        )
        self.assertEqual(result.json(), {"ok": False, "labels": []})

    def test_empty_add_preserves_labels_and_legacy_set_still_replaces(self):
        self._msg(1, labels="work,personal")
        url = f"/api/mail/labels/{self.aid}"
        self.assertEqual(
            self.client.post(url, json={"uid": "1", "add_label": "  "}).json(),
            {"ok": True, "labels": ["work", "personal"]},
        )
        self.assertEqual(
            self.client.post(url, json={"uid": "1", "labels": ["new"]}).json(), {"ok": True}
        )
        saved = self.client.get(f"/api/mail/cached/{self.aid}").json()["messages"]
        self.assertEqual(saved[0]["labels"], ["new"])

    def test_concurrent_additions_merge_before_writing(self):
        with tempfile.TemporaryDirectory(prefix="alles-mail-labels-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'labels.db'}")
            try:
                CachedMessage.__table__.create(engine)
                with Session(engine) as db:
                    db.add(
                        CachedMessage(account_id="a", folder="INBOX", uid="1", labels="original")
                    )
                    db.commit()
                barrier = threading.Barrier(2)

                def add(label):
                    with Session(engine) as db:
                        barrier.wait(timeout=5)
                        return mail_cache.add_label(db, "a", "INBOX", "1", label)

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(add, ["work", "personal"]))
                self.assertTrue(all("original" in result for result in results))
                with Session(engine) as db:
                    self.assertEqual(
                        set(db.query(CachedMessage).one().labels.split(",")),
                        {"original", "work", "personal"},
                    )
            finally:
                engine.dispose()

    def test_set_labels_can_store_multiple_labels(self):
        self._msg(1)
        db = self.db()
        mail_cache.set_labels(db, self.aid, "INBOX", "1", ["work", "later"])
        db.close()
        msgs = self.client.get(f"/api/mail/cached/{self.aid}").json()["messages"]
        self.assertEqual(set(msgs[0]["labels"]), {"work", "later"})

    def test_by_label_filters(self):
        self._msg(1)
        self._msg(2)
        self.client.post(f"/api/mail/labels/{self.aid}", json={"uid": "1", "labels": ["work"]})
        d = self.client.get(f"/api/mail/by-label/{self.aid}", params={"label": "work"}).json()
        self.assertEqual([m["uid"] for m in d["messages"]], ["1"])

    def test_by_label_filters_before_limit(self):
        self._msg(10, labels="homework")
        self._msg(9, labels="homework")
        self._msg(1, labels="work")
        db = self.db()
        got = mail_cache.by_label(db, self.aid, "work", limit=1)
        db.close()
        self.assertEqual([m["uid"] for m in got], ["1"])

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

    def test_by_category_filters_before_limit(self):
        self._msg(10, sender="alice@friend.com", subject="lunch")
        self._msg(9, sender="bob@friend.com", subject="hey")
        self._msg(1, sender="deals@shop.com", lu="<https://x/u>")
        db = self.db()
        got = mail_cache.by_category(db, self.aid, "promotions", limit=1)
        db.close()
        self.assertEqual([m["uid"] for m in got], ["1"])

    def test_cat_route(self):
        self._msg(1, sender="no-reply@bank.com", subject="statement")  # updates
        d = self.client.get(f"/api/mail/category/{self.aid}", params={"cat": "updates"}).json()
        self.assertEqual([m["uid"] for m in d["messages"]], ["1"])
