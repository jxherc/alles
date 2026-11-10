"""
alles CLI

  alles                status, address and the everyday commands
  alles install        install alles as a background service (macos/linux)
  alles access lan     let your phone and other computers open it (asks for a password)
  alles access device  only this computer can open it again
  alles access domain  open it at your own domain: alles.example.com/docs, or docs.alles.example.com
  alles password       set or change the owner password (optional for this computer only)
  alles config         edit the settings file  (alles config path prints where it is)
  alles start          start the server in the background
  alles stop           stop it
  alles restart        restart it (after changing settings)
  alles status         running or stopped, health, address and access
  alles ask "question" one answer from aide, right here
  alles chat           talk with aide until ctrl-d
  alles logs [N]       print the last N log lines (default 60)
  alles logs -f        follow the log live (ctrl-c to stop)
  alles logs --level warn --since 1h --grep text
                       only what matters: a level floor, a time window, a word
  alles logs boot      the newest startup check log, from a failed update or restore
  alles logs list      every log file and its size
  alles logs --clear   truncate the log file
  alles backup [-o file] [--photos]
                       an encrypted backup of everything (restore stage reads it)
  alles dump           a plain summary of this install for a bug report, no secrets
  alles update         get the newest release; it checks itself and keeps a rollback
  alles update accept  keep an update now (the next update does it for you)
  alles update rollback
                       restore the previous verified code and data
  alles folders        where docs, files and backups are
  alles folders move   put an older install's folders into one ~/Alles folder
  alles tools          what aide can use (node, pi, its browser, searxng) and if it's ready
  alles tools install [name|all]
                       install them (node comes with alles install)
  alles version        the release, by its short commit
  alles completion zsh|bash|fish
                       tab completion: eval "$(alles completion zsh)"
  alles open           open the browser
  alles doctor         check the install is ready (deps, folders, provider)
  alles restore apply <id> [--allow-partial]
                       verify, migrate, and atomically apply a staged backup
  alles restore stage <backup> [--key <recovery-key>]
                       stage an encrypted backup on a clean installation
  alles restore recover
                       put original data back after an interrupted restore
  alles restore rollback <operation-id>
                       roll back a completed restore while its snapshot exists
  alles install --launcher-only
                       only put `alles` on your PATH
  alles uninstall      remove alles again; your personal data stays

windows: alles.cmd   unix/git-bash: ./alles   or just: python app.py
"""

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # dotenv is a dep, but never let a missing

    def load_dotenv(*a, **k):
        return False  # import block the whole CLI


ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", encoding="utf-8-sig")


def _native_layout(*, files: bool = True):
    """Return the verified native layout only when its dispatcher selected this process.

    files=False is for commands that only read (status, logs, version): they skip hashing every
    release file, which made each of them take seconds."""
    try:
        from services.native_install import current_layout, verify_install
    except ImportError:
        if not (ROOT / "services" / "native_install.py").is_file():
            return None
        raise
    layout = current_layout()
    if layout is not None:
        verify_install(layout, files=files)
    return layout


def _runtime_dir() -> Path:
    return Path(os.environ.get("ALLES_DATA") or (ROOT / "data"))


PID_FILE = _runtime_dir() / "alles.pid"
LOG_FILE = _runtime_dir() / "alles-server.log"

IS_WIN = sys.platform == "win32"


def _port():
    try:
        return int(os.getenv("PORT", "6769"))
    except ValueError:
        return 6769


def _url():
    return f"http://localhost:{_port()}"


def _pid():
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def _running(pid):
    if pid is None:
        return False
    try:
        if IS_WIN:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"], stderr=subprocess.DEVNULL, text=True
            )
            return str(pid) in out
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _port_open(port: int | None = None):
    """is something accepting connections on our port? (server up, or an orphan)"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port if port is not None else _port())) == 0


def _alles_process(pid):
    """Return the tracked Alles process only when its command and working directory match."""
    if pid is None:
        return None
    try:
        import psutil

        proc = psutil.Process(pid)
        cwd = Path(proc.cwd()).resolve()
        expected_root = ROOT.resolve()
        expected_app = (expected_root / "app.py").resolve()
        if cwd != expected_root:
            return None
        for arg in proc.cmdline()[1:]:
            candidate = Path(arg)
            if candidate.name != "app.py":
                continue
            if not candidate.is_absolute():
                candidate = cwd / candidate
            if candidate.resolve() == expected_app:
                return proc
    except Exception:
        return None
    return None


def _tail(n=60):
    if not LOG_FILE.exists():
        return []
    return LOG_FILE.read_text(errors="replace").splitlines()[-n:]


def _deps_ok() -> bool:
    """app.py will run under THIS interpreter — make sure it has the deps,
    otherwise the server just crash-loops into the log file."""
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401

        return True
    except ImportError:
        return False


def _start_safety_allows(runtime: Path) -> bool:
    try:
        from services.restore_apply import maintenance_lock_path
        from services.update_safety import update_lock_path, update_start_allowed

        if maintenance_lock_path(runtime).exists():
            print("an offline restore is unfinished — start cancelled")
            print("recover the original data with:  alles restore recover")
            return False
        if update_lock_path(runtime).exists() and not update_start_allowed(
            runtime, os.environ.get("ALLES_UPDATE_TOKEN")
        ):
            print("a staged update is unfinished — start cancelled")
            print("restore the original version with:  alles update rollback")
            return False
    except Exception as exc:
        print(f"could not check restore state: {exc}")
        return False
    return True


def cmd_start(args=()):
    native = _native_layout()
    runtime = native.data_root if native is not None else _runtime_dir()
    if not _start_safety_allows(runtime):
        return False
    if native is not None:
        from services import service_manager

        if _native_refresh_service(native):
            print(f"alles start requested through {native.manager}")
            return True
        try:
            service_manager.control("server", "start")
        except (service_manager.ServiceControlError, service_manager.ServiceOwnershipError) as exc:
            print(f"alles could not start: {exc}")
            return False
        print(f"alles start requested through {native.manager}")
        return True
    if not _deps_ok():
        print(f"dependencies are missing for this python:\n  {sys.executable}")
        print("install them with:")
        print(f"  {sys.executable} -m pip install -r requirements.txt")
        print("(if you installed packages into a different python, run alles with that one)")
        return False
    pid = _pid()
    if _running(pid):
        if _alles_process(pid) is not None:
            print(f"alles already running  pid={pid}  {_url()}")
            return True
        print(f"stale pid file points to another process ({pid}); leaving that process alone")
        PID_FILE.unlink(missing_ok=True)
    if _port_open():
        print(f"port {_port()} is busy, but Alles does not own a verified process there")
        print("refusing to stop an unknown process — choose another PORT or stop it yourself")
        return False

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    python = sys.executable or "python3"
    with open(LOG_FILE, "a") as log:
        if IS_WIN:
            proc = subprocess.Popen(
                [python, str(ROOT / "app.py")],
                cwd=ROOT,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                close_fds=True,
            )
        else:
            proc = subprocess.Popen(
                [python, str(ROOT / "app.py")],
                cwd=ROOT,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )

    PID_FILE.write_text(str(proc.pid))

    # wait for the server to actually accept connections — not just for the
    # process to exist. first boot can load embedding models, so give it time.
    print("starting…", end="", flush=True)
    deadline = time.time() + 40
    while time.time() < deadline:
        if _port_open():
            print(f"\ralles started  pid={proc.pid}  {_url()}        ")
            return True
        if proc.poll() is not None:  # process died during startup
            print("\ralles failed to start. last log lines:        \n")
            print("\n".join("  " + l for l in _tail(15)) or "  (log empty)")
            PID_FILE.unlink(missing_ok=True)
            return False
        print(".", end="", flush=True)
        time.sleep(0.5)
    print(f"\ralles is still warming up (pid={proc.pid}).        ")
    print(f"  port {_port()} isn't answering yet — check:  alles logs -f")
    return False


def cmd_stop(args=()):
    native = _native_layout(files=False)
    if native is not None:
        from services import service_manager

        try:
            service_manager.control("server", "stop")
        except (service_manager.ServiceControlError, service_manager.ServiceOwnershipError) as exc:
            print(f"alles could not stop: {exc}")
            return False
        print(f"alles stopped through {native.manager}")
        return True
    pid = _pid()
    if not _running(pid):
        if _port_open():  # PID file stale but something's on the port
            print("no verified Alles process, but the port is busy")
            print("refusing to stop an unknown process")
        else:
            print("alles is not running")
        PID_FILE.unlink(missing_ok=True)
        return not _port_open()

    proc = _alles_process(pid)
    if proc is None:
        print(f"pid {pid} is running but cannot be verified as this Alles installation")
        print("refusing to signal an unknown process")
        return False

    try:
        import psutil

        proc.terminate()
        try:
            proc.wait(timeout=10)
        except psutil.TimeoutExpired:
            print("not responding to a graceful stop — forcing the verified Alles process…")
            proc.kill()
            proc.wait(timeout=2)
        except psutil.NoSuchProcess:
            pass
    except Exception as e:
        print(f"stop failed: {e}")
        return False

    if proc.is_running():
        print(f"stop failed — pid {pid} is still alive")
        return False
    PID_FILE.unlink(missing_ok=True)
    print(f"alles stopped  (pid {pid})")
    return True


def cmd_restart(args=()):
    native = _native_layout()
    if native is not None:
        if not _start_safety_allows(native.data_root):
            return False
        from services import service_manager

        if _native_refresh_service(native):
            print(f"alles restarted through {native.manager}")
            return True
        try:
            service_manager.control("server", "restart")
        except (service_manager.ServiceControlError, service_manager.ServiceOwnershipError) as exc:
            print(f"alles could not restart: {exc}")
            return False
        print(f"alles restarted through {native.manager}")
        return True
    cmd_stop()
    time.sleep(0.5)
    cmd_start()


def _health_ok(port: int) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def _access_label() -> str:
    try:
        from core.server_config import access_profile
        from core.settings import auth_enabled

        profile = access_profile()
        locked = auth_enabled()
    except Exception:
        return ""
    domain = ""
    try:
        from core.settings import load_settings

        bound = str(load_settings().get("base_domain") or "")
        domain = "" if bound == "localhost" else bound
    except Exception:
        pass
    at = f", at {domain}" if domain else ""
    if profile == "device":
        return f"this computer only{at}"
    lock = "password on" if locked else "no password"
    return f"other devices ({profile}, {lock}){at}"


def _settings_path(native) -> Path:
    if native is not None and getattr(native, "config_file", None):
        return native.config_file
    return ROOT / ".env"


def _local_time(iso: str | None) -> str:
    from datetime import datetime

    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ""


def _native_update_lines(native) -> list[tuple[bool | None, str, str]]:
    """Pending accept or rollback, and a newer release waiting, each with the command to run."""
    from services import native_install

    lines: list[tuple[bool | None, str, str]] = []
    try:
        state = _load_native_update_state(_native_update_state_path(native.data_root.resolve()))
    except RuntimeError:
        state = {"phase": "invalid"}
    if state and state.get("phase") == "applied":
        back = f"alles update rollback goes back to {state['old_commit'][:7]}"
        lines.append((True, "update", f"{state['new_commit'][:7]} is on; {back}"))
    elif state and state.get("phase") == "rolled_back":
        lines.append((None, "update", "a rollback needs one more step: alles update rollback"))
    elif state:
        lines.append((False, "update", "an update stopped halfway: alles update rollback"))
    elif native.previous_release.is_file():
        lines.append((True, "update", "the release before this one is still kept"))
    check = native_install.update_check(native, timeout=5)
    if check.get("waiting"):
        lines.append((None, "new release", f"{check['latest'][:7]} is ready: alles update"))
    elif check.get("failed"):
        lines.append(
            (None, "new release", f"{check['failed'][:7]} failed its checks: alles logs boot")
        )
    return lines


def cmd_status(args=()):
    from services import cli_ui

    ui = cli_ui.Style()
    native = _native_layout(files=False)
    port = native.port if native is not None else _port()
    url = f"http://localhost:{port}"
    release = None
    if native is not None:
        from services import native_install

        release = native_install.release_summary(native)
    elif (ROOT / ".git").exists():
        commit = _git_value(["rev-parse", "HEAD"])
        release = {"short": commit[:7], "installed_at": None} if commit else None
    title = ()
    if release and release.get("short"):
        when = _local_time(release.get("installed_at"))
        title = (f"release {release['short']}" + (f" · installed {when}" if when else ""),)
    ui.header("status", title)
    width = 13
    if native is not None:
        from services import service_manager

        try:
            state = service_manager.status("server")
        except service_manager.ServiceOwnershipError as exc:
            ui.check(False, "service", f"untrusted: {exc}", width)
            return False
        if not state["available"]:
            ui.check(False, "service", f"{native.manager} is unavailable", width)
            return False
        running = bool(state["running"])
    else:
        pid = _pid()
        running = _running(pid) and _alles_process(pid) is not None
        if not running and _running(pid):
            ui.check(None, "pid file", f"points to another process ({pid}); left alone", width)
        elif not running and _port_open():
            ui.check(
                None, "port", f"{port} is busy, but no verified Alles process is tracked", width
            )
        elif not running:
            PID_FILE.unlink(missing_ok=True)
    if running:
        healthy = _health_ok(port)
        ui.check(True, "running", url, width)
        ui.check(healthy, "health", "ok" if healthy else "not answering yet: alles logs", width)
        if not healthy and native is not None and _on_mac_drive(native):
            # the service waits on macOS's question until someone answers it
            ui.check(None, "", _ALLOW_HINT, width)
    elif native is not None and state.get("last_exit") and state.get("starts", 0) > 1:
        # the service manager keeps starting it and it keeps dying: "start it" wouldn't help
        ui.check(
            False,
            "not starting",
            f"exits right away (exit {state['last_exit']}, {state['starts']} starts): alles logs",
            width,
        )
        if _on_mac_drive(native):
            ui.check(None, "", _drive_hint(native), width)
        if _health_ok(port):
            ui.check(None, "", f"something else answers on {url}", width)
    else:
        ui.check(False, "stopped", "start it with: alles start", width)
    if native is not None:
        for ok, label, detail in _native_update_lines(native):
            if label:
                ui.check(ok, label, detail, width)
            else:
                ui.say(f"    {' ' * width}{ui.dim(detail)}")
    rows = []
    if release and release.get("short"):
        source = " ".join(
            part for part in (release.get("repository"), release.get("branch")) if part
        )
        rows.append(("release", release["short"] + (f"  ({source})" if source else "")))
    access = _access_label()
    if access:
        rows.append(("access", access))
    if native is not None:
        from services import folder_layout

        ok, text = folder_layout.describe(native)
        if ok:
            rows.append(("folders", text.removeprefix("one folder: ")))
        else:
            ui.check(ok, "folders", text, width)
    rows.append(("settings", cli_ui.short_path(_settings_path(native))))
    rows.append(
        ("data", cli_ui.short_path(native.data_root if native is not None else _runtime_dir()))
    )
    ui.say()
    ui.rows(rows, dim_value=True)
    return running


_EVERYDAY = (
    ("alles access lan", "open it from your phone or another computer"),
    ("alles logs -f", "watch what it is doing"),
    ("alles doctor", "check the install"),
    ("alles config", "edit settings, then: alles restart"),
    ("alles update", "get the newest version"),
    ("alles help", "every command"),
)


def cmd_home(args=()):
    """Bare `alles`: where it stands and what to type next."""
    from services import cli_ui

    cmd_status()
    ui = cli_ui.Style()
    ui.say()
    ui.rows(list(_EVERYDAY))
    ui.say()
    return True


def _log_files() -> list[tuple[str, Path]]:
    """The service log first, then the boot check logs a failed update or restore kept, newest first."""
    from core.settings import data_dir
    from services import native_install

    native = _native_layout(files=False)
    main = native.data_root / "alles-service.log" if native is not None else LOG_FILE
    # what the service said before it could reach the drive sits on the startup disk
    early = native_install.service_launcher_log(native) if native is not None else None
    launcher = [("launcher", early)] if early is not None and early.is_file() else []
    boot = _boot_log_dir(data_dir().expanduser().resolve())
    found = sorted(boot.glob("*.log"), key=lambda p: p.stat().st_mtime) if boot.is_dir() else []
    return [("service", main), *launcher, *((p.stem, p) for p in reversed(found))]


def _logs_options(args: list[str]) -> dict | None:
    """`alles logs` flags the way hermes's `hermes logs` takes them (-n, -f, --level, --since)."""
    opts = {"count": "60", "follow": False, "level": None, "since": None, "grep": None}
    opts["name"] = None
    takes = {"-n": "count", "--lines": "count", "--level": "level", "--since": "since"}
    takes |= {"--grep": "grep", "-g": "grep"}
    items = iter(args)
    for arg in items:
        key, eq, inline = arg.partition("=")
        if key in takes:
            value = inline if eq else next(items, None)
            if value is None:
                print(f"alles logs: {key} needs a value", file=sys.stderr)
                return None
            opts[takes[key]] = value
        elif arg in ("-f", "--follow"):
            opts["follow"] = True
        elif arg.isdigit():
            opts["count"] = arg
        elif not arg.startswith("-") and opts["name"] is None:
            opts["name"] = arg
        else:
            print(f"alles logs: unknown option '{arg}'", file=sys.stderr)
            return None
    if not str(opts["count"]).isdigit():
        print("alles logs: -n takes a number", file=sys.stderr)
        return None
    opts["count"] = int(opts["count"])
    return opts


