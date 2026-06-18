import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import vault_md
from tests._client import ApiTest

BOARD = """# Project

## Backlog
- [ ] idea one
- [ ] idea two

## In Progress
- [ ] build alpha

## Done
- [x] kickoff
"""


def _names(cols):
    return [c["name"] for c in cols]


def _col(cols, name):
    return next(c for c in cols if c["name"] == name)


class BoardParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self.p.start()
        vault_md.write("board.md", BOARD)

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_parse_columns(self):
        cols = vault_md.parse_board(BOARD)
        self.assertEqual(_names(cols), ["Backlog", "In Progress", "Done"])

    def test_parse_cards(self):
        cols = vault_md.parse_board(BOARD)
        self.assertEqual(
            [c["text"] for c in _col(cols, "Backlog")["cards"]], ["idea one", "idea two"]
        )
        self.assertTrue(_col(cols, "Done")["cards"][0]["done"])
        self.assertFalse(_col(cols, "Backlog")["cards"][0]["done"])

    def test_parse_ignores_frontmatter_and_keeps_abs_lines(self):
        fm = "---\nkanban: true\n---\n" + BOARD
        cols = vault_md.parse_board(fm)
        self.assertEqual(_names(cols), ["Backlog", "In Progress", "Done"])
        line = _col(cols, "In Progress")["cards"][0]["line"]
        self.assertEqual(fm.split("\n")[line], "- [ ] build alpha")

    def test_parse_no_headings(self):
        self.assertEqual(vault_md.parse_board("just some text, no columns"), [])

    def test_add_card_existing_column(self):
        vault_md.board_add_card("board.md", "Backlog", "idea three")
        cols = vault_md.parse_board(vault_md.read("board.md")["content"])
        self.assertEqual(
            [c["text"] for c in _col(cols, "Backlog")["cards"]],
            ["idea one", "idea two", "idea three"],
        )

    def test_add_card_missing_column_creates_it(self):
        vault_md.board_add_card("board.md", "Review", "check it")
        cols = vault_md.parse_board(vault_md.read("board.md")["content"])
        self.assertIn("Review", _names(cols))
        self.assertEqual([c["text"] for c in _col(cols, "Review")["cards"]], ["check it"])

    def test_move_card_between_columns(self):
        cols = vault_md.parse_board(vault_md.read("board.md")["content"])
        line = _col(cols, "In Progress")["cards"][0]["line"]
        vault_md.board_move_card("board.md", line, "Done")
        cols2 = vault_md.parse_board(vault_md.read("board.md")["content"])
        self.assertIn("build alpha", [c["text"] for c in _col(cols2, "Done")["cards"]])
        self.assertNotIn("build alpha", [c["text"] for c in _col(cols2, "In Progress")["cards"]])

    def test_move_preserves_done_state(self):
        cols = vault_md.parse_board(vault_md.read("board.md")["content"])
        line = _col(cols, "Done")["cards"][0]["line"]
        vault_md.board_move_card("board.md", line, "Backlog")
        cols2 = vault_md.parse_board(vault_md.read("board.md")["content"])
        kick = next(c for c in _col(cols2, "Backlog")["cards"] if c["text"] == "kickoff")
        self.assertTrue(kick["done"])

    def test_move_invalid_line_raises(self):
        with self.assertRaises(ValueError):
            vault_md.board_move_card("board.md", 0, "Done")  # line 0 is "# Project", not a card


class BoardApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.vp = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self.vp.start()
        vault_md.write("board.md", BOARD)

    def tearDown(self):
        self.vp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_api_get_board(self):
        r = self.client.get("/api/vault-md/board", params={"path": "board"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            [c["name"] for c in r.json()["columns"]], ["Backlog", "In Progress", "Done"]
        )

    def test_api_add_card(self):
        r = self.client.post(
            "/api/vault-md/board/add", json={"path": "board", "column": "Done", "text": "wrap up"}
        )
        self.assertEqual(r.status_code, 200)
        texts = [c["text"] for c in _col(r.json()["columns"], "Done")["cards"]]
        self.assertIn("wrap up", texts)

    def test_api_move_card(self):
        cols = self.client.get("/api/vault-md/board", params={"path": "board"}).json()["columns"]
        line = _col(cols, "Backlog")["cards"][0]["line"]
        r = self.client.post(
            "/api/vault-md/board/move", json={"path": "board", "line": line, "to_col": "Done"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("idea one", [c["text"] for c in _col(r.json()["columns"], "Done")["cards"]])


if __name__ == "__main__":
    unittest.main()
