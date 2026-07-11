import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import text

import core.database as database
from core.database import Connection, McpServer
from services import secretstore
from tests._client import ApiTest


class ConnectorSecretMigrationTest(ApiTest):
    def test_plaintext_database_credentials_are_migrated(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(secretstore, "_KEY_FILE", Path(temp) / "secret.key"),
        ):
            secretstore._key = None
            secretstore._key_path = None
            secretstore._keys = {}
            secretstore._active_id = ""
            with self.eng.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO connections (id,service,token,meta,created_at) "
                        "VALUES ('c','github','plain-token','{\"secret\":\"plain\"}',"
                        "'2026-01-01 00:00:00')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO mcp_servers "
                        "(id,name,transport,command,args,url,env,headers,enabled,disabled_tools,created_at) "
                        "VALUES ('m','mcp','sse','','[\"--token\",\"plain\"]',"
                        "'https://example.test?token=plain','{\"TOKEN\":\"plain\"}',"
                        "'{\"Authorization\":\"plain\"}',1,'[]','2026-01-01 00:00:00')"
                    )
                )

            self.assertEqual(database._encrypt_plaintext_secrets(), 6)
            with self.eng.connect() as connection:
                values = connection.execute(text("SELECT token,meta FROM connections")).one()
                mcp_values = connection.execute(
                    text("SELECT args,url,env,headers FROM mcp_servers")
                ).one()
            self.assertTrue(all(value.startswith("enc2:") for value in (*values, *mcp_values)))
            db = self.db()
            self.assertEqual(db.get(Connection, "c").token, "plain-token")
            self.assertEqual(db.get(McpServer, "m").env_dict()["TOKEN"], "plain")
            db.close()


if __name__ == "__main__":
    unittest.main()