def cmd_logs(args=()):
    """alles logs [N] [-f] [--level warn] [--since 1h] [--grep text] | boot | list | --clear"""
    from services import cli_logs
    from services.cli_ui import Style, short_path

    args = list(args)
    files = _log_files()
    log_file = files[0][1]
    if "--clear" in args:
        log_file.write_text("")
        print("log cleared")
        return True
    opts = _logs_options(args)
    if opts is None:
        return False
    ui = Style()
    if opts["name"] == "list":
        sizes = [
            (name, f"{path.stat().st_size / 1024:.0f} KB  {short_path(path)}")
            for name, path in files
            if path.is_file()
        ]
        if sizes:
            ui.rows(sizes)
        else:
            print("no logs yet: run  alles start  first")
        return True
    if opts["name"] == "boot":
        if len(files) < 2:
            print("no boot check logs: every update and restore so far started fine")
            return True
        log_file = files[1][1]
        print(ui.dim(short_path(log_file)))
    elif opts["name"] is not None:
        print(f"alles logs: no log named '{opts['name']}' (see: alles logs list)", file=sys.stderr)
        return False
    if not log_file.exists():
        print("no log yet: run  alles start  first")
        return True
    try:
        keep = cli_logs.LineFilter(level=opts["level"], since=opts["since"], grep=opts["grep"])
    except cli_logs.FilterError as exc:
        print(f"alles logs: {exc}", file=sys.stderr)
        return False
    # a terminal gets one readable line per record; a pipe keeps the raw json lines for jq or grep
    if ui.tty:

        def show(line):
            return cli_logs.render(line, ui)
    else:

        def show(line):
            return line

    with log_file.open("r", errors="replace") as handle:
        lines = (line.rstrip("\n") for line in handle)
        for line in cli_logs.last_lines(lines, 40 if opts["follow"] else opts["count"], keep):
            print(show(line))
        sys.stdout.flush()
        if opts["follow"]:
            _follow_logs(handle, keep, show)
    return True


def _follow_logs(handle, keep, show):
    try:
        while True:
            line = handle.readline()
            if not line:
                time.sleep(0.3)
                continue
            line = line.rstrip("\n")
            if keep(line):
                print(show(line), flush=True)
    except KeyboardInterrupt:
        print()


def _git(args, *, capture=True):
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=capture,
        text=True,
    )


def _git_value(args) -> str | None:
    result = _git(args)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _short_path(path) -> str:
    from services.cli_ui import short_path

    return short_path(path)


def _boot_log_dir(live: Path) -> Path:
    """Boot check logs sit beside the data folder, so a data swap or rollback never drops them."""
    from services.backup_recovery import staging_root

    return staging_root(live) / "logs"


def _update_paths(live: Path) -> tuple[Path, Path]:
    import hashlib

    from services.backup_recovery import staging_root

    directory = staging_root(live) / "updates"
    try:
        directory.resolve().relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        # Keep private backups and the detached code worktree outside the Git checkout.
        suffix = hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:12]
        directory = ROOT.resolve().parent / f".{ROOT.name}-updates-{suffix}"
    return directory, directory / "latest.json"


def _write_update_state(path: Path, state: dict | None) -> None:
    import json

    content = None
    if state is not None:
        content = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    _atomic_private_bytes(path, content)


def _create_native_update_state(path: Path, state: dict) -> None:
    """Publish the first native recovery state without replacing a competing update."""
    import json

    content = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("another native update published recovery state") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    try:
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        pass


def _load_update_state(path: Path) -> dict | None:
    import json
    import re

    try:
        state = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RuntimeError("the saved update rollback state is invalid")
    if not isinstance(state, dict):
        raise RuntimeError("the saved update rollback state is invalid")
    for key in ("old_head", "new_head"):
        if not re.fullmatch(r"[0-9a-f]{40}", str(state.get(key, ""))):
            raise RuntimeError("the saved update rollback commit is invalid")
    phase = state.get("phase")
    restore_id = state.get("restore_id")
    if phase not in {"preparing", "clearing"} and not re.fullmatch(
        r"[0-9a-f]{32}", str(restore_id or "")
    ):
        raise RuntimeError("the saved update restore id is invalid")
    operation_id = state.get("operation_id")
    if operation_id is not None and not re.fullmatch(r"[0-9a-f]{32}", str(operation_id)):
        raise RuntimeError("the saved update operation id is invalid")
    candidate_id = state.get("candidate_id")
    if candidate_id is not None and not re.fullmatch(r"[0-9a-f]{32}", str(candidate_id)):
        raise RuntimeError("the saved update candidate id is invalid")
    if not re.fullmatch(r"[0-9a-f]{32}", str(state.get("update_id", ""))):
        raise RuntimeError("the saved update id is invalid")
    if phase not in {
        "preparing",
        "staged",
        "code_switched",
        "applied",
        "rollback_code_restored",
        "rolled_back",
        "clearing",
    }:
        raise RuntimeError("the saved update phase is invalid")
    return state


def _finish_update_marker_if_present(live: Path, update_id: str) -> None:
    from services.update_safety import finish_update, update_lock_path

    if update_lock_path(live).exists():
        finish_update(live, update_id)


def _clear_active_update(live: Path, state_path: Path, state: dict) -> bool:
    from services.update_safety import UpdateSafetyError, finish_update

    try:
        # A durable intermediate phase makes a crash between the two file
        # removals resumable instead of leaving state with a missing marker.
        state["phase"] = "clearing"
        _write_update_state(state_path, state)
        finish_update(live, state["update_id"])
        _write_update_state(state_path, None)
        return True
    except (UpdateSafetyError, OSError, RuntimeError) as exc:
        print(f"could not clear the update maintenance state: {exc}")
        return False


