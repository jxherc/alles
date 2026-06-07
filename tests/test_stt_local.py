import unittest

from services import stt_local


class SttLocalTests(unittest.TestCase):
    def test_available_returns_bool(self):
        self.assertIsInstance(stt_local.available(), bool)

    def test_transcribe_errors_without_lib(self):
        # if faster-whisper isn't installed, transcribe should raise (route turns
        # that into a clear "pip install" message) rather than silently passing.
        if stt_local.available():
            self.skipTest("faster-whisper installed; nothing to assert here")
        with self.assertRaises(Exception):
            stt_local.transcribe(b"x", size="tiny")


if __name__ == "__main__":
    unittest.main()
