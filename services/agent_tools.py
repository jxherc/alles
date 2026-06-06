"""
Tool registry for aide's agent mode.

Tools return {"output": str, "error": bool}. Long-running tools can stream
incremental {"type": "output", "text": str} events via stream_execute().
"""
import asyncio
import base64
import contextvars
import fnmatch
import json
import os
import re
import shlex
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx


ROOT = Path(__file__).parent.parent
CODEX_HOME = Path(os.getenv("CODEX_HOME") or Path.home() / ".codex")

# per-run context (settings, endpoint, model) — async-task safe via contextvars
# so concurrent sub-agents don't clobber each other.
_ctx = contextvars.ContextVar("agent_ctx", default={})


def set_agent_ctx(settings=None, ep=None, model=""):
    _ctx.set({"settings": settings or {}, "ep": ep, "model": model})


def get_agent_ctx() -> dict:
    return _ctx.get()


def _settings() -> dict:
    return (_ctx.get() or {}).get("settings", {}) or {}

TOOL_PERMISSION = {
    "shell": "shell",
    "read_file": "read",
    "write_file": "write",
    "edit_file": "write",
    "apply_patch": "write",
    "todo_update": "state",
    "list_files": "read",
    "glob_files": "read",
    "grep_files": "read",
    "web_search": "web",
    "web_fetch": "web",
    "memory_search": "memory_read",
    "memory_add": "memory_write",
    "skill_list": "read",
    "skill_load": "read",
    "mcp_list_tools": "mcp_read",
    "mcp_call_tool": "mcp_call",
    "opencode_run": "delegate",
    "git_status": "read",
    "git_diff": "read",
    "git_branch": "git_write",
    "git_commit": "git_write",
    "screenshot": "computer",
    "computer_click": "computer",
    "computer_move": "computer",
    "computer_type": "computer",
    "computer_key": "computer",
    "computer_scroll": "computer",
    "spawn_agent": "delegate",
    "spawn_agents": "delegate",
}


def _safe_text(value, limit: int = 20000) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + f"\n\n[truncated {len(text) - limit} chars]"


def _resolve(path: str = ".") -> Path:
    p = Path(path or ".").expanduser()
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def _sandbox_cmd(command: str, workdir: str) -> list[str] | None:
    """wrap a command to run inside docker if sandbox is enabled + docker present"""
    s = _settings()
    if not s.get("agent_sandbox"):
        return None
    if not shutil.which("docker"):
        return None
    image = s.get("agent_sandbox_image") or "alpine:latest"
    cmd = ["docker", "run", "--rm", "-i"]
    if s.get("agent_sandbox_no_net"):
        cmd += ["--network", "none"]
    cmd += ["-v", f"{workdir}:/work", "-w", "/work", image, "sh", "-c", command]
    return cmd


async def _stream_shell(command: str, cwd: str = ""):
    try:
        workdir = str(_resolve(cwd or "."))
        sandboxed = _sandbox_cmd(command, workdir)
        if sandboxed:
            cmd = sandboxed
        elif os.name == "nt":
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
        else:
            cmd = ["bash", "-lc", command]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        collected = []
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=180)
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                collected.append(text)
                yield {"type": "output", "text": text}
        except asyncio.TimeoutError:
            proc.kill()
            yield {"type": "result", "result": {"output": "timeout after 180s", "error": True}}
            return
        await proc.wait()
        yield {"type": "result", "result": {
            "output": _safe_text("".join(collected), 12000),
            "error": proc.returncode != 0,
        }}
    except Exception as e:
        yield {"type": "result", "result": {"output": str(e), "error": True}}


async def _run_shell(command: str, cwd: str = "") -> dict:
    out = []
    final = {"output": "", "error": False}
    async for event in _stream_shell(command, cwd):
        if event["type"] == "output":
            out.append(event["text"])
        elif event["type"] == "result":
            final = event["result"]
    if out and not final.get("output"):
        final["output"] = _safe_text("".join(out), 12000)
    return final


