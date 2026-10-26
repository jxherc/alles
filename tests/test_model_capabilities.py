import json
import unittest
from types import SimpleNamespace

from core.api_errors import ApiError
from core.database import ModelEndpoint
from routes.chat import ChatRequest, _apply_run_controls
from services import llm
from services import model_capabilities as caps
from services.agent_runtime import provider_effort
from services.model_providers import fetch_catalog
from tests._client import ApiTest

ALL = ["low", "medium", "high", "xhigh", "max"]
MSGS = [{"role": "user", "content": "hi"}]


def anthropic_caps(levels, *, enabled=True):
    effort = {"supported": bool(levels)}
    for level in ALL:
        effort[level] = {"supported": level in levels}
    return {
        "capabilities": {
            "effort": effort,
            "thinking": {"supported": True, "types": {"enabled": {"supported": enabled}}},
        }
    }


class EffortLevelsTest(unittest.TestCase):
    def test_provider_metadata_wins_over_names(self):
        meta = anthropic_caps(["low", "high"])
        self.assertEqual(caps.effort_levels("anthropic", "claude-opus-5", meta), ["low", "high"])
        # a catalog that says unsupported beats a name that looks supported
        self.assertEqual(
            caps.effort_levels("anthropic", "claude-opus-5", anthropic_caps([], enabled=False)), []
        )

    def test_anthropic_names_without_metadata(self):
        self.assertEqual(caps.effort_levels("anthropic", "claude-opus-5-5"), ALL)
        self.assertEqual(caps.effort_levels("anthropic", "claude-opus-4-7"), ALL)
        self.assertEqual(
            caps.effort_levels("anthropic", "claude-sonnet-4-6"), ["low", "medium", "high", "max"]
        )
        self.assertEqual(
            caps.effort_levels("anthropic", "claude-opus-4-5-20251101"), ["low", "medium", "high"]
        )
        self.assertEqual(caps.effort_levels("anthropic", "claude-haiku-3-5"), [])

    def test_legacy_thinking_models_take_budget_levels_only(self):
        for name in ("claude-3-7-sonnet-20250219", "claude-sonnet-4-20250514", "claude-sonnet-4-5"):
            self.assertEqual(caps.effort_levels("anthropic", name), ["high", "xhigh", "max"], name)
            self.assertEqual(caps.anthropic_effort_api(name), "budget", name)
        self.assertEqual(caps.anthropic_effort_api("claude-opus-5"), "effort")
        self.assertEqual(caps.anthropic_effort_api("claude-haiku-3-5"), "")

    def test_openai_names(self):
        self.assertEqual(caps.effort_levels("openai", "o3-mini"), ["low", "medium", "high"])
        self.assertEqual(caps.effort_levels("openai", "gpt-5"), ["low", "medium", "high"])
        self.assertEqual(
            caps.effort_levels("openai", "gpt-5-2025-08-07"), ["low", "medium", "high"]
        )
        self.assertEqual(
            caps.effort_levels("openai", "gpt-5.2"), ["low", "medium", "high", "xhigh"]
        )
        self.assertEqual(
            caps.effort_levels("openai", "gpt-6-astra"), ["low", "medium", "high", "xhigh"]
        )
        for name in ("gpt-4o", "gpt-4.1", "o1-mini", "gpt-5-chat-latest", "text-embedding-3"):
            self.assertEqual(caps.effort_levels("openai", name), [], name)

    def test_models_with_no_levels(self):
        for provider, name in (
            ("deepseek", "deepseek-reasoner"),
            ("ollama", "qwen3:8b"),
            ("groq", "llama-3.3-70b"),
            ("openrouter", "openai/gpt-5"),
        ):
            self.assertEqual(caps.effort_levels(provider, name), [], name)

    def test_openrouter_catalog_levels(self):
        meta = {"reasoning": {"supported_efforts": ["max", "high", "low", "none", "bogus"]}}
        self.assertEqual(
            caps.effort_levels("openrouter", "vendor/model", meta), ["low", "high", "max"]
        )
        by_parameter = {"supported_parameters": ["tools", "reasoning"]}
        self.assertEqual(
            caps.effort_levels("openrouter", "vendor/model", by_parameter),
            ["low", "medium", "high"],
        )
        self.assertEqual(
            caps.effort_levels("openrouter", "vendor/model", {"supported_parameters": ["tools"]}),
            [],
        )

    def test_gemini_thinking_flag_and_names(self):
        self.assertEqual(
            caps.effort_levels("gemini", "gemini-x", {"thinking": True}), ["low", "medium", "high"]
        )
        self.assertEqual(caps.effort_levels("gemini", "gemini-2.5-pro", {"thinking": False}), [])
        self.assertEqual(
            caps.effort_levels("gemini", "gemini-2.5-flash"), ["low", "medium", "high"]
        )
        self.assertEqual(caps.effort_levels("gemini", "gemini-2.0-flash"), [])

    def test_garbage_metadata_is_ignored(self):
        for meta in (None, [], "x", {"capabilities": "no"}, {"reasoning": 3}, {"thinking": "yes"}):
            self.assertEqual(caps.effort_levels("openai", "o3", meta), ["low", "medium", "high"])

    def test_thinks_covers_models_without_levels(self):
        self.assertTrue(caps.thinks("deepseek-reasoner"))
        self.assertTrue(caps.thinks("anthropic/claude-sonnet-4"))
        self.assertFalse(caps.thinks("claude-3-5-sonnet"))
        self.assertFalse(caps.thinks("gpt-4o"))


