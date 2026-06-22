import asyncio
import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import core.settings as cfg
from core.database import ProactiveItem, Task
from services import proactive
from tests._client import ApiTest


class _IsolatedSettings(ApiTest):
    """isolate the settings file so run() reads a clean (off-by-default) config
    and never touches the real data/settings.json."""

    def setUp(self):
        super().setUp()
        self._orig_file = cfg._SETTINGS_FILE
        cfg._SETTINGS_FILE = Path(tempfile.mkdtemp()) / "settings.json"

    def tearDown(self):
        cfg._SETTINGS_FILE = self._orig_file
        super().tearDown()


def _iso(n):
    return (date.today() + timedelta(days=n)).isoformat()


def _run(coro):
    return asyncio.run(coro)


def _sig(key, cat="task", urg=70):
    return {"category": cat, "key": key, "urgency": urg, "title": "t",
            "detail": "d", "link": "tasks", "data": {}}


class ProactiveGateTests(_IsolatedSettings):
    def test_disabled_by_default_no_run(self):
        called = {"reason": False}

        async def _spy(db, sigs, s):
            called["reason"] = True
            return []

        self._patch_reason(_spy)
        out = _run(proactive.run(force=False))
        self.assertFalse(out["ran"])
        self.assertEqual(out["reason"], "disabled")
        self.assertFalse(called["reason"])

    def test_force_no_signals(self):
        out = _run(proactive.run(force=True))
        self.assertFalse(out["ran"])
        self.assertEqual(out["reason"], "no_signals")

    def test_force_writes_card(self):
        d = self.db()
        d.add(Task(title="pay rent", done=False, due_date=_iso(-2), priority=1))
        d.commit()
        d.close()

        async def _fake(db, sigs, s):
            k = sigs[0]["key"]
            return [{"title": "pay rent", "body": "overdue", "link": "tasks",
                     "score": 80, "source_keys": [k]}]

        self._patch_reason(_fake)
        out = _run(proactive.run(force=True))
        self.assertTrue(out["ran"])
        self.assertEqual(out["written"], 1)
        d = self.db()
        self.assertEqual(d.query(ProactiveItem).count(), 1)
        d.close()

    def test_second_force_run_no_dup(self):
        d = self.db()
        d.add(Task(title="pay rent", done=False, due_date=_iso(-2)))
        d.commit()
        d.close()

        async def _fake(db, sigs, s):
            return [{"title": "pay rent", "body": "overdue", "link": "tasks",
                     "score": 80, "source_keys": [sigs[0]["key"]]}]

        self._patch_reason(_fake)
        _run(proactive.run(force=True))
        out2 = _run(proactive.run(force=True))
        # force always re-runs, but the upsert dedups -> still exactly one card
        self.assertTrue(out2["ran"])
        self.assertEqual(out2["written"], 0)
        d = self.db()
        self.assertEqual(d.query(ProactiveItem).count(), 1)
        d.close()

    def test_scheduled_nothing_new_after_seen(self):
        import core.settings as cfg
        # enable scheduled path; equal quiet bounds = never quiet, so the test is
        # not wall-clock dependent
        cfg.save_settings({"pidx_proactive_enabled": True,
                           "pidx_proactive_quiet_start": 0, "pidx_proactive_quiet_end": 0})
        d = self.db()
        d.add(Task(title="pay rent", done=False, due_date=_iso(-2)))
        d.commit()
        d.close()

        calls = {"n": 0}

        async def _fake(db, sigs, s):
            calls["n"] += 1
            return [{"title": "pay rent", "body": "overdue", "link": "tasks",
                     "score": 80, "source_keys": [sigs[0]["key"]]}]

        self._patch_reason(_fake)
        first = _run(proactive.run(force=False))   # master on, new signal -> runs
        self.assertTrue(first["ran"])
        second = _run(proactive.run(force=False))  # nothing new -> no model call
        self.assertFalse(second["ran"])
        self.assertEqual(second["reason"], "nothing_new")
        self.assertEqual(calls["n"], 1)

    def _patch_reason(self, fn):
        orig = proactive._reason
        proactive._reason = fn
        self.addCleanup(lambda: setattr(proactive, "_reason", orig))


