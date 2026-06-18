import os
import struct
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

from services import webpush as wp


def _fake_client(status):
    class _Resp:
        status_code = status
        text = ""

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    return lambda *a, **k: _Client()


class WebPushTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(wp, "_KEY_FILE", Path(self._tmp.name) / "vapid.pem")
        self._p.start()
        wp._vapid_key = None  # regenerate against the temp file, not real data/

    def tearDown(self):
        self._p.stop()
        wp._vapid_key = None
        self._tmp.cleanup()

    def test_b64u_roundtrip_no_padding(self):
        data = os.urandom(20)
        self.assertEqual(wp._b64u_dec(wp._b64u(data)), data)
        self.assertNotIn("=", wp._b64u(data))

    def test_public_key_generated_and_stable(self):
        k1 = wp.public_key_b64u()
        self.assertTrue((Path(self._tmp.name) / "vapid.pem").exists())
        self.assertEqual(len(wp._b64u_dec(k1)), 65)  # uncompressed P-256 point
        self.assertEqual(k1, wp.public_key_b64u())  # cached → stable

    def test_vapid_auth_header_shape(self):
        h = wp._vapid_auth("https://push.example.com/abc")
        self.assertTrue(h.startswith("vapid t="))
        self.assertIn(", k=", h)

    def _sub(self):
        ua = ec.generate_private_key(ec.SECP256R1())
        pub = ua.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return {
            "endpoint": "https://push.example/x",
            "p256dh": wp._b64u(pub),
            "auth": wp._b64u(os.urandom(16)),
        }

    def test_encrypt_structure(self):
        body = wp._encrypt(b"hello", self._sub()["p256dh"], self._sub()["auth"])
        rs = struct.unpack("!I", body[16:20])[0]
        self.assertEqual(rs, 4096)  # record size header
        self.assertEqual(body[20], 65)  # ephemeral key length
        self.assertGreater(len(body), 16 + 5 + 65)

    def test_send_push_prunes_on_410(self):
        with mock.patch.object(wp.httpx, "AsyncClient", _fake_client(410)):
            self.assertFalse(asyncio.run(wp.send_push(self._sub(), {"title": "t"})))

    def test_send_push_alive_on_201(self):
        with mock.patch.object(wp.httpx, "AsyncClient", _fake_client(201)):
            self.assertTrue(asyncio.run(wp.send_push(self._sub(), {"title": "t"})))


if __name__ == "__main__":
    unittest.main()
