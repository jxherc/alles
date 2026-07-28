"""Small, argument-safe Git helpers for Project branch context."""

import subprocess
from pathlib import Path


class ProjectGitError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _git(root: str, *args: str, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    command = ["git", "-C", str(Path(root)), *args]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(
            command,
            124,
            stdout="",
            stderr="Git could not complete safely within the local timeout",
        )


def branch_state(root: str) -> dict:
    try:
        inside = _git(root, "rev-parse", "--is-inside-work-tree")
    except (OSError, subprocess.SubprocessError):
        inside = None
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        return {"repository": False, "current": "", "branches": [], "dirty": False}

    current_result = _git(root, "branch", "--show-current")
    current = current_result.stdout.strip() if current_result.returncode == 0 else ""
    branches_result = _git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    branches = (
        sorted(
            {line.strip() for line in branches_result.stdout.splitlines() if line.strip()},
            key=str.casefold,
        )
        if branches_result.returncode == 0
        else []
    )
    if current in branches:
        branches.remove(current)
        branches.insert(0, current)
    dirty_result = _git(root, "status", "--porcelain", "--untracked-files=normal")
    dirty = dirty_result.returncode == 0 and bool(dirty_result.stdout.strip())
    return {"repository": True, "current": current, "branches": branches, "dirty": dirty}


def switch_branch(root: str, branch: str) -> dict:
    state = branch_state(root)
    if not state["repository"]:
        raise ProjectGitError("project_not_git", "this Project folder is not a Git repository")
    if branch not in state["branches"]:
        raise ProjectGitError("project_git_branch_missing", "that local Git branch is unavailable")
    if branch == state["current"]:
        return state
    result = _git(root, "switch", "--no-guess", "--", branch, timeout=120)
    if result.returncode != 0:
        reconciled = branch_state(root)
        if reconciled.get("current") == branch:
            return reconciled
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[-1] if detail else "Git could not switch branches"
        raise ProjectGitError("project_git_switch_failed", message)
    return branch_state(root)
