import asyncio
from unittest import mock

from core.database import PushSubscription
from services import push_delivery
from tests._client import ApiTest


class PushDeliveryTests(ApiTest):
    def test_mixed_outcomes_count_once_and_prune_only_gone(self):
        db = self.db()
        for name in ("sent", "gone", "uncertain", "failed"):
            db.add(PushSubscription(endpoint=f"https://push.example/{name}", p256dh="k", auth="a"))
        db.commit()
        db.close()

        seen = []

        async def deliver(sub, payload):
            seen.append((sub["endpoint"], payload))
            return sub["endpoint"].rsplit("/", 1)[-1]

        payload = {"title": "test"}
        with mock.patch("services.webpush.send_push", deliver):
            result = asyncio.run(push_delivery.broadcast_result(payload))

        self.assertEqual(result, {"sent": 1, "failed": 1, "uncertain": 1, "pruned": 1, "total": 4})
        self.assertEqual(len(seen), 4)
        self.assertTrue(all(sent_payload == payload for _, sent_payload in seen))
        db = self.db()
        endpoints = {sub.endpoint for sub in db.query(PushSubscription).all()}
        db.close()
        self.assertEqual(
            endpoints,
            {
                "https://push.example/sent",
                "https://push.example/uncertain",
                "https://push.example/failed",
            },
        )
