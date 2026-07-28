"""Validation for Aide's structured, selectable user questions."""

import re


_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _text(value, *, field: str, limit: int) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field}_required")
    if len(result) > limit:
        raise ValueError(f"{field}_too_long")
    return result


def normalize_request(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("question_request_invalid")
    raw_questions = value.get("questions")
    if not isinstance(raw_questions, list) or not 1 <= len(raw_questions) <= 4:
        raise ValueError("questions_count_invalid")

    questions = []
    question_ids = set()
    for index, raw in enumerate(raw_questions, 1):
        if not isinstance(raw, dict):
            raise ValueError("question_invalid")
        question_id = str(raw.get("id") or f"question_{index}").strip()
        if not _ID_RE.fullmatch(question_id) or question_id in question_ids:
            raise ValueError("question_id_invalid")
        question_ids.add(question_id)
        prompt = _text(raw.get("prompt"), field="question_prompt", limit=500)
        selection = str(raw.get("selection") or "single").strip().lower()
        if selection not in {"single", "multiple"}:
            raise ValueError("question_selection_invalid")
        raw_choices = raw.get("choices")
        if not isinstance(raw_choices, list) or not 2 <= len(raw_choices) <= 5:
            raise ValueError("question_choices_count_invalid")

        choices = []
        choice_ids = set()
        for choice_index, raw_choice in enumerate(raw_choices, 1):
            if isinstance(raw_choice, str):
                raw_choice = {"id": f"choice_{choice_index}", "label": raw_choice}
            if not isinstance(raw_choice, dict):
                raise ValueError("question_choice_invalid")
            choice_id = str(raw_choice.get("id") or f"choice_{choice_index}").strip()
            if not _ID_RE.fullmatch(choice_id) or choice_id in choice_ids:
                raise ValueError("question_choice_id_invalid")
            choice_ids.add(choice_id)
            choices.append(
                {
                    "id": choice_id,
                    "label": _text(raw_choice.get("label"), field="question_choice_label", limit=160),
                    "description": str(raw_choice.get("description") or "").strip()[:300],
                }
            )

        questions.append(
            {
                "id": question_id,
                "prompt": prompt,
                "selection": selection,
                "choices": choices,
                "allow_free_text": bool(raw.get("allow_free_text")),
                "free_text_label": str(raw.get("free_text_label") or "another answer").strip()[:80]
                or "another answer",
            }
        )

    return {
        "title": str(value.get("title") or "Aide needs your input").strip()[:120]
        or "Aide needs your input",
        "questions": questions,
    }


def normalize_answer(request: dict, value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("question_answer_invalid")
    if value.get("cancelled") is True:
        return {"cancelled": True, "answers": {}}
    raw_answers = value.get("answers")
    if not isinstance(raw_answers, dict):
        raise ValueError("question_answers_required")

    answers = {}
    for question in request.get("questions", []):
        raw = raw_answers.get(question["id"])
        if not isinstance(raw, dict):
            raise ValueError("question_answer_required")
        selected = raw.get("selected", [])
        if isinstance(selected, str):
            selected = [selected]
        if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
            raise ValueError("question_selection_invalid")
        selected = list(dict.fromkeys(item.strip() for item in selected if item.strip()))
        allowed = {choice["id"] for choice in question["choices"]}
        if any(item not in allowed for item in selected):
            raise ValueError("question_choice_invalid")
        if question["selection"] == "single" and len(selected) > 1:
            raise ValueError("question_single_choice_required")
        free_text = str(raw.get("free_text") or "").strip()
        if len(free_text) > 2000:
            raise ValueError("question_free_text_too_long")
        if free_text and not question["allow_free_text"]:
            raise ValueError("question_free_text_forbidden")
        if not selected and not free_text:
            raise ValueError("question_answer_required")
        answers[question["id"]] = {"selected": selected, "free_text": free_text}

    if set(raw_answers) != {question["id"] for question in request.get("questions", [])}:
        raise ValueError("question_answer_unknown")
    return {"cancelled": False, "answers": answers}
