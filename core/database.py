import os, uuid, json
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Text, Boolean,
    Integer, DateTime, ForeignKey, event
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker, relationship

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "aide.db")
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

# wal mode so reads don't block writes
@event.listens_for(engine, "connect")
def _set_wal(conn, _):
    conn.execute("pragma journal_mode=wal")
    conn.execute("pragma foreign_keys=on")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass


def _uid():
    return str(uuid.uuid4())

def _now():
    return datetime.utcnow()


class ModelEndpoint(Base):
    __tablename__ = "model_endpoints"
    id           = Column(String, primary_key=True, default=_uid)
    name         = Column(String, nullable=False)
    base_url     = Column(String, nullable=False)
    api_key      = Column(Text, default="")      # stored plain for now, encrypt later
    enabled      = Column(Boolean, default=True)
    cached_models = Column(Text, default="[]")   # json list of model id strings
    created_at   = Column(DateTime, default=_now)

    def models_list(self):
        try:
            return json.loads(self.cached_models or "[]")
        except Exception:
            return []


class Session(Base):
    __tablename__ = "sessions"
    id             = Column(String, primary_key=True, default=_uid)
    name           = Column(String, default="new chat")
    model          = Column(String, default="")
    endpoint_id    = Column(String, ForeignKey("model_endpoints.id", ondelete="SET NULL"), nullable=True)
    mode           = Column(String, default="chat")   # chat | agent
    starred        = Column(Boolean, default=False)
    archived       = Column(Boolean, default=False)
    message_count  = Column(Integer, default=0)
    created_at     = Column(DateTime, default=_now)
    last_message_at = Column(DateTime, default=_now)

    messages = relationship("Message", back_populates="session",
                            cascade="all, delete-orphan",
                            order_by="Message.timestamp")
    endpoint = relationship("ModelEndpoint", foreign_keys=[endpoint_id])


class Message(Base):
    __tablename__ = "messages"
    id         = Column(String, primary_key=True, default=_uid)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role       = Column(String, nullable=False)   # user | assistant | system
    content    = Column(Text, default="")
    meta       = Column(Text, default="{}")       # json — usage, thinking, etc.
    timestamp  = Column(DateTime, default=_now)

    session = relationship("Session", back_populates="messages")

    def meta_dict(self):
        try:
            return json.loads(self.meta or "{}")
        except Exception:
            return {}


class McpServer(Base):
    __tablename__ = "mcp_servers"
    id        = Column(String, primary_key=True, default=_uid)
    name      = Column(String, nullable=False)
    transport = Column(String, default="stdio")  # stdio | sse
    command   = Column(String, default="")
    args      = Column(Text, default="[]")        # json list
    url       = Column(String, default="")
    enabled   = Column(Boolean, default=True)
    disabled_tools = Column(Text, default="[]")   # json list of disabled tool names
    created_at = Column(DateTime, default=_now)

    def args_list(self):
        try: return json.loads(self.args or "[]")
        except: return []

    def disabled_tools_list(self):
        try: return json.loads(self.disabled_tools or "[]")
        except: return []


class Note(Base):
    __tablename__ = "notes"
    id         = Column(String, primary_key=True, default=_uid)
    title      = Column(String, default="")
    content    = Column(Text, default="")
    pinned     = Column(Boolean, default=False)
    archived   = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now)


class Task(Base):
    __tablename__ = "tasks"
    id        = Column(String, primary_key=True, default=_uid)
    title     = Column(String, nullable=False)
    done      = Column(Boolean, default=False)
    priority  = Column(Integer, default=0)   # 0 normal, 1 high
    due_date  = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now)


class Memory(Base):
    __tablename__ = "memories"
    id         = Column(String, primary_key=True, default=_uid)
    text       = Column(Text, nullable=False)
    category   = Column(String, default="general")  # identity | preference | fact | task | general
    source     = Column(String, default="manual")   # manual | extracted | imported
    session_id = Column(String, nullable=True)       # which session it came from
    pinned     = Column(Boolean, default=False)      # always inject if pinned
    timestamp  = Column(DateTime, default=_now)


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
