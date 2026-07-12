import json
import unittest
from types import SimpleNamespace
from unittest import mock

from core.database import ModelEndpoint
from services import model_catalog
from services.model_providers import CatalogFetchError, CatalogResult
from tests._client import ApiTest


def endpoint(**values):
    defaults = {
        "id": "ep1",
        "name": "provider",
        "base_url": "https://api.example.test",
        "api_key": "",
        "provider_adapter": "auto",
        "cached_models": json.dumps(["old-chat", "kept-chat"]),
        "image_models": json.dumps(["old-image"]),
        "unavailable_models": json.dumps(["returned-chat"]),
        "model_metadata": "{}",
        "catalog_status": "live",
        "catalog_source": "openai-compatible",
        "catalog_error": "",
        "catalog_refreshed_at": None,
        "health_status": "healthy",
        "last_tested_at": None,
        "last_error_code": "",
    }
    defaults.update(values)
    ep = SimpleNamespace(**defaults)
    ep.models_list = lambda: json.loads(ep.cached_models or "[]")
    ep.image_models_list = lambda: json.loads(ep.image_models or "[]")
    ep.unavailable_models_list = lambda: json.loads(ep.unavailable_models or "[]")
    return ep


class ModelCatalogUnitTest(unittest.IsolatedAsyncioTestCase):
    async def test_success_reconciles_added_removed_and_returned_models(self):
        ep = endpoint()
        live = CatalogResult(
            ["kept-chat", "returned-chat", "gpt-image-1"],
            {"kept-chat": {"owned_by": "provider"}},
            "openai-compatible",
        )
        with mock.patch("services.model_catalog.fetch_catalog", return_value=live):
            result = await model_catalog.refresh_endpoint(ep)
        self.assertEqual(ep.catalog_status, "live")
        self.assertEqual(ep.health_status, "healthy")
        self.assertEqual(result["added"], ["returned-chat"])
        self.assertEqual(result["removed"], ["old-chat"])
        self.assertEqual(json.loads(ep.unavailable_models), ["old-chat", "old-image"])
        self.assertEqual(json.loads(ep.image_models), ["gpt-image-1"])

    async def test_failure_keeps_last_good_catalog_and_marks_stale(self):
        ep = endpoint()
        with mock.patch(
            "services.model_catalog.fetch_catalog",
            side_effect=CatalogFetchError("timeout"),
        ):
            result = await model_catalog.refresh_endpoint(ep)
        self.assertEqual(ep.models_list(), ["old-chat", "kept-chat"])
        self.assertEqual(ep.image_models_list(), ["old-image"])
        self.assertEqual(ep.catalog_status, "stale")
        self.assertEqual(ep.catalog_error, "timeout")
        self.assertEqual(result["error_code"], "timeout")

    async def test_first_failure_stays_unverified_and_unavailable(self):
        ep = endpoint(
            cached_models="[]",
            image_models="[]",
            catalog_status="unverified",
            health_status="unverified",
        )
        with mock.patch(
            "services.model_catalog.fetch_catalog",
            side_effect=CatalogFetchError("authentication_failed"),
        ):
            await model_catalog.refresh_endpoint(ep)
        self.assertEqual(ep.catalog_status, "unavailable")
        self.assertEqual(ep.health_status, "unverified")

    async def test_manual_catalog_never_refreshes_or_erases_models(self):
        ep = endpoint(provider_adapter="manual", catalog_status="manual")
        with mock.patch("services.model_catalog.fetch_catalog") as fetch:
            result = await model_catalog.refresh_endpoint(ep)
        fetch.assert_not_called()
        self.assertEqual(result["models"], ["old-chat", "kept-chat"])
        self.assertEqual(ep.catalog_status, "manual")


