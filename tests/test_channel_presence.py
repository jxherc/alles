import asyncio
import json
import unittest
from unittest import mock

from core.settings import save_settings
from services import channel_runs, jarvis_discord, photon_channel
from tests._client import ApiTest


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class PresenceTest(unittest.TestCase):
    def run_task(self, every, seconds, tick=2.0, runs=None):
        """a fake task of `seconds` with the watch loop ticking every `tick`; returns send times."""
        clock, sent = FakeClock(), []

        async def send(space, on):
            sent.append((clock.now, space, on))

        presence = channel_runs.Presence(send, every=every, clock=clock)
        runs = {"r1": {"space": "chat-1", "told": set()}} if runs is None else runs

        async def go():
            await presence("chat-1", True)
            while clock.now < seconds:
                clock.now += tick
                await presence.tick(runs)
            await presence("chat-1", False)

        asyncio.run(go())
        return sent

    def test_a_60_second_task_keeps_typing_inside_the_bubble_lifetime(self):
        sent = self.run_task(every=4.0, seconds=60)
        starts = [t for t, _, on in sent if on]
        self.assertEqual(starts[0], 0.0)
        gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
        self.assertTrue(gaps, "typing was never sent again")
        self.assertLessEqual(max(gaps), 4.0)  # imessage and telegram bubbles last about 5s
        self.assertEqual(sent[-1][2:], (False,))
        self.assertGreater(starts[-1], 55)  # still being refreshed near the end of the task

    def test_a_five_second_gap_on_a_two_second_tick_would_leave_a_hole(self):
        starts = [t for t, _, on in self.run_task(every=5.0, seconds=30) if on]
        self.assertEqual(max(b - a for a, b in zip(starts, starts[1:], strict=False)), 6.0)

    def test_no_typing_while_the_run_waits_for_the_owner(self):
        runs = {"r1": {"space": "chat-1", "told": set(), "paused": True}}
        sent = self.run_task(every=4.0, seconds=30, runs=runs)
        self.assertEqual([on for _, _, on in sent], [True, False])  # the first start and the stop

    def test_a_failing_send_never_breaks_the_watcher(self):
        async def send(space, on):
            raise RuntimeError("telegram is down")

        presence = channel_runs.Presence(send, every=1.0, clock=FakeClock())
        asyncio.run(presence("chat-1", True))
        asyncio.run(presence.tick({"r1": {"space": "chat-1"}}))

    def test_a_stopped_chat_starts_again_at_the_next_tick(self):
        clock, sent = FakeClock(), []

        async def send(space, on):
            sent.append(on)

        presence = channel_runs.Presence(send, every=4.0, clock=clock)
        runs = {"r1": {"space": "a"}}

        async def go():
            await presence("a", True)
            await presence("a", False)
            clock.now += 2
            await presence.tick(runs)

        asyncio.run(go())
        self.assertEqual(sent, [True, False, True])

    def test_discord_refreshes_every_8_seconds_and_telegram_and_imessage_every_4(self):
        from services import telegram_channel

        self.assertEqual(jarvis_discord._TYPING_REFRESH_SECONDS, 8.0)
        self.assertEqual(telegram_channel._presence.every, 4.0)
        self.assertEqual(photon_channel._presence.every, 4.0)


class PhotonReadTest(ApiTest):
    def setUp(self):
        super().setUp()
        photon_channel._seen.clear()
        photon_channel._runs.clear()
        photon_channel.state.update(ignored=0, handled=0, last_ignored="")
        save_settings({"photon_owner_handles": ["+15550100199"]})
        self.commands = []

        async def send(command):
            self.commands.append(command)

        for patch in (
            mock.patch.object(photon_channel, "_send", side_effect=send),
            mock.patch("services.jarvis_handoff.launch"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        save_settings({"photon_owner_handles": [], "photon_read_receipts": True})
        photon_channel._runs.clear()
        super().tearDown()

    def record(self, sender="+15550100199", message_id="m1"):
        return {
            "type": "message",
            "id": message_id,
            "space": "chat-1",
            "sender": sender,
            "text": "hi",
        }

    def test_the_owner_message_is_marked_read_then_typing_starts(self):
        asyncio.run(photon_channel.handle_message(self.record()))
        self.assertEqual(
            self.commands[:2],
            [
                {"type": "read", "space": "chat-1", "id": "m1"},
                {"type": "typing", "space": "chat-1", "on": True},
            ],
        )

    def test_a_stranger_on_the_shared_line_gets_no_receipt_and_no_typing(self):
        asyncio.run(photon_channel.handle_message(self.record(sender="+15559990000")))
        self.assertEqual(self.commands, [])

    def test_the_setting_turns_read_receipts_off(self):
        save_settings({"photon_read_receipts": False})
        self.assertFalse(photon_channel.settings()["read_receipts"])
        asyncio.run(photon_channel.handle_message(self.record()))
        self.assertEqual([c["type"] for c in self.commands], ["typing"])

    def test_read_receipts_default_to_on(self):
        self.assertTrue(photon_channel.settings()["read_receipts"])

    def test_the_settings_route_saves_the_read_receipts_choice_and_keeps_it_when_left_out(self):
        body = {"enabled": False, "project_id": "p1", "owner_handles": ["me@example.test"]}
        with mock.patch.object(photon_channel, "restart", new=mock.AsyncMock()):
            off = self.client.put(
                "/api/aide/channels/photon", json={**body, "read_receipts": False}
            )
            self.assertEqual(off.status_code, 200, off.text)
            self.assertIs(off.json()["read_receipts"], False)
            kept = self.client.put("/api/aide/channels/photon", json=body)
        self.assertIs(kept.json()["read_receipts"], False)

    def test_typing_pauses_for_a_question_and_comes_back_when_it_is_answered(self):
        from core.database import JarvisRunPrompt

        asyncio.run(photon_channel.handle_message(self.record()))
        run_id = next(iter(photon_channel._runs))
        with self.db() as db:
            db.add(
                JarvisRunPrompt(
                    run_id=run_id,
                    kind="choice",
                    question="which week?",
                    options=json.dumps(["this", "next"]),
                )
            )
            db.commit()
        clock = FakeClock()
        presence = channel_runs.Presence(photon_channel._typing, every=4.0, clock=clock)

        async def reply(space, text):
            pass

        async def step():
            clock.now += 10
            await channel_runs.watch_once(photon_channel._runs, reply, presence, photon_channel.log)
            await presence.tick(photon_channel._runs)

        self.commands.clear()
        asyncio.run(step())
        self.assertTrue(photon_channel._runs[run_id]["paused"])
        self.assertEqual([c["on"] for c in self.commands], [False])  # stopped, not started again
        with self.db() as db:
            db.query(JarvisRunPrompt).update({"state": "answered"})
            db.commit()
        self.commands.clear()
        asyncio.run(step())
        self.assertFalse(photon_channel._runs[run_id]["paused"])
        self.assertEqual([c["on"] for c in self.commands], [True])


if __name__ == "__main__":
    unittest.main()
