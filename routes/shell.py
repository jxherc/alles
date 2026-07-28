"""
shell execution and a scoped interactive PTY — admin only.
"""

import asyncio
import contextlib
import ipaddress
import json
import logging
import os
import signal
import struct
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_auth
from core.database import Project, Session, SessionLocal, get_db
from core.server_config import trusted_hosts
from services.project_environment import canonical_folder, folder_state, session_environment

if os.name == "posix":
    import fcntl
    import pty
    import termios

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])
log = logging.getLogger("aide.shell")

_TIMEOUT_EXEC = 30  # seconds for blocking exec
_TIMEOUT_STREAM = 120  # seconds for streaming
_PTY_MAX_COLS = 500
_PTY_MAX_ROWS = 200
_PTY_INPUT_WRITE_TIMEOUT = 2.0
_PTY_CHILD_BOOTSTRAP = (
    "import fcntl, os, sys, termios; "
    "fcntl.ioctl(0, termios.TIOCSCTTY, 0); "
    "os.execv(sys.argv[1], [sys.argv[1], '-l'])"
)


def _find_shell():
    if sys.platform == "win32":
        # prefer git bash, fall back to cmd
        for path in [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ]:
            if os.path.exists(path):
                return [path, "-c"]
        return ["cmd", "/c"]
    return ["/bin/bash", "-c"]


def _interactive_shell() -> str:
    configured = os.environ.get("SHELL", "")
    candidates = [configured, "/bin/zsh", "/bin/bash", "/bin/sh"]
    return next((path for path in candidates if path and os.path.isfile(path)), "")


def _same_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin", "").strip()
    if not origin:
        from core.settings import auth_enabled

        return not auth_enabled()
    parsed = urlsplit(origin)
    expected_origin_scheme = {"ws": "http", "wss": "https"}.get(websocket.url.scheme)
    hostname = (parsed.hostname or "").lower()
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = None
    configured_host = any(
        hostname == allowed or (allowed.startswith("*.") and hostname.endswith(allowed[1:]))
        for allowed in trusted_hosts()
    )
    return (
        parsed.scheme == expected_origin_scheme
        and parsed.netloc.lower() == websocket.headers.get("host", "").lower()
        and (literal_address is not None or configured_host)
    )


def _resize_pty(fd: int, cols: int, rows: int) -> None:
    cols = min(_PTY_MAX_COLS, max(20, int(cols)))
    rows = min(_PTY_MAX_ROWS, max(5, int(rows)))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _terminate_pty_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=1)


async def _wait_pty_writable(fd: int) -> None:
    loop = asyncio.get_running_loop()
    ready = loop.create_future()

    def mark_ready() -> None:
        if not ready.done():
            ready.set_result(None)

    loop.add_writer(fd, mark_ready)
    try:
        await ready
    finally:
        loop.remove_writer(fd)


async def _write_pty_input(
    fd: int,
    data: bytes,
    *,
    write_fn=None,
    wait_writable=None,
    write_timeout: float = _PTY_INPUT_WRITE_TIMEOUT,
) -> None:
    """Write one complete browser input frame without losing short or blocked writes."""
    write_fn = write_fn or os.write
    wait_writable = wait_writable or _wait_pty_writable
    pending = memoryview(data)
    while pending:
        try:
            written = write_fn(fd, pending)
        except BlockingIOError:
            await asyncio.wait_for(wait_writable(fd), timeout=write_timeout)
            continue
        if written <= 0:
            raise OSError("PTY input closed before the complete frame was written")
        pending = pending[written:]


class ExecRequest(BaseModel):
    command: str
    timeout: int = Field(
        _TIMEOUT_EXEC, ge=1
    )  # a 0/negative timeout "times out" instantly, running nothing
    session_id: str = ""
    project_id: str = ""
    context_required: bool = False


def _execution_cwd(body, db: DbSession) -> str:
    if body.session_id:
        session = db.get(Session, body.session_id)
        if not session:
            raise HTTPException(404, "session not found")
        environment = session_environment(session)
        if environment["cwd"]:
            return environment["cwd"]
        if environment["kind"] != "general":
            raise ApiError(
                409,
                "project_folder_unavailable",
                "relink this Project folder before running terminal commands",
            )
    elif body.project_id:
        project = db.get(Project, body.project_id)
        if not project:
            raise HTTPException(404, "project not found")
        if folder_state(project.working_dir) != "available":
            raise ApiError(
                409,
                "project_folder_unavailable",
                "relink this Project folder before running terminal commands",
            )
        return canonical_folder(project.working_dir, must_exist=True)
    if body.context_required:
        raise ApiError(
            400,
            "project_context_required",
            "choose a Project folder before running terminal commands",
        )
    return os.path.expanduser("~")


