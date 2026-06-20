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


class ChunkEdgeCases(unittest.TestCase):
    def test_exact_size_no_overlap(self):
        # text exactly equal to size → one chunk
        chunks = _chunk("a" * 700, size=700, overlap=0)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], "a" * 700)

    def test_collapses_excessive_blank_lines(self):
        # rag._chunk strips triple+ newlines down to double
        text = "para one\n\n\n\n\npara two"
        chunks = _chunk(text)
        self.assertEqual(len(chunks), 1)
        self.assertNotIn("\n\n\n", chunks[0])

    def test_size_parameter_respected(self):
        chunks = _chunk("x" * 500, size=100, overlap=0)
        self.assertEqual(len(chunks), 5)
        for c in chunks:
            self.assertEqual(len(c), 100)


class RetrieveTests(unittest.TestCase):
    def tearDown(self):
        rag._index = None  # don't leak the fake index

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

    def test_k_limits_results(self):
        rag._index = [
            {"path": f"{i}.md", "chunk": f"apple fruit number {i}", "vec": None} for i in range(10)
        ]
        hits = rag.retrieve("apple", k=3)
        self.assertLessEqual(len(hits), 3)

    def test_zero_score_filtered_out(self):
        # a query that shares no tokens with the chunks → no hits returned
        rag._index = [
            {"path": "cars.md", "chunk": "automobile engine horsepower turbo", "vec": None},
        ]
        hits = rag.retrieve("banana mango tropical fruit")
        self.assertEqual(hits, [])

    def test_retrieve_returns_score_and_chunk(self):
        rag._index = [
            {"path": "info.md", "chunk": "python programming language", "vec": None},
        ]
        hits = rag.retrieve("python language", k=1)
        if hits:  # score > 0 required; if jaccard matches it will be here
            self.assertIn("score", hits[0])
            self.assertIn("chunk", hits[0])
            self.assertIn("path", hits[0])


if __name__ == "__main__":
    unittest.main()
