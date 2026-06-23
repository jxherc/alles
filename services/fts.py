"""3i - first-class FTS5 full-text store: phrase / negation / prefix queries, field-ranked (title
weighted above body via bm25), cross-kind. raw SQL over the same sqlite connection as the ORM.

complements the embedding index (textindex): FTS5 is for precise keyword/phrase/boolean queries,
embeddings for fuzzy semantic recall.
"""

from sqlalchemy import text

_TABLE = "fts_docs"

# kind -> bm25 column weight pair (title, body). a kind can register its own weighting + an index_fn.
REGISTRY = {}


def register(kind, *, title_weight=2.0, body_weight=1.0, index_fn=None):
    REGISTRY[kind] = {
        "title_weight": title_weight,
        "body_weight": body_weight,
        "index_fn": index_fn,
    }


def ensure(db):
    db.execute(
        text(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {_TABLE} USING fts5("
            "kind, ref UNINDEXED, title, body, tokenize='porter')"
        )
    )
    db.commit()


def remove(db, kind, ref):
    db.execute(text(f"DELETE FROM {_TABLE} WHERE kind = :k AND ref = :r"), {"k": kind, "r": ref})
    db.commit()


def index(db, kind, ref, body, title=""):
    """upsert one document (delete the existing kind+ref, then insert)."""
    remove(db, kind, ref)
    db.execute(
        text(f"INSERT INTO {_TABLE} (kind, ref, title, body) VALUES (:k, :r, :t, :b)"),
        {"k": kind, "r": ref, "t": title or "", "b": body or ""},
    )
    db.commit()


def on_mutation(db, kind, ref, text_body, title=""):
    """spine hook: (re)index a row when it changes. kind weights come from the registry if set."""
    ensure(db)
    index(db, kind, ref, text_body, title)


def clear(db):
    db.execute(text(f"DELETE FROM {_TABLE}"))
    db.commit()


def search(db, query, kind=None, limit=10):
    """FTS5 MATCH over title+body. phrase ("..."), negation (NOT), prefix (foo*) pass through.
    ordered by bm25 with title weighted above body. returns [{kind, ref, title, score}]."""
    q = (query or "").strip()
    if not q:
        return []
    tw, bw = 2.0, 1.0
    if kind and kind in REGISTRY:
        tw, bw = REGISTRY[kind]["title_weight"], REGISTRY[kind]["body_weight"]
    sql = (
        f"SELECT kind, ref, title, bm25({_TABLE}, 0.0, 0.0, :tw, :bw) AS score "
        f"FROM {_TABLE} WHERE {_TABLE} MATCH :q"
    )
    params = {"q": q, "tw": tw, "bw": bw}
    if kind:
        sql += " AND kind = :kind"
        params["kind"] = kind
    sql += " ORDER BY score LIMIT :lim"  # bm25 is negative; lower = better
    params["lim"] = max(1, int(limit))
    try:
        rows = db.execute(text(sql), params).fetchall()
    except Exception:
        # a malformed MATCH expression (unbalanced quote, etc.) shouldn't blow up the caller
        db.rollback()
        return []
    return [{"kind": r[0], "ref": r[1], "title": r[2], "score": round(r[3], 4)} for r in rows]
