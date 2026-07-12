import unittest

from sqlalchemy import create_engine, text

from core.migrations import m0022_model_catalogs as migration


class ModelCatalogMigrationTest(unittest.TestCase):
    def test_adds_catalog_and_health_columns(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE model_endpoints (id TEXT PRIMARY KEY)"))
            migration.up(conn)
            migration.up(conn)
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(model_endpoints)"))}
        self.assertTrue(
            {
                "provider_adapter",
                "catalog_status",
                "catalog_source",
                "catalog_error",
                "catalog_refreshed_at",
                "unavailable_models",
                "model_metadata",
                "health_status",
                "last_tested_at",
                "last_error_code",
            }.issubset(columns)
        )


if __name__ == "__main__":
    unittest.main()
