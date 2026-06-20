"""ui-2e — voice waveform redesigned toward Apple Voice Memos: centered rounded bars + live
MM:SS timer + recording red. Source-contract level; the live render is in pw_voice_2e.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOICE = (ROOT / "static" / "js" / "voice.js").read_text(encoding="utf-8")


class VoiceWaveTests(unittest.TestCase):
    def test_uses_rounded_bars(self):
        self.assertIn("function _roundBar", VOICE)
        self.assertIn("arcTo", VOICE)

    def test_recording_red(self):
        self.assertIn("#ff453a", VOICE)

    def test_live_timer(self):
        self.assertIn("_recStart", VOICE)
        self.assertIn("fillText", VOICE)
        self.assertIn("withTimer", VOICE)

    def test_timer_is_mm_ss(self):
        self.assertIn("padStart(2", VOICE)

    def test_mic_call_enables_timer(self):
        self.assertIn("_runDotWave(document.getElementById('mic-wave'), _micAmp, true)", VOICE)

    def test_recstart_set_on_record(self):
        self.assertIn("_recStart = ", VOICE)

    def test_bars_mirror_around_centre(self):
        # bar is drawn centred: cy - h/2
        self.assertIn("cy - h / 2", VOICE)

    def test_scrolls_left_newest_right(self):
        self.assertIn("W - 4 - n * step", VOICE)


if __name__ == "__main__":
    unittest.main()
