"""pi, the coding agent alles runs on the machine that hosts it.

alles installs a pinned pi into the user's cache folder, writes pi's model list from alles's
endpoints (keys go in through env vars, never onto disk), and keeps one `pi --mode rpc`
process per open chat. a chat is one of pi's own session files; each project gets a folder
of them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from core.settings import data_dir

PI_PACKAGE = "@earendil-works/pi-coding-agent"
PI_VERSION = "1.3.0"
OMP_VERSION = "18.12.3"
MIN_NODE = (22, 19)
IDLE_SECONDS = 15 * 60
MAX_RUNNING = 4
LOG_LIMIT = 4000
OUTPUT_LIMIT = 4000
# enough of an edit's old and new text to draw it as a diff
ARGS_LIMIT = 8000

# the harnesses alles drives through pi's rpc protocol. pi is the default: company-backed with
# the smallest issue backlog. omp (oh-my-pi) is a one-person pi fork with 60+ built-in providers
# and an ask-before-commands mode; it speaks the same protocol, so it's one click away.
NATIVE = {
    "pi": {"name": "pi", "version": PI_VERSION, "bin_env": "ALLES_PI_BIN"},
    "omp": {"name": "oh-my-pi", "version": OMP_VERSION, "bin_env": "ALLES_OMP_BIN"},
}
DEFAULT_HARNESS = "pi"
APPROVAL = {"auto": "yolo", "ask": "write"}


def home() -> Path:
    return data_dir() / "pi"


def _tool_dir(harness: str = "pi") -> Path:
    # the install is reinstallable, so it lives in the user cache, not in data that backups copy
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "alles" / f"{harness}-{NATIVE[harness]['version']}"


def bin_path(harness: str = "pi") -> Path:
    # tests point these at a fake
    custom = os.environ.get(NATIVE[harness]["bin_env"])
    if custom:
        return Path(custom)
    return _tool_dir(harness) / ("bin/pi" if harness == "pi" else "omp")


def agent_dir(harness: str = "pi") -> Path:
    return home() / ("agent" if harness == "pi" else f"{harness}-agent")


def sessions_dir(project_id: str, harness: str = "pi") -> Path:
    base = home() / "sessions" / project_id
    return base if harness == "pi" else base / harness


EXTENSION = Path(__file__).parent / "pi_ext" / "alles.ts"
THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
# pi only offers effort levels for a model models.json marks as reasoning, so mark the ones that
# think. a guess from the name; pi clamps a level the model doesn't take
_THINKS = re.compile(
    r"(^|[^a-z0-9])(o1|o3|o4)([^a-z0-9]|$)|gpt-5|gpt5|gemini-(2\.5|[3-9])|deepseek-(r1|reasoner|v3\.[1-9]|v[4-9])"
    r"|qwen3|qwq|thinking|reason|kimi-k2|glm-(4\.[5-9]|[5-9])|grok-(3-mini|[4-9])|minimax-m|magistral"
)


# alles's own tools pi can use through the bridge: docs, tasks, calendar, memory and the rest.
# pi has its own file, shell and web tools; browser, computer, server and outgoing mail stay
# with Aide, where their approvals live
_BRIDGE_SKIP = ("browse_", "computer_", "server_", "adguard_", "npm_", "files_operation", "github_")
_BRIDGE_SKIP_NAMES = {"mail_send", "search_code", "screenshot", "spawn_agent", "spawn_agents"}
_BRIDGE_EXTRA = {"memory_search", "memory_add", "skill_list", "skill_load", "skill_match"}


def bridge_tools() -> list[dict]:
    from services.agent_tools import APP_TOOL_DEFS, MUTATING_TOOLS, TOOL_DEFS

    picked = [t for t in TOOL_DEFS if t["function"]["name"] in _BRIDGE_EXTRA] + [
        t
        for t in APP_TOOL_DEFS
        if not t["function"]["name"].startswith(_BRIDGE_SKIP)
        and t["function"]["name"] not in _BRIDGE_SKIP_NAMES
    ]
    return [
        {
            "name": "alles_" + t["function"]["name"],
            "tool": t["function"]["name"],
            "description": t["function"]["description"],
            "parameters": t["function"]["parameters"],
            "changes": t["function"]["name"] in MUTATING_TOOLS,
        }
        for t in picked
    ]


# where Aide's brief to pi starts in a handed-over task (agent_tools._pi_run_stream writes it)
HANDOFF_MARK = "\n\n(handed over by Aide"


def split_handoff(text: str) -> tuple[str, bool]:
    """the owner-facing task, and whether Aide handed it over; the brief is for pi only."""
    task, mark, _ = (text or "").partition(HANDOFF_MARK)
    return (task.strip(), True) if mark else (text, False)


def private_paths() -> list[str]:
    """folders and files pi must never read or change: alles's data (its database, vault keys,
    uploads), shell history and ssh keys. alles's own data reaches pi only through its tools."""
    home = Path.home()
    paths = [
        data_dir(),
        home / ".ssh",
        home / ".bash_history",
        home / ".zsh_history",
        home / ".gnupg",
    ]
    return sorted({str(Path(p).expanduser().resolve()) for p in paths})


