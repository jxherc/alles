"""
books — a reading list. shelves (want / reading / done), ratings, notes, and an
optional keyless OpenLibrary lookup to autofill cover + author from a title or ISBN.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import Book, get_db

router = APIRouter(prefix="/api")

STATUSES = ("want", "reading", "done")


# ── pure helpers ──────────────────────────────────────────────────────────────
def clamp_rating(r) -> int:
    try:
        return max(0, min(5, int(r)))
    except (TypeError, ValueError):
        return 0


def year_count(books, year: int) -> int:
    return sum(1 for b in books if b.status == "done" and str(b.finished)[:4] == str(year))


def parse_ol_doc(doc: dict) -> dict:
    """pull the fields we want out of an OpenLibrary search doc."""
    cover_i = doc.get("cover_i")
    authors = doc.get("author_name") or []
    isbns = doc.get("isbn") or []
    return {
        "title": doc.get("title", ""),
        "author": authors[0] if authors else "",
        "cover": f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else "",
        "isbn": isbns[0] if isbns else "",
        "year": doc.get("first_publish_year") or 0,
    }


# ── serialization ──────────────────────────────────────────────────────────────
def _fmt(b: Book) -> dict:
    return {
        "id": b.id,
        "title": b.title,
        "author": b.author,
        "status": b.status,
        "rating": b.rating,
        "started": b.started,
        "finished": b.finished,
        "cover": b.cover,
        "notes": b.notes,
        "isbn": b.isbn,
        "year": b.year,
        "created_at": b.created_at.isoformat() if b.created_at else "",
    }


# ── endpoints ──────────────────────────────────────────────────────────────────
@router.get("/books/overview")
def overview(db: DbSession = Depends(get_db)):
    books = db.query(Book).order_by(Book.created_at.desc()).all()
    shelves = {s: [] for s in STATUSES}
    for b in books:
        shelves.get(b.status, shelves["want"]).append(_fmt(b))
    return {
        "shelves": shelves,
        "this_year": year_count(books, date.today().year),
        "total": len(books),
    }


@router.get("/books/lookup")
def lookup(q: str = "", db: DbSession = Depends(get_db)):
    """best-effort OpenLibrary search (keyless). returns a few candidates to autofill."""
    if not q.strip():
        return {"results": []}
    try:
        import httpx

        r = httpx.get(
            "https://openlibrary.org/search.json", params={"q": q, "limit": 6}, timeout=10
        )
        docs = r.json().get("docs", [])
        return {"results": [parse_ol_doc(d) for d in docs]}
    except Exception:
        return {"results": []}


class BookBody(BaseModel):
    title: str
    author: str = ""
    status: str = "want"
    rating: int = 0
    cover: str = ""
    isbn: str = ""
    notes: str = ""
    year: int = 0


@router.post("/books")
def create_book(body: BookBody, db: DbSession = Depends(get_db)):
    if not body.title.strip():
        raise HTTPException(400, "title required")
    if body.status not in STATUSES:
        raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")
    b = Book(
        title=body.title.strip(),
        author=body.author.strip(),
        status=body.status,
        rating=clamp_rating(body.rating),
        cover=body.cover.strip(),
        isbn=body.isbn.strip(),
        notes=body.notes,
        year=body.year,
        started=date.today().isoformat() if body.status == "reading" else "",
        finished=date.today().isoformat() if body.status == "done" else "",
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return _fmt(b)


class BookPatch(BaseModel):
    title: str | None = None
    author: str | None = None
    status: str | None = None
    rating: int | None = None
    started: str | None = None
    finished: str | None = None
    cover: str | None = None
    notes: str | None = None
    isbn: str | None = None


@router.patch("/books/{bid}")
def update_book(bid: str, body: BookPatch, db: DbSession = Depends(get_db)):
    b = db.get(Book, bid)
    if not b:
        raise HTTPException(404)
    if body.status is not None:
        if body.status not in STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")
        # stamp milestones when moving shelves (only if not already set)
        if body.status == "reading" and not b.started:
            b.started = date.today().isoformat()
        if body.status == "done" and not b.finished:
            b.finished = date.today().isoformat()
        b.status = body.status
    if body.rating is not None:
        b.rating = clamp_rating(body.rating)
    for f in ("title", "author", "started", "finished", "cover", "notes", "isbn"):
        v = getattr(body, f)
        if v is not None:
            setattr(b, f, v.strip() if isinstance(v, str) and f in ("title", "author") else v)
    db.commit()
    return _fmt(b)


@router.delete("/books/{bid}")
def delete_book(bid: str, db: DbSession = Depends(get_db)):
    b = db.get(Book, bid)
    if not b:
        raise HTTPException(404)
    db.delete(b)
    db.commit()
    return {"ok": True}