def _health_endpoint_ok(timeout: float = 3, *, base_url: str | None = None) -> bool:
    import json
    import urllib.error
    import urllib.request

    class _RejectRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    endpoint = f"{base_url or _url()}/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RejectRedirects())
    try:
        with opener.open(endpoint, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return response.status == 200 and response.geturl() == endpoint and body.get("ok") is True
    except (OSError, UnicodeError, ValueError, urllib.error.URLError):
        return False


def _updated_server_healthy(target: str) -> bool:
    pid = _pid()
    return (
        _running(pid)
        and _alles_process(pid) is not None
        and _git_value(["rev-parse", "HEAD"]) == target
        and _health_endpoint_ok()
    )


def _update_checkout_ready(old_head: str, target: str) -> bool:
    status = _git(["status", "--porcelain"])
    return (
        status.returncode == 0
        and not status.stdout.strip()
        and _git_value(["rev-parse", "HEAD"]) == old_head
        and _git_value(["rev-parse", "@{upstream}"]) == target
    )


def _updated_checkout_ready(target: str) -> bool:
    status = _git(["status", "--porcelain"])
    return (
        status.returncode == 0
        and not status.stdout.strip()
        and _git_value(["rev-parse", "HEAD"]) == target
        and _git_value(["rev-parse", "@{upstream}"]) == target
    )


def _reset_update_code(commit: str) -> bool:
    # --keep refuses a tracked edit that appears after our clean-tree check.
    # A hard reset would silently destroy that edit.
    result = _git(["reset", "--keep", commit])
    return result.returncode == 0


def _remove_update_worktree(path: Path) -> None:
    import shutil

    try:
        _git(["worktree", "remove", "--force", str(path)])
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _rollback_update(state: dict, state_path: Path | None = None) -> bool:
    """Restore the pre-update commit and staged data snapshot while writers are stopped."""
    state.setdefault("restart_after_rollback", bool(state.get("was_running")))
    if not _stop_for_restore():
        print("could not stop a verified Alles instance — rollback did not start")
        return False
    live = _runtime_dir().expanduser().resolve()
    from services.restore_apply import RestoreApplyError, active_restore_operation

    try:
        active = active_restore_operation(live)
    except RestoreApplyError as exc:
        print(f"restore maintenance state is invalid; rollback refused: {exc}")
        return False
    expected_operation = state.get("operation_id")
    if active is not None and active.operation_id != expected_operation:
        print("another restore operation is active; update rollback did not touch code or data")
        return False

    status = _git(["status", "--porcelain"])
    current = _git_value(["rev-parse", "HEAD"])
    if status.returncode != 0 or status.stdout.strip():
        print("code changed after the update; automatic reset was refused")
        return False
    if current == state["new_head"]:
        if not _reset_update_code(state["old_head"]):
            print("could not restore the previous code commit")
            return False
        status = _git(["status", "--porcelain"])
        current = _git_value(["rev-parse", "HEAD"])
        if status.returncode != 0 or status.stdout.strip() or current != state["old_head"]:
            print("the previous commit was not restored cleanly; data rollback did not start")
            return False
        state["phase"] = "rollback_code_restored"
        if state_path is not None:
            _write_update_state(state_path, state)
    elif current == state["old_head"] and state.get("phase") in {
        "code_switched",
        "applied",
        "rollback_code_restored",
    }:
        # Resume a prior rollback that restored code before data or bookkeeping.
        state["phase"] = "rollback_code_restored"
        if state_path is not None:
            _write_update_state(state_path, state)
    else:
        print("the current commit does not match either side of the saved update")
        return False

    restored = False
    operation_id = expected_operation
    if operation_id:
        from services.instance_lock import InstanceLock, InstanceLockError
        from services.restore_apply import (
            begin_manual_rollback,
            recover_interrupted_restore,
            rollback_restore_operation,
        )

        owner_lock = InstanceLock(live)
        try:
            owner_lock.acquire()
            try:
                operation = begin_manual_rollback(live, operation_id)
            except RestoreApplyError:
                # Recover only the exact operation owned by this update. An
                # unrelated restore must never count as update rollback success.
                active = active_restore_operation(live)
                if active is not None and active.operation_id != operation_id:
                    print("another restore operation became active; data rollback was refused")
                    return False
                if active is not None:
                    result = recover_interrupted_restore(live)
                    restored = result.get("status") == "rolled_back"
                    if result.get("status") == "applied":
                        operation = begin_manual_rollback(live, operation_id)
                        rollback_restore_operation(operation, reason="update-rollback")
                        restored = True
            else:
                rollback_restore_operation(operation, reason="update-rollback")
                restored = True
        except (InstanceLockError, RestoreApplyError, OSError):
            restored = False
        finally:
            owner_lock.release()
    if not restored:
        restored = _apply_staged_restore(state["restore_id"], allow_partial=True)
    if not restored:
        print("code was restored, but data rollback needs attention")
        print("run:  alles restore recover")
        return False
    state["phase"] = "rolled_back"
    if state_path is not None:
        _write_update_state(state_path, state)
    return True


def _cmd_update_rollback() -> bool:
    from services.update_safety import UpdateSafetyError, begin_update

    live = _runtime_dir().expanduser().resolve()
    _, state_path = _update_paths(live)
    try:
        state = _load_update_state(state_path)
    except RuntimeError as exc:
        print(f"update rollback stopped: {exc}")
        return False
    if not state:
        print("no staged update rollback is available")
        return False
    status = _git(["status", "--porcelain"])
    if status.returncode != 0 or status.stdout.strip():
        print("local changes are present — rollback cancelled without touching them")
        return False
    current = _git_value(["rev-parse", "HEAD"])
    phase = state["phase"]
    if current == state["old_head"] and phase in {
        "preparing",
        "staged",
        "clearing",
        "rolled_back",
    }:
        try:
            _finish_update_marker_if_present(live, state["update_id"])
            _write_update_state(state_path, None)
        except (UpdateSafetyError, OSError) as exc:
            print(f"update rollback stopped: {exc}")
            return False
        restart_needed = bool(state.get("restart_after_rollback", state.get("was_running")))
        if restart_needed:
            try:
                running = _restore_server_state()
            except RuntimeError as exc:
                print(f"update recovery finished, but restart was refused: {exc}")
                return False
            if not running and not cmd_start():
                print("update recovery finished, but Alles did not restart; run  alles logs")
                return False
        if phase in {"preparing", "staged"}:
            print("the staged update never switched code; nothing needed rollback")
        else:
            print(f"update rollback bookkeeping recovered at {state['old_head'][:12]}")
        return True
    resumable_old = current == state["old_head"] and phase in {
        "code_switched",
        "applied",
        "rollback_code_restored",
    }
    resumable_new = current == state["new_head"] and phase in {
        "staged",
        "code_switched",
        "applied",
    }
    if not (resumable_old or resumable_new):
        print("the current commit does not match the saved update; rollback cancelled")
        return False
    try:
        begin_update(live, state["update_id"])
    except UpdateSafetyError as exc:
        print(f"update rollback stopped: {exc}")
        return False
    try:
        was_running = _restore_server_state()
    except RuntimeError as exc:
        print(f"update rollback stopped: {exc}")
        return False
    restart_needed = was_running or bool(state.get("restart_after_rollback"))
    state["restart_after_rollback"] = restart_needed
    try:
        _write_update_state(state_path, state)
    except OSError as exc:
        print(f"update rollback stopped before data changes: {exc}")
        return False
    if not _rollback_update(state, state_path):
        return False
    try:
        _finish_update_marker_if_present(live, state["update_id"])
        _write_update_state(state_path, None)
    except (UpdateSafetyError, OSError) as exc:
        print(f"rollback finished, but its maintenance marker remains: {exc}")
        return False
    if restart_needed and not cmd_start():
        print("the previous version was restored but did not restart; run  alles logs")
        return False
    print(f"update rolled back to {state['old_head'][:12]}")
    return True


def _cmd_update_accept(*, quiet: bool = False) -> bool:
    """Forget the one-click rollback after the owner accepts a healthy update."""
    from services.update_safety import update_lock_path

    live = _runtime_dir().expanduser().resolve()
    _, state_path = _update_paths(live)
    try:
        state = _load_update_state(state_path)
    except RuntimeError as exc:
        print(f"update acceptance stopped: {exc}")
        return False
    if not state or state.get("phase") != "applied":
        print("there is no completed update waiting for acceptance")
        return False
    if update_lock_path(live).exists():
        print("the update is still active; recover it before accepting")
        return False
    status = _git(["status", "--porcelain"])
    if status.returncode != 0 or status.stdout.strip():
        print("local changes are present — acceptance cancelled")
        return False
    if _git_value(["rev-parse", "HEAD"]) != state["new_head"]:
        print("the current commit does not match the completed update")
        return False
    from services.backup_recovery import (
        RecoveryError,
        discard_consumed_staged_recovery,
        discard_staged_recovery,
        staging_root,
    )
    from services.recovery_crypto import is_encrypted_recovery
    from services.restore_apply import RestoreApplyError, discard_completed_restore

    raw_backup = Path(str(state.get("backup", ""))).expanduser()
    try:
        backup = raw_backup.resolve(strict=True)
        backup.relative_to(state_path.parent.resolve())
    except (OSError, ValueError):
        print("the retained encrypted rollback backup is missing or outside the update area")
        return False
    if raw_backup.is_symlink() or not backup.is_file() or not is_encrypted_recovery(backup):
        print("the retained rollback backup is not a valid encrypted Alles backup")
        return False

    recovery = staging_root(live)
    try:
        candidate_id = state.get("candidate_id")
        if candidate_id and (recovery / "staged" / candidate_id).exists():
            discard_consumed_staged_recovery(live, candidate_id)
        operation_id = state.get("operation_id")
        if operation_id and (recovery / "operations" / f"{operation_id}.json").exists():
            discard_completed_restore(live, operation_id)
        if (recovery / "staged" / state["restore_id"]).exists():
            discard_staged_recovery(live, state["restore_id"])
        _write_update_state(state_path, None)
    except (RecoveryError, RestoreApplyError, OSError) as exc:
        print(f"update acceptance stopped safely: {exc}")
        return False
    if not quiet:
        print("update accepted; its encrypted pre-update backup was kept")
    return True


def _stage_update_data(
    live: Path,
    code_root: Path,
    update_dir: Path,
    *,
    python_path: Path | None = None,
    artifact_callback=None,
    progress=None,
):
    """Create the encrypted rollback backup and test the new code on a second staged copy."""
    progress = progress or (lambda *_args: None)
    import uuid
    from datetime import datetime

    from services.backup_recovery import (
        RecoveryError,
        create_recovery_archive,
        discard_staged_recovery,
        stage_recovery_archive,
    )
    from services.recovery_crypto import (
        encrypt_recovery_archive,
        load_or_create_recovery_key,
    )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = update_dir / f"{stamp}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, mode=0o700)
    plaintext = run_dir / "pre-update.zip"
    encrypted = run_dir / "pre-update.alles-backup"
    rollback_id = uuid.uuid4().hex
    candidate_id = uuid.uuid4().hex
    rollback = preflight = None
    try:
        if artifact_callback is not None:
            artifact_callback(
                backup=str(encrypted),
                restore_id=rollback_id,
                candidate_id=candidate_id,
            )
        progress("backup", "start")
        recovery_key = load_or_create_recovery_key(live)
        # The key must exist before the snapshot so the installed candidate and
        # retained encrypted backup keep the same recoverable key on first use.
        create_recovery_archive(
            live,
            plaintext,
            include_photos=True,
            expected_recovery_key=recovery_key,
        )
        encrypt_recovery_archive(plaintext, encrypted, recovery_key)
        try:
            encrypted.chmod(0o600)
        except OSError:
            pass
        progress("backup", "done", f"{encrypted.stat().st_size / 1_048_576:.1f} MB, encrypted")
        progress("data", "start", "a copy of your data on the new release")
        rollback = stage_recovery_archive(plaintext, live, restore_id=rollback_id)
        preflight = stage_recovery_archive(plaintext, live, restore_id=candidate_id)
        _prepare_staged_candidate(
            preflight,
            live,
            app_root=code_root,
            python_path=python_path,
            keep_outside_vault=True,
        )
        progress("data", "done", "migrated and started twice")
        return rollback, preflight, encrypted
    except (RecoveryError, RuntimeError, OSError) as exc:
        if preflight is not None:
            discard_staged_recovery(live, preflight.restore_id)
        if rollback is not None:
            discard_staged_recovery(live, rollback.restore_id)
        raise RuntimeError(str(exc)) from exc
    finally:
        plaintext.unlink(missing_ok=True)


def _cmd_update_probe() -> bool:
    """Non-mutating candidate check for the retained rollback control plane."""
    import tempfile

    from services.restore_apply import active_restore_operation
    from services.update_safety import (
        begin_update,
        finish_update,
        update_start_allowed,
    )

    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        update_id = "a" * 32
        begin_update(data, update_id)
        if not update_start_allowed(data, update_id):
            return False
        if active_restore_operation(data) is not None:
            return False
        finish_update(data, update_id)
    print("update rollback control plane ok")
    return True


def _candidate_update_control_plane_ok(code_root: Path, update_dir: Path) -> bool:
    import shutil
    import tempfile

    probe_data = Path(tempfile.mkdtemp(prefix="control-probe-", dir=update_dir))
    env = os.environ.copy()
    env.update(
        {
            "ALLES_DATA": str(probe_data / "data"),
            "ALLES_DB": "",
            "AUTH_ENABLED": "false",
            "PYTHON_DOTENV_DISABLED": "1",
        }
    )
    env.pop("ALLES_UPDATE_TOKEN", None)
    try:
        result = subprocess.run(
            [sys.executable or "python3", "cli.py", "update", "probe"],
            cwd=code_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        shutil.rmtree(probe_data, ignore_errors=True)


def _native_update_state_path(live: Path) -> Path:
    directory, _ = _update_paths(live)
    return directory / "native-latest.json"


def _load_native_update_state(path: Path) -> dict | None:
    import json
    import re

    try:
        state = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("the native update rollback state is invalid") from exc
    if not isinstance(state, dict) or state.get("kind") != "native":
        raise RuntimeError("the native update rollback state is invalid")
    for key in ("update_id",):
        if not re.fullmatch(r"[0-9a-f]{32}", str(state.get(key, ""))):
            raise RuntimeError("the native update rollback state is invalid")
    for key in ("old_release", "new_release"):
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", str(state.get(key, ""))):
            raise RuntimeError("the native update release id is invalid")
    for key in ("old_commit", "new_commit"):
        if not re.fullmatch(r"[0-9a-f]{40}", str(state.get(key, ""))):
            raise RuntimeError("the native update commit is invalid")
    if state.get("phase") not in {
        "preparing",
        "stopping_service",
        "service_stopped",
        "data_staged",
        "data_swapping",
        "data_swapped",
        "release_switched",
        "applied",
        "data_restored",
        "accepting",
        "accepted",
        "rolled_back",
    }:
        raise RuntimeError("the native update phase is invalid")
    for key in ("restore_id", "candidate_id", "operation_id"):
        value = state.get(key)
        if value is not None and not re.fullmatch(r"[0-9a-f]{32}", str(value)):
            raise RuntimeError("the native update recovery state is invalid")
    return state


def _fetch_native_update_source(
    manifest: dict, update_dir: Path, *, progress=None
) -> tuple[Path | None, str]:
    """Fetch one exact commit from the source pinned by the install manifest."""
    import shutil
    import uuid

    source = manifest.get("source") or {}
    if source.get("kind") == "archive":
        return _fetch_archive_update_source(source, update_dir, progress=progress)
    if source.get("kind") != "git":
        raise RuntimeError(
            "this install has no verified Git update source; reinstall from a tracked release"
        )
    from services.native_install import latest_release_commit

    url = source["url"]
    target = latest_release_commit(source)
    if target == source["commit"]:
        return None, target

    update_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    checkout = update_dir / f".native-source-{uuid.uuid4().hex}"
    commands = (
        (["git", "init", str(checkout)], None),
        (["git", "remote", "add", "origin", url], checkout),
        (["git", "fetch", "--depth=1", "origin", target], checkout),
        (["git", "checkout", "--detach", "FETCH_HEAD"], checkout),
    )
    try:
        for command, cwd in commands:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError("the new release could not be downloaded safely")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=checkout,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if (
            head.returncode != 0
            or (head.stdout or "").strip().lower() != target
            or status.returncode != 0
            or (status.stdout or "").strip()
        ):
            raise RuntimeError("the downloaded release did not match the resolved commit")
        return checkout, target
    except (OSError, subprocess.SubprocessError) as exc:
        shutil.rmtree(checkout, ignore_errors=True)
        raise RuntimeError("the new release could not be downloaded safely") from exc
    except Exception:
        shutil.rmtree(checkout, ignore_errors=True)
        raise


def _copy_with_progress(response, out, progress) -> None:
    """Copy a download, telling `progress` how far it got (a bar when the size is known)."""
    from services.cli_ui import Style

    total = int(response.headers.get("Content-Length") or 0) if progress else 0
    done = 0
    ui = Style()
    while chunk := response.read(256 * 1024):
        out.write(chunk)
        done += len(chunk)
        if progress is not None:
            size = f"{done / 1_048_576:.1f} MB"
            detail = f"{ui.bar(done / total, 16)} {size}" if total else f"downloading {size}"
            progress("check", "update", detail)


def _fetch_archive_update_source(
    source: dict, update_dir: Path, *, progress=None
) -> tuple[Path | None, str]:
    """Resolve the branch's newest commit on github and unpack exactly that archive."""
    import shutil
    import tarfile
    import tempfile
    import urllib.request
    import uuid

    from services.native_install import latest_release_commit

    repository = source["repository"]
    target = latest_release_commit(source)
    if target == source["commit"]:
        return None, target

    update_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    checkout = update_dir / f".native-source-{uuid.uuid4().hex}"
    unpack = Path(tempfile.mkdtemp(prefix="archive-", dir=update_dir))
    try:
        archive = unpack / "release.tar.gz"
        request = urllib.request.Request(
            f"https://codeload.github.com/{repository}/tar.gz/{target}",
            headers={"User-Agent": "alles-update"},
        )
        with urllib.request.urlopen(request, timeout=300) as response, archive.open("wb") as out:
            _copy_with_progress(response, out, progress)
        with tarfile.open(archive) as bundle:
            if bundle.pax_headers.get("comment", target).lower() != target:
                raise RuntimeError("the downloaded release did not match the resolved commit")
            if hasattr(tarfile, "data_filter"):
                bundle.extractall(unpack / "tree", filter="data")
            else:
                # older 3.11 builds: refuse anything that is not a plain file or folder inside
                for member in bundle.getmembers():
                    name = Path(member.name)
                    if (
                        name.is_absolute()
                        or ".." in name.parts
                        or not (member.isfile() or member.isdir())
                    ):
                        raise RuntimeError("the downloaded release contains an unsafe entry")
                bundle.extractall(unpack / "tree")
        tops = list((unpack / "tree").iterdir())
        if len(tops) != 1 or not tops[0].is_dir():
            raise RuntimeError("the downloaded release has an unexpected layout")
        os.replace(tops[0], checkout)
        return checkout, target
    except RuntimeError:
        shutil.rmtree(checkout, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(checkout, ignore_errors=True)
        raise RuntimeError("the new release could not be downloaded safely") from exc
    finally:
        shutil.rmtree(unpack, ignore_errors=True)


def _native_candidate_control_plane_ok(release: Path, python: Path, update_dir: Path) -> bool:
    import shutil
    import tempfile

    probe = Path(tempfile.mkdtemp(prefix="native-control-", dir=update_dir))
    env = os.environ.copy()
    env.update(
        {
            "ALLES_DATA": str(probe / "data"),
            "ALLES_DB": "",
            "AUTH_ENABLED": "false",
            "PYTHON_DOTENV_DISABLED": "1",
            # a published release is checked file by file; bytecode would change it
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    env.pop("ALLES_NATIVE_ROOT", None)
    env.pop("ALLES_UPDATE_TOKEN", None)
    try:
        result = subprocess.run(
            [str(python), str(release / "cli.py"), "update", "probe"],
            cwd=release,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def _on_mac_drive(native) -> bool:
    """macOS keeps launchd jobs off an external drive's files until they're allowed."""
    return sys.platform == "darwin" and str(native.data_root).startswith("/Volumes/")


_ALLOW_HINT = "if macOS asks about alles-server, click Allow"


def _drive_hint(native) -> str:
    """What the owner does so macOS lets the service use the drive."""
    from services import native_install

    binary = native_install.service_launcher_path(native)
    if binary is None or not binary.is_file():
        return "macOS keeps it off the drive: run alles restart, then click Allow for alles-server"
    return (
        "macOS keeps it off the drive: allow alles-server in System Settings › "
        "Privacy & Security › Files & Folders"
    )


def _native_refresh_service(native) -> bool:
    """Move the service onto the compiled launcher when it isn't yet. True when it reloaded."""
    if getattr(native, "manager", "") != "launchd":
        return False
    from services import native_install

    try:
        refreshed = native_install.refresh_service(native)
    except (native_install.NativeInstallError, OSError) as exc:
        print(f"alles kept its service as it was: {exc}")
        return False
    if refreshed:
        print(_ALLOW_HINT)
    return refreshed


def _native_service_running() -> bool:
    from services import service_manager

    state = service_manager.status("server")
    if not state.get("available"):
        raise RuntimeError("the owned service manager is unavailable")
    return bool(state.get("running"))


def _native_service_endpoint(layout) -> tuple[int, str]:
    from services import native_install

    # The owned service definition intentionally does not inherit the invoking
    # shell's PORT. Verify that definition before relying on its endpoint (6769 unless the
    # install chose ALLES_PORT, which the dispatcher hands to every command).
    native_install.verify_install(layout)
    port = layout.port
    return port, f"http://127.0.0.1:{port}"


def _native_stop_service(layout) -> None:
    from services import service_manager

    port, _ = _native_service_endpoint(layout)
    if _native_service_running():
        service_manager.control("server", "stop")
    deadline = time.time() + 20
    while _port_open(port) and time.time() < deadline:
        time.sleep(0.2)
    if _port_open(port):
        raise RuntimeError("the owned Alles service did not stop")
    _wait_for_data_lock(layout.data_root)


def _wait_for_data_lock(data_root: Path, seconds: float = 30) -> None:
    """Return once a stopped server has let go of the data lock.

    the port closes first and the shutdown handlers drop the lock after, so taking the lock the
    moment the port closed lost the race (nov 5: an update stopped with "another Alles process is
    already using this data directory" while its own stopped server was still shutting down)."""
    from services.instance_lock import InstanceLock, InstanceLockError

    deadline = time.time() + seconds
    while True:
        lock = InstanceLock(data_root)
        try:
            lock.acquire()
        except InstanceLockError:
            if time.time() >= deadline:
                raise RuntimeError("the owned Alles service is still shutting down") from None
            time.sleep(0.2)
            continue
        lock.release()
        return


def _service_update_token(layout, token: str | None) -> None:
    """Hand an update's start token to the service manager, or take it back (None).

    systemd and launchd start alles with their own environment, so the new release could not see
    the token and refused to start while the update lock was held.
    """
    if getattr(layout, "manager", "") == "launchd":
        command = (
            ["launchctl", "setenv", "ALLES_UPDATE_TOKEN", token]
            if token
            else ["launchctl", "unsetenv", "ALLES_UPDATE_TOKEN"]
        )
    else:
        command = (
            ["systemctl", "--user", "set-environment", f"ALLES_UPDATE_TOKEN={token}"]
            if token
            else ["systemctl", "--user", "unset-environment", "ALLES_UPDATE_TOKEN"]
        )
    try:
        subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def _native_start_service_healthy(layout, token: str | None = None) -> bool:
    from services import service_manager

    _, base_url = _native_service_endpoint(layout)
    if token:
        _service_update_token(layout, token)
    try:
        try:
            # a reload starts it too (RunAtLoad); a failed one leaves the old definition to start
            if not _native_refresh_service(layout):
                service_manager.control("server", "start")
        except Exception:
            return False
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if _native_service_running() and _health_endpoint_ok(timeout=1, base_url=base_url):
                    return True
            except Exception:
                return False
            time.sleep(0.4)
        return False
    finally:
        if token:
            _service_update_token(layout, None)


def _native_restore_update_data(state: dict, live: Path) -> bool:
    """Restore exactly the recovery operation owned by one native update."""
    from services.instance_lock import InstanceLock, InstanceLockError
    from services.restore_apply import (
        RestoreApplyError,
        active_restore_operation,
        begin_manual_rollback,
        recover_interrupted_restore,
        rollback_restore_operation,
    )

    operation_id = state.get("operation_id")
    restored = False
    lock = InstanceLock(live)
    acquired = False
    try:
        lock.acquire()
        acquired = True
        active = active_restore_operation(live)
        if not operation_id:
            if active is None:
                return True
            if active.restore_id != state.get("candidate_id"):
                return False
            operation_id = active.operation_id
            state["operation_id"] = operation_id
        if active is not None:
            if active.operation_id != operation_id:
                return False
            result = recover_interrupted_restore(live)
            if result.get("status") == "rolled_back":
                restored = True
            elif result.get("status") == "applied":
                operation = begin_manual_rollback(live, operation_id)
                rollback_restore_operation(operation, reason="native-update-rollback")
                restored = True
        else:
            operation = begin_manual_rollback(live, operation_id)
            rollback_restore_operation(operation, reason="native-update-rollback")
            restored = True
    except (InstanceLockError, RestoreApplyError, OSError):
        restored = False
    finally:
        if acquired:
            lock.release()
    if restored:
        return True
    restore_id = state.get("restore_id")
    return bool(restore_id and _apply_staged_restore(restore_id, allow_partial=True))


def _native_rollback_update(layout, state: dict, state_path: Path) -> bool:
    from services import native_install

    live = layout.data_root.resolve()
    try:
        phase = state.get("phase")
        service_was_untouched = phase == "preparing" or (
            phase == "stopping_service" and _native_service_running()
        )
        state["service_was_untouched"] = service_was_untouched
        if not service_was_untouched:
            # an "applied" update lets its new release start (update_start_allowed); from here on
            # the service manager must not bring it back while the data goes back
            state["rolling_back"] = True
            _write_update_state(state_path, state)
        if service_was_untouched:
            manifest = native_install.verify_install(layout)
            if manifest["release_id"] != state["old_release"]:
                raise RuntimeError("the active release changed while the candidate was preparing")
            candidate = layout.releases / state["new_release"]
            if candidate.exists():
                native_install.discard_inactive_release(layout, state["new_release"])
            state["phase"] = "rolled_back"
            _write_update_state(state_path, state)
            return True
        _native_stop_service(layout)
        manifest = native_install.verify_install(layout)
        current = manifest["release_id"]
        if current == state["new_release"]:
            native_install.rollback_release(layout, source_commit=state["old_commit"])
        elif current != state["old_release"]:
            raise RuntimeError("the installed release matches neither side of this update")
        if phase in {"data_swapping", "data_swapped", "release_switched", "applied"}:
            if not _native_restore_update_data(state, live):
                raise RuntimeError("the pre-update data snapshot could not be restored")
            # the snapshot is used up once applied; a retry after a later failure must not
            # try to restore it again
            state["phase"] = "data_restored"
            _write_update_state(state_path, state)

        # Once rolled back, the failed candidate must not remain as a selectable release.
        manifest = native_install.verify_install(layout)
        if layout.previous_release.exists():
            previous = layout.previous_release.read_text("utf-8").strip()
            if previous == state["new_release"] and manifest["release_id"] == state["old_release"]:
                native_install.accept_release(layout)
        else:
            candidate = layout.releases / state["new_release"]
            if candidate.exists():
                native_install.discard_inactive_release(layout, state["new_release"])
        state["phase"] = "rolled_back"
        _write_update_state(state_path, state)
        return True
    except Exception as exc:
        print(f"native rollback needs attention: {exc}")
        return False


def _native_complete_rollback(layout, state: dict, state_path: Path) -> bool:
    from services.backup_recovery import (
        RecoveryError,
        discard_consumed_staged_recovery,
        discard_staged_recovery,
        staging_root,
    )
    from services.restore_apply import RestoreApplyError, discard_completed_restore
    from services.update_safety import UpdateSafetyError, finish_update, update_lock_path

    try:
        recovery = staging_root(layout.data_root)
        candidate_id = state.get("candidate_id")
        if candidate_id and (recovery / "staged" / candidate_id).exists():
            candidate = recovery / "staged" / candidate_id
            if (candidate / "data").exists():
                discard_staged_recovery(layout.data_root, candidate_id)
            else:
                discard_consumed_staged_recovery(layout.data_root, candidate_id)
        operation_id = state.get("operation_id")
        journal = recovery / "operations" / f"{operation_id}.json" if operation_id else None
        if journal is not None and journal.exists():
            import json

            # only an applied operation has temporary copies to drop. a rolled-back one keeps
            # its journal and failed copy as the record of what happened
            if json.loads(journal.read_text("utf-8")).get("state") == "applied":
                discard_completed_restore(layout.data_root, operation_id)
        restore_id = state.get("restore_id")
        if restore_id and (recovery / "staged" / restore_id).exists():
            restore = recovery / "staged" / restore_id
            if (restore / "data").exists():
                discard_staged_recovery(layout.data_root, restore_id)
            else:
                discard_consumed_staged_recovery(layout.data_root, restore_id)
        backup_value = str(state.get("backup") or "").strip()
        if backup_value:
            raw_backup = Path(backup_value).expanduser()
            backup = raw_backup.resolve(strict=False)
            update_root = state_path.parent.resolve()
            backup.relative_to(update_root)
            if (
                backup.name != "pre-update.alles-backup"
                or backup.parent.parent != update_root
                or raw_backup.is_symlink()
                or (backup.exists() and not backup.is_file())
            ):
                raise OSError("native rollback backup identity is invalid")
            backup.unlink(missing_ok=True)
            try:
                backup.parent.rmdir()
            except OSError:
                pass
        if update_lock_path(layout.data_root).exists():
            finish_update(layout.data_root, state["update_id"])
    except (RecoveryError, RestoreApplyError, UpdateSafetyError, OSError, ValueError) as exc:
        print(f"native rollback finished, but bookkeeping remains: {exc}")
        return False
    return True


def _native_clear_rollback_state(state_path: Path) -> bool:
    try:
        _write_update_state(state_path, None)
    except OSError as exc:
        print(f"native rollback restarted, but its saved state remains: {exc}")
        return False
    return True


def _native_finish_rollback(layout, state: dict, state_path: Path) -> bool:
    if not _native_rollback_update(layout, state, state_path):
        return False
    service_was_untouched = bool(
        state.get("service_was_untouched", state.get("phase") == "preparing")
    )
    if not _native_complete_rollback(layout, state, state_path):
        return False
    if (
        not service_was_untouched
        and state.get("was_running")
        and not _native_start_service_healthy(layout)
    ):
        print("the previous version was restored but did not restart")
        return False
    return _native_clear_rollback_state(state_path)


def _cmd_native_update_rollback(layout) -> bool:
    from services.update_safety import UpdateCommandLock, UpdateSafetyError

    command_lock = UpdateCommandLock(layout.data_root)
    try:
        command_lock.acquire()
    except UpdateSafetyError as exc:
        print(f"native update rollback stopped: {exc}")
        return False
    try:
        return _cmd_native_update_rollback_locked(layout)
    finally:
        command_lock.release()


def _cmd_native_update_rollback_locked(layout) -> bool:
    from services.update_safety import UpdateSafetyError, begin_update, update_lock_path

    state_path = _native_update_state_path(layout.data_root)
    try:
        state = _load_native_update_state(state_path)
    except RuntimeError as exc:
        print(f"native update rollback stopped: {exc}")
        return False
    if not state:
        print("no native update rollback is available")
        return False
    if state["phase"] in {"accepting", "accepted"}:
        print("the native update was already accepted; run  alles update accept  to finish cleanup")
        return False
    if state["phase"] == "rolled_back":
        if not _native_complete_rollback(layout, state, state_path):
            return False
        if (
            not state.get("service_was_untouched")
            and state.get("was_running")
            and not _native_start_service_healthy(layout)
        ):
            print("the previous version was restored but did not restart")
            return False
        return _native_clear_rollback_state(state_path)
    if not update_lock_path(layout.data_root).exists():
        try:
            begin_update(layout.data_root, state["update_id"])
        except UpdateSafetyError as exc:
            print(f"native update rollback stopped: {exc}")
            return False
    if not _native_finish_rollback(layout, state, state_path):
        return False
    print(f"native update rolled back to {state['old_release'][:12]}")
    return True


def _cmd_native_update_accept(layout) -> bool:
    from services.update_safety import UpdateCommandLock, UpdateSafetyError

    command_lock = UpdateCommandLock(layout.data_root)
    try:
        command_lock.acquire()
    except UpdateSafetyError as exc:
        print(f"native update acceptance stopped: {exc}")
        return False
    try:
        return _cmd_native_update_accept_locked(layout)
    finally:
        command_lock.release()


def _cmd_native_update_accept_locked(layout, *, quiet: bool = False) -> bool:
    from services import native_install
    from services.backup_recovery import (
        RecoveryError,
        discard_consumed_staged_recovery,
        discard_staged_recovery,
        staging_root,
    )
    from services.recovery_crypto import is_encrypted_recovery
    from services.restore_apply import RestoreApplyError, discard_completed_restore
    from services.update_safety import update_lock_path

    state_path = _native_update_state_path(layout.data_root)
    try:
        state = _load_native_update_state(state_path)
    except RuntimeError as exc:
        print(f"native update acceptance stopped: {exc}")
        return False
    if not state or state["phase"] not in {"applied", "accepting", "accepted"}:
        print("there is no completed native update waiting for acceptance")
        return False
    if update_lock_path(layout.data_root).exists():
        print("the native update is still active; recover it before accepting")
        return False
    manifest = native_install.verify_install(layout)
    if manifest["release_id"] != state["new_release"]:
        print("the installed release does not match the completed native update")
        return False
    raw_backup = Path(str(state.get("backup", ""))).expanduser()
    try:
        backup = raw_backup.resolve(strict=True)
        backup.relative_to(state_path.parent.resolve())
    except (OSError, ValueError):
        print("the retained encrypted rollback backup is missing or outside the update area")
        return False
    if raw_backup.is_symlink() or not backup.is_file() or not is_encrypted_recovery(backup):
        print("the retained rollback backup is not a valid encrypted Alles backup")
        return False
    recovery = staging_root(layout.data_root)
    try:
        if state["phase"] == "applied":
            state["phase"] = "accepting"
            _write_update_state(state_path, state)
        if state["phase"] == "accepting":
            # This call is intentionally retryable with expected_previous: once both the old
            # release tree and pointer are gone, accept_release returns that expected id.
            native_install.accept_release(layout, expected_previous=state["old_release"])
            state["phase"] = "accepted"
            _write_update_state(state_path, state)
        candidate_id = state.get("candidate_id")
        if candidate_id and (recovery / "staged" / candidate_id).exists():
            discard_consumed_staged_recovery(layout.data_root, candidate_id)
        operation_id = state.get("operation_id")
        if operation_id and (recovery / "operations" / f"{operation_id}.json").exists():
            discard_completed_restore(layout.data_root, operation_id)
        if state.get("restore_id") and (recovery / "staged" / state["restore_id"]).exists():
            discard_staged_recovery(layout.data_root, state["restore_id"])
        _write_update_state(state_path, None)
    except (RecoveryError, RestoreApplyError, OSError, native_install.NativeInstallError) as exc:
        print(f"native update acceptance stopped safely: {exc}")
        return False
    if not quiet:
        print("native update accepted; its encrypted pre-update backup was kept")
    # the one folder move runs here, in the new release, once the old one can't roll back to a
    # layout it doesn't know (an older installed release runs the whole update itself)
    _folders_move(layout, quiet_when_nothing=True)
    return True


def _folders_move(layout, *, quiet_when_nothing: bool = False) -> bool:
    """Stop the service, put the folders in one place (or finish a half move), start it again."""
    from services import cli_ui, folder_layout
    from services.instance_lock import InstanceLock, InstanceLockError

    ui = cli_ui.Style()
    try:
        found = folder_layout.plan(layout)
    except (folder_layout.FolderMoveError, OSError) as exc:
        ui.check(False, "folders", f"can't be read: {exc}", 12)
        return False
    if found["state"] not in {"move", "unfinished"}:
        if not quiet_when_nothing:
            ok, text = folder_layout.describe(layout)
            ui.check(ok, "folders", text, 12)
        return found["state"] in {"one-folder", "inside-data"}
    try:
        was_running = _native_service_running()
        _native_stop_service(layout)
    except RuntimeError as exc:
        ui.check(False, "folders", f"not moved: {exc}", 12)
        return False
    lock = InstanceLock(layout.data_root)
    try:
        lock.acquire()
    except InstanceLockError as exc:
        ui.check(False, "folders", f"not moved: {exc}", 12)
        return False
    try:
        result = folder_layout.move(layout)
    except (folder_layout.FolderMoveError, OSError) as exc:
        result = {"state": "failed", "why": str(exc)}
    finally:
        lock.release()
    if result["state"] == "done":
        ui.check(True, "folders", "docs and files are in ~/Alles, backups beside the data", 12)
    elif result["state"] == "rolled_back":
        ui.check(None, "folders", f"put back as they were: {result.get('why', 'it stopped')}", 12)
    else:
        ui.check(False, "folders", f"not moved: {result.get('why', result['state'])}", 12)
    if was_running and not _native_start_service_healthy(layout):
        ui.check(False, "service", "did not start again: alles logs", 12)
        return False
    return result["state"] == "done"


def cmd_folders(args=()):
    """alles folders [move]: where docs, files and backups are, and the one folder move."""
    from services import cli_ui, folder_layout
    from services.update_safety import UpdateCommandLock, UpdateSafetyError

    # showing the folders only reads; the move below changes data and checks every file
    native = _native_layout(files=tuple(args) == ("move",))
    ui = cli_ui.Style()
    if native is None:
        ui.check(None, "folders", "only an installed alles (alles install) moves its folders", 12)
        return not args
    if tuple(args) == ("move",):
        command_lock = UpdateCommandLock(native.data_root)
        try:
            command_lock.acquire()
        except UpdateSafetyError as exc:
            ui.check(False, "folders", f"not now: {exc}", 12)
            return False
        try:
            return _folders_move(native)
        finally:
            command_lock.release()
    if args:
        print("usage:  alles folders  |  alles folders move")
        return False
    from core.settings import load_settings

    settings = load_settings()
    ok, text = folder_layout.describe(native)
    ui.check(ok, "folders", text, 12)
    ui.rows(
        [
            ("docs", cli_ui.short_path(settings.get("vault_dir") or native.data_root / "vault")),
            ("files", cli_ui.short_path(settings.get("files_dir") or native.data_root / "files")),
            ("backups", cli_ui.short_path(settings.get("automatic_backup_dir") or "not set")),
            ("data", cli_ui.short_path(native.data_root)),
        ],
        dim_value=True,
    )
    return ok is not False


def _cmd_native_update(layout) -> bool:
    from services.update_safety import UpdateCommandLock, UpdateSafetyError

    command_lock = UpdateCommandLock(layout.data_root)
    try:
        command_lock.acquire()
    except UpdateSafetyError as exc:
        print(f"native update stopped: {exc}")
        return False
    try:
        return _cmd_native_update_locked(layout)
    finally:
        command_lock.release()


# Bump only when the hand-off arguments change; an installed release reads this line from the
# release it downloaded and runs the old in-process path when it is missing.
NATIVE_UPDATE_HANDOFF = 1


def _native_handoff_version(release: Path) -> int:
    """Read the hand-off protocol a staged release speaks, without running it."""
    import re

    try:
        text = (release / "cli.py").read_text("utf-8")
    except (OSError, UnicodeError):
        return 0
    found = re.search(r"^NATIVE_UPDATE_HANDOFF = (\d+)$", text, re.MULTILINE)
    return int(found.group(1)) if found else 0


def _native_run_handoff(release: Path, python: Path, update_id: str) -> bool:
    """Let the downloaded release prepare, check and switch to itself; we wait for its answer."""
    env = os.environ.copy()
    # a published release is checked file by file; bytecode would change it
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("ALLES_UPDATE_TOKEN", None)
    try:
        result = subprocess.run(
            [str(python), "-B", str(release / "cli.py"), "update", "handoff", update_id],
            cwd=release,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"the new release could not be started: {exc}") from exc
    return result.returncode == 0


_UPDATE_STEPS = {
    "check": "new release",
    "copy": "app files",
    "environment": "python environment",
    "packages": "python packages",
    "startup": "startup check",
    "backup": "backup",
    "data": "data check",
    "switch": "switch",
    "health": "health check",
    "service": "background service",
}


def _update_steps():
    from services import cli_ui

    return cli_ui.Steps(_UPDATE_STEPS, cli_ui.Style())


def _timed_step(steps, step: str, work, *args, **kwargs):
    """Run one piece of work under a live step line; the step is marked done when it returns."""
    if steps is None:
        return work(*args, **kwargs)
    steps.start(step)
    result = work(*args, **kwargs)
    if result:
        steps.finish(True, step)
    return result


def _native_keep_last_update(layout, state: dict | None, steps) -> bool:
    """Asking for a newer release is the owner's ok for the last one, so the update keeps it.

    Only a release that runs and answers its health check is kept. One that doesn't may be the
    reason for this update, and the old release is the only way back, so that still takes a
    rollback or an accept by hand. An update that stopped halfway is never kept.
    """
    from services import native_install

    ui, width = steps.style, steps.width

    def stop(why: str, *more: str) -> bool:
        ui.check(None, "update", why, width)
        for line in more:
            ui.say(f"    {' ' * width}{ui.dim(line)}")
        return False

    phase = state["phase"] if state else None
    if phase == "rolled_back":
        return stop("a rollback needs one more step: alles update rollback")
    if phase not in {None, "applied", "accepting", "accepted"}:
        return stop("the last update stopped halfway: alles update rollback")
    if phase in {None, "applied"}:
        try:
            _, base_url = _native_service_endpoint(layout)
            healthy = _native_service_running() and _health_endpoint_ok(base_url=base_url)
        except Exception:
            healthy = False
        if not healthy:
            more = ("start it, then update again: alles start",)
            if state:
                more += ("or go back: alles update rollback", "or keep it: alles update accept")
            return stop("the last one isn't running, so its way back is still kept", *more)
    if state is None:
        # an old release left with no record of the update that kept it: nothing to roll back
        try:
            native_install.accept_release(layout)
        except native_install.NativeInstallError as exc:
            return stop(f"the release kept from before could not be removed: {exc}")
        return True
    if not _cmd_native_update_accept_locked(layout, quiet=True):
        return False
    ui.check(True, "last update", f"{state['new_commit'][:7]} kept", width)
    return True


def _cmd_native_update_locked(layout) -> bool:
    import shutil
    import uuid

    from services import native_install
    from services.instance_lock import InstanceLockError
    from services.restore_apply import RestoreApplyError
    from services.update_safety import UpdateSafetyError, begin_update

    live = layout.data_root.resolve()
    update_dir, _ = _update_paths(live)
    state_path = _native_update_state_path(live)
    source_checkout = None
    target = None
    update_id = None
    update_started = False
    state_published = False
    steps = _update_steps()
    try:
        manifest = native_install.verify_install(layout)
        old_short = manifest["source"].get("commit", manifest["release_id"])[:7]
        steps.style.header("update", (f"release {old_short}",))
        existing = _load_native_update_state(state_path)
        if existing or layout.previous_release.exists():
            if not _native_keep_last_update(layout, existing, steps):
                return False
            manifest = native_install.verify_install(layout)
        kind = (manifest.get("source") or {}).get("kind")
        steps.start("check", "asking github" if kind == "archive" else "asking the release source")
        source_checkout, target = _fetch_native_update_source(
            manifest, update_dir, progress=steps.handle
        )
        native_install.remember_latest(layout, manifest["source"]["commit"], target)
        if source_checkout is None:
            steps.finish(True, "check", f"{old_short} is the newest, nothing to do")
            return True
        steps.finish(True, "check", f"{old_short} → {target[:7]}")
        update_id = uuid.uuid4().hex
        was_running = _native_service_running()
        state = {
            "kind": "native",
            "phase": "preparing",
            "update_id": update_id,
            "old_release": manifest["release_id"],
            "new_release": target,
            "old_commit": manifest["source"]["commit"],
            "new_commit": target,
            "was_running": was_running,
        }
        _create_native_update_state(state_path, state)
        state_published = True
        begin_update(live, update_id)
        update_started = True
        release = native_install.stage_update_release(
            source_checkout,
            layout,
            release_id=target,
            release_builder=lambda source, stage: native_install.build_release(
                source, stage, progress=steps.handle
            ),
            release_probe=lambda stage, python: _timed_step(
                steps, "startup", _native_install_probe, stage, python
            ),
        )
        python = release / ".venv" / "bin" / "python"
        if not _native_candidate_control_plane_ok(release, python, update_dir):
            raise RuntimeError("the staged native release cannot run the rollback control plane")
        if _native_handoff_version(release) == NATIVE_UPDATE_HANDOFF:
            # the new release prepares and checks its own data (oct 28: a fix to that step used
            # to reach the box one release late); this one only fetched it and keeps the rollback
            steps.close()
            if _native_run_handoff(release, python, update_id):
                return True
            left = _load_native_update_state(state_path)
            if not (left and left.get("update_id") == update_id):
                # the new release already put everything back and said why
                native_install.remember_failed(layout, manifest["source"]["commit"], target)
                return False
            raise RuntimeError("the new release stopped before it finished its update")
        return _native_apply_update(
            layout, state, state_path, release, python, update_dir, steps=steps
        )
    except (
        native_install.NativeInstallError,
        UpdateSafetyError,
        InstanceLockError,
        RestoreApplyError,
        RuntimeError,
        OSError,
    ) as exc:
        _native_update_failed(
            layout,
            exc,
            state_path=state_path,
            update_id=update_id,
            target=target,
            update_started=update_started,
            state_published=state_published,
            steps=steps,
        )
        return False
    finally:
        steps.close()
        if source_checkout is not None:
            shutil.rmtree(source_checkout, ignore_errors=True)


def _native_update_failed(
    layout,
    exc: Exception,
    *,
    state_path: Path,
    update_id: str | None,
    target: str | None,
    update_started: bool,
    state_published: bool,
    steps=None,
) -> None:
    from services import native_install
    from services.update_safety import UpdateSafetyError, finish_update

    live = layout.data_root.resolve()
    if steps is not None:
        steps.fail(f"update stopped: {exc}")
    else:
        print(f"native update stopped: {exc}")
    try:
        state = _load_native_update_state(state_path)
    except RuntimeError:
        state = None
    if target:
        # the release this update started from: once the switch happened, the installed one is
        # the failed target itself, and status then called the running release "failed"
        current = (
            (state or {}).get("old_commit")
            if state and state.get("update_id") == update_id
            else None
        )
        if not current:
            try:
                current = native_install.verify_install(layout)["source"]["commit"]
            except (native_install.NativeInstallError, KeyError, TypeError):
                current = None
        if current:
            native_install.remember_failed(layout, current, target)
    owned_state = bool(state and update_id and state.get("update_id") == update_id)
    if owned_state and (update_started or state.get("phase") != "preparing"):
        if _native_finish_rollback(layout, state, state_path):
            print()
            print(f"  your data and release {state['old_commit'][:7]} are back as they were")
        else:
            print("run:  alles update rollback")
        return
    if owned_state and state_published:
        try:
            _write_update_state(state_path, None)
        except OSError:
            print("the native update recovery state still needs cleanup")
    if update_started and update_id:
        try:
            finish_update(live, update_id)
        except UpdateSafetyError:
            print("the native update maintenance marker still needs recovery")
    if update_started and target and (layout.releases / target).exists():
        try:
            native_install.discard_inactive_release(layout, target)
        except native_install.NativeInstallError:
            pass


def _native_apply_update(
    layout,
    state: dict,
    state_path: Path,
    release: Path,
    python: Path,
    update_dir: Path,
    *,
    steps=None,
) -> bool:
    """Back up, migrate a copy with `release`'s code, swap it in and switch. Raises on failure."""
    from services import native_install
    from services.instance_lock import InstanceLock
    from services.restore_apply import (
        begin_restore_operation,
        complete_restore_operation,
        swap_in_staged,
    )
    from services.update_safety import finish_update

    live = layout.data_root.resolve()
    update_id, target = state["update_id"], state["new_release"]
    state["phase"] = "stopping_service"
    _write_update_state(state_path, state)
    _native_stop_service(layout)
    state["phase"] = "service_stopped"
    _write_update_state(state_path, state)

    lock = InstanceLock(live)
    acquired = False
    operation = None
    encrypted = None
    try:
        lock.acquire()
        acquired = True

        def persist_staged_artifact(**artifact):
            state.update(artifact)
            _write_update_state(state_path, state)

        rollback, candidate, encrypted = _stage_update_data(
            live,
            release,
            update_dir,
            python_path=python,
            artifact_callback=persist_staged_artifact,
            **({"progress": steps.handle} if steps is not None else {}),
        )
        state.update(
            {
                "phase": "data_staged",
                "restore_id": rollback.restore_id,
                "candidate_id": candidate.restore_id,
                "backup": str(encrypted),
            }
        )
        _write_update_state(state_path, state)
        issues = _update_coverage_issues(rollback)
        if issues:
            raise RuntimeError(
                "automatic native update cannot roll back external data roots: " + ", ".join(issues)
            )
        operation = begin_restore_operation(live, candidate.restore_id)
        if steps is not None:
            steps.start("switch")
        state.update({"phase": "data_swapping", "operation_id": operation.operation_id})
        _write_update_state(state_path, state)
        swap_in_staged(operation, candidate.data_dir)
        state["phase"] = "data_swapped"
        _write_update_state(state_path, state)
        native_install.activate_release(layout, target, source_commit=state["new_commit"])
        state["phase"] = "release_switched"
        _write_update_state(state_path, state)
        if steps is not None:
            steps.finish(True, "switch", f"release {target[:7]}")
    finally:
        if acquired:
            lock.release()

    healthy = _timed_step(
        steps,
        "health",
        _run_recovery_probe,
        live,
        passes=1,
        app_root=release,
        python_path=python,
        log_dir=_boot_log_dir(live),
    )
    if not healthy:
        raise RuntimeError(_probe_failure(healthy, "the new release failed its health check"))
    complete_restore_operation(operation)
    state["phase"] = "applied"
    _write_update_state(state_path, state)
    if state["was_running"] and not _timed_step(
        steps, "service", _native_start_service_healthy, layout, token=update_id
    ):
        raise RuntimeError(
            "the new release did not start as a service\nits log: "
            + _short_path(layout.data_root / "alles-service.log")
        )
    finish_update(live, update_id)
    if steps is None:
        print(f"alles updated safely to native release {target[:12]}")
        print(f"rollback backup kept at: {encrypted}")
        print("rollback command:  alles update rollback")
        return True
    ui = steps.style
    steps.close()
    ui.say()
    ui.say(f"  {ui.good(ui.mark_ok)} {ui.bold(f'alles is on release {target[:7]}')}")
    ui.say()
    ui.rows(
        [
            ("go back", "alles update rollback"),
            ("backup", _short_path(encrypted)),
        ],
    )
    ui.say()
    return True


def _cmd_native_update_handoff(layout, update_id: str) -> bool:
    """Runs inside the downloaded release: the installed one fetched it and holds the lock."""
    import re

    from services import native_install
    from services.instance_lock import InstanceLockError
    from services.restore_apply import RestoreApplyError
    from services.update_safety import UpdateCommandLock, UpdateSafetyError

    if not re.fullmatch(r"[0-9a-f]{32}", update_id or ""):
        print("usage:  alles update")
        return False
    probe_lock = UpdateCommandLock(layout.data_root)
    try:
        probe_lock.acquire()
    except UpdateSafetyError:
        pass  # held by the installed release that started this one, as it should be
    else:
        probe_lock.release()
        print("this step only runs from  alles update")
        return False
    live = layout.data_root.resolve()
    update_dir, _ = _update_paths(live)
    state_path = _native_update_state_path(live)
    try:
        state = _load_native_update_state(state_path)
    except RuntimeError as exc:
        print(f"native update stopped: {exc}")
        return False
    if not state or state.get("update_id") != update_id or state.get("phase") != "preparing":
        print("native update stopped: no update is waiting for this release")
        return False
    release = layout.releases / state["new_release"]
    if ROOT.resolve() != release.resolve():
        print("native update stopped: only the downloaded release can prepare itself")
        return False
    steps = _update_steps()
    try:
        return _native_apply_update(
            layout,
            state,
            state_path,
            release,
            release / ".venv" / "bin" / "python",
            update_dir,
            steps=steps,
        )
    except (
        native_install.NativeInstallError,
        UpdateSafetyError,
        InstanceLockError,
        RestoreApplyError,
        RuntimeError,
        OSError,
    ) as exc:
        _native_update_failed(
            layout,
            exc,
            state_path=state_path,
            update_id=update_id,
            target=state["new_release"],
            update_started=True,
            state_published=True,
            steps=steps,
        )
        return False
    finally:
        steps.close()


def cmd_update(args=()):
    import uuid

    native = _native_layout()
    if args:
        if tuple(args) == ("probe",):
            return _cmd_update_probe()
        if tuple(args) in (("rollback",), ("recover",)):
            if native is not None:
                return _cmd_native_update_rollback(native)
            return _cmd_update_rollback()
        if tuple(args) == ("accept",):
            if native is not None:
                return _cmd_native_update_accept(native)
            return _cmd_update_accept()
        if len(args) == 2 and args[0] == "handoff" and native is not None:
            return _cmd_native_update_handoff(native, args[1])
        print("usage:  alles update  |  alles update rollback  |  alles update accept")
        return False
    if native is not None:
        return _cmd_native_update(native)
    if not (ROOT / ".git").exists():
        print("not a git checkout — update manually, then  alles restart")
        return False
    try:
        status = _git(["status", "--porcelain"])
    except FileNotFoundError:
        print("git not found on PATH")
        return False
    if status.returncode != 0:
        print("could not inspect the working tree — update cancelled")
        return False
    if status.stdout.strip():
        print("local changes are present — update cancelled without touching them")
        print("commit or move those changes first, then run  alles update")
        return False

    old_head = _git_value(["rev-parse", "HEAD"])
    if not old_head:
        print("could not identify the current commit — update cancelled")
        return False
    print("checking the upstream release without changing live files…")
    fetch = _git(["fetch", "--prune"])
    if fetch.returncode != 0:
        print("git fetch failed — live code and data were not changed")
        return False
    target = _git_value(["rev-parse", "@{upstream}"])
    if not target:
        print("this branch has no upstream release to update from")
        return False
    if target == old_head:
        print("alles is already up to date")
        return True
    if _git(["merge-base", "--is-ancestor", old_head, target]).returncode != 0:
        print("upstream is not a fast-forward update — live files were not changed")
        return False

    live = _runtime_dir().expanduser().resolve()
    if os.environ.get("ALLES_DB"):
        print("automatic update is disabled while ALLES_DB overrides the database path")
        return False
    update_dir, state_path = _update_paths(live)
    update_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        existing_state = _load_update_state(state_path)
    except RuntimeError as exc:
        print(f"an earlier update needs attention: {exc}")
        return False
    if existing_state:
        # same rule as the installed update: a healthy last update is kept by asking for the next
        if existing_state.get("phase") != "applied" or not _health_endpoint_ok():
            print("an earlier update still has rollback state")
            print("use  alles update rollback  or  alles update accept  before another update")
            return False
        if not _cmd_update_accept(quiet=True):
            return False
        print("the last update was kept")
    from services.restore_apply import maintenance_lock_path
    from services.update_safety import update_lock_path

    if maintenance_lock_path(live).exists():
        print("an unfinished restore must be recovered before updating")
        return False
    if update_lock_path(live).exists():
        print("an unfinished update marker must be recovered before updating")
        return False
    code_stage = update_dir / f".code-{uuid.uuid4().hex}"
    try:
        added = _git(["worktree", "add", "--detach", str(code_stage), target])
        if added.returncode != 0:
            print("could not stage the downloaded code — live files were not changed")
            return False
        for dependency_file in ("requirements.txt", "pyproject.toml"):
            current = ROOT / dependency_file
            candidate = code_stage / dependency_file
            if current.read_bytes() != candidate.read_bytes():
                print(
                    "this update changes Python dependencies; automatic update was stopped safely"
                )
                print("use the future packaged updater, or update the environment manually")
                return False
        compile_check = subprocess.run(
            [
                sys.executable or "python3",
                "-m",
                "compileall",
                "-q",
                "cli.py",
                "app.py",
                "core",
                "routes",
                "services",
            ],
            cwd=code_stage,
        )
        if compile_check.returncode != 0:
            print("staged code did not compile — live files were not changed")
            return False
        if not _candidate_update_control_plane_ok(code_stage, update_dir):
            print("staged code cannot run the rollback control plane — live files were unchanged")
            return False
        try:
            was_running = _restore_server_state()
        except RuntimeError as exc:
            print(f"update stopped: {exc}")
            return False
        update_id = uuid.uuid4().hex
        state = {
            "phase": "preparing",
            "update_id": update_id,
            "old_head": old_head,
            "new_head": target,
            "was_running": was_running,
        }
        _write_update_state(state_path, state)
        from services.update_safety import UpdateSafetyError, begin_update, finish_update

        try:
            begin_update(live, update_id)
        except UpdateSafetyError as exc:
            print(f"update stopped: {exc}")
            _write_update_state(state_path, None)
            return False
        if not _stop_for_restore():
            print("could not stop a verified Alles instance; code and data were not changed")
            _clear_active_update(live, state_path, state)
            return False
        from services.instance_lock import InstanceLock, InstanceLockError
        from services.restore_apply import (
            RestoreApplyError,
            begin_restore_operation,
            complete_restore_operation,
            swap_in_staged,
        )

        owner_lock = InstanceLock(live)
        owner_held = False
        code_switched = False
        swapped = False
        operation = None
        rollback = None
        candidate = None
        try:
            owner_lock.acquire()
            owner_held = True
            # A preflight can be slow. Re-check the exact pinned state after writers
            # stopped and immediately before any live code changes.
            if not _update_checkout_ready(old_head, target):
                raise RuntimeError("code or upstream changed during preflight")

            print("creating an exact encrypted rollback backup while all writers are stopped…")

            def persist_staged_artifact(**artifact):
                state.update(artifact)
                _write_update_state(state_path, state)

            rollback, candidate, encrypted = _stage_update_data(
                live,
                code_stage,
                update_dir,
                artifact_callback=persist_staged_artifact,
            )
            issues = _update_coverage_issues(rollback)
            if issues:
                joined = ", ".join(issues)
                raise RuntimeError(
                    f"automatic update cannot yet roll back external data roots: {joined}"
                )
            state.update(
                {
                    "phase": "staged",
                    "restore_id": rollback.restore_id,
                    "candidate_id": candidate.restore_id,
                    "backup": str(encrypted),
                }
            )
            _write_update_state(state_path, state)

            if not _update_checkout_ready(old_head, target):
                raise RuntimeError("code or upstream changed while the candidate was tested")

            switched = _git(["merge", "--ff-only", target], capture=False)
            if switched.returncode != 0:
                raise RuntimeError("the staged code could not be switched in")
            code_switched = True
            state["phase"] = "code_switched"
            _write_update_state(state_path, state)
            if not _updated_checkout_ready(target):
                raise RuntimeError("live code differs from the tested update candidate")

            operation = begin_restore_operation(live, candidate.restore_id)
            state["operation_id"] = operation.operation_id
            _write_update_state(state_path, state)
            swap_in_staged(operation, candidate.data_dir)
            swapped = True
        except (InstanceLockError, RestoreApplyError, RuntimeError, OSError) as exc:
            print(f"update switch failed: {exc}")
        finally:
            if owner_held:
                owner_lock.release()

        if not code_switched:
            from services.backup_recovery import discard_staged_recovery

            for staged in (candidate, rollback):
                if staged is not None:
                    try:
                        discard_staged_recovery(live, staged.restore_id)
                    except Exception:
                        pass
            if _clear_active_update(live, state_path, state):
                _restart_original_if_needed(was_running)
            return False
        if operation is None or not swapped:
            if _rollback_update(state, state_path):
                if _clear_active_update(live, state_path, state):
                    if not _restart_original_if_needed(was_running):
                        print("the original data was restored but Alles did not restart")
            else:
                print("automatic rollback needs help; run:  alles update rollback")
            return False

        # The swapped candidate already booted twice in isolation. Probe it once
        # in the final location before releasing the restore rollback snapshot.
        previous_token = os.environ.get("ALLES_UPDATE_TOKEN")
        os.environ["ALLES_UPDATE_TOKEN"] = update_id
        try:
            healthy = _run_recovery_probe(live, passes=1, log_dir=_boot_log_dir(live))
        finally:
            if previous_token is None:
                os.environ.pop("ALLES_UPDATE_TOKEN", None)
            else:
                os.environ["ALLES_UPDATE_TOKEN"] = previous_token
        if not healthy:
            print(_probe_failure(healthy, "the new version failed its health check"))
            print("rolling back…")
            if _rollback_update(state, state_path):
                if _clear_active_update(live, state_path, state):
                    if _restart_original_if_needed(was_running):
                        print("the original version was restored")
                    else:
                        print("the original version was restored but Alles did not restart")
            else:
                print("automatic rollback needs help; run:  alles update rollback")
            return False

        try:
            complete_restore_operation(operation)
        except RestoreApplyError as exc:
            print(f"update health passed, but rollback bookkeeping failed: {exc}")
            print("run:  alles update rollback")
            return False

        if was_running:
            previous_token = os.environ.get("ALLES_UPDATE_TOKEN")
            os.environ["ALLES_UPDATE_TOKEN"] = update_id
            try:
                healthy = bool(cmd_start()) and _updated_server_healthy(target)
            finally:
                if previous_token is None:
                    os.environ.pop("ALLES_UPDATE_TOKEN", None)
                else:
                    os.environ["ALLES_UPDATE_TOKEN"] = previous_token
            if not healthy:
                print("updated normal startup failed — rolling code and data back…")
                if _rollback_update(state, state_path):
                    if _clear_active_update(live, state_path, state):
                        if _restart_original_if_needed(True):
                            print("the original version was restored")
                        else:
                            print("the original version was restored but did not restart")
                else:
                    print("automatic rollback needs help; run:  alles update rollback")
                return False

        state["phase"] = "applied"
        _write_update_state(state_path, state)
        try:
            finish_update(live, update_id)
        except UpdateSafetyError as exc:
            print(f"update applied, but its maintenance marker remains: {exc}")
            print("run:  alles update rollback")
            return False
        print(f"alles updated safely to {target[:12]}")
        print(f"rollback backup kept at: {encrypted}")
        print("rollback command:  alles update rollback")
        if not was_running:
            print("Alles was stopped before update, so it was left stopped")
        return True
    finally:
        if code_stage.exists():
            _remove_update_worktree(code_stage)


def cmd_open(args=()):
    if not _port_open():
        print("alles isn't reachable — start it first with  alles start")
        return
    webbrowser.open(_url())
    print(f"opening {_url()}")


def _folder_checks() -> list[tuple[bool | None, str, str]]:
    """Where the docs and files folders point, that they exist and take writes, and no update copy.

    oct 28: doctor said "ready" while the docs folder pointed at an update's copy inside data/.
    """
    import uuid

    from core.settings import data_dir, load_settings
    from services.backup_recovery import EXTERNAL_VAULT_SUBPATH
    from services.cli_ui import short_path

    data = data_dir().expanduser().resolve()
    try:
        settings = load_settings()
    except Exception as exc:  # a broken settings file is itself the finding
        return [(False, "settings", f"can't be read: {exc}")]
    copy = data / EXTERNAL_VAULT_SUBPATH
    out = []
    for key, label, default in (
        ("vault_dir", "docs folder", data / "vault"),
        ("files_dir", "files folder", data / "files"),
    ):
        path = Path(settings.get(key) or default).expanduser()
        if not path.is_absolute():
            path = ROOT / path  # how files_store anchors a relative folder
        path = path.resolve()
        shown = short_path(path)
        if path == copy or copy in path.parents:
            out.append((False, label, f"{shown} is an update's copy: point it back to your folder"))
            continue
        if not path.is_dir():
            out.append((False, label, f"{shown} is missing"))
            continue
        probe = path / f".alles-doctor-{uuid.uuid4().hex}"
        try:
            probe.write_bytes(b"")
            probe.unlink()
        except OSError:
            out.append((False, label, f"{shown} can't be written"))
            continue
        out.append((True, label, shown))
    native = _native_layout(files=False)
    if native is not None:
        from services import folder_layout

        ok, text = folder_layout.describe(native)
        out.append((ok, "folders", text))
    if copy.exists():
        out.append(
            (
                False,
                "leftover copy",
                f"{short_path(copy)} blocks the next update: keep what you need, then delete it",
            )
        )
    return out


def cmd_doctor(args=()):
    """fresh-install readiness check: deps, data dir, encryption key, provider, and the server."""
    from services import cli_ui

    ui = cli_ui.Style()
    ui.header("doctor")
    try:
        from services import doctor
    except Exception as e:
        ui.check(False, "checks", f"couldn't load: {e}")
        return False
    checks = doctor.run_all()
    folders = _folder_checks()
    width = max([len(c["label"]) for c in checks] + [len(f[1]) for f in folders]) + 2
    for c in checks:
        # a missing optional piece is a note, not a failure
        ok = True if c["ok"] else (False if c["label"] in doctor._HARD else None)
        detail = (str(c["detail"]).splitlines() or [""])[0]
        ui.check(ok, c["label"], detail[:140], width)
    for ok, label, detail in folders:
        ui.check(ok, label, detail, width)
    native = _native_layout()
    port = native.port if native is not None else _port()
    if native is not None or _port_open(port):
        healthy = _health_ok(port)
        ui.check(
            healthy, "server", "answering" if healthy else "not answering: alles status", width
        )
    hard_fail = [c for c in checks if not c["ok"] and c["label"] in doctor._HARD]
    hard_fail += [f for f in folders if f[0] is False]
    ui.say()
    if hard_fail:
        ui.say(f"  {ui.bad('not ready')}: fix the {ui.mark_bad} lines, then run alles doctor again")
        return False
    ui.say(f"  {ui.good('ready')}")
    return True


def _unix_bin_dirs():
    # ~/.local/bin first (no sudo), then /usr/local/bin (global, may need sudo)
    return [Path.home() / ".local" / "bin", Path("/usr/local/bin")]


def _cmd_install_launcher():
    """Compatibility path for a checkout-only launcher."""
    if IS_WIN:
        print("windows: this folder already has alles.cmd. to run it from anywhere,")
        print("add this folder to your PATH:")
        print(f"  {ROOT}")
        return False

    py = sys.executable or "python3"
    cli = ROOT / "cli.py"

    chosen = None
    for d in _unix_bin_dirs():
        try:
            d.mkdir(parents=True, exist_ok=True)
            t = d / ".alles_write_test"
            t.write_text("x")
            t.unlink()
            chosen = d
            break
        except Exception:
            continue  # not writable (e.g. /usr/local/bin without sudo) — try next

    if not chosen:
        print("no writable bin dir on PATH. install it yourself with sudo:")
        print("  sudo tee /usr/local/bin/alles >/dev/null <<EOF")
        print("  #!/usr/bin/env bash")
        print(f'  exec "{py}" "{cli}" "$@"')
        print("  EOF")
        print("  sudo chmod +x /usr/local/bin/alles")
        return False

    launcher = chosen / "alles"
    launcher.write_text(f'#!/usr/bin/env bash\nexec "{py}" "{cli}" "$@"\n')
    launcher.chmod(0o755)
    print(f"installed launcher: {launcher}")
    print(f"  -> {py} {cli}")

    on_path = str(chosen) in os.environ.get("PATH", "").split(os.pathsep)
    if on_path:
        print("\nready — run it from anywhere:  alles start")
    else:
        rc = "~/.zshrc" if os.environ.get("SHELL", "").endswith("zsh") else "~/.bashrc"
        print(f"\n{chosen} isn't on your PATH yet. add it once:")
        print(f"  echo 'export PATH=\"{chosen}:$PATH\"' >> {rc} && source {rc}")
        print("then:  alles start")
    return True


def _native_install_probe(release: Path, python: Path) -> "ProbeResult":
    import tempfile

    from services import native_install

    try:
        log_dir = _boot_log_dir(native_install.platform_layout().data_root)
    except native_install.NativeInstallError:
        log_dir = None
    with tempfile.TemporaryDirectory(prefix="alles-native-install-probe-") as directory:
        return _run_recovery_probe(
            Path(directory),
            passes=2,
            app_root=release,
            python_path=python,
            log_dir=log_dir,
        )


_INSTALL_STEPS = {
    "folders": "folders",
    "copy": "app files",
    "environment": "python environment",
    "packages": "python packages",
    "check": "startup check",
    "service": "background service",
    "linger": "runs after logout",
}


def _install_source_from_env() -> dict | None:
    """install.sh names the exact github archive it downloaded, so updates can follow it."""
    repository, branch, commit = (
        os.environ.get(f"ALLES_INSTALL_{key}", "").strip()
        for key in ("REPOSITORY", "BRANCH", "COMMIT")
    )
    if repository and branch and commit:
        return {
            "kind": "archive",
            "repository": repository,
            "branch": branch,
            "commit": commit.lower(),
        }
    return None


def _wait_for_health(port: int, seconds: float = 45) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _health_ok(port):
            return True
        time.sleep(0.5)
    return False


def _shell_rc() -> Path:
    shell = Path(os.environ.get("SHELL", "")).name
    home = Path.home()
    if shell == "zsh":
        return home / ".zshrc"
    if shell == "bash":
        return home / ".bashrc"
    return home / ".profile"


def _put_launcher_on_path(launcher: Path) -> Path | None:
    """Add the launcher's folder to PATH for new shells. Returns the file changed, if any."""
    folder = launcher.parent
    entries = [
        Path(entry).expanduser() for entry in os.environ.get("PATH", "").split(os.pathsep) if entry
    ]
    if any(entry == folder for entry in entries):
        return None
    rc = _shell_rc()
    try:
        current = rc.read_text("utf-8") if rc.exists() else ""
    except OSError:
        return None
    if ".local/bin" in current:
        return None
    line = 'export PATH="$HOME/.local/bin:$PATH"'
    with rc.open("a", encoding="utf-8") as handle:
        handle.write(
            ("" if current.endswith("\n") or not current else "\n")
            + f"\n# added by the alles installer\n{line}\n"
        )
    return rc


def _ask(ui, question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(f"  {question} [y/N] ")
    except (EOFError, KeyboardInterrupt):
        ui.say()
        return False
    return answer.strip().lower() in {"y", "yes"}


def _offer_aide_tools(ui, launcher: Path) -> None:
    """oct 27: node comes with alles; pi and aide's browser are offered here and in alles tools."""
    try:
        subprocess.call([str(launcher), "tools", "install", "node"])
        if _ask(ui, "install pi (aide's coding helper) and aide's browser too? about 300 MB"):
            subprocess.call([str(launcher), "tools", "install", "pi", "browser"])
            return
    except OSError as exc:
        ui.check(None, "aide's tools", f"not installed: {exc}")
    ui.say(ui.dim("  later: alles tools install"))


def _old_launcher_checkout(launcher: Path) -> str | None:
    """The checkout an older `alles install --launcher-only` command runs, or None."""
    import re

    try:
        if launcher.is_symlink() or not launcher.is_file():
            return None
        text = launcher.read_text("utf-8")
    except (OSError, UnicodeError):
        return None
    found = re.fullmatch(r'#!/usr/bin/env bash\nexec "[^"\n]+" "([^"\n]+)/cli\.py" "\$@"\n', text)
    return found.group(1) if found else None


def cmd_install(args=()):
    """Install alles as a background service on macOS or Linux, one step per line."""
    args = tuple(args)
    if args in (("launcher",), ("--launcher-only",)):
        return _cmd_install_launcher()
    if args:
        print("usage:  alles install  |  alles install --launcher-only")
        return False
    if IS_WIN:
        print("the installer supports macOS and Linux")
        return False
    from services import cli_ui, native_install

    ui = cli_ui.Style()
    source = _install_source_from_env()
    if source is None:  # install.sh already printed the header and its download line
        ui.header("install")
    steps = cli_ui.Steps(_INSTALL_STEPS, ui)
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if sys.version_info < (3, 11):
        ui.check(False, f"python {version}", "alles needs python 3.11 or newer", steps.width)
        return False
    ui.check(True, f"python {version}", "", steps.width)
    # install.sh names the folder it was started in; on another drive, the install goes there
    started_in = os.environ.get("ALLES_INSTALL_FROM", "").strip()
    if started_in and not os.environ.get("ALLES_HOME", "").strip():
        on_drive = native_install.drive_install_home(Path(started_in))
        if on_drive is not None:
            os.environ["ALLES_HOME"] = str(on_drive)
            ui.check(True, "folder", f"{on_drive}  (the drive you're in)", steps.width)
    try:
        layout = native_install.platform_layout()
        native_install.check_install_home(layout)
    except native_install.NativeInstallError as exc:
        steps.fail(f"stopped safely: {exc}")
        steps.close()
        return False
    aside = None
    old = _old_launcher_checkout(layout.launcher)
    if old is not None:
        where = cli_ui.short_path(layout.launcher)
        ui.say(f"  {where} is an older alles command that runs {cli_ui.short_path(old)}")
        if not _ask(ui, "replace it with this install's alles command?"):
            ui.check(
                False, "alles command", f"kept: move {where} away, then install again", steps.width
            )
            return False
        aside = layout.launcher.with_name(".alles-before-install")
        os.replace(layout.launcher, aside)
    installed = False
    try:
        # the installer registers the service under the install's own data folder, not this checkout
        os.environ["ALLES_DATA"] = str(layout.data_root)
        result = native_install.install(
            ROOT,
            layout,
            release_probe=_native_install_probe,
            install_source=source,
            progress=steps.handle,
        )
        installed = True
    except native_install.NativeInstallError as exc:
        steps.fail(f"stopped safely: {exc}")
        return False
    except KeyboardInterrupt:
        steps.fail("stopped: nothing was left half-installed")
        return False
    finally:
        steps.close()
        if aside is not None:
            if installed:
                aside.unlink(missing_ok=True)
            elif not layout.launcher.exists():
                os.replace(aside, layout.launcher)

    port, _ = _native_service_endpoint(layout)
    running = _wait_for_health(port)
    changed_rc = _put_launcher_on_path(layout.launcher)
    ui.say()
    if running:
        ui.say(f"  {ui.good(ui.mark_ok)} {ui.bold('alles is running')}")
    else:
        ui.say(
            f"  {ui.warn(ui.mark_warn)} {ui.bold('alles is still starting')}  {ui.dim('check with: alles status')}"
        )
    ui.say()
    ui.rows(
        [
            ("open", f"http://localhost:{port}"),
            ("settings", cli_ui.short_path(result.get("config_file") or "")),
            ("data", cli_ui.short_path(result["data_root"])),
        ]
    )
    ui.say()
    if layout.manager == "launchd":
        ui.say(
            ui.dim("  it keeps running after you close this terminal and starts when you log in.")
        )
    elif result.get("keeps_running"):
        ui.say(
            ui.dim(
                "  it keeps running after you close this terminal and starts again after a restart."
            )
        )
    else:
        ui.say(
            ui.dim("  it stops when you log out until you run: sudo loginctl enable-linger $USER")
        )
    if changed_rc is not None:
        ui.say(
            ui.dim(
                f"  the alles command works in new terminals ({cli_ui.short_path(changed_rc)} was updated)."
            )
        )
    ui.say()
    ui.rows(list(_EVERYDAY))
    ui.say()
    _offer_aide_tools(ui, layout.launcher)
    # the owner's order: installed first, then a password if they want one, then other devices
    if _ask(ui, "set a password for alles? it's optional while only this computer opens it"):
        subprocess.call([str(layout.launcher), "password"])
    if _ask(ui, "open alles from your phone or another computer too?"):
        subprocess.call([str(layout.launcher), "access", "lan"])
    return True


def _reachable_addresses() -> list[tuple[str, str]]:
    """Addresses other devices can use: tailscale's name and ip, then this network's ip."""
    import json

    found: list[tuple[str, str]] = []
    try:
        status = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        me = json.loads(status.stdout or "{}").get("Self") or {}
        name = str(me.get("DNSName") or "").rstrip(".")
        if name:
            found.append((name, "tailscale"))
        for ip in me.get("TailscaleIPs") or []:
            if ":" not in ip:
                found.append((ip, "tailscale"))
                break
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    try:
        # a udp "connect" sends nothing; it only picks the outgoing interface
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            ip = probe.getsockname()[0]
        if not ip.startswith("127.") and all(ip != known for known, _ in found):
            found.append((ip, "this network"))
    except OSError:
        pass
    return found


def _restart_for_settings(native) -> bool:
    if native is not None:
        from services import service_manager

        try:
            service_manager.control("server", "restart")
        except (service_manager.ServiceControlError, service_manager.ServiceOwnershipError):
            return False
        return _wait_for_health(native.port, 30)
    if _running(_pid()):
        return bool(cmd_restart())
    return False


def _prompt_owner_password(ui, width) -> bool:
    """ask for the owner password twice in the terminal and turn the lock on"""
    import getpass

    from core.auth import MIN_OWNER_PASSWORD_LENGTH, hash_password
    from core.settings import save_settings

    if not sys.stdin.isatty():
        ui.check(False, "owner password", "run this in a terminal so it can ask for one", width)
        return False
    ui.say(ui.dim(f"  choose an owner password, {MIN_OWNER_PASSWORD_LENGTH} characters or more"))
    while True:
        try:
            first = getpass.getpass("  password: ")
            second = getpass.getpass("  again:    ")
        except (EOFError, KeyboardInterrupt):
            ui.say()
            return False
        if len(first) < MIN_OWNER_PASSWORD_LENGTH:
            ui.say(ui.warn(f"  too short: {MIN_OWNER_PASSWORD_LENGTH} characters or more"))
        elif first != second:
            ui.say(ui.warn("  those didn't match, try again"))
        else:
            break
    save_settings({"auth_password_hash": hash_password(first), "auth_enabled": True})
    ui.check(True, "owner password", "set", width)
    return True


def cmd_password(args=()):
    """Set or change the owner password. it's optional while only this computer opens alles."""
    from services import cli_ui

    ui = cli_ui.Style()
    ui.header("password")
    try:
        ok = _prompt_owner_password(ui, 24)
    except ImportError:
        ui.say(
            "  run this with the installed alles command, or inside the alles python environment"
        )
        return False
    if ok:
        _restart_for_settings(_native_layout())
    return ok


def cmd_access(args=()):
    """alles access lan | device: who can open alles. alles access domain: at which address."""
    from services import cli_ui

    ui = cli_ui.Style()
    choice = args[0] if args else ""
    if choice == "domain":
        return _access_domain(list(args[1:]), ui)
    if choice not in ("lan", "device"):
        ui.header("access")
        current = _access_label()
        if current:
            ui.rows([("now", current)], dim_value=True)
            ui.say()
        ui.rows(
            [
                (
                    "alles access lan",
                    "your phone and other computers can open it (asks for a password)",
                ),
                ("alles access device", "only this computer can open it"),
                (
                    "alles access domain alles.example.com",
                    "open it at your own domain, each app after a slash (add subdomain for docs.…)",
                ),
            ]
        )
        ui.say()
        return not args
    try:
        from core.settings import auth_enabled, load_settings, save_settings
    except ImportError:
        ui.say(
            "  run this with the installed alles command, or inside the alles python environment"
        )
        return False
    native = _native_layout()
    ui.header(f"access {choice}")
    width = 24
    if choice == "lan" and not auth_enabled():
        if load_settings().get("auth_password_hash"):
            save_settings({"auth_enabled": True})
            ui.check(True, "owner password", "turned back on", width)
        else:
            ui.say(
                ui.dim("  other devices need a password, so anyone on the network can't open it")
            )
            if not _prompt_owner_password(ui, width):
                return False
    save_settings(
        {
            "access_profile": choice,
            "public_url": "",
            "trusted_hosts": _domain_hosts(choice, load_settings()),
            "forwarded_allow_ips": "",
        }
    )
    restarted = _restart_for_settings(native)
    label = "open to other devices" if choice == "lan" else "this computer only"
    if restarted:
        ui.check(True, label, "alles restarted", width)
    else:
        ui.check(None, label, "saved; it applies when alles starts: alles start", width)
    if choice == "lan":
        addresses = _reachable_addresses()
        if addresses:
            ui.say()
            ui.say("  open it from your other devices")
            port = native.port if native is not None else _port()
            ui.rows([(f"http://{host}:{port}", where) for host, where in addresses], dim_value=True)
    ui.say()
    return True


def _domain_hosts(profile: str, settings: dict) -> str:
    """the trusted host list a profile needs for the bound domain. lan trusts every host, so it
    needs none; this computer only has to name the domain beside localhost, since the https proxy
    in front of alles hands it the domain's name."""
    domain = str(settings.get("base_domain") or "").strip().lower()
    if profile != "device" or not domain or domain == "localhost":
        return ""
    from core.server_config import _DEVICE_TRUSTED_HOSTS

    hosts = [*_DEVICE_TRUSTED_HOSTS, domain]
    if str(settings.get("app_urls") or "") == "subdomain":
        hosts.append(f"*.{domain}")
    return ",".join(hosts)


def _clean_domain(raw: str) -> str:
    from urllib.parse import urlsplit

    from core.server_config import AccessConfigError, _normalize_trusted_host

    text = raw.strip().lower()
    host = urlsplit(text if "://" in text else f"https://{text}").hostname or ""
    try:
        host = _normalize_trusted_host(host)
    except AccessConfigError:
        return ""
    return host if "." in host and not host.startswith("*") and host != "localhost" else ""


def _access_domain(args: list[str], ui) -> bool:
    """alles access domain <name> [path|subdomain] | off: the address your https proxy serves."""
    try:
        from core.server_config import access_profile
        from core.settings import load_settings, save_settings
    except ImportError:
        ui.say(
            "  run this with the installed alles command, or inside the alles python environment"
        )
        return False
    native = _native_layout()
    port = native.port if native is not None else _port()
    settings = load_settings()
    current = str(settings.get("base_domain") or "")
    current = "" if current == "localhost" else current
    width = 24
    if not args:
        ui.header("access domain")
        if current:
            mode = settings.get("app_urls") or "path"
            ui.rows([("now", f"{current}, apps on {mode}s")], dim_value=True)
            ui.say()
        ui.rows(
            [
                (
                    "alles access domain alles.example.com",
                    "apps after a slash: alles.example.com/docs",
                ),
                (
                    "alles access domain alles.example.com subdomain",
                    "apps on subdomains: docs.alles.example.com",
                ),
                ("alles access domain off", "forget the domain"),
            ]
        )
        ui.say()
        return True
    if args[0] == "off":
        ui.header("access domain off")
        settings = {**settings, "base_domain": "", "app_urls": ""}
        trusted = _domain_hosts(access_profile(), settings)
        save_settings({"base_domain": "", "app_urls": "", "trusted_hosts": trusted})
        restarted = _restart_for_settings(native)
        ui.check(
            True if restarted else None,
            "domain",
            "forgotten" if restarted else "forgotten; it applies when alles starts",
            width,
        )
        ui.say()
        return True
    domain = _clean_domain(args[0])
    mode = args[1] if len(args) > 1 else "path"
    if not domain or mode not in ("path", "subdomain") or len(args) > 2:
        ui.say("  usage: alles access domain alles.example.com [path|subdomain]")
        return False
    ui.header(f"access domain {domain}")
    profile = access_profile()
    patch = {"base_domain": domain, "app_urls": mode}
    if profile == "public":
        # public access already names its hosts; the domain joins them
        hosts = [h for h in str(settings.get("trusted_hosts") or "").split(",") if h.strip()]
        hosts += [
            h
            for h in (domain, f"*.{domain}" if mode == "subdomain" else "")
            if h and h not in hosts
        ]
        patch["trusted_hosts"] = ",".join(hosts)
    else:
        patch["trusted_hosts"] = _domain_hosts(profile, {**settings, **patch})
    save_settings(patch)
    restarted = _restart_for_settings(native)
    ui.check(
        True if restarted else None,
        "domain",
        "alles restarted" if restarted else "saved; it applies when alles starts: alles start",
        width,
    )
    ui.say()
    ui.say(
        f"  point {domain}{' and *.' + domain if mode == 'subdomain' else ''} at this computer, and have"
    )
    ui.say(
        f"  your https proxy (caddy, nginx, cloudflare tunnel) send it to http://127.0.0.1:{port}"
    )
    ui.say()
    if mode == "path":
        ui.rows(
            [(f"https://{domain}", "home"), (f"https://{domain}/docs", "every app after a slash")],
            dim_value=True,
        )
    else:
        ui.rows(
            [
                (f"https://{domain}", "home"),
                (f"https://docs.{domain}", "every app on its own subdomain"),
            ],
            dim_value=True,
        )
    ui.say()
    return True


def cmd_config(args=()):
    """Open the settings file in an editor; `alles config path` prints where it is."""
    import shlex

    from services import cli_ui

    native = _native_layout(files=False)
    path = _settings_path(native)
    if args and args[0] == "path":
        print(path)
        return True
    if not path.exists():
        if native is not None:
            from services import native_install

            native_install._write_settings_file(native)
        else:
            example = ROOT / ".env.example"
            path.write_text(example.read_text("utf-8") if example.exists() else "", "utf-8")
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        editor = next((name for name in ("nano", "vi") if _which(name)), "")
    ui = cli_ui.Style()
    if not editor or not sys.stdin.isatty():
        ui.say(str(path))
        return True
    subprocess.call([*shlex.split(editor), str(path)])
    ui.say(ui.dim("  changed something? run  alles restart  to use it"))
    return True


def _which(name: str) -> bool:
    import shutil

    return shutil.which(name) is not None


def _legacy_launcher_source() -> str:
    py = sys.executable or "python3"
    return f'#!/usr/bin/env bash\nexec "{py}" "{ROOT / "cli.py"}" "$@"\n'


def _cmd_uninstall_launcher():
    """Remove only a launcher whose exact content belongs to this checkout."""
    if IS_WIN:
        print("windows: remove this folder from your PATH manually.")
        return False
    removed = []
    for d in _unix_bin_dirs():
        p = d / "alles"
        try:
            if p.is_symlink():
                print(f"refusing to remove symlinked launcher: {p}")
                continue
            if p.is_file() and p.read_text("utf-8") == _legacy_launcher_source():
                p.unlink()
                removed.append(str(p))
        except Exception as e:
            print(f"couldn't remove {p}: {e}")
    print("removed: " + ", ".join(removed) if removed else "nothing owned to remove")
    return bool(removed)


def cmd_uninstall(args=()):
    """Remove verified native program files while keeping personal data."""
    args = tuple(args)
    if args in (("launcher",), ("--launcher-only",)):
        return _cmd_uninstall_launcher()
    if args:
        print("usage:  alles uninstall  |  alles uninstall --launcher-only")
        return False
    if IS_WIN:
        print("the native uninstaller currently supports macOS and Linux")
        return False
    from services import native_install

    try:
        result = native_install.uninstall_keep_data(native_install.platform_layout())
    except native_install.NativeInstallError as exc:
        print(f"native uninstall stopped safely: {exc}")
        return False
    print("alles program files and user service were removed")
    print(f"personal data kept at: {result['data_root']}")
    print(f"visible Vault kept at: {result['vault_kept']}")
    print(f"visible Files kept at: {result['files_kept']}")
    return True


def _atomic_private_bytes(path: Path, content: bytes | None) -> None:
    """Replace one recovery-side file without exposing partial contents."""
    import uuid

    if content is None:
        path.unlink(missing_ok=True)
        try:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.partial"
    try:
        with temp.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        os.replace(temp, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    finally:
        temp.unlink(missing_ok=True)


RECOVERY_PROBE_TIMEOUT_SECONDS = 120.0


class ProbeResult:
    """A boot check's answer: truthy when healthy, else the real error and where its log went."""

    def __init__(self, ok: bool, error: str = "", log: Path | None = None):
        self.ok, self.error, self.log = ok, error, log

    def __bool__(self) -> bool:
        return self.ok

    def explain(self, what: str) -> str:
        text = what + (f"\n{self.error}" if self.error else "")
        return text + (f"\nfull log: {_short_path(self.log)}" if self.log else "")


def _probe_error(output: str, exit_code: int | None, timeout: float) -> str:
    """The line that says why: a traceback's last line, else the last thing it printed."""
    import re

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if re.match(r"^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt)\b.*", line):
            return line[:300]
    if exit_code is None:
        return f"no healthy answer within {int(timeout)}s"
    tail = lines[-1][:300] if lines else "no output"
    return f"exited with code {exit_code}: {tail}"


def _save_probe_log(log_dir: Path, output: bytes) -> Path | None:
    from datetime import datetime

    try:
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = log_dir / f"boot-check-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        path.write_bytes(output)
        path.chmod(0o600)
        return path
    except OSError:
        return None


def _recovery_probe_once(
    candidate: Path,
    *,
    timeout: float = RECOVERY_PROBE_TIMEOUT_SECONDS,
    app_root: Path | None = None,
    python_path: Path | None = None,
    log_dir: Path | None = None,
) -> ProbeResult:
    """Boot only init/migrations + /health against isolated candidate data.

    Recovery can include every pending migration on a cold disk. Keep the
    allowance bounded, but do not reject a healthy candidate merely because
    a cold or resource-constrained host needs longer than one minute.
    """
    import json
    import tempfile
    import urllib.error
    import urllib.request

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

    code_root = (app_root or ROOT).expanduser().resolve()
    if not (code_root / "app.py").is_file():
        return ProbeResult(False, f"{code_root / 'app.py'} is missing")
    env = os.environ.copy()
    env.update(
        {
            "ALLES_DATA": str(candidate),
            "ALLES_DB": str(candidate / "aide.db"),
            "ALLES_HOST": "127.0.0.1",
            # the check listens on loopback only, so a lan or public install's password rule
            # doesn't apply; without this every shared install failed its update check
            "ALLES_ACCESS_PROFILE": "device",
            "ALLES_RECOVERY_PREFLIGHT": "1",
            "AUTH_ENABLED": "false",
            "PORT": str(port),
            "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONUNBUFFERED": "1",
            # a published release is checked file by file; bytecode would change it
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    env.pop("ALLES_RELOAD", None)
    env.pop("ALLES_NATIVE_ROOT", None)
    env.pop("PYTHONPATH", None)
    python = str(python_path) if python_path is not None else (sys.executable or "python3")
    candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(
            [python, str(code_root / "app.py")],
            cwd=code_root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        healthy = False
        try:
            deadline = time.time() + timeout
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/health", timeout=0.5
                    ) as response:
                        body = json.loads(response.read().decode("utf-8"))
                    if response.status == 200 and body.get("ok") is True and proc.poll() is None:
                        healthy = True
                        break
                except (
                    OSError,
                    UnicodeError,
                    ValueError,
                    urllib.error.URLError,
                ):
                    pass
                time.sleep(0.2)
        finally:
            exit_code = proc.poll()
            if exit_code is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        if healthy:
            return ProbeResult(True)
        log.seek(0)
        output = log.read()
    error = _probe_error(output.decode("utf-8", "replace"), exit_code, timeout)
    saved = _save_probe_log(log_dir, output) if log_dir is not None else None
    return ProbeResult(False, error, saved)


def _run_recovery_probe(
    candidate: Path,
    *,
    passes: int,
    app_root: Path | None = None,
    python_path: Path | None = None,
    log_dir: Path | None = None,
) -> ProbeResult:
    result = ProbeResult(True)
    for _ in range(passes):
        result = _recovery_probe_once(
            candidate, app_root=app_root, python_path=python_path, log_dir=log_dir
        )
        if not result:
            break
    return result


def _probe_failure(result, what: str) -> str:
    """Works for a ProbeResult and for a plain False from older callers and test doubles."""
    explain = getattr(result, "explain", None)
    return explain(what) if explain else what


def _update_coverage_issues(staged) -> list[str]:
    """an update swaps the data folder and never writes to an outside files folder, so it can
    roll back without a copy of it (owner's call, oct 28). a restore keeps the full check."""
    return [role for role in _coverage_issues(staged) if role != "files"]


def _coverage_issues(staged) -> list[str]:
    import sqlite3
    from contextlib import closing

    locations = {item["role"]: item for item in staged.manifest["locations"]}
    issues = [role for role in ("vault", "files") if not locations.get(role, {}).get("included")]
    if not locations.get("photos", {}).get("included"):
        uri = f"{(staged.data_dir / 'aide.db').resolve().as_uri()}?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True)) as conn:
                have_photos = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='photos'"
                ).fetchone()
                if have_photos and conn.execute("SELECT 1 FROM photos LIMIT 1").fetchone():
                    issues.append("photos")
        except sqlite3.Error:
            issues.append("photos")
    return issues


def _prepare_staged_candidate(
    staged,
    live_root: Path,
    *,
    app_root: Path | None = None,
    python_path: Path | None = None,
    keep_outside_vault: bool = False,
) -> None:
    """Remap configured file roots into staging, boot twice, then set final paths."""
    import json
    import shutil

    settings_path = staged.data_dir / "settings.json"
    if settings_path.is_symlink():
        raise RuntimeError("staged settings.json cannot be a link")
    original_bytes = settings_path.read_bytes() if settings_path.is_file() else None
    try:
        original = json.loads(original_bytes.decode("utf-8")) if original_bytes else {}
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("staged settings.json is invalid") from exc
    if not isinstance(original, dict):
        raise RuntimeError("staged settings.json must contain an object")

    locations = {item["role"]: item for item in staged.manifest["locations"]}
    applied = staged.manifest["database"]["applied_migrations"]
    schema_version = applied[-1]["version"] if applied else 0
    if schema_version < 10 and not locations.get("vault", {}).get("included"):
        raise RuntimeError("this older backup needs its vault included before safe migration")

    keys = {"vault": "vault_dir", "files": "files_dir", "photos": "photos_dir"}
    isolated = dict(original)
    final = dict(original)
    outside_copy = None
    for role, key in keys.items():
        location = locations.get(role, {})
        if location.get("included") and location.get("storage") == "data":
            subpath = location.get("subpath")
            if not isinstance(subpath, str) or not subpath:
                raise RuntimeError(f"included {role} location is invalid")
            isolated[key] = str((staged.data_dir / subpath).resolve())
            # an update never writes to an outside vault, so it stays the live one and the
            # backup's copy is only for the boot check (a restore uses the copy instead)
            if keep_outside_vault and location.get("policy") == "external-captured":
                outside_copy = staged.data_dir / subpath
            elif key in original:
                final[key] = str((live_root / subpath).resolve())
        else:
            isolated.pop(key, None)

    isolated_bytes = json.dumps(isolated, ensure_ascii=False, indent=2, allow_nan=False).encode(
        "utf-8"
    )
    if original_bytes is None:
        final_bytes = None
    elif final == original:
        # Do not rewrite harmless formatting or key order when recovery did not change a path.
        final_bytes = original_bytes
    else:
        final_bytes = json.dumps(final, ensure_ascii=False, indent=2, allow_nan=False).encode(
            "utf-8"
        )
    _atomic_private_bytes(settings_path, isolated_bytes)
    try:
        log_dir = _boot_log_dir(live_root)
        if app_root is None:
            healthy = _run_recovery_probe(staged.data_dir, passes=2, log_dir=log_dir)
        else:
            healthy = _run_recovery_probe(
                staged.data_dir,
                passes=2,
                app_root=app_root,
                python_path=python_path,
                log_dir=log_dir,
            )
        if not healthy:
            raise RuntimeError(
                _probe_failure(healthy, "a copy of your data failed its migration and boot check")
            )
    except Exception:
        _atomic_private_bytes(settings_path, original_bytes)
        raise
    _atomic_private_bytes(settings_path, final_bytes)
    if outside_copy is not None:
        shutil.rmtree(outside_copy)


def _restore_server_state() -> bool:
    """Return whether the verified server is running; reject unknown ownership."""
    pid = _pid()
    if _running(pid):
        if _alles_process(pid) is None:
            raise RuntimeError(f"pid {pid} is not a verified Alles process")
        return True
    if _port_open():
        raise RuntimeError(f"port {_port()} is busy with an unknown process")
    PID_FILE.unlink(missing_ok=True)
    return False


def _stop_for_restore() -> bool:
    pid = _pid()
    if _running(pid):
        if _alles_process(pid) is None:
            return False
        return bool(cmd_stop())
    if _port_open():
        return False
    PID_FILE.unlink(missing_ok=True)
    return True


def _restart_original_if_needed(was_running: bool) -> bool:
    if not was_running:
        return True
    return bool(cmd_start())


def _apply_staged_restore(restore_id: str, *, allow_partial: bool) -> bool:
    if os.environ.get("ALLES_DB"):
        print("restore is disabled while ALLES_DB overrides the database path")
        print("use one database under ALLES_DATA before applying a whole-data restore")
        return False

    from services.backup_recovery import (
        RecoveryError,
        refresh_prepared_recovery,
        verify_staged_recovery,
    )
    from services.instance_lock import InstanceLock, InstanceLockError
    from services.restore_apply import (
        RestoreApplyError,
        begin_manual_rollback,
        begin_restore_operation,
        complete_restore_operation,
        mark_restore_state,
        rollback_restore_operation,
        swap_in_staged,
    )

    live = _runtime_dir().expanduser().resolve()
    try:
        was_running = _restore_server_state()
        staged = verify_staged_recovery(live, restore_id)
        issues = _coverage_issues(staged)
        if issues and not allow_partial:
            joined = ", ".join(issues)
            print(f"this backup does not contain all selected data: {joined}")
            print("make a complete backup, or repeat with --allow-partial if that is intentional")
            return False
        if staged.state != "prepared":
            print("checking the staged copy twice before stopping Alles…")
            _prepare_staged_candidate(staged, live)
            staged = refresh_prepared_recovery(live, restore_id)
        staged = verify_staged_recovery(live, restore_id)
    except (RecoveryError, RuntimeError, OSError) as exc:
        print(f"restore preflight failed: {exc}")
        print("live data was not changed")
        return False

    if not _stop_for_restore():
        print("could not stop a verified Alles instance; live data was not changed")
        return False

    owner_lock = InstanceLock(live)
    operation = None
    try:
        owner_lock.acquire()
        operation = begin_restore_operation(live, restore_id)
        mark_restore_state(operation, "candidate_ready")
        swap_in_staged(operation, staged.data_dir)
    except (InstanceLockError, RestoreApplyError, OSError) as exc:
        print(f"restore swap stopped safely: {exc}")
        owner_lock.release()
        _restart_original_if_needed(was_running)
        return False
    owner_lock.release()

    probe = _run_recovery_probe(live, passes=1, log_dir=_boot_log_dir(live))
    if not probe:
        print(_probe_failure(probe, "the restored copy failed its health check"))
        print("restoring the original data…")
        try:
            owner_lock.acquire()
            rollback_restore_operation(operation, reason="installed-health-check-failed")
        except (InstanceLockError, RestoreApplyError, OSError) as exc:
            print(f"automatic rollback needs help: {exc}")
            print("run:  alles restore recover")
            return False
        finally:
            owner_lock.release()
        _restart_original_if_needed(was_running)
        print("original data restored; the failed candidate was kept for diagnosis")
        return False

    try:
        complete_restore_operation(operation)
    except RestoreApplyError as exc:
        print(f"restore health passed but final bookkeeping failed: {exc}")
        print("run:  alles restore recover")
        return False

    if was_running and not cmd_start():
        print("normal startup failed after restore — rolling back to the original data…")
        cmd_stop()
        try:
            owner_lock.acquire()
            manual = begin_manual_rollback(live, operation.operation_id)
            rollback_restore_operation(manual, reason="normal-startup-failed")
        except (InstanceLockError, RestoreApplyError, OSError) as exc:
            print(f"automatic rollback needs help: {exc}")
            print("run:  alles restore recover")
            return False
        finally:
            owner_lock.release()
        cmd_start()
        return False

    print(f"restore applied safely  operation={operation.operation_id}")
    print(f"rollback kept:  alles restore rollback {operation.operation_id}")
    if not was_running:
        print("Alles was stopped before restore, so it was left stopped")
    return True


def _stage_backup_from_cli(backup_name: str, options: list[str]) -> bool:
    import hmac
    import uuid

    from services.backup_recovery import (
        RecoveryError,
        stage_recovery_archive,
        staging_root,
    )
    from services.recovery_crypto import (
        decrypt_recovery_container,
        is_encrypted_recovery,
        load_recovery_key,
        recovery_key_path,
    )

    key_name = None
    index = 0
    while index < len(options):
        if options[index] != "--key" or index + 1 >= len(options) or key_name is not None:
            print("invalid stage options; use: --key <recovery-key-file>")
            return False
        key_name = options[index + 1]
        index += 2

    raw_live = _runtime_dir().expanduser()
    is_junction = getattr(raw_live, "is_junction", None)
    if raw_live.is_symlink() or bool(is_junction and is_junction()):
        print("ALLES_DATA cannot be a link during recovery staging")
        return False
    live = raw_live.resolve()
    live.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(backup_name).expanduser()
    incoming = staging_root(live) / "incoming"
    incoming.mkdir(parents=True, exist_ok=True, mode=0o700)
    decrypted = incoming / f"cli-{uuid.uuid4().hex}.zip"
    try:
        archive = backup
        if is_encrypted_recovery(backup):
            key_path = Path(key_name).expanduser() if key_name else recovery_key_path(live)
            key = load_recovery_key(key_path)
            decrypt_recovery_container(backup, decrypted, key)
            archive = decrypted
        staged = stage_recovery_archive(archive, live)
        if is_encrypted_recovery(backup):
            try:
                restored_key = load_recovery_key(staged.data_dir / "recovery.key")
                if not hmac.compare_digest(restored_key, key):
                    raise RecoveryError(
                        "backup recovery key does not match its encrypted container"
                    )
            except RecoveryError:
                from services.backup_recovery import discard_staged_recovery

                discard_staged_recovery(live, staged.restore_id)
                raise
    except (RecoveryError, OSError) as exc:
        print(f"backup staging failed: {exc}")
        return False
    finally:
        decrypted.unlink(missing_ok=True)
    print(f"backup verified and staged  restore_id={staged.restore_id}")
    print(f"next:  alles restore apply {staged.restore_id}")
    return True


def _recover_restore() -> bool:
    from services.instance_lock import InstanceLock, InstanceLockError
    from services.restore_apply import RestoreApplyError, recover_interrupted_restore

    live = _runtime_dir().expanduser().resolve()
    try:
        was_running = _restore_server_state()
    except RuntimeError as exc:
        print(f"restore recovery refused: {exc}")
        return False
    if was_running and not cmd_stop():
        print("could not stop the verified Alles process")
        return False
    owner_lock = InstanceLock(live)
    try:
        owner_lock.acquire()
        result = recover_interrupted_restore(live)
    except (InstanceLockError, RestoreApplyError, OSError) as exc:
        print(f"restore recovery failed safely: {exc}")
        return False
    finally:
        owner_lock.release()
    print(f"restore recovery finished: {result['status']}")
    return _restart_original_if_needed(was_running)


def _rollback_completed_restore(operation_id: str) -> bool:
    from services.instance_lock import InstanceLock, InstanceLockError
    from services.restore_apply import (
        RestoreApplyError,
        begin_manual_rollback,
        rollback_restore_operation,
    )

    live = _runtime_dir().expanduser().resolve()
    try:
        was_running = _restore_server_state()
    except RuntimeError as exc:
        print(f"rollback refused: {exc}")
        return False
    if was_running and not cmd_stop():
        print("could not stop the verified Alles process")
        return False
    owner_lock = InstanceLock(live)
    try:
        owner_lock.acquire()
        operation = begin_manual_rollback(live, operation_id)
        rollback_restore_operation(operation, reason="manual-rollback")
    except (InstanceLockError, RestoreApplyError, OSError) as exc:
        print(f"rollback failed safely: {exc}")
        return False
    finally:
        owner_lock.release()
    print("previous data restored; the replaced candidate was kept for diagnosis")
    return _restart_original_if_needed(was_running)


def cmd_restore(args=()):
    args = list(args)
    if not args:
        print("usage: alles restore apply <restore-id> [--allow-partial]")
        print("       alles restore stage <backup> [--key <recovery-key-file>]")
        print("       alles restore recover")
        print("       alles restore rollback <operation-id>")
        return False
    action = args[0]
    if action == "apply" and len(args) >= 2:
        return _apply_staged_restore(args[1], allow_partial="--allow-partial" in args[2:])
    if action == "stage" and len(args) >= 2:
        return _stage_backup_from_cli(args[1], args[2:])
    if action == "recover" and len(args) == 1:
        return _recover_restore()
    if action == "rollback" and len(args) == 2:
        return _rollback_completed_restore(args[1])
    print("invalid restore command; run `alles restore` for usage")
    return False


def cmd_test(args=()):
    """run the test suites — python (unittest) + js (node:test). pass `py` or `js` to scope."""
    import subprocess

    which = args[0] if args else "all"
    rc = 0
    if which in ("all", "py"):
        print("• python tests")
        rc |= subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", "tests"])
    if which in ("all", "js"):
        print("• js tests")
        from pathlib import Path

        # pass files explicitly — `node --test <dir>` mis-reports on windows
        js = sorted(str(p) for p in Path("tests/js").glob("*.test.mjs"))
        if js:
            rc |= subprocess.call(["node", "--test", *js])
        else:
            print("  (no js tests)")
    sys.exit(1 if rc else 0)


_AIDE_TOOLS = ("node", "pi", "browser")  # node first: pi needs it


def _install_tool(dep_id: str) -> None:
    """Install one of aide's tools in this process (the server does the same in the background)."""
    import asyncio

    from services import dependencies

    if dep_id == "pi":
        from services import pi_agent

        asyncio.run(pi_agent._run_install("pi"))
        error = pi_agent._install["pi"].get("error")
        if error:
            raise dependencies.DependencyError(error)
        return
    dependencies._installers[dep_id]()


def cmd_tools(args=()):
    """alles tools: what aide can use and whether each is ready. alles tools install [name|all]."""
    import asyncio
    import shlex

    from services import cli_ui, dependencies

    ui = cli_ui.Style()
    args = list(args)
    installing = args[:1] == ["install"]
    wanted = [name for name in args[1:] if name != "all"] or list(_AIDE_TOOLS)
    unknown = [name for name in wanted if name not in dependencies.IDS]
    if unknown or (args and not installing):
        ui.say("usage:  alles tools  |  alles tools install [node|pi|browser|searxng|all]")
        return False
    ui.header("tools" if not installing else "tools install")
    steps = cli_ui.Steps({dep_id: dependencies.NAMES[dep_id] for dep_id in dependencies.IDS}, ui)
    ok = True
    missing = []
    for dep_id in dependencies.IDS if not installing else wanted:
        row = asyncio.run(dependencies.state(dep_id))
        ready = row["state"] == "ready"
        if not ready and dep_id in _AIDE_TOOLS:
            missing.append(dep_id)
        if not installing or ready or not row.get("can_install"):
            # not asked to install, already there, or it needs something first (pi needs node)
            mark = True if ready else (False if installing else None)
            ui.check(mark, row["name"], row.get("detail") or row["state"], steps.width)
            ok = ok and (ready or not installing)
            continue
        steps.start(dep_id, row.get("detail", ""))
        try:
            try:
                _install_tool(dep_id)
            except dependencies.DependencyError as exc:
                # a missing system package needs root: say the command, run it only on a yes
                if not (exc.fix and sys.stdin.isatty()):
                    raise
                steps.finish(None, dep_id, str(exc).split(":")[0])
                ui.say(f"    {ui.dim(shlex.join(exc.fix))}")
                if not _ask(ui, "run it now?") or subprocess.call(exc.fix) != 0:
                    ok = False
                    continue
                steps.start(dep_id, "again")
                _install_tool(dep_id)
        except Exception as exc:  # noqa: BLE001 - each tool says its own sentence
            steps.finish(False, dep_id, str(exc).splitlines()[0][:160])
            if getattr(exc, "fix", None):
                ui.say(f"    {ui.dim(shlex.join(exc.fix))}")
            ok = False
            continue
        row = asyncio.run(dependencies.state(dep_id))
        steps.finish(row["state"] == "ready", dep_id, row.get("detail") or row.get("error", ""))
        ok = ok and row["state"] == "ready"
    steps.close()
    if not installing:
        if missing:
            ui.say()
            ui.say(f"  {ui.dim('install them:')} alles tools install {' '.join(missing)}")
    ui.say()
    return ok


def cmd_version(args=()):
    """The release as its short commit, the same name the update screen and status use."""
    native = _native_layout(files=False)
    if native is not None:
        from services import native_install

        release = native_install.release_summary(native)
        short, when = release.get("short"), _local_time(release.get("installed_at"))
    else:
        short, when = (_git_value(["rev-parse", "HEAD"]) or "")[:7] or None, ""
    print(f"alles {short or 'unknown'}" + (f" (installed {when})" if when else ""))
    return True


def cmd_completion(args=()):
    """Tab completion for alles: eval "$(alles completion zsh)" in .zshrc (bash and fish too)."""
    shell = (list(args) or [Path(os.environ.get("SHELL", "zsh")).name])[0]
    names = " ".join(sorted(COMMANDS))
    scripts = {
        "zsh": f"#compdef alles\n_alles() {{ compadd {names} }}\ncompdef _alles alles",
        "bash": f"complete -W '{names}' alles",
        "fish": f"complete -c alles -f -n __fish_use_subcommand -a '{names}'",
    }
    if shell not in scripts:
        print("usage:  alles completion zsh|bash|fish")
        return False
    print(scripts[shell])
    return True


def _server_url() -> str:
    native = _native_layout(files=False)
    return f"http://127.0.0.1:{native.port if native is not None else _port()}"


def _chat_client():
    from services import cli_chat

    def ask_password():
        if not sys.stdin.isatty():
            return None
        import getpass

        return getpass.getpass("  owner password: ")

    return cli_chat.Client(_server_url(), ask_password)


def cmd_ask(args=()):
    """alles ask "question": one answer from aide, streamed, then back to the shell.

    hermes does this with `hermes chat -q` (hermes-agent 0.22.2+1885.g20acba0); alles gives it
    its own short word. A piped stdin is the question when no words are given.
    """
    from services import cli_chat, cli_ui

    question = " ".join(args).strip()
    if not question and not sys.stdin.isatty():
        question = sys.stdin.read().strip()
    if not question:
        print('usage:  alles ask "what is on my calendar today"', file=sys.stderr)
        return False
    ui = cli_ui.Style()
    client = _chat_client()
    printer = cli_chat.Printer(ui)
    session = None
    try:
        session = client.new_session(question[:60])
        client.turn(session, question, printer)
    except cli_chat.ChatError as exc:
        if session and not printer.wrote:
            client.drop(session)
        print(f"  {ui.bad(str(exc))}", file=sys.stderr)
        return False
    return True


def cmd_chat(args=()):
    """alles chat: talk with aide in one conversation until ctrl-d or /exit."""
    from services import cli_chat, cli_ui

    if not sys.stdin.isatty():
        return cmd_ask(args)
    ui = cli_ui.Style()
    ui.header("chat", (ui.dim("ctrl-d or /exit to leave"),))
    client = _chat_client()
    session = None
    prompt = f"{ui.accent('›')} "
    while True:
        try:
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return True
        if line in ("/exit", "/quit", "exit", "quit"):
            return True
        if not line:
            continue
        printer = cli_chat.Printer(ui)
        fresh = session is None
        try:
            if fresh:
                session = client.new_session(line[:60])
            print()
            client.turn(session, line, printer)
            print()
        except KeyboardInterrupt:
            print()
        except cli_chat.ChatError as exc:
            if fresh and session and not printer.wrote:
                client.drop(session)  # nothing answered yet: no empty conversation left behind
                session = None
            ui.say(f"  {ui.bad(str(exc))}")


def cmd_backup(args=()):
    """alles backup [-o file] [--photos]: an encrypted backup of everything, like the backup page.

    hermes has `hermes backup` (hermes_cli/subcommands/backup.py, 0.22.2+1885.g20acba0); this one
    writes the same encrypted file the backup page downloads, so `alles restore stage` reads it.
    """
    from datetime import datetime

    from core.settings import data_dir
    from services import cli_ui
    from services.backup_recovery import RecoveryError
    from services.encrypted_backup import create_encrypted_backup

    args = list(args)
    photos = "--photos" in args
    output = None
    for flag in ("-o", "--output"):
        if flag in args:
            index = args.index(flag)
            if index + 1 >= len(args):
                print("usage:  alles backup [-o file] [--photos]", file=sys.stderr)
                return False
            output = Path(args[index + 1]).expanduser()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"alles-backup-{stamp}.alles-backup"
    if output is None:
        output = Path.home() / name
    elif output.is_dir():
        output = output / name
    ui = cli_ui.Style()
    ui.header("backup")
    steps = cli_ui.Steps({"backup": "backup"}, ui)
    steps.start("backup", "with photos" if photos else "")
    try:
        create_encrypted_backup(data_dir().expanduser().resolve(), output, include_photos=photos)
    except (RecoveryError, OSError) as exc:
        steps.fail(f"backup stopped: {exc}")
        return False
    finally:
        steps.close()
    size = output.stat().st_size / 1_048_576
    steps.finish(True, "backup", f"{size:.1f} MB")
    ui.say()
    ui.rows(
        [
            ("file", cli_ui.short_path(output)),
            ("restore", "alles restore stage <file>"),
            ("elsewhere", "add --key <recovery key>: settings › backup shows it"),
        ],
        dim_value=True,
    )
    return True


def _dump_lines() -> list[tuple[str, str]]:
    """Facts about this install for a bug report. Names only: no keys, passwords or messages."""
    import platform

    from core.settings import auth_enabled, data_dir, load_settings

    native = _native_layout(files=False)
    rows: list[tuple[str, str]] = []
    if native is not None:
        from services import native_install

        summary = native_install.release_summary(native)
        rows.append(("release", f"{summary['short']} (native, {native.manager})"))
    else:
        commit = _git_value(["rev-parse", "--short", "HEAD"]) if (ROOT / ".git").exists() else None
        rows.append(("release", f"{commit or 'unknown'} (source checkout)"))
    rows.append(("os", f"{platform.system()} {platform.release()} {platform.machine()}"))
    rows.append(("python", platform.python_version()))
    try:
        settings = load_settings()
    except Exception as exc:  # the broken file is the finding
        settings = {}
        rows.append(("settings", f"can't be read: {type(exc).__name__}"))
    rows.append(("access", _access_label() or "unknown"))
    rows.append(("password", "on" if auth_enabled() else "off"))
    rows.append(("data", str(data_dir())))
    for key, label in (("vault_dir", "docs folder"), ("files_dir", "files folder")):
        rows.append((label, str(settings.get(key) or "default")))
    try:
        from core.database import ModelEndpoint, SessionLocal

        with SessionLocal() as db:  # the provider column only: keys stay encrypted and unread
            found = db.query(ModelEndpoint.provider_id).filter(ModelEndpoint.enabled.is_(True))
            kinds = sorted({provider or "custom" for (provider,) in found})
        rows.append(("providers", ", ".join(kinds) or "none"))
    except Exception as exc:
        rows.append(("providers", f"can't be read: {type(exc).__name__}"))
    port = native.port if native is not None else _port()
    rows.append(("server", "answering" if _health_ok(port) else "not answering"))
    try:
        import asyncio

        from services import dependencies

        for dep_id in dependencies.IDS:
            state = asyncio.run(dependencies.state(dep_id))
            rows.append((dependencies.NAMES[dep_id], str(state.get("detail") or state["state"])))
    except Exception as exc:
        rows.append(("tools", f"can't be read: {type(exc).__name__}"))
    return rows


def cmd_dump(args=()):
    """alles dump: a plain summary of this install to paste into a bug report.

    Same idea as `hermes dump` (hermes_cli/dump.py, 0.22.2+1885.g20acba0): plain text even in a
    terminal, so it pastes cleanly, and nothing secret in it.
    """
    rows = _dump_lines()
    width = max(len(key) for key, _ in rows) + 2
    print("--- alles dump ---")
    for key, value in rows:
        print(f"{key.ljust(width)}{value}")
    print("--- end dump ---")
    return True


COMMANDS = {
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "logs": cmd_logs,
    "update": cmd_update,
    "open": cmd_open,
    "doctor": cmd_doctor,
    "restore": cmd_restore,
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "access": cmd_access,
    "password": cmd_password,
    "config": cmd_config,
    "test": cmd_test,
    "tools": cmd_tools,
    "version": cmd_version,
    "completion": cmd_completion,
    "ask": cmd_ask,
    "chat": cmd_chat,
    "backup": cmd_backup,
    "dump": cmd_dump,
    "folders": cmd_folders,
}


def _usage():
    return __doc__.strip() + "\n\ncommands: " + "  ".join(COMMANDS)


def main():
    from core.tool_path import extend_tool_path

    extend_tool_path()
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help", "help"):
        print(_usage())
        return
    if not args:
        cmd_home()
        return
    if args[0] not in COMMANDS:
        print(f"alles: unknown command '{args[0]}'\n", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        sys.exit(1)
    if COMMANDS[args[0]](args[1:]) is False:
        sys.exit(1)


if __name__ == "__main__":
    main()
