"""
Obsidian-style markdown vault: real .md files on disk + wikilinks + backlinks.
Everything is stored as plain files so the vault is portable and git-able.
"""

import re
import shutil
from pathlib import Path

from core.settings import data_dir, load_settings

ROOT = Path(__file__).resolve().parent.parent


def vault_dir() -> Path:
    s = load_settings()
    d = s.get("vault_dir") or str(data_dir() / "vault")
    p = Path(d).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe(rel: str) -> Path:
    """resolve a path inside the vault, rejecting traversal."""
    base = vault_dir()
    p = (base / (rel or "").lstrip("/\\")).resolve()
    if base not in p.parents and p != base:
        raise ValueError("path escapes vault")
    return p


_WIKILINK = re.compile(r"\[\[([^\[\]|#]+)(?:[#|][^\[\]]*)?\]\]")

# system folders that hold embedded assets + templates — kept out of the tree,
# search, tags and the graph so they don't clutter the actual notes
_SYS_DIRS = {"_assets", "_templates"}


def _is_md(p: Path) -> bool:
    return p.suffix.lower() in (".md", ".markdown")


def _in_sys_dir(p: Path) -> bool:
    return any(part in _SYS_DIRS for part in p.parts)


def tree() -> dict:
    """nested folder/file tree of the vault (md files only)."""
    base = vault_dir()

    def walk(d: Path) -> list:
        items = []
        for child in sorted(d.iterdir(), key=lambda c: (c.is_file(), c.name.lower())):
            if child.name.startswith(".") or child.name in _SYS_DIRS:
                continue
            rel = str(child.relative_to(base)).replace("\\", "/")
            if child.is_dir():
                items.append(
                    {"type": "dir", "name": child.name, "path": rel, "children": walk(child)}
                )
            elif _is_md(child):
                try:
                    mt = child.stat().st_mtime
                except OSError:
                    mt = 0
                items.append({"type": "file", "name": child.stem, "path": rel, "mtime": mt})
        return items

    return {"path": str(base), "items": walk(base)}


def read(rel: str) -> dict:
    p = _safe(rel)
    if not p.exists() or not p.is_file():
        return {"path": rel, "content": "", "exists": False}
    return {"path": rel, "content": p.read_text("utf-8", errors="replace"), "exists": True}


def write(rel: str, content: str) -> dict:
    p = _safe(rel)
    if p.suffix == "":
        p = p.with_suffix(".md")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content or "", "utf-8")
    return {"path": str(p.relative_to(vault_dir())).replace("\\", "/"), "ok": True}


def parse_frontmatter(content: str):
    """split a leading --- yaml-ish block off the top. returns (props, body).
    handles `key: value`, inline `key: [a, b]` lists and block `- item` lists.
    no closing fence → treated as plain content (props {})."""
    text = (content or "").replace("\r\n", "\n")
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        return {}, content or ""
    close = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break
    if close is None:
        return {}, content or ""
    fm = lines[1:close]
    body = "\n".join(lines[close + 1 :])
    props: dict = {}
    i = 0
    while i < len(fm):
        m = re.match(r"^([A-Za-z0-9_][\w \-]*?):\s*(.*)$", fm[i])
        if not m:
            i += 1
            continue
        key, val = m.group(1).strip(), m.group(2).strip()
        if val == "":
            # maybe a block list follows
            items, j = [], i + 1
            while j < len(fm) and re.match(r"^\s*-\s+", fm[j]):
                items.append(re.sub(r"^\s*-\s+", "", fm[j]).strip())
                j += 1
            if items:
                props[key] = items
                i = j
                continue
            props[key] = ""
        elif val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            props[key] = [s.strip() for s in inner.split(",") if s.strip()] if inner else []
        else:
            props[key] = val
        i += 1
    return props, body


def set_frontmatter(content: str, props: dict) -> str:
    """rewrite the leading frontmatter block to exactly `props`, keeping the body.
    empty props → strip the block entirely."""
    _, body = parse_frontmatter(content)
    if not props:
        return body
    out = ["---"]
    for k, v in props.items():
        if isinstance(v, list):
            out.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        else:
            out.append(f"{k}: {v}")
    out.append("---")
    return "\n".join(out) + "\n" + body


