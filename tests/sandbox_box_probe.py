"""Check the agent shell sandbox on this machine and print a pass/fail table.

Run from the repo: `python tests/sandbox_box_probe.py` (add `--no-internet` on a box with no way
out). It only imports services/shell_sandbox.py and only writes inside its own temp folders: every
"outside" target, and the home it hands the sandbox, are throwaway folders next to the task folder.
A sleeping child of this script stands in for the alles server, and two local web servers stand in
for alles's port and a project's dev server.
"""

import http.server
import os
import shlex
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services import shell_sandbox  # noqa: E402

PY = shlex.quote(sys.executable)
rows = []


def record(check, expected, ok, detail=""):
    rows.append((check, expected, "PASS" if ok else "FAIL", detail))


class _Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


def _server():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Page)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run(command, project, home, *, closed_ports=(), offline=False):
    argv, env, once = shell_sandbox.wrap(
        command, project, [project], closed_ports=closed_ports, offline=offline
    )
    try:
        done = subprocess.run(
            argv,
            cwd=project,
            env={**os.environ, "HOME": str(home), **env},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
            start_new_session=True,  # as alles runs it
        )
        return done.returncode, (done.stdout + done.stderr).strip()
    finally:
        if once:
            shutil.rmtree(once, ignore_errors=True)


def main():
    internet = "--no-internet" not in sys.argv
    kind = shell_sandbox.kind()
    record(
        "sandbox found and its probe holds a write in", "sandbox-exec or bwrap", bool(kind), kind
    )
    if not kind:
        return
    base = Path(tempfile.mkdtemp(prefix="alles-box-probe-")).resolve()
    try:
        project, outside, home = base / "project", base / "outside", base / "home"
        for folder in (project, outside, home):
            folder.mkdir()
        (outside / "keep.txt").write_text("outside words")
        (project / "link").symlink_to(outside, target_is_directory=True)

        code, out = run(
            "echo hi > made.txt && mkdir -p a/b && echo x > a/b/c && cat made.txt", project, home
        )
        record("write inside the task folder", "works", code == 0 and out == "hi", out[-80:])
        code, out = run('echo note > "$TMPDIR/n" && cat "$TMPDIR/n"', project, home)
        record("write in the private temp folder", "works", code == 0 and out == "note", out[-80:])

        attempts = {
            "cd .. then write": "cd .. && echo x > outside/cd.txt",
            "absolute path": f"echo x > {outside}/abs.txt",
            "symlink inside pointing out": "echo x > link/sym.txt",
            "symlink made by the command": f"ln -s {outside} fresh && echo x > fresh/new.txt",
            "~ (the sandbox's home)": "echo x > ~/probe.txt",
            "python -c": f"{PY} -c \"open('{outside}/py.txt', 'w').write('x')\"",
            "overwrite a file outside": f"echo gone > {outside}/keep.txt",
            "delete a file outside": f"rm {outside}/keep.txt",
            "move a file out of there": f"mv {outside}/keep.txt taken.txt",
            "hard link to a file outside": f"ln {outside}/keep.txt hard && echo gone >> hard",
            "a script it wrote": f"printf 'echo x > {outside}/s.txt' > s.sh && bash s.sh",
        }
        for name, command in attempts.items():
            code, out = run(command, project, home)
            record(
                f"escape: {name}", "refused", code != 0, out.splitlines()[-1][-80:] if out else ""
            )
        intact = sorted(p.name for p in outside.iterdir()) == ["keep.txt"]
        intact = intact and (outside / "keep.txt").read_text() == "outside words"
        record("outside folder untouched after all that", "untouched", intact)
        record("home untouched", "untouched", list(home.iterdir()) == [])

        alles, dev = _server(), _server()
        fetch = (
            f'{PY} -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=5)" '
        )
        modes = [("alles has a password", False)]
        if kind == "bwrap":
            modes.append(("alles has no password", True))
        for label, offline in modes:
            port = alles.server_address[1]
            closed = (port,)
            for host in ("127.0.0.1", "localhost"):
                code, _ = run(
                    fetch + f"http://{host}:{port}/",
                    project,
                    home,
                    closed_ports=closed,
                    offline=offline,
                )
                if kind == "bwrap" and not offline:
                    # bubblewrap can't close one port; alles's api needs the owner's session here
                    rows.append(
                        (f"alles port via {host} ({label})", "reachable by design", "INFO", "")
                    )
                else:
                    record(f"alles port via {host} ({label})", "refused", code != 0)
            code, out = run(
                fetch + f"http://127.0.0.1:{dev.server_address[1]}/",
                project,
                home,
                closed_ports=closed,
                offline=offline,
            )
            if offline:
                record(f"other local port ({label})", "refused (no network)", code != 0)
            else:
                record(f"other local port ({label})", "works", code == 0, out[-80:])
            if internet:
                code, out = run(
                    fetch + "https://example.com/",
                    project,
                    home,
                    closed_ports=closed,
                    offline=offline,
                )
                if offline:
                    record(f"internet ({label})", "refused (no network)", code != 0)
                else:
                    record(f"internet ({label})", "works", code == 0, out[-80:])
        for server in (alles, dev):
            server.shutdown()
            server.server_close()

        # a process of the owner's (alles itself, say), started outside the sandbox
        victim = subprocess.Popen(["sleep", "120"], start_new_session=True)
        try:
            code, out = run(f"kill -TERM {victim.pid}", project, home)
            record(
                "signal a process outside",
                "refused",
                code != 0 and victim.poll() is None,
                out[-80:],
            )
            if kind == "bwrap":
                code, out = run(
                    f"test -e /proc/{victim.pid}/environ && cat /proc/{victim.pid}/environ",
                    project,
                    home,
                )
                record("read an outside process's /proc", "refused", code != 0, out[-80:])
                ptrace = (
                    f'{PY} -c "import ctypes, sys; libc = ctypes.CDLL(None, use_errno=True); '
                    f'sys.exit(0 if libc.ptrace(16, {victim.pid}, 0, 0) == 0 else 1)"'
                )
                code, out = run(ptrace, project, home)
                record("ptrace an outside process", "refused", code != 0, out[-80:])
                code, out = run("ps -e -o pid= | wc -l", project, home)
                if (
                    shell_sandbox._proc.get(shell_sandbox._tool()[1])
                    == shell_sandbox._PROC_FORMS[0]
                ):
                    record(
                        "sees only its own processes",
                        "a handful",
                        code == 0 and int(out or 0) < 10,
                        out,
                    )
                else:
                    # this machine refuses a fresh /proc, so the real one is bound read-only
                    rows.append(
                        ("sees only its own processes", "listed, read-only /proc", "INFO", out)
                    )
        finally:
            victim.kill()
            victim.wait()
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        width = max(len(r[0]) for r in rows) if rows else 10
        for check, expected, verdict, detail in rows:
            print(f"{verdict:4}  {check:<{width}}  [{expected}]  {detail}")
        failed = [r for r in rows if r[2] == "FAIL"]
        print(
            f"\n{len(rows) - len(failed)} of {len(rows)} checks pass"
            + (": FAILED" if failed else "")
        )
    sys.exit(1 if any(r[2] == "FAIL" for r in rows) else 0)
