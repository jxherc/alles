from datetime import datetime
from types import SimpleNamespace

from core.database import Monitor, MonitorCheck
from routes.watch import cert_days_left, check_passes, record_check, uptime_pct
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
