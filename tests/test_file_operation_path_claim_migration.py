import unittest

from sqlalchemy import create_engine, text

from core.database import FileOperationPathClaim
from core.migrations import m0036_file_operation_path_claims


class FileOperationPathClaimMigrationTests(unittest.TestCase):
    def _create_legacy_schema(self, conn):
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("CREATE TABLE storage_locations (id VARCHAR PRIMARY KEY)"))
        conn.execute(
            text("INSERT INTO storage_locations (id) VALUES ('local'),('local-alias'),('remote')")
        )
        conn.execute(text("CREATE TABLE file_operations (id VARCHAR PRIMARY KEY)"))
        conn.execute(
            text(
                "INSERT INTO file_operations (id) VALUES "
                "('legacy-op'),('same-op'),('equal-op'),('child-op'),"
                "('ancestor-op'),('update-op'),('other-scope-op'),"
                "('root-op'),('root-child-op'),('replacement-op')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE file_operation_source_claims ("
                "operation_id VARCHAR PRIMARY KEY, location_id VARCHAR NOT NULL, "
                "claim_scope VARCHAR NOT NULL, normalized_path VARCHAR NOT NULL, "
                "created_at DATETIME, "
                "FOREIGN KEY(operation_id) REFERENCES file_operations(id) ON DELETE CASCADE, "
                "FOREIGN KEY(location_id) REFERENCES storage_locations(id) ON DELETE RESTRICT)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO file_operation_source_claims "
                "(operation_id,location_id,claim_scope,normalized_path,created_at) "
                "VALUES ('legacy-op','local','local-physical','/data/Folder','2026-07-18')"
            )
        )

    def test_model_supports_multiple_claims_per_operation(self):
        table = FileOperationPathClaim.__table__
        self.assertEqual(table.name, "file_operation_path_claims")
        self.assertTrue(table.c.id.primary_key)
        self.assertFalse(table.c.operation_id.primary_key)

        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text("CREATE TABLE storage_locations (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("INSERT INTO storage_locations (id) VALUES ('local')"))
            conn.execute(text("CREATE TABLE file_operations (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("INSERT INTO file_operations (id) VALUES ('one'),('two')"))
            table.create(conn)
            conn.execute(
                text(
                    "INSERT INTO file_operation_path_claims "
                    "(id,operation_id,location_id,claim_scope,normalized_path) VALUES "
                    "('one-parent','one','local','scope','folder'),"
                    "('one-child','one','local','scope','folder/note.txt')"
                )
            )
            with self.assertRaises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO file_operation_path_claims "
                        "(id,operation_id,location_id,claim_scope,normalized_path) "
                        "VALUES ('two-child','two','local','scope','folder/other.txt')"
                    )
                )
            triggers = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='trigger' AND tbl_name='file_operation_path_claims'"
                    )
                )
            }
            self.assertEqual(
                triggers,
                {
                    "trg_file_operation_path_claim_overlap_insert",
                    "trg_file_operation_path_claim_overlap_update",
                },
            )
        engine.dispose()

    def test_local_claim_overlap_is_case_insensitive_but_remote_claims_are_not(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text("CREATE TABLE storage_locations (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("INSERT INTO storage_locations (id) VALUES ('local'),('remote')"))
            conn.execute(text("CREATE TABLE file_operations (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("INSERT INTO file_operations (id) VALUES ('one'),('two')"))
            FileOperationPathClaim.__table__.create(conn)
            conn.execute(
                text(
                    "INSERT INTO file_operation_path_claims "
                    "(id,operation_id,location_id,claim_scope,normalized_path) "
                    "VALUES ('one','one','local','local-physical-ci','/data/docs')"
                )
            )
            with self.assertRaises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO file_operation_path_claims "
                        "(id,operation_id,location_id,claim_scope,normalized_path) "
                        "VALUES ('two','two','local','local-physical-ci','/data/docs/file.md')"
                    )
                )
            conn.execute(text("DELETE FROM file_operation_path_claims"))
            conn.execute(
                text(
                    "INSERT INTO file_operation_path_claims "
                    "(id,operation_id,location_id,claim_scope,normalized_path) VALUES "
                    "('one','one','remote','s3:test','Docs/File.md'),"
                    "('two','two','remote','s3:test','docs/file.md')"
                )
            )
        engine.dispose()

    def test_migration_is_idempotent_migrates_legacy_and_enforces_overlap(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            self._create_legacy_schema(conn)
            m0036_file_operation_path_claims.up(conn)
            m0036_file_operation_path_claims.up(conn)

            columns = {
                row[1]: {"not_null": bool(row[3]), "primary_key": bool(row[5])}
                for row in conn.execute(text("PRAGMA table_info(file_operation_path_claims)"))
            }
            self.assertEqual(columns["id"], {"not_null": True, "primary_key": True})

            migrated = conn.execute(
                text(
                    "SELECT id,operation_id,location_id,claim_scope,normalized_path,created_at "
                    "FROM file_operation_path_claims WHERE operation_id='legacy-op'"
                )
            ).one()
            self.assertEqual(
                tuple(migrated),
                (
                    "legacy-source:legacy-op",
                    "legacy-op",
                    "local",
                    "local-physical",
                    "/data/folder",
                    "2026-07-18",
                ),
            )
            self.assertEqual(
                conn.execute(text("SELECT count(*) FROM file_operation_path_claims")).scalar(),
                1,
            )

            # One operation may hold overlapping source/destination identities.
            conn.execute(
                text(
                    "INSERT INTO file_operation_path_claims "
                    "(id,operation_id,location_id,claim_scope,normalized_path) VALUES "
                    "('same-parent','same-op','local-alias','same-operation','/data/folder'),"
                    "('same-child','same-op','local-alias','same-operation',"
                    "'/data/folder/note.txt')"
                )
            )

            for claim_id, operation_id, path in (
                ("equal", "equal-op", "/data/folder"),
                ("child", "child-op", "/data/folder/note.txt"),
                ("ancestor", "ancestor-op", "/data"),
            ):
                with self.assertRaises(Exception):
                    conn.execute(
                        text(
                            "INSERT INTO file_operation_path_claims "
                            "(id,operation_id,location_id,claim_scope,normalized_path) "
                            "VALUES (:id,:operation_id,'local-alias','local-physical',:path)"
                        ),
                        {"id": claim_id, "operation_id": operation_id, "path": path},
                    )

            conn.execute(
                text(
                    "INSERT INTO file_operation_path_claims "
                    "(id,operation_id,location_id,claim_scope,normalized_path) VALUES "
                    "('update','update-op','local','local-physical','/data/sibling'),"
                    "('other-scope','other-scope-op','remote','remote:one','/data/folder')"
                )
            )
            with self.assertRaises(Exception):
                conn.execute(
                    text(
                        "UPDATE file_operation_path_claims SET normalized_path='/data/folder/new' "
                        "WHERE id='update'"
                    )
                )
            conn.execute(
                text(
                    "UPDATE file_operation_path_claims SET operation_id='replacement-op' "
                    "WHERE id='other-scope'"
                )
            )

            conn.execute(
                text(
                    "INSERT INTO file_operation_path_claims "
                    "(id,operation_id,location_id,claim_scope,normalized_path) "
                    "VALUES ('root','root-op','remote','root-scope','')"
                )
            )
            with self.assertRaises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO file_operation_path_claims "
                        "(id,operation_id,location_id,claim_scope,normalized_path) "
                        "VALUES ('root-child','root-child-op','remote','root-scope','folder')"
                    )
                )

            # The old table remains intact for compatibility.
            self.assertEqual(
                conn.execute(
                    text(
                        "SELECT normalized_path FROM file_operation_source_claims "
                        "WHERE operation_id='legacy-op'"
                    )
                ).scalar(),
                "/data/Folder",
            )
            conn.execute(text("DELETE FROM file_operations WHERE id='legacy-op'"))
            self.assertIsNone(
                conn.execute(
                    text(
                        "SELECT operation_id FROM file_operation_path_claims "
                        "WHERE operation_id='legacy-op'"
                    )
                ).first()
            )
        engine.dispose()

    def test_migration_preserves_preexisting_root_and_descendant_recovery_claims(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            self._create_legacy_schema(conn)
            conn.execute(
                text(
                    "INSERT INTO file_operation_source_claims "
                    "(operation_id,location_id,claim_scope,normalized_path,created_at) VALUES "
                    "('root-op','remote','legacy-remote','','2026-07-18'),"
                    "('root-child-op','remote','legacy-remote','folder','2026-07-18')"
                )
            )

            m0036_file_operation_path_claims.up(conn)

            migrated = conn.execute(
                text(
                    "SELECT operation_id,normalized_path FROM file_operation_path_claims "
                    "WHERE claim_scope='legacy-remote' ORDER BY operation_id"
                )
            ).all()
            self.assertEqual(
                [tuple(row) for row in migrated],
                [("root-child-op", "folder"), ("root-op", "")],
            )
            with self.assertRaises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO file_operation_path_claims "
                        "(id,operation_id,location_id,claim_scope,normalized_path) "
                        "VALUES ('replacement','replacement-op','remote','legacy-remote','other')"
                    )
                )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
