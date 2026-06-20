"""tiny currency converter (4d). offline-first: a static USD-relative table is the
source of truth so net-worth roll-ups are deterministic and work with no network.
refresh() can pull ECB daily rates when you want them, but nothing calls it
automatically — the app never depends on a reachable network."""

# 1 USD = RATES[code] units of that currency
RATES = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "JPY": 150.0,
    "CAD": 1.36,
    "AUD": 1.52,
    "INR": 83.0,
    "CHF": 0.88,
    "CNY": 7.2,
    "MXN": 17.0,
}

_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR", "Fr": "CHF"}


def code(cur):
    """normalize a currency symbol or code → an ISO code we know (default USD)."""
    cur = (cur or "USD").strip()
    if cur.upper() in RATES:
        return cur.upper()
    return _SYMBOL.get(cur, "USD")


def get_rates():
    return dict(RATES)


def convert(amount, frm, to, rates=None):
    rates = rates or RATES
    f, t = code(frm), code(to)
    rf = rates.get(f, 1.0) or 1.0
    rt = rates.get(t, 1.0) or 1.0
    usd = (amount or 0.0) / rf  # native → USD
    return round(usd * rt, 2)  # USD → target


def refresh():
    """best-effort ECB pull (manual). updates RATES in place; returns True on success.
    EUR-based feed → re-based to USD. never raises."""
    try:
        import urllib.request
        import xml.etree.ElementTree as ET

        url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
        with urllib.request.urlopen(url, timeout=4) as r:  # noqa: S310
            root = ET.fromstring(r.read())
        eur = {"EUR": 1.0}
        for cube in root.iter():
            c, rate = cube.get("currency"), cube.get("rate")
            if c and rate:
                eur[c] = float(rate)
        usd = eur.get("USD")
        if not usd:
            return False
        RATES.clear()
        for c, v in eur.items():
            RATES[c] = round(v / usd, 6)  # re-base EUR feed onto USD=1.0
        RATES["USD"] = 1.0
        return True
    except Exception:
        return False
