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

    def test_recording_can_be_cancelled_without_transcription(self):
        self.assertIn("export function cancelRecording()", VOICE)
        self.assertIn("_sr?.abort()", VOICE)
        self.assertIn("take !== _take", VOICE)

    def test_each_recording_gets_a_new_take_id(self):
        self.assertIn("const take = ++_take", VOICE)

    def test_permission_prompt_cannot_start_two_recordings(self):
        self.assertIn("let _starting = false", VOICE)
        self.assertIn("if (_recording || _starting || _settling) return", VOICE)

    def test_stopped_take_settles_before_another_recording_can_start(self):
        self.assertIn("let _settling = false", VOICE)
        self.assertIn("_settling = Boolean(_recorder)", VOICE)
        self.assertIn("_settling = Boolean(_sr)", VOICE)
        self.assertIn("_settling = false", VOICE)
        self.assertIn("_recording || _starting || _settling", VOICE)


if __name__ == "__main__":
    unittest.main()
