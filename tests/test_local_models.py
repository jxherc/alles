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


if __name__ == "__main__":
    unittest.main()
