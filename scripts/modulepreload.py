"""keep index.html's modulepreload list in step with app.js's static import graph.

without it the browser finds each module only after its parent arrives, so startup is a dozen
round trips deep. with every static import listed up front, it asks for them all at once.

    python scripts/modulepreload.py          # rewrite the list in static/index.html
    python scripts/modulepreload.py --check  # exit 1 when the list is stale
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
INDEX = STATIC / "index.html"
START, END = "<!-- modulepreload:start -->", "<!-- modulepreload:end -->"
# static imports only; import() stays lazy on purpose
IMPORT = re.compile(
    r"""^\s*(?:import|export)\s[^'"`;]*?from\s*['"]([^'"]+)['"]|^\s*import\s*['"]([^'"]+)['"]""",
    re.M,
)


def entry() -> str:
    """the app.js url index.html imports, with its ?v= stamp."""
    found = re.search(
        r'<script type="module" src="/static/js/app\.js\?v=([^"]+)"', INDEX.read_text()
    )
    return f"/static/js/app.js?v={found.group(1)}"


def graph(start: str) -> list[str]:
    seen, order, todo = set(), [], [start]
    while todo:
        url = todo.pop(0)
        if url in seen:
            continue
        seen.add(url)
        order.append(url)
        path = STATIC / urlsplit(url).path.removeprefix("/static/")
        if not path.is_file():
            continue
        base = urlsplit(url).path.rsplit("/", 1)[0]
        for a, b in IMPORT.findall(path.read_text()):
            spec = a or b
            if not spec.startswith((".", "/")):
                continue
            joined = spec if spec.startswith("/") else _join(base, spec)
            todo.append(joined)
    return order


def _join(base: str, spec: str) -> str:
    parts = base.split("/")
    path, _, query = spec.partition("?")
    for piece in path.split("/"):
        if piece == "..":
            parts.pop()
        elif piece and piece != ".":
            parts.append(piece)
    return "/".join(parts) + (f"?{query}" if query else "")


def block() -> str:
    urls = graph(entry())
    lines = "\n".join(f'<link rel="modulepreload" href="{u}">' for u in urls)
    return f"{START}\n{lines}\n{END}"


def main() -> int:
    html = INDEX.read_text()
    fresh = block()
    current = re.search(re.escape(START) + r".*?" + re.escape(END), html, re.S)
    if "--check" in sys.argv:
        if not current or current.group(0) != fresh:
            print(
                "static/index.html modulepreload list is stale; run python scripts/modulepreload.py"
            )
            return 1
        return 0
    if current:
        html = html.replace(current.group(0), fresh)
    else:
        html = html.replace("</head>", f"{fresh}\n</head>", 1)
    INDEX.write_text(html)
    print(f"{fresh.count('modulepreload') - 2} modules listed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