async def _read_file(path: str, start_line: int = 1, end_line: int = 0) -> dict:
    try:
        p = _resolve(path)
        if not p.exists():
            return {"output": f"not found: {path}", "error": True}
        if p.is_dir():
            return {"output": f"is a directory: {path}", "error": True}
        lines = p.read_text("utf-8", errors="replace").splitlines()
        if end_line and end_line >= start_line:
            selected = lines[max(0, start_line - 1):end_line]
            prefix = f"{p}\nlines {start_line}-{end_line}\n\n"
        else:
            selected = lines
            prefix = f"{p}\n\n"
        return {"output": _safe_text(prefix + "\n".join(selected)), "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _write_file(path: str, content: str) -> dict:
    try:
        p = _resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, "utf-8")
        return {"output": f"wrote {len(content)} chars to {p}", "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _edit_file(path: str, old: str, new: str, replace_all: bool = False) -> dict:
    try:
        p = _resolve(path)
        if not p.exists():
            return {"output": f"not found: {path}", "error": True}
        text = p.read_text("utf-8", errors="replace")
        count = text.count(old)
        if count == 0:
            return {"output": "old text not found", "error": True}
        if count > 1 and not replace_all:
            return {"output": f"old text appears {count} times; set replace_all=true or use a more exact old string", "error": True}
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        p.write_text(updated, "utf-8")
        return {"output": f"edited {p} ({count if replace_all else 1} replacement{'s' if replace_all or count != 1 else ''})", "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _apply_patch_text(patch: str, cwd: str = "") -> dict:
    try:
        workdir = _resolve(cwd or ".")
        if not patch.strip():
            return {"output": "patch text required", "error": True}
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False, encoding="utf-8") as f:
            f.write(patch)
            patch_path = f.name
        try:
            if (workdir / ".git").exists():
                quoted = json.dumps(patch_path) if os.name == "nt" else shlex.quote(patch_path)
                return await _run_shell(f"git apply --whitespace=nowarn {quoted}", cwd=str(workdir))
            return {"output": "apply_patch currently requires a git worktree so `git apply` can apply the unified diff", "error": True}
        finally:
            try:
                Path(patch_path).unlink()
            except Exception:
                pass
    except Exception as e:
        return {"output": str(e), "error": True}


async def _todo_update(items: list[dict]) -> dict:
    try:
        normalized = []
        for item in items or []:
            normalized.append({
                "step": str(item.get("step", "")).strip(),
                "status": item.get("status", "pending") if item.get("status") in ("pending", "in_progress", "completed") else "pending",
            })
        normalized = [i for i in normalized if i["step"]]
        return {"output": json.dumps({"todos": normalized}, indent=2), "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _git_status(cwd: str = ".") -> dict:
    return await _run_shell("git status --short --branch", cwd=cwd)


async def _git_diff(cwd: str = ".", staged: bool = False, path: str = "") -> dict:
    cmd = "git diff --cached" if staged else "git diff"
    if path:
        q = json.dumps(path) if os.name == "nt" else shlex.quote(path)
        cmd += f" -- {q}"
    return await _run_shell(cmd, cwd=cwd)


async def _git_branch(cwd: str = ".", name: str = "", checkout: bool = True) -> dict:
    if not name.strip():
        return {"output": "branch name required", "error": True}
    q = json.dumps(name.strip()) if os.name == "nt" else shlex.quote(name.strip())
    cmd = f"git switch -c {q}" if checkout else f"git branch {q}"
    return await _run_shell(cmd, cwd=cwd)


async def _git_commit(cwd: str = ".", message: str = "", paths: list[str] | None = None) -> dict:
    if not message.strip():
        return {"output": "commit message required", "error": True}
    if paths:
        quoted = " ".join(json.dumps(p) if os.name == "nt" else shlex.quote(p) for p in paths)
        add = await _run_shell(f"git add -- {quoted}", cwd=cwd)
    else:
        add = await _run_shell("git add -A", cwd=cwd)
    if add.get("error"):
        return add
    msg = json.dumps(message.strip()) if os.name == "nt" else shlex.quote(message.strip())
    return await _run_shell(f"git commit -m {msg}", cwd=cwd)


async def _list_files(path: str = ".", depth: int = 1) -> dict:
    try:
        root = _resolve(path)
        if not root.exists():
            return {"output": f"not found: {path}", "error": True}
        if root.is_file():
            return {"output": str(root), "error": False}
        lines = []
        base_parts = len(root.parts)
        for item in sorted(root.rglob("*")):
            rel_depth = len(item.parts) - base_parts
            if rel_depth > max(1, depth):
                continue
            rel = item.relative_to(root)
            lines.append(("[dir] " if item.is_dir() else "      ") + str(rel))
            if len(lines) >= 500:
                lines.append("[truncated]")
                break
        return {"output": "\n".join(lines) or "(empty)", "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _glob_files(pattern: str, path: str = ".") -> dict:
    try:
        root = _resolve(path)
        matches = []
        for item in root.rglob("*"):
            rel = str(item.relative_to(root)).replace("\\", "/")
            if fnmatch.fnmatch(rel, pattern):
                matches.append(rel)
            if len(matches) >= 500:
                matches.append("[truncated]")
                break
        return {"output": "\n".join(matches) or "(no matches)", "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _grep_files(pattern: str, path: str = ".", file_glob: str = "*") -> dict:
    try:
        root = _resolve(path)
        rx = re.compile(pattern)
        rows = []
        for item in root.rglob(file_glob):
            if not item.is_file():
                continue
            try:
                for i, line in enumerate(item.read_text("utf-8", errors="replace").splitlines(), start=1):
                    if rx.search(line):
                        rel = item.relative_to(root)
                        rows.append(f"{rel}:{i}: {line[:240]}")
                        if len(rows) >= 500:
                            rows.append("[truncated]")
                            return {"output": "\n".join(rows), "error": False}
            except Exception:
                continue
        return {"output": "\n".join(rows) or "(no matches)", "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _web_search(query: str, max_results: int = 5) -> dict:
    try:
        from services.research_engine import web_search
        results = await web_search(query, max_results=max_results)
        return {"output": json.dumps(results, indent=2), "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _web_fetch(url: str, max_chars: int = 12000) -> dict:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return {"output": "only http/https URLs are allowed", "error": True}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            r = await c.get(url, headers={"user-agent": "aide-agent/1.0"})
            r.raise_for_status()
        text = r.text
        if "html" in r.headers.get("content-type", ""):
            text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
            text = re.sub(r"(?s)<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
        return {"output": _safe_text(text, max_chars), "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _memory_search(query: str, top_k: int = 8) -> dict:
    try:
        from services.memory_store import search_memories
        return {"output": json.dumps(search_memories(query, top_k=top_k), indent=2), "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _memory_add(text: str, category: str = "", pinned: bool = False) -> dict:
    try:
        from services.memory_store import add_memory
        return {"output": json.dumps(add_memory(text, category=category, source="agent", pinned=pinned), indent=2), "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


def _skill_files() -> list[Path]:
    roots = [
        CODEX_HOME / "skills",
        CODEX_HOME / "skills" / ".system",
        CODEX_HOME / "plugins" / "cache",
    ]
    out = []
    for root in roots:
        if root.exists():
            out.extend(root.rglob("SKILL.md"))
    return out


async def _skill_list() -> dict:
    try:
        skills = []
        for p in _skill_files():
            try:
                text = p.read_text("utf-8", errors="replace")
                name = ""
                desc = ""
                for line in text.splitlines()[:25]:
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip().strip('"')
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip().strip('"')
                skills.append({"name": name or p.parent.name, "description": desc, "path": str(p)})
            except Exception:
                continue

        from core.database import SessionLocal, CookbookEntry
        db = SessionLocal()
        try:
            for e in db.query(CookbookEntry).order_by(CookbookEntry.name).all():
                skills.append({"name": f"cookbook/{e.name}", "description": e.description, "path": f"cookbook:{e.id}"})
        finally:
            db.close()
        return {"output": json.dumps(skills[:300], indent=2), "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _skill_load(name_or_path: str) -> dict:
    try:
        target = name_or_path.strip()
        if target.startswith("cookbook/") or target.startswith("cookbook:"):
            key = target.split("/", 1)[-1].split(":", 1)[-1]
            from core.database import SessionLocal, CookbookEntry
            db = SessionLocal()
            try:
                rows = db.query(CookbookEntry).all()
                match = next((e for e in rows if e.id == key or e.name == key), None)
                if not match:
                    return {"output": f"cookbook skill not found: {target}", "error": True}
                return {"output": f"# {match.name}\n\n{match.description}\n\n{match.prompt}", "error": False}
            finally:
                db.close()

        p = Path(target)
        if p.exists():
            return {"output": _safe_text(p.read_text("utf-8", errors="replace")), "error": False}
        for sf in _skill_files():
            if sf.parent.name == target:
                return {"output": _safe_text(sf.read_text("utf-8", errors="replace")), "error": False}
        return {"output": f"skill not found: {target}", "error": True}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _mcp_list_tools() -> dict:
    try:
        from routes import mcp
        rows = []
        for sid, tools in mcp._tools.items():
            for t in tools:
                rows.append({
                    "server_id": sid,
                    "name": t.get("name"),
                    "description": t.get("description", ""),
                    "schema": t.get("schema", {}),
                })
        return {"output": json.dumps(rows, indent=2), "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _mcp_call_tool(server_id: str, tool_name: str, arguments: dict | None = None) -> dict:
    try:
        from routes import mcp
        session = mcp._sessions.get(server_id)
        if not session:
            return {"output": f"MCP server not connected: {server_id}", "error": True}
        result = await session.call_tool(tool_name, arguments or {})
        return {"output": _safe_text(str(result), 12000), "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _opencode_run(prompt: str, cwd: str = ".", model: str = "", agent: str = "") -> dict:
    cmd = shutil.which("opencode")
    if os.name == "nt":
        if cmd:
            parts = [f"& {json.dumps(cmd)} run {json.dumps(prompt)}"]
        else:
            npx = shutil.which("npx.cmd") or shutil.which("npx")
            if not npx:
                return {
                    "output": "OpenCode is not installed and npx is not available. Install with `npm install -g opencode-ai`, then run `opencode auth login`.",
                    "error": True,
                }
            parts = [f"& {json.dumps(npx)} -y opencode-ai run {json.dumps(prompt)}"]
        if model:
            parts.append(f"--model {json.dumps(model)}")
        if agent:
            parts.append(f"--agent {json.dumps(agent)}")
    else:
        if cmd:
            parts = [shlex.quote(cmd), "run", shlex.quote(prompt)]
        else:
            npx = shutil.which("npx")
            if not npx:
                return {
                    "output": "OpenCode is not installed and npx is not available. Install with `npm install -g opencode-ai`, then run `opencode auth login`.",
                    "error": True,
                }
            parts = [shlex.quote(npx), "-y", "opencode-ai", "run", shlex.quote(prompt)]
        if model:
            parts.extend(["--model", shlex.quote(model)])
        if agent:
            parts.extend(["--agent", shlex.quote(agent)])
    return await _run_shell(" ".join(parts), cwd=cwd)


# ── computer use (pyautogui) ────────────────────────────────────────────────
def _shots_dir() -> Path:
    d = ROOT / "data" / "agent_shots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pg():
    import pyautogui
    pyautogui.FAILSAFE = False
    return pyautogui


async def _screenshot() -> dict:
    try:
        pg = _pg()
    except Exception:
        return {"output": "pyautogui not installed. run: pip install pyautogui pillow", "error": True}
    try:
        import time
        img = pg.screenshot()
        w, h = img.size
        path = _shots_dir() / f"shot-{int(time.time() * 1000)}.png"
        img.save(path)
        b64 = base64.b64encode(path.read_bytes()).decode()
        return {
            "output": f"screenshot {w}x{h} saved as {path.name}. screen coords: x 0..{w}, y 0..{h}.",
            "error": False,
            "image": f"data:image/png;base64,{b64}",
        }
    except Exception as e:
        return {"output": str(e), "error": True}


async def _computer_click(x=None, y=None, button="left", clicks=1) -> dict:
    try:
        pg = _pg()
    except Exception:
        return {"output": "pyautogui not installed", "error": True}
    try:
        b = button or "left"
        n = int(clicks or 1)
        if x is not None and y is not None:
            pg.click(int(x), int(y), clicks=n, button=b)
            return {"output": f"{b} click x{n} at ({int(x)},{int(y)})", "error": False}
        pg.click(clicks=n, button=b)
        return {"output": f"{b} click x{n} at current pos", "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _computer_move(x, y) -> dict:
    try:
        pg = _pg()
    except Exception:
        return {"output": "pyautogui not installed", "error": True}
    try:
        pg.moveTo(int(x), int(y), duration=0.1)
        return {"output": f"moved to ({int(x)},{int(y)})", "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _computer_type(text, interval=0.0) -> dict:
    try:
        pg = _pg()
    except Exception:
        return {"output": "pyautogui not installed", "error": True}
    try:
        pg.write(str(text), interval=float(interval or 0))
        return {"output": f"typed {len(str(text))} chars", "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _computer_key(keys: str) -> dict:
    try:
        pg = _pg()
    except Exception:
        return {"output": "pyautogui not installed", "error": True}
    try:
        parts = [k.strip().lower() for k in str(keys).replace(" ", "").split("+") if k.strip()]
        if len(parts) > 1:
            pg.hotkey(*parts)
        elif parts:
            pg.press(parts[0])
        else:
            return {"output": "no key given", "error": True}
        return {"output": f"pressed {keys}", "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


async def _computer_scroll(amount) -> dict:
    try:
        pg = _pg()
    except Exception:
        return {"output": "pyautogui not installed", "error": True}
    try:
        pg.scroll(int(amount))
        return {"output": f"scrolled {amount}", "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


# ── sub-agents ───────────────────────────────────────────────────────────────
async def _run_subagent(task: str, cwd: str = "") -> str:
    from services.agent_runtime import run_agent  # lazy — avoid import cycle
    ctx = get_agent_ctx()
    ep, model = ctx.get("ep"), ctx.get("model")
    if not ep or not model:
        return "[sub-agent error: no endpoint/model in context]"
    sub = dict(_settings())
    sub["agent_max_turns"] = min(int(sub.get("agent_max_turns", 24) or 24), 10)
    sub["agent_subagents"] = False     # no recursive spawning
    if cwd:
        sub["agent_cwd"] = cwd
    stop = asyncio.Event()
    acc, think, steps = [], [], []
    async for _ in run_agent([{"role": "user", "content": task}], ep, model, stop, sub, acc, think, steps):
        pass
    return "".join(acc).strip() or "(no output)"


async def _spawn_agent(task: str, cwd: str = "") -> dict:
    if not task.strip():
        return {"output": "task required", "error": True}
    out = await asyncio.create_task(_run_subagent(task, cwd))  # own context
    return {"output": out, "error": False}


async def _spawn_agents(tasks: list | None) -> dict:
    items = [t for t in (tasks or []) if (t or {}).get("task")]
    if not items:
        return {"output": "no tasks provided", "error": True}
    results = await asyncio.gather(
        *(asyncio.create_task(_run_subagent(it["task"], it.get("cwd", ""))) for it in items),
        return_exceptions=True,
    )
    parts = []
    for i, r in enumerate(results):
        label = items[i]["task"][:60]
        body = f"[error: {r}]" if isinstance(r, Exception) else r
        parts.append(f"### sub-agent {i + 1} — {label}\n{body}")
    return {"output": "\n\n".join(parts), "error": False}


async def execute(name: str, args: dict) -> dict:
    args = args or {}
    if name == "screenshot":
        return await _screenshot()
    if name == "computer_click":
        return await _computer_click(args.get("x"), args.get("y"), args.get("button", "left"), args.get("clicks", 1))
    if name == "computer_move":
        return await _computer_move(args.get("x"), args.get("y"))
    if name == "computer_type":
        return await _computer_type(args.get("text", ""), args.get("interval", 0))
    if name == "computer_key":
        return await _computer_key(args.get("keys", ""))
    if name == "computer_scroll":
        return await _computer_scroll(args.get("amount", 0))
    if name == "spawn_agent":
        return await _spawn_agent(args.get("task", ""), args.get("cwd", ""))
    if name == "spawn_agents":
        return await _spawn_agents(args.get("tasks", []))
    if name in ("shell", "bash"):
        return await _run_shell(args.get("command", "echo no command"), args.get("cwd", ""))
    if name == "read_file":
        return await _read_file(args.get("path", ""), int(args.get("start_line") or 1), int(args.get("end_line") or 0))
    if name == "write_file":
        return await _write_file(args.get("path", ""), args.get("content", ""))
    if name == "edit_file":
        return await _edit_file(args.get("path", ""), args.get("old", ""), args.get("new", ""), bool(args.get("replace_all")))
    if name == "apply_patch":
        return await _apply_patch_text(args.get("patch", ""), args.get("cwd", "."))
    if name == "todo_update":
        return await _todo_update(args.get("items", []))
    if name == "list_files":
        return await _list_files(args.get("path", "."), int(args.get("depth") or 1))
    if name == "glob_files":
        return await _glob_files(args.get("pattern", "*"), args.get("path", "."))
    if name == "grep_files":
        return await _grep_files(args.get("pattern", ""), args.get("path", "."), args.get("file_glob", "*"))
    if name == "web_search":
        return await _web_search(args.get("query", ""), int(args.get("max_results") or 5))
    if name == "web_fetch":
        return await _web_fetch(args.get("url", ""), int(args.get("max_chars") or 12000))
    if name == "memory_search":
        return await _memory_search(args.get("query", ""), int(args.get("top_k") or 8))
    if name == "memory_add":
        return await _memory_add(args.get("text", ""), args.get("category", ""), bool(args.get("pinned")))
    if name == "skill_list":
        return await _skill_list()
    if name == "skill_load":
        return await _skill_load(args.get("name_or_path", ""))
    if name == "mcp_list_tools":
        return await _mcp_list_tools()
    if name == "mcp_call_tool":
        return await _mcp_call_tool(args.get("server_id", ""), args.get("tool_name", ""), args.get("arguments", {}))
    if name == "opencode_run":
        return await _opencode_run(args.get("prompt", ""), args.get("cwd", "."), args.get("model", ""), args.get("agent", ""))
    if name == "git_status":
        return await _git_status(args.get("cwd", "."))
    if name == "git_diff":
        return await _git_diff(args.get("cwd", "."), bool(args.get("staged")), args.get("path", ""))
    if name == "git_branch":
        return await _git_branch(args.get("cwd", "."), args.get("name", ""), bool(args.get("checkout", True)))
    if name == "git_commit":
        return await _git_commit(args.get("cwd", "."), args.get("message", ""), args.get("paths") or None)
    return {"output": f"unknown tool: {name}", "error": True}


async def stream_execute(name: str, args: dict):
    args = args or {}
    if name in ("shell", "bash"):
        async for event in _stream_shell(args.get("command", "echo no command"), args.get("cwd", "")):
            yield event
        return
    result = await execute(name, args)
    yield {"type": "result", "result": result}


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


TOOL_DEFS = [
    _tool("shell", "Run a local shell command. On Windows this uses PowerShell; on Unix it uses bash. Use for tests, builds, git, installs, and system inspection.", {
        "command": {"type": "string"},
        "cwd": {"type": "string", "description": "Working directory, relative to aide root or absolute.", "default": "."},
    }, ["command"]),
    _tool("read_file", "Read a file, optionally with a 1-based line range.", {
        "path": {"type": "string"},
        "start_line": {"type": "integer", "default": 1},
        "end_line": {"type": "integer", "description": "0 means read through EOF.", "default": 0},
    }, ["path"]),
    _tool("write_file", "Create or overwrite a file.", {
        "path": {"type": "string"},
        "content": {"type": "string"},
    }, ["path", "content"]),
    _tool("edit_file", "Edit an existing file by exact string replacement.", {
        "path": {"type": "string"},
        "old": {"type": "string"},
        "new": {"type": "string"},
        "replace_all": {"type": "boolean", "default": False},
    }, ["path", "old", "new"]),
    _tool("apply_patch", "Apply a unified diff patch using git apply. Prefer this for multi-file or structural code edits.", {
        "patch": {"type": "string", "description": "Unified diff text."},
        "cwd": {"type": "string", "default": "."},
    }, ["patch"]),
    _tool("todo_update", "Update the visible agent checklist. Use before starting multi-step work and whenever progress changes.", {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {"type": "string"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                },
                "required": ["step", "status"],
            },
        },
    }, ["items"]),
    _tool("list_files", "List files and folders.", {
        "path": {"type": "string", "default": "."},
        "depth": {"type": "integer", "default": 1},
    }),
    _tool("glob_files", "Find files by glob pattern.", {
        "pattern": {"type": "string", "description": "Example: **/*.py"},
        "path": {"type": "string", "default": "."},
    }, ["pattern"]),
    _tool("grep_files", "Search file contents with a regular expression.", {
        "pattern": {"type": "string"},
        "path": {"type": "string", "default": "."},
        "file_glob": {"type": "string", "default": "*"},
    }, ["pattern"]),
    _tool("web_search", "Search the web using aide's configured search provider/fallback chain.", {
        "query": {"type": "string"},
        "max_results": {"type": "integer", "default": 5},
    }, ["query"]),
    _tool("web_fetch", "Fetch and read a URL.", {
        "url": {"type": "string"},
        "max_chars": {"type": "integer", "default": 12000},
    }, ["url"]),
    _tool("memory_search", "Search aide's long-term memory.", {
        "query": {"type": "string"},
        "top_k": {"type": "integer", "default": 8},
    }, ["query"]),
    _tool("memory_add", "Store a durable memory when the user says something worth remembering.", {
        "text": {"type": "string"},
        "category": {"type": "string", "enum": ["", "identity", "preference", "fact", "task", "contact", "general"], "default": ""},
        "pinned": {"type": "boolean", "default": False},
    }, ["text"]),
    _tool("skill_list", "List available SKILL.md files and cookbook skills.", {}),
    _tool("skill_load", "Load a skill by name, path, or cookbook/name.", {
        "name_or_path": {"type": "string"},
    }, ["name_or_path"]),
    _tool("mcp_list_tools", "List connected MCP tools.", {}),
    _tool("mcp_call_tool", "Call a connected MCP tool.", {
        "server_id": {"type": "string"},
        "tool_name": {"type": "string"},
        "arguments": {"type": "object", "default": {}},
    }, ["server_id", "tool_name"]),
    _tool("opencode_run", "Delegate a coding subtask to OpenCode CLI via `opencode run` when OpenCode is installed and authenticated.", {
        "prompt": {"type": "string"},
        "cwd": {"type": "string", "default": "."},
        "model": {"type": "string", "description": "Optional OpenCode provider/model id."},
        "agent": {"type": "string", "description": "Optional OpenCode agent name."},
    }, ["prompt"]),
    _tool("git_status", "Show git branch and short working tree status.", {
        "cwd": {"type": "string", "default": "."},
    }),
    _tool("git_diff", "Show git diff for review.", {
        "cwd": {"type": "string", "default": "."},
        "staged": {"type": "boolean", "default": False},
        "path": {"type": "string", "default": ""},
    }),
    _tool("git_branch", "Create a git branch, optionally switching to it.", {
        "cwd": {"type": "string", "default": "."},
        "name": {"type": "string"},
        "checkout": {"type": "boolean", "default": True},
    }, ["name"]),
    _tool("git_commit", "Stage files and create a git commit.", {
        "cwd": {"type": "string", "default": "."},
        "message": {"type": "string"},
        "paths": {"type": "array", "items": {"type": "string"}},
    }, ["message"]),
]


COMPUTER_TOOL_DEFS = [
    _tool("screenshot", "Capture the current screen and see it. Always screenshot before clicking/typing so you act on real coordinates.", {}),
    _tool("computer_click", "Click the mouse at screen pixel coordinates (from a screenshot).", {
        "x": {"type": "integer"},
        "y": {"type": "integer"},
        "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
        "clicks": {"type": "integer", "default": 1},
    }, ["x", "y"]),
    _tool("computer_move", "Move the mouse to screen coordinates without clicking.", {
        "x": {"type": "integer"}, "y": {"type": "integer"},
    }, ["x", "y"]),
    _tool("computer_type", "Type text at the current cursor/focus.", {
        "text": {"type": "string"},
        "interval": {"type": "number", "default": 0},
    }, ["text"]),
    _tool("computer_key", "Press a key or combo, e.g. 'enter', 'ctrl+c', 'alt+tab'.", {
        "keys": {"type": "string"},
    }, ["keys"]),
    _tool("computer_scroll", "Scroll vertically. Positive scrolls up, negative down.", {
        "amount": {"type": "integer"},
    }, ["amount"]),
]

SUBAGENT_TOOL_DEFS = [
    _tool("spawn_agent", "Delegate one focused subtask to a fresh sub-agent (own tool loop). Returns its summary. Use for self-contained chunks of a larger job.", {
        "task": {"type": "string", "description": "Clear, self-contained instructions for the sub-agent."},
        "cwd": {"type": "string", "default": ""},
    }, ["task"]),
    _tool("spawn_agents", "Run several sub-agents in parallel on independent subtasks, then get all summaries. Use to fan out work.", {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "cwd": {"type": "string"},
                },
                "required": ["task"],
            },
        },
    }, ["tasks"]),
]


def build_tool_defs(settings: dict) -> list:
    """base tools + optional computer-use / sub-agent tools per settings"""
    defs = list(TOOL_DEFS)
    if (settings or {}).get("agent_computer_use"):
        defs += COMPUTER_TOOL_DEFS
    if (settings or {}).get("agent_subagents", True):
        defs += SUBAGENT_TOOL_DEFS
    # plan mode: hide everything that changes state — read/inspect only
    if (settings or {}).get("agent_permission_mode") == "plan":
        defs = [d for d in defs if d["function"]["name"] not in MUTATING_TOOLS]
    return defs


# tools that change state — gated by approve/plan modes + get a diff preview
MUTATING_TOOLS = {
    "shell", "bash", "write_file", "edit_file", "apply_patch",
    "git_branch", "git_commit",
    "computer_click", "computer_move", "computer_type", "computer_key", "computer_scroll",
    "mcp_call_tool", "opencode_run", "spawn_agent", "spawn_agents",
}
# subset that produces a file diff we can preview
_DIFF_TOOLS = {"write_file", "edit_file", "apply_patch"}


def preview_change(name: str, args: dict) -> str:
    """unified diff for a pending edit, WITHOUT applying it (for diff review)"""
    import difflib
    args = args or {}
    try:
        if name == "apply_patch":
            return (args.get("patch") or "").strip()
        if name == "write_file":
            p = _resolve(args.get("path", ""))
            old = p.read_text("utf-8", errors="replace").splitlines(keepends=True) if p.exists() else []
            new = (args.get("content") or "").splitlines(keepends=True)
        elif name == "edit_file":
            p = _resolve(args.get("path", ""))
            if not p.exists():
                return ""
            text = p.read_text("utf-8", errors="replace")
            o, n = args.get("old", ""), args.get("new", "")
            cnt = text.count(o)
            if cnt == 0:
                return ""
            updated = text.replace(o, n) if args.get("replace_all") else text.replace(o, n, 1)
            old = text.splitlines(keepends=True)
            new = updated.splitlines(keepends=True)
        else:
            return ""
        rel = str(args.get("path", ""))
        diff = difflib.unified_diff(old, new, fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3)
        out = "".join(diff)
        return out if len(out) <= 16000 else out[:16000] + "\n[diff truncated]"
    except Exception:
        return ""


async def agent_status() -> dict:
    from services.memory_store import get_all_memories

    try:
        skills = json.loads((await _skill_list())["output"])
    except Exception:
        skills = []
    try:
        mcp_tools = json.loads((await _mcp_list_tools())["output"])
    except Exception:
        mcp_tools = []
    try:
        memories = get_all_memories()
    except Exception:
        memories = []

    opencode_path = shutil.which("opencode")
    npx_path = shutil.which("npx.cmd") or shutil.which("npx")

    try:
        import importlib.util
        has_pyautogui = importlib.util.find_spec("pyautogui") is not None
    except Exception:
        has_pyautogui = False

    return {
        "root": str(ROOT),
        "tools": [t["function"]["name"] for t in TOOL_DEFS],
        "permissions": TOOL_PERMISSION,
        "tool_count": len(TOOL_DEFS),
        "opencode": {
            "installed": bool(opencode_path),
            "path": opencode_path or "",
            "npx_fallback": bool(npx_path),
            "npx_path": npx_path or "",
        },
        "sandbox": {"docker": bool(shutil.which("docker"))},
        "computer_use": {"pyautogui": has_pyautogui},
        "mcp": {
            "connected_tool_count": len(mcp_tools),
            "tools": mcp_tools[:50],
        },
        "skills": {
            "count": len(skills),
            "items": skills[:50],
        },
        "memory": {
            "count": len(memories),
        },
    }
