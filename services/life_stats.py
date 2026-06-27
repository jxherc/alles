"""4b - life-tracking statistics: mood<->behavior Spearman correlation, habit failure risk, and
health baselines + anomaly bands. pure (operate on plain lists), so they're cheap + testable.
"""

import datetime
from math import sqrt


def _rank(xs):
    """average ranks (ties share the mean rank)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1  # 1-based average rank
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / sqrt(vx * vy)


def spearman(xs, ys):
    """rank correlation. None if fewer than 3 points or a series has no variance."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    return _pearson(_rank(xs), _rank(ys))


_MOOD = {
    5: ("great", "amazing", "ecstatic", "joyful", "fantastic", "excellent", "😄", "😁", "🤩"),
    4: ("happy", "good", "content", "calm", "relaxed", "🙂", "😊"),
    3: ("meh", "ok", "okay", "neutral", "fine", "😐"),
    2: ("down", "tired", "anxious", "stressed", "low", "😕", "😟"),
    1: ("sad", "awful", "terrible", "depressed", "miserable", "angry", "😢", "😞", "😠"),
}


def mood_score(s):
    """map a mood word/emoji to 1..5; unknown -> 3 (neutral)."""
    t = (s or "").strip().lower()
    for score, words in _MOOD.items():
        if any(w in t for w in words):
            return score
    return 3


def _strength(rho):
    a = abs(rho)
    if a >= 0.6:
        return "strong"
    if a >= 0.3:
        return "moderate"
    if a >= 0.1:
        return "weak"
    return "none"


def correlate(pairs):
    """pairs = [(x, y)]. returns {rho, n, strength, direction} (explainable)."""
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    rho = spearman(xs, ys)
    if rho is None:
        return {"rho": None, "n": len(pairs), "strength": "none", "direction": "none"}
    return {
        "rho": round(rho, 3),
        "n": len(pairs),
        "strength": _strength(rho),
        "direction": "positive" if rho > 0 else ("negative" if rho < 0 else "none"),
    }


def habit_failure_risk(done_dates, today, *, window=14):
    """risk (0..1) of failing today, from the recent completion rate over `window` days."""
    window = max(1, int(window))  # ?window=0 from the risk endpoint would divide by zero; negatives are nonsense too
    if isinstance(today, str):
        today = datetime.date.fromisoformat(today)
    done = set(done_dates or [])
    hit = 0
    for i in range(1, window + 1):
        d = (today - datetime.timedelta(days=i)).isoformat()
        if d in done:
            hit += 1
    rate = hit / window
    risk = round(1 - rate, 3)
    if rate >= 0.8:
        reason = "strong recent streak"
    elif rate >= 0.4:
        reason = f"done {hit}/{window} recent days - keep it up"
    else:
        reason = f"only {hit}/{window} recent days - at risk of slipping"
    return {"risk": risk, "recent_rate": round(rate, 3), "reason": reason}


def health_baseline(values):
    vals = [float(v) for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return {"mean": 0.0, "std": 0.0, "n": 0}
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    return {"mean": round(mean, 4), "std": round(sqrt(var), 4), "n": n}


def _median(xs):
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def health_anomalies(series, *, k=2.0):
    """series = [(date, value)]. flag points whose robust modified z-score (median + MAD) exceeds k.
    MAD resists masking - a lone spike doesn't inflate the scale the way mean+std does, and a
    near-constant series with sub-unit jitter stays unflagged."""
    vals = [float(v) for _, v in series]
    if len(vals) < 3:
        return []
    med = _median(vals)
    mad = _median([abs(x - med) for x in vals])
    if mad == 0:
        return []  # over half the points identical - no robust scale
    out = []
    for (d, v), x in zip(series, vals):
        z = 0.6745 * (x - med) / mad  # modified z-score
        if abs(z) >= k:
            out.append({"date": d, "value": v, "z": round(z, 2)})
    return out