_PERIODIC_TMPL = {
    "weekly": "# Week {wk}, {iy}\n\n## Focus\n\n\n## Notes\n\n\n## Review\n",
    "monthly": "# {month} {year}\n\n## Goals\n\n\n## Highlights\n\n\n## Review\n",
}


_CARD = re.compile(r"^\s*[-*]\s+(?:\[([ xX])\]\s+)?(.*)$")
_H2 = re.compile(r"^##\s+(.*)$")


def parse_board(content: str) -> list[dict]:
    """parse a markdown doc into kanban columns: `## Heading` = column, list items
    under it = cards. card line numbers are absolute (frontmatter offset included)
    so they line up with set_task / board_move_card."""
    lines = (content or "").replace("\r\n", "\n").split("\n")
    cols: list[dict] = []
    cur = None
    in_fm = False
    for i, ln in enumerate(lines):
        if i == 0 and ln.strip() == "---":
            in_fm = True
            continue
        if in_fm:
            if ln.strip() == "---":
                in_fm = False
            continue
        h = _H2.match(ln)
        if h:
            cur = {"name": h.group(1).strip(), "cards": []}
            cols.append(cur)
            continue
        if cur is not None:
            m = _CARD.match(ln)
            if m and m.group(2).strip():
                cur["cards"].append(
                    {
                        "text": m.group(2).strip(),
                        "line": i,
                        "done": (m.group(1) or "").lower() == "x",
                    }
                )
    return cols


def _insert_into_column(lines: list[str], column: str, card_line: str):
    """insert card_line at the end of `## column`'s block, creating the column if absent."""
    hidx = None
    for i, ln in enumerate(lines):
        m = _H2.match(ln)
        if m and m.group(1).strip().lower() == column.strip().lower():
            hidx = i
            break
    if hidx is None:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append(f"## {column.strip()}")
        lines.append(card_line)
        return
    end = len(lines)
    for j in range(hidx + 1, len(lines)):
        if _H2.match(lines[j]):
            end = j
            break
    ins = hidx + 1
    for j in range(hidx + 1, end):
        if lines[j].strip() != "":
            ins = j + 1
    lines.insert(ins, card_line)


def board_add_card(rel: str, column: str, text: str) -> dict:
    p = _safe(rel)
    raw = p.read_text("utf-8", errors="replace") if p.is_file() else ""
    lines = raw.replace("\r\n", "\n").split("\n")
    _insert_into_column(lines, column, f"- [ ] {text.strip()}")
    new = "\n".join(lines)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new, "utf-8")
    return {"ok": True, "columns": parse_board(new)}


def board_move_card(rel: str, line: int, to_col: str) -> dict:
    p = _safe(rel)
    if not p.is_file():
        raise ValueError("not a file")
    lines = p.read_text("utf-8", errors="replace").replace("\r\n", "\n").split("\n")
    if line < 0 or line >= len(lines):
        raise ValueError("line out of range")
    if not _CARD.match(lines[line]) or not _CARD.match(lines[line]).group(2).strip():
        raise ValueError("not a card line")
    card_line = lines[line]
    del lines[line]
    _insert_into_column(lines, to_col, card_line)
    new = "\n".join(lines)
    p.write_text(new, "utf-8")
    return {"ok": True, "columns": parse_board(new)}


def _cmp_prop(pv, op: str, value: str) -> bool:
    """compare a single frontmatter value against a filter. pv may be str/list/None."""
    if op == "exists":
        return pv is not None
    if op == "missing":
        return pv is None
    if pv is None:
        return op == "ne"  # a missing value is "not equal" to anything
    if isinstance(pv, list):
        vals = [str(x).lower() for x in pv]
        if op in ("eq", "contains"):
            return value.lower() in vals
        if op == "ne":
            return value.lower() not in vals
        return False
    s = str(pv)
    if op == "eq":
        return s.lower() == value.lower()
    if op == "ne":
        return s.lower() != value.lower()
    if op == "contains":
        return value.lower() in s.lower()
    if op in ("gt", "lt"):
        try:
            a, b = float(s), float(value)
        except ValueError:
            a, b = s.lower(), value.lower()
        return a > b if op == "gt" else a < b
    return False


