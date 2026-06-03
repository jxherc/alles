"""
shell execution — admin only, streams output via SSE.
"""
import os, sys, asyncio, json, shutil, logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api")
log = logging.getLogger("aide.shell")

_TIMEOUT_EXEC   = 30   # seconds for blocking exec
_TIMEOUT_STREAM = 120  # seconds for streaming


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


class ExecRequest(BaseModel):
    command: str
    timeout: int = _TIMEOUT_EXEC


# POST /api/shell/exec  — blocking, returns stdout/stderr/exit_code
@router.post("/shell/exec")
async def shell_exec(body: ExecRequest):
    shell = _find_shell()
    try:
        proc = await asyncio.create_subprocess_exec(
            *shell, body.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.path.expanduser("~"),
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
    timeout: int = _TIMEOUT_STREAM


async def _stream_proc(command: str, timeout: int):
    shell = _find_shell()
    try:
        proc = await asyncio.create_subprocess_exec(
            *shell, command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
            cwd=os.path.expanduser("~"),
        )
    except Exception as e:
        yield f"data: {json.dumps({'type':'error','text':str(e)})}\n\n"
        return

    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                proc.kill()
                yield f"data: {json.dumps({'type':'error','text':f'timed out after {timeout}s'})}\n\n"
                break
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=min(remaining, 5))
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            yield f"data: {json.dumps({'type':'line','text':line.decode('utf-8','replace').rstrip()})}\n\n"

        await proc.wait()
        yield f"data: {json.dumps({'type':'done','exit_code':proc.returncode})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type':'error','text':str(e)})}\n\n"
    finally:
        yield "data: [DONE]\n\n"


# POST /api/shell/stream  — SSE line-by-line output
@router.post("/shell/stream")
async def shell_stream(body: StreamRequest):
    return StreamingResponse(
        _stream_proc(body.command, body.timeout),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