@router.websocket("/shell/pty")
async def shell_pty(
    websocket: WebSocket,
    session_id: str = "",
    project_id: str = "",
):
    """Attach one authenticated browser tab to one scoped local PTY.

    The protocol is intentionally small: the browser sends JSON input/resize messages and
    receives raw terminal bytes. No attach addon or DOM-rendered terminal content is used.
    """
    try:
        # Router dependencies are expected to cover WebSockets, but this shell
        # endpoint is too powerful to rely on registration behavior alone.
        require_auth(websocket)
    except HTTPException:
        await websocket.close(code=1008, reason="not authenticated")
        return
    if not _same_origin(websocket):
        await websocket.close(code=1008, reason="origin not allowed")
        return
    if os.name != "posix" or sys.platform not in {"darwin", "linux"}:
        await websocket.close(code=1003, reason="terminal unavailable on this platform")
        return
    shell = _interactive_shell()
    if not shell:
        await websocket.close(code=1011, reason="shell unavailable")
        return
    db = SessionLocal()
    try:
        try:
            cwd = _execution_cwd(
                SimpleNamespace(
                    session_id=session_id,
                    project_id=project_id,
                    context_required=True,
                ),
                db,
            )
        except (ApiError, HTTPException) as exc:
            await websocket.close(
                code=1008, reason=str(getattr(exc, "detail", "invalid context"))[:100]
            )
            return
    finally:
        db.close()

    await websocket.accept()
    master_fd, slave_fd = pty.openpty()
    _resize_pty(master_fd, 100, 30)
    env = os.environ.copy()
    env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor"})
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", _PTY_CHILD_BOOTSTRAP, shell],
            cwd=cwd,
            env=env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            close_fds=True,
        )
    except Exception:
        os.close(master_fd)
        os.close(slave_fd)
        await websocket.close(code=1011, reason="could not start terminal")
        return
    try:
        os.close(slave_fd)
        os.set_blocking(master_fd, False)
        loop = asyncio.get_running_loop()
        output: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)
        reader_open = True
        reader_registered = False
    except BaseException:
        await asyncio.to_thread(_terminate_pty_process, process)
        with contextlib.suppress(OSError):
            os.close(master_fd)
        with contextlib.suppress(OSError):
            os.close(slave_fd)
        raise

    def pause_reader() -> None:
        nonlocal reader_registered
        if reader_registered:
            loop.remove_reader(master_fd)
            reader_registered = False

    def resume_reader() -> None:
        nonlocal reader_registered
        if reader_open and not reader_registered and not output.full():
            loop.add_reader(master_fd, queue_output)
            reader_registered = True

    def queue_output() -> None:
        nonlocal reader_open
        if output.full():
            pause_reader()
            return
        try:
            chunk = os.read(master_fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            chunk = b""
        if chunk:
            output.put_nowait(chunk)
            if output.full():
                pause_reader()
            return
        if reader_open:
            reader_open = False
            pause_reader()
            output.put_nowait(None)

    async def send_output() -> None:
        while True:
            chunk = await output.get()
            resume_reader()
            if chunk is None:
                return
            await websocket.send_bytes(chunk)

    async def receive_input() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            raw = message.get("text")
            if not raw:
                data = message.get("bytes")
                if data:
                    await _write_pty_input(master_fd, data)
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "input":
                data = str(event.get("data") or "").encode("utf-8")
                if data:
                    await _write_pty_input(master_fd, data)
            elif event.get("type") == "resize":
                with contextlib.suppress(TypeError, ValueError, OSError):
                    _resize_pty(master_fd, event.get("cols", 100), event.get("rows", 30))

    try:
        resume_reader()
        await websocket.send_json({"type": "ready", "cwd": cwd})
        sender = asyncio.create_task(send_output())
        receiver = asyncio.create_task(receive_input())
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            with contextlib.suppress(WebSocketDisconnect):
                task.result()
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    finally:
        pause_reader()
        await asyncio.to_thread(_terminate_pty_process, process)
        with contextlib.suppress(OSError):
            os.close(master_fd)


# POST /api/shell/exec  — blocking, returns stdout/stderr/exit_code
@router.post("/shell/exec")
async def shell_exec(body: ExecRequest, db: DbSession = Depends(get_db)):
    shell = _find_shell()
    cwd = _execution_cwd(body, db)
    try:
        proc = await asyncio.create_subprocess_exec(
            *shell,
            body.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=body.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"exit_code": -1, "stdout": "", "stderr": f"timed out after {body.timeout}s"}

        return {
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", "replace")[:50_000],
            "stderr": stderr.decode("utf-8", "replace")[:10_000],
        }
    except Exception as e:
        raise HTTPException(500, str(e))


class StreamRequest(BaseModel):
    command: str
    timeout: int = Field(_TIMEOUT_STREAM, ge=1)
    session_id: str = ""
    project_id: str = ""
    context_required: bool = False


async def _stream_proc(command: str, timeout: int, cwd: str):
    shell = _find_shell()
    try:
        proc = await asyncio.create_subprocess_exec(
            *shell,
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
            cwd=cwd,
        )
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
        return

    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                proc.kill()
                yield f"data: {json.dumps({'type': 'error', 'text': f'timed out after {timeout}s'})}\n\n"
                break
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=min(remaining, 5))
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            yield f"data: {json.dumps({'type': 'line', 'text': line.decode('utf-8', 'replace').rstrip()})}\n\n"

        await proc.wait()
        yield f"data: {json.dumps({'type': 'done', 'exit_code': proc.returncode})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
    finally:
        yield "data: [DONE]\n\n"


class PyExecRequest(BaseModel):
    code: str
    timeout: int = Field(30, ge=1)


# POST /api/execute/python — run python code, return stdout/stderr
@router.post("/execute/python")
async def execute_python(body: PyExecRequest):
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(body.code)
        fname = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            fname,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=body.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"exit_code": -1, "stdout": "", "stderr": f"timed out after {body.timeout}s"}
        return {
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", "replace")[:50_000],
            "stderr": stderr.decode("utf-8", "replace")[:10_000],
        }
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        try:
            os.unlink(fname)
        except Exception:
            pass


# POST /api/shell/stream  — SSE line-by-line output
@router.post("/shell/stream")
async def shell_stream(body: StreamRequest, db: DbSession = Depends(get_db)):
    cwd = _execution_cwd(body, db)
    return StreamingResponse(
        _stream_proc(body.command, body.timeout, cwd),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
