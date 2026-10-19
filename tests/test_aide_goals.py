import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest import mock

from core.database import (
    AideGoal,
    JarvisRun,
    JarvisRunPrompt,
    JarvisTrigger,
    JarvisWorkflow,
    ModelEndpoint,
)
from services import aide_goals, jarvis_handoff, jarvis_scheduler
from services.jarvis_store import create_run
from tests._client import ApiTest

TAIL = '\n```goal\n{"notes": "%s", "notify": %s, "headline": "%s", "done": %s}\n```'


def reply(text, notes="saw nothing new", notify="false", headline="", done="false"):
    return text + TAIL % (notes, notify, headline, done)


class GoalTest(ApiTest):
    def setUp(self):
        super().setUp()
        db = self.db()
        db.add(
            ModelEndpoint(
                name="local",
                base_url="http://127.0.0.1:11434/v1",
                api_key="",
                enabled=True,
                cached_models='["goal-model"]',
            )
        )
        db.commit()
        db.close()

    def add_goal(self, **body):
        response = self.client.post(
            "/api/jarvis/aide-goals", json={"aim": "watch flight prices to lisbon", **body}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def run_goal(self, goal_id, answer, *, seen=None):
        db = self.db()
        workflow = db.get(JarvisWorkflow, goal_id)
        run = db.query(JarvisRun).filter_by(
            workflow_id=goal_id, state="queued"
        ).first() or create_run(db, workflow)
        db.commit()
        run_id = run.id
        db.close()

        async def stream(_session, request, *_args, **_kwargs):
            if seen is not None:
                seen.append(request)
            yield {"delta": answer}

        alerts = []

        async def alert(notice):
            alerts.append(notice)

        with (
            mock.patch("services.chat_turn._build_messages", return_value=[]),
            mock.patch("services.chat_turn._stream_and_save", side_effect=stream),
            mock.patch.object(aide_goals, "alert", side_effect=alert),
        ):
            asyncio.run(jarvis_handoff._execute(run_id))
        return run_id, alerts


class GoalLifecycleTest(GoalTest):
    def test_a_goal_starts_now_and_keeps_its_own_rhythm(self):
        goal = self.add_goal(every="six_hours", mode="act")
        self.assertEqual(
            (goal["every"], goal["mode"], goal["status"]), ("six_hours", "act", "active")
        )
        self.assertTrue(goal["running"])
        db = self.db()
        trigger = db.query(JarvisTrigger).filter_by(workflow_id=goal["id"]).one()
        self.assertEqual(json.loads(trigger.config), {"every_seconds": 6 * 3600})
        self.assertEqual(db.query(JarvisRun).filter_by(workflow_id=goal["id"]).count(), 1)
        workflow = db.get(JarvisWorkflow, goal["id"])
        self.assertEqual(aide_goals.permission(workflow), "full_auto")
        db.close()
        listed = self.client.get("/api/jarvis/aide-goals").json()["items"]
        self.assertEqual([g["id"] for g in listed], [goal["id"]])
        generic = self.client.patch(f"/api/jarvis/workflows/{goal['id']}", json={"name": "x"})
        self.assertEqual(generic.status_code, 409)

    def test_each_check_remembers_the_last_one_and_only_news_alerts(self):
        goal = self.add_goal()
        seen = []
        run_id, alerts = self.run_goal(
            goal["id"], reply("prices are 410 eur", notes="cheapest 410 eur on oct 19"), seen=seen
        )
        self.assertIn("goal: watch flight prices to lisbon", seen[0])
        self.assertIn("nothing yet; this is the first check", seen[0])
        self.assertEqual(alerts, [])
        db = self.db()
        self.assertEqual(db.get(JarvisRun, run_id).result_summary, "prices are 410 eur")
        self.assertEqual(db.get(AideGoal, goal["id"]).notes, "cheapest 410 eur on oct 19")
        db.close()

        _run, alerts = self.run_goal(
            goal["id"],
            reply(
                "dropped",
                notes="now 290 eur",
                notify="true",
                headline="lisbon flights fell to 290 eur",
            ),
            seen=seen,
        )
        self.assertIn("cheapest 410 eur on oct 19", seen[1])
        self.assertIn("this is check 2", seen[1])
        self.assertEqual(alerts[0]["body"], "lisbon flights fell to 290 eur")
        listed = self.client.get("/api/jarvis/aide-goals").json()["items"][0]
        self.assertEqual(
            (listed["checks"], listed["headline"]), (2, "lisbon flights fell to 290 eur")
        )

    def test_done_or_limits_stop_the_goal(self):
        goal = self.add_goal()
        _run, alerts = self.run_goal(
            goal["id"], reply("booked", done="true", headline="booked at 280")
        )
        self.assertTrue(alerts[0]["title"].startswith("done: "))
        db = self.db()
        self.assertEqual(db.get(AideGoal, goal["id"]).status, "done")
        self.assertFalse(db.get(JarvisWorkflow, goal["id"]).enabled)
        self.assertFalse(db.query(JarvisTrigger).filter_by(workflow_id=goal["id"]).one().enabled)
        db.close()

        capped = self.add_goal(max_runs=1)
        self.run_goal(capped["id"], reply("checked"))
        db = self.db()
        self.assertEqual(db.get(AideGoal, capped["id"]).status, "finished")
        db.close()
        resumed = self.client.patch(
            f"/api/jarvis/aide-goals/{capped['id']}/state", json={"enabled": True}
        ).json()
        self.assertEqual(
            (resumed["status"], resumed["enabled"], resumed["max_runs"]), ("active", True, None)
        )

    def test_a_goal_past_its_end_date_stops_instead_of_running(self):
        goal = self.add_goal(until="2026-01-01")
        db = self.db()
        db.query(JarvisRun).filter_by(workflow_id=goal["id"]).delete()
        trigger = db.query(JarvisTrigger).filter_by(workflow_id=goal["id"]).one()
        trigger.next_run_at = datetime(2026, 3, 1)
        db.commit()
        db.close()
        with mock.patch("services.jarvis_scheduler.SessionLocal", self.db):
            asyncio.run(jarvis_scheduler.scan_due(datetime(2026, 3, 1, 0, 1)))
        db = self.db()
        self.assertEqual(db.get(AideGoal, goal["id"]).status, "finished")
        self.assertEqual(db.query(JarvisRun).filter_by(workflow_id=goal["id"]).count(), 0)
        db.close()

    def test_a_question_alerts_once(self):
        goal = self.add_goal()
        db = self.db()
        run = db.query(JarvisRun).filter_by(workflow_id=goal["id"]).one()
        db.add(JarvisRunPrompt(run_id=run.id, kind="question", question="which airport?"))
        db.commit()
        db.close()
        alerts = []

        async def alert(notice):
            alerts.append(notice)

        with mock.patch.object(aide_goals, "alert", side_effect=alert):
            asyncio.run(aide_goals.alert_waiting())
            asyncio.run(aide_goals.alert_waiting())
        self.assertEqual(len(alerts), 1)
        self.assertIn("which airport?", alerts[0]["body"])
        self.assertTrue(alerts[0]["title"].endswith("needs you"))

    def test_edit_and_delete(self):
        goal = self.add_goal()
        edited = self.client.patch(
            f"/api/jarvis/aide-goals/{goal['id']}",
            json={"aim": "watch flights to porto", "every": "week"},
        ).json()
        self.assertEqual((edited["aim"], edited["every"]), ("watch flights to porto", "week"))
        busy = self.client.delete(f"/api/jarvis/aide-goals/{goal['id']}")
        self.assertEqual(busy.status_code, 409)
        db = self.db()
        db.query(JarvisRun).filter_by(workflow_id=goal["id"]).update({JarvisRun.state: "cancelled"})
        db.commit()
        db.close()
        self.assertEqual(
            self.client.delete(f"/api/jarvis/aide-goals/{goal['id']}").status_code, 200
        )
        self.assertEqual(self.client.get("/api/jarvis/aide-goals").json()["items"], [])

    def test_until_must_be_a_date(self):
        response = self.client.post("/api/jarvis/aide-goals", json={"aim": "x", "until": "soon"})
        self.assertEqual(response.status_code, 400)


class GoalToolTest(GoalTest):
    def test_chat_can_set_and_list_a_goal(self):
        from services import agent_tools

        made = asyncio.run(agent_tools._goal_add("keep my inbox under 20 unread", every="hour"))
        self.assertIn("first check starts now", made["output"])
        listed = asyncio.run(agent_tools._goal_list())
        self.assertIn("keep my inbox under 20 unread (active, 0 checks)", listed["output"])
        db = self.db()
        trigger = db.query(JarvisTrigger).filter_by(workflow_id=made["goal_id"]).one()
        self.assertEqual(json.loads(trigger.config)["every_seconds"], 3600)
        self.assertLess(trigger.next_run_at, datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1, minutes=1))
        db.close()

    def test_names_stay_short_and_artifact_wrappers_drop(self):
        self.assertEqual(
            aide_goals.short_name("keep an eye on my open tasks: tell me if one is new"),
            "keep an eye on my open tasks",
        )
        goal = self.add_goal(aim="track my tasks: note them")
        self.assertEqual(goal["name"], "track my tasks")
        run_id, _alerts = self.run_goal(
            goal["id"], reply('<aide-artifact type="markdown" title="t">\n* a\n</aide-artifact>')
        )
        db = self.db()
        self.assertEqual(db.get(JarvisRun, run_id).result_summary, "* a")
        db.close()

    def test_tail_parsing_is_forgiving(self):
        self.assertEqual(aide_goals.read_tail("plain answer"), ("plain answer", {}))
        clean, data = aide_goals.read_tail(reply("hi", notes="n"))
        self.assertEqual((clean, data["notes"]), ("hi", "n"))
        broken = "hi\n```goal\n{not json}\n```"
        self.assertEqual(aide_goals.read_tail(broken), (broken, {}))
