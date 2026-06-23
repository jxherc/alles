"""stage 4d - Base computed/formula fields. tests first (RED)."""

import os
import unittest

os.environ["AUTH_ENABLED"] = "false"
from services import base_formula as bf


class FormulaTests(unittest.TestCase):
    def test_arithmetic_precedence(self):
        self.assertEqual(bf.evaluate("{a} + {b} * 2", {"a": 1, "b": 3}), 7)

    def test_multiply_fields(self):
        self.assertEqual(bf.evaluate("{price} * {qty}", {"price": 2.5, "qty": 4}), 10.0)

    def test_comparison_bool(self):
        self.assertEqual(bf.evaluate("{x} > 5", {"x": 10}), True)
        self.assertEqual(bf.evaluate("{x} > 5", {"x": 2}), False)

    def test_ternary(self):
        self.assertEqual(bf.evaluate("'shipped' if {done} else 'open'", {"done": True}), "shipped")
        self.assertEqual(bf.evaluate("'shipped' if {done} else 'open'", {"done": False}), "open")

    def test_string_concat(self):
        self.assertEqual(
            bf.evaluate("{first} + ' ' + {last}", {"first": "Ada", "last": "L"}), "Ada L"
        )

    def test_round_function(self):
        self.assertEqual(bf.evaluate("round({v}, 1)", {"v": 3.14159}), 3.1)

    def test_len_and_upper(self):
        self.assertEqual(bf.evaluate("len({s})", {"s": "abc"}), 3)
        self.assertEqual(bf.evaluate("upper({s})", {"s": "hi"}), "HI")

    def test_missing_field_default(self):
        # an unreferenced/missing field resolves to 0 so numeric formulas still compute
        self.assertEqual(bf.evaluate("{a} + {missing}", {"a": 5}), 5)

    def test_numeric_string_coercion(self):
        self.assertEqual(bf.evaluate("{a} * 2", {"a": "3"}), 6)

    def test_div_by_zero_safe(self):
        out = bf.evaluate("{a} / {b}", {"a": 1, "b": 0})
        self.assertIsInstance(out, dict)
        self.assertIn("error", out)

    def test_malicious_import_rejected(self):
        out = bf.evaluate("__import__('os').system('echo hi')", {})
        self.assertIsInstance(out, dict)
        self.assertIn("error", out)

    def test_attribute_access_rejected(self):
        out = bf.evaluate("{a}.__class__", {"a": 1})
        self.assertIsInstance(out, dict)
        self.assertIn("error", out)

    def test_unknown_function_rejected(self):
        out = bf.evaluate("eval('1')", {})
        self.assertIsInstance(out, dict)
        self.assertIn("error", out)

    def test_huge_power_rejected(self):
        # 9**9**9 would compute a ~370M-digit int and hang the process - must be refused fast
        out = bf.evaluate("9**9**9", {})
        self.assertIsInstance(out, dict)
        self.assertIn("error", out)

    def test_small_power_still_works(self):
        self.assertEqual(bf.evaluate("{a} ** 2", {"a": 5}), 25)

    def test_huge_string_mult_rejected(self):
        out = bf.evaluate("'ab' * 50000000", {})
        self.assertIsInstance(out, dict)
        self.assertIn("error", out)

    def test_small_repeat_ok(self):
        self.assertEqual(bf.evaluate("'-' * 3", {}), "---")


if __name__ == "__main__":
    unittest.main()
