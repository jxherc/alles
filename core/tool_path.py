"""systemd and launchd start alles with a bare PATH (/usr/bin:/bin...), so node from nvm, homebrew
or ~/.local/bin is invisible and pi, photon and harness installs fail with "node not found". this
adds the usual tool folders that exist, the way a login shell would, every time alles starts, so a
node installed after alles is found too."""

import os
import re
from pathlib import Path


def _version_key(name: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", name)[:3])


def _nvm_bin(home: Path) -> Path | None:
    versions = home / ".nvm" / "versions" / "node"
    try:
        installed = [entry for entry in versions.iterdir() if (entry / "bin" / "node").exists()]
    except OSError:
        return None
    if not installed:
        return None
    try:
        wanted = (home / ".nvm" / "alias" / "default").read_text("utf-8").strip().lstrip("v")
    except OSError:
        wanted = ""
    # "24" or "24.22.1" pick that line; "node" or "lts/*" fall back to the newest install
    chosen = [
        entry
        for entry in installed
        if wanted
        and (entry.name.lstrip("v") == wanted or entry.name.lstrip("v").startswith(wanted + "."))
    ]
    return max(chosen or installed, key=lambda entry: _version_key(entry.name)) / "bin"


def tool_dirs(home: Path) -> tuple[list[Path], list[Path]]:
    """per-user folders go first (the user picked them), system folders last."""
    user = [
        _nvm_bin(home),
        home / ".volta" / "bin",
        home / ".bun" / "bin",
        home / ".local" / "share" / "fnm" / "aliases" / "default" / "bin",
        home / "Library" / "Application Support" / "fnm" / "aliases" / "default" / "bin",
        home / ".local" / "share" / "mise" / "shims",
        home / ".asdf" / "shims",
        home / ".npm-global" / "bin",
        home / ".local" / "bin",
        home / ".cargo" / "bin",
    ]
    system = [
        Path("/opt/homebrew/bin"),
        Path("/opt/homebrew/sbin"),
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/bin"),
        Path("/usr/sbin"),
        Path("/sbin"),
    ]
    return [entry for entry in user if entry is not None], system


def extend_tool_path(environ=os.environ, home: Path | None = None) -> str:
    home = home or Path(environ.get("HOME") or Path.home())
    current = [entry for entry in environ.get("PATH", "").split(os.pathsep) if entry]
    user, system = tool_dirs(home)
    seen = set(current)
    front = [str(entry) for entry in user if str(entry) not in seen and entry.is_dir()]
    seen.update(front)
    back = [str(entry) for entry in system if str(entry) not in seen and entry.is_dir()]
    environ["PATH"] = os.pathsep.join(front + current + back)
    return environ["PATH"]


def find_tool(name: str) -> str | None:
    """shutil.which after a fresh look at the tool folders, so a node installed while alles runs
    is found on the next check"""
    import shutil

    extend_tool_path()
    return shutil.which(name)