class ModelCatalogApiTest(ApiTest):
    def _seed(self, **values):
        db = self.db()
        ep = ModelEndpoint(
            name=values.pop("name", "Custom"),
            base_url="https://custom.example/v1",
            cached_models=json.dumps(["last-good"]),
            **values,
        )
        db.add(ep)
        db.commit()
        db.refresh(ep)
        endpoint_id = ep.id
        db.close()
        return endpoint_id

    def test_manual_model_edit_marks_catalog_manual(self):
        endpoint_id = self._seed()
        response = self.client.patch(
            f"/api/models/endpoint/{endpoint_id}", json={"models": ["manual-a", "manual-a"]}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["models"], ["manual-a"])
        self.assertEqual(body["provider_adapter"], "manual")
        self.assertEqual(body["catalog_status"], "manual")

    def test_changing_endpoint_moves_old_models_out_of_picker(self):
        endpoint_id = self._seed(catalog_status="live")
        response = self.client.patch(
            f"/api/models/endpoint/{endpoint_id}",
            json={"base_url": "https://new.example/v1"},
        )
        body = response.json()
        self.assertEqual(body["models"], [])
        self.assertEqual(body["unavailable_models"], ["last-good"])
        self.assertEqual(body["catalog_status"], "unverified")

    def test_invalid_adapter_has_stable_error(self):
        response = self.client.post(
            "/api/models/endpoint",
            json={"name": "bad", "base_url": "https://x", "provider_adapter": "shell"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_provider_adapter")

    def test_probe_success_updates_live_catalog(self):
        endpoint_id = self._seed()
        live = CatalogResult(["live-chat", "gpt-image-1"], {}, "openai-compatible")
        with mock.patch(
            "services.model_catalog.fetch_catalog", new=mock.AsyncMock(return_value=live)
        ):
            response = self.client.post(f"/api/models/endpoint/{endpoint_id}/probe")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["models"], ["live-chat"])
        listed = self.client.get("/api/models").json()[0]
        self.assertEqual(listed["catalog_status"], "live")
        self.assertEqual(listed["health_status"], "healthy")

    def test_probe_failure_preserves_last_good_list_and_marks_stale(self):
        endpoint_id = self._seed(catalog_status="live", health_status="healthy")
        with mock.patch(
            "services.model_catalog.fetch_catalog",
            new=mock.AsyncMock(side_effect=CatalogFetchError("timeout")),
        ):
            response = self.client.post(f"/api/models/endpoint/{endpoint_id}/probe")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "model_catalog_refresh_failed")
        listed = self.client.get("/api/models").json()[0]
        self.assertEqual(listed["models"], ["last-good"])
        self.assertEqual(listed["catalog_status"], "stale")
        self.assertEqual(listed["catalog_error"], "timeout")

    def test_refresh_all_keeps_other_endpoints_working_after_one_failure(self):
        failed_id = self._seed(name="failed", catalog_status="live", health_status="healthy")
        live_id = self._seed(name="live")

        async def fetch(ep, *, client=None):
            if ep.id == failed_id:
                raise CatalogFetchError("timeout")
            return CatalogResult(["fresh-chat"], {}, "openai-compatible")

        with mock.patch("services.model_catalog.fetch_catalog", side_effect=fetch):
            response = self.client.post("/api/models/refresh?force=true")

        self.assertEqual(response.status_code, 200)
        results = {item["endpoint_id"]: item for item in response.json()["results"]}
        self.assertEqual(results[failed_id]["error_code"], "timeout")
        self.assertEqual(results[failed_id]["models"], ["last-good"])
        self.assertEqual(results[live_id]["models"], ["fresh-chat"])
        self.assertEqual(results[live_id]["status"], "live")

    def test_endpoint_url_credentials_are_masked_in_api(self):
        db = self.db()
        db.add(
            ModelEndpoint(
                name="masked",
                base_url="https://user:pass@example.test/v1?token=private",
            )
        )
        db.commit()
        db.close()
        url = self.client.get("/api/models").json()[0]["base_url"]
        self.assertNotIn("user", url)
        self.assertNotIn("pass", url)
        self.assertNotIn("private", url)


if __name__ == "__main__":
    unittest.main()
