import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import vault_md
from tests._client import ApiTest


def _seed():
    vault_md.write("A.md", "---\ntags: [core]\n---\n[[B]] and [[C]]")
    vault_md.write("B.md", "see [[C]]")
    vault_md.write("C.md", "see [[D]]")
    vault_md.write("D.md", "leaf node")
    vault_md.write("E.md", "---\ntags: [island]\n---\nalone")
    vault_md.write("proj/F.md", "back to [[A]]")


def _ids(g):
    return sorted(n["id"] for n in g["nodes"])


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self.p.start()
        _seed()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_full_graph(self):
        g = vault_md.graph()
        self.assertEqual(_ids(g), ["A", "B", "C", "D", "E", "F"])
        self.assertEqual(len(g["edges"]), 5)

    def test_graph_tag_filter(self):
        g = vault_md.graph(tag="core")
        self.assertEqual(_ids(g), ["A"])
        self.assertEqual(g["edges"], [])

    def test_graph_folder_filter(self):
        g = vault_md.graph(folder="proj")
        self.assertEqual(_ids(g), ["F"])

    def test_local_depth1(self):
        g = vault_md.local_graph("A", depth=1)
        self.assertEqual(_ids(g), ["A", "B", "C", "F"])
        self.assertEqual(len(g["edges"]), 4)
        self.assertEqual(g["center"], "A")

    def test_local_depth2_reaches_further(self):
        g = vault_md.local_graph("A", depth=2)
        self.assertEqual(_ids(g), ["A", "B", "C", "D", "F"])

    def test_local_depth0_just_center(self):
        g = vault_md.local_graph("A", depth=0)
        self.assertEqual(_ids(g), ["A"])
        self.assertEqual(g["edges"], [])

    def test_local_isolated_node(self):
        g = vault_md.local_graph("E", depth=2)
        self.assertEqual(_ids(g), ["E"])
        self.assertEqual(g["edges"], [])

    def test_local_unknown_name(self):
        g = vault_md.local_graph("Nope", depth=1)
        self.assertEqual(g["nodes"], [])
        self.assertIsNone(g["center"])

    def test_local_case_insensitive(self):
        g = vault_md.local_graph("a", depth=1)
        self.assertEqual(g["center"], "A")


class GraphApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.vp = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self.vp.start()
        _seed()

    def tearDown(self):
        self.vp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_api_graph_tag(self):
        r = self.client.get("/api/vault-md/graph", params={"tag": "core"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([n["id"] for n in r.json()["nodes"]], ["A"])

    def test_api_local_graph(self):
        r = self.client.get("/api/vault-md/local-graph", params={"name": "A", "depth": 1})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sorted(n["id"] for n in r.json()["nodes"]), ["A", "B", "C", "F"])
        self.assertEqual(r.json()["center"], "A")


if __name__ == "__main__":
    unittest.main()
