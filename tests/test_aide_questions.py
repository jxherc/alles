import unittest

from services.aide_questions import normalize_answer, normalize_request


class AideQuestionContractTests(unittest.TestCase):
    def request(self):
        return normalize_request(
            {
                "title": "Choose the next pass",
                "questions": [
                    {
                        "id": "scope",
                        "prompt": "What should Aide inspect?",
                        "choices": [
                            {"id": "ui", "label": "interface"},
                            {"id": "api", "label": "api", "description": "routes and schemas"},
                        ],
                        "allow_free_text": True,
                    },
                    {
                        "id": "proof",
                        "prompt": "Which proof should run?",
                        "selection": "multiple",
                        "choices": ["browser", "tests", "computer"],
                    },
                ],
            }
        )

    def test_normalizes_one_to_four_questions_and_choice_metadata(self):
        request = self.request()
        self.assertEqual(request["title"], "Choose the next pass")
        self.assertEqual(request["questions"][0]["selection"], "single")
        self.assertEqual(request["questions"][1]["choices"][0]["id"], "choice_1")
        self.assertEqual(request["questions"][0]["free_text_label"], "another answer")

    def test_accepts_single_multiple_and_optional_free_text_answers(self):
        answer = normalize_answer(
            self.request(),
            {
                "answers": {
                    "scope": {"selected": "ui", "free_text": "include phone width"},
                    "proof": {"selected": ["choice_1", "choice_3"]},
                }
            },
        )
        self.assertFalse(answer["cancelled"])
        self.assertEqual(answer["answers"]["scope"]["selected"], ["ui"])
        self.assertEqual(answer["answers"]["proof"]["selected"], ["choice_1", "choice_3"])

    def test_cancel_is_explicit_and_needs_no_answers(self):
        self.assertEqual(
            normalize_answer(self.request(), {"cancelled": True}),
            {"cancelled": True, "answers": {}},
        )

    def test_rejects_unsafe_or_ambiguous_shapes(self):
        with self.assertRaisesRegex(ValueError, "questions_count_invalid"):
            normalize_request({"questions": []})
        with self.assertRaisesRegex(ValueError, "question_choices_count_invalid"):
            normalize_request(
                {"questions": [{"id": "one", "prompt": "pick", "choices": ["only"]}]}
            )
        with self.assertRaisesRegex(ValueError, "question_single_choice_required"):
            normalize_answer(
                self.request(),
                {
                    "answers": {
                        "scope": {"selected": ["ui", "api"]},
                        "proof": {"selected": ["choice_1"]},
                    }
                },
            )
        with self.assertRaisesRegex(ValueError, "question_choice_invalid"):
            normalize_answer(
                self.request(),
                {
                    "answers": {
                        "scope": {"selected": ["unknown"]},
                        "proof": {"selected": ["choice_1"]},
                    }
                },
            )


if __name__ == "__main__":
    unittest.main()
