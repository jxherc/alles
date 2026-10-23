"""m0046 - structured, durable Jarvis questions and answers."""

from core.migrations.runner import add_column

VERSION = 46
NAME = "jarvis_structured_questions"


def up(conn):
    add_column(
        conn,
        "jarvis_run_prompts",
        "question_schema",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    add_column(
        conn,
        "jarvis_run_prompts",
        "answer_data",
        "TEXT NOT NULL DEFAULT '{}'",
    )
