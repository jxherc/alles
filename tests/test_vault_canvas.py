import tempfile
from pathlib import Path
from unittest import mock

from services import vault_md
from tests._client import ApiTest


class CanvasTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_read_new_canvas_empty(self):
        d = self.client.get("/api/vault-md/canvas", params={"path": "board"}).json()
        self.assertFalse(d["exists"])
        self.assertEqual(d["nodes"], [])

    def test_write_then_read(self):
        nodes = [{"id": "n1", "x": 10, "y": 20, "text": "hello"}]
        edges = [{"from": "n1", "to": "n2"}]
        self.client.put(
            "/api/vault-md/canvas", json={"path": "board", "nodes": nodes, "edges": edges}
        )
        d = self.client.get("/api/vault-md/canvas", params={"path": "board"}).json()
        self.assertTrue(d["exists"])
        self.assertEqual(d["nodes"][0]["text"], "hello")
        self.assertEqual(d["edges"][0]["from"], "n1")

    def test_write_persists_positions(self):
        self.client.put(
            "/api/vault-md/canvas",
            json={"path": "b", "nodes": [{"id": "a", "x": 99, "y": 5}], "edges": []},
        )
        d = self.client.get("/api/vault-md/canvas", params={"path": "b"}).json()
        self.assertEqual(d["nodes"][0]["x"], 99)

    def test_canvas_suffix_added(self):
        self.client.put("/api/vault-md/canvas", json={"path": "noext", "nodes": [], "edges": []})
        self.assertTrue((Path(self.tmp.name) / "noext.canvas").exists())

    def test_list_canvases(self):
        self.client.put("/api/vault-md/canvas", json={"path": "one", "nodes": [], "edges": []})
        self.client.put("/api/vault-md/canvas", json={"path": "sub/two", "nodes": [], "edges": []})
        c = self.client.get("/api/vault-md/canvases").json()["canvases"]
        self.assertEqual(set(c), {"one.canvas", "sub/two.canvas"})

    def test_overwrite_updates(self):
        self.client.put(
            "/api/vault-md/canvas", json={"path": "x", "nodes": [{"id": "1"}], "edges": []}
        )
        self.client.put(
            "/api/vault-md/canvas",
            json={"path": "x", "nodes": [{"id": "1"}, {"id": "2"}], "edges": []},
        )
        d = self.client.get("/api/vault-md/canvas", params={"path": "x"}).json()
        self.assertEqual(len(d["nodes"]), 2)

    def test_read_with_or_without_suffix(self):
        self.client.put(
            "/api/vault-md/canvas", json={"path": "y.canvas", "nodes": [{"id": "z"}], "edges": []}
        )
        d1 = self.client.get("/api/vault-md/canvas", params={"path": "y"}).json()
        d2 = self.client.get("/api/vault-md/canvas", params={"path": "y.canvas"}).json()
        self.assertEqual(d1["nodes"], d2["nodes"])

    def test_list_skips_hidden(self):
        vault_md.canvas_write("_hidden/h", [], [])
        vault_md.canvas_write("visible", [], [])
        c = self.client.get("/api/vault-md/canvases").json()["canvases"]
        self.assertIn("visible.canvas", c)
        self.assertFalse(any(x.startswith("_hidden") for x in c))
