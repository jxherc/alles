"""guard against the SVG-as-text footgun: window.icon()/_si() return an SVG *string*, so they must be
assigned via innerHTML, never textContent. (The journal streak line shipped the raw <svg> markup as
visible text because it used .textContent — caught only by looking at it.)"""

import re
import unittest
from pathlib import Path

JS_DIR = Path(__file__).resolve().parent.parent / "static" / "js"


class NoIconInTextContent(unittest.TestCase):
    def test_no_textcontent_assignment_takes_an_icon(self):
        offenders = []
        # match `.textContent = <expr>` up to the line end / semicolon, flag if it calls an icon helper
        pat = re.compile(r"\.textContent\s*=\s*([^;\n]*)")
        for f in JS_DIR.glob("*.js"):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                for m in pat.finditer(line):
                    rhs = m.group(1)
                    if "_si(" in rhs or "window.icon(" in rhs or "iconEl(" in rhs:
                        offenders.append(f"{f.name}:{i}: {line.strip()}")
        self.assertFalse(
            offenders,
            "icon helpers return SVG strings — use innerHTML, not textContent:\n"
            + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
