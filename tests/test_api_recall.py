import os, tempfile
_tmp = tempfile.mkdtemp()
os.environ["ALLES_DATA"] = _tmp
os.environ["ALLES_DB"] = os.path.join(_tmp, "test.db")

from core.settings import load_settings, save_settings

def test_pidx_settings_defaults_and_patch():
    s = load_settings()
    for k in ("pidx_enabled", "pidx_mail", "pidx_note", "pidx_journal", "pidx_contact", "pidx_read", "pidx_book"):
        assert s.get(k) is True
    save_settings({"pidx_mail": False})
    assert load_settings().get("pidx_mail") is False
    save_settings({"pidx_mail": True})  # restore

# tests/test_api_recall.py (append)
from fastapi.testclient import TestClient

def test_recall_endpoints():
    from app import app
    with TestClient(app) as c:
        r = c.get("/api/recall/stats")
        assert r.status_code == 200
        assert "by_kind" in r.json()
        r = c.post("/api/recall/reindex", json={})
        assert r.status_code == 200
        r = c.post("/api/recall/clear", json={})
        assert r.status_code == 200
