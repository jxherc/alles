"""Ordinary book saves shared by the Books screen and Aide."""

from datetime import date

from sqlalchemy.orm import Session

from core.database import Book

STATUSES = ("want", "reading", "done")


class BookInputError(ValueError):
    def __init__(self, field: str):
        self.field = field
        super().__init__(field)


def clamp_rating(r) -> int:
    try:
        return max(0, min(5, int(r)))
    except (TypeError, ValueError):
        return 0


def save_book(
    db: Session,
    *,
    title: str,
    author: str = "",
    status: str = "want",
    rating: int = 0,
    cover: str = "",
    isbn: str = "",
    notes: str = "",
    year: int = 0,
) -> Book:
    title = title.strip()
    if not title:
        raise BookInputError("title")
    if status not in STATUSES:
        raise BookInputError("status")
    book = Book(
        title=title,
        author=author.strip(),
        status=status,
        rating=clamp_rating(rating),
        cover=cover.strip(),
        isbn=isbn.strip(),
        notes=notes,
        year=year,
        started=date.today().isoformat() if status == "reading" else "",
        finished=date.today().isoformat() if status == "done" else "",
    )
    db.add(book)
    db.commit()
    db.refresh(book)
    try:
        from services import personal_index

        personal_index.index_record(db, "book", book)
    except Exception:
        pass
    return book