class ProactiveUpsertTests(ApiTest):
    def test_upsert_dedup(self):
        sigs = [_sig("task_overdue:1")]
        card = {"title": "x", "body": "y", "link": "tasks", "score": 70,
                "source_keys": ["task_overdue:1"]}
        d = self.db()
        self.assertEqual(proactive._upsert(d, [card], sigs), 1)
        self.assertEqual(proactive._upsert(d, [dict(card, score=90)], sigs), 0)  # refresh, no dup
        self.assertEqual(d.query(ProactiveItem).count(), 1)
        self.assertEqual(d.query(ProactiveItem).first().score, 90)
        d.close()

    def test_dismissed_not_recreated(self):
        sigs = [_sig("task_overdue:1")]
        card = {"title": "x", "body": "y", "link": "tasks", "score": 70,
                "source_keys": ["task_overdue:1"]}
        d = self.db()
        d.add(ProactiveItem(dedupe_key=proactive._dedupe_key(["task_overdue:1"]),
                            title="x", source_keys=json.dumps(["task_overdue:1"]),
                            dismissed=True, status="dismissed"))
        d.commit()
        self.assertEqual(proactive._upsert(d, [card], sigs), 0)  # stays suppressed
        live = d.query(ProactiveItem).filter(ProactiveItem.dismissed == False).count()  # noqa: E712
        self.assertEqual(live, 0)
        d.close()

    def test_dedupe_key_stable_and_order_independent(self):
        a = proactive._dedupe_key(["k1", "k2"])
        b = proactive._dedupe_key(["k2", "k1"])
        self.assertEqual(a, b)


class ProactiveParseTests(ApiTest):
    def test_validation(self):
        sigs = [_sig("k1")]
        raw = json.dumps([
            {"title": "good", "body": "b", "link": "tasks", "score": 90, "source_keys": ["k1"]},
            {"title": "badlink", "body": "b", "link": "evil", "score": 50, "source_keys": ["k1"]},
            {"title": "bogus", "body": "b", "link": "tasks", "score": 50, "source_keys": ["nope"]},
            {"title": "", "body": "b", "link": "tasks", "score": 50, "source_keys": ["k1"]},
        ])
        out = proactive._parse_suggestions(raw, sigs)
        self.assertEqual([c["title"] for c in out], ["good", "badlink"])
        self.assertEqual([c["link"] for c in out], ["tasks", ""])

    def test_fenced_json(self):
        sigs = [_sig("k1")]
        raw = '```json\n[{"title":"a","body":"b","link":"","score":40,"source_keys":["k1"]}]\n```'
        out = proactive._parse_suggestions(raw, sigs)
        self.assertEqual(len(out), 1)

    def test_garbage_returns_empty(self):
        self.assertEqual(proactive._parse_suggestions("not json at all", [_sig("k1")]), [])


class ProactiveQuietHoursTests(ApiTest):
    def test_quiet_window_wraps_midnight(self):
        s = {"pidx_proactive_quiet_start": 22, "pidx_proactive_quiet_end": 7}
        self.assertTrue(proactive._in_quiet_hours(s, datetime(2026, 1, 1, 23, 0)))
        self.assertTrue(proactive._in_quiet_hours(s, datetime(2026, 1, 1, 3, 0)))
        self.assertFalse(proactive._in_quiet_hours(s, datetime(2026, 1, 1, 12, 0)))

    def test_equal_bounds_never_quiet(self):
        s = {"pidx_proactive_quiet_start": 0, "pidx_proactive_quiet_end": 0}
        self.assertFalse(proactive._in_quiet_hours(s, datetime(2026, 1, 1, 3, 0)))


class ProactivePushTests(ApiTest):
    def _patch_broadcast(self):
        import routes.push as push
        sent = []

        async def fake(payload):
            sent.append(payload)
            return 1

        orig = push.broadcast
        push.broadcast = fake
        self.addCleanup(lambda: setattr(push, "broadcast", orig))
        return sent

    def _card(self, **kw):
        d = self.db()
        defaults = dict(dedupe_key="k", title="card", urgency=90, source_keys="[]")
        defaults.update(kw)
        d.add(ProactiveItem(**defaults))
        d.commit()
        return d

    def test_inapp_channel_no_push(self):
        sent = self._patch_broadcast()
        d = self._card()
        n = _run(proactive._maybe_push(d, {"pidx_proactive_channel": "inapp"}))
        self.assertEqual(n, 0)
        self.assertEqual(sent, [])
        d.close()

    def test_push_channel_pushes_urgent_once(self):
        sent = self._patch_broadcast()
        d = self._card(title="urgent thing", urgency=90)
        s = {"pidx_proactive_channel": "push", "pidx_proactive_push_min": 70}
        self.assertEqual(_run(proactive._maybe_push(d, s)), 1)
        self.assertEqual(sent[0]["body"], "urgent thing")
        # pushed flag set -> not pushed again
        self.assertEqual(_run(proactive._maybe_push(d, s)), 0)
        d.close()

    def test_below_threshold_not_pushed(self):
        self._patch_broadcast()
        d = self._card(urgency=40)
        n = _run(proactive._maybe_push(d, {"pidx_proactive_channel": "push",
                                           "pidx_proactive_push_min": 70}))
        self.assertEqual(n, 0)
        d.close()
