"""Concurrent edits must not erase unrelated saved signatures."""

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import core.settings
from routes.mail import SignatureBody, delete_signature, list_signatures, save_signature
from tests._client import ApiTest


class SignatureConcurrency(ApiTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="alles-signatures-")
        self.settings = mock.patch.object(
            core.settings, "_SETTINGS_FILE", Path(self.temp.name) / "settings.json"
        )
        self.settings.start()

    def tearDown(self):
        self.settings.stop()
        self.temp.cleanup()
        super().tearDown()

    def overlap(self, first, second):
        original = core.settings.load_settings
        read = threading.Event()
        release = threading.Event()
        second_done = threading.Event()
        owner = {"thread": None, "paused": False}

        def load():
            value = original()
            if threading.get_ident() == owner["thread"] and not owner["paused"]:
                owner["paused"] = True
                read.set()
                assert release.wait(5)
            return value

        def run_first():
            owner["thread"] = threading.get_ident()
            return first()

        def run_second():
            try:
                return second()
            finally:
                second_done.set()

        with mock.patch.object(core.settings, "load_settings", side_effect=load):
            with ThreadPoolExecutor(max_workers=2) as pool:
                one = pool.submit(run_first)
                assert read.wait(5)
                two = pool.submit(run_second)
                second_done.wait(0.25)
                release.set()
                one.result(5)
                two.result(5)

    def test_two_new_signatures_are_both_preserved(self):
        self.overlap(
            lambda: save_signature(SignatureBody(id="first", name="first", body="one")),
            lambda: save_signature(SignatureBody(id="second", name="second", body="two")),
        )
        self.assertEqual({s["id"] for s in list_signatures()["signatures"]}, {"first", "second"})

    def test_delete_preserves_another_signature_saved_concurrently(self):
        save_signature(SignatureBody(id="old", name="old", body="old"))
        self.overlap(
            lambda: delete_signature("old"),
            lambda: save_signature(SignatureBody(id="new", name="new", body="new")),
        )
        self.assertEqual({s["id"] for s in list_signatures()["signatures"]}, {"new"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
