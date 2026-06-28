"""
alles CLI

  alles start          start the server in the background
  alles stop           stop it
  alles restart        restart it
  alles status         running/stopped + url + reachability
  alles logs [N]       print the last N log lines (default 60)
  alles logs -f        follow the log live (ctrl-c to stop)
  alles logs --clear   truncate the log file
  alles update         git pull, then restart
  alles open           open the browser
  alles doctor         check the install is ready (deps, data dir, provider)
  alles install        put `alles` on your PATH so you can run it from anywhere
  alles uninstall      remove the PATH launcher again

windows: alles.cmd   unix/git-bash: ./alles   or just: python app.py
"""

import sys, os, signal, socket, subprocess, time, webbrowser
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # dotenv is a dep, but never let a missing

    def load_dotenv(*a, **k):
        return False  # import block the whole CLI


ROOT = Path(__file__).parent
PID_FILE = ROOT / "data" / "alles.pid"
LOG_FILE = ROOT / "data" / "alles-server.log"

load_dotenv(ROOT / ".env", encoding="utf-8-sig")

IS_WIN = sys.platform == "win32"


def _port():
    try:
        return int(os.getenv("PORT", "8000"))
    except ValueError:
        return 8000


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


def _port_open():
    """is something accepting connections on our port? (server up, or an orphan)"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", _port())) == 0


def _kill_port():
    """find and kill whatever is holding our port — cross-platform best effort"""
    port = _port()
    try:
        if IS_WIN:
            out = subprocess.check_output(
                ["netstat", "-ano", "-p", "tcp"], stderr=subprocess.DEVNULL, text=True
            )
            for line in out.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    pid = line.strip().split()[-1]
                    subprocess.call(
                        ["taskkill", "/F", "/PID", pid],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    print(f"  killed orphan process {pid} on port {port}")
            return
        # unix: prefer lsof (works on macOS + linux), fall back to fuser (linux)
        from shutil import which

        if which("lsof"):
            out = subprocess.check_output(
                ["lsof", "-ti", f"tcp:{port}"], stderr=subprocess.DEVNULL, text=True
            )
            for pid in out.split():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    print(f"  killed orphan process {pid} on port {port}")
                except Exception:
                    pass
        elif which("fuser"):
            subprocess.call(
                ["fuser", "-k", f"{port}/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
    except subprocess.CalledProcessError:
        pass  # nothing was listening
    except Exception:
        pass


def _tail(n=60):
    if not LOG_FILE.exists():
        return []
    return LOG_FILE.read_text(errors="replace").splitlines()[-n:]


def _deps_ok() -> bool:
    """app.py will run under THIS interpreter — make sure it has the deps,
    otherwise the server just crash-loops into the log file."""
    try:
        import fastapi, uvicorn  # noqa: F401

        return True
    except ImportError:
        return False


def cmd_start(args=()):
    if not _deps_ok():
        print(f"dependencies are missing for this python:\n  {sys.executable}")
        print("install them with:")
        print(f"  {sys.executable} -m pip install -r requirements.txt")
        print("(if you installed packages into a different python, run alles with that one)")
        return
    pid = _pid()
    if _running(pid):
        print(f"alles already running  pid={pid}  {_url()}")
        return
    if _port_open():
        print(f"port {_port()} is busy (orphan?) — clearing it…")
        _kill_port()
        time.sleep(0.5)

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    python = sys.executable or "python3"
    with open(LOG_FILE, "a") as log:
        if IS_WIN:
            proc = subprocess.Popen(
                [python, "app.py"],
                cwd=ROOT,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                close_fds=True,
            )
        else:
            proc = subprocess.Popen(
                [python, "app.py"], cwd=ROOT, stdout=log, stderr=log, start_new_session=True
            )

    PID_FILE.write_text(str(proc.pid))

    # wait for the server to actually accept connections — not just for the
    # process to exist. first boot can load embedding models, so give it time.
    print("starting…", end="", flush=True)
    deadline = time.time() + 40
    while time.time() < deadline:
        if _port_open():
            print(f"\ralles started  pid={proc.pid}  {_url()}        ")
            return
        if proc.poll() is not None:  # process died during startup
            print("\ralles failed to start. last log lines:        \n")
            print("\n".join("  " + l for l in _tail(15)) or "  (log empty)")
            PID_FILE.unlink(missing_ok=True)
            return
        print(".", end="", flush=True)
        time.sleep(0.5)
    print(f"\ralles is still warming up (pid={proc.pid}).        ")
    print(f"  port {_port()} isn't answering yet — check:  alles logs -f")


def cmd_stop(args=()):
    pid = _pid()
    if not _running(pid):
        if _port_open():  # PID file stale but something's on the port
            print("no tracked pid, but the port is busy — clearing it…")
            _kill_port()
        else:
            print("alles is not running")
        PID_FILE.unlink(missing_ok=True)
        return

    try:
        if IS_WIN:
            subprocess.call(
                ["taskkill", "/F", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):  # up to 10s for a graceful exit
                if not _running(pid):
                    break
                time.sleep(0.5)
            if _running(pid):  # escalate
                print("not responding to SIGTERM — forcing…")
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
                time.sleep(0.5)
    except Exception as e:
        print(f"stop failed: {e}")
        return

    if _running(pid):
        print(f"stop failed — pid {pid} is still alive")
        return
    PID_FILE.unlink(missing_ok=True)
    print(f"alles stopped  (pid {pid})")


def cmd_restart(args=()):
    cmd_stop()
    time.sleep(0.5)
    cmd_start()


def cmd_status(args=()):
    pid = _pid()
    up = _port_open()
    if _running(pid):
        state = "reachable" if up else "process up, port not answering yet"
        print(f"alles running   pid={pid}   {_url()}   ({state})")
    elif up:
        print(f"alles running   (untracked pid)   {_url()}   reachable")
    else:
        print("alles stopped")
        PID_FILE.unlink(missing_ok=True)


def cmd_logs(args=()):
    args = list(args)
    if "--clear" in args:
        LOG_FILE.write_text("")
        print("log cleared")
        return
    if not LOG_FILE.exists():
        print("no log file yet — run  alles start  first")
        return
    if "-f" in args or "--follow" in args:
        _follow_logs()
        return
    n = next((int(a) for a in args if a.isdigit()), 60)
    print("\n".join(_tail(n)))


def _follow_logs():
    with LOG_FILE.open("r", errors="replace") as f:
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


def cmd_update(args=()):
    if not (ROOT / ".git").exists():
        print("not a git checkout — update manually, then  alles restart")
        return
    print("pulling latest…")
    try:
        r = subprocess.run(["git", "pull", "--ff-only"], cwd=ROOT)
    except FileNotFoundError:
        print("git not found on PATH")
        return
    if r.returncode != 0:
        print("git pull failed (local changes or diverged) — resolve, then  alles restart")
        return
    cmd_restart()


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


def cmd_install(args=()):
    """make `alles` runnable from any directory on mac/linux.

    writes a tiny launcher onto your PATH that calls THIS python (so a venv is
    remembered) with the full path to cli.py — no cd, no activating the venv."""
    if IS_WIN:
        print("windows: this folder already has alles.cmd. to run it from anywhere,")
        print("add this folder to your PATH:")
        print(f"  {ROOT}")
        return

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
        print(f"  sudo tee /usr/local/bin/alles >/dev/null <<EOF")
        print(f"  #!/usr/bin/env bash")
        print(f'  exec "{py}" "{cli}" "$@"')
        print(f"  EOF")
        print(f"  sudo chmod +x /usr/local/bin/alles")
        return

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
        print(f'  echo \'export PATH="{chosen}:$PATH"\' >> {rc} && source {rc}')
        print("then:  alles start")


def cmd_uninstall(args=()):
    """remove the launcher that `alles install` created."""
    if IS_WIN:
        print("windows: remove this folder from your PATH manually.")
        return
    removed = []
    for d in _unix_bin_dirs():
        p = d / "alles"
        try:
            if p.is_symlink() or p.exists():
                p.unlink()
                removed.append(str(p))
        except Exception as e:
            print(f"couldn't remove {p}: {e}")
    print("removed: " + ", ".join(removed) if removed else "nothing to remove")


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
