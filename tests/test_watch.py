from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from core.database import Monitor, MonitorCheck
from routes.watch import cert_days_left, check_passes, perform_check
from services.watch_checks import monitor_address, record_check, uptime_pct
from tests._client import ApiTest


class WatchLogicTests(ApiTest):
    # ── pure: did an http/health response pass? ──
    def test_check_passes_status_match(self):
        ok, _ = check_passes("http", 200, "", 0, 200, "", 50)
        self.assertTrue(ok)

    def test_check_passes_status_mismatch(self):
        ok, err = check_passes("http", 200, "", 0, 500, "", 50)
        self.assertFalse(ok)
        self.assertIn("500", err)

    def test_check_passes_default_status_accepts_2xx_3xx(self):
        # expect_status 0 → any 2xx/3xx is fine, 4xx/5xx fail
        self.assertTrue(check_passes("http", 0, "", 0, 204, "", 10)[0])
        self.assertTrue(check_passes("http", 0, "", 0, 301, "", 10)[0])
        self.assertFalse(check_passes("http", 0, "", 0, 404, "", 10)[0])

    def test_check_passes_keyword_present(self):
        self.assertTrue(check_passes("health", 200, "ok", 0, 200, '{"status":"ok"}', 5)[0])

    def test_check_passes_keyword_missing(self):
        ok, err = check_passes("health", 200, "ready", 0, 200, "nope", 5)
        self.assertFalse(ok)
        self.assertIn("keyword", err.lower())

    def test_check_passes_keyword_case_insensitive(self):
        self.assertTrue(check_passes("http", 200, "Welcome", 0, 200, "WELCOME home", 5)[0])

    def test_check_passes_latency_ceiling_exceeded(self):
        ok, err = check_passes("http", 200, "", 300, 200, "", 900)
        self.assertFalse(ok)
        self.assertIn("900", err)

    def test_check_passes_latency_under_ceiling(self):
        self.assertTrue(check_passes("http", 200, "", 300, 200, "", 120)[0])

    # ── pure: cert days-left ──
    def test_cert_days_left_future(self):
        now = datetime(2026, 6, 20)
        self.assertEqual(cert_days_left(datetime(2026, 7, 20), now), 30)

    def test_cert_days_left_expired_negative(self):
        now = datetime(2026, 6, 20)
        self.assertLess(cert_days_left(datetime(2026, 6, 10), now), 0)

    # ── pure: uptime percentage ──
    def test_uptime_pct_empty_is_none(self):
        self.assertIsNone(uptime_pct([]))

    def test_uptime_pct_ratio(self):
        checks = [
            SimpleNamespace(ok=True),
            SimpleNamespace(ok=True),
            SimpleNamespace(ok=False),
            SimpleNamespace(ok=True),
        ]
        self.assertEqual(uptime_pct(checks), 75.0)

    # ── storage + prune ──
    def test_record_check_stores(self):
        db = self.db()
        m = Monitor(name="x", url="http://x", kind="http")
        db.add(m)
        db.commit()
        record_check(db, m.id, ok=True, status_code=200, latency_ms=42)
        rows = db.query(MonitorCheck).filter(MonitorCheck.monitor_id == m.id).all()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].ok)
        self.assertEqual(rows[0].latency_ms, 42)

    def test_record_check_prunes_to_keep(self):
        db = self.db()
        m = Monitor(name="x", url="http://x", kind="http")
        db.add(m)
        db.commit()
        for i in range(12):
            record_check(db, m.id, ok=True, status_code=200, latency_ms=i, keep=5)
        rows = db.query(MonitorCheck).filter(MonitorCheck.monitor_id == m.id).all()
        self.assertEqual(len(rows), 5)


