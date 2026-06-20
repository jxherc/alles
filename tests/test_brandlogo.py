"""ui-1f — per-provider glowing brand logos + dropdown integration. Runtime behavior via node;
wiring via source scan."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DROP = (ROOT / "static" / "js" / "dropdown.js").read_text(encoding="utf-8")
APP = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def _node(expr):
    node = shutil.which("node")
    assert node, "node required"
    code = (
        "import {providerKey, providerLogo, brandColor, BRAND_PROVIDERS} from './static/js/brandlogo.js';"
        f"process.stdout.write(JSON.stringify((()=>{{{expr}}})()));"
    )
    out = subprocess.run(
        [node, "--input-type=module", "-e", code], cwd=str(ROOT), capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


class BrandLogoTests(unittest.TestCase):
    def test_provider_key_known(self):
        self.assertEqual(_node("return providerKey('deepseek');"), "deepseek")
        self.assertEqual(_node("return providerKey('claude-opus-4');"), "anthropic")
        self.assertEqual(_node("return providerKey('gpt-4o');"), "openai")

    def test_provider_key_unknown_defaults(self):
        self.assertEqual(_node("return providerKey('totally-unknown');"), "_default")

    def test_openai_compatible_endpoints_detected_by_name_url(self):
        # moonshot/groq etc. report provider 'openai' — must still get their own mark
        self.assertEqual(
            _node("return providerKey('openai Moonshot https://api.moonshot.cn moonshot-v1-8k');"),
            "moonshot",
        )
        self.assertEqual(
            _node("return providerKey('openai Groq https://api.groq.com/openai llama-3.1-70b');"),
            "groq",
        )
        self.assertEqual(
            _node("return providerKey('openai OpenAI https://api.openai.com gpt-4o');"), "openai"
        )

    def test_every_provider_has_a_real_logo_not_spark(self):
        # no provider (besides _default) should fall back to the spark glyph
        spark = "M12 2l2.4 7.1L22 12"
        n = _node(
            "return BRAND_PROVIDERS.filter(p => providerLogo(p).includes('%s')).length;" % spark
        )
        self.assertEqual(n, 0, "some providers still use the spark fallback")

    def test_logo_is_glowing_svg(self):
        out = _node("return providerLogo('deepseek');")
        self.assertIn("<svg", out)
        self.assertIn("brandlogo-glow", out)

    def test_logo_carries_brand_color(self):
        out = _node("return providerLogo('deepseek');")
        self.assertIn(_node("return brandColor('deepseek');"), out)

    def test_glow_can_be_disabled(self):
        out = _node("return providerLogo('openai', {glow:false});")
        self.assertNotIn("brandlogo-glow", out)

    def test_enough_providers(self):
        self.assertGreaterEqual(_node("return BRAND_PROVIDERS.length;"), 10)

    def test_dropdown_supports_per_option_icon(self):
        self.assertIn("import { providerLogo } from './brandlogo.js'", DROP)
        self.assertIn("el._iconHtml", DROP)
        self.assertIn("_iconFor(el, opt.value)", DROP)

    def test_home_selector_passes_provider_icon(self):
        self.assertIn("icon: providerKey(", APP)

    def test_brandlogo_css_present(self):
        self.assertIn(".brandlogo-glow", CSS)


if __name__ == "__main__":
    unittest.main()
