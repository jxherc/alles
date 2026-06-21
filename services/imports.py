"""csv importers — pure parsers (unit-tested), no db. the routes call these then
create rows. goodreads export → books; a simple date/kind/value csv → health."""

import csv
import io

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


def parse_health_csv(text) -> list[dict]:
    """parse a simple csv with date / kind(or metric) / value / unit columns."""
    out = []
    try:
        reader = csv.DictReader(io.StringIO(text))
    except Exception:
        return []
    for row in reader:
        r = {(k or "").strip().lower(): v for k, v in row.items()}
        try:
            value = float(r.get("value"))
        except (TypeError, ValueError):
            continue
        kind = (r.get("kind") or r.get("metric") or "custom").strip() or "custom"
        out.append(
            {
                "kind": kind,
                "value": value,
                "unit": (r.get("unit") or "").strip(),
                "date": (r.get("date") or "").strip()[:10],
            }
        )
    return out
