import unittest
from services.vcard import to_vcard, parse_vcards


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


if __name__ == "__main__":
    unittest.main()
