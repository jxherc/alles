"""
Stored credentials for external services the agent can talk to (github, etc).
Token comes from the DB Connection row, or falls back to env (GITHUB_TOKEN / *_API_KEY).
"""
import os

from core.database import SessionLocal, Connection


def get_connection(service: str):
    db = SessionLocal()
    try:
        return db.query(Connection).filter(Connection.service == service.lower()).first()
    finally:
        db.close()


def get_token(service: str) -> str:
    c = get_connection(service)
    if c and c.token:
        return c.token
    svc = service.upper()
    return os.getenv(f"{svc}_TOKEN", "") or os.getenv(f"{svc}_API_KEY", "")


def list_connections():
    db = SessionLocal()
    try:
        return db.query(Connection).order_by(Connection.service).all()
    finally:
        db.close()
