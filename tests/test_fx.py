import unittest
from unittest import mock

from services import fx


class FxTests(unittest.TestCase):
    def test_fx_convert_same(self):
        self.assertEqual(fx.convert(100, "USD", "USD"), 100.0)

    def test_fx_convert_cross(self):
        self.assertEqual(fx.convert(100, "USD", "EUR"), 92.0)  # 1 USD = 0.92 EUR

    def test_fx_convert_back(self):
        # EUR → USD then USD → EUR round-trips close to the original
        usd = fx.convert(100, "EUR", "USD")
        self.assertAlmostEqual(fx.convert(usd, "USD", "EUR"), 100.0, delta=0.5)

    def test_fx_symbol_map(self):
        self.assertEqual(fx.code("$"), "USD")
        self.assertEqual(fx.code("€"), "EUR")
        self.assertEqual(fx.code("£"), "GBP")
        self.assertEqual(fx.code("usd"), "USD")
        self.assertEqual(fx.code("???"), "USD")

    def test_zero_amount(self):
        self.assertEqual(fx.convert(0, "USD", "EUR"), 0.0)

    def test_none_amount(self):
        # None amount treated as 0
        self.assertEqual(fx.convert(None, "USD", "JPY"), 0.0)

    def test_jpy_convert(self):
        # 1 USD = 150 JPY per static table
        self.assertEqual(fx.convert(1, "USD", "JPY"), 150.0)

    def test_jpy_to_usd(self):
        result = fx.convert(150, "JPY", "USD")
        self.assertAlmostEqual(result, 1.0, delta=0.01)

    def test_get_rates_returns_copy(self):
        rates = fx.get_rates()
        self.assertIn("USD", rates)
        self.assertEqual(rates["USD"], 1.0)
        # mutating the returned dict doesn't affect the module
        rates["USD"] = 99
        self.assertEqual(fx.RATES["USD"], 1.0)

    def test_yen_symbol(self):
        self.assertEqual(fx.code("¥"), "JPY")

    def test_inr_symbol(self):
        self.assertEqual(fx.code("₹"), "INR")

    def test_custom_rates_dict(self):
        # rates= overrides the table, but convert() still normalizes codes through code(),
        # so the keys have to be currencies it knows (EUR), not arbitrary ones
        custom = {"USD": 1.0, "EUR": 2.0}
        result = fx.convert(100, "USD", "EUR", rates=custom)
        self.assertEqual(result, 200.0)

    def test_refresh_network_error_returns_false(self):
        # never raises, and a dead network leaves RATES untouched (no leak into other tests)
        before = dict(fx.RATES)
        with mock.patch("urllib.request.urlopen", side_effect=OSError("no net")):
            self.assertEqual(fx.refresh(), False)
        self.assertEqual(fx.RATES, before)

    def test_refresh_parses_and_rebases_to_usd(self):
        # fake ECB EUR-based feed → refresh re-bases onto USD=1.0. restore RATES after so
        # the global table can't bleed into the money/net-worth tests that run later.
        xml = (
            '<gesmes:Envelope xmlns:gesmes="x" xmlns="y">'
            "<Cube><Cube time='2026-01-01'>"
            "<Cube currency='USD' rate='1.10'/>"
            "<Cube currency='GBP' rate='0.85'/>"
            "</Cube></Cube></gesmes:Envelope>"
        )
        cm = mock.MagicMock()
        cm.read.return_value = xml.encode()
        cm.__enter__.return_value = cm
        before = dict(fx.RATES)
        try:
            with mock.patch("urllib.request.urlopen", return_value=cm):
                self.assertEqual(fx.refresh(), True)
            self.assertEqual(fx.RATES["USD"], 1.0)
            # GBP re-based: 0.85 EUR / 1.10 USD-per-EUR
            self.assertAlmostEqual(fx.RATES["GBP"], round(0.85 / 1.10, 6), places=6)
        finally:
            fx.RATES.clear()
            fx.RATES.update(before)


if __name__ == "__main__":
    unittest.main()
