"""
Notes app backed by the markdown vault instead of the `notes` DB table.

Each note is a real .md file under `Notes/` in the vault, so Obsidian opens/edits
them directly. Mapping:
  title    -> filename (the file IS the note; id = the stem)
  content  -> body
  items    -> trailing `- [ ]` / `- [x]` checkbox lines
  tags / pinned / archived / due / created -> frontmatter

We build the frontmatter block by hand (not via vault_md.set_frontmatter) so a body
that starts with `---` (a horizontal rule) doesn't get eaten as frontmatter.
"""

import re
from datetime import datetime

from services import vault_md

NOTES_DIR = "Notes"

# windows-illegal filename chars + control chars. obsidian rejects these too.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# any checkbox line; text may be empty (we drop empty-text ones)
_CB = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s*(.*)$")


def _rel(stem: str) -> str:
    return f"{NOTES_DIR}/{stem}.md"


def _fname(title: str) -> str:
    s = _ILLEGAL.sub("", (title or "").strip())
    s = re.sub(r"\s+", " ", s).strip(" .")
    s = s[:120].strip(" .")
    return s or "Untitled"


def _exists(stem: str) -> bool:
    try:
        return vault_md._safe(_rel(stem)).is_file()
    except ValueError:
        return False


def _unique(stem: str, ignore: str | None = None) -> str:
    base, n = stem, 2
    while _exists(stem) and stem != ignore:
        stem = f"{base} {n}"
        n += 1
    return stem


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _iso(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return ""


def _norm_tags(tags) -> list[str]:
    """list or comma-string -> lowercase, trimmed, deduped (order kept)."""
    if isinstance(tags, str):
        tags = tags.split(",")
    seen, out = set(), []
    for t in tags or []:
        t = str(t).strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _norm_items(items) -> list[dict]:
    out = []
    for r in items or []:
        if isinstance(r, dict) and str(r.get("text", "")).strip():
            out.append({"text": str(r["text"]).strip(), "done": bool(r.get("done"))})
    return out


def _fm_block(props: dict) -> str:
    if not props:
        return ""
    out = ["---"]
    for k, v in props.items():
        if isinstance(v, list):
            out.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        else:
            out.append(f"{k}: {v}")
    out.append("---")
    return "\n".join(out) + "\n"


def _compose(content, items, tags, pinned, archived, due, created_iso, legacy_id=None) -> str:
    props: dict = {}
    if tags:
        props["tags"] = tags
    if pinned:
        props["pinned"] = "true"
    if archived:
        props["archived"] = "true"
    if due:
        props["due"] = due
    props["created"] = created_iso
    if legacy_id:
        props["legacy_id"] = legacy_id
    body = (content or "").rstrip()
    if items:
        lines = [f"- [{'x' if it['done'] else ' '}] {it['text']}" for it in items]
        body = (body + "\n\n" if body else "") + "\n".join(lines)
    return _fm_block(props) + body


def _split_items(body: str):
    """peel the trailing run of checkbox/blank lines off the end -> items; rest -> content.
    a checkbox in the middle of prose stays in content (only the tail counts as items)."""
    lines = (body or "").replace("\r\n", "\n").split("\n")
    i = len(lines)
    while i > 0 and (lines[i - 1].strip() == "" or _CB.match(lines[i - 1])):
        i -= 1
    items = []
    for ln in lines[i:]:
        m = _CB.match(ln)
        if m and m.group(2).strip():
            items.append({"text": m.group(2).strip(), "done": m.group(1).lower() == "x"})
    content = "\n".join(lines[:i]).rstrip()
    return content, items


def _read(stem: str) -> dict | None:
    try:
        p = vault_md._safe(_rel(stem))
    except ValueError:
        return None
    if not p.is_file():
        return None
    props, body = vault_md.parse_frontmatter(p.read_text("utf-8", errors="replace"))
    content, items = _split_items(body)
    tags = props.get("tags")
    if isinstance(tags, str):
        tags = [t for t in (s.strip().lower() for s in tags.split(",")) if t]
    elif isinstance(tags, list):
        tags = _norm_tags(tags)
    else:
        tags = []
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0
    return {
        "id": stem,
        "title": stem,
        "content": content,
        "pinned": str(props.get("pinned", "")).lower() == "true",
        "archived": str(props.get("archived", "")).lower() == "true",
        "tags": tags,
        "items": items,
        "due": props.get("due", "") or "",
        "created_at": props.get("created") or _iso(mtime),
        "updated_at": _iso(mtime),
    }


def _legacy(stem: str) -> str | None:
    try:
        p = vault_md._safe(_rel(stem))
    except ValueError:
        return None
    if not p.is_file():
        return None
    props, _ = vault_md.parse_frontmatter(p.read_text("utf-8", errors="replace"))
    return props.get("legacy_id")


def _all() -> list[dict]:
    base = vault_md.vault_dir() / NOTES_DIR
    if not base.is_dir():
        return []
    out = []
    for p in base.glob("*.md"):  # flat: notes live directly under Notes/
        if p.name.startswith("."):
            continue
        r = _read(p.stem)
        if r:
            out.append(r)
    return out


# ── public api the route calls ───────────────────────────────────────────────
def get(nid: str) -> dict | None:
    if not nid or "/" in nid or "\\" in nid:
        return None
    return _read(nid)


def create(title="", content="", pinned=False, tags=None, items=None, due="",
           legacy_id=None, created_iso=None) -> dict:
    stem = _unique(_fname(title))
    md = _compose(
        content, _norm_items(items), _norm_tags(tags), bool(pinned), False,
        (due or "").strip(), created_iso or _now_iso(), legacy_id,
    )
    vault_md.write(_rel(stem), md)
    return _read(stem)


def update(nid: str, partial: dict) -> dict | None:
    cur = get(nid)
    if cur is None:
        return None
    content = partial["content"] if partial.get("content") is not None else cur["content"]
    pinned = partial["pinned"] if partial.get("pinned") is not None else cur["pinned"]
    archived = partial["archived"] if partial.get("archived") is not None else cur["archived"]
    tags = _norm_tags(partial["tags"]) if partial.get("tags") is not None else cur["tags"]
    items = _norm_items(partial["items"]) if partial.get("items") is not None else cur["items"]
    due = partial["due"].strip() if partial.get("due") is not None else cur["due"]

    final = nid
    if partial.get("title") is not None:
        new_stem = _fname(partial["title"])
        if new_stem != nid:
            new_stem = _unique(new_stem, ignore=nid)
            vault_md.rename(_rel(nid), _rel(new_stem))
            try:
                vault_md.rewrite_links(nid, new_stem)  # fix [[old]] backlinks
            except Exception:
                pass
            final = new_stem

    md = _compose(content, items, tags, bool(pinned), bool(archived), due,
                  cur["created_at"], _legacy(final))
    vault_md.write(_rel(final), md)
    return _read(final)


def set_archived(nid: str, val: bool) -> dict | None:
    return update(nid, {"archived": bool(val)})


def delete(nid: str) -> dict:
    if nid and "/" not in nid and "\\" not in nid:
        try:
            vault_md.delete(_rel(nid))
        except Exception:
            pass
    return {"ok": True}


def list_notes(q="", tag="", archived=False, limit=0, offset=0) -> list[dict]:
    rows = [r for r in _all() if (r["archived"] if archived else not r["archived"])]
    if tag:
        t = tag.strip().lower()
        rows = [r for r in rows if t in r["tags"]]
    if q:
        ql = q.lower()
        rows = [
            r for r in rows
            if ql in r["title"].lower() or ql in r["content"].lower() or ql in " ".join(r["tags"])
        ]
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    rows.sort(key=lambda r: not r["pinned"])  # stable: pinned float to top, newest-first within
    if offset:
        rows = rows[max(0, offset):]
    if limit:
        rows = rows[: max(1, int(limit))]
    return rows


def tag_counts() -> list[dict]:
    counts: dict[str, int] = {}
    for r in _all():
        if r["archived"]:
            continue
        for t in r["tags"]:
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(counts.items())]


