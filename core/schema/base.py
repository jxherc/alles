import uuid
from datetime import UTC, datetime

from sqlalchemy import Text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class EncryptedText(TypeDecorator):
    """seals server-side secrets (API keys, mail passwords) at rest with the
    machine-local key in data/secret.key. legacy plaintext rows pass through
    on read and get sealed by the init_db migration."""

    impl = Text
    cache_ok = True

    def __init__(self, purpose: str):
        super().__init__()
        self.purpose = purpose

    def process_bind_param(self, value, dialect):
        if not value:
            return value
        from services.secretstore import seal

        return seal(value, self.purpose)

    def process_result_value(self, value, dialect):
        if not value:
            return value
        from services.secretstore import unseal

        return unseal(value, self.purpose)


def _uid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(UTC).replace(tzinfo=None)
