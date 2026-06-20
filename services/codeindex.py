"""semantic codebase index (10a) — reuses the 1c text index with kind="code".

Walks a repo, indexes source files as kind="code" in services/textindex, and exposes a
meaning-based search the agent (and the UI) can hit. No new deps: textindex already does the
fastembed-or-jaccard scoring.
"""

import os
from pathlib import Path

from services import textindex

CODE_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".mjs",
    ".css",
    ".html",
    ".json",
    ".sh",
    ".sql",
    ".toml",
    ".yaml",
    ".yml",
    ".rs",
    ".go",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".rb",
    ".php",
    ".lua",
    ".vue",
    ".svelte",
    ".md",
}
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    "data",
    ".venv",
    "venv",
    ".tmp",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".next",
    "vendor",
}
MAX_BYTES = 256 * 1024


def iter_code_files(root):
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        # prune skipped + dot dirs in place so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() not in CODE_EXTS:
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield p


def _rel(root, p):
    return str(Path(p).relative_to(root)).replace("\\", "/")


def reindex(db, root) -> int:
    """wipe + rebuild the code index from a repo root. returns chunk count."""
    root = Path(root)
    items = []
    for p in iter_code_files(root):
        try:
            items.append((_rel(root, p), p.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return textindex.reindex_kind(db, "code", items)


def search(db, query, k: int = 8) -> list[dict]:
    return textindex.search(db, query, "code", k)


def stats(db) -> int:
    return textindex.stats(db).get("code", 0)
