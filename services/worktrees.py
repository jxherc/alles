"""per-run git worktree isolation (10a).

When `agent_worktree` is on, an agent run gets its own detached worktree off HEAD so parallel
runs don't stomp each other's edits. The runtime repoints `agent_cwd` at it; teardown removes it.
"""

import subprocess
import tempfile
from pathlib import Path


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30
    )


def is_git_repo(path) -> bool:
    p = Path(path or ".")
    if not p.exists():
        return False
    try:
        r = _git(p, "rev-parse", "--is-inside-work-tree")
    except Exception:
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def _wt_dir(run_id) -> Path:
    return Path(tempfile.gettempdir()) / "alles-worktrees" / f"run-{run_id}"


def setup(root, run_id) -> str | None:
    """create a detached worktree off HEAD. returns its path, or None if not a git repo / failed."""
    if not is_git_repo(root):
        return None
    wt = _wt_dir(run_id)
    if wt.exists():
        return str(wt)
    wt.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = _git(root, "worktree", "add", "--detach", str(wt), "HEAD")
    except Exception:
        return None
    return str(wt) if r.returncode == 0 else None


def teardown(root, path) -> bool:
    if not path:
        return False
    try:
        r = _git(root, "worktree", "remove", "--force", str(path))
    except Exception:
        return False
    return r.returncode == 0
