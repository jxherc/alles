import unittest

from services.agent_intents import message_needs_tools


class AgentIntentsTest(unittest.TestCase):
    def test_action_phrases_promote(self):
        for m in [
            "add a meeting tomorrow at 3pm",
            "put lunch with sam on my calendar",
            "remind me to call the dentist",
            "create a task to file taxes",
            "send an email to alex",
            "check my inbox",
            "research the best mechanical keyboards",
            "run npm install",
        ]:
            self.assertTrue(message_needs_tools(m), f"should promote: {m!r}")

    def test_read_questions_promote(self):
        for m in [
            "what's on my calendar today",
            "what is my schedule tomorrow",
            "do i have any meetings this week",
            "what's in my inbox",
            "any new emails?",
            "any unread mail",
            "what are my tasks",
            "do i have any reminders",
            "what's going on today",
        ]:
            self.assertTrue(message_needs_tools(m), f"should promote: {m!r}")

    def test_plain_chat_does_not_promote(self):
        for m in [
            "what is the capital of france",
            "explain how transformers work",
            "how do i add an event in google calendar",   # asking how, not asking aide to do it
            "tell me a joke",
            "what does grep do",
            "write me a poem about the sea",
            "",
        ]:
            self.assertFalse(message_needs_tools(m), f"should NOT promote: {m!r}")


if __name__ == "__main__":
    unittest.main()
