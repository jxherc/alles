"""Two SQLite connections; synthetic delivery only, no scheduler or network."""

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, MailAccount, ScheduledMail
from routes.mail import cancel_scheduled
from services.mail_outbox import process_due


class CancelConnections(unittest.TestCase):
    def test_claim_and_cancel_have_one_honest_outcome(self):
        for claim_first in [False, True]:
            with self.subTest(claim_first=claim_first):
                with tempfile.TemporaryDirectory(prefix="alles-outbox-claim-") as root:
                    engine = create_engine(f"sqlite:///{Path(root) / 'owned.db'}")
                    Base.metadata.create_all(engine)
                    sessions = sessionmaker(bind=engine)
                    with sessions() as db:
                        account = MailAccount(
                            name="Owned fixture",
                            email="owned@example.invalid",
                            imap_host="127.0.0.1",
                            imap_port=9,
                            smtp_host="127.0.0.1",
                            smtp_port=9,
                            username="owned",
                            password="",
                            use_ssl=False,
                        )
                        db.add(account)
                        db.flush()
                        row = ScheduledMail(
                            account_id=account.id,
                            to="recipient@example.invalid",
                            subject="owned delivery",
                            body="synthetic only",
                            send_at="2000-01-01T00:00:00",
                            status="scheduled",
                        )
                        db.add(row)
                        db.commit()
                        identity = row.id
                    entered = threading.Event()
                    release = threading.Event()
                    deliveries = []

                    def synthetic(account, message):
                        deliveries.append(message.id)
                        entered.set()
                        assert release.wait(10)

                    def deliver():
                        with sessions() as db:
                            return process_due(db, now_iso="2001-01-01T00:00:00", send_fn=synthetic)

                    try:
                        if claim_first:
                            with ThreadPoolExecutor(max_workers=1) as pool:
                                future = pool.submit(deliver)
                                try:
                                    self.assertTrue(entered.wait(10))
                                    with sessions() as db:
                                        self.assertEqual(
                                            db.get(ScheduledMail, identity).status, "sending"
                                        )
                                        try:
                                            result = cancel_scheduled(identity, db)
                                        except HTTPException as error:
                                            result = error.status_code
                                finally:
                                    release.set()
                                count = future.result(timeout=15)
                            with sessions() as db:
                                state = db.get(ScheduledMail, identity).status
                            print("claim first", result, state, count, deliveries, flush=True)
                            self.assertEqual(result, 409)
                            self.assertEqual((state, count, deliveries), ("sent", 1, [identity]))
                        else:
                            with sessions() as db:
                                self.assertEqual(
                                    cancel_scheduled(identity, db)["status"], "canceled"
                                )
                            release.set()
                            count = deliver()
                            with sessions() as db:
                                state = db.get(ScheduledMail, identity).status
                            print("cancel first", state, count, deliveries, flush=True)
                            self.assertEqual((state, count, deliveries), ("canceled", 0, []))
                    finally:
                        release.set()
                        engine.dispose()


if __name__ == "__main__":
    unittest.main(verbosity=2)
