from types import SimpleNamespace
from unittest import mock

from core.database import Task
from tests._client import ApiTest


class SearchSpellingTests(ApiTest):
    def test_a_typo_gets_a_suggestion_from_the_owners_own_titles(self):
        db = self.db()
        try:
            db.add(Task(title="renew passport application"))
            db.commit()
        finally:
            db.close()
        data = self.client.get("/api/search", params={"q": "renew pasport"}).json()
        self.assertEqual(data["suggestion"], "renew passport")
        found = self.client.get("/api/search", params={"q": "passport"}).json()
        self.assertNotIn("suggestion", found)
        self.assertEqual(found["tasks"][0]["title"], "renew passport application")
        nothing = self.client.get("/api/search", params={"q": "qzxwvk"}).json()
        self.assertNotIn("suggestion", nothing)

    def test_spellfix_asks_the_chat_model_and_skips_unchanged_queries(self):
        selected = SimpleNamespace(
            endpoint=SimpleNamespace(base_url="https://api.example", api_key="k"), model="m"
        )
        with (
            mock.patch("services.model_resolver.resolve_model", return_value=selected),
            mock.patch("services.llm.simple_complete", return_value="vault\n") as complete,
        ):
            fixed = self.client.post("/api/search/spellfix", json={"q": "vauls"}).json()
            same = self.client.post("/api/search/spellfix", json={"q": "Vault"}).json()
        self.assertEqual(fixed, {"query": "vault"})
        self.assertEqual(same, {"query": ""})
        self.assertEqual(complete.call_args_list[0].args[0][1]["content"], "vauls")