def thinks(model: str) -> bool:
    name = (model or "").lower().split("/")[-1]
    if "claude" in name:
        return not re.search(r"claude-(instant|2|3-5|3\.5|3-(opus|sonnet|haiku))", name)
    return bool(_THINKS.search(name))


# replaces pi's default prompt. kept short on purpose: every token here is paid on every request
SYSTEM_PROMPT = """You are pi, a coding agent on the owner's machine, working in the current folder through alles.
Tools: read (view files), bash (run commands; prefer rg and fd), edit (exact-text replace; one call per file with several edits; keep oldText short and unique), write (new files or full rewrites only), web_search and web_fetch (docs, errors, releases, anything that may have changed).
Work:
- Read before changing. Make the smallest change that solves it and match the code around it.
- After editing, run the relevant test, build or lint and say what you ran and what happened. Never claim something works without checking.
- Ask one short question only when a real choice blocks you.
- Secrets show as {{secret:NAME}}. Use that text as-is in commands and files; it becomes the real value only when a tool runs. Never print, log or commit secrets.
- Deleting data, force-pushing, rewriting git history or touching files outside this folder needs the owner's yes.
Replies: short and plain. Lead with the result. Give file paths as path:line. No filler."""


def settings() -> dict:
    from core.settings import load_settings

    saved = load_settings()
    harness = saved.get("coding_harness") or DEFAULT_HARNESS
    return {
        "harness": harness,
        "approval": saved.get("coding_approval") or "auto",
        "guard": saved.get("coding_guard", True) is not False,
        # effort new pi chats start with; "" leaves pi's own default
        "thinking": saved.get("coding_thinking")
        if saved.get("coding_thinking") in THINKING_LEVELS
        else "",
    }


# ── install ──

_install = {name: {"task": None, "error": ""} for name in NATIVE}


