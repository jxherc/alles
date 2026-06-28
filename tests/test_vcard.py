import unittest

from services.vcard import parse_vcards, to_vcard


class VcardTests(unittest.TestCase):
    def test_roundtrip(self):
        contacts = [
            {
                "name": "Ada Lovelace",
                "email": "ada@x.com",
                "phone": "+1 555 0100",
                "notes": "first programmer",
            },
            {"name": "Grace Hopper", "email": "grace@navy.mil", "phone": "", "notes": ""},
        ]
        vcf = to_vcard(contacts)
        self.assertIn("BEGIN:VCARD", vcf)
        self.assertIn("FN:Ada Lovelace", vcf)
        parsed = parse_vcards(vcf)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["name"], "Ada Lovelace")
        self.assertEqual(parsed[0]["email"], "ada@x.com")
        self.assertEqual(parsed[1]["name"], "Grace Hopper")

    def test_escaping(self):
        p = parse_vcards(to_vcard([{"name": "Smith, John", "notes": "line1\nline2"}]))[0]
        self.assertEqual(p["name"], "Smith, John")
        self.assertEqual(p["notes"], "line1\nline2")

    def test_parses_N_when_no_FN(self):
        p = parse_vcards("BEGIN:VCARD\nVERSION:3.0\nN:Hopper;Grace;;;\nEMAIL:g@x.com\nEND:VCARD")
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]["name"], "Grace Hopper")
        self.assertEqual(p[0]["email"], "g@x.com")

    def test_ignores_empty(self):
        self.assertEqual(parse_vcards(""), [])
        self.assertEqual(parse_vcards("BEGIN:VCARD\nEND:VCARD"), [])  # no name/email

    def test_phone_roundtrip(self):
        vcf = to_vcard([{"name": "Test User", "phone": "+44 20 7946 0958", "email": ""}])
        p = parse_vcards(vcf)
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]["phone"], "+44 20 7946 0958")

    def test_semicolon_in_name_escaped(self):
        vcf = to_vcard([{"name": "O'Brien; James", "email": "j@x.com"}])
        p = parse_vcards(vcf)
        self.assertEqual(p[0]["name"], "O'Brien; James")

    def test_company_and_title_roundtrip(self):
        vcf = to_vcard(
            [{"name": "Alice", "email": "a@x.com", "company": "ACME", "title": "Engineer"}]
        )
        p = parse_vcards(vcf)
        self.assertEqual(p[0]["company"], "ACME")
        self.assertEqual(p[0]["title"], "Engineer")

    def test_website_roundtrip(self):
        vcf = to_vcard([{"name": "Bob", "email": "b@x.com", "website": "https://bob.dev"}])
        p = parse_vcards(vcf)
        self.assertEqual(p[0]["website"], "https://bob.dev")

    def test_birthday_roundtrip(self):
        vcf = to_vcard([{"name": "Eve", "email": "e@x.com", "birthday": "1990-01-15"}])
        p = parse_vcards(vcf)
        self.assertEqual(p[0]["birthday"], "1990-01-15")

    def test_email_only_card_kept(self):
        # cards with email but no name should be kept (name="" but email set)
        p = parse_vcards("BEGIN:VCARD\nVERSION:3.0\nEMAIL:anon@x.com\nEND:VCARD")
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]["email"], "anon@x.com")

    def test_multiple_cards_in_one_vcf(self):
        contacts = [{"name": f"Person {i}", "email": f"p{i}@x.com"} for i in range(5)]
        vcf = to_vcard(contacts)
        parsed = parse_vcards(vcf)
        self.assertEqual(len(parsed), 5)
        for i, p in enumerate(parsed):
            self.assertEqual(p["name"], f"Person {i}")

    def test_unfolds_rfc_line_folding(self):
        # phones/CardDAV fold long values onto a continuation line starting with a space
        # (RFC 2426). the wrapped half used to be silently dropped on import.
        vcf = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Long Note Person\r\n"
            "NOTE:this note is long enough that the exporter wrapped it across two physi\r\n"
            " cal lines\r\n"
            "END:VCARD\r\n"
        )
        p = parse_vcards(vcf)
        self.assertEqual(len(p), 1)
        self.assertEqual(
            p[0]["notes"],
            "this note is long enough that the exporter wrapped it across two physical lines",
        )


if __name__ == "__main__":
    unittest.main()
