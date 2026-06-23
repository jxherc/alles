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
    # bind to an isolated in-memory db so this doesn't run against (or depend on) whatever
    # global engine a prior test left behind — other tests swap db.engine and this one used
    # the global one via TestClient, making it order-dependent
    import core.database as db
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.Base.metadata.create_all(eng)
    orig = db.engine
    db.engine = eng
    db.SessionLocal.configure(bind=eng)
    try:
        from app import app
        with TestClient(app) as c:
            r = c.get("/api/recall/stats")
            assert r.status_code == 200
            assert "by_kind" in r.json()
            r = c.post("/api/recall/reindex", json={})
            assert r.status_code == 200
            r = c.post("/api/recall/clear", json={})
            assert r.status_code == 200
    finally:
        db.SessionLocal.configure(bind=orig)
        db.engine = orig
        eng.dispose()
