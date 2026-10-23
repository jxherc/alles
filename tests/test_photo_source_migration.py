import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from core.database import Base
from core.migrations import m0017_photo_sources
from core.migrations.runner import run_migrations


class PhotoSourceMigrationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.execute(text("CREATE TABLE photos (id TEXT PRIMARY KEY)"))

    def tearDown(self):
        self.engine.dispose()

    def test_adds_stable_source_columns(self):
        run_migrations(self.engine, modules=[m0017_photo_sources])
        with self.engine.connect() as conn:
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(photos)"))}
        self.assertTrue({"source", "source_id", "source_asset_id", "source_modified_at"} <= columns)

    def test_partial_unique_index_allows_uploads_but_rejects_duplicate_source_ids(self):
        run_migrations(self.engine, modules=[m0017_photo_sources])
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO photos(id) VALUES ('upload-1'), ('upload-2')"))
            conn.execute(
                text(
                    "INSERT INTO photos(id,source,source_id) "
                    "VALUES ('apple-1','apple_photos','asset-1:photo')"
                )
            )
            with self.assertRaises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO photos(id,source,source_id) "
                        "VALUES ('apple-2','apple_photos','asset-1:photo')"
                    )
                )

    def test_model_schema_enforces_the_same_source_identity(self):
        engine = create_engine("sqlite://")
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO photos(id,filename) VALUES "
                        "('upload-1','upload-1.png'), ('upload-2','upload-2.png')"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO photos(id,filename,source,source_id) "
                        "VALUES ('apple-1','apple-1.png','apple_photos','asset-1:photo')"
                    )
                )
                with self.assertRaisesRegex(
                    IntegrityError,
                    r"UNIQUE constraint failed: photos.source, photos.source_id",
                ):
                    conn.execute(
                        text(
                            "INSERT INTO photos(id,filename,source,source_id) "
                            "VALUES ('apple-2','apple-2.png','apple_photos','asset-1:photo')"
                        )
                    )
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
