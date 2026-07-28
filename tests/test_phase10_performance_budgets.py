"""Representative Phase 10 server and release-payload performance budgets.

Payload bounds run in the regular suite. Absolute latency budgets are an opt-in benchmark because
wall-clock scheduling noise on shared runners is not an application correctness signal.
"""

from __future__ import annotations

import math
import os
import time
import unittest
from pathlib import Path

from tests._client import ApiTest

ROOT = Path(__file__).resolve().parents[1]


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


class Phase10PerformanceBudgetTests(ApiTest):
    BUDGETS_MS = {
        "/": 750.0,
        "/api/health": 250.0,
        "/api/settings/localization/options": 500.0,
        "/api/credits": 1_000.0,
    }

    @unittest.skipUnless(
        os.environ.get("ALLES_RUN_PERFORMANCE_BUDGETS") == "1",
        "controlled performance benchmark only",
    )
    def test_representative_warm_server_paths_stay_within_p95_budgets(self):
        results: dict[str, float] = {}
        for path, budget_ms in self.BUDGETS_MS.items():
            warm = self.client.get(path)
            self.assertEqual(warm.status_code, 200, path)
            samples = []
            for _ in range(25):
                started = time.perf_counter()
                response = self.client.get(path)
                samples.append((time.perf_counter() - started) * 1_000)
                self.assertEqual(response.status_code, 200, path)
            results[path] = _p95(samples)
            self.assertLess(results[path], budget_ms, f"{path} p95 exceeded {budget_ms} ms")
        print("phase10 server p95 ms", {path: round(value, 2) for path, value in results.items()})

    def test_release_payloads_stay_bounded_and_credits_remain_metadata_only(self):
        root = self.client.get("/")
        credits = self.client.get("/api/credits")
        localization = self.client.get("/api/settings/localization/options")
        self.assertLess(len(root.content), 350_000)
        self.assertLess(len(credits.content), 500_000)
        self.assertLess(len(localization.content), 25_000)
        self.assertTrue(
            all("license_texts" not in entry for entry in credits.json()["entries"]),
            "the metadata list must not eagerly load license bodies",
        )
        catalogs = sorted((ROOT / "static" / "locales").glob("*.json"))
        sizes = {path.name: path.stat().st_size for path in catalogs}
        self.assertTrue(sizes)
        self.assertLess(max(sizes.values()), 40_000)
        print(
            "phase10 payload bytes",
            {
                "root": len(root.content),
                "credits": len(credits.content),
                "localization_options": len(localization.content),
                "largest_catalog": max(sizes.values()),
            },
        )


if __name__ == "__main__":
    unittest.main()