class CatalogMetadataTest(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, url, payload):
        class Client:
            async def get(self, _url, headers=None):
                return SimpleNamespace(status_code=200, json=lambda: payload)

        ep = SimpleNamespace(base_url=url, api_key="k", provider_adapter="auto")
        return await fetch_catalog(ep, client=Client())

    async def test_anthropic_capabilities_are_kept_and_noise_dropped(self):
        item = {
            "id": "claude-opus-5-5",
            "display_name": "Claude",
            "capabilities": {
                "effort": {
                    "supported": True,
                    "high": {"supported": True, "extra": "x"},
                    "xhigh": {"supported": False},
                    "huge": {"supported": True},
                },
                "thinking": {"supported": True, "types": {"enabled": {"supported": False}}},
                "batch": {"supported": True},
            },
        }
        result = await self.fetch("https://api.anthropic.com", {"data": [item]})
        kept = result.metadata["claude-opus-5-5"]["capabilities"]
        self.assertEqual(
            kept["effort"],
            {"supported": True, "high": {"supported": True}, "xhigh": {"supported": False}},
        )
        self.assertEqual(kept["thinking"]["types"], {"enabled": {"supported": False}})
        self.assertNotIn("batch", kept)
        self.assertEqual(
            caps.effort_levels("anthropic", "claude-opus-5-5", result.metadata["claude-opus-5-5"]),
            ["high"],
        )

    async def test_openrouter_and_gemini_reasoning_fields_are_kept(self):
        result = await self.fetch(
            "https://openrouter.ai/api/v1",
            {
                "data": [
                    {
                        "id": "vendor/m",
                        "supported_parameters": ["tools", "reasoning", 5],
                        "reasoning": {"supported_efforts": ["low", "high"], "secret": 1},
                    }
                ]
            },
        )
        meta = result.metadata["vendor/m"]
        self.assertEqual(meta["supported_parameters"], ["tools", "reasoning"])
        self.assertEqual(meta["reasoning"], {"supported_efforts": ["low", "high"]})
        gem = await self.fetch(
            "https://generativelanguage.googleapis.com",
            {
                "models": [
                    {
                        "name": "models/gemini-2.5-pro",
                        "supportedGenerationMethods": ["generateContent"],
                        "thinking": True,
                    }
                ]
            },
        )
        self.assertIs(gem.metadata["gemini-2.5-pro"]["thinking"], True)


