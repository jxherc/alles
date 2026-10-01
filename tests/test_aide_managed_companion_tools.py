import asyncio
import unittest
from unittest import mock

from services import agent_tools


class AideManagedCompanionToolTests(unittest.TestCase):
    @mock.patch("services.managed_companion_clients.adguard_dashboard")
    def test_adguard_dashboard_stays_typed_and_read_only(self, dashboard):
        dashboard.return_value = {"connected": True, "stats": {"num_dns_queries": 8}}
        result = asyncio.run(agent_tools.execute("adguard_dashboard", {}))
        self.assertEqual(result["stats"]["num_dns_queries"], 8)

    @mock.patch("services.managed_companion_clients.set_adguard_filtering")
    def test_adguard_filtering_uses_the_documented_default_interval(self, filtering):
        filtering.return_value = {"ok": True, "enabled": True, "interval": 24}
        result = asyncio.run(agent_tools.execute("adguard_filtering_set", {"enabled": True}))
        filtering.assert_called_once_with(True, 24)
        self.assertEqual(result["interval"], 24)

    @mock.patch("services.managed_companion_clients.create_npm_proxy_host")
    def test_npm_proxy_creation_never_accepts_credentials(self, create):
        create.return_value = {"id": 4, "enabled": True}
        result = asyncio.run(
            agent_tools.execute(
                "npm_proxy_host_create",
                {
                    "domain_names": ["home.example"],
                    "forward_scheme": "http",
                    "forward_host": "127.0.0.1",
                    "forward_port": 6769,
                },
            )
        )
        self.assertEqual(result["id"], 4)
        schema = next(
            item["function"]["parameters"]
            for item in agent_tools.APP_TOOL_DEFS
            if item["function"]["name"] == "npm_proxy_host_create"
        )
        self.assertNotIn("password", str(schema).lower())
        self.assertNotIn("token", str(schema).lower())


if __name__ == "__main__":
    unittest.main()
