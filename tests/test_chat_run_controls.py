import unittest

from core.api_errors import ApiError
from routes.chat import ChatRequest, CustomEffort, _apply_run_controls


class RunControlTests(unittest.TestCase):
    def request(self, **changes):
        values = {"session_id": "session", "message": "hello"}
        values.update(changes)
        return ChatRequest(**values)

    def test_deep_work_enables_bounded_delegation_only_for_real_work(self):
        simple = self.request(effort="deep_work", message="say hello")
        settings = {}
        _apply_run_controls(settings, simple, "https://api.deepseek.com", "deepseek-v4")
        self.assertEqual(settings["agent_effort"], "deep_work")
        self.assertFalse(settings["agent_subagents"])

        involved = self.request(
            effort="deep_work",
            message="Inspect the backend and frontend, fix every related issue, then run the full test suite.",
        )
        settings = {}
        _apply_run_controls(settings, involved, "https://api.deepseek.com", "deepseek-v4")
        self.assertTrue(settings["agent_subagents"])

    def test_long_cjk_task_is_nontrivial_without_space_delimited_words(self):
        involved = self.request(
            effort="deep_work",
            message="請檢查整個後端與前端實作並修復所有相關問題然後執行完整測試套件確認沒有任何回歸問題最後整理實際完成的內容與仍需人工驗證的項目並保持現有資料完整不被覆蓋或刪除",
        )
        settings = {}
        _apply_run_controls(settings, involved, "https://api.deepseek.com", "deepseek-v4")
        self.assertTrue(settings["agent_subagents"])

    def test_custom_profile_is_translated_for_runtime(self):
        body = self.request(
            effort="custom",
            reasoning_mode="off",
            message="Review the whole implementation, repair the problems, and verify all affected paths.",
            custom_effort=CustomEffort(
                max_turns=32,
                verification="thorough",
                delegation="auto",
                workflows="auto",
            ),
        )
        settings = {}
        _apply_run_controls(settings, body, "https://api.deepseek.com", "deepseek-v4")
        self.assertEqual(settings["agent_reasoning_mode"], "off")
        self.assertEqual(settings["agent_custom_effort"]["max_turns"], 32)
        self.assertTrue(settings["agent_subagents"])

    def test_unsupported_explicit_reasoning_is_rejected(self):
        body = self.request(reasoning_mode="on")
        with self.assertRaises(ApiError) as caught:
            _apply_run_controls({}, body, "https://api.openai.com", "gpt-4o-mini")
        self.assertEqual(caught.exception.code, "reasoning_control_unsupported")


if __name__ == "__main__":
    unittest.main()