def _match_note(row: dict, filters: list) -> bool:
    for flt in filters:
        field = flt.get("field") or flt.get("key") or ""
        op = flt.get("op", "eq")
        value = str(flt.get("value", ""))
        if field == "tag":
            tv = value.lstrip("#").lower()
            if op in ("eq", "contains"):
                ok = tv in row["tags"]
            elif op == "ne":
                ok = tv not in row["tags"]
            elif op == "exists":
                ok = bool(row["tags"])
            elif op == "missing":
                ok = not row["tags"]
            else:
                ok = False
        elif field == "folder":
            pref = value.lower().rstrip("/")
            ok = row["path"].lower().startswith(pref + "/") if pref else "/" not in row["path"]
        elif field == "name":
            ok = _cmp_prop(row["name"], op, value)
        else:
            ok = _cmp_prop(row["props"].get(field), op, value)
        if not ok:
            return False
    return True


def query_notes(filters=None, sort=None, limit=None) -> list[dict]:
    """dataview-lite: filter notes by frontmatter properties / tags / folder, sort, limit.
    each row = {name, path, props, tags, modified}."""
    filters = filters or []
    base = vault_dir()
    rows = []
    for p in _all_md():
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        props, body = parse_frontmatter(text)
        tags = set()
        tp = props.get("tags")
        if isinstance(tp, list):
            tags.update(str(x).lower() for x in tp)
        elif isinstance(tp, str) and tp:
            tags.update(s.strip().lower() for s in tp.split(",") if s.strip())
        tags.update(m.group(1).lower() for m in _TAG.finditer(body))
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0
        row = {
            "name": p.stem,
            "path": str(p.relative_to(base)).replace("\\", "/"),
            "props": props,
            "tags": sorted(tags),
            "modified": mtime,
        }
        if _match_note(row, filters):
            rows.append(row)
    if sort and sort.get("field"):
        f = sort["field"]

        def _key(r):
            if f == "name":
                return r["name"].lower()
            if f == "modified":
                return r["modified"]
            v = r["props"].get(f)
            if v is None:
                return (2, "")
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            try:
                return (0, float(v))
            except ValueError:
                return (1, str(v).lower())

        rows.sort(key=_key, reverse=(sort.get("dir", "asc") == "desc"))
    if limit:
        rows = rows[: int(limit)]
    return rows


def periodic_path(kind: str, d=None) -> str:
    """relative note path for a periodic note. weekly uses ISO year+week so the
    new-year boundary lands in the right bucket."""
    from datetime import date as _date

    d = d or _date.today()
    if kind == "weekly":
        iy, iw, _ = d.isocalendar()
        return f"Periodic/{iy}-W{iw:02d}.md"
    if kind == "monthly":
        return f"Periodic/{d.year}-{d.month:02d}.md"
    if kind == "daily":
        return f"{d.year}-{d.month:02d}-{d.day:02d}.md"
    raise ValueError("kind must be weekly, monthly or daily")


def open_or_create_periodic(kind: str, d=None) -> dict:
    """return the periodic note's path, creating it from a template if missing.
    never overwrites an existing note."""
    import calendar
    from datetime import date as _date

    d = d or _date.today()
    rel = periodic_path(kind, d)  # raises on bad kind
    p = _safe(rel)
    if p.exists():
        return {"path": rel, "existed": True, "ok": True}
    if kind == "weekly":
        iy, iw, _ = d.isocalendar()
        body = _PERIODIC_TMPL["weekly"].format(wk=iw, iy=iy)
    elif kind == "monthly":
        body = _PERIODIC_TMPL["monthly"].format(month=calendar.month_name[d.month], year=d.year)
    else:
        body = f"# {rel[:-3]}\n\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, "utf-8")
    return {"path": rel, "created": True, "ok": True}


def create(rel: str, content: str = "") -> dict:
    p = _safe(rel)
    if p.suffix == "":
        p = p.with_suffix(".md")
    if p.exists():
        return {
            "path": str(p.relative_to(vault_dir())).replace("\\", "/"),
            "ok": True,
            "existed": True,
        }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content or f"# {p.stem}\n\n", "utf-8")
    return {"path": str(p.relative_to(vault_dir())).replace("\\", "/"), "ok": True}


def delete(rel: str) -> dict:
    p = _safe(rel)
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    return {"ok": True}


