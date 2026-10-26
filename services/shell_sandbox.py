"""write confinement for the agent's shell commands.

macOS runs a command under sandbox-exec, linux under bubblewrap (bwrap). either way it can write
only inside the folders it's given and a private temp folder for its run, and it can't reach the
ports it's told to keep closed (alles's own). reads stay as they are. kind() is "" when this
machine can't confine a command; the caller decides what that means (refuse it, or ask the owner
with the command shown as unconfined).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_works: dict[str, bool] = {}  # the confining tool's path -> it really confined a probe
_scratch: dict[str, str] = {}  # agent run id -> that run's private temp folder
# a fresh /proc first. a vm or container that hides part of its own /proc refuses one, so then
# the real one, read-only: other processes show up there, but the sandbox's own pid space
# still can't signal or trace them
_PROC_FORMS = (["--proc", "/proc"], ["--ro-bind", "/proc", "/proc"])
_proc: dict[str, list[str]] = {}  # bwrap's path -> the /proc form its probe confined with
_lock = threading.Lock()


def _tool() -> tuple[str, str]:
    if sys.platform == "darwin":
        return "sandbox-exec", SANDBOX_EXEC if os.access(SANDBOX_EXEC, os.X_OK) else ""
    if sys.platform.startswith("linux"):
        return "bwrap", shutil.which("bwrap") or ""
    return "", ""


def kind() -> str:
    """'sandbox-exec', 'bwrap', or '' when this machine can't confine a command."""
    name, tool = _tool()
    if not tool:
        return ""
    with _lock:
        known = _works.get(tool)
    if known is None:
        # once per install: looked up again only when the tool's path changes
        known = _probe(name, tool)
        with _lock:
            _works[tool] = known
    return name if known else ""


def missing_hint() -> str:
    if sys.platform.startswith("linux"):
        return "shell needs a sandbox here: install bubblewrap, or switch to approve mode"
    return "shell needs a sandbox here and this machine has none: switch to approve mode"


def _probe(name: str, tool: str) -> bool:
    # a real try, not just "is it installed": a write inside lands and one beside it doesn't
    if name != "bwrap":
        return _try(name, tool)
    for form in _PROC_FORMS:
        _proc[tool] = form
        if _try(name, tool):
            return True
    _proc.pop(tool, None)
    return False


