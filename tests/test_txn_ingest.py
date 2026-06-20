import unittest
from datetime import date, timedelta

from services import txn_ingest as ti

OFX_SGML = """
OFXHEADER:100
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20240115120000[-5:EST]
<TRNAMT>-15.99
<NAME>NETFLIX.COM
<FITID>aaa1
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20240116
<TRNAMT>2000.00
<NAME>ACME PAYROLL
<FITID>bbb2
</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""

OFX_XML = """<?xml version="1.0"?>
<OFX><STMTTRN><DTPOSTED>20240201</DTPOSTED><TRNAMT>-9.99</TRNAMT><NAME>Spotify</NAME><FITID>x1</FITID></STMTTRN></OFX>
"""


class ParseOfxTests(unittest.TestCase):
    def test_parse_basic(self):
        rows = ti.parse_ofx(OFX_SGML)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["date"], "2024-01-15")
        self.assertEqual(rows[0]["amount"], -15.99)
        self.assertIn("NETFLIX", rows[0]["payee"].upper())

    def test_parse_xml(self):
        rows = ti.parse_ofx(OFX_XML)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["payee"], "Spotify")
        self.assertEqual(rows[0]["amount"], -9.99)

    def test_parse_amount_sign(self):
        rows = ti.parse_ofx(OFX_SGML)
        self.assertEqual(rows[1]["amount"], 2000.00)

    def test_parse_skips_incomplete(self):
        bad = "<STMTTRN><NAME>NoAmount</NAME></STMTTRN>"
        self.assertEqual(ti.parse_ofx(bad), [])

    def test_parse_empty(self):
        self.assertEqual(ti.parse_ofx(""), [])

    def test_parse_date_strips_time(self):
        rows = ti.parse_ofx(OFX_SGML)
        self.assertEqual(rows[0]["date"], "2024-01-15")  # time/tz dropped


def _series(payee, amount, start, n, step_days):
    d = date.fromisoformat(start)
    return [
        {"date": (d + timedelta(days=step_days * i)).isoformat(), "amount": amount, "payee": payee}
        for i in range(n)
    ]


class DetectRecurringTests(unittest.TestCase):
    def test_detects_monthly(self):
        txns = _series("Netflix", -15.99, "2024-01-15", 4, 30)
        c = ti.detect_recurring(txns)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["cycle"], "monthly")
        self.assertEqual(c[0]["count"], 4)

    def test_ignores_below_min_count(self):
        txns = _series("Netflix", -15.99, "2024-01-15", 2, 30)
        self.assertEqual(ti.detect_recurring(txns), [])

    def test_ignores_irregular(self):
        txns = [
            {"date": "2024-01-01", "amount": -5.0, "payee": "Random"},
            {"date": "2024-01-03", "amount": -5.0, "payee": "Random"},
            {"date": "2024-03-20", "amount": -5.0, "payee": "Random"},
        ]
        self.assertEqual(ti.detect_recurring(txns), [])

    def test_groups_by_amount(self):
        txns = _series("Shop", -10.0, "2024-01-01", 3, 30) + _series(
            "Shop", -25.0, "2024-01-05", 3, 30
        )
        c = ti.detect_recurring(txns)
        amounts = sorted(x["amount"] for x in c)
        self.assertEqual(amounts, [-25.0, -10.0])

    def test_weekly_detected(self):
        c = ti.detect_recurring(_series("Gym", -8.0, "2024-01-01", 5, 7))
        self.assertTrue(c and c[0]["cycle"] == "weekly")

    def test_yearly_detected(self):
        c = ti.detect_recurring(_series("Domain", -12.0, "2020-06-01", 3, 365))
        self.assertTrue(c and c[0]["cycle"] == "yearly")

    def test_sorted_by_count(self):
        txns = _series("A", -1.0, "2024-01-01", 5, 30) + _series("B", -2.0, "2024-01-01", 3, 30)
        c = ti.detect_recurring(txns)
        self.assertEqual(c[0]["count"], 5)

    def test_different_payees_separate(self):
        txns = _series("Netflix", -15.0, "2024-01-01", 3, 30) + _series(
            "Spotify", -10.0, "2024-01-01", 3, 30
        )
        self.assertEqual(len(ti.detect_recurring(txns)), 2)

    def test_blank_payee_ignored(self):
        txns = _series("", -5.0, "2024-01-01", 4, 30)
        self.assertEqual(ti.detect_recurring(txns), [])


if __name__ == "__main__":
    unittest.main()
