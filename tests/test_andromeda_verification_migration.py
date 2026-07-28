import unittest

from sqlalchemy import create_engine, inspect, text

from core.migrations import m0045_andromeda_verification_jobs as migration


class AndromedaVerificationMigrationTest(unittest.TestCase):
    def test_adds_saved_fields_and_durable_job_table_idempotently(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE andromeda_saved_searches ("
                    "id VARCHAR PRIMARY KEY, query VARCHAR NOT NULL)"
                )
            )
            migration.up(conn)
            migration.up(conn)
        inspector = inspect(engine)
        saved_columns = {
            column["name"] for column in inspector.get_columns("andromeda_saved_searches")
        }
        self.assertTrue({"verification_json", "verifier_model_json"} <= saved_columns)
        self.assertIn("andromeda_verification_jobs", inspector.get_table_names())
        job_columns = {
            column["name"] for column in inspector.get_columns("andromeda_verification_jobs")
        }
        self.assertTrue(
            {
                "id",
                "query",
                "answer_json",
                "results_json",
                "evidence_json",
                "model_json",
                "result_json",
                "status",
                "error_code",
                "checked_at",
                "created_at",
                "updated_at",
            }
            <= job_columns
        )
        self.assertIn(
            "ix_andromeda_verification_jobs_status",
            {index["name"] for index in inspector.get_indexes("andromeda_verification_jobs")},
        )


if __name__ == "__main__":
    unittest.main()
