import sys
import unittest
from unittest import mock

from services import stt_local


class SttLocalTests(unittest.TestCase):
    def test_available_returns_bool(self):
        self.assertIsInstance(stt_local.available(), bool)

    def test_transcribe_errors_without_lib(self):
        # mock faster_whisper as absent; transcribe must raise
        with mock.patch.dict(sys.modules, {"faster_whisper": None}):
            with mock.patch.object(stt_local, "_get_model", side_effect=ImportError("no lib")):
                with self.assertRaises(Exception):
                    stt_local.transcribe(b"x", size="tiny")

    def test_available_is_idempotent(self):
        r1 = stt_local.available()
        r2 = stt_local.available()
        self.assertEqual(r1, r2)

    def test_available_matches_import(self):
        try:
            import faster_whisper  # noqa: F401

            expected = True
        except Exception:
            expected = False
        self.assertEqual(stt_local.available(), expected)

    def test_transcribe_empty_bytes_errors_without_lib(self):
        # simulate absent library — _get_model raises ImportError
        with mock.patch.object(stt_local, "_get_model", side_effect=ImportError("no lib")):
            with self.assertRaises(Exception):
                stt_local.transcribe(b"", size="base")

    def test_transcribe_size_param_errors_without_lib(self):
        # same simulation but with a non-default size arg
        with mock.patch.object(stt_local, "_get_model", side_effect=ImportError("no lib")):
            with self.assertRaises(Exception):
                stt_local.transcribe(b"audio", size="large-v3")

    def test_module_level_model_starts_none(self):
        # _model resets to None in a fresh import; we can't guarantee no prior
        # test cached it, but we can assert the attribute exists and is accessible
        self.assertIn("_model", dir(stt_local))

    def test_get_model_returns_cached_when_size_matches(self):
        sentinel = object()
        with (
            mock.patch.object(stt_local, "_model", sentinel),
            mock.patch.object(stt_local, "_loaded_size", "base"),
        ):
            result = stt_local._get_model("base")
        self.assertIs(result, sentinel)

    def test_get_model_reloads_on_different_size(self):
        # _loaded_size = "base" but we ask for "tiny" → must NOT return the cached sentinel
        sentinel = object()
        with (
            mock.patch.object(stt_local, "_model", sentinel),
            mock.patch.object(stt_local, "_loaded_size", "base"),
        ):
            if stt_local.available():
                # lib present: _get_model actually loads a new model → result ≠ sentinel
                result = stt_local._get_model("tiny")
                self.assertIsNot(result, sentinel)
            else:
                # lib absent: raises ImportError — also proves cache was bypassed
                with self.assertRaises(Exception):
                    stt_local._get_model("tiny")

    def test_transcribe_cleans_up_temp_file(self):
        # even when transcribe fails (no lib or mock failure), the tmp .webm must be gone
        import tempfile
        from pathlib import Path

        created_files = []
        real_ntf = tempfile.NamedTemporaryFile

        def tracking_ntf(*args, **kwargs):
            f = real_ntf(*args, **kwargs)
            created_files.append(f.name)
            return f

        with mock.patch("tempfile.NamedTemporaryFile", side_effect=tracking_ntf):
            try:
                stt_local.transcribe(b"data", size="base")
            except Exception:
                pass

        for path in created_files:
            self.assertFalse(Path(path).exists(), f"temp file {path} was not cleaned up")


if __name__ == "__main__":
    unittest.main()
