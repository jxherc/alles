import os
import tempfile
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from core.settings import load_settings, save_settings


def test_pidx_settings_defaults_and_patch():
    with (
        tempfile.TemporaryDirectory() as tmp,
        mock.patch.dict(
            os.environ,
            {"ALLES_DATA": tmp, "ALLES_DB": os.path.join(tmp, "test.db")},
        ),
    ):
        settings = load_settings()
        for key in (
            "pidx_enabled",
            "pidx_mail",
            "pidx_note",
            "pidx_journal",
            "pidx_contact",
            "pidx_read",
            "pidx_book",
        ):
            assert settings.get(key) is True
        save_settings({"pidx_mail": False})
        assert load_settings().get("pidx_mail") is False


def test_recall_endpoints():
    # Bind to an isolated in-memory database and keep environment changes inside
    # this test. Module-level ALLES_DB used to poison every later recovery test.
    import core.database as db

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.Base.metadata.create_all(engine)
    original = db.engine
    db.engine = engine
    db.SessionLocal.configure(bind=engine)
    try:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(
                os.environ,
                {"ALLES_DATA": tmp, "ALLES_DB": os.path.join(tmp, "test.db")},
            ),
        ):
            from app import app

            with TestClient(app) as client:
                response = client.get("/api/recall/stats")
                assert response.status_code == 200
                assert "by_kind" in response.json()
                assert client.post("/api/recall/reindex", json={}).status_code == 200
                assert client.post("/api/recall/clear", json={}).status_code == 200
    finally:
        db.SessionLocal.configure(bind=original)
        db.engine = original
        engine.dispose()
