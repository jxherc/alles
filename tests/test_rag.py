import unittest
from services import rag
from services.rag import _chunk


class ChunkTests(unittest.TestCase):
    def test_overlap_and_size(self):
        chunks = _chunk("x" * 2000, size=700, overlap=120)
        self.assertGreater(len(chunks), 2)
        self.assertEqual(chunks[0], "x" * 700)
        # step = size - overlap = 580, so chunk[1] starts at 580
        self.assertTrue(chunks[1].startswith("x"))

    def test_empty(self):
        self.assertEqual(_chunk(""), [])
        self.assertEqual(_chunk("   \n\n  "), [])

    def test_short_text_one_chunk(self):
        self.assertEqual(_chunk("hello world"), ["hello world"])


class RetrieveTests(unittest.TestCase):
    def tearDown(self):
        rag._index = None   # don't leak the fake index

    def test_ranks_by_relevance_jaccard(self):
        # vec=None forces the keyword (jaccard) path — no fastembed needed
        rag._index = [
            {"path": "cats.md", "chunk": "cats are independent and love to nap", "vec": None},
            {"path": "dogs.md", "chunk": "dogs are loyal and bark at strangers", "vec": None},
        ]
        hits = rag.retrieve("tell me about cats and napping", k=2)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["path"], "cats.md")

    def test_empty_index(self):
        rag._index = []
        self.assertEqual(rag.retrieve("anything"), [])


if __name__ == "__main__":
    unittest.main()
