"""csv importers — pure parsers (unit-tested), no db. the routes call these then
create rows. goodreads export → books; a simple date/kind/value csv → health."""

import csv
import io

from services.health_entries import HealthInputError, finite_value

_SHELF = {"read": "done", "currently-reading": "reading", "to-read": "want"}


def _int(v, default=0):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def parse_goodreads_csv(text) -> list[dict]:
    """map a goodreads library export to book dicts."""
    out = []
    try:
        reader = csv.DictReader(io.StringIO(text))
    except Exception:
        return []
    for row in reader:
        title = (row.get("Title") or "").strip()
        if not title:
            continue
        shelf = (row.get("Exclusive Shelf") or "").strip().lower()
        status = _SHELF.get(shelf, "want")
        rating = max(0, min(5, _int(row.get("My Rating"))))
        # goodreads wraps isbns as ="9780..." to stop excel mangling them
        isbn = (row.get("ISBN13") or "").strip().lstrip("=").strip('"')
        date_read = (row.get("Date Read") or "").strip().replace("/", "-")
        out.append(
            {
                "title": title,
                "author": (row.get("Author") or "").strip(),
                "status": status,
                "rating": rating,
                "finished": date_read if status == "done" else "",
                "isbn": isbn,
                "year": _int(row.get("Year Published")),
            }
        )
    return out


def iter_health_csv(text, *, strict=False):
    """Yield the source line and parsed row, or None for a non-finite/missing value."""
    reader = csv.DictReader(io.StringIO(text.removeprefix("\ufeff")), strict=True)
    try:
        headers = [(name or "").strip().lower() for name in reader.fieldnames or []]
        if len(set(headers)) != len(headers):
            raise HealthInputError("CSV column names must be unique")
        for row in reader:
            if strict and None in row:
                raise HealthInputError(
                    f"line {reader.line_num} has more cells than the header; nothing imported"
                )
            r = {(k or "").strip().lower(): v for k, v in row.items()}
            try:
                value = finite_value(r.get("value"))
            except HealthInputError:
                yield reader.line_num, None
                continue
            kind = (r.get("kind") or r.get("metric") or "custom").strip() or "custom"
            yield (
                reader.line_num,
                {
                    "kind": kind,
                    "value": value,
                    "unit": (r.get("unit") or "").strip(),
                    "date": (r.get("date") or "").strip(),
                },
            )
    except csv.Error:
        raise HealthInputError(f"could not read CSV near line {reader.line_num}") from None


def parse_health_csv(text) -> list[dict]:
    """Keep the legacy parser's valid-row list for callers that skip invalid values."""
    return [
        {**row, "date": row["date"][:10]} for _, row in iter_health_csv(text) if row is not None
    ]