def all_notes() -> list[dict]:
    """every note incl. archived — for the index reindex + export."""
    return _all()


# ── migration (DB notes -> vault files) ──────────────────────────────────────
def existing_legacy_ids() -> set:
    """legacy_id of every already-migrated note file, so the migration is idempotent."""
    base = vault_md.vault_dir() / NOTES_DIR
    if not base.is_dir():
        return set()
    out = set()
    for p in base.glob("*.md"):
        lid = _legacy(p.stem)
        if lid:
            out.add(lid)
    return out


def migrate_note(*, title, content, pinned, archived, tags, items, due, created_iso, legacy_id) -> str:
    """write one legacy DB note as a vault file, carrying its archived flag + legacy_id.
    items may be a json string (the old Text column) or a list."""
    import json
    if isinstance(items, str):
        try:
            items = json.loads(items or "[]")
        except Exception:
            items = []
    stem = _unique(_fname(title))
    md = _compose(content or "", _norm_items(items), _norm_tags(tags), bool(pinned),
                  bool(archived), (due or "").strip(), created_iso or _now_iso(), legacy_id)
    vault_md.write(_rel(stem), md)
    return stem


def migration_plan(db) -> list[dict]:
    """dry-run: what the notes->vault migration WOULD do, without writing anything."""
    from sqlalchemy import text
    done = existing_legacy_ids()
    out = []
    for row in db.execute(text("SELECT id, title FROM notes")).fetchall():
        nid, title = row[0], row[1]
        out.append({
            "id": nid,
            "target": f"{NOTES_DIR}/{_fname(title)}.md",
            "action": "skip" if nid in done else "create",
        })
    return out
