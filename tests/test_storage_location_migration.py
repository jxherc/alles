import json
import os
import tempfile
import unittest

from sqlalchemy import create_engine, text

from core.migrations import m0033_storage_locations


class StorageLocationMigrationTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.path}")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE file_tags (id TEXT PRIMARY KEY, path TEXT UNIQUE, tags TEXT, "
                    "color TEXT, starred BOOLEAN, created_at DATETIME)"
                )
            )
            conn.execute(text("CREATE INDEX ix_file_tags_path ON file_tags(path)"))
            conn.execute(
                text(
                    "CREATE TABLE file_versions (id TEXT PRIMARY KEY, path TEXT, sha TEXT, "
                    "size INTEGER, stored TEXT, created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE file_comments (id TEXT PRIMARY KEY, path TEXT, body TEXT, "
                    "author TEXT, parent_id TEXT, resolved BOOLEAN, created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE trash_items (id TEXT PRIMARY KEY, kind TEXT, ref TEXT, name TEXT, "
                    "payload TEXT, trashed_at DATETIME, expires_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE shares (id TEXT PRIMARY KEY, token TEXT, kind TEXT, ref TEXT, "
                    "level TEXT, expires_at TEXT, password_hash TEXT, created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE index_chunks (id TEXT PRIMARY KEY, kind TEXT, ref TEXT, "
                    "chunk_no INTEGER, text TEXT, vec TEXT, created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO file_tags VALUES "
                    "('tag-1','docs\\note.md','work','purple',1,'2026-01-01')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO file_versions VALUES "
                    "('version-1','docs/note.md','abc123',7,'blob-1','2026-01-02')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO file_comments VALUES "
                    "('comment-1','docs/note.md','keep me','me',NULL,0,'2026-01-03')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO trash_items VALUES "
                    "('trash-file','file','docs/note.md','note.md','{}','2026-01-04',NULL),"
                    "('trash-photo','photo','photo-1','photo.jpg','{}','2026-01-04',NULL)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO shares VALUES "
                    "('share-file','token-file','file','docs/note.md','view','','','2026-01-05'),"
                    "('share-folder','token-folder','folder','docs','view','','','2026-01-05'),"
                    "('share-doc','token-doc','doc','note.md','view','','','2026-01-05')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO index_chunks VALUES "
                    "('index-file','file','docs/note.md',0,'hello','','2026-01-06'),"
                    "('index-doc','doc','note.md',0,'hello','','2026-01-06')"
                )
            )

    def tearDown(self):
        self.engine.dispose()
        os.remove(self.path)

    def _snapshot(self):
        with self.engine.connect() as conn:
            tables = [
                "storage_locations",
                "file_tags",
                "file_versions",
                "file_comments",
                "trash_items",
                "shares",
                "index_chunks",
                "file_operations",
                "storage_location_migration_audits",
            ]
            return {
                table: conn.execute(text(f'SELECT * FROM "{table}" ORDER BY 1')).fetchall()
                for table in tables
            }

    def test_backfills_every_file_identity_and_is_repeatable(self):
        with self.engine.begin() as conn:
            m0033_storage_locations.up(conn)

        with self.engine.connect() as conn:
            default = conn.execute(
                text("SELECT id,kind,access,is_default FROM storage_locations")
            ).one()
            self.assertEqual(default, ("default-local", "local", "managed", 1))
            tag = conn.execute(
                text("SELECT path,location_id,normalized_path,tags,starred FROM file_tags")
            ).one()
            normalized_tag_path = "docs/note.md" if os.name == "nt" else "docs\\note.md"
            self.assertEqual(
                tag,
                ("docs\\note.md", "default-local", normalized_tag_path, "work", 1),
            )
            version = conn.execute(
                text("SELECT location_id,normalized_path,sha,stored FROM file_versions")
            ).one()
            self.assertEqual(version, ("default-local", "docs/note.md", "abc123", "blob-1"))
            comment = conn.execute(
                text("SELECT location_id,normalized_path,body FROM file_comments")
            ).one()
            self.assertEqual(comment, ("default-local", "docs/note.md", "keep me"))
            self.assertEqual(
                conn.execute(
                    text(
                        "SELECT location_id,normalized_path FROM trash_items WHERE id='trash-file'"
                    )
                ).one(),
                ("default-local", "docs/note.md"),
            )
            self.assertEqual(
                conn.execute(
                    text(
                        "SELECT location_id,normalized_path FROM trash_items WHERE id='trash-photo'"
                    )
                ).one(),
                (None, None),
            )
            self.assertEqual(
                conn.execute(
                    text("SELECT location_id,normalized_path FROM shares WHERE id='share-file'")
                ).one(),
                ("default-local", "docs/note.md"),
            )
            self.assertEqual(
                conn.execute(
                    text("SELECT location_id,normalized_path FROM shares WHERE id='share-folder'")
                ).one(),
                ("default-local", "docs"),
            )
            self.assertEqual(
                conn.execute(
                    text(
                        "SELECT location_id,normalized_path FROM index_chunks WHERE id='index-file'"
                    )
                ).one(),
                ("default-local", "docs/note.md"),
            )
            audit = json.loads(
                conn.execute(
                    text(
                        "SELECT counts_json FROM storage_location_migration_audits "
                        "WHERE id='m0033-default-local'"
                    )
                ).scalar_one()
            )
            self.assertEqual(
                audit,
                {
                    "file_comments": 1,
                    "file_index_chunks": 1,
                    "file_shares": 2,
                    "file_tags": 1,
                    "file_trash_items": 1,
                    "file_versions": 1,
                },
            )

            conn.execute(
                text(
                    "INSERT INTO storage_locations "
                    "(id,name,kind,access,root_path,endpoint,bucket,prefix,config,secret,enabled,"
                    "is_default,created_at,updated_at) VALUES "
                    "('other','other','local','managed','/tmp/other','','','','{}','',1,0,"
                    "'2026-01-01','2026-01-01')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO file_tags "
                    "(id,path,location_id,normalized_path,tags,color,starred,created_at) VALUES "
                    "('tag-2','docs/note.md','other','docs/note.md','','',0,'2026-01-01')"
                )
            )
            conn.commit()

        before = self._snapshot()
        with self.engine.begin() as conn:
            m0033_storage_locations.up(conn)
        self.assertEqual(self._snapshot(), before)

    def test_preserves_legacy_root_file_tag_metadata(self):
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM file_tags"))
            conn.execute(
                text(
                    "INSERT INTO file_tags VALUES "
                    "('root-tag','/','archive','purple',1,'2026-01-01')"
                )
            )
            m0033_storage_locations.up(conn)

        with self.engine.connect() as conn:
            self.assertEqual(
                conn.execute(
                    text(
                        "SELECT path,location_id,normalized_path,tags,color,starred "
                        "FROM file_tags WHERE id='root-tag'"
                    )
                ).one(),
                ("/", "default-local", "", "archive", "purple", 1),
            )

    def test_preserves_legacy_root_comment_and_folder_share_identities(self):
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO file_comments VALUES "
                    "('root-comment','/','root note','me',NULL,0,'2026-01-07')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO shares VALUES "
                    "('root-share','token-root','folder','.','view','','','2026-01-07')"
                )
            )
            m0033_storage_locations.up(conn)

        with self.engine.connect() as conn:
            self.assertEqual(
                conn.execute(
                    text(
                        "SELECT location_id,normalized_path FROM file_comments "
                        "WHERE id='root-comment'"
                    )
                ).one(),
                ("default-local", ""),
            )
            self.assertEqual(
                conn.execute(
                    text("SELECT location_id,normalized_path FROM shares WHERE id='root-share'")
                ).one(),
                ("default-local", ""),
            )

        before = self._snapshot()
        with self.engine.begin() as conn:
            m0033_storage_locations.up(conn)
        self.assertEqual(self._snapshot(), before)

    @unittest.skipIf(os.name == "nt", "backslash is a path separator on Windows")
    def test_preserves_distinct_posix_backslash_and_slash_paths(self):
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM file_tags"))
            conn.execute(
                text(
                    "INSERT INTO file_tags VALUES "
                    "('literal-backslash','folder\\name.txt','one','',0,'2026-01-01'),"
                    "('path-separator','folder/name.txt','two','',0,'2026-01-01')"
                )
            )
            m0033_storage_locations.up(conn)

        with self.engine.connect() as conn:
            identities = (
                conn.execute(text("SELECT normalized_path FROM file_tags ORDER BY id"))
                .scalars()
                .all()
            )
        self.assertEqual(identities, ["folder\\name.txt", "folder/name.txt"])

    def test_merges_legacy_tag_rows_that_normalize_to_one_identity(self):
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM file_tags"))
            conn.execute(
                text(
                    "INSERT INTO file_tags VALUES "
                    "('collision-a','/folder/note.md','work,shared','',0,'2026-01-02'),"
                    "('collision-b','folder/note.md','shared,urgent','purple',1,'2026-01-01')"
                )
            )
            m0033_storage_locations.up(conn)

        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id,path,location_id,normalized_path,tags,color,starred,created_at "
                    "FROM file_tags"
                )
            ).one()
        self.assertEqual(
            row,
            (
                "collision-a",
                "/folder/note.md",
                "default-local",
                "folder/note.md",
                "work,shared,urgent",
                "purple",
                1,
                "2026-01-01",
            ),
        )
        before = self._snapshot()
        with self.engine.begin() as conn:
            m0033_storage_locations.up(conn)
        self.assertEqual(self._snapshot(), before)

    def test_unsafe_legacy_path_blocks_without_dropping_the_old_table(self):
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO file_tags VALUES ('unsafe','../escape.txt','','',0,'2026-01-01')")
            )
        with self.assertRaisesRegex(RuntimeError, "unsafe legacy Files path"):
            with self.engine.begin() as conn:
                m0033_storage_locations.up(conn)
        with self.engine.connect() as conn:
            self.assertEqual(
                conn.execute(text("SELECT path FROM file_tags WHERE id='unsafe'")).scalar_one(),
                "../escape.txt",
            )

    def test_empty_legacy_database_does_not_gain_owner_data(self):
        with self.engine.begin() as conn:
            for table in (
                "file_tags",
                "file_versions",
                "file_comments",
                "trash_items",
                "shares",
                "index_chunks",
            ):
                conn.execute(text(f'DELETE FROM "{table}"'))
            m0033_storage_locations.up(conn)
        with self.engine.connect() as conn:
            self.assertEqual(
                conn.execute(text("SELECT COUNT(*) FROM storage_locations")).scalar_one(),
                0,
            )
            self.assertEqual(
                conn.execute(text("SELECT COUNT(*) FROM file_operations")).scalar_one(),
                0,
            )
