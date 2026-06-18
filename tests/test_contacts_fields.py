import unittest

from services.vcard import parse_vcards, to_vcard
from tests._client import ApiTest


class VcardMappingTests(unittest.TestCase):
    def test_export_includes_org_title_url_bday(self):
        v = to_vcard(
            [
                {
                    "name": "Ada Lovelace",
                    "company": "Analytical Engines",
                    "title": "Mathematician",
                    "website": "https://ada.example",
                    "birthday": "1815-12-10",
                    "address": "London",
                }
            ]
        )
        self.assertIn("ORG:Analytical Engines", v)
        self.assertIn("TITLE:Mathematician", v)
        self.assertIn("URL:https://ada.example", v)
        self.assertIn("BDAY:1815-12-10", v)
        self.assertIn("ADR", v)

    def test_parse_org_title_url_bday(self):
        text = (
            "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Bob\r\nORG:Acme\r\nTITLE:Boss\r\n"
            "URL:https://acme.test\r\nBDAY:1990-05-04\r\nADR;TYPE=HOME:;;1 St;;;;\r\nEND:VCARD\r\n"
        )
        c = parse_vcards(text)[0]
        self.assertEqual(c["company"], "Acme")
        self.assertEqual(c["title"], "Boss")
        self.assertEqual(c["website"], "https://acme.test")
        self.assertEqual(c["birthday"], "1990-05-04")

    def test_roundtrip(self):
        orig = {
            "name": "Carol",
            "company": "Co",
            "title": "Eng",
            "birthday": "2000-01-02",
            "website": "https://c.io",
        }
        back = parse_vcards(to_vcard([orig]))[0]
        for k in ("name", "company", "title", "birthday", "website"):
            self.assertEqual(back[k], orig[k])


class ContactFieldApiTests(ApiTest):
    def test_create_with_rich_fields(self):
        r = self.client.post(
            "/api/contacts",
            json={
                "name": "Dee",
                "company": "Globex",
                "title": "VP",
                "address": "1 Rd",
                "birthday": "1988-03-03",
                "website": "https://dee.dev",
            },
        )
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["company"], "Globex")
        self.assertEqual(d["birthday"], "1988-03-03")

    def test_fmt_includes_new_fields(self):
        self.client.post("/api/contacts", json={"name": "Ed"})
        c = self.client.get("/api/contacts").json()[0]
        for k in ("company", "title", "address", "birthday", "website"):
            self.assertIn(k, c)

    def test_patch_rich_field(self):
        cid = self.client.post("/api/contacts", json={"name": "Fay"}).json()["id"]
        self.client.patch(
            f"/api/contacts/{cid}", json={"company": "NewCo", "birthday": "1995-07-07"}
        )
        c = [x for x in self.client.get("/api/contacts").json() if x["id"] == cid][0]
        self.assertEqual(c["company"], "NewCo")
        self.assertEqual(c["birthday"], "1995-07-07")

    def test_export_endpoint_has_org(self):
        self.client.post("/api/contacts", json={"name": "Gil", "company": "OrgX"})
        v = self.client.get("/api/contacts/export").text
        self.assertIn("ORG:OrgX", v)

    def test_import_endpoint_keeps_company(self):
        text = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Hank\r\nORG:Imported Inc\r\nEND:VCARD\r\n"
        self.client.post("/api/contacts/import", json={"vcard": text})
        c = [x for x in self.client.get("/api/contacts").json() if x["name"] == "Hank"][0]
        self.assertEqual(c["company"], "Imported Inc")


if __name__ == "__main__":
    unittest.main()
