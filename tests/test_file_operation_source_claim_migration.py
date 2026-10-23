import unittest
from unittest import mock

from sqlalchemy import create_engine, text

from core.migrations import (
    m0035_file_operation_source_claims,
    m0042_file_operation_source_claim_roots,
    m0044_local_source_claim_casefold,
)


class FileOperationSourceClaimMigrationTests(unittest.TestCase):
    def test_migration_canonicalizes_existing_unicode_local_claims(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text("CREATE TABLE storage_locations (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("INSERT INTO storage_locations (id) VALUES ('local')"))
            conn.execute(text("CREATE TABLE file_operations (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("INSERT INTO file_operations (id) VALUES ('unicode-op')"))
            m0035_file_operation_source_claims.up(conn)
            conn.execute(
                text(
                    "INSERT INTO file_operation_source_claims "
                    "(operation_id,location_id,claim_scope,normalized_path) "
                    "VALUES ('unicode-op','local','local-physical','/DATA/CAFÉ/STRASSE')"
                )
            )

            with mock.patch.object(
                m0044_local_source_claim_casefold,
                "local_claim_case_insensitive",
                return_value=True,
            ):
                m0044_local_source_claim_casefold.up(conn)
                m0044_local_source_claim_casefold.up(conn)

            self.assertEqual(
                conn.execute(
                    text(
                        "SELECT normalized_path FROM file_operation_source_claims "
                        "WHERE operation_id='unicode-op'"
                    )
                ).scalar(),
                "/data/café/strasse",
            )
        engine.dispose()

    def test_migration_rejects_legacy_claims_that_casefold_to_overlapping_trees(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE storage_locations (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("INSERT INTO storage_locations (id) VALUES ('local')"))
            conn.execute(text("CREATE TABLE file_operations (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("INSERT INTO file_operations (id) VALUES ('one'),('two')"))
            m0035_file_operation_source_claims.up(conn)
            conn.execute(
                text(
                    "INSERT INTO file_operation_source_claims "
                    "(operation_id,location_id,claim_scope,normalized_path) VALUES "
                    "('one','local','local-physical','/data/straße'),"
                    "('two','local','local-physical','/data/STRASSE/child')"
                )
            )

            with (
                mock.patch.object(
                    m0044_local_source_claim_casefold,
                    "local_claim_case_insensitive",
                    return_value=True,
                ),
                self.assertRaisesRegex(RuntimeError, "overlap after Unicode casefolding"),
            ):
                m0044_local_source_claim_casefold.up(conn)

            self.assertEqual(
                conn.execute(
                    text(
                        "SELECT normalized_path FROM file_operation_source_claims "
                        "ORDER BY operation_id"
                    )
                )
                .scalars()
                .all(),
                ["/data/straße", "/data/STRASSE/child"],
            )
            with self.assertRaises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO file_operation_source_claims "
                        "(operation_id,location_id,claim_scope,normalized_path) "
                        "VALUES ('three','local','local-physical','/data/straße/note')"
                    )
                )
        engine.dispose()

    def test_migration_preserves_distinct_case_sensitive_legacy_claims(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE storage_locations (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("INSERT INTO storage_locations (id) VALUES ('local')"))
            conn.execute(text("CREATE TABLE file_operations (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("INSERT INTO file_operations (id) VALUES ('upper'),('lower')"))
            m0035_file_operation_source_claims.up(conn)
            conn.execute(
                text(
                    "INSERT INTO file_operation_source_claims "
                    "(operation_id,location_id,claim_scope,normalized_path) VALUES "
                    "('upper','local','local-physical','/data/A'),"
                    "('lower','local','local-physical','/data/a')"
                )
            )

            with mock.patch.object(
                m0044_local_source_claim_casefold,
                "local_claim_case_insensitive",
                return_value=False,
            ):
                m0044_local_source_claim_casefold.up(conn)

            self.assertEqual(
                conn.execute(
                    text(
                        "SELECT claim_scope, normalized_path FROM file_operation_source_claims "
                        "ORDER BY operation_id"
                    )
                ).all(),
                [("local-physical-cs", "/data/a"), ("local-physical-cs", "/data/A")],
            )
        engine.dispose()

    def test_source_claims_are_idempotent_and_reject_path_overlap(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text("CREATE TABLE storage_locations (id VARCHAR PRIMARY KEY)"))
            conn.execute(
                text(
                    "INSERT INTO storage_locations (id) VALUES "
                    "('local'),('local-alias'),('remote-one'),('remote-two')"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE file_operations ("
                    "id VARCHAR PRIMARY KEY, action VARCHAR NOT NULL, "
                    "source_location_id VARCHAR NOT NULL, source_path VARCHAR NOT NULL)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO file_operations "
                    "(id,action,source_location_id,source_path) VALUES "
                    "('folder-op','move','local','folder'),"
                    "('child-op','move','local-alias','folder/note.txt'),"
                    "('case-child-op','move','local-alias','FOLDER/other.txt'),"
                    "('sibling-op','move','local','sibling/note.txt'),"
                    "('root-op','move','local',''),"
                    "('remote-one-op','move','remote-one','folder'),"
                    "('remote-case-op','move','remote-one','FOLDER/other.txt'),"
                    "('remote-two-op','move','remote-two','folder')"
                )
            )
            m0035_file_operation_source_claims.up(conn)
            m0035_file_operation_source_claims.up(conn)
            m0042_file_operation_source_claim_roots.up(conn)
            m0042_file_operation_source_claim_roots.up(conn)
            m0044_local_source_claim_casefold.up(conn)
            m0044_local_source_claim_casefold.up(conn)
            conn.execute(
                text(
                    "INSERT INTO file_operation_source_claims "
                    "(operation_id,location_id,claim_scope,normalized_path) "
                    "VALUES ('folder-op','local','local-physical-ci','/data/folder')"
                )
            )
            with self.assertRaises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO file_operation_source_claims "
                        "(operation_id,location_id,claim_scope,normalized_path) "
                        "VALUES ('child-op','local-alias','local-physical-ci',"
                        "'/data/folder/note.txt')"
                    )
                )
            with self.assertRaises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO file_operation_source_claims "
                        "(operation_id,location_id,claim_scope,normalized_path) "
                        "VALUES ('case-child-op','local-alias','local-physical-ci',"
                        "'/data/folder/other.txt')"
                    )
                )
            conn.execute(
                text(
                    "INSERT INTO file_operation_source_claims "
                    "(operation_id,location_id,claim_scope,normalized_path) "
                    "VALUES ('sibling-op','local','local-physical-ci','/data/sibling/note.txt')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO file_operation_source_claims "
                    "(operation_id,location_id,claim_scope,normalized_path) VALUES "
                    "('remote-one-op','remote-one','location:remote-one','folder'),"
                    "('remote-case-op','remote-one','location:remote-one','FOLDER/other.txt'),"
                    "('remote-two-op','remote-two','location:remote-two','folder')"
                )
            )
            with self.assertRaises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO file_operation_source_claims "
                        "(operation_id,location_id,claim_scope,normalized_path) "
                        "VALUES ('root-op','remote-one','location:remote-one','')"
                    )
                )
            conn.execute(text("DELETE FROM file_operations WHERE id='folder-op'"))
            self.assertIsNone(
                conn.execute(
                    text(
                        "SELECT operation_id FROM file_operation_source_claims "
                        "WHERE operation_id='folder-op'"
                    )
                ).first()
            )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
