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

import json
import re
from datetime import datetime

from services import vault_md

NOTES_DIR = "Notes"

# windows-illegal filename chars + control chars. obsidian rejects these too.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# any checkbox line; text may be empty (we drop empty-text ones)
_CB = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s*(.*)$")
_FM_KEY = re.compile(
    r"^(?:"
    r"\"((?:[^\"\\]|\\.)+)\""
    r"|'((?:[^']|'')+)'"
    r"|((?![-?:](?:[ \t]|$))[^ \t\r\n#{}\[\],&*!|>'\"%@`][^:\r\n]*?)"
    r"):[ \t]*(.*?)(?:\r?\n)?$"
)


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
            encoded = ", ".join(json.dumps(str(x), ensure_ascii=False) for x in v)
            out.append(f"{k}: [{encoded}]")
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


def _line_ending(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    return "\n"


def _frontmatter_parts(text: str) -> tuple[str, list[str], str] | None:
    """Return the exact opening line, interior lines, and body.

    This parser deliberately preserves every byte-representable character and line ending. It is
    narrower than ``vault_md.parse_frontmatter`` because mutation must never normalize unrelated
    frontmatter or Markdown.
    """
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    rest = text[len(bom) :]
    lines = rest.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    close = None
    for index, line in enumerate(lines[1:], 1):
        if line.rstrip("\r\n") == "---":
            close = index
            break
    if close is None:
        return None
    interior = lines[1:close]
    if not any(_FM_KEY.match(line) for line in interior):
        if any(line.strip() and not line.lstrip().startswith("#") for line in interior):
            return None
    opening = bom + lines[0]
    body = "".join(lines[close + 1 :])
    return opening, interior, lines[close] + body


def _managed_value(key: str, value) -> str | None:
    if key == "tags":
        tags = _norm_tags(value)
        encoded = ", ".join(json.dumps(tag, ensure_ascii=False) for tag in tags)
        return f"tags: [{encoded}]" if tags else None
    if key in {"pinned", "archived"}:
        return f"{key}: true" if bool(value) else None
    if key == "due":
        due = str(value or "").strip()
        return f"due: {due}" if due else None
    raise ValueError(f"unsupported managed note field: {key}")


def _patch_frontmatter(text: str, changes: dict) -> str:
    """Patch only explicitly changed Notes metadata, preserving everything else exactly."""
    if not changes:
        return text
    eol = _line_ending(text)
    parsed = _frontmatter_parts(text)
    if parsed is None:
        rendered = [line for key, value in changes.items() if (line := _managed_value(key, value))]
        if not rendered:
            return text
        bom = "\ufeff" if text.startswith("\ufeff") else ""
        body = text[len(bom) :]
        return bom + f"---{eol}{eol.join(rendered)}{eol}---{eol}" + body

    opening, interior, closing_and_body = parsed
    spans: dict[str, tuple[int, int]] = {}
    index = 0
    while index < len(interior):
        match = _FM_KEY.match(interior[index])
        if not match:
            index += 1
            continue
        key = next(value for value in match.groups()[:3] if value is not None).strip()
        end = index + 1
        while end < len(interior) and not _FM_KEY.match(interior[end]):
            end += 1
        value_end = end
        while value_end > index + 1 and (
            not interior[value_end - 1].strip() or interior[value_end - 1].lstrip().startswith("#")
        ):
            value_end -= 1
        if key in changes:
            if key in spans:
                raise vault_md.DocumentConflictError(
                    f"note has duplicate {key!r} frontmatter; edit it in Source mode"
                )
            continuation = interior[index + 1 : value_end]
            simple_list = match.group(4).strip() == "" and all(
                not line.strip() or (re.match(r"^\s+-\s+", line) is not None and "#" not in line)
                for line in continuation
            )
            if continuation and not simple_list:
                raise vault_md.DocumentConflictError(
                    f"note has complex {key!r} frontmatter; edit it in Source mode"
                )
            spans[key] = (index, value_end)
        index = end

    replacements: list[tuple[int, int, list[str]]] = []
    append: list[str] = []
    for key, value in changes.items():
        rendered = _managed_value(key, value)
        replacement = [rendered + eol] if rendered else []
        if key in spans:
            start, end = spans[key]
            replacements.append((start, end, replacement))
        elif rendered:
            append.append(rendered + eol)

    for start, end, replacement in sorted(replacements, reverse=True):
        interior[start:end] = replacement
    interior.extend(append)
    if not any(line.strip() for line in interior):
        bom = "\ufeff" if opening.startswith("\ufeff") else ""
        closing_line = closing_and_body.splitlines(keepends=True)[0]
        return bom + closing_and_body[len(closing_line) :]
    return opening + "".join(interior) + closing_and_body


def _body_start(text: str) -> int:
    parsed = _frontmatter_parts(text)
    if parsed is None:
        return 0
    opening, interior, closing_and_body = parsed
    closing_line = closing_and_body.splitlines(keepends=True)[0]
    return len(opening) + sum(len(line) for line in interior) + len(closing_line)


def _trailing_items_start(body: str) -> int | None:
    lines = body.splitlines(keepends=True)
    index = len(lines)
    saw_item = False
    while index > 0:
        line = lines[index - 1].rstrip("\r\n")
        if _CB.match(line):
            saw_item = True
            index -= 1
            continue
        if line.strip() == "":
            index -= 1
            continue
        break
    if not saw_item:
        return None
    return sum(len(line) for line in lines[:index])


def _render_items(items: list[dict], eol: str) -> str:
    return eol.join(f"- [{'x' if item['done'] else ' '}] {item['text']}" for item in items)


def _patch_body(text: str, partial: dict) -> str:
    if "content" not in partial and "items" not in partial:
        return text
    start = _body_start(text)
    head, body = text[:start], text[start:]
    item_start = _trailing_items_start(body)
    content = body if item_start is None else body[:item_start]
    old_items = "" if item_start is None else body[item_start:]
    old_separator = old_items[: len(old_items) - len(old_items.lstrip("\r\n"))]
    eol = _line_ending(text)

    if "content" in partial:
        content = str(partial.get("content") or "")
    if "items" in partial:
        items = _norm_items(partial.get("items"))
        old_items = _render_items(items, eol)

    if old_items:
        if "content" not in partial and item_start is not None:
            body = content + old_separator + old_items.lstrip("\r\n")
        else:
            content = content.rstrip("\r\n")
            separator = eol * 2 if content else ""
            body = content + separator + old_items.lstrip("\r\n")
    else:
        body = content
    return head + body


def _patch_note_document(raw: str, partial: dict) -> str:
    metadata = {
        key: partial[key]
        for key in ("tags", "pinned", "archived", "due")
        if partial.get(key) is not None
    }
    body_changes = {
        key: partial[key] for key in ("content", "items") if partial.get(key) is not None
    }
    return _patch_body(_patch_frontmatter(raw, metadata), body_changes)


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
    document = vault_md.read(_rel(stem))
    props, body = vault_md.parse_frontmatter(document["content"])
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
        "hash": document["hash"],
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


def create(
    title="",
    content="",
    pinned=False,
    tags=None,
    items=None,
    due="",
    legacy_id=None,
    created_iso=None,
) -> dict:
    stem = _unique(_fname(title))
    md = _compose(
        content,
        _norm_items(items),
        _norm_tags(tags),
        bool(pinned),
        False,
        (due or "").strip(),
        created_iso or _now_iso(),
        legacy_id,
    )
    vault_md.write(_rel(stem), md)
    return _read(stem)


def update(nid: str, partial: dict, expected_hash: str | None = None) -> dict | None:
    cur = get(nid)
    if cur is None:
        return None
    document = vault_md.read(_rel(nid))
    if not document.get("editable", True):
        raise vault_md.DocumentEncodingError(
            "document is not valid UTF-8; the original file was left unchanged"
        )
    raw = document["content"]
    if expected_hash is not None and expected_hash != document["hash"]:
        raise vault_md.DocumentConflictError("document changed since it was opened")

    final = nid
    new_stem = nid
    if partial.get("title") is not None:
        new_stem = _fname(partial["title"])
        if new_stem != nid:
            new_stem = _unique(new_stem, ignore=nid)
            final = new_stem

    md = _patch_note_document(raw, partial)
    current_hash = document["hash"]
    if md != raw:
        current_hash = vault_md.write(_rel(nid), md, expected_hash=document["hash"])["hash"]
    if final != nid:
        vault_md.rename(_rel(nid), _rel(final), expected_hash=current_hash)
        try:
            vault_md.rewrite_links(nid, final)  # fix [[old]] backlinks
        except Exception:
            pass
    return _read(final)


def set_archived(nid: str, val: bool) -> dict | None:
    return update(nid, {"archived": bool(val)})


def delete(nid: str, db=None) -> dict:
    if nid and "/" not in nid and "\\" not in nid:
        try:
            if db is None:
                vault_md.delete(_rel(nid))
            else:
                from services import trash

                path = vault_md._safe(_rel(nid))
                item = trash.soft_delete_path(db, "vault", _rel(nid), path)
                return {"ok": True, "trashed": True, "trash_id": item.id}
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
            r
            for r in rows
            if ql in r["title"].lower() or ql in r["content"].lower() or ql in " ".join(r["tags"])
        ]
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    rows.sort(key=lambda r: not r["pinned"])  # stable: pinned float to top, newest-first within
    if offset:
        rows = rows[max(0, offset) :]
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


def migrate_note(
    *, title, content, pinned, archived, tags, items, due, created_iso, legacy_id
) -> str:
    """write one legacy DB note as a vault file, carrying its archived flag + legacy_id.
    items may be a json string (the old Text column) or a list."""
    import json

    if isinstance(items, str):
        try:
            items = json.loads(items or "[]")
        except Exception:
            items = []
    stem = _unique(_fname(title))
    md = _compose(
        content or "",
        _norm_items(items),
        _norm_tags(tags),
        bool(pinned),
        bool(archived),
        (due or "").strip(),
        created_iso or _now_iso(),
        legacy_id,
    )
    vault_md.write(_rel(stem), md)
    return stem


def migration_plan(db) -> list[dict]:
    """dry-run: what the notes->vault migration WOULD do, without writing anything."""
    from sqlalchemy import text

    done = existing_legacy_ids()
    out = []
    for row in db.execute(text("SELECT id, title FROM notes")).fetchall():
        nid, title = row[0], row[1]
        out.append(
            {
                "id": nid,
                "target": f"{NOTES_DIR}/{_fname(title)}.md",
                "action": "skip" if nid in done else "create",
            }
        )
    return out