def _try(name: str, tool: str) -> bool:
    base = Path(tempfile.mkdtemp(prefix="alles-sandbox-probe-")).resolve()
    try:
        inside, beside, tmp = base / "inside", base / "beside", base / "tmp"
        for folder in (inside, beside, tmp):
            folder.mkdir()
        # the strictest form there is, so every flag a real command may get is known to work
        argv, env = _argv(
            name,
            tool,
            ["/bin/sh", "-c", ": > ok; : > ../beside/no"],
            inside,
            [inside],
            tmp,
            closed_ports=(1,),
            offline=True,
        )
        subprocess.run(
            argv,
            cwd=inside,
            env={**os.environ, **env},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        return (inside / "ok").exists() and not (beside / "no").exists()
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(base, ignore_errors=True)


def scratch(run_id: str) -> Path:
    """the run's private temp folder; its commands share it, so a file made in one is there for the next."""
    with _lock:
        path = _scratch.get(run_id)
        if not path or not os.path.isdir(path):
            path = _scratch[run_id] = tempfile.mkdtemp(prefix="alles-shell-")
    return Path(path).resolve()


def drop_scratch(run_id: str) -> None:
    with _lock:
        path = _scratch.pop(run_id, None)
    if path:
        shutil.rmtree(path, ignore_errors=True)


def wrap(
    command: str, workdir, writable, run_id: str = "", *, closed_ports=(), offline: bool = False
) -> tuple[list[str], dict, str]:
    """argv and env overrides that run `command` confined, plus a temp folder to remove once it
    ends ('' when the folder belongs to the run). raises RuntimeError when nothing can confine it.

    closed_ports: local ports the command can't connect to (macOS). offline: no network at all,
    for where a port can't be closed on its own (linux)."""
    name, tool = _tool()
    if not tool or not kind():
        raise RuntimeError(missing_hint())
    once = "" if run_id else tempfile.mkdtemp(prefix="alles-shell-")
    tmp = Path(once).resolve() if once else scratch(run_id)
    roots = []
    for raw in writable:
        try:
            root = Path(raw).resolve()
        except (OSError, RuntimeError):
            continue
        if root.is_dir() and root != Path(root.anchor) and root not in roots:
            roots.append(root)
    argv, env = _argv(
        name,
        tool,
        ["bash", "-lc", command],
        Path(workdir),
        roots,
        tmp,
        closed_ports=closed_ports,
        offline=offline,
    )
    return argv, env, once


def _sb_string(path) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _profile(writable, tmp, closed_ports=()) -> str:
    places = [*writable, tmp]
    write = " ".join(f"(subpath {_sb_string(p)})" for p in places)
    sockets = " ".join(f"(remote unix-socket (subpath {_sb_string(p)}))" for p in places)
    # "localhost" covers 127.0.0.1, ::1 and this machine's own lan address; the profile language
    # takes no other host than it or "*"
    closed = [
        f'(deny network-outbound (remote ip "localhost:{int(port)}"))' for port in closed_ports
    ]
    return "\n".join(
        [
            "(version 1)",
            "(allow default)",
            "(deny file-write*)",
            f'(allow file-write* {write} (literal "/dev/null") (literal "/dev/zero")'
            ' (literal "/dev/dtracehelper") (regex #"^/dev/fd/"))',
            # another program would do the writing for it: apps opened or scripted through
            # launch services and apple events, the spotlight and file coordination daemons,
            # docker's daemon or a launcher through their sockets. none of git, python, pip, node,
            # npm or curl needs them; dns and logging keep their sockets
            "(deny appleevent-send)",
            '(deny mach-lookup (global-name-prefix "com.apple.coreservices.")'
            ' (global-name-prefix "com.apple.CoreServices.") (global-name-prefix "com.apple.lsd.")'
            ' (global-name-prefix "com.apple.metadata.") (global-name "com.apple.FileCoordination"))',
            "(deny network-outbound (remote unix-socket))",
            f"(allow network-outbound {sockets}"
            ' (remote unix-socket (path-literal "/private/var/run/mDNSResponder"))'
            ' (remote unix-socket (path-literal "/private/var/run/syslog")))',
            *closed,
            # its own children yes, alles or anything else of the owner's no
            "(deny signal (target others))",
        ]
    )


def _hidden() -> list[str]:
    # the session bus, the user's systemd and rootless docker live in the runtime folder, and the
    # docker socket starts containers that can mount anything: none of them are the task's
    args = []
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if os.path.isdir(runtime):
        args += ["--tmpfs", os.path.realpath(runtime)]
    seen = set()
    for sock in ("/run/docker.sock", "/var/run/docker.sock", "/run/podman/podman.sock"):
        real = os.path.realpath(sock)
        if real not in seen and os.path.exists(real) and not os.path.isdir(real):
            seen.add(real)
            args += ["--ro-bind", "/dev/null", real]
    return args


def _argv(
    name, tool, shell, workdir, writable, tmp, closed_ports=(), offline=False
) -> tuple[list[str], dict]:
    if name == "sandbox-exec":
        env = {
            "TMPDIR": f"{tmp}/",
            "XDG_CACHE_HOME": f"{tmp}/cache",
            "npm_config_cache": f"{tmp}/npm",
        }
        return [tool, "-p", _profile(writable, tmp, closed_ports), *shell], env
    # its own processes only (alles and the rest can't be seen, traced or signalled), its own
    # ipc and host name. a port can't be closed on its own here, so offline is no network at all
    args = [tool, "--die-with-parent", "--new-session"]
    args += [
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        *(["--unshare-net"] if offline else []),
    ]
    args += ["--ro-bind", "/", "/", "--dev", "/dev", *_proc.get(tool, _PROC_FORMS[0])]
    # the run's temp folder is the sandbox's /tmp, so nothing else in the real /tmp is reachable
    args += ["--bind", str(tmp), "/tmp", *_hidden()]
    for root in writable:
        args += ["--bind", str(root), str(root)]
    args += ["--chdir", str(workdir), "--", *shell]
    env = {"TMPDIR": "/tmp", "XDG_CACHE_HOME": "/tmp/cache", "npm_config_cache": "/tmp/npm"}
    return args, env
