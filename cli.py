"""
alles CLI
  alles start    - start server in background
  alles stop     - stop server
  alles restart  - restart server
  alles status   - show if running + url
  alles logs     - tail logs
  alles open     - open in browser
"""
import sys, os, signal, subprocess, time, webbrowser
from pathlib import Path
from dotenv import load_dotenv

ROOT     = Path(__file__).parent
PID_FILE = ROOT / "data" / "aide.pid"
LOG_FILE = ROOT / "data" / "aide-server.log"

load_dotenv(ROOT / ".env", encoding="utf-8-sig")


def _port():
    return int(os.getenv("PORT", "8000"))

def _pid():
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None

def _running(pid):
    if pid is None:
        return False
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ['tasklist', '/FI', f'PID eq {pid}', '/NH'],
                stderr=subprocess.DEVNULL, text=True,
            )
            return str(pid) in out
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def _port_in_use():
    """check if something is already bound to our port (catches orphans not in PID file)"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', _port())) == 0


def _kill_port():
    """find and kill whatever is holding our port"""
    port = _port()
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ['netstat', '-ano', '-p', 'tcp'],
                stderr=subprocess.DEVNULL, text=True,
            )
            for line in out.splitlines():
                if f':{port} ' in line and 'LISTENING' in line:
                    pid = line.strip().split()[-1]
                    subprocess.call(['taskkill', '/F', '/PID', pid],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"killed orphaned process {pid} holding port {port}")
        else:
            subprocess.call(['fuser', '-k', f'{port}/tcp'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def cmd_start():
    pid = _pid()
    if _running(pid):
        print(f"alles already running  pid={pid}  http://localhost:{_port()}")
        return
    if _port_in_use():
        print(f"port {_port()} is in use by an orphaned process — killing it...")
        _kill_port()
        time.sleep(0.5)

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    python = sys.executable
    log = open(LOG_FILE, "a")

    if sys.platform == "win32":
        proc = subprocess.Popen(
            [python, "app.py"],
            cwd=ROOT,
            stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    else:
        proc = subprocess.Popen(
            [python, "app.py"],
            cwd=ROOT,
            stdout=log, stderr=log,
            start_new_session=True,
        )

    PID_FILE.write_text(str(proc.pid))
    time.sleep(1.2)

    if _running(proc.pid):
        print(f"alles started  pid={proc.pid}  http://localhost:{_port()}")
    else:
        print("alles failed to start - check logs:")
        print(f"  alles logs")


def cmd_stop():
    pid = _pid()
    if not _running(pid):
        print("alles is not running")
        PID_FILE.unlink(missing_ok=True)
        return

    try:
        if sys.platform == "win32":
            subprocess.call(["taskkill", "/F", "/PID", str(pid)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)

        # wait up to 5s
        for _ in range(10):
            time.sleep(0.5)
            if not _running(pid):
                break

        PID_FILE.unlink(missing_ok=True)
        print(f"alles stopped  (pid {pid})")
    except Exception as e:
        print(f"stop failed: {e}")


def cmd_restart():
    cmd_stop()
    time.sleep(0.5)
    cmd_start()


def cmd_status():
    pid = _pid()
    port = _port()
    if _running(pid):
        print(f"alles running   pid={pid}   http://localhost:{port}")
    else:
        print("alles stopped")
        PID_FILE.unlink(missing_ok=True)


def cmd_logs(n=60):
    if not LOG_FILE.exists():
        print("no log file yet - run  alles start  first")
        return
    lines = LOG_FILE.read_text(errors="replace").splitlines()
    print("\n".join(lines[-n:]))


def cmd_open():
    pid = _pid()
    if not _running(pid):
        print("alles is not running - start it first with  alles start")
        return
    url = f"http://localhost:{_port()}"
    webbrowser.open(url)
    print(f"opening {url}")


COMMANDS = {
    "start":   cmd_start,
    "stop":    cmd_stop,
    "restart": cmd_restart,
    "status":  cmd_status,
    "logs":    cmd_logs,
    "open":    cmd_open,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__.strip())
        print("\ncommands:", "  ".join(COMMANDS))
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
