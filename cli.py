"""
alles CLI

  alles start          start the server in the background
  alles stop           stop it
  alles restart        restart it
  alles status         running/stopped + url + reachability
  alles logs [N]       print the last N log lines (default 60)
  alles logs -f        follow the log live (ctrl-c to stop)
  alles logs --clear   truncate the log file
  alles update         stage, verify, switch, health-check, and keep rollback
  alles update rollback
                       restore the previous verified code and data
  alles open           open the browser
  alles doctor         check the install is ready (deps, data dir, provider)
  alles restore apply <id> [--allow-partial]
                       verify, migrate, and atomically apply a staged backup
  alles restore stage <backup> [--key <recovery-key>]
                       stage an encrypted backup on a clean installation
  alles restore recover
                       put original data back after an interrupted restore
  alles restore rollback <operation-id>
                       roll back a completed restore while its snapshot exists
  alles install        put `alles` on your PATH so you can run it from anywhere
  alles uninstall      remove the PATH launcher again

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


def _native_layout():
    """Return the verified native layout only when its dispatcher selected this process."""
    try:
        from services.native_install import current_layout, verify_install
    except ImportError:
        if not (ROOT / "services" / "native_install.py").is_file():
            return None
        raise
    layout = current_layout()
    if layout is not None:
        verify_install(layout)
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
    native = _native_layout()
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


def cmd_status(args=()):
    native = _native_layout()
    if native is not None:
        from services import service_manager

        try:
            state = service_manager.status("server")
        except service_manager.ServiceOwnershipError as exc:
            print(f"alles native service is untrusted: {exc}")
            return False
        label = "running" if state["running"] else "stopped"
        suffix = "" if state["available"] else " (service manager unavailable)"
        print(f"alles {label} through {native.manager}{suffix}")
        return bool(state["available"] and state["running"])
    pid = _pid()
    up = _port_open()
    if _running(pid) and _alles_process(pid) is not None:
        state = "reachable" if up else "process up, port not answering yet"
        print(f"alles running   pid={pid}   {_url()}   ({state})")
    elif _running(pid):
        print(f"stale pid file points to another process ({pid}); it was not touched")
    elif up:
        print(f"port {_port()} is busy, but no verified Alles process is tracked")
    else:
        print("alles stopped")
        PID_FILE.unlink(missing_ok=True)


def cmd_logs(args=()):
    args = list(args)
    native = _native_layout()
    log_file = native.data_root / "alles-service.log" if native is not None else LOG_FILE
    if "--clear" in args:
        log_file.write_text("")
        print("log cleared")
        return
    if not log_file.exists():
        print("no log file yet — run  alles start  first")
        return
    if "-f" in args or "--follow" in args:
        _follow_logs(log_file)
        return
    n = next((int(a) for a in args if a.isdigit()), 60)
    if native is not None:
        print("\n".join(log_file.read_text(errors="replace").splitlines()[-n:]))
    else:
        print("\n".join(_tail(n)))


def _follow_logs(log_file: Path = LOG_FILE):
    with log_file.open("r", errors="replace") as f:
        for ln in f.readlines()[-40:]:
            sys.stdout.write(ln)
        sys.stdout.flush()
        try:
            while True:
                ln = f.readline()
                if ln:
                    sys.stdout.write(ln)
                    sys.stdout.flush()
                else:
                    time.sleep(0.3)
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


def _cmd_update_accept() -> bool:
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
    print("update accepted; its encrypted pre-update backup was kept")
    return True


def _stage_update_data(
    live: Path,
    code_root: Path,
    update_dir: Path,
    *,
    python_path: Path | None = None,
    artifact_callback=None,
):
    """Create the encrypted rollback backup and test the new code on a second staged copy."""
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
        rollback = stage_recovery_archive(plaintext, live, restore_id=rollback_id)
        preflight = stage_recovery_archive(plaintext, live, restore_id=candidate_id)
        _prepare_staged_candidate(
            preflight,
            live,
            app_root=code_root,
            python_path=python_path,
        )
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


def _fetch_native_update_source(manifest: dict, update_dir: Path) -> tuple[Path | None, str]:
    """Fetch one exact commit from the source pinned by the install manifest."""
    import re
    import shutil
    import uuid

    source = manifest.get("source") or {}
    if source.get("kind") != "git":
        raise RuntimeError(
            "this install has no verified Git update source; reinstall from a tracked release"
        )
    url = source["url"]
    branch = source["branch"]
    ref = f"refs/heads/{branch}"
    try:
        remote = subprocess.run(
            ["git", "ls-remote", "--exit-code", "--refs", url, ref],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("the configured release source could not be checked") from exc
    rows = [line.split() for line in (remote.stdout or "").splitlines() if line.strip()]
    if remote.returncode != 0 or len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref:
        raise RuntimeError("the configured release branch could not be resolved exactly")
    target = rows[0][0].lower()
    if not re.fullmatch(r"[0-9a-f]{40}", target):
        raise RuntimeError("the configured release branch returned an invalid commit")
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


def _native_service_running() -> bool:
    from services import service_manager

    state = service_manager.status("server")
    if not state.get("available"):
        raise RuntimeError("the owned service manager is unavailable")
    return bool(state.get("running"))


def _native_service_endpoint(layout) -> tuple[int, str]:
    from services import native_install

    # The owned service definition intentionally does not inherit the invoking
    # shell's PORT. Verify that definition before relying on its fixed endpoint.
    native_install.verify_install(layout)
    port = 6769
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


def _native_start_service_healthy(layout) -> bool:
    from services import service_manager

    _, base_url = _native_service_endpoint(layout)
    try:
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
        if operation_id and (recovery / "operations" / f"{operation_id}.json").exists():
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


def _cmd_native_update_accept_locked(layout) -> bool:
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
    print("native update accepted; its encrypted pre-update backup was kept")
    return True


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


def _cmd_native_update_locked(layout) -> bool:
    import shutil
    import uuid

    from services import native_install
    from services.instance_lock import InstanceLock, InstanceLockError
    from services.restore_apply import (
        RestoreApplyError,
        begin_restore_operation,
        complete_restore_operation,
        swap_in_staged,
    )
    from services.update_safety import UpdateSafetyError, begin_update, finish_update

    live = layout.data_root.resolve()
    update_dir, _ = _update_paths(live)
    state_path = _native_update_state_path(live)
    source_checkout = None
    target = None
    update_id = None
    update_started = False
    state_published = False
    try:
        manifest = native_install.verify_install(layout)
        existing = _load_native_update_state(state_path)
        if existing or layout.previous_release.exists():
            print("a native update is awaiting rollback or acceptance")
            return False
        source_checkout, target = _fetch_native_update_source(manifest, update_dir)
        if source_checkout is None:
            print("alles is already up to date")
            return True
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
            release_probe=_native_install_probe,
        )
        python = release / ".venv" / "bin" / "python"
        if not _native_candidate_control_plane_ok(release, python, update_dir):
            raise RuntimeError("the staged native release cannot run the rollback control plane")

        state["phase"] = "stopping_service"
        _write_update_state(state_path, state)
        _native_stop_service(layout)
        state["phase"] = "service_stopped"
        _write_update_state(state_path, state)

        lock = InstanceLock(live)
        acquired = False
        operation = None
        rollback = candidate = None
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
            issues = _coverage_issues(rollback)
            if issues:
                raise RuntimeError(
                    "automatic native update cannot roll back external data roots: "
                    + ", ".join(issues)
                )
            operation = begin_restore_operation(live, candidate.restore_id)
            state.update({"phase": "data_swapping", "operation_id": operation.operation_id})
            _write_update_state(state_path, state)
            swap_in_staged(operation, candidate.data_dir)
            state["phase"] = "data_swapped"
            _write_update_state(state_path, state)
            native_install.activate_release(layout, target, source_commit=target)
            state["phase"] = "release_switched"
            _write_update_state(state_path, state)
        finally:
            if acquired:
                lock.release()

        healthy = _run_recovery_probe(
            live,
            passes=1,
            app_root=release,
            python_path=python,
        )
        if not healthy:
            raise RuntimeError("the native release failed its final-location health check")
        complete_restore_operation(operation)
        state["phase"] = "applied"
        _write_update_state(state_path, state)
        if was_running and not _native_start_service_healthy(layout):
            raise RuntimeError("the native release failed normal service startup")
        finish_update(live, update_id)
        print(f"alles updated safely to native release {target[:12]}")
        print(f"rollback backup kept at: {encrypted}")
        print("rollback command:  alles update rollback")
        return True
    except (
        native_install.NativeInstallError,
        UpdateSafetyError,
        InstanceLockError,
        RestoreApplyError,
        RuntimeError,
        OSError,
    ) as exc:
        print(f"native update stopped: {exc}")
        try:
            state = _load_native_update_state(state_path)
        except RuntimeError:
            state = None
        owned_state = bool(state and update_id and state.get("update_id") == update_id)
        if owned_state and (update_started or state.get("phase") != "preparing"):
            if _native_finish_rollback(layout, state, state_path):
                print("the previous native release and data were restored")
            else:
                print("run:  alles update rollback")
        else:
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
        return False
    finally:
        if source_checkout is not None:
            shutil.rmtree(source_checkout, ignore_errors=True)


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
        print("an earlier update still has rollback state")
        print("use  alles update rollback  or  alles update accept  before another update")
        return False
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
            issues = _coverage_issues(rollback)
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
            healthy = _run_recovery_probe(live, passes=1)
        finally:
            if previous_token is None:
                os.environ.pop("ALLES_UPDATE_TOKEN", None)
            else:
                os.environ["ALLES_UPDATE_TOKEN"] = previous_token
        if not healthy:
            print("updated version failed its final-location health check — rolling back…")
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


def cmd_doctor(args=()):
    """fresh-install readiness check — deps, data dir, encryption key, provider."""
    try:
        from services import doctor
    except Exception as e:
        print(f"couldn't load checks: {e}")
        return
    checks = doctor.run_all()
    print("alles doctor\n")
    for c in checks:
        mark = "ok " if c["ok"] else "!! "
        print(f"  [{mark}] {c['label']:<24} {c['detail']}")
    hard_fail = [c for c in checks if not c["ok"] and c["label"] in doctor._HARD]
    print()
    if hard_fail:
        print("not ready — fix the !! items above, then:  alles start")
        sys.exit(1)
    print("ready to go.  start with:  alles start")


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


def _native_install_probe(release: Path, python: Path) -> bool:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="alles-native-install-probe-") as directory:
        return _run_recovery_probe(
            Path(directory),
            passes=2,
            app_root=release,
            python_path=python,
        )


def cmd_install(args=()):
    """Install an owned native runtime, launcher, and user service on macOS/Linux."""
    args = tuple(args)
    if args in (("launcher",), ("--launcher-only",)):
        return _cmd_install_launcher()
    if args:
        print("usage:  alles install  |  alles install --launcher-only")
        return False
    if IS_WIN:
        print("the native installer currently supports macOS and Linux")
        return False
    from services import native_install

    try:
        layout = native_install.platform_layout()
        result = native_install.install(
            ROOT,
            layout,
            release_probe=_native_install_probe,
        )
    except native_install.NativeInstallError as exc:
        print(f"native install stopped safely: {exc}")
        return False
    print(f"alles installed at {result['runtime_root']}")
    print(f"personal data: {result['data_root']}")
    print(f"setup: {_native_service_endpoint(layout)[1]}")
    return True


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


def _recovery_probe_once(
    candidate: Path,
    *,
    timeout: float = RECOVERY_PROBE_TIMEOUT_SECONDS,
    app_root: Path | None = None,
    python_path: Path | None = None,
) -> bool:
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
        return False
    env = os.environ.copy()
    env.update(
        {
            "ALLES_DATA": str(candidate),
            "ALLES_DB": str(candidate / "aide.db"),
            "ALLES_HOST": "127.0.0.1",
            "ALLES_RECOVERY_PREFLIGHT": "1",
            "AUTH_ENABLED": "false",
            "PORT": str(port),
            "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONUNBUFFERED": "1",
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
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        return healthy


def _run_recovery_probe(
    candidate: Path,
    *,
    passes: int,
    app_root: Path | None = None,
    python_path: Path | None = None,
) -> bool:
    return all(
        _recovery_probe_once(candidate, app_root=app_root, python_path=python_path)
        for _ in range(passes)
    )


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
) -> None:
    """Remap configured file roots into staging, boot twice, then set final paths."""
    import json

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
    for role, key in keys.items():
        location = locations.get(role, {})
        if location.get("included") and location.get("storage") == "data":
            subpath = location.get("subpath")
            if not isinstance(subpath, str) or not subpath:
                raise RuntimeError(f"included {role} location is invalid")
            isolated[key] = str((staged.data_dir / subpath).resolve())
            if key in original:
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
        if app_root is None:
            healthy = _run_recovery_probe(staged.data_dir, passes=2)
        else:
            healthy = _run_recovery_probe(
                staged.data_dir,
                passes=2,
                app_root=app_root,
                python_path=python_path,
            )
        if not healthy:
            raise RuntimeError("staged Alles failed its migration/boot check")
    except Exception:
        _atomic_private_bytes(settings_path, original_bytes)
        raise
    _atomic_private_bytes(settings_path, final_bytes)


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

    if not _run_recovery_probe(live, passes=1):
        print("installed copy failed its health check — restoring the original data…")
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
    "test": cmd_test,
}


def _usage():
    return __doc__.strip() + "\n\ncommands: " + "  ".join(COMMANDS)


def main():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help", "help"):
        print(_usage())
        return
    if not args or args[0] not in COMMANDS:
        if args:
            print(f"alles: unknown command '{args[0]}'\n", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        sys.exit(1)
    COMMANDS[args[0]](args[1:])


if __name__ == "__main__":
    main()
