import unittest

from services import llm


class DetectProviderTests(unittest.TestCase):
    CASES = {
        "https://api.anthropic.com": "anthropic",
        "https://api.deepseek.com": "deepseek",
        "https://openrouter.ai/api/v1": "openrouter",
        "https://api.groq.com/openai/v1": "groq",
        "https://api.x.ai/v1": "xai",
        "https://api.openai.com/v1": "openai",
        "http://localhost:11434": "ollama",
        "http://localhost:11434/v1": "ollama",
        "https://my-ollama-box:11434": "ollama",
        "https://example.com/v1": "openai",  # unknown -> openai-compat fallback
    }

    def test_detect(self):
        for url, expected in self.CASES.items():
            self.assertEqual(llm.detect_provider(url), expected, url)


class AnthropicImageBlocksTests(unittest.TestCase):
    def test_data_url_to_base64_block(self):
        content = [
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
        ]
        out = llm._anthropic_blocks(content)
        self.assertEqual(out[0], {"type": "text", "text": "look"})
        self.assertEqual(out[1]["type"], "image")
        self.assertEqual(out[1]["source"]["media_type"], "image/png")
        self.assertEqual(out[1]["source"]["data"], "QUJD")

    def test_plain_string_passthrough(self):
        self.assertEqual(llm._anthropic_blocks("hi"), "hi")


class AnthropicPayloadTests(unittest.TestCase):
    def test_system_split_and_tool_conversion(self):
        msgs = [
            {"role": "system", "content": "be nice"},
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"call_id": "c1", "name": "shell", "args": {"command": "ls"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        ]
        p = llm._build_anthropic_payload(msgs, "claude-x", tools=[])
        self.assertEqual(p["system"], "be nice")
        self.assertTrue(all(m["role"] != "system" for m in p["messages"]))
        # assistant tool_use block present
        asst = [m for m in p["messages"] if m["role"] == "assistant"][0]
        self.assertEqual(asst["content"][0]["type"], "tool_use")

    def test_temperature_threads_through(self):
        msgs = [{"role": "user", "content": "hi"}]
        # anthropic builder used to silently drop temperature
        self.assertEqual(
            llm._build_anthropic_payload(msgs, "claude-x", temperature=0.2)["temperature"], 0.2
        )
        self.assertEqual(
            llm._build_openai_payload(msgs, "gpt-x", temperature=0.2)["temperature"], 0.2
        )
        # absent → not forced into the payload
        self.assertNotIn("temperature", llm._build_anthropic_payload(msgs, "claude-x"))
        self.assertNotIn("temperature", llm._build_openai_payload(msgs, "gpt-x"))


class OpenAIUsagePayloadTests(unittest.TestCase):
    # deepseek (+ other openai-compatible) must request usage on streamed replies,
    # else the usage dashboard has no tokens to show for them
    def test_include_usage_for_compatible_providers(self):
        msgs = [{"role": "user", "content": "hi"}]
        for prov in ("openai", "deepseek", "openrouter", "groq", "xai"):
            p = llm._build_openai_payload(msgs, "m", stream=True, provider=prov)
            self.assertEqual(p.get("stream_options"), {"include_usage": True}, prov)

    def test_no_usage_flag_when_unsupported_or_not_streaming(self):
        msgs = [{"role": "user", "content": "hi"}]
        self.assertNotIn(
            "stream_options",
            llm._build_openai_payload(msgs, "m", stream=False, provider="deepseek"),
        )
        self.assertNotIn(
            "stream_options", llm._build_openai_payload(msgs, "m", stream=True, provider="gemini")
        )


if __name__ == "__main__":
    unittest.main()