class WatchApiTests(ApiTest):
    def _create(self, **kw):
        body = {"name": "Site", "url": "https://example.com", "kind": "http"}
        body.update(kw)
        return self.client.post("/api/watch", json=body)

    def test_create_returns_id_and_fields(self):
        r = self._create()
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j["id"])
        self.assertEqual(j["name"], "Site")
        self.assertEqual(j["kind"], "http")

    def test_create_rejects_bad_kind(self):
        r = self._create(kind="banana")
        self.assertEqual(r.status_code, 400)

    def test_create_requires_name_and_url(self):
        self.assertEqual(
            self.client.post("/api/watch", json={"name": "", "url": "https://x"}).status_code, 400
        )
        self.assertEqual(
            self.client.post("/api/watch", json={"name": "x", "url": ""}).status_code, 400
        )

    def test_only_the_owner_or_an_admin_token_names_what_alles_fetches(self):
        import os

        def token(scopes):
            made = self.client.post("/api/tokens", json={"name": "t", "scopes": scopes}).json()
            return {"Authorization": f"Bearer {made['token']}"}

        phone = token(["read", "write", "models"])
        admin = token(["admin"])
        mid = self._create().json()["id"]
        inside = {"name": "router", "url": "http://192.168.1.1/admin", "kind": "http"}
        os.environ["AUTH_ENABLED"] = "true"
        try:
            made = self.client.post("/api/watch", headers=phone, json=inside)
            self.assertEqual(made.status_code, 401, made.text)
            moved = self.client.patch(
                f"/api/watch/{mid}", headers=phone, json={"url": inside["url"]}
            )
            self.assertEqual(moved.status_code, 401, moved.text)
            # reading, checking and deleting stay with the everyday scopes
            seen = self.client.get("/api/watch", headers=phone).json()["monitors"]
            self.assertEqual([m["url"] for m in seen], ["https://example.com"])
            allowed = self.client.post("/api/watch", headers=admin, json=inside)
            self.assertEqual(allowed.status_code, 200, allowed.text)
            renamed = self.client.patch(f"/api/watch/{mid}", headers=admin, json={"name": "site"})
            self.assertEqual(renamed.status_code, 200, renamed.text)
            self.assertEqual(
                self.client.delete(f"/api/watch/{mid}", headers=phone).status_code, 200
            )
        finally:
            os.environ["AUTH_ENABLED"] = "false"

    # a monitor is checked with httpx.get(its address): without a scheme that fails every time
    def test_an_address_typed_without_a_scheme_is_saved_as_https(self):
        for typed, kind, saved in (
            ("example.com", "http", "https://example.com"),
            ("  example.com:8443/health  ", "health", "https://example.com:8443/health"),
            ("nas:8080", "http", "https://nas:8080"),
            ("example.com", "cert", "https://example.com"),
            ("http://192.168.1.20:6769/health", "health", "http://192.168.1.20:6769/health"),
        ):
            with self.subTest(typed=typed):
                made = self._create(url=typed, kind=kind)
                self.assertEqual(made.status_code, 200, made.text)
                self.assertEqual(made.json()["url"], saved)

    def test_an_address_no_check_could_reach_is_refused(self):
        for typed in ("ftp://example.com", "not an address", "https://", "example.com:port"):
            with self.subTest(typed=typed):
                made = self._create(url=typed)
                self.assertEqual(made.status_code, 400, made.text)
                self.assertEqual(made.json()["detail"], "that doesn't look like a web address")
        self.assertEqual(self.client.get("/api/watch").json()["monitors"], [])

    def test_a_certificate_check_only_needs_a_host(self):
        # it opens a tls connection to the host and port, whatever the scheme says
        made = self._create(url="imaps://mail.example.com:993", kind="cert")
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json()["url"], "imaps://mail.example.com:993")
        # that address is no page a site check could fetch
        moved = self.client.patch(f"/api/watch/{made.json()['id']}", json={"kind": "http"})
        self.assertEqual(moved.status_code, 400, moved.text)

    def test_patch_checks_the_address_like_create(self):
        mid = self._create().json()["id"]
        moved = self.client.patch(f"/api/watch/{mid}", json={"url": "example.org/status"})
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(moved.json()["url"], "https://example.org/status")
        refused = self.client.patch(f"/api/watch/{mid}", json={"url": "ftp://example.org"})
        self.assertEqual(refused.status_code, 400, refused.text)
        kept = self.client.get("/api/watch").json()["monitors"][0]
        self.assertEqual(kept["url"], "https://example.org/status")

    def test_a_monitor_saved_without_a_scheme_is_still_checked(self):
        # rows the web app and aide saved before the address was checked
        asked = []

        def get(url, **_):
            asked.append(url)
            return SimpleNamespace(status_code=200, text="")

        with mock.patch("httpx.get", get):
            old = Monitor(name="old", url="example.com", kind="http")
            self.assertTrue(perform_check(old)["ok"])
        self.assertEqual(asked, ["https://example.com"])

    def test_monitor_address(self):
        self.assertEqual(monitor_address("HTTPS://Example.com/a?b=1"), "HTTPS://Example.com/a?b=1")
        self.assertEqual(monitor_address("[::1]:6769"), "https://[::1]:6769")
        for bad in ("", "   ", None, "https://[::1", "file:///etc/passwd", "a b.com"):
            self.assertEqual(monitor_address(bad), "", bad)

    def test_list_contains_created(self):
        self._create(name="Alpha")
        r = self.client.get("/api/watch")
        names = [m["name"] for m in r.json()["monitors"]]
        self.assertIn("Alpha", names)

    def test_patch_updates_fields(self):
        mid = self._create().json()["id"]
        r = self.client.patch(f"/api/watch/{mid}", json={"name": "Renamed", "enabled": False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "Renamed")
        self.assertFalse(r.json()["enabled"])

    def test_patch_rejects_blank_name_and_url(self):
        mid = self._create().json()["id"]
        self.assertEqual(self.client.patch(f"/api/watch/{mid}", json={"name": ""}).status_code, 400)
        self.assertEqual(
            self.client.patch(f"/api/watch/{mid}", json={"url": "  "}).status_code, 400
        )

    def test_patch_rejects_bad_kind(self):
        mid = self._create().json()["id"]
        self.assertEqual(
            self.client.patch(f"/api/watch/{mid}", json={"kind": "banana"}).status_code, 400
        )

    def test_patch_clamps_and_trims_like_create(self):
        mid = self._create().json()["id"]
        r = self.client.patch(
            f"/api/watch/{mid}",
            json={
                "name": "  Renamed  ",
                "url": "  https://example.org  ",
                "expect_keyword": "  ready  ",
                "interval_secs": 1,
                "latency_ceiling_ms": -20,
            },
        )
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(j["name"], "Renamed")
        self.assertEqual(j["url"], "https://example.org")
        self.assertEqual(j["expect_keyword"], "ready")
        self.assertEqual(j["interval_secs"], 10)
        self.assertEqual(j["latency_ceiling_ms"], 0)

    def test_patch_unknown_404(self):
        self.assertEqual(self.client.patch("/api/watch/nope", json={"name": "z"}).status_code, 404)

    def test_delete_removes(self):
        mid = self._create().json()["id"]
        self.assertEqual(self.client.delete(f"/api/watch/{mid}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/watch/{mid}").status_code, 404)

    def test_overview_shape_and_status(self):
        mid = self._create(name="Ov").json()["id"]
        db = self.db()
        record_check(db, mid, ok=True, status_code=200, latency_ms=30)
        record_check(db, mid, ok=False, status_code=500, latency_ms=20)
        r = self.client.get("/api/watch/overview")
        self.assertEqual(r.status_code, 200)
        mon = next(m for m in r.json()["monitors"] if m["id"] == mid)
        self.assertEqual(mon["status"], "down")  # latest check failed
        self.assertIn("uptime_24h", mon)
        self.assertEqual(mon["uptime_24h"], 50.0)
        self.assertIsInstance(mon["spark"], list)

    def test_overview_unknown_status_without_checks(self):
        mid = self._create(name="Fresh").json()["id"]
        mon = next(
            m for m in self.client.get("/api/watch/overview").json()["monitors"] if m["id"] == mid
        )
        self.assertEqual(mon["status"], "unknown")

    def test_history_newest_first(self):
        mid = self._create().json()["id"]
        db = self.db()
        record_check(db, mid, ok=True, status_code=200, latency_ms=10)
        record_check(db, mid, ok=False, status_code=503, latency_ms=11)
        rows = self.client.get(f"/api/watch/{mid}/history").json()["checks"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status_code"], 503)  # newest first

    def test_manual_check_records_failure_for_dead_target(self):
        # 127.0.0.1:1 → connection refused fast, deterministic, no external network
        mid = self._create(name="Dead", url="http://127.0.0.1:1").json()["id"]
        r = self.client.post(f"/api/watch/{mid}/check")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        hist = self.client.get(f"/api/watch/{mid}/history").json()["checks"]
        self.assertGreaterEqual(len(hist), 1)
        self.assertFalse(hist[0]["ok"])
