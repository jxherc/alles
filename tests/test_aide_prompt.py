import unittest

from core.settings import (
    BASE_AIDE_SYSTEM_PROMPT,
    LEGACY_AIDE_SYSTEM_PROMPT,
    build_aide_system_prompt,
    owner_instructions,
)


class AidePromptTests(unittest.TestCase):
    def test_base_introduces_the_ecosystem(self):
        for space in (
            "Home",
            "Andromeda",
            "Plan",
            "Inbox",
            "Docs",
            "Files",
            "Library",
            "Health",
            "Finance",
            "Vault",
            "Server",
        ):
            self.assertIn(space, BASE_AIDE_SYSTEM_PROMPT)
        # rides on every turn, so it stays small
        self.assertLess(len(BASE_AIDE_SYSTEM_PROMPT), 2000)

    def test_old_saved_default_is_not_owner_text(self):
        self.assertEqual(owner_instructions({"system_prompt": LEGACY_AIDE_SYSTEM_PROMPT}), "")
        self.assertEqual(owner_instructions({"system_prompt": BASE_AIDE_SYSTEM_PROMPT}), "")
        prompt = build_aide_system_prompt({"system_prompt": LEGACY_AIDE_SYSTEM_PROMPT})
        self.assertNotIn("### Owner instructions", prompt)
        self.assertEqual(prompt.count("You are Aide"), 1)

    def test_owner_text_follows_base_and_date_comes_last(self):
        prompt = build_aide_system_prompt(
            {"owner_instructions": "keep it brief", "timezone": "America/Toronto"}
        )
        self.assertLess(prompt.index(BASE_AIDE_SYSTEM_PROMPT), prompt.index("keep it brief"))
        last = prompt.rsplit("\n\n", 1)[-1]
        self.assertTrue(last.startswith("Today is "), last)
        self.assertIn("(America/Toronto)", last)

    def test_unknown_timezone_falls_back_to_server_time(self):
        last = build_aide_system_prompt({"timezone": "Not/AZone"}).rsplit("\n\n", 1)[-1]
        self.assertTrue(last.startswith("Today is "), last)
        self.assertNotIn("Not/AZone", last)


if __name__ == "__main__":
    unittest.main()
