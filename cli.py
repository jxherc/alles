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

windows: alles.cmd   unix/git-bash: ./alles   or just: python app.py
"""
import sys, os, signal, socket, subprocess, time, webbrowser
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:                       # dotenv is a dep, but never let a missing
    def load_dotenv(*a, **k): return False   # import block the whole CLI

ROOT     = Path(__file__).parent
PID_FILE = ROOT / "data" / "aide.pid"
LOG_FILE = ROOT / "data" / "aide-server.log"

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
                ['tasklist', '/FI', f'PID eq {pid}', '/NH'],
                stderr=subprocess.DEVNULL, text=True)
            return str(pid) in out
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _port_open():
    """is something accepting connections on our port? (server up, or an orphan)"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', _port())) == 0


def _kill_port():
    """find and kill whatever is holding our port — cross-platform best effort"""
    port = _port()
    try:
        if IS_WIN:
            out = subprocess.check_output(['netstat', '-ano', '-p', 'tcp'],
                                          stderr=subprocess.DEVNULL, text=True)
            for line in out.splitlines():
                if f':{port} ' in line and 'LISTENING' in line:
                    pid = line.strip().split()[-1]
                    subprocess.call(['taskkill', '/F', '/PID', pid],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"  killed orphan process {pid} on port {port}")
            return
        # unix: prefer lsof (works on macOS + linux), fall back to fuser (linux)
        from shutil import which
        if which('lsof'):
            out = subprocess.check_output(['lsof', '-ti', f'tcp:{port}'],
                                          stderr=subprocess.DEVNULL, text=True)
            for pid in out.split():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    print(f"  killed orphan process {pid} on port {port}")
                except Exception:
                    pass
        elif which('fuser'):
            subprocess.call(['fuser', '-k', f'{port}/tcp'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        pass   # nothing was listening
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
                [python, "app.py"], cwd=ROOT, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                close_fds=True)
        else:
            proc = subprocess.Popen(
                [python, "app.py"], cwd=ROOT, stdout=log, stderr=log,
                start_new_session=True)

    PID_FILE.write_text(str(proc.pid))

    # wait for the server to actually accept connections — not just for the
    # process to exist. first boot can load embedding models, so give it time.
    print("starting…", end="", flush=True)
    deadline = time.time() + 40
    while time.time() < deadline:
        if _port_open():
            print(f"\ralles started  pid={proc.pid}  {_url()}        ")
            return
        if proc.poll() is not None:        # process died during startup
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
        if _port_open():               # PID file stale but something's on the port
            print("no tracked pid, but the port is busy — clearing it…")
            _kill_port()
        else:
            print("alles is not running")
        PID_FILE.unlink(missing_ok=True)
        return

    try:
        if IS_WIN:
            subprocess.call(["taskkill", "/F", "/PID", str(pid)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):            # up to 10s for a graceful exit
                if not _running(pid):
                    break
                time.sleep(0.5)
            if _running(pid):              # escalate
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
                    sys.stdout.write(ln); sys.stdout.flush()
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


COMMANDS = {
    "start":   cmd_start,
    "stop":    cmd_stop,
    "restart": cmd_restart,
    "status":  cmd_status,
    "logs":    cmd_logs,
    "update":  cmd_update,
    "open":    cmd_open,
    "doctor":  cmd_doctor,
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
