import unittest

from services import local_models


class LocalModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._jobs = dict(local_models._jobs)
        local_models._jobs.clear()

    def tearDown(self):
        local_models._jobs.clear()
        local_models._jobs.update(self._jobs)

    def test_rejects_shell_like_model_names(self):
        with self.assertRaises(ValueError):
            local_models._validate_model("llama3.2:3b; rm -rf data")

    def test_accepts_known_preset_model(self):
        self.assertEqual(local_models._validate_model("llama3.2:3b"), "llama3.2:3b")

    def test_delete_rejects_bad_name(self):
        with self.assertRaises(ValueError):
            local_models.delete_model("evil; rm -rf /")

    async def test_hwfit_marks_installed_and_prefers_gpu_fit(self):
        old_profile = local_models.hardware_profile
        old_installed = local_models.installed_models
        try:
            local_models.hardware_profile = lambda: {
                "system": "test",
                "machine": "x64",
                "ram_gb": 32,
                "gpus": [{"name": "Test GPU", "vram_gb": 8}],
                "best_vram_gb": 8,
            }

            async def installed():
                return ["llama3.2:3b"]

            local_models.installed_models = installed
            result = await local_models.hwfit()
        finally:
            local_models.hardware_profile = old_profile
            local_models.installed_models = old_installed

        tiny = next(p for p in result["presets"] if p["model"] == "llama3.2:3b")
        self.assertEqual(tiny["fit"], "fits_gpu")
        self.assertTrue(tiny["installed"])

    def test_active_download_job_is_reused(self):
        local_models._set_job(
            "job-1",
            id="job-1",
            type="download_model",
            model="llama3.2:3b",
            status="running",
            created_at=1,
        )
        found = local_models.find_active_download("llama3.2:3b")
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], "job-1")

    def test_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            local_models._validate_model("")

    def test_validate_strips_whitespace(self):
        # spaces around a valid preset name → valid after strip
        result = local_models._validate_model("  llama3.2:3b  ")
        self.assertEqual(result, "llama3.2:3b")

    def test_find_active_download_returns_none_if_done(self):
        local_models._set_job(
            "job-2",
            id="job-2",
            type="download_model",
            model="llama3.1:8b",
            status="done",
            created_at=1,
        )
        self.assertIsNone(local_models.find_active_download("llama3.1:8b"))

    def test_find_active_download_queued(self):
        local_models._set_job(
            "job-3",
            id="job-3",
            type="download_model",
            model="deepseek-r1:8b",
            status="queued",
            created_at=2,
        )
        found = local_models.find_active_download("deepseek-r1:8b")
        self.assertIsNotNone(found)
        self.assertEqual(found["status"], "queued")

    def test_get_job_returns_none_for_missing(self):
        self.assertIsNone(local_models.get_job("no-such-job-id"))

    def test_list_jobs_returns_sorted(self):
        local_models._set_job("j-b", id="j-b", type="download_model", model="a", status="done", created_at=2)
        local_models._set_job("j-a", id="j-a", type="download_model", model="b", status="done", created_at=1)
        lst = local_models.list_jobs()
        # newest first
        self.assertEqual(lst[0]["id"], "j-b")

    async def test_hwfit_too_large_when_no_vram(self):
        old_profile = local_models.hardware_profile
        old_installed = local_models.installed_models
        try:
            local_models.hardware_profile = lambda: {
                "system": "test",
                "machine": "x64",
                "ram_gb": 4,  # too little for anything
                "gpus": [],
                "best_vram_gb": 0,
            }

            async def installed():
                return []

            local_models.installed_models = installed
            result = await local_models.hwfit()
        finally:
            local_models.hardware_profile = old_profile
            local_models.installed_models = old_installed

        # all presets should be too_large with 4GB RAM and no GPU
        for p in result["presets"]:
            self.assertEqual(p["fit"], "too_large", msg=f"{p['model']} should be too_large")

    def test_presets_have_required_keys(self):
        required = {"id", "label", "model", "family", "params_b", "vram_gb", "ram_gb"}
        for p in local_models.PRESETS:
            for k in required:
                self.assertIn(k, p, msg=f"preset {p.get('id')} missing key {k}")


if __name__ == "__main__":
    unittest.main()
