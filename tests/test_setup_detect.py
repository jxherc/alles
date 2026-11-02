import asyncio
import unittest
from unittest import mock

import httpx

from services import setup_detect

AUTOCONFIG = """<?xml version="1.0"?>
<clientConfig version="1.1"><emailProvider id="example.org">
  <incomingServer type="pop3"><hostname>pop.example.org</hostname><port>995</port></incomingServer>
  <incomingServer type="imap"><hostname>mail.example.org</hostname><port>993</port></incomingServer>
  <outgoingServer type="smtp"><hostname>smtp.example.org</hostname><port>465</port></outgoingServer>
</emailProvider></clientConfig>"""


def _client(routes):
    def handler(request):
        for (host, path), response in routes.items():
            if request.url.host == host and request.url.path == path:
                return response
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _detect(email, routes, public=True):
    async def run():
        async with _client(routes) as client:
            with mock.patch.object(setup_detect, "_public_host", return_value=public):
                return await setup_detect.detect(email, client=client)

    return asyncio.run(run())


class SetupDetectTests(unittest.TestCase):
    def test_known_providers_need_no_lookup(self):
        found = _detect("Me@iCloud.com", {})
        self.assertEqual(found["provider"], "icloud")
        self.assertEqual(found["mail"]["imap_host"], "imap.mail.me.com")
        self.assertEqual(found["caldav"]["url"], "https://caldav.icloud.com/")
        gmail = _detect("x@gmail.com", {})
        self.assertEqual((gmail["signin"], gmail["caldav"]), ("google", None))
        self.assertEqual(_detect("x@hotmail.com", {})["signin"], "microsoft")

    def test_own_domain_reads_the_isp_database(self):
        found = _detect(
            "a@example.org",
            {
                ("autoconfig.thunderbird.net", "/v1.1/example.org"): httpx.Response(
                    200, text=AUTOCONFIG
                ),
                ("example.org", "/.well-known/caldav"): httpx.Response(
                    301, headers={"location": "https://example.org/remote.php/dav"}
                ),
            },
        )
        self.assertEqual(found["mail"]["imap_host"], "mail.example.org")
        self.assertEqual(found["mail"]["smtp_port"], 465)
        self.assertEqual(found["mail"]["source"], "autoconfig")
        self.assertEqual(found["caldav"]["url"], "https://example.org/.well-known/caldav")

    def test_a_site_that_redirects_everything_is_not_caldav(self):
        found = _detect(
            "a@example.org",
            {
                ("example.org", "/.well-known/caldav"): httpx.Response(
                    301, headers={"location": "https://www.example.org/"}
                )
            },
        )
        self.assertIsNone(found["caldav"])
        self.assertEqual(found["mail"]["source"], "guess")
        self.assertEqual(found["mail"]["imap_host"], "imap.example.org")

    def test_private_hosts_are_never_fetched(self):
        routes = {
            ("autoconfig.thunderbird.net", "/v1.1/example.org"): httpx.Response(
                200, text=AUTOCONFIG
            )
        }
        found = _detect("a@example.org", routes, public=False)
        self.assertEqual(found["mail"]["source"], "guess")

    def test_bad_addresses_answer_nothing(self):
        for email in ("", "nobody", "a@localhost", "a@10.0.0.1", "a@b"):
            self.assertEqual(_detect(email, {})["mail"], None, email)

    def test_autoconfig_with_placeholders_is_ignored(self):
        text = AUTOCONFIG.replace("mail.example.org", "%EMAILDOMAIN%")
        self.assertIsNone(setup_detect.parse_autoconfig(text))
        self.assertIsNone(setup_detect.parse_autoconfig("not xml"))


if __name__ == "__main__":
    unittest.main()
