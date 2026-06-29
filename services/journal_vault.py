"""
Opt-in mirror of journal entries to Obsidian daily notes.

Off by default. When `journal_mirror_vault` is on AND no passcode is set, each entry
is written to `Journal/YYYY-MM-DD.md` (frontmatter mood/tags, body = content). You can
edit it in either place — the vault watcher folds Obsidian edits back into the DB row.

Setting a passcode auto-pauses the mirror and purges the plaintext files, so turning the
lock on actually re-privatises. Removing the passcode re-mirrors if the toggle is still on.
The DB stays the source of truth for the lock + mood analytics; the files are just a window.
"""

import re

from core.settings import load_settings
from services import vault_md

JOURNAL_DIR = "Journal"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _rel(day: str) -> str:
    return f"{JOURNAL_DIR}/{day}.md"


def enabled() -> bool:
    # only mirror when turned on AND the journal isn't passcode-locked
    s = load_settings()
    return bool(s.get("journal_mirror_vault")) and not s.get("journal_passcode")


def is_daily(path: str):
    """rel path -> the YYYY-MM-DD day if it's a journal daily note, else None."""
    from pathlib import PurePosixPath

    p = PurePosixPath((path or "").replace("\\", "/"))
    if len(p.parts) == 2 and p.parts[0] == JOURNAL_DIR and p.suffix.lower() == ".md":
        if _DATE.match(p.stem):
            return p.stem
    return None


def _compose(content, mood, tags) -> str:
    fm = []
    if mood:
        fm.append(f"mood: {mood}")
    if tags:
        fm.append(f"tags: {tags}")
    head = "---\n" + "\n".join(fm) + "\n---\n\n" if fm else ""
    return head + (content or "").strip() + "\n"


def write_entry(day, content, mood="", tags=""):
    day = str(day)[:10]
    if not _DATE.match(day):
        return
    try:
        vault_md.write(_rel(day), _compose(content, mood, tags))
    except Exception:
        pass


def delete_entry(day):
    day = str(day)[:10]
    try:
        vault_md.delete(_rel(day))
    except Exception:
        pass


def read_entry(day):
    """parse a daily note back to {content, mood, tags}, or None if it's missing."""
    day = str(day)[:10]
    try:
        p = vault_md._safe(_rel(day))
    except ValueError:
        return None
    if not p.is_file():
        return None
    props, body = vault_md.parse_frontmatter(p.read_text("utf-8", errors="replace"))
    tags = props.get("tags", "")
    if isinstance(tags, list):
        tags = ", ".join(str(t) for t in tags)
    return {
        "content": body.strip(),
        "mood": str(props.get("mood", "") or "").strip(),
        "tags": str(tags).strip(),
    }


def sync_from_vault(db, day):
    """an Obsidian edit to a daily note -> update/create the DB row. idempotent: a no-op
    when the row already matches (so our own mirror write echoing back does nothing)."""
    if not enabled():  # don't fold vault edits in while the journal is locked
        return
    from core.database import JournalEntry, _now

    parsed = read_entry(day)
    if parsed is None:  # file gone — leave the DB row alone (deletes go through the app)
        return
    e = db.query(JournalEntry).filter(JournalEntry.date == day).first()
    if e and (e.content or "") == parsed["content"] and (e.mood or "") == parsed["mood"] \
            and (e.tags or "") == parsed["tags"]:
        return
    if e:
        e.content, e.mood, e.tags = parsed["content"], parsed["mood"][:40], parsed["tags"]
        e.updated_at = _now()
    else:
        e = JournalEntry(date=day, content=parsed["content"], mood=parsed["mood"][:40],
                         tags=parsed["tags"])
        db.add(e)
    db.commit()
    try:
        from services import personal_index
        personal_index.index_record(db, "journal", e)
    except Exception:
        pass


def backfill():
    """write every existing entry to the vault (when the mirror gets turned on)."""
    from core.database import JournalEntry, SessionLocal

    db = SessionLocal()
    try:
        for e in db.query(JournalEntry).all():
            write_entry(e.date, e.content or "", e.mood or "", e.tags or "")
    finally:
        db.close()


def purge():
    """remove every mirrored daily note (mirror turned off / a passcode set)."""
    base = vault_md.vault_dir() / JOURNAL_DIR
    if not base.is_dir():
        return
    for p in base.glob("*.md"):
        if _DATE.match(p.stem):
            try:
                p.unlink()
            except OSError:
                pass
