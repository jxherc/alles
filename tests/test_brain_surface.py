"""surface-brain stage - aide injection of insights + the distilled user-model, the manual
distill route, and the two new inject settings. tests first (RED)."""

import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import insights, user_model


class _DBCase(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()


class InsightInjectionTests(_DBCase):
    def test_formats_pinned_first(self):
        self.s.add(db.Insight(title="normal insight", body="b1", dedupe_key="i1"))
        self.s.add(db.Insight(title="pinned insight", body="b2", dedupe_key="i2", pinned=True))
        self.s.add(db.Insight(title="hidden", body="b3", dedupe_key="i3", dismissed=True))
        self.s.commit()
        out = insights.inject_active_insights(self.s)
        self.assertIn("pinned insight", out)
        self.assertIn("normal insight", out)
        self.assertNotIn("hidden", out)
        self.assertLess(out.index("pinned insight"), out.index("normal insight"))

    def test_empty_when_none(self):
        self.assertEqual(insights.inject_active_insights(self.s), "")

    def test_bounded_by_limit(self):
        for i in range(12):
            self.s.add(db.Insight(title=f"insight number {i}", body="x", dedupe_key=f"k{i}"))
        self.s.commit()
        out = insights.inject_active_insights(self.s, limit=5)
        self.assertEqual(out.count("\n- "), 5)


class DistilledInjectionTests(_DBCase):
    def test_excludes_vetoed_and_below_threshold(self):
        user_model.apply_distilled(
            self.s, [{"text": "likes dark mode", "category": "preference", "confidence": 0.9}]
        )
        user_model.apply_distilled(
            self.s, [{"text": "weak signal fact", "category": "general", "confidence": 0.3}]
        )
        self.s.add(
            db.Memory(text="vetoed fact zzz", source="distilled", confidence=0.9, vetoed=True)
        )
        self.s.commit()
        out = user_model.inject_distilled(self.s, threshold=0.5)
        self.assertIn("dark mode", out)
        self.assertNotIn("weak signal", out)
        self.assertNotIn("zzz", out)

    def test_empty_when_none(self):
        self.assertEqual(user_model.inject_distilled(self.s), "")

    def test_ordered_by_confidence(self):
        user_model.apply_distilled(
            self.s, [{"text": "low conf fact", "category": "fact", "confidence": 0.55}]
        )
        user_model.apply_distilled(
            self.s, [{"text": "high conf fact", "category": "fact", "confidence": 0.95}]
        )
        self.s.commit()
        out = user_model.inject_distilled(self.s, threshold=0.5)
        self.assertLess(out.index("high conf fact"), out.index("low conf fact"))


class IncognitoEvidenceTests(_DBCase):
    def test_gather_evidence_skips_incognito_sessions(self):
        # incognito = no trace: its name must never become distill evidence
        self.s.add(db.Session(name="planning a normal trip"))
        self.s.add(db.Session(name="secret incognito topic", incognito=True))
        self.s.commit()
        ev = user_model.gather_evidence(self.s)
        self.assertTrue(any("normal trip" in t for t in ev["topics"]))
        self.assertFalse(any("incognito topic" in t for t in ev["topics"]))


class ParserRobustnessTests(_DBCase):
    def test_insights_parse_numeric_title_no_crash(self):
        out = insights._parse('[{"title":123,"body":456,"evidence":[1,2]}]')
        self.assertIsInstance(out, list)

    def test_parse_facts_numeric_text_no_crash(self):
        out = user_model._parse_facts('[{"text":123,"confidence":0.5}]')
        self.assertIsInstance(out, list)

    def test_apply_insights_numeric_fields_no_crash(self):
        n = insights.apply_insights(self.s, [{"title": 123, "body": 456, "evidence": ["e"]}])
        self.assertIsInstance(n, int)

    def test_apply_distilled_caps_text_300(self):
        user_model.apply_distilled(
            self.s, [{"text": "Q" * 9999, "category": "fact", "confidence": 0.7}]
        )
        m = self.s.query(db.Memory).filter(db.Memory.source == "distilled").first()
        self.assertLessEqual(len(m.text), 300)


class BuildMessagesTests(_DBCase):
    def _sys(self, extra):
        from routes.chat import _build_messages

        base = {
            "memory_auto_inject": False,
            "session_context_inject": False,
            "artifacts_enabled": False,
        }
        base.update(extra)
        sess = db.Session(name="test session")
        self.s.add(sess)
        self.s.commit()
        msgs = _build_messages(sess, "hello there", base, db=self.s)
        return msgs[0]["content"]

    def test_insights_injected_when_on(self):
        self.s.add(db.Insight(title="spends more after travel", body="", dedupe_key="z1"))
        self.s.commit()
        self.assertIn("spends more after travel", self._sys({"insights_auto_inject": True}))

    def test_insights_omitted_when_off(self):
        self.s.add(db.Insight(title="should not show", body="", dedupe_key="z2"))
        self.s.commit()
        self.assertNotIn("should not show", self._sys({"insights_auto_inject": False}))

    def test_distilled_injected_when_on(self):
        self.s.add(db.Memory(text="prefers concise answers", source="distilled", confidence=0.9))
        self.s.commit()
        self.assertIn("concise answers", self._sys({"distilled_auto_inject": True}))

    def test_distilled_omitted_when_off_and_vetoed_never_injected(self):
        self.s.add(db.Memory(text="hidden pref", source="distilled", confidence=0.9))
        self.s.add(
            db.Memory(text="vetoed pref qqq", source="distilled", confidence=0.9, vetoed=True)
        )
        self.s.commit()
        self.assertNotIn("hidden pref", self._sys({"distilled_auto_inject": False}))
        self.assertNotIn("qqq", self._sys({"distilled_auto_inject": True}))


class RouteAndSettingsTests(unittest.TestCase):
    def setUp(self):
        from starlette.testclient import TestClient

        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        from app import app

        self.c = TestClient(app)
        self.s = db.SessionLocal()

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_distill_run_route_clean_without_model(self):
        r = self.c.post("/api/memory/distill/run").json()
        self.assertIn("ran", r)
        self.assertIn("count", r)

    def test_inject_settings_default_true(self):
        from core.settings import _defaults

        self.assertTrue(_defaults.get("insights_auto_inject"))
        self.assertTrue(_defaults.get("distilled_auto_inject"))

    def test_settingspatch_accepts_inject_keys(self):
        from routes.settings import SettingsPatch

        p = SettingsPatch(insights_auto_inject=False, distilled_auto_inject=False)
        self.assertFalse(p.insights_auto_inject)
        self.assertFalse(p.distilled_auto_inject)


if __name__ == "__main__":
    unittest.main()
