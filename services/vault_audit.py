"""the vault's own activity log: opens, locks, reveals, exports and security changes.

one json line per event in <data>/vault-audit.jsonl. no secrets and no entry contents go in:
an event names the vault, the action, how (password, passkey, browser) and an entry id where
there is one. entry names stay out; the screen shows them from the live list.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from core.settings import data_dir

KEEP = 2000
_lock = threading.Lock()


def _path() -> Path:
    return data_dir() / "vault-audit.jsonl"


def record(vault_id: str, action: str, **detail) -> None:
    row = {"at": round(time.time(), 3), "vault": vault_id, "action": action}
    row.update({k: v for k, v in detail.items() if v not in (None, "")})
    line = json.dumps(row, sort_keys=True)
    path = _path()
    with _lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            if path.stat().st_size > KEEP * 400:
                _trim(path)
        except OSError:
            pass  # the log must never block an unlock or a lock


def _trim(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()[-KEEP:]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def recent(vault_id: str, limit: int = 100) -> list[dict]:
    with _lock:
        try:
            lines = _path().read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
    out = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("vault") == vault_id:
            out.append(row)
            if len(out) >= limit:
                break
    return out