def node_version() -> tuple[int, int] | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        out = subprocess.run([node, "-v"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.match(r"v(\d+)\.(\d+)", out.strip())
    return (int(found.group(1)), int(found.group(2))) if found else None


def installed_version(harness: str = "pi") -> str:
    wanted = NATIVE[harness]["version"]
    if os.environ.get(NATIVE[harness]["bin_env"]):
        return wanted if bin_path(harness).exists() else ""
    if harness == "omp":
        marker = _tool_dir("omp") / "VERSION"
        return marker.read_text().strip() if marker.exists() and bin_path("omp").exists() else ""
    package = _tool_dir() / "lib" / "node_modules" / PI_PACKAGE / "package.json"
    try:
        return json.loads(package.read_text()).get("version") or ""
    except (OSError, ValueError):
        return ""


def status(harness: str = "pi") -> dict:
    version = installed_version(harness)
    wanted = NATIVE[harness]["version"]
    base = {
        "harness": harness,
        "name": NATIVE[harness]["name"],
        "version": version,
        "wanted": wanted,
    }
    if harness == "pi":
        node = node_version()
        base["node"] = ".".join(map(str, node or ()))
    task = _install[harness]["task"]
    if task is not None and not task.done():
        return {**base, "state": "installing"}
    if version == wanted and bin_path(harness).exists():
        return {**base, "state": "ready"}
    if harness == "pi" and (node is None or node < MIN_NODE):
        return {**base, "state": "needs_node", "error": "pi needs node 22.19 or newer"}
    if _install[harness]["error"]:
        return {**base, "state": "failed", "error": _install[harness]["error"]}
    return {**base, "state": "missing"}


async def _communicate(proc, what: str, stdin: bytes | None = None) -> str:
    try:
        _, err = await asyncio.wait_for(proc.communicate(stdin), timeout=600)
    except TimeoutError:
        proc.kill()
        return f"installing {what} took longer than 10 minutes"
    if proc.returncode != 0:
        tail = (err or b"").decode(errors="replace").strip().splitlines()[-1:] or ["install failed"]
        return tail[0][:300]
    return ""


async def _run_install(harness: str = "pi") -> None:
    tool = _tool_dir(harness)
    tool.mkdir(parents=True, exist_ok=True)
    if harness == "omp":
        # omp's own installer: a prebuilt binary for this machine, checked against its sha256
        from services.net_guard import safe_get_public_async

        try:
            script = await safe_get_public_async(
                "https://omp.sh/install", timeout=30, max_bytes=200_000
            )
            script.raise_for_status()
        except Exception as exc:
            _install[harness]["error"] = (
                f"could not download the omp installer ({type(exc).__name__})"
            )
            return
        proc = await asyncio.create_subprocess_exec(
            "sh",
            "-s",
            "--",
            "--binary",
            "--ref",
            f"v{OMP_VERSION}",
            env={**os.environ, "PI_INSTALL_DIR": str(tool)},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        error = await _communicate(proc, "omp", script.content)
        if not error:
            (tool / "VERSION").write_text(OMP_VERSION)
        _install[harness]["error"] = error
        return
    npm = shutil.which("npm")
    if not npm:
        _install[harness]["error"] = "npm was not found next to node"
        return
    proc = await asyncio.create_subprocess_exec(
        npm,
        "install",
        "-g",
        "--prefix",
        str(tool),
        # pi's own docs install it this way; no package scripts run
        "--ignore-scripts",
        "--no-audit",
        "--no-fund",
        f"{PI_PACKAGE}@{PI_VERSION}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _install[harness]["error"] = await _communicate(proc, "pi")


def ensure_installed(harness: str = "pi") -> dict:
    """start the install in the background when it's missing; safe to call often."""
    current = status(harness)
    if current["state"] in ("missing", "failed"):
        _install[harness]["error"] = ""
        _install[harness]["task"] = asyncio.get_running_loop().create_task(_run_install(harness))
        return {**current, "state": "installing", "error": ""}
    return current


# ── models ──


def _api_and_base(endpoint) -> tuple[str, str]:
    from services.llm import detect_provider

    adapter = (endpoint.provider_adapter or "auto").lower()
    kind = detect_provider(endpoint.base_url) if adapter == "auto" else adapter
    parts = urlsplit((endpoint.base_url or "").rstrip("/"))
    path = parts.path.rstrip("/")
    if kind == "anthropic":
        return "anthropic-messages", urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    if "googleapis.com" in parts.netloc and "/openai" not in path:
        path = "/v1beta/openai"
    elif not path:
        path = "/v1"
    return "openai-completions", urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _provider_id(endpoint) -> str:
    return "alles-" + re.sub(r"[^a-z0-9]+", "-", str(endpoint.id).lower()).strip("-")


def model_config(db) -> tuple[dict, dict, list[dict]]:
    """pi's models.json, the env vars holding the keys, and the choices for the picker."""
    from core.database import ModelEndpoint
    from services.model_catalog import is_chat_model

    providers, env, choices = {}, {}, []
    rows = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()  # noqa: E712
    for index, endpoint in enumerate(rows):
        if (endpoint.auth_type or "api_key") != "api_key":
            continue  # oauth sign-ins stay inside alles
        if urlsplit(endpoint.base_url or "").scheme not in ("http", "https"):
            continue
        try:
            models = [m for m in json.loads(endpoint.cached_models or "[]") if is_chat_model(m)]
        except ValueError:
            models = []
        if not models:
            continue
        api, base = _api_and_base(endpoint)
        key_var = f"ALLES_PI_KEY_{index}"
        env[key_var] = endpoint.api_key or "none"
        provider = _provider_id(endpoint)
        providers[provider] = {
            "baseUrl": base,
            "api": api,
            "apiKey": "$" + key_var,
            "models": [{"id": m, **({"reasoning": True} if thinks(m) else {})} for m in models],
        }
        choices += [
            {
                "endpoint_id": endpoint.id,
                "endpoint": endpoint.name,
                "model": m,
                "provider": provider,
                "thinks": thinks(m),
            }
            for m in models
        ]
    return {"providers": providers}, env, choices


def resolve_choice(db, endpoint_id: str = "", model: str = "") -> dict | None:
    """the exact model asked for, else the coding default, else nothing."""
    _, _, choices = model_config(db)
    if endpoint_id and model:
        return next(
            (c for c in choices if c["endpoint_id"] == endpoint_id and c["model"] == model), None
        )
    from services.model_resolver import ModelResolutionError, resolve_model

    try:
        picked = resolve_model(db, "coding")
    except ModelResolutionError:
        return choices[0] if choices else None
    return next(
        (
            c
            for c in choices
            if c["endpoint_id"] == picked.endpoint.id and c["model"] == picked.model
        ),
        choices[0] if choices else None,
    )


# ── projects ──


def check_folder(raw: str) -> Path:
    path = Path(os.path.expanduser(str(raw or "").strip()))
    if not path.is_absolute():
        raise ValueError("use a full folder path, like /home/me/project")
    path = path.resolve()
    if not path.is_dir():
        raise ValueError("that folder does not exist on this machine")
    if path == Path(path.anchor):
        raise ValueError("pick a project folder, not the whole disk")
    private = data_dir().resolve()
    if path == private or private in path.parents:
        raise ValueError("alles keeps its private data there; pick another folder")
    return path


def public_project(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "path": row.path,
        "exists": Path(row.path).is_dir(),
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
    }


# ── chats (pi session files) ──


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content or []
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _entries(path: Path) -> list[dict]:
    rows = []
    with path.open("rb") as handle:
        for line in handle:
            with contextlib.suppress(ValueError):
                rows.append(json.loads(line))
    return rows


def find_chat(project_id: str, chat_id: str) -> tuple[Path, str] | None:
    """the session file behind a chat and the harness that wrote it."""
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", chat_id or ""):
        return None
    for harness in NATIVE:
        folder = sessions_dir(project_id, harness)
        found = (
            next(iter(sorted(folder.glob(f"*_{chat_id}.jsonl"))), None) if folder.is_dir() else None
        )
        if found:
            return found, harness
    from services import acp_agent

    path = acp_agent.log_dir(project_id) / f"{chat_id}.jsonl"
    if path.exists():
        head = acp_agent.read_head(path) or {}
        return path, head.get("harness") or "acp"
    return None


def _chat_file(project_id: str, chat_id: str) -> Path | None:
    found = find_chat(project_id, chat_id)
    return found[0] if found and found[1] in NATIVE else None


def chat_summary(path: Path) -> dict | None:
    try:
        entries = _entries(path)
    except OSError:
        return None
    # omp writes a title line before the session header
    head = next((e for e in entries[:3] if e.get("type") == "session"), None)
    if not head:
        return None
    name, first, handed = "", "", False
    for entry in entries:
        if entry.get("type") == "session_info" and entry.get("name"):
            name = entry["name"]
        message = entry.get("message") or {}
        if not first and entry.get("type") == "message" and message.get("role") == "user":
            first, handed = split_handoff(_text_of(message.get("content")).strip())
    return {
        "id": head.get("id"),
        "title": name or (first[:80] if first else "new chat"),
        "from_aide": bool(first) and handed,
        "created_at": head.get("timestamp"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)),
    }


def list_chats(project_id: str) -> list[dict]:
    from services import acp_agent

    rows = []
    for harness in NATIVE:
        folder = sessions_dir(project_id, harness)
        if folder.is_dir():
            for path in folder.glob("*.jsonl"):
                if row := chat_summary(path):
                    rows.append({**row, "harness": harness})
    rows += acp_agent.list_chats(project_id)
    for row in rows:
        row["running"] = bool((live := _chats.get(row["id"])) and live.busy)
    return sorted(rows, key=lambda row: row["updated_at"], reverse=True)


def _short(value, limit=OUTPUT_LIMIT) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"\n… {len(text) - limit} more characters"


def transcript(project_id: str, chat_id: str) -> dict | None:
    """the active branch as simple items: user, assistant (text + tool calls), tool results."""
    found = find_chat(project_id, chat_id)
    if found is None:
        return None
    path, harness = found
    if harness not in NATIVE:
        from services import acp_agent

        return acp_agent.transcript(project_id, chat_id)
    entries = [e for e in _entries(path) if e.get("id") and e.get("type") != "session"]
    model = {}
    by_id = {e["id"]: e for e in entries}
    branch, node = [], entries[-1] if entries else None
    while node is not None:
        branch.append(node)
        node = by_id.get(node.get("parentId"))
    items = []
    for entry in reversed(branch):
        if entry.get("type") == "model_change":
            named = entry.get("model")
            if isinstance(named, str) and "/" in named:  # omp: "provider/model"
                provider, _, model_id = named.partition("/")
                model = {"provider": provider, "model": model_id}
            elif isinstance(named, dict):
                model = {"provider": named.get("provider"), "model": named.get("id")}
            else:
                model = {"provider": entry.get("provider"), "model": entry.get("modelId")}
        if entry.get("type") != "message":
            continue
        message = entry.get("message") or {}
        role = message.get("role")
        if role == "user":
            task, handed = split_handoff(_text_of(message.get("content")))
            items.append({"kind": "user", "text": task, **({"from_aide": True} if handed else {})})
        elif role == "assistant":
            items.append(_assistant_item(message))
        elif role == "toolResult":
            items.append(
                {
                    "kind": "tool_done",
                    "id": message.get("toolCallId"),
                    "ok": not message.get("isError"),
                    "output": _short(_text_of(message.get("content"))),
                }
            )
    return {"items": items, "model": model, "harness": harness}


def _assistant_item(message: dict) -> dict:
    content = message.get("content") or []
    tools = [
        {
            "id": block.get("id"),
            "name": block.get("name"),
            "args": _short(block.get("arguments"), ARGS_LIMIT),
        }
        for block in content
        if isinstance(block, dict) and block.get("type") == "toolCall"
    ]
    item = {"kind": "assistant", "text": _text_of(content), "tools": tools}
    if message.get("errorMessage"):
        item["error"] = str(message["errorMessage"])[:500]
    return item


# ── running chats ──

_chats: dict[str, PiChat] = {}


def _clean_env(keys: dict, harness: str = "pi") -> dict:
    # harnesses run model-written commands; they get the user's shell env, not alles's secrets
    env = {k: v for k, v in os.environ.items() if not k.startswith("ALLES_")}
    env = {**env, **keys, "PI_CODING_AGENT_DIR": str(agent_dir(harness))}
    if harness == "pi":
        env["PI_OFFLINE"] = "1"
    else:
        env["OMP_SKIP_SETUP"] = "1"
    return env


def _goal_file(chat_id: str) -> Path:
    return home() / "goals" / f"{re.sub(r'[^A-Za-z0-9_-]', '', chat_id)}.txt"


def load_goal(chat_id: str) -> str:
    path = _goal_file(chat_id)
    return path.read_text(encoding="utf-8").strip() if chat_id and path.is_file() else ""


def save_goal(chat_id: str, text: str) -> None:
    path = _goal_file(chat_id)
    if not text:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text[:4000], encoding="utf-8")


def _secrets_file(chat_id: str) -> Path:
    return home() / "secrets" / f"{chat_id}.json"


def load_secrets(chat_id: str) -> dict[str, str]:
    from services.secretstore import unseal

    try:
        return json.loads(unseal(_secrets_file(chat_id).read_text(), f"pi.secrets.{chat_id}"))
    except (OSError, ValueError):
        return {}


def save_secrets(chat_id: str, secrets: dict[str, str]) -> None:
    """sealed with alles's key, like every other stored secret."""
    from services.secretstore import seal

    path = _secrets_file(chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(seal(json.dumps(secrets), f"pi.secrets.{chat_id}"))
    path.chmod(0o600)


def _b64(value: dict) -> str:
    import base64

    return base64.b64encode(json.dumps(value).encode()).decode()


_bridge_tokens: dict[str, str] = {}


def bridge_chat(token: str):
    """the running chat a web-tool call from pi belongs to, if the token is real."""
    chat_id = _bridge_tokens.get(token or "")
    return _chats.get(chat_id) if chat_id else None


def _write_models(harness: str, config: dict) -> None:
    folder = agent_dir(harness)
    folder.mkdir(parents=True, exist_ok=True)
    if harness == "pi":
        (folder / "models.json").write_text(json.dumps(config, indent=1))
        (folder / "SYSTEM.md").write_text(SYSTEM_PROMPT)
        return
    # omp reads models.yml, names the key's env var without a "$", and json is valid yaml
    providers = {
        name: {**provider, "apiKey": str(provider.get("apiKey", "")).lstrip("$")}
        for name, provider in config.get("providers", {}).items()
    }
    (folder / "models.yml").write_text(json.dumps({"providers": providers}, indent=1))


class PiChat:
    def __init__(self, project, choice: dict, harness: str = "pi"):
        self.harness = harness
        self.harness_name = NATIVE[harness]["name"]
        self.project_id = project.id
        self.cwd = project.path
        self.choice = choice
        self.id = ""
        self.proc = None
        self.busy = False
        self.log: list[dict] = []
        self.seq = 0
        self.listeners: set[asyncio.Queue] = set()
        self.waiting: dict[str, asyncio.Future] = {}
        self.questions: dict[str, dict] = {}
        self.last_active = time.monotonic()
        self.stats: dict = {}
        self.partial = ""
        self.secrets: dict[str, str] = {}
        self._bridge = ""
        self._first_delta = 0.0
        self._turn_start = 0.0
        self._speeds: list[float] = []
        self._reader = None
        self._tasks: set[asyncio.Task] = set()
        # pi's effort for this chat and the levels its model takes
        self.thinking: dict = {"level": "", "levels": []}
        # "allow" when Aide handed this work over (its approval covers the task) or code runs
        # on auto; "ask" makes pi check with the owner before an alles tool changes anything
        self.writes = "allow" if settings()["approval"] == "auto" else "ask"

    # process

    async def start(self, db, chat_file: Path | None) -> None:
        config, keys, _ = model_config(db)
        _write_models(self.harness, config)
        folder = sessions_dir(self.project_id, self.harness)
        folder.mkdir(parents=True, exist_ok=True)
        args = [str(bin_path(self.harness)), "--mode", "rpc", "--session-dir", str(folder)]
        extra = {}
        if self.harness == "pi":
            args += ["--provider", self.choice["provider"], "--model", self.choice["model"]]
            # no auto-discovered skills (they cost tens of thousands of tokens a request)
            args += ["--no-skills", "--extension", str(EXTENSION)]
            if settings()["thinking"] and chat_file is None:
                args += ["--thinking", settings()["thinking"]]
            if chat_file is not None:
                args += ["--session", str(chat_file)]
                head = next((e for e in _entries(chat_file)[:3] if e.get("type") == "session"), {})
                self.secrets = load_secrets(str(head.get("id") or ""))
            from core.settings import get_port

            self._bridge = uuid.uuid4().hex
            extra = {
                "PI_ALLES_SECRETS": _b64(self.secrets),
                "PI_ALLES_BRIDGE_URL": f"http://127.0.0.1:{get_port()}/pi-bridge",
                "PI_ALLES_BRIDGE_TOKEN": self._bridge,
                "PI_ALLES_GUARD": "on" if settings().get("guard", True) else "off",
                "PI_ALLES_TOOLS": _b64({"tools": bridge_tools()}),
                # pi never reads or touches these; alles's own data goes through the alles tools
                "PI_ALLES_PRIVATE": _b64({"paths": private_paths()}),
                "PI_ALLES_WRITES": self.writes,
            }
        else:
            args += ["--model", f"{self.choice['provider']}/{self.choice['model']}"]
            args += ["--approval-mode", APPROVAL.get(settings()["approval"], "yolo")]
            if chat_file is not None:
                args += ["--resume", str(chat_file)]
        self.proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.cwd,
            env=_clean_env({**keys, **extra}, self.harness),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=32 * 1024 * 1024,
        )
        self._reader = asyncio.create_task(self._read())
        state = await self.command("get_state")
        self.id = str(state.get("sessionId") or "")
        if not self.id:
            await self.close()
            raise RuntimeError(f"{self.harness_name} started without a session")
        _chats[self.id] = self
        if self._bridge:
            _bridge_tokens[self._bridge] = self.id
        await self.load_thinking()

    async def close(self) -> None:
        proc = self.proc
        if proc is None:
            return
        with contextlib.suppress(Exception):
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
        if _chats.get(self.id) is self:
            _chats.pop(self.id, None)
        _bridge_tokens.pop(self._bridge, None)

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def command(self, kind: str, timeout: float = 30, **fields) -> dict:
        if not self.alive:
            raise RuntimeError("pi is not running for this chat")
        request = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.waiting[request] = future
        self.proc.stdin.write((json.dumps({"id": request, "type": kind, **fields}) + "\n").encode())
        await self.proc.stdin.drain()
        try:
            reply = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.waiting.pop(request, None)
        if not reply.get("success"):
            raise RuntimeError(str(reply.get("error") or f"pi refused {kind}")[:300])
        return reply.get("data") or {}

    # what the browser sees

    def emit(self, event: dict) -> None:
        self.seq += 1
        if self.secrets:
            # last line of defense: nothing shown or kept holds a secret's real value
            from services.secret_scan import hide

            event = {
                k: hide(v, self.secrets) if isinstance(v, str) else v for k, v in event.items()
            }
        event = {**event, "seq": self.seq}
        self.log.append(event)
        if len(self.log) > LOG_LIMIT:
            del self.log[: len(self.log) - LOG_LIMIT]
        for queue in list(self.listeners):
            queue.put_nowait(event)

    async def _read(self) -> None:
        try:
            while line := await self.proc.stdout.readline():
                with contextlib.suppress(ValueError):
                    await self._handle(json.loads(line))
        finally:
            for future in self.waiting.values():
                if not future.done():
                    future.set_exception(RuntimeError("pi stopped"))
            if self.busy:
                self.busy = False
                self.emit({"kind": "error", "text": "pi stopped unexpectedly"})
                self.emit({"kind": "idle"})
            if _chats.get(self.id) is self:
                _chats.pop(self.id, None)

    async def _handle(self, record: dict) -> None:
        kind = record.get("type")
        if kind == "response":
            future = self.waiting.get(record.get("id"))
            if future is not None and not future.done():
                future.set_result(record)
            return
        self.last_active = time.monotonic()
        if kind == "turn_start":
            self._turn_start = time.monotonic()
        if kind == "agent_start":
            self.busy = True
            self._speeds = []
            self.emit({"kind": "busy"})
        elif kind == "message_update":
            update = record.get("assistantMessageEvent") or {}
            if update.get("type") in ("text_delta", "thinking_delta", "toolcall_delta"):
                if not self._first_delta:
                    self._first_delta = time.monotonic()
                if update.get("type") == "text_delta":
                    self.partial += update.get("delta", "")
                    self.emit({"kind": "delta", "text": update.get("delta", "")})
                elif update.get("type") == "thinking_delta":
                    # shown live while pi thinks; pi keeps its own record of it
                    self.emit({"kind": "thinking", "text": update.get("delta", "")})
        elif kind == "message_end":
            message = record.get("message") or {}
            if message.get("role") == "assistant":
                self.partial = ""
                self._speed(message.get("usage") or {})
                self.emit(_assistant_item(message))
        elif kind == "tool_execution_start":
            self.emit(
                {
                    "kind": "tool",
                    "id": record.get("toolCallId"),
                    "name": record.get("toolName"),
                    "args": _short(record.get("args"), ARGS_LIMIT),
                }
            )
        elif kind == "tool_execution_end":
            result = record.get("result") or {}
            self.emit(
                {
                    "kind": "tool_done",
                    "id": record.get("toolCallId"),
                    "ok": not record.get("isError"),
                    "output": _short(_text_of(result.get("content"))),
                }
            )
        elif kind in ("agent_settled", "session_settled"):  # pi, omp
            self.busy = False
            # the reader can't wait on its own reply, so stats come from a side task
            task = asyncio.get_running_loop().create_task(self._settle())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        elif kind == "extension_ui_request":
            await self._question(record)

    def _speed(self, usage: dict) -> None:
        now, first, self._first_delta = time.monotonic(), self._first_delta, 0.0
        output = usage.get("output") or 0
        # generation speed from the first token; a reply that lands in one chunk counts its wait too
        started = first if first and now - first > 0.2 else self._turn_start
        if output and started and now - started > 0.05:
            self._speeds.append(output / (now - started))

    async def _settle(self) -> None:
        await self._refresh_stats()
        self.emit({"kind": "idle"})

    async def _refresh_stats(self) -> None:
        try:
            data = await self.command("get_session_stats", timeout=10)
        except Exception:
            return
        tokens = data.get("tokens") or {}
        prompt = (
            (tokens.get("input") or 0)
            + (tokens.get("cacheRead") or 0)
            + (tokens.get("cacheWrite") or 0)
        )
        speed = sum(self._speeds) / len(self._speeds) if self._speeds else None
        usage = data.get("contextUsage") or {}
        self.stats = {
            "tokens_per_second": round(speed, 1) if speed else self.stats.get("tokens_per_second"),
            "cache_hit_rate": round((tokens.get("cacheRead") or 0) / prompt, 3) if prompt else None,
            "input_tokens": tokens.get("input") or 0,
            "output_tokens": tokens.get("output") or 0,
            "cache_read_tokens": tokens.get("cacheRead") or 0,
            "context_percent": usage.get("percent"),
            "context_tokens": usage.get("tokens"),
            "context_window": usage.get("contextWindow"),
            "cost": data.get("cost") or 0,
        }
        self._counts = {
            k: data.get(k) or 0 for k in ("userMessages", "assistantMessages", "toolCalls")
        }
        self.emit({"kind": "stats", **self.stats})

    async def _question(self, record: dict) -> None:
        method = record.get("method")
        if method not in ("confirm", "select"):
            # notices and editors have no place in this view; dialogs we can't show are declined
            if method in ("input", "editor"):
                await self._reply_question(record.get("id"), {"cancelled": True})
            return
        question = {
            "id": record.get("id"),
            "method": method,
            "title": str(record.get("title") or record.get("message") or "pi has a question")[:500],
            "options": [str(o)[:200] for o in (record.get("options") or [])][:12],
        }
        self.questions[question["id"]] = question
        self.emit({"kind": "question", **question})

    async def _reply_question(self, question_id: str, answer: dict) -> None:
        payload = {"type": "extension_ui_response", "id": question_id, **answer}
        self.proc.stdin.write((json.dumps(payload) + "\n").encode())
        await self.proc.stdin.drain()

    async def answer(self, question_id: str, value) -> None:
        question = self.questions.pop(question_id, None)
        if question is None:
            raise KeyError(question_id)
        if value is None:
            answer = {"cancelled": True}
        elif question["method"] == "confirm":
            answer = {"confirmed": bool(value)}
        else:
            if value not in question["options"]:
                raise ValueError("pick one of the offered options")
            answer = {"value": value}
        await self._reply_question(question_id, answer)
        self.emit({"kind": "answered", "id": question_id})

    # what the owner does

    async def send(self, text: str, echo: bool = True) -> int:
        """returns the seq of the user event, so a browser can follow from there."""
        self.last_active = time.monotonic()
        if self.harness == "pi":
            from services.secret_scan import mask

            text, found = mask(text, self.secrets)
            fresh = {k: v for k, v in found.items() if k not in self.secrets}
            if fresh:
                # pi's extension learns them before the prompt that uses them; no model sees this
                await self.command("prompt", message=f"/alles-secret {_b64(fresh)}")
                self.secrets.update(fresh)
                save_secrets(self.id, self.secrets)
        if echo:
            task, handed = split_handoff(text)
            self.emit({"kind": "user", "text": task, **({"from_aide": True} if handed else {})})
        seq = self.seq
        if self.busy:
            await self.command("prompt", message=text, streamingBehavior="steer")
        else:
            await self.command("prompt", message=text)
        return seq

    async def stop(self) -> None:
        if self.busy:
            await self.command("abort", timeout=30)
            self.emit({"kind": "note", "text": "stopped"})

    async def set_model(self, choice: dict) -> None:
        await self.command("set_model", provider=choice["provider"], modelId=choice["model"])
        self.choice = choice
        await self.load_thinking()

    async def load_thinking(self) -> dict:
        if self.harness != "pi":
            return self.thinking
        with contextlib.suppress(RuntimeError, TimeoutError):
            levels = (await self.command("get_available_thinking_levels", timeout=10)).get("levels")
            state = await self.command("get_state", timeout=10)
            self.thinking = {
                "level": str(state.get("thinkingLevel") or ""),
                "levels": [str(level) for level in levels or [] if level in THINKING_LEVELS],
            }
        return self.thinking

    async def set_thinking(self, level: str) -> dict:
        await self.command("set_thinking_level", level=level)
        return await self.load_thinking()

    async def commands(self) -> list[dict]:
        """pi's extension commands and prompt templates; each runs as a "/name" prompt."""
        if self.harness != "pi":
            return []
        data = await self.command("get_commands", timeout=10)
        return [
            {
                "name": str(c.get("name") or ""),
                "description": str(c.get("description") or "")[:200],
                "source": str(c.get("source") or ""),
            }
            for c in data.get("commands") or []
            # alles's own bridge commands aren't for typing
            if c.get("name") and not str(c.get("name")).startswith("alles-")
        ]

    async def compact(self, instructions: str = "") -> None:
        self.emit({"kind": "note", "text": "compacting the context…"})
        fields = {"customInstructions": instructions} if instructions else {}
        try:
            data = await self.command("compact", timeout=600, **fields)
        except RuntimeError as exc:
            # pi says why (often "session too small"); that answers the command
            self.emit({"kind": "note", "text": f"nothing compacted: {str(exc)[:200].lower()}"})
            return
        await self._refresh_stats()
        self.emit(
            {
                "kind": "compacted",
                "before": data.get("tokensBefore"),
                "after": data.get("estimatedTokensAfter"),
                "window": self.stats.get("context_window"),
                "summary": _short(data.get("summary") or "", 1200),
            }
        )

    async def show_context(self) -> None:
        await self._refresh_stats()
        self.emit(
            {
                "kind": "context",
                "tokens": self.stats.get("context_tokens"),
                "window": self.stats.get("context_window"),
                "percent": self.stats.get("context_percent"),
                "input": self.stats.get("input_tokens"),
                "output": self.stats.get("output_tokens"),
                "cache_read": self.stats.get("cache_read_tokens"),
                "cost": self.stats.get("cost"),
                "model": self.choice.get("model", ""),
                "thinking": self.thinking.get("level", ""),
                **getattr(self, "_counts", {}),
            }
        )

    async def builtin(self, text: str) -> int | None:
        """alles's own / commands for a pi chat; None when the text isn't one."""
        name, _, rest = text.strip().partition(" ")
        rest = rest.strip()
        first = self.seq + 1  # the browser follows from the first event this makes
        if name == "/compact":
            await self.compact(rest)
        elif name == "/context":
            await self.show_context()
        elif name == "/goal":
            if not rest:
                goal = load_goal(self.id)
                self.emit({"kind": "goal", "text": goal, "state": "shown" if goal else "none"})
            elif rest == "clear":
                save_goal(self.id, "")
                self.emit({"kind": "goal", "text": "", "state": "cleared"})
            else:
                save_goal(self.id, rest)
                self.emit({"kind": "goal", "text": rest, "state": "set"})
                await self.send(
                    f"Goal: {rest}\n\nWork toward this goal until it is done or you are blocked. "
                    "End each reply with a short checklist: what is done, what is left.",
                    echo=False,  # the goal card shows it
                )
        else:
            return None
        return first


def live_chat(chat_id: str) -> PiChat | None:
    chat = _chats.get(chat_id)
    return chat if chat is not None and chat.alive else None


async def open_chat(
    db, project, chat_id: str | None, choice: dict, harness: str | None = None, handed: bool = False
):
    """the running harness for this chat, starting one (new or from its saved file) if needed.
    handed: Aide gave pi this work, so the approval Aide already got covers pi's changes."""
    if chat_id and (chat := live_chat(chat_id)):
        return chat
    chat_file = None
    if chat_id:
        found = find_chat(project.id, chat_id)
        if found is None:
            raise LookupError("chat not found")
        chat_file, harness = found
    harness = harness or settings()["harness"]
    if sum(1 for c in _chats.values() if c.alive) >= MAX_RUNNING:
        await _close_oldest_idle()
    if harness not in NATIVE:
        return await _open_acp(project, harness, chat_id, chat_file)
    chat = PiChat(project, choice, harness)
    if handed:
        chat.writes = "allow"
    await chat.start(db, chat_file)
    return chat


async def _open_acp(project, harness: str, chat_id: str | None, chat_file: Path | None):
    from services import acp_agent, harnesses

    entry = harnesses.find(await harnesses.refresh_registry(), harness)
    started = harnesses.launch(entry) if entry else None
    if not started:
        raise RuntimeError(f"{harness} isn't installed; install it under more harnesses first")
    resume = None
    if chat_file is not None:
        head = acp_agent.read_head(chat_file) or {}
        resume = {"chat_id": chat_id, "acp_session": head.get("acp_session")}
    chat = acp_agent.AcpChat(project, entry, *started)
    await chat.start(resume)
    return chat


async def _close_oldest_idle() -> None:
    idle = sorted((c for c in _chats.values() if not c.busy), key=lambda c: c.last_active)
    if not idle:
        raise RuntimeError(f"{MAX_RUNNING} chats are already working; stop one first")
    await idle[0].close()


async def close_idle() -> int:
    """the job that stops pi processes nobody has used for a while."""
    now, closed = time.monotonic(), 0
    for chat in list(_chats.values()):
        if not chat.busy and not chat.listeners and now - chat.last_active > IDLE_SECONDS:
            await chat.close()
            closed += 1
    return closed


async def close_all() -> None:
    for chat in list(_chats.values()):
        await chat.close()


async def delete_chat(project_id: str, chat_id: str) -> bool:
    found = find_chat(project_id, chat_id)
    if found is None:
        return False
    path = found[0]
    if chat := _chats.get(chat_id):
        await chat.close()
    path.unlink()
    _secrets_file(chat_id).unlink(missing_ok=True)
    return True


async def forget_project(project_id: str) -> None:
    """stop its chats and set its chat files aside; the project folder itself is untouched."""
    for chat in [c for c in _chats.values() if c.project_id == project_id]:
        await chat.close()
    folder = sessions_dir(project_id)
    if folder.is_dir():
        removed = home() / "removed"
        removed.mkdir(parents=True, exist_ok=True)
        folder.rename(removed / f"{project_id}-{int(time.time())}")


def browse(raw: str) -> dict:
    """folders under a path, for picking a project; hidden folders stay out of the list."""
    path = Path(os.path.expanduser(raw or "~")).resolve()
    if not path.is_dir():
        raise ValueError("that folder does not exist on this machine")
    try:
        names = sorted(
            (p.name for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=str.lower,
        )
    except PermissionError as exc:
        raise ValueError("alles can't read that folder") from exc
    parent = path.parent if path.parent != path else None
    return {"path": str(path), "parent": str(parent) if parent else None, "folders": names[:500]}
