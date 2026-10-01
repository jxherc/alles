"""2e - tag rules (payee -> tag), tag hierarchy (food/coffee -> food), tag-budget rollup.

pure + testable. mirrors routes/money._categorize for tags; spending_by_tag rolls each txn's tags
up through their ancestors so a 'food/coffee' charge counts toward a 'food' budget.
"""

from core.database import Transaction


def _norm(csv):
    seen, out = set(), []
    for t in (csv or "").split(","):
        t = t.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return ",".join(out)


def apply_rules(payee, rules, existing=""):
    """add tags from every rule whose match is a substring of payee, merged into existing."""
    p = (payee or "").lower()
    tags = [t for t in (existing or "").split(",") if t.strip()]
    if p:
        for r in rules:
            m = (r.match or "").lower()
            if m and m in p:
                tags.extend((r.tags or "").split(","))
    return _norm(",".join(tags))


def ancestors(tag):
    """'a/b/c' -> ['a/b/c','a/b','a']."""
    parts = [p for p in (tag or "").split("/") if p]
    return ["/".join(parts[:i]) for i in range(len(parts), 0, -1)]


def expand(csv):
    """expand each tag to include its ancestors. 'food/coffee' -> {'food/coffee','food'}."""
    out = set()
    for t in (csv or "").split(","):
        t = t.strip().lower()
        if t:
            out.update(ancestors(t))
    return out


def spending_by_tag(db, month):
    """expense rolled up per tag for `month`, honoring hierarchy. income + transfers excluded."""
    from sqlalchemy import or_

    by = {}
    # month + expense + transfer filters in sql instead of a full-table scan
    rows = (
        db.query(Transaction)
        .filter(
            Transaction.date.like(f"{month}%"),
            Transaction.amount < 0,
            or_(Transaction.transfer_id.is_(None), Transaction.transfer_id == ""),
        )
        .all()
    )
    for t in rows:
        for tag in expand(t.tags or ""):
            by[tag] = by.get(tag, 0.0) + (-(t.amount or 0.0))
    return by
