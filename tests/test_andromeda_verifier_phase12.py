import json
from unittest import mock

from core.database import AndromedaVerificationJob, ModelEndpoint
from core.settings import save_settings
from services import andromeda_verifier
from tests._client import ApiTest


class AndromedaVerifierValidationTest(ApiTest):
    def setUp(self):
        super().setUp()
        self.flags = mock.patch.dict(
            "os.environ",
            {"ALLES_AFTERLIFE_FEATURES": "afterlife_shell,afterlife_andromeda"},
            clear=False,
        )
        self.flags.start()

    def tearDown(self):
        self.flags.stop()
        super().tearDown()

    @staticmethod
    def _answer():
        return {
            "status": "ready",
            "claims": [
                {
                    "text": "SQLite 3.50.4 was released on 2026-07-17.",
                    "citations": [],
                }
            ],
        }

    @staticmethod
    def _evidence():
        return [
            {
                "id": "s1",
                "title": "official changes",
                "url": "https://sqlite.org/changes.html",
                "source_kind": "release notes",
                "source_quality": 2,
                "versions": ["3.50.4"],
                "dates": ["2026-07-18"],
                "passages": ["SQLite 3.50.4 was released on 2026-07-18."],
            }
        ]

    def _endpoint(self, url="http://127.0.0.1:11434"):
        db = self.db()
        endpoint = ModelEndpoint(
            name="verifier fixture",
            base_url=url,
            cached_models=json.dumps(["verify-small"]),
            enabled=True,
        )
        db.add(endpoint)
        db.commit()
        db.refresh(endpoint)
        endpoint_id = endpoint.id
        db.close()
        return endpoint_id

    def test_default_policy_checks_only_freshness_sensitive_queries(self):
        settings = {
            "andromeda_verification_enabled": True,
            "andromeda_verifier_mode": "freshness-sensitive",
        }
        self.assertTrue(andromeda_verifier.should_verify(settings, "latest sqlite release"))
        self.assertFalse(andromeda_verifier.should_verify(settings, "how does a b-tree work"))
        settings["andromeda_verifier_mode"] = "manual"
        self.assertFalse(andromeda_verifier.should_verify(settings, "latest sqlite release"))
        self.assertTrue(
            andromeda_verifier.should_verify(settings, "latest sqlite release", manual=True)
        )

    def test_correction_requires_an_exact_supporting_quote(self):
        raw = json.dumps(
            {
                "verdicts": [
                    {
                        "claim_index": 0,
                        "verdict": "corrected",
                        "correction": "SQLite 3.50.4 was released on 2026-07-18.",
                        "citations": [
                            {
                                "source_id": "s1",
                                "quote": "SQLite 3.50.4 was released on 2026-07-18.",
                            }
                        ],
                    }
                ]
            }
        )
        checked = andromeda_verifier.validate_verifier_output(
            raw, "latest sqlite release", self._answer(), self._evidence()
        )
        self.assertEqual(checked["status"], "checked")
        self.assertEqual(checked["counts"]["corrected"], 1)
        self.assertEqual(checked["changes"][0]["before"], self._answer()["claims"][0]["text"])
        self.assertEqual(
            checked["corrected_claims"][0]["text"],
            "SQLite 3.50.4 was released on 2026-07-18.",
        )

    def test_fabricated_correction_is_downgraded_to_insufficient(self):
        raw = json.dumps(
            {
                "verdicts": [
                    {
                        "claim_index": 0,
                        "verdict": "corrected",
                        "correction": "SQLite 9.9.9 was released on 2026-07-19.",
                        "citations": [{"source_id": "s1", "quote": "not in the source"}],
                    }
                ]
            }
        )
        checked = andromeda_verifier.validate_verifier_output(
            raw, "latest sqlite release", self._answer(), self._evidence()
        )
        self.assertEqual(checked["counts"]["insufficient"], 1)
        self.assertEqual(checked["changes"], [])
        self.assertEqual(checked["rejected_verdicts"], 1)

    def test_quote_whitespace_must_match_the_source_exactly(self):
        raw = json.dumps(
            {
                "verdicts": [
                    {
                        "claim_index": 0,
                        "verdict": "corrected",
                        "correction": "SQLite 3.50.4 was released on 2026-07-18.",
                        "citations": [
                            {
                                "source_id": "s1",
                                "quote": "SQLite 3.50.4   was released on 2026-07-18.",
                            }
                        ],
                    }
                ]
            }
        )
        checked = andromeda_verifier.validate_verifier_output(
            raw, "latest sqlite release", self._answer(), self._evidence()
        )
        self.assertEqual(checked["counts"]["insufficient"], 1)
        self.assertEqual(checked["rejected_verdicts"], 1)

    def test_api_creates_and_cancels_a_local_background_job(self):
        endpoint_id = self._endpoint()
        save_settings(
            {
                "model_roles": {
                    "aide_chat": {},
                    "andromeda_answer": {},
                    "andromeda_verifier": {
                        "endpoint_id": endpoint_id,
                        "model": "verify-small",
                    },
                    "jarvis": {},
                },
                "andromeda_verification_enabled": True,
                "andromeda_verifier_mode": "always",
            }
        )
        with mock.patch("services.andromeda_verifier.launch") as launch:
            response = self.client.post(
                "/api/andromeda/verification",
                json={"query": "latest sqlite release", "answer": self._answer(), "results": []},
            )
        self.assertEqual(response.status_code, 200)
        job = response.json()
        self.assertEqual(job["status"], "pending")
        launch.assert_called_once_with(job["id"])
        cancelled = self.client.post(f"/api/andromeda/verification/{job['id']}/cancel")
        self.assertEqual(cancelled.json()["status"], "cancelled")

    def test_remote_verifier_needs_its_own_exact_confirmation(self):
        endpoint_id = self._endpoint("https://models.example.test/v1")
        save_settings(
            {
                "model_roles": {
                    "aide_chat": {},
                    "andromeda_answer": {},
                    "andromeda_verifier": {
                        "endpoint_id": endpoint_id,
                        "model": "verify-small",
                    },
                    "jarvis": {},
                },
                "andromeda_verification_enabled": True,
                "andromeda_verifier_mode": "always",
            }
        )
        refused = self.client.post(
            "/api/andromeda/verification",
            json={"query": "latest sqlite release", "answer": self._answer(), "results": []},
        )
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["code"], "remote_verifier_confirmation_required")
        preview = self.client.post(
            "/api/andromeda/verification/preview",
            json={"query": "latest sqlite release"},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["status"], "ready")
        self.assertEqual(preview.json()["model"]["privacy_class"], "remote")

    def test_restart_marks_unfinished_jobs_honestly_interrupted(self):
        db = self.db()
        db.add(
            AndromedaVerificationJob(
                query="latest sqlite release",
                answer_json=json.dumps(self._answer()),
                status="running",
            )
        )
        db.commit()
        db.close()
        self.assertEqual(andromeda_verifier.recover_interrupted(), 1)
        db = self.db()
        job = db.query(AndromedaVerificationJob).one()
        self.assertEqual((job.status, job.error_code), ("interrupted", "server_restarted"))
        db.close()
