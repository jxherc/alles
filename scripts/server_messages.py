"""keep the english messages the server can send to a screen in step with the code.

screens show these as they arrive (error details, refusals), so each language gets a file that
maps the english text to its own. f-string messages become templates: f"no note {name}" is
"no note {name}", and the screen fills the value back in.

    python scripts/server_messages.py          # rewrite static/locales/server/en.json
    python scripts/server_messages.py --check  # exit 1 when the list or a translation is stale
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "locales" / "server"
SOURCES = ("app.py", "routes", "services", "core")
LANGUAGES = ("fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar")
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


# a migration's refusals and a programming slip never reach a screen
SKIP_DIRS = ("core/migrations",)
SKIP_ERRORS = {"AssertionError", "NotImplementedError", "SystemExit"}
SHOWN_FIELDS = {"detail", "error", "message", "reason"}


def _files():
    for source in SOURCES:
        path = ROOT / source
        for file in [path] if path.is_file() else sorted(path.rglob("*.py")):
            if not file.relative_to(ROOT).as_posix().startswith(SKIP_DIRS):
                yield file


def _slot(node: ast.AST) -> str:
    # the placeholder is named after what fills it: f"{note.title}" -> {title}
    while isinstance(node, (ast.Call, ast.Subscript)):
        node = node.func if isinstance(node, ast.Call) else node.value
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            break
    if isinstance(node, ast.Attribute):
        name = node.attr if not isinstance(node.value, ast.Name) else node.value.id
        if node.attr not in {"replace", "strip", "lower", "upper", "join", "get", "format"}:
            name = node.attr
    elif isinstance(node, ast.Name):
        name = node.id
    else:
        name = "value"
    name = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_") or "value"
    return name if name[0].isalpha() else f"v_{name}"


def _template(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.JoinedStr):
        return None
    parts, used = [], {}
    for value in node.values:
        if isinstance(value, ast.Constant):
            parts.append(str(value.value))
            continue
        name = _slot(value.value)
        used[name] = used.get(name, 0) + 1
        parts.append("{" + (name if used[name] == 1 else f"{name}_{used[name]}") + "}")
    return "".join(parts)


def _shown(text: str) -> bool:
    # a sentence a person reads, not a code like "recent_auth_required" or a path
    words = PLACEHOLDER.sub("", text)
    return (
        " " in text.strip()
        and re.search(r"[a-z]{2}", words) is not None
        and not text.lstrip().startswith(("/", "http", "{"))
        and len(text) <= 400
    )


def extract() -> list[str]:
    found = set()
    for path in _files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                # a json body's own words: {"detail": ...}, {"error": ...}, a status "reason"
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in SHOWN_FIELDS:
                        text = _template(value)
                        if text and _shown(text):
                            found.add(text)
                continue
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if name == "HTTPException":
                args = node.args[1:2] + [k.value for k in node.keywords if k.arg == "detail"]
            elif (
                name.endswith(("Error", "Exception"))
                and name[:1].isupper()
                and name not in SKIP_ERRORS
            ):
                # (code, message) errors carry the words second; a code alone never reads as a sentence
                args = node.args + [
                    k.value for k in node.keywords if k.arg in {"message", "detail"}
                ]
            else:
                continue
            for arg in args:
                text = _template(arg)
                if text and _shown(text):
                    found.add(text)
    return sorted(found)


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(messages: list[str]) -> list[str]:
    problems = []
    current = json.loads((OUT / "en.json").read_text(encoding="utf-8"))["messages"]
    if current != messages:
        problems.append(
            "static/locales/server/en.json is stale; run python scripts/server_messages.py"
        )
    for language in LANGUAGES:
        path = OUT / f"{language}.json"
        if not path.is_file():
            problems.append(f"{path.name} is missing")
            continue
        table = json.loads(path.read_text(encoding="utf-8"))["messages"]
        missing = [m for m in messages if not str(table.get(m, "")).strip()]
        extra = [m for m in table if m not in set(messages)]
        slots = [
            m
            for m in messages
            if m in table
            and sorted(PLACEHOLDER.findall(m)) != sorted(PLACEHOLDER.findall(table[m]))
        ]
        for label, items in (
            ("untranslated", missing),
            ("no longer sent", extra),
            ("placeholders differ", slots),
        ):
            if items:
                problems.append(f"{path.name}: {len(items)} {label}, e.g. {items[0]!r}")
    return problems


def main() -> int:
    messages = extract()
    if "--check" in sys.argv:
        problems = check(messages)
        print("\n".join(problems) or f"{len(messages)} server messages, all translated")
        return 1 if problems else 0
    OUT.mkdir(parents=True, exist_ok=True)
    _write(OUT / "en.json", {"schema_version": 1, "language": "en", "messages": messages})
    print(f"{len(messages)} server messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