class RequestPayloadTest(unittest.TestCase):
    def test_openai_sends_only_levels_the_model_takes(self):
        build = llm._build_openai_payload
        self.assertEqual(
            build(MSGS, "o3-mini", provider="openai", effort="xhigh").get("reasoning_effort"), None
        )
        self.assertEqual(
            build(MSGS, "gpt-5.2", provider="openai", effort="xhigh")["reasoning_effort"], "xhigh"
        )
        self.assertNotIn(
            "reasoning_effort", build(MSGS, "gpt-4o", provider="openai", effort="high")
        )
        self.assertNotIn("reasoning_effort", build(MSGS, "gpt-5", provider="openai", effort=""))

    def test_openrouter_and_gemini_use_their_own_fields(self):
        meta = {"reasoning": {"supported_efforts": ["low", "high"]}}
        p = llm._build_openai_payload(
            MSGS, "vendor/m", provider="openrouter", effort="high", model_metadata=meta
        )
        self.assertEqual(p["reasoning"], {"effort": "high"})
        self.assertNotIn("reasoning_effort", p)
        p = llm._build_openai_payload(
            MSGS, "vendor/m", provider="openrouter", effort="medium", model_metadata=meta
        )
        self.assertNotIn("reasoning", p)
        p = llm._build_openai_payload(MSGS, "gemini-2.5-pro", provider="gemini", effort="low")
        self.assertEqual(p["reasoning_effort"], "low")
        p = llm._build_openai_payload(MSGS, "deepseek-reasoner", provider="deepseek", effort="high")
        self.assertNotIn("reasoning_effort", p)
        self.assertNotIn("reasoning", p)

    def test_anthropic_effort_field_budget_and_drops(self):
        build = llm._build_anthropic_payload
        p = build(MSGS, "claude-opus-5-5", effort="xhigh")
        self.assertEqual(p["output_config"], {"effort": "xhigh"})
        self.assertNotIn("thinking", p)
        # a level this model lacks is not sent
        p = build(MSGS, "claude-opus-4-5-20251101", effort="max")
        self.assertNotIn("output_config", p)
        # models with no levels get nothing
        p = build(MSGS, "claude-3-5-sonnet", effort="high")
        self.assertNotIn("output_config", p)
        self.assertNotIn("thinking", p)
        # legacy budget models keep the thinking budget and never get output_config
        p = build(MSGS, "claude-3-7-sonnet", effort="high")
        self.assertEqual(p["thinking"], {"type": "enabled", "budget_tokens": 8000})
        self.assertNotIn("output_config", p)
        p = build(MSGS, "claude-3-7-sonnet", effort="medium")
        self.assertNotIn("thinking", p)

    def test_anthropic_catalog_metadata_drives_the_payload(self):
        meta = anthropic_caps(["low", "high"], enabled=False)
        build = llm._build_anthropic_payload
        self.assertEqual(
            build(MSGS, "claude-future", effort="high", model_metadata=meta)["output_config"],
            {"effort": "high"},
        )
        self.assertNotIn(
            "output_config", build(MSGS, "claude-future", effort="max", model_metadata=meta)
        )
        # explicit thinking on is refused where the catalog says budgets are not accepted
        self.assertNotIn(
            "thinking",
            build(MSGS, "claude-future", effort="high", thinking=True, model_metadata=meta),
        )

    def test_reasoning_switch_follows_the_catalog(self):
        url = "https://api.anthropic.com"
        self.assertTrue(llm.reasoning_control_supported(url, "claude-sonnet-4"))
        self.assertFalse(
            llm.reasoning_control_supported(
                url, "claude-sonnet-4", anthropic_caps(ALL, enabled=False)
            )
        )
        self.assertFalse(llm.reasoning_control_supported("https://api.openai.com", "o3"))


URL = "https://api.anthropic.com"
BUDGET_MODELS = (
    "claude-3-7-sonnet-20250219",
    "claude-opus-4-1",
    "claude-opus-4-5-20251101",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
)
ADAPTIVE_MODELS = ("claude-opus-4-6", "claude-sonnet-4-6", "claude-opus-4-7", "claude-opus-4-8")
NO_SWITCH_MODELS = (
    "claude-fable-5",
    "claude-fable-5-1",
    "claude-mythos-5",
    "claude-mythos-preview",
    "claude-opus-5-5",
    "claude-sonnet-5-5",
)


def thinking_of(model, **kw):
    return llm._build_anthropic_payload(MSGS, model, **kw).get("thinking")


