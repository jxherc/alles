"""Ordinary book saves shared by the Books screen and Aide."""

import hashlib
import json
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from core.database import Book, BookCreateReceipt

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


def create_identity(value: str) -> str:
    try:
        if str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise HTTPException(400, "request_id must be a canonical UUID")


def _find_request(db: Session, identity: str):
    return (
        db.query(BookCreateReceipt, Book)
        .outerjoin(Book, Book.id == BookCreateReceipt.book_id)
        .filter(BookCreateReceipt.id == identity)
        .populate_existing()
        .first()
    )


def _replay(found, payload_hash: str = "") -> Book:
    if found is None:
        raise HTTPException(404, "book save request not found")
    receipt, book = found
    if payload_hash and receipt.payload_hash != payload_hash:
        raise HTTPException(409, "this request already saved different book details")
    if book is None:
        raise HTTPException(410, "the saved book was deleted; discard this pending save")
    return book


def recover_book(db: Session, request_id: str) -> Book:
    return _replay(_find_request(db, create_identity(request_id)))


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
    request_id: str = "",
) -> Book:
    title = title.strip()
    if not title:
        raise BookInputError("title")
    if status not in STATUSES:
        raise BookInputError("status")
    payload = {
        "title": title,
        "author": author.strip(),
        "status": status,
        "rating": clamp_rating(rating),
        "cover": cover.strip(),
        "isbn": isbn.strip(),
        "notes": notes,
        "year": year,
    }
    identity = create_identity(request_id) if request_id else ""
    if identity:
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        db.execute(sql_text("BEGIN IMMEDIATE"))
        found = _find_request(db, identity)
        if found is not None:
            book = _replay(found, payload_hash)
            db.commit()
            return book
    book = Book(
        **payload,
        started=date.today().isoformat() if status == "reading" else "",
        finished=date.today().isoformat() if status == "done" else "",
    )
    db.add(book)
    if identity:
        db.flush()
        db.add(BookCreateReceipt(id=identity, payload_hash=payload_hash, book_id=book.id))
    db.commit()
    db.refresh(book)
    try:
        from services import personal_index

        personal_index.index_record(db, "book", book)
    except Exception:
        pass
    return book
