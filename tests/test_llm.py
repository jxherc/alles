import asyncio
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

    def test_additional_providers(self):
        cases = {
            "https://api.mistral.ai/v1": "mistral",
            "https://api.perplexity.ai": "perplexity",
            "https://api.together.xyz/v1": "together",
            "https://api.fireworks.ai/inference/v1": "fireworks",
            "https://api.cohere.com/v1": "cohere",
            "https://generativelanguage.googleapis.com/v1beta": "gemini",
            "https://api.moonshot.cn/v1": "moonshot",
        }
        for url, expected in cases.items():
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

    def test_http_image_url_block(self):
        content = [{"type": "image_url", "image_url": {"url": "https://example.com/img.jpg"}}]
        out = llm._anthropic_blocks(content)
        self.assertEqual(out[0]["type"], "image")
        self.assertEqual(out[0]["source"]["type"], "url")
        self.assertEqual(out[0]["source"]["url"], "https://example.com/img.jpg")

    def test_empty_list(self):
        self.assertEqual(llm._anthropic_blocks([]), [])


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

    def test_thinking_payload_on_supported_model(self):
        msgs = [{"role": "user", "content": "think"}]
        p = llm._build_anthropic_payload(msgs, "claude-3-7-sonnet", effort="high")
        self.assertIn("thinking", p)
        self.assertEqual(p["thinking"]["budget_tokens"], 8000)
        # temperature must be stripped when thinking is on
        self.assertNotIn("temperature", p)

    def test_thinking_not_added_for_nonsupporting_model(self):
        msgs = [{"role": "user", "content": "think"}]
        p = llm._build_anthropic_payload(msgs, "claude-3-5-sonnet", effort="high")
        self.assertNotIn("thinking", p)

    def test_multiple_system_messages_joined(self):
        msgs = [
            {"role": "system", "content": "rule one"},
            {"role": "system", "content": "rule two"},
            {"role": "user", "content": "go"},
        ]
        p = llm._build_anthropic_payload(msgs, "m")
        self.assertIn("rule one", p["system"])
        self.assertIn("rule two", p["system"])

    def test_tool_result_message_converted(self):
        msgs = [
            {"role": "user", "content": "do x"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"call_id": "t1", "name": "search", "args": {}}],
            },
            {"role": "tool", "tool_call_id": "t1", "content": "result text"},
        ]
        p = llm._build_anthropic_payload(msgs, "m")
        tool_result_msg = [m for m in p["messages"] if m["role"] == "user"][-1]
        self.assertEqual(tool_result_msg["content"][0]["type"], "tool_result")
        self.assertEqual(tool_result_msg["content"][0]["content"], "result text")

    def test_tools_converted_to_anthropic_format(self):
        msgs = [{"role": "user", "content": "hi"}]
        tools = [
            {
                "function": {
                    "name": "get_weather",
                    "description": "returns weather",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                }
            }
        ]
        p = llm._build_anthropic_payload(msgs, "m", tools=tools)
        self.assertEqual(p["tools"][0]["name"], "get_weather")
        self.assertIn("input_schema", p["tools"][0])


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

    def test_oai_reasoning_effort_set_for_o_models(self):
        msgs = [{"role": "user", "content": "hi"}]
        p = llm._build_openai_payload(msgs, "o3-mini", provider="openai", effort="high")
        self.assertEqual(p["reasoning_effort"], "high")

    def test_oai_reasoning_effort_not_set_for_non_reasoning(self):
        msgs = [{"role": "user", "content": "hi"}]
        p = llm._build_openai_payload(msgs, "gpt-4", provider="openai", effort="high")
        self.assertNotIn("reasoning_effort", p)

    def test_tools_added_with_auto_choice(self):
        msgs = [{"role": "user", "content": "hi"}]
        tools = [{"function": {"name": "f", "description": "d", "parameters": {}}}]
        p = llm._build_openai_payload(msgs, "m", tools=tools)
        self.assertEqual(p["tool_choice"], "auto")
        self.assertEqual(p["tools"], tools)


class CooldownTests(unittest.TestCase):
    def setUp(self):
        # clean state before each test
        llm._fail_counts.clear()
        llm._cooldowns.clear()

    def tearDown(self):
        llm._fail_counts.clear()
        llm._cooldowns.clear()

    def test_two_fails_trigger_cooldown(self):
        url = "http://dead.host/v1"
        llm._mark_fail(url)
        self.assertFalse(llm._is_cooling(url))
        llm._mark_fail(url)
        self.assertTrue(llm._is_cooling(url))

    def test_mark_ok_clears_cooldown(self):
        url = "http://flaky.host/v1"
        llm._mark_fail(url)
        llm._mark_fail(url)
        self.assertTrue(llm._is_cooling(url))
        llm._mark_ok(url)
        self.assertFalse(llm._is_cooling(url))

    def test_clear_cooldown_alias(self):
        url = "http://other.host/v1"
        llm._mark_fail(url)
        llm._mark_fail(url)
        llm.clear_cooldown(url)
        self.assertFalse(llm._is_cooling(url))

    def test_separate_hosts_independent(self):
        llm._mark_fail("http://a.host/v1")
        llm._mark_fail("http://a.host/v1")
        # b.host should not be in cooldown
        self.assertFalse(llm._is_cooling("http://b.host/v1"))