class ClaudeThinkingFamiliesTest(unittest.TestCase):
    def test_budget_models_use_budgets_and_off_just_omits(self):
        for model in BUDGET_MODELS:
            with self.subTest(model):
                found = caps.anthropic_thinking(model)
                self.assertEqual((found["on"], found["off"]), ("budget", "omit"))
                self.assertTrue(llm.reasoning_control_supported(URL, model))
                self.assertEqual(
                    thinking_of(model, thinking=True),
                    {"type": "enabled", "budget_tokens": 8000},
                )
                self.assertIsNone(thinking_of(model, thinking=False))

    def test_46_and_later_opus_and_sonnet_use_adaptive_and_disabled(self):
        for model in (*ADAPTIVE_MODELS, "claude-sonnet-5"):
            with self.subTest(model):
                found = caps.anthropic_thinking(model)
                self.assertEqual((found["on"], found["off"]), ("adaptive", "disabled"))
                self.assertTrue(llm.reasoning_control_supported(URL, model))
                self.assertEqual(thinking_of(model, thinking=True), {"type": "adaptive"})
                self.assertEqual(thinking_of(model, thinking=False), {"type": "disabled"})

    def test_no_budget_tokens_where_budgets_are_removed(self):
        removed = (
            "claude-opus-4-7",
            "claude-opus-4-8",
            "claude-opus-5",
            "claude-sonnet-5",
            *NO_SWITCH_MODELS,
        )
        for model in removed:
            for thinking in (None, True, False):
                for effort in ("", "high", "xhigh", "max"):
                    with self.subTest(model=model, thinking=thinking, effort=effort):
                        payload = llm._build_anthropic_payload(
                            MSGS, model, thinking=thinking, effort=effort
                        )
                        self.assertNotIn("budget_tokens", json.dumps(payload))
                        self.assertNotEqual((payload.get("thinking") or {}).get("type"), "enabled")

    def test_no_implicit_thinking_without_an_explicit_on(self):
        for model in (*ADAPTIVE_MODELS, "claude-opus-5", "claude-sonnet-5"):
            with self.subTest(model):
                self.assertIsNone(thinking_of(model, effort="high"))

    def test_adaptive_drops_temperature_like_budget_thinking(self):
        payload = llm._build_anthropic_payload(
            MSGS, "claude-opus-4-7", thinking=True, temperature=0.2
        )
        self.assertNotIn("temperature", payload)

    def test_opus_5_off_at_xhigh_or_max_is_lowered_to_high(self):
        for level in ("xhigh", "max"):
            payload = llm._build_anthropic_payload(
                MSGS, "claude-opus-5", thinking=False, effort=level
            )
            self.assertEqual(payload["thinking"], {"type": "disabled"})
            self.assertEqual(payload["output_config"], {"effort": "high"})
        payload = llm._build_anthropic_payload(
            MSGS, "claude-opus-5", thinking=False, effort="medium"
        )
        self.assertEqual(payload["output_config"], {"effort": "medium"})
        # on keeps the chosen level, and so does a model with no such limit
        payload = llm._build_anthropic_payload(MSGS, "claude-opus-5", thinking=True, effort="max")
        self.assertEqual(payload["output_config"], {"effort": "max"})
        self.assertEqual(payload["thinking"], {"type": "adaptive"})
        payload = llm._build_anthropic_payload(
            MSGS, "claude-opus-4-7", thinking=False, effort="xhigh"
        )
        self.assertEqual(payload["output_config"], {"effort": "xhigh"})
        payload = llm._build_anthropic_payload(
            MSGS, "claude-haiku-5-5", thinking=False, effort="max"
        )
        self.assertEqual(payload["output_config"], {"effort": "high"})

    def test_fable_mythos_and_55_models_have_no_switch_and_send_no_thinking(self):
        for model in NO_SWITCH_MODELS:
            with self.subTest(model):
                self.assertFalse(llm.reasoning_control_supported(URL, model))
                self.assertIsNone(thinking_of(model, thinking=True))
                self.assertIsNone(thinking_of(model, thinking=False))
        # effort still works on them
        payload = llm._build_anthropic_payload(MSGS, "claude-fable-5-1", effort="max")
        self.assertEqual(payload["output_config"], {"effort": "max"})

    def test_catalog_thinking_types_override_names(self):
        def types(**flags):
            return {
                "capabilities": {
                    "thinking": {
                        "supported": True,
                        "types": {k: {"supported": v} for k, v in flags.items()},
                    }
                }
            }

        adaptive_only = types(adaptive=True, enabled=False, disabled=False)
        self.assertFalse(llm.reasoning_control_supported(URL, "claude-new", adaptive_only))
        self.assertIsNone(thinking_of("claude-new", thinking=False, model_metadata=adaptive_only))
        both = types(adaptive=True, enabled=False, disabled=True)
        self.assertTrue(llm.reasoning_control_supported(URL, "claude-new", both))
        self.assertEqual(
            thinking_of("claude-new", thinking=True, model_metadata=both), {"type": "adaptive"}
        )
        self.assertEqual(
            thinking_of("claude-new", thinking=False, model_metadata=both), {"type": "disabled"}
        )
        # a catalog saying disabled is refused beats a name that would allow it
        refused = types(adaptive=True, enabled=False, disabled=False)
        self.assertFalse(llm.reasoning_control_supported(URL, "claude-opus-4-7", refused))
        budget = types(adaptive=False, enabled=True, disabled=True)
        self.assertEqual(
            thinking_of("claude-new", thinking=True, model_metadata=budget),
            {"type": "enabled", "budget_tokens": 8000},
        )
        self.assertIsNone(thinking_of("claude-new", thinking=False, model_metadata=budget))

    def test_switch_agrees_with_what_the_builder_sends(self):
        every = (
            *BUDGET_MODELS,
            *ADAPTIVE_MODELS,
            *NO_SWITCH_MODELS,
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-haiku-5-5",
            "claude-3-5-sonnet",
        )
        for model in every:
            with self.subTest(model):
                offered = llm.reasoning_control_supported(URL, model)
                on = thinking_of(model, thinking=True)
                off = thinking_of(model, thinking=False)
                if offered:
                    self.assertIn((on or {}).get("type"), {"adaptive", "enabled"})
                    self.assertIn((off or {}).get("type"), {None, "disabled"})
                else:
                    self.assertIsNone(on)
                    self.assertIsNone(off)


