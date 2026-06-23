"""2c - spending anomaly detection: category spend spikes vs history + new merchants.
pure + testable; reuses 2b (forecast.category_averages) and 2a (money_query._norm_payee).
"""

from services.forecast import _recent_months, category_averages
from services.money_query import _norm_payee


def category_anomalies(db, *, as_of, months=3, ratio=1.5, min_amount=50.0):
    """categories whose THIS-month spend is >= ratio x the historical monthly average."""
    from routes.money import _spending_by_cat

    avg = category_averages(db, months=months, as_of=as_of)
    cur = _spending_by_cat(db, as_of.strftime("%Y-%m"))
    out = []
    for cat, spent in cur.items():
        base = avg.get(cat, 0.0)
        if spent >= min_amount and base > 0 and spent >= base * ratio:
            out.append(
                {
                    "category": cat,
                    "current": round(spent, 2),
                    "baseline": round(base, 2),
                    "ratio": round(spent / base, 2),
                }
            )
    return sorted(out, key=lambda x: -x["ratio"])


def new_merchants(db, *, as_of, months=3, min_amount=20.0):
    """normalized merchants seen THIS month but not in the prior `months`."""
    from core.database import Account, Transaction

    cur_month = as_of.strftime("%Y-%m")
    prior = set(_recent_months(as_of, months))
    accts = {a.id for a in db.query(Account).filter_by(archived=False).all()}
    cur_m, prior_m = {}, set()
    for t in db.query(Transaction).all():
        # income (>=0) + transfer legs are not merchant spending (consistent with _spending_by_cat)
        if t.account_id not in accts or (t.amount or 0) >= 0 or t.transfer_id:
            continue
        m = _norm_payee(t.payee or "")
        if not m:
            continue
        mo = (t.date or "")[:7]
        if mo == cur_month:
            cur_m[m] = cur_m.get(m, 0.0) + (-(t.amount or 0.0))
        elif mo in prior:
            prior_m.add(m)
    return [
        {"merchant": m, "amount": round(v, 2)}
        for m, v in sorted(cur_m.items(), key=lambda x: -x[1])
        if m not in prior_m and v >= min_amount
    ]
