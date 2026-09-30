import hashlib
import re
import unittest
from pathlib import Path

from core.database import Base
from services import backup_recovery
from tests.test_route_compatibility import _route_rows

ROOT = Path(__file__).parents[1]
SPECIFICATIONS = ROOT / "specifications.md"


def _mapped_inventory(document: str) -> set[str]:
    match = re.search(
        r"^## database table inventory\n(.*?)(?=^## |\Z)",
        document,
        re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError("mapped-table inventory section is missing")
    section = match.group(1)
    count = re.search(r"\*\*(\d+) mapped tables\*\*", section)
    names = re.findall(r"^\| `([^`]+)` \|", section, re.MULTILINE)
    if not count or len(names) != int(count.group(1)) or len(set(names)) != len(names):
        raise AssertionError("mapped-table count does not match its inventory rows")
    return set(names)


class AfterlifePhase0InventoryTest(unittest.TestCase):
    def test_data_inventory_matches_every_mapped_table_and_root_role(self):
        document = SPECIFICATIONS.read_text("utf-8")

        self.assertEqual(_mapped_inventory(document), set(Base.metadata.tables))
        for role in backup_recovery.LOCATION_ROLES:
            self.assertIn(f"`{role}`", document, f"missing backup root role: {role}")

    def test_trust_map_matches_route_snapshot(self):
        document = SPECIFICATIONS.read_text("utf-8")
        source = (ROOT / "app.py").read_text("utf-8")
        rows = _route_rows()
        digest = hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest()
        router_count = len(re.findall(r"^app\.include_router\(", source, re.MULTILINE))

        self.assertIn(f"- {router_count} included fastapi router modules", document)
        self.assertIn(f"- {len(rows)} http method/path pairs", document)
        self.assertIn(f"- sha-256: `{digest}`", document)
        paths = [row.split(" ", 1)[1] for row in rows]
        groups = {
            "api": sum(path.startswith("/api/") for path in paths),
            "v1": sum(path.startswith("/v1/") for path in paths),
        }
        groups["public"] = len(rows) - groups["api"] - groups["v1"]
        self.assertIn(
            f"- {groups['api']} `/api/*`, {groups['v1']} `/v1/*`, and "
            f"{groups['public']} non-api shell/public pairs",
            document,
        )

    def test_trust_map_names_every_registered_job(self):
        document = SPECIFICATIONS.read_text("utf-8")
        source = (ROOT / "app.py").read_text("utf-8")
        jobs = set(re.findall(r'jobs\.register\(\s*"([^"]+)"', source))

        self.assertEqual(len(jobs), 26)
        for job in jobs:
            self.assertIn(f"`{job}`", document, f"missing registered job: {job}")


if __name__ == "__main__":
    unittest.main()
