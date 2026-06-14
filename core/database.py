import os, uuid, json
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Text, Boolean,
    Integer, Float, DateTime, ForeignKey, event, text
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


from sqlalchemy.types import TypeDecorator

class EncryptedText(TypeDecorator):
    """seals server-side secrets (API keys, mail passwords) at rest with the
    machine-local key in data/secret.key. legacy plaintext rows pass through
    on read and get sealed by the init_db migration."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not value:
            return value
        from services.secretstore import seal
        return seal(value)

    def process_result_value(self, value, dialect):
        if not value:
            return value
        from services.secretstore import unseal
        return unseal(value)


def _uid():
    return str(uuid.uuid4())

def _now():
    return datetime.utcnow()


class ModelEndpoint(Base):
    __tablename__ = "model_endpoints"
    id           = Column(String, primary_key=True, default=_uid)
    name         = Column(String, nullable=False)
    base_url     = Column(String, nullable=False)
    api_key      = Column(EncryptedText, default="")   # AES-GCM at rest, see secretstore
    enabled       = Column(Boolean, default=True)
    cached_models = Column(Text, default="[]")   # json list of model id strings
    vision_models = Column(Text, default="[]")   # json list of vision-capable model ids
    created_at    = Column(DateTime, default=_now)

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
    persona_id     = Column(String, ForeignKey("personas.id", ondelete="SET NULL"), nullable=True)
    project_id     = Column(String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    working_dir    = Column(Text, default="")
    starred        = Column(Boolean, default=False)
    archived       = Column(Boolean, default=False)
    incognito      = Column(Boolean, default=False)
    share_token    = Column(String, nullable=True)
    message_count  = Column(Integer, default=0)
    created_at     = Column(DateTime, default=_now)
    last_message_at = Column(DateTime, default=_now)

    messages = relationship("Message", back_populates="session",
                            cascade="all, delete-orphan",
                            order_by="Message.timestamp")
    endpoint = relationship("ModelEndpoint", foreign_keys=[endpoint_id])
    persona  = relationship("Persona", foreign_keys=[persona_id])
    project  = relationship("Project", back_populates="sessions", foreign_keys=[project_id])


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


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    id          = Column(String, primary_key=True, default=_uid)
    title       = Column(String, nullable=False)
    description = Column(Text, default="")
    start_dt    = Column(String, nullable=False)  # ISO8601
    end_dt      = Column(String, nullable=True)
    all_day     = Column(Boolean, default=False)
    color       = Column(String, default="")      # accent | green | warn | etc.
    recurrence  = Column(String, default="")       # '' | daily | weekly | monthly
    recur_until = Column(String, nullable=True)     # ISO date, optional series end
    caldav_uid  = Column(String, nullable=True)     # set when synced from/to CalDAV
    created_at  = Column(DateTime, default=_now)


class GalleryImage(Base):
    __tablename__ = "gallery_images"
    id         = Column(String, primary_key=True, default=_uid)
    filename   = Column(String, nullable=False)
    prompt     = Column(Text, default="")
    tags       = Column(Text, default="")
    source     = Column(String, default="upload")  # upload | generated
    created_at = Column(DateTime, default=_now)


class CookbookEntry(Base):
    __tablename__ = "cookbook"
    id          = Column(String, primary_key=True, default=_uid)
    name        = Column(String, nullable=False)   # slash command name (no spaces)
    description = Column(String, default="")
    prompt      = Column(Text, nullable=False)
    created_at  = Column(DateTime, default=_now)


class Persona(Base):
    __tablename__ = "personas"
    id           = Column(String, primary_key=True, default=_uid)
    name         = Column(String, nullable=False)
    emoji        = Column(String, default="")
    system_prompt = Column(Text, default="")
    model        = Column(String, default="")       # override model, or "" = use session default
    is_default   = Column(Boolean, default=False)
    created_at   = Column(DateTime, default=_now)


class Webhook(Base):
    __tablename__ = "webhooks"
    id         = Column(String, primary_key=True, default=_uid)
    name       = Column(String, nullable=False)
    url        = Column(String, nullable=False)
    events     = Column(Text, default="[]")  # json list: message, research_done, session_created
    enabled    = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)

    def events_list(self):
        try: return json.loads(self.events or "[]")
        except: return []


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id          = Column(String, primary_key=True, default=_uid)
    name        = Column(String, nullable=False)
    token_hash  = Column(String, nullable=False)   # bcrypt or sha256
    prefix      = Column(String, nullable=False)   # first 8 chars for display
    created_at  = Column(DateTime, default=_now)
    last_used_at = Column(DateTime, nullable=True)


class Memory(Base):
    __tablename__ = "memories"
    id         = Column(String, primary_key=True, default=_uid)
    text       = Column(Text, nullable=False)
    category   = Column(String, default="general")  # identity | preference | fact | task | general
    source     = Column(String, default="manual")   # manual | extracted | imported
    session_id = Column(String, nullable=True)       # which session it came from
    pinned     = Column(Boolean, default=False)      # always inject if pinned
    timestamp  = Column(DateTime, default=_now)


class Project(Base):
    __tablename__ = "projects"
    id            = Column(String, primary_key=True, default=_uid)
    name          = Column(String, nullable=False)
    description   = Column(Text, default="")
    system_prompt = Column(Text, default="")
    working_dir   = Column(Text, default="")
    color         = Column(String, default="")
    created_at    = Column(DateTime, default=_now)

    sessions = relationship("Session", back_populates="project", foreign_keys="Session.project_id")


class Upload(Base):
    __tablename__ = "uploads"
    id            = Column(String, primary_key=True, default=_uid)
    filename      = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    mime_type     = Column(String, default="")
    size          = Column(Integer, default=0)
    session_id    = Column(String, nullable=True)
    created_at    = Column(DateTime, default=_now)


class Document(Base):
    __tablename__ = "documents"
    id         = Column(String, primary_key=True, default=_uid)
    title      = Column(String, default="untitled")
    content    = Column(Text, default="")
    doc_type   = Column(String, default="md")   # md | txt | html | csv
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now)


class VaultEntry(Base):
    __tablename__ = "vault_entries"
    id              = Column(String, primary_key=True, default=_uid)
    name            = Column(String, nullable=False)
    username        = Column(String, default="")   # for password entries
    value_encrypted = Column(Text, default="")   # base64 ciphertext+nonce
    category        = Column(String, default="general")
    created_at      = Column(DateTime, default=_now)


class Contact(Base):
    __tablename__ = "contacts"
    id         = Column(String, primary_key=True, default=_uid)
    name       = Column(String, nullable=False)
    email      = Column(String, default="")
    phone      = Column(String, default="")
    notes      = Column(Text, default="")
    tags       = Column(Text, default="[]")   # json list
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now)


class MailAccount(Base):
    __tablename__ = "mail_accounts"
    id         = Column(String, primary_key=True, default=_uid)
    name       = Column(String, default="")          # display label
    email      = Column(String, default="")
    imap_host  = Column(String, default="")
    imap_port  = Column(Integer, default=993)
    smtp_host  = Column(String, default="")
    smtp_port  = Column(Integer, default=587)
    username   = Column(String, default="")
    password   = Column(EncryptedText, default="")     # AES-GCM at rest, see secretstore
    use_ssl    = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)


class Album(Base):
    __tablename__ = "albums"
    id         = Column(String, primary_key=True, default=_uid)
    name       = Column(String, nullable=False)
    cover_id   = Column(String, nullable=True)   # a Photo.id
    created_at = Column(DateTime, default=_now)


class Photo(Base):
    __tablename__ = "photos"
    id            = Column(String, primary_key=True, default=_uid)
    filename      = Column(String, nullable=False)   # stored original: uid.ext
    thumb         = Column(String, default="")        # uid.jpg in .thumbs
    original_name = Column(String, default="")
    album_id      = Column(String, ForeignKey("albums.id", ondelete="SET NULL"), nullable=True)
    width         = Column(Integer, default=0)
    height        = Column(Integer, default=0)
    taken_at      = Column(DateTime, nullable=True)   # EXIF DateTimeOriginal, else file mtime
    exif          = Column(Text, default="{}")
    favorite      = Column(Boolean, default=False)
    created_at    = Column(DateTime, default=_now)    # import time


class Reminder(Base):
    __tablename__ = "reminders"
    id         = Column(String, primary_key=True, default=_uid)
    text       = Column(Text, nullable=False)
    trigger_at = Column(DateTime, nullable=False)
    type       = Column(String, default="reminder")   # reminder | message
    session_id = Column(String, nullable=True)         # for type=message
    fired      = Column(Boolean, default=False)
    notified   = Column(Boolean, default=False)        # web push already sent
    created_at = Column(DateTime, default=_now)


class AutomationRule(Base):
    __tablename__ = "automation_rules"
    id          = Column(String, primary_key=True, default=_uid)
    name        = Column(String, default="")
    trigger     = Column(String, nullable=False)   # mail_from | sub_renewing | day_event_near | daily_at | doc_tag
    trigger_arg = Column(String, default="")        # sender substr | days | days | HH:MM | tag
    action      = Column(String, nullable=False)   # create_task | push | create_note | push_digest
    action_arg  = Column(Text, default="")          # template ({from} {subject} {name} {date} {path} {tag})
    enabled     = Column(Boolean, default=True)
    state       = Column(Text, default="{}")        # engine state: dedupe keys, last mail uids, last daily run
    created_at  = Column(DateTime, default=_now)


class DayEvent(Base):
    __tablename__ = "day_events"
    id          = Column(String, primary_key=True, default=_uid)
    name        = Column(String, nullable=False)
    date        = Column(String, nullable=False)      # ISO date YYYY-MM-DD
    repeat      = Column(String, default="none")      # none | yearly | monthly
    category    = Column(String, default="")
    notes       = Column(Text, default="")
    pinned      = Column(Boolean, default=False)
    notify_days = Column(Integer, default=1)           # push window; -1 = off, 0 = day-of only
    last_notified = Column(String, default="")         # occurrence date already pushed
    created_at  = Column(DateTime, default=_now)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id          = Column(String, primary_key=True, default=_uid)
    name        = Column(String, nullable=False)
    price       = Column(Float, default=0.0)
    currency    = Column(String, default="$")
    cycle       = Column(String, default="monthly")   # weekly | monthly | quarterly | yearly | custom
    cycle_days  = Column(Integer, default=30)          # only used for cycle=custom
    next_due    = Column(String, nullable=False)       # ISO date YYYY-MM-DD
    category    = Column(String, default="")
    url         = Column(String, default="")
    notes       = Column(Text, default="")
    active      = Column(Boolean, default=True)
    remind_days = Column(Integer, default=1)           # push N days before renewal (0 = off)
    last_notified_due = Column(String, default="")     # due date we already pushed for
    created_at  = Column(DateTime, default=_now)


class Account(Base):
    __tablename__ = "money_accounts"
    id         = Column(String, primary_key=True, default=_uid)
    name       = Column(String, nullable=False)
    kind       = Column(String, default="checking")   # checking | savings | cash | credit | investment
    currency   = Column(String, default="$")
    opening    = Column(Float, default=0.0)            # starting balance; live balance = opening + txns
    color      = Column(String, default="accent")
    archived   = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)


class Transaction(Base):
    __tablename__ = "money_transactions"
    id         = Column(String, primary_key=True, default=_uid)
    account_id = Column(String, ForeignKey("money_accounts.id", ondelete="CASCADE"))
    date       = Column(String, nullable=False)        # ISO date YYYY-MM-DD
    amount     = Column(Float, default=0.0)            # positive = income, negative = expense
    category   = Column(String, default="")
    payee      = Column(String, default="")
    notes      = Column(Text, default="")
    created_at = Column(DateTime, default=_now)


class Budget(Base):
    __tablename__ = "money_budgets"
    id         = Column(String, primary_key=True, default=_uid)
    category   = Column(String, nullable=False)
    limit_amt  = Column(Float, default=0.0)            # monthly spending cap for this category
    created_at = Column(DateTime, default=_now)


class DocRevision(Base):
    __tablename__ = "doc_revisions"
    id         = Column(String, primary_key=True, default=_uid)
    path       = Column(String, nullable=False, index=True)   # vault-relative, normalized
    content    = Column(Text, default="")
    created_at = Column(DateTime, default=_now)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id         = Column(String, primary_key=True, default=_uid)
    endpoint   = Column(Text, unique=True, nullable=False)   # browser push URL
    p256dh     = Column(String, default="")                  # client public key
    auth       = Column(String, default="")                  # client auth secret
    created_at = Column(DateTime, default=_now)


class SessionTemplate(Base):
    __tablename__ = "session_templates"
    id              = Column(String, primary_key=True, default=_uid)
    name            = Column(String, nullable=False)
    system_prompt   = Column(Text, default="")
    initial_message = Column(Text, default="")
    created_at      = Column(DateTime, default=_now)


class Connection(Base):
    __tablename__ = "connections"
    id         = Column(String, primary_key=True, default=_uid)
    service    = Column(String, nullable=False)   # github | gitlab | slack | ...
    token      = Column(Text, default="")         # access token / PAT
    meta       = Column(Text, default="{}")       # json: base_url, username, scopes...
    created_at = Column(DateTime, default=_now)


def _add_col(conn, table, col, col_type):
    try:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
        conn.commit()
    except Exception:
        pass


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(engine)
    # migrations — safe to run multiple times (all idempotent)
    with engine.connect() as conn:
        _add_col(conn, "sessions", "persona_id",   "TEXT")
        _add_col(conn, "sessions", "project_id",   "TEXT")
        _add_col(conn, "sessions", "working_dir",  "TEXT DEFAULT ''")
        _add_col(conn, "sessions", "incognito",    "BOOLEAN DEFAULT 0")
        _add_col(conn, "sessions", "mode",         "TEXT DEFAULT 'chat'")
        _add_col(conn, "sessions", "starred",      "BOOLEAN DEFAULT 0")
        _add_col(conn, "sessions", "archived",     "BOOLEAN DEFAULT 0")
        _add_col(conn, "sessions", "share_token",  "TEXT")
        _add_col(conn, "model_endpoints", "vision_models", "TEXT DEFAULT '[]'")
        _add_col(conn, "projects", "working_dir", "TEXT DEFAULT ''")
        _add_col(conn, "vault_entries", "username", "TEXT DEFAULT ''")
        _add_col(conn, "calendar_events", "recurrence",  "TEXT DEFAULT ''")
        _add_col(conn, "calendar_events", "recur_until", "TEXT")
        _add_col(conn, "calendar_events", "caldav_uid",  "TEXT")
        _add_col(conn, "reminders", "notified", "BOOLEAN DEFAULT 0")
    _encrypt_plaintext_secrets()


def _encrypt_plaintext_secrets():
    """one-time (idempotent) — seal credentials that predate at-rest encryption"""
    from services.secretstore import seal, PREFIX
    with engine.begin() as conn:
        for table, col in (("model_endpoints", "api_key"), ("mail_accounts", "password")):
            rows = conn.execute(text(
                f"SELECT id, {col} FROM {table} WHERE {col} != '' AND {col} NOT LIKE :p"
            ), {"p": PREFIX + "%"}).fetchall()
            for rid, val in rows:
                conn.execute(text(f"UPDATE {table} SET {col} = :v WHERE id = :id"),
                             {"v": seal(val), "id": rid})


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