class RunControlTest(unittest.TestCase):
    def body(self, **values):
        return ChatRequest(session_id="s", message="hello", **values)

    def test_unsupported_provider_level_is_dropped_without_error(self):
        settings = {"agent_effort": "high"}
        _apply_run_controls(
            settings, self.body(effort="xhigh"), "https://api.openai.com", "o3-mini"
        )
        self.assertEqual(settings["agent_effort"], "")
        self.assertEqual(provider_effort(settings), "")
        settings = {}
        _apply_run_controls(
            settings, self.body(effort="high"), "https://api.deepseek.com", "deepseek-v4"
        )
        self.assertEqual(settings["agent_effort"], "")

    def test_supported_level_and_local_profiles_stay(self):
        settings = {}
        _apply_run_controls(settings, self.body(effort="high"), "https://api.openai.com", "o3-mini")
        self.assertEqual(settings["agent_effort"], "high")
        for effort in ("deep_work", "custom"):
            settings = {}
            _apply_run_controls(
                settings, self.body(effort=effort), "https://api.deepseek.com", "deepseek-v4"
            )
            self.assertEqual(settings["agent_effort"], effort)

    def test_catalog_metadata_reaches_the_gate(self):
        settings = {}
        meta = {"reasoning": {"supported_efforts": ["low"]}}
        _apply_run_controls(
            settings, self.body(effort="low"), "https://openrouter.ai/api/v1", "v/m", meta
        )
        self.assertEqual(settings["agent_effort"], "low")

    def test_reasoning_switch_still_refused_where_unsupported(self):
        with self.assertRaises(ApiError):
            _apply_run_controls({}, self.body(reasoning_mode="on"), "https://api.openai.com", "o3")

    def test_automatic_sends_no_provider_level(self):
        self.assertEqual(provider_effort({}), "")
        self.assertEqual(provider_effort({"agent_effort": "deep_work"}), "high")


class ModelsPayloadTest(ApiTest):
    def seed(self, base_url, models, metadata=None):
        db = self.db()
        ep = ModelEndpoint(
            name="p",
            base_url=base_url,
            cached_models=json.dumps(models),
            model_metadata=json.dumps(metadata or {}),
        )
        db.add(ep)
        db.commit()
        db.close()

    def test_payload_lists_each_models_effort_levels_and_reasoning_switch(self):
        self.seed("https://api.openai.com/v1", ["o3-mini", "gpt-5.2", "gpt-4o"])
        listed = self.client.get("/api/models").json()[0]
        self.assertEqual(
            listed["effort_levels"],
            {"o3-mini": ["low", "medium", "high"], "gpt-5.2": ["low", "medium", "high", "xhigh"]},
        )
        self.assertEqual(listed["reasoning_control"], [])

    def test_payload_uses_stored_catalog_metadata(self):
        self.seed(
            "https://openrouter.ai/api/v1",
            ["a/with", "a/without"],
            {"a/with": {"reasoning": {"supported_efforts": ["low", "high"]}}},
        )
        listed = self.client.get("/api/models").json()[0]
        self.assertEqual(listed["effort_levels"], {"a/with": ["low", "high"]})

    def test_deepseek_has_no_levels_but_a_reasoning_switch(self):
        self.seed("https://api.deepseek.com", ["deepseek-v4"])
        listed = self.client.get("/api/models").json()[0]
        self.assertEqual(listed["effort_levels"], {})
        self.assertEqual(listed["reasoning_control"], ["deepseek-v4"])


if __name__ == "__main__":
    unittest.main()