def rename(rel: str, new_rel: str) -> dict:
    src = _safe(rel)
    dst = _safe(new_rel)
    # only auto-append .md when renaming a FILE (folders keep their plain name)
    if src.is_file() and dst.suffix == "":
        dst = dst.with_suffix(".md")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {"path": str(dst.relative_to(vault_dir())).replace("\\", "/"), "ok": True}


def rewrite_links(old_name: str, new_name: str) -> list[str]:
    """a note's [[wikilink]] target is its stem, so renaming a note orphans every
    backlink. walk the vault and rewrite [[old]] / [[old#heading]] / [[old|alias]]
    → [[new...]], preserving the heading/alias tail. returns changed rel-paths."""
    old_l = (old_name or "").strip().lower()
    new_name = (new_name or "").strip()
    if not old_l or not new_name or old_l == new_name.lower():
        return []
    base = vault_dir()
    # like _WIKILINK but captures the #heading / |alias tail separately so we keep it
    pat = re.compile(r"\[\[([^\[\]|#]+)((?:[#|][^\[\]]*)?)\]\]")

    def _sub(m):
        if m.group(1).strip().lower() == old_l:
            return f"[[{new_name}{m.group(2)}]]"
        return m.group(0)

    changed = []
    for p in _all_md():
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        new_text = pat.sub(_sub, text)
        if new_text != text:
            try:
                p.write_text(new_text, "utf-8")
                changed.append(str(p.relative_to(base)).replace("\\", "/"))
            except Exception:
                continue
    return changed


def _all_md() -> list[Path]:
    base = vault_dir()
    return [
        p
        for p in base.rglob("*")
        if p.is_file() and _is_md(p) and not p.name.startswith(".") and not _in_sys_dir(p)
    ]


def note_names() -> list[str]:
    """all note stems, for [[ autocomplete + graph."""
    return sorted({p.stem for p in _all_md()})


def search(q: str, limit: int = 20) -> list[dict]:
    ql = (q or "").lower()
    base = vault_dir()
    out = []
    for p in _all_md():
        if not ql or ql in p.stem.lower():
            out.append({"name": p.stem, "path": str(p.relative_to(base)).replace("\\", "/")})
    out.sort(key=lambda r: (not r["name"].lower().startswith(ql), len(r["name"])))
    return out[:limit]


def backlinks(name: str) -> list[dict]:
    """notes that contain a [[name]] link to this note."""
    base = vault_dir()
    target = (name or "").strip().lower()
    out = []
    for p in _all_md():
        if p.stem.lower() == target:
            continue
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        for m in _WIKILINK.finditer(text):
            if m.group(1).strip().lower() == target:
                # grab a little surrounding context
                start = max(0, m.start() - 40)
                ctx = " ".join(text[start : m.end() + 40].split())
                out.append(
                    {
                        "name": p.stem,
                        "path": str(p.relative_to(base)).replace("\\", "/"),
                        "context": ctx,
                    }
                )
                break
    return out


def outgoing_links(rel: str) -> list[str]:
    p = _safe(rel)
    if not p.exists():
        return []
    text = p.read_text("utf-8", errors="replace")
    return sorted({m.group(1).strip() for m in _WIKILINK.finditer(text)})


def create_folder(rel: str) -> dict:
    p = _safe(rel)
    p.mkdir(parents=True, exist_ok=True)
    return {"path": str(p.relative_to(vault_dir())).replace("\\", "/"), "ok": True}


def find_asset(name: str) -> str | None:
    """resolve an embed target (image/file) by relative path or bare name."""
    base = vault_dir()
    name = (name or "").strip()
    try:
        p = _safe(name)
        if p.is_file():
            return str(p.relative_to(base)).replace("\\", "/")
    except ValueError:
        pass
    target = name.lower()
    for f in base.rglob("*"):
        if (
            f.is_file()
            and not f.name.startswith(".")
            and (f.name.lower() == target or f.stem.lower() == target)
        ):
            return str(f.relative_to(base)).replace("\\", "/")
    return None


def file_bytes(rel: str):
    import mimetypes

    p = _safe(rel)
    if not p.is_file():
        raise ValueError("not a file")
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return p.read_bytes(), mime


