import unittest
from unittest import mock

from services.hwfit import fit
from services.hwfit.models import get_models, params_b, estimate_memory_gb

# synthetic systems so these tests don't depend on the host's actual hardware
BIG_GPU = {"has_gpu": True, "gpu_vram_gb": 80, "gpu_count": 1, "available_ram_gb": 128,
           "gpu_name": "a100", "backend": "cuda", "gpu_family": "", "gpu_only": False}
TINY = {"has_gpu": False, "gpu_vram_gb": 0, "gpu_count": 1, "available_ram_gb": 6,
        "gpu_name": "", "backend": "cpu_x86", "gpu_family": ""}

VALID_FIT = {"perfect", "good", "marginal", "too_tight"}


class CatalogTests(unittest.TestCase):
    def test_catalog_loads(self):
        models = get_models()
        self.assertGreater(len(models), 200)   # real catalog is ~900
        self.assertIn("name", models[0])

    def test_rank_sorted_and_shaped(self):
        rows = fit.rank_models(BIG_GPU, use_case="general", limit=10)
        self.assertTrue(rows)
        for r in rows:
            self.assertIn(r["fit_level"], VALID_FIT)
            self.assertIn("score", r)
            self.assertIn("required_gb", r)
        scores = [r["score"] for r in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))   # descending

    def test_search_filters(self):
        rows = fit.rank_models(BIG_GPU, search="qwen", limit=20)
        self.assertTrue(rows)
        for r in rows:
            self.assertIn("qwen", (r["name"] + r.get("provider", "")).lower())

    def test_tiny_box_marks_big_models_too_tight(self):
        rows = fit.rank_models(TINY, sort="params", limit=5)   # biggest models
        # a 6GB CPU box can't fit the largest models
        self.assertTrue(any(r["fit_level"] == "too_tight" for r in rows))


class ScoringTests(unittest.TestCase):
    def test_fit_score_bounds(self):
        self.assertEqual(fit._fit_score(100, 50), 0)     # doesn't fit
        self.assertEqual(fit._fit_score(10, 16), 100)    # comfy (ratio ~0.6)
        self.assertEqual(fit._fit_score(5, 0), 0)        # no budget

    def test_quant_bits(self):
        self.assertEqual(fit._quant_bits("Q4_K_M"), 4)
        self.assertEqual(fit._quant_bits("Q8_0"), 8)
        self.assertEqual(fit._quant_bits("AWQ-4bit"), 4)
        self.assertEqual(fit._quant_bits("FP8"), 8)
        self.assertEqual(fit._quant_bits("BF16"), 16)

    def test_version_key_ignores_param_counts(self):
        self.assertEqual(fit._version_key("MiniMax-M2.7"), 2.7)
        self.assertEqual(fit._version_key("Qwen3-235B"), 3.0)   # 3, not 235
        self.assertEqual(fit._version_key("plain"), 0.0)

    def test_bandwidth_lookup_longest_match(self):
        # "m4 max" must win over "m4"
        self.assertEqual(fit._lookup_bandwidth("Apple M4 Max"), 546)
        self.assertEqual(fit._lookup_bandwidth("Apple M4"), 120)
        self.assertEqual(fit._lookup_bandwidth("RTX 4090"), 1008)

    def test_memory_estimate_positive(self):
        m = next(x for x in get_models() if params_b(x) > 1)
        self.assertGreater(estimate_memory_gb(m, "Q4_K_M", 4096), 0)


class SystemCacheTests(unittest.TestCase):
    def test_detect_system_is_cached(self):
        from services import local_models as lm
        from services.hwfit import hardware
        lm._sys_cache = None
        calls = []
        def fake():
            calls.append(1)
            return {"backend": "x"}
        with mock.patch.object(hardware, "detect_system", fake):
            a = lm.detect_system_info()
            b = lm.detect_system_info()
        lm._sys_cache = None        # don't leak the fake into other tests
        self.assertIs(a, b)         # same cached object
        self.assertEqual(len(calls), 1)   # probed once, not twice


if __name__ == "__main__":
    unittest.main()
