import json

from core.database import ModelEndpoint
from routes.research import _is_chat_model, _first_chat_model, _resolve_ep
from tests._client import ApiTest


class ResearchResolveTest(ApiTest):
    def test_is_chat_model(self):
        self.assertTrue(_is_chat_model("gpt-4o"))
        self.assertTrue(_is_chat_model("llama-3.1-70b"))
        self.assertFalse(_is_chat_model("text-embedding-3-small"))
        self.assertFalse(_is_chat_model("bge-reranker-v2"))
        self.assertFalse(_is_chat_model("whisper-1"))
        self.assertFalse(_is_chat_model(""))

    def test_first_chat_model_skips_embeddings(self):
        class FakeEp:
            def models_list(self):
                return ["text-embedding-3-large", "gpt-4o", "another-chat"]

        self.assertEqual(_first_chat_model(FakeEp()), "gpt-4o")

    def test_resolve_skips_embedding_only_first_entry(self):
        # the original bug: it grabbed models_list()[0], which can be an embedding model
        d = self.db()
        d.add(
            ModelEndpoint(
                name="oai",
                base_url="http://x",
                api_key="k",
                cached_models=json.dumps(["text-embedding-3-small", "gpt-4o"]),
            )
        )
        d.commit()
        d.close()
        base, key, model = _resolve_ep()
        self.assertEqual(base, "http://x")
        self.assertEqual(model, "gpt-4o")  # not the embedding model

    def test_resolve_none_when_no_chat_model_anywhere(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="emb",
                base_url="http://x",
                api_key="k",
                cached_models=json.dumps(["text-embedding-3-small"]),
            )
        )
        d.commit()
        d.close()
        self.assertEqual(_resolve_ep(), (None, None, None))
