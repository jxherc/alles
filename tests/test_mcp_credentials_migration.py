import unittest

from sqlalchemy import create_engine, text

from core.migrations import m0020_mcp_credentials as migration


class McpCredentialsMigrationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE mcp_servers ("
                    "id TEXT PRIMARY KEY, name TEXT NOT NULL, transport TEXT, command TEXT, "
                    "args TEXT, url TEXT, enabled BOOLEAN, disabled_tools TEXT, created_at TEXT)"
                )
            )

    def test_adds_env_and_headers_without_changing_existing_server(self):
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO mcp_servers "
                    "(id,name,transport,command,args,url,enabled,disabled_tools,created_at) "
                    "VALUES ('one','server','stdio','run','[]','',1,'[]','')"
                )
            )
            migration.up(connection)
            migration.up(connection)
            row = connection.execute(
                text("SELECT name,env,headers FROM mcp_servers WHERE id='one'")
            ).one()
        self.assertEqual(tuple(row), ("server", "{}", "{}"))


if __name__ == "__main__":
    unittest.main()
