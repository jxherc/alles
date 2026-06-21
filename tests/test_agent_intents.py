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
            "what do i have on my calendar?",  # the one real usage caught
            "what do i have on my calendar this week",
            "do i have anything on my calendar",
            "check my calendar",
            "check it on my schedule",
            "pull up my inbox",
            "do i have any meetings this week",
            "what's in my inbox",
            "any new emails?",
            "any unread mail",
            "what are my tasks",
            "what do i have on my plate",
            "do i have any reminders",
            "what's going on today",
            "what do i have coming up",
        ]:
            self.assertTrue(message_needs_tools(m), f"should promote: {m!r}")

    def test_plain_chat_does_not_promote(self):
        for m in [
            "what is the capital of france",
            "explain how transformers work",
            "how do i add an event in google calendar",  # asking how, not asking aide to do it
            "tell me a joke",
            "what does grep do",
            "write me a poem about the sea",
            "",
        ]:
            self.assertFalse(message_needs_tools(m), f"should NOT promote: {m!r}")

    def test_empty_string_never_promotes(self):
        self.assertFalse(message_needs_tools(""))

    def test_shell_commands_promote(self):
        for m in [
            "run npm install in the backend folder",
            "pip install requests",
            "docker compose up",
        ]:
            self.assertTrue(message_needs_tools(m), f"should promote: {m!r}")

    def test_code_editing_promotes(self):
        for m in [
            "fix the bug in the auth function",
            "refactor the login class",
            "add a test for the payment method",
        ]:
            self.assertTrue(message_needs_tools(m), f"should promote: {m!r}")

    def test_research_promotes(self):
        for m in [
            "research the best laptops for developers",
            "deep dive into rust's ownership model",
            "look into the latest react updates",
        ]:
            self.assertTrue(message_needs_tools(m), f"should promote: {m!r}")

    def test_case_insensitive(self):
        # patterns use re.I so casing shouldn't matter
        self.assertTrue(message_needs_tools("REMIND ME to do laundry"))
        self.assertTrue(message_needs_tools("Check My Inbox"))
        self.assertFalse(message_needs_tools("WHAT IS THE CAPITAL OF FRANCE"))

    def test_email_actions_promote(self):
        for m in [
            "send an email to sarah about the meeting",
            "write a message to the team",
            "reply to john's email",
        ]:
            self.assertTrue(message_needs_tools(m), f"should promote: {m!r}")

    def test_personal_app_actions_promote(self):
        for m in [
            # health
            "log my weight 72.3 kg",
            "track my sleep",
            "record my workout",
            # books
            "add dune to my reading list",
            "i finished reading the hobbit",
            "add a book to my reading list",
            # read-later
            "save this link to read later",
            "read this later: https://example.com/post",
            # habits
            "mark my reading habit done",
            "did i do my habits today",
            # watch
            "is example.com up",
            "is my website down",
            "add a monitor for my site",
        ]:
            self.assertTrue(message_needs_tools(m), f"should promote: {m!r}")

    def test_personal_app_lookalikes_do_not_promote(self):
        # these mention the same nouns but aren't asking aide to act
        for m in [
            "what's a good book to read",
            "how do i lose weight",
            "what is a good habit to build",
            "why is the sky blue",
        ]:
            self.assertFalse(message_needs_tools(m), f"should NOT promote: {m!r}")


if __name__ == "__main__":
    unittest.main()
