import unittest

from sqlalchemy import create_engine, inspect

from core.migrations import m0021_audit_records as migration


class AuditRecordsMigrationTest(unittest.TestCase):
    def test_creates_audit_table_and_indexes(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            migration.up(conn)
            migration.up(conn)
        inspector = inspect(engine)
        self.assertIn("audit_records", inspector.get_table_names())
        columns = {column["name"] for column in inspector.get_columns("audit_records")}
        self.assertEqual(
            columns,
            {
                "id",
                "action",
                "outcome",
                "actor",
                "target",
                "request_id",
                "details",
                "created_at",
            },
        )
        self.assertEqual(
            {index["name"] for index in inspector.get_indexes("audit_records")},
            {"ix_audit_records_action", "ix_audit_records_created_at"},
        )


if __name__ == "__main__":
    unittest.main()
