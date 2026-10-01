import json
import unittest
from unittest import mock

from core.database import ModelEndpoint, Persona, Session
from services.model_resolver import (
    ModelResolutionError,
    normalize_model_roles,
    resolve_model,
)
from tests._client import ApiTest


class ModelResolverTest(ApiTest):
    def _endpoint(self, name, url, models, metadata=None):
        db = self.db()
        endpoint = ModelEndpoint(
            name=name,
            base_url=url,
            cached_models=json.dumps(models),
            model_metadata=json.dumps(metadata or {}),
        )
        db.add(endpoint)
        db.commit()
        db.refresh(endpoint)
        endpoint_id = endpoint.id
        db.close()
        return endpoint_id

    @staticmethod
    def _settings(role_choice=None):
        return {
            "model_roles": {
                "aide_chat": role_choice or {},
                "andromeda_answer": role_choice or {},
                "andromeda_verifier": {},
                "jarvis": role_choice or {},
            },
            "default_endpoint_id": "",
            "default_model": "",
        }

    def test_precedence_is_explicit_workflow_feature_then_role(self):
        ids = {
            name: self._endpoint(name, f"https://{name}.test/v1", [name])
            for name in ("explicit", "workflow", "feature", "role")
        }
        settings = self._settings({"endpoint_id": ids["role"], "model": "role"})
        db = self.db()
        selected = resolve_model(
            db,
            "aide_chat",
            explicit={"endpoint_id": ids["explicit"], "model": "explicit"},
            workflow_override={"model": "workflow"},
            feature_default={"model": "feature"},
            settings=settings,
        )
        self.assertEqual((selected.model, selected.reason), ("explicit", "explicit_override"))
        selected = resolve_model(
            db,
            "aide_chat",
            workflow_override={"model": "workflow"},
            feature_default={"model": "feature"},
            settings=settings,
        )
        self.assertEqual((selected.model, selected.reason), ("workflow", "workflow_override"))
        selected = resolve_model(
            db,
            "aide_chat",
            feature_default={"model": "feature"},
            settings=settings,
        )
        self.assertEqual((selected.model, selected.reason), ("feature", "feature_default"))
        selected = resolve_model(db, "aide_chat", settings=settings)
        self.assertEqual((selected.model, selected.reason), ("role", "role_default"))
        db.close()

    def test_broken_role_does_not_silently_switch(self):
        endpoint_id = self._endpoint("remote", "https://remote.test/v1", ["available"])
        settings = self._settings({"endpoint_id": endpoint_id, "model": "removed"})
        db = self.db()
        with self.assertRaises(ModelResolutionError) as raised:
            resolve_model(db, "aide_chat", settings=settings)
        self.assertEqual(raised.exception.code, "model_unavailable")
        db.close()

    def test_configured_same_class_local_fallback_is_allowed(self):
        primary_id = self._endpoint("primary", "http://localhost:11434", ["new"])
        fallback_id = self._endpoint("fallback", "http://127.0.0.1:1234/v1", ["backup"])
        settings = self._settings(
            {
                "endpoint_id": primary_id,
                "model": "removed",
                "cost_class": "local",
                "fallbacks": [
                    {"endpoint_id": fallback_id, "model": "backup", "cost_class": "local"}
                ],
            }
        )
        db = self.db()
        selected = resolve_model(db, "jarvis", settings=settings)
        self.assertEqual((selected.model, selected.reason), ("backup", "role_fallback"))
        self.assertEqual(selected.privacy_class, "local")
        db.close()

    def test_remote_fallback_needs_an_explicit_matching_cost_class(self):
        primary_id = self._endpoint("primary", "https://primary.test/v1", ["new"])
        fallback_id = self._endpoint("fallback", "https://fallback.test/v1", ["backup"])
        settings = self._settings(
            {
                "endpoint_id": primary_id,
                "model": "removed",
                "fallbacks": [{"endpoint_id": fallback_id, "model": "backup"}],
            }
        )
        db = self.db()
        with self.assertRaises(ModelResolutionError):
            resolve_model(db, "jarvis", settings=settings)
        db.close()

    def test_andromeda_unconfigured_default_is_local_first(self):
        self._endpoint("remote", "https://remote.test/v1", ["remote-model"])
        self._endpoint("local", "http://localhost:11434", ["local-model"])
        db = self.db()
        selected = resolve_model(db, "andromeda_answer", settings=self._settings())
        self.assertEqual(selected.model, "local-model")
        self.assertEqual(selected.privacy_class, "local")
        db.close()

    def test_fallback_skips_non_chat_models_and_returns_known_price_data(self):
        self._endpoint("embed", "https://embed.test/v1", ["text-embedding-3-small"])
        self._endpoint(
            "chat",
            "https://chat.test/v1",
            ["chat-model"],
            {"chat-model": {"input_price": 1.5, "owned_by": "provider"}},
        )
        db = self.db()
        selected = resolve_model(db, "aide_chat", settings=self._settings())
        self.assertEqual(selected.model, "chat-model")
        self.assertEqual(selected.price_metadata, {"input_price": 1.5})
        db.close()

    def test_roles_api_reports_effective_and_broken_choices(self):
        endpoint_id = self._endpoint("chat", "https://chat.test/v1", ["chat-model"])
        settings = {
            "model_roles": {
                "aide_chat": {"endpoint_id": endpoint_id, "model": "chat-model"},
                "andromeda_answer": {"endpoint_id": endpoint_id, "model": "removed"},
                "andromeda_verifier": {},
                "jarvis": {},
            },
            "default_endpoint_id": "",
            "default_model": "",
        }
        with mock.patch("routes.models.load_settings", return_value=settings):
            response = self.client.get("/api/models/roles")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["aide_chat"]["effective"]["model"], "chat-model")
        self.assertEqual(body["aide_chat"]["effective"]["reason"], "role_default")
        self.assertEqual(body["andromeda_answer"]["status"], "broken")
        self.assertEqual(body["andromeda_answer"]["error_code"], "model_unavailable")

    def test_chat_uses_role_then_persona_then_session_choice(self):
        from routes.chat import _resolve_session_model

        role_id = self._endpoint("role", "https://role.test/v1", ["role-model"])
        persona_id = self._endpoint("persona", "https://persona.test/v1", ["persona-model"])
        explicit_id = self._endpoint("explicit", "https://explicit.test/v1", ["explicit-model"])
        settings = self._settings({"endpoint_id": role_id, "model": "role-model"})
        db = self.db()
        persona = Persona(name="focused", model="persona-model")
        session = Session(name="chat")
        db.add_all([persona, session])
        db.commit()

        endpoint, model = _resolve_session_model(session, db, settings)
        self.assertEqual((endpoint.id, model), (role_id, "role-model"))

        session.persona_id = persona.id
        db.commit()
        endpoint, model = _resolve_session_model(session, db, settings)
        self.assertEqual((endpoint.id, model), (persona_id, "persona-model"))

        session.endpoint_id = explicit_id
        session.model = "explicit-model"
        db.commit()
        endpoint, model = _resolve_session_model(session, db, settings)
        self.assertEqual((endpoint.id, model), (explicit_id, "explicit-model"))
        db.close()


class ModelRoleValidationTest(unittest.TestCase):
    def test_normalizes_all_four_roles(self):
        roles = normalize_model_roles({"aide_chat": {"model": " chat "}})
        self.assertEqual(roles["aide_chat"]["model"], "chat")
        self.assertEqual(roles["andromeda_answer"]["model"], "")
        self.assertEqual(roles["andromeda_verifier"]["model"], "")
        self.assertEqual(roles["jarvis"]["fallbacks"], [])

    def test_migrates_legacy_andromeda_choice_to_answer_role(self):
        roles = normalize_model_roles({"andromeda": {"endpoint_id": "ep", "model": "fast"}})
        self.assertEqual(roles["andromeda_answer"]["model"], "fast")
        self.assertEqual(roles["andromeda_verifier"]["model"], "")

    def test_rejects_unknown_roles_and_fields(self):
        with self.assertRaises(ValueError):
            normalize_model_roles({"other": {}})
        with self.assertRaises(ValueError):
            normalize_model_roles({"aide_chat": {"secret": "x"}})


if __name__ == "__main__":
    unittest.main()