def full_text_search(q: str, limit: int = 50) -> list[dict]:
    """search note names AND contents, with a snippet of context."""
    base = vault_dir()
    ql = (q or "").strip().lower()
    if not ql:
        return []
    out = []
    for p in _all_md():
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        low = text.lower()
        idx = low.find(ql)
        in_name = ql in p.stem.lower()
        if idx < 0 and not in_name:
            continue
        ctx = ""
        if idx >= 0:
            s = max(0, idx - 40)
            ctx = " ".join(text[s : idx + len(ql) + 50].split())
        out.append(
            {"name": p.stem, "path": str(p.relative_to(base)).replace("\\", "/"), "context": ctx}
        )
        if len(out) >= limit:
            break
    out.sort(key=lambda r: (ql not in r["name"].lower(), r["name"].lower()))
    return out


_TAG = re.compile(r"(?:^|\s)#([A-Za-z0-9][A-Za-z0-9_/\-]*)")


def all_tags() -> list[dict]:
    counts: dict[str, int] = {}
    for p in _all_md():
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        for t in {m.group(1) for m in _TAG.finditer(text)}:
            counts[t] = counts.get(t, 0) + 1
    return [
        {"tag": t, "count": c} for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def notes_with_tag(tag: str) -> list[dict]:
    base = vault_dir()
    target = (tag or "").lstrip("#").lower()
    out = []
    for p in _all_md():
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        if any(m.group(1).lower() == target for m in _TAG.finditer(text)):
            out.append({"name": p.stem, "path": str(p.relative_to(base)).replace("\\", "/")})
    return out


_TASK = re.compile(r"^(\s*)[-*]\s+\[([ xX])\]\s+(.*)$")


def all_tasks(include_done: bool = True) -> list[dict]:
    """every `- [ ]` / `- [x]` checkbox across the vault — for the rollup view."""
    base = vault_dir()
    out = []
    for p in _all_md():
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        rel = str(p.relative_to(base)).replace("\\", "/")
        for i, line in enumerate(text.split("\n")):
            m = _TASK.match(line)
            if not m:
                continue
            done = m.group(2).lower() == "x"
            if not include_done and done:
                continue
            txt = m.group(3).strip()
            if txt:
                out.append({"path": rel, "name": p.stem, "line": i, "text": txt, "done": done})
    # open tasks first, then by doc
    out.sort(key=lambda t: (t["done"], t["name"].lower()))
    return out


def set_task(rel: str, line: int, done: bool) -> dict:
    """flip a single checkbox on a known line and save the doc."""
    p = _safe(rel)
    if not p.is_file():
        raise ValueError("not a file")
    lines = p.read_text("utf-8", errors="replace").split("\n")
    if line < 0 or line >= len(lines):
        raise ValueError("line out of range")
    if not _TASK.match(lines[line]):
        raise ValueError("not a task line")
    mark = "x" if done else " "
    lines[line] = re.sub(r"\[[ xX]\]", f"[{mark}]", lines[line], count=1)
    p.write_text("\n".join(lines), "utf-8")
    return {"ok": True, "done": done}


_DEFAULT_TEMPLATES = {
    "meeting": "# {{title}}\n\n**date:** {{date}}\n**attendees:** \n\n## agenda\n- \n\n## notes\n\n\n## action items\n- [ ] \n",
    "daily": "# {{date}}\n\n## today\n- [ ] \n\n## notes\n\n\n## log\n",
    "project": "# {{title}}\n\n## goal\n\n\n## tasks\n- [ ] \n\n## resources\n\n\n## notes\n",
}


def list_templates() -> list[dict]:
    """templates live in _templates/*.md. seed a few starters on first use."""
    base = vault_dir()
    tdir = base / "_templates"
    if not tdir.exists():
        tdir.mkdir(parents=True, exist_ok=True)
        for name, body in _DEFAULT_TEMPLATES.items():
            (tdir / f"{name}.md").write_text(body, "utf-8")
    out = []
    for p in sorted(tdir.glob("*.md")):
        try:
            out.append({"name": p.stem, "content": p.read_text("utf-8", errors="replace")})
        except Exception:
            pass
    return out


def save_asset(filename: str, data: bytes) -> dict:
    """stash a pasted/dropped image under _assets/, de-duping the name."""
    base = vault_dir()
    adir = base / "_assets"
    adir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", (filename or "asset").strip().lower()) or "asset"
    if "." not in name:
        name += ".png"
    stem, _, ext = name.rpartition(".")
    p = adir / name
    i = 1
    while p.exists():
        p = adir / f"{stem}-{i}.{ext}"
        i += 1
    p.write_bytes(data)
    rel = str(p.relative_to(base)).replace("\\", "/")
    return {"path": rel, "name": p.name}


def unlinked_mentions(name: str) -> list[dict]:
    """notes that say this note's title in plain text but don't [[link]] it."""
    base = vault_dir()
    target = (name or "").strip()
    if len(target) < 2:
        return []
    tl = target.lower()
    pat = re.compile(r"(?<![\w\[])" + re.escape(target) + r"(?![\w\]])", re.IGNORECASE)
    out = []
    for p in _all_md():
        if p.stem.lower() == tl:
            continue
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        # blank out real wikilinks first so [[name]] isn't counted as "unlinked"
        stripped = _WIKILINK.sub(lambda m: " " * len(m.group(0)), text)
        m = pat.search(stripped)
        if not m:
            continue
        s = max(0, m.start() - 40)
        ctx = " ".join(stripped[s : m.end() + 40].split())
        out.append(
            {"name": p.stem, "path": str(p.relative_to(base)).replace("\\", "/"), "context": ctx}
        )
    return out


def _note_tags(text: str) -> set:
    props, body = parse_frontmatter(text)
    tags = set()
    tp = props.get("tags")
    if isinstance(tp, list):
        tags.update(str(x).lower() for x in tp)
    elif isinstance(tp, str) and tp:
        tags.update(s.strip().lower() for s in tp.split(",") if s.strip())
    tags.update(m.group(1).lower() for m in _TAG.finditer(body))
    return tags


def _graph_files(tag=None, folder=None) -> list[Path]:
    files = _all_md()
    if not tag and not folder:
        return files
    base = vault_dir()
    tnorm = (tag or "").lstrip("#").lower()
    fnorm = (folder or "").lower().rstrip("/")
    out = []
    for p in files:
        rel = str(p.relative_to(base)).replace("\\", "/")
        if fnorm and not rel.lower().startswith(fnorm + "/"):
            continue
        if tnorm:
            try:
                text = p.read_text("utf-8", errors="replace")
            except Exception:
                text = ""
            if tnorm not in _note_tags(text):
                continue
        out.append(p)
    return out


def _edges_for(files: list[Path]) -> dict:
    """nodes = the given notes, edges = resolved [[wikilinks]] between them (within the set)."""
    base = vault_dir()
    by_stem = {p.stem.lower(): p.stem for p in files}
    nodes = [{"id": p.stem, "path": str(p.relative_to(base)).replace("\\", "/")} for p in files]
    edges = []
    for p in files:
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        for tgt in {m.group(1).strip() for m in _WIKILINK.finditer(text)}:
            res = by_stem.get(tgt.lower())
            if res and res != p.stem:
                edges.append({"source": p.stem, "target": res})
    deg: dict[str, int] = {}
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    for n in nodes:
        n["degree"] = deg.get(n["id"], 0)
    return {"nodes": nodes, "edges": edges}


def graph(tag=None, folder=None) -> dict:
    """nodes = notes, edges = resolved [[wikilinks]]. optional tag/folder filter."""
    return _edges_for(_graph_files(tag, folder))


def local_graph(name: str, depth: int = 1) -> dict:
    """subgraph within `depth` hops of `name` (undirected over wikilinks)."""
    full = _edges_for(_all_md())
    idmap = {n["id"].lower(): n["id"] for n in full["nodes"]}
    start = idmap.get((name or "").strip().lower())
    if not start:
        return {"nodes": [], "edges": [], "center": None}
    adj: dict[str, set] = {}
    for e in full["edges"]:
        adj.setdefault(e["source"], set()).add(e["target"])
        adj.setdefault(e["target"], set()).add(e["source"])
    keep = {start}
    frontier = {start}
    for _ in range(max(0, int(depth))):
        nxt = set()
        for node in frontier:
            nxt |= adj.get(node, set())
        nxt -= keep
        if not nxt:
            break
        keep |= nxt
        frontier = nxt
    nodes = [n for n in full["nodes"] if n["id"] in keep]
    edges = [e for e in full["edges"] if e["source"] in keep and e["target"] in keep]
    return {"nodes": nodes, "edges": edges, "center": start}
