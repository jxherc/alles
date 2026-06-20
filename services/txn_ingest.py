"""shared transaction ingestion + recurring detection (1f).

parse_ofx: read OFX/QFX bank exports (both 1.x SGML and 2.x XML) into plain dicts.
detect_recurring: cluster transactions by payee + amount and infer a billing cycle from
the spacing, so money (bills) and subs (auto-detect, 4e) can propose recurring charges.
"""

import re
import statistics
from datetime import date


def _payee_norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_ofx(text: str) -> list[dict]:
    """extract STMTTRN records. returns [{date 'YYYY-MM-DD', amount float, payee, memo, fitid}]."""
    out = []
    text = text or ""
    for block in re.split(r"(?i)<STMTTRN>", text)[1:]:
        block = re.split(r"(?i)</STMTTRN>", block)[0]

        def tag(name, b=block):
            m = re.search(rf"(?i)<{name}>([^<\r\n]+)", b)
            return m.group(1).strip() if m else ""

        dt = tag("DTPOSTED")
        amt = tag("TRNAMT")
        if not dt or not amt:
            continue
        try:
            amount = float(amt.replace(",", ""))
        except ValueError:
            continue
        ds = re.sub(r"[^0-9]", "", dt)[:8]
        if len(ds) < 8:
            continue
        iso = f"{ds[0:4]}-{ds[4:6]}-{ds[6:8]}"
        name = tag("NAME") or tag("MEMO")
        out.append(
            {
                "date": iso,
                "amount": amount,
                "payee": name,
                "memo": tag("MEMO"),
                "fitid": tag("FITID"),
            }
        )
    return out


def _cycle_for(gap_days: float) -> str | None:
    if 5 <= gap_days <= 9:
        return "weekly"
    if 12 <= gap_days <= 16:
        return "weekly"  # biweekly → closest supported cycle
    if 26 <= gap_days <= 35:
        return "monthly"
    if 84 <= gap_days <= 96:
        return "quarterly"
    if 360 <= gap_days <= 372:
        return "yearly"
    return None


def detect_recurring(txns: list[dict], min_count: int = 3) -> list[dict]:
    """txns: [{date 'YYYY-MM-DD', amount, payee}]. returns recurring candidates
    [{payee, amount, cycle, count, last_date}] sorted by count desc."""
    groups: dict[tuple, list[dict]] = {}
    for t in txns:
        d = (t.get("date") or "")[:10]
        if not d:
            continue
        try:
            y, m, dd = (int(x) for x in d.split("-"))
            day = date(y, m, dd)
        except Exception:
            continue
        key = (_payee_norm(t.get("payee", "")), round(float(t.get("amount") or 0.0), 2))
        if not key[0]:
            continue
        groups.setdefault(key, []).append({"day": day, "payee": t.get("payee", "")})

    out = []
    for (norm, amount), items in groups.items():
        if len(items) < min_count:
            continue
        items.sort(key=lambda x: x["day"])
        gaps = [(items[i]["day"] - items[i - 1]["day"]).days for i in range(1, len(items))]
        gaps = [g for g in gaps if g > 0]
        if not gaps:
            continue
        med = statistics.median(gaps)
        cycle = _cycle_for(med)
        if not cycle:
            continue
        out.append(
            {
                "payee": items[-1]["payee"],
                "amount": amount,
                "cycle": cycle,
                "count": len(items),
                "last_date": items[-1]["day"].isoformat(),
            }
        )
    out.sort(key=lambda c: c["count"], reverse=True)
    return out
