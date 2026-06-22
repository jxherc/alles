from core.database import ProactiveItem
from tests._client import ApiTest


class ProactiveModelTests(ApiTest):
    def test_roundtrip_and_dismiss(self):
        d = self.db()
        it = ProactiveItem(dedupe_key="k1", category="task", title="pay rent",
                           body="rent is overdue", link="tasks", score=70, urgency=70,
                           source_keys='["task_overdue:1"]')
        d.add(it)
        d.commit()
        rid = it.id
        d.close()

        d2 = self.db()
        got = d2.get(ProactiveItem, rid)
        self.assertEqual(got.title, "pay rent")
        self.assertEqual(got.status, "new")
        self.assertFalse(got.dismissed)
        # dismiss
        got.status = "dismissed"
        got.dismissed = True
        d2.commit()
        d2.close()

        d3 = self.db()
        again = d3.get(ProactiveItem, rid)
        self.assertTrue(again.dismissed)
        self.assertEqual(again.status, "dismissed")
        d3.close()
