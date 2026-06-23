import re
from unittest import mock

from core.database import IndexChunk
from services import textindex
from tests._client import ApiTest

# deterministic fake embedder: bag-of-words over a tiny vocab → predictable cosine
VOCAB = ["cat", "dog", "fish", "car", "road", "tax", "invoice"]


def fake_embed(texts):
    out = []
    for t in texts:
        toks = set(re.findall(r"\w+", (t or "").lower()))
        out.append([1.0 if w in toks else 0.0 for w in VOCAB])
    return out


class TextIndexTests(ApiTest):
    def test_index_creates_chunks(self):
        d = self.db()
        n = textindex.index(d, "doc", "a.md", "the cat sat on the mat")
        self.assertGreaterEqual(n, 1)
        self.assertEqual(d.query(IndexChunk).filter_by(kind="doc", ref="a.md").count(), n)

    def test_index_replaces_no_dupes(self):
        d = self.db()
        textindex.index(d, "doc", "a.md", "first version about dogs")
        textindex.index(d, "doc", "a.md", "second version about cats")
        # only the latest content remains
        rows = d.query(IndexChunk).filter_by(kind="doc", ref="a.md").all()
        joined = " ".join(r.text for r in rows)
        self.assertIn("second", joined)
        self.assertNotIn("first", joined)

    def test_remove_deletes(self):
        d = self.db()
        textindex.index(d, "doc", "a.md", "something")
        self.assertEqual(textindex.remove(d, "doc", "a.md"), 1)
        self.assertEqual(d.query(IndexChunk).filter_by(ref="a.md").count(), 0)

    def test_search_ranks_relevant_first(self):
        d = self.db()
        with mock.patch.object(textindex, "_embed", fake_embed):
            textindex.index(d, "doc", "cats.md", "all about the cat and the cat again")
            textindex.index(d, "doc", "cars.md", "all about the car on the road")
            hits = textindex.search(d, "cat", k=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["ref"], "cats.md")

    def test_search_kind_scoped(self):
        d = self.db()
        with mock.patch.object(textindex, "_embed", fake_embed):
            textindex.index(d, "doc", "d.md", "cat")
            textindex.index(d, "code", "c.py", "cat")
            hits = textindex.search(d, "cat", kind="code")
        self.assertTrue(all(h["kind"] == "code" for h in hits))
        self.assertTrue(any(h["ref"] == "c.py" for h in hits))

    def test_search_keyword_fallback(self):
        d = self.db()
        with mock.patch.object(textindex, "_embed", lambda texts: None):
            textindex.index(d, "doc", "tax.md", "annual tax invoice details")
            textindex.index(d, "doc", "pet.md", "the dog and the fish")
            hits = textindex.search(d, "tax invoice", k=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["ref"], "tax.md")

    def test_search_finds_unembedded_chunk_in_mixed_index(self):
        # a chunk indexed before the embedder was available (vec="") must stay findable
        # by keyword even after other chunks get embedded — not silently dropped
        d = self.db()
        with mock.patch.object(textindex, "_embed", fake_embed):
            textindex.index(d, "doc", "embedded.md", "cat cat cat")  # gets a real vec
        d.add(IndexChunk(kind="doc", ref="old.md", chunk_no=0,
                         text="annual tax invoice details", vec=""))
        d.commit()
        with mock.patch.object(textindex, "_embed", fake_embed):
            hits = textindex.search(d, "tax invoice", k=5)
        self.assertIn("old.md", {h["ref"] for h in hits})

    def test_search_empty_index(self):
        d = self.db()
        self.assertEqual(textindex.search(d, "anything"), [])

    def test_search_no_match_returns_empty(self):
        d = self.db()
        with mock.patch.object(textindex, "_embed", lambda texts: None):
            textindex.index(d, "doc", "a.md", "completely unrelated words here")
            hits = textindex.search(d, "zzzzzz qqqqq", k=5)
        self.assertEqual(hits, [])

    def test_multi_kind_isolation(self):
        d = self.db()
        textindex.index(d, "doc", "a.md", "shared word alpha")
        textindex.index(d, "code", "a.py", "shared word alpha")
        textindex.remove(d, "doc", "a.md")
        self.assertEqual(d.query(IndexChunk).filter_by(kind="doc").count(), 0)
        self.assertEqual(d.query(IndexChunk).filter_by(kind="code").count(), 1)

    def test_persisted_in_db(self):
        d = self.db()
        textindex.index(d, "doc", "p.md", "persistent content goes to sqlite")
        # a fresh session sees it (it's in the db, not memory)
        d2 = self.db()
        self.assertGreaterEqual(d2.query(IndexChunk).filter_by(ref="p.md").count(), 1)

    def test_stats_counts(self):
        d = self.db()
        textindex.index(d, "doc", "a.md", "one")
        textindex.index(d, "doc", "b.md", "two")
        textindex.index(d, "code", "c.py", "three")
        s = textindex.stats(d)
        self.assertEqual(s.get("doc"), 2)
        self.assertEqual(s.get("code"), 1)

    def test_reindex_kind_replaces(self):
        d = self.db()
        textindex.index(d, "doc", "old.md", "old content")
        n = textindex.reindex_kind(d, "doc", [("new.md", "new content")])
        self.assertGreaterEqual(n, 1)
        refs = {r.ref for r in d.query(IndexChunk).filter_by(kind="doc").all()}
        self.assertEqual(refs, {"new.md"})
