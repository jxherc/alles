import unittest

from sqlalchemy import create_engine, text

from core.migrations import m0034_file_transfer_state


class FileTransferStateMigrationTests(unittest.TestCase):
    def test_offline_table_is_idempotent(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text("CREATE TABLE storage_locations (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("INSERT INTO storage_locations (id) VALUES ('local')"))
            m0034_file_transfer_state.up(conn)
            m0034_file_transfer_state.up(conn)
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(offline_files)"))}
            self.assertIn("location_id", columns)
            self.assertIn("checksum", columns)
            conn.execute(
                text(
                    "INSERT INTO offline_files "
                    "(id,location_id,normalized_path,state) VALUES ('one','local','a.txt','ready')"
                )
            )
            with self.assertRaises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO offline_files "
                        "(id,location_id,normalized_path,state) VALUES "
                        "('two','local','a.txt','ready')"
                    )
                )
        engine.dispose()