class ParseOpenAITests(unittest.TestCase):
    def _run(self, lines):
        class FakeResp:
            async def aiter_lines(self_):
                for l in lines:
                    yield l

        async def go():
            evts = []
            async for ev in llm._parse_openai(FakeResp()):
                evts.append(ev)
            return evts

        return asyncio.run(go())

    def test_text_delta_and_done(self):
        lines = [
            'data: {"choices":[{"delta":{"content":"hello"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]
        evts = self._run(lines)
        self.assertEqual(evts[0], {"delta": "hello"})
        self.assertTrue(evts[-1]["done"])

    def test_tool_call_accumulated(self):
        lines = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"shell","arguments":""}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"cmd\\":\\"ls\\"}"}}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]
        evts = self._run(lines)
        tc = next(e for e in evts if "tool_call" in e)
        self.assertEqual(tc["tool_call"]["name"], "shell")
        self.assertEqual(tc["tool_call"]["args"], {"cmd": "ls"})

    def test_tool_call_flushed_without_done_sentinel(self):
        # some openai-compat servers end the stream without a [DONE] line. the tool
        # call must still be emitted (it was getting dropped on the fallthrough path).
        lines = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c9","function":{"name":"search","arguments":"{\\"q\\":\\"x\\"}"}}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        ]
        evts = self._run(lines)
        tc = next((e for e in evts if "tool_call" in e), None)
        self.assertIsNotNone(tc, "tool call was dropped when stream ended without [DONE]")
        self.assertEqual(tc["tool_call"]["name"], "search")
        self.assertEqual(tc["tool_call"]["args"], {"q": "x"})
        # and exactly one tool_call event (no duplicate flush)
        self.assertEqual(sum(1 for e in evts if "tool_call" in e), 1)

    def test_usage_captured(self):
        lines = [
            'data: {"choices":[{"delta":{"content":"x"},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":2}}',
            "data: [DONE]",
        ]
        evts = self._run(lines)
        done = next(e for e in evts if e.get("done"))
        # usage in the same chunk as finish_reason still reaches the done event
        self.assertEqual(done["usage"].get("prompt_tokens"), 5)
        self.assertEqual(done["usage"].get("completion_tokens"), 2)

    def test_usage_in_trailing_chunk_after_finish(self):
        # real OpenAI-compat shape (deepseek/openai/groq/…): finish_reason arrives first,
        # then a SEPARATE chunk carries usage, then [DONE]. must not be dropped.
        lines = [
            'data: {"choices":[{"delta":{"content":"hi"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":3}}',
            "data: [DONE]",
        ]
        evts = self._run(lines)
        done = next(e for e in evts if e.get("done"))
        self.assertEqual(done["usage"].get("prompt_tokens"), 10)
        self.assertEqual(done["usage"].get("completion_tokens"), 3)

    def test_tool_calls_not_double_emitted_with_trailing_usage(self):
        # finish no longer returns early — make sure tool calls aren't emitted twice
        lines = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"shell","arguments":"{}"}}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":1}}',
            "data: [DONE]",
        ]
        evts = self._run(lines)
        tool_calls = [e for e in evts if "tool_call" in e]
        self.assertEqual(len(tool_calls), 1)

    def test_reasoning_content_yields_thinking(self):
        lines = [
            'data: {"choices":[{"delta":{"reasoning_content":"let me think"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]
        evts = self._run(lines)
        thinking = next(e for e in evts if "thinking" in e)
        self.assertEqual(thinking["thinking"], "let me think")

    def test_malformed_json_lines_skipped(self):
        lines = [
            "data: not-json",
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            "data: [DONE]",
        ]
        evts = self._run(lines)
        self.assertTrue(any("delta" in e for e in evts))


class ParseAnthropicTests(unittest.TestCase):
    def _run(self, lines):
        class FakeResp:
            async def aiter_lines(self_):
                for l in lines:
                    yield l

        async def go():
            evts = []
            async for ev in llm._parse_anthropic(FakeResp()):
                evts.append(ev)
            return evts

        return asyncio.run(go())

    def test_text_delta_and_done(self):
        lines = [
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"world"}}',
            'data: {"type":"message_delta","usage":{"output_tokens":10}}',
            'data: {"type":"message_stop"}',
        ]
        evts = self._run(lines)
        self.assertEqual(evts[0], {"delta": "world"})
        self.assertEqual(evts[-1], {"done": True, "usage": {"output_tokens": 10}})

    def test_thinking_delta(self):
        lines = [
            'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"hmm"}}',
            'data: {"type":"message_stop"}',
        ]
        evts = self._run(lines)
        self.assertEqual(evts[0], {"thinking": "hmm"})

    def test_tool_call_assembled(self):
        lines = [
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"tu1","name":"calc"}}',
            'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"v\\":1}"}}',
            'data: {"type":"content_block_stop"}',
            'data: {"type":"message_stop"}',
        ]
        evts = self._run(lines)
        tc = next(e for e in evts if "tool_call" in e)
        self.assertEqual(tc["tool_call"]["name"], "calc")
        self.assertEqual(tc["tool_call"]["args"], {"v": 1})


class ParseOllamaTests(unittest.TestCase):
    def _run(self, lines):
        class FakeResp:
            async def aiter_lines(self_):
                for l in lines:
                    yield l

        async def go():
            evts = []
            async for ev in llm._parse_ollama(FakeResp()):
                evts.append(ev)
            return evts

        return asyncio.run(go())

    def test_basic_stream_and_done(self):
        lines = [
            '{"message":{"content":"hi"},"done":false}',
            '{"message":{"content":" there"},"done":true,"prompt_eval_count":3,"eval_count":5}',
        ]
        evts = self._run(lines)
        self.assertEqual(evts[0], {"delta": "hi"})
        done = next(e for e in evts if e.get("done"))
        self.assertEqual(done["usage"]["prompt_tokens"], 3)
        self.assertEqual(done["usage"]["completion_tokens"], 5)

    def test_empty_lines_skipped(self):
        lines = [
            "",
            '{"message":{"content":"x"},"done":true}',
        ]
        evts = self._run(lines)
        self.assertTrue(any(e.get("done") for e in evts))


if __name__ == "__main__":
    unittest.main()
