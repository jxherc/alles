import json
import os
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker
from sqlalchemy.types import TypeDecorator

# default db lives in <data>/aide.db; ALLES_DB (or ALLES_DATA via settings.data_dir) isolates it
from core.settings import data_dir as _data_dir

DB_PATH = os.environ.get("ALLES_DB") or str(_data_dir() / "aide.db")
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


# wal mode so reads don't block writes
@event.listens_for(engine, "connect")
def _set_wal(conn, _):
    conn.execute("pragma journal_mode=wal")
    conn.execute("pragma foreign_keys=on")


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


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
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    base_url = Column(String, nullable=False)
    api_key = Column(EncryptedText, default="")  # AES-GCM at rest, see secretstore
    enabled = Column(Boolean, default=True)
    cached_models = Column(Text, default="[]")  # json list of model id strings (chat)
    vision_models = Column(Text, default="[]")  # json list of vision-capable model ids
    image_models = Column(Text, default="[]")  # json list of image-generation model ids
    created_at = Column(DateTime, default=_now)

    def models_list(self):
        try:
            return json.loads(self.cached_models or "[]")
        except Exception:
            return []

    def image_models_list(self):
        try:
            return json.loads(self.image_models or "[]")
        except Exception:
            return []


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, default="new chat")
    model = Column(String, default="")
    endpoint_id = Column(
        String, ForeignKey("model_endpoints.id", ondelete="SET NULL"), nullable=True
    )
    mode = Column(String, default="chat")  # chat | agent
    persona_id = Column(String, ForeignKey("personas.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    working_dir = Column(Text, default="")
    starred = Column(Boolean, default=False)
    archived = Column(Boolean, default=False)
    incognito = Column(Boolean, default=False)
    share_token = Column(String, nullable=True)
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)
    last_message_at = Column(DateTime, default=_now)

    messages = relationship(
        "Message",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Message.timestamp",
    )
    endpoint = relationship("ModelEndpoint", foreign_keys=[endpoint_id])
    persona = relationship("Persona", foreign_keys=[persona_id])
    project = relationship("Project", back_populates="sessions", foreign_keys=[project_id])


class Message(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True, default=_uid)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # user | assistant | system
    content = Column(Text, default="")
    meta = Column(Text, default="{}")  # json — usage, thinking, etc.
    timestamp = Column(DateTime, default=_now)

    session = relationship("Session", back_populates="messages")

    def meta_dict(self):
        try:
            return json.loads(self.meta or "{}")
        except Exception:
            return {}


class McpServer(Base):
    __tablename__ = "mcp_servers"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    transport = Column(String, default="stdio")  # stdio | sse
    command = Column(String, default="")
    args = Column(Text, default="[]")  # json list
    url = Column(String, default="")
    enabled = Column(Boolean, default=True)
    disabled_tools = Column(Text, default="[]")  # json list of disabled tool names
    created_at = Column(DateTime, default=_now)

    def args_list(self):
        try:
            return json.loads(self.args or "[]")
        except Exception:
            return []

    def disabled_tools_list(self):
        try:
            return json.loads(self.disabled_tools or "[]")
        except Exception:
            return []


class Note(Base):
    __tablename__ = "notes"
    id = Column(String, primary_key=True, default=_uid)
    title = Column(String, default="")
    content = Column(Text, default="")
    pinned = Column(Boolean, default=False)
    archived = Column(Boolean, default=False)
    tags = Column(String, default="")  # comma-separated
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now)


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    id = Column(String, primary_key=True, default=_uid)
    date = Column(String, unique=True, index=True)  # one per day, ISO YYYY-MM-DD
    content = Column(Text, default="")
    mood = Column(String, default="")  # emoji / short word
    tags = Column(String, default="")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now)


class Task(Base):
    __tablename__ = "tasks"
    id = Column(String, primary_key=True, default=_uid)
    title = Column(String, nullable=False)
    done = Column(Boolean, default=False)
    priority = Column(Integer, default=0)  # 0 normal, 1 high
    due_date = Column(String, nullable=True)
    parent_id = Column(String, nullable=True)  # subtasks point at their parent
    tags = Column(String, default="")  # comma-separated
    repeat = Column(String, default="")  # ''|daily|weekly|monthly|yearly
    notes = Column(Text, default="")
    project = Column(String, default="")
    sort_order = Column(Integer, default=0)  # manual drag-reorder
    completed_at = Column(DateTime, nullable=True)  # when done flipped true (for the activity feed)
    created_at = Column(DateTime, default=_now)


class Calendar(Base):
    """a named calendar (Personal/Work/…) — events belong to one, inherit its
    colour, and can be toggled on/off as a layer."""

    __tablename__ = "calendars"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    color = Column(String, default="accent")
    visible = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    id = Column(String, primary_key=True, default=_uid)
    calendar_id = Column(String, default="")  # which Calendar it belongs to
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    location = Column(String, default="")
    guests = Column(Text, default="")  # freeform / comma list
    start_dt = Column(String, nullable=False)  # ISO8601
    end_dt = Column(String, nullable=True)
    all_day = Column(Boolean, default=False)
    color = Column(String, default="")  # override; '' = use the calendar's colour
    reminders = Column(Text, default="[]")  # json: minutes-before [10, 60, ...]
    recurrence = Column(String, default="")  # '' | daily | weekly | monthly | yearly
    recur_interval = Column(Integer, default=1)  # every N (days/weeks/…)
    recur_byday = Column(String, default="")  # weekly: 'MO,WE,FR'
    recur_count = Column(Integer, nullable=True)  # end after N occurrences
    recur_until = Column(String, nullable=True)  # ISO date, optional series end
    recur_except = Column(Text, default="[]")  # json: excluded occurrence dates
    caldav_uid = Column(String, nullable=True)  # set when synced from/to CalDAV
    subscription_id = Column(String, nullable=True)  # 8a: set when pulled from an ICS-URL feed
    meeting_url = Column(String, default="")  # 8b: video-meeting link (paste or generated)
    created_at = Column(DateTime, default=_now)


class EventAttendee(Base):
    """8b — a structured invitee on an event, with a per-person RSVP token."""

    __tablename__ = "event_attendees"
    id = Column(String, primary_key=True, default=_uid)
    event_id = Column(String, nullable=False)
    name = Column(String, default="")
    email = Column(String, default="")
    status = Column(String, default="invited")  # invited | accepted | declined | tentative
    token = Column(String, default=_uid)  # public RSVP token
    created_at = Column(DateTime, default=_now)


class BookingPage(Base):
    """8b — a public appointment page; guests pick a free slot which becomes an event."""

    __tablename__ = "booking_pages"
    id = Column(String, primary_key=True, default=_uid)
    token = Column(String, default=_uid)
    title = Column(String, default="Book a time")
    duration_min = Column(Integer, default=30)
    work_start = Column(Integer, default=9)
    work_end = Column(Integer, default=17)
    days_ahead = Column(Integer, default=14)
    calendar_id = Column(String, default="")
    created_at = Column(DateTime, default=_now)


class CalendarSubscription(Base):
    """8a — a read-only external calendar fed by an ICS URL (Google/Apple public feed,
    holidays, sports). refreshed on a timer; its events are full-replaced each sync."""

    __tablename__ = "calendar_subscriptions"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    calendar_id = Column(String, default="")  # the Calendar layer its events land in
    last_synced = Column(String, default="")  # ISO time of last successful/attempted sync
    last_status = Column(String, default="")  # 'ok' | 'error: ...'
    created_at = Column(DateTime, default=_now)


class GalleryImage(Base):
    __tablename__ = "gallery_images"
    id = Column(String, primary_key=True, default=_uid)
    filename = Column(String, nullable=False)
    prompt = Column(Text, default="")
    tags = Column(Text, default="")
    source = Column(String, default="upload")  # upload | generated
    created_at = Column(DateTime, default=_now)


class CookbookEntry(Base):
    __tablename__ = "cookbook"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)  # slash command name (no spaces)
    description = Column(String, default="")
    prompt = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now)


class Persona(Base):
    __tablename__ = "personas"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    emoji = Column(String, default="")
    system_prompt = Column(Text, default="")
    model = Column(String, default="")  # override model, or "" = use session default
    temperature = Column(Float, nullable=True)  # pinned sampling temp, or null = provider default
    default_mode = Column(String, default="")  # "" auto | "chat" pure-chat | "agent" always tools
    accent = Column(
        String, default=""
    )  # hex accent that re-themes the app when active, "" = use global
    initial_message = Column(
        Text, default=""
    )  # prefilled into the composer when picked (merged from templates)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)


class PersonaDoc(Base):
    """10d — a knowledge file attached to a persona. The text lives in the 1c index under
    kind=persona:<id>; this row keeps the title for listing."""

    __tablename__ = "persona_docs"
    id = Column(String, primary_key=True, default=_uid)
    persona_id = Column(String, nullable=False, index=True)
    title = Column(String, default="untitled")
    created_at = Column(DateTime, default=_now)


class Webhook(Base):
    __tablename__ = "webhooks"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    events = Column(Text, default="[]")  # json list: message, research_done, session_created
    enabled = Column(Boolean, default=True)
    secret = Column(String, default="")  # HMAC-SHA256 signing key for X-Alles-Signature
    last_status = Column(String, default="")  # "ok" | "NNN" http code | "error"
    last_error = Column(String, default="")
    last_triggered = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)

    def events_list(self):
        try:
            return json.loads(self.events or "[]")
        except Exception:
            return []


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    token_hash = Column(String, nullable=False)  # bcrypt or sha256
    prefix = Column(String, nullable=False)  # first 8 chars for display
    created_at = Column(DateTime, default=_now)
    last_used_at = Column(DateTime, nullable=True)


class Memory(Base):
    __tablename__ = "memories"
    id = Column(String, primary_key=True, default=_uid)
    text = Column(Text, nullable=False)
    category = Column(String, default="general")  # identity | preference | fact | task | general
    source = Column(String, default="manual")  # manual | extracted | imported
    session_id = Column(String, nullable=True)  # which session it came from
    pinned = Column(Boolean, default=False)  # always inject if pinned
    timestamp = Column(DateTime, default=_now)


class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    system_prompt = Column(Text, default="")
    working_dir = Column(Text, default="")
    color = Column(String, default="")
    created_at = Column(DateTime, default=_now)

    sessions = relationship("Session", back_populates="project", foreign_keys="Session.project_id")


class Upload(Base):
    __tablename__ = "uploads"
    id = Column(String, primary_key=True, default=_uid)
    filename = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    mime_type = Column(String, default="")
    size = Column(Integer, default=0)
    session_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now)


class Vault(Base):
    """9c — a separate vault with its own master password. The 'default' vault absorbs
    legacy single-vault entries + the old settings verifier."""

    __tablename__ = "vaults"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False, default="Personal")
    verifier = Column(String, default="")  # salt+derived-key blob (no plaintext)
    travel_safe = Column(Boolean, default=False)  # reachable while Travel Mode is on
    biometric_blob = Column(Text, default="")  # 9c-2: master pw wrapped for biometric release
    created_at = Column(DateTime, default=_now)


class VaultEntry(Base):
    __tablename__ = "vault_entries"
    id = Column(String, primary_key=True, default=_uid)
    vault_id = Column(String, default="default")  # 9c — which vault this entry belongs to
    name = Column(String, nullable=False)
    username = Column(String, default="")  # for password entries
    value_encrypted = Column(Text, default="")  # base64 ciphertext+nonce (JSON of fields)
    category = Column(String, default="general")
    type = Column(String, default="password")  # password | card | note
    created_at = Column(DateTime, default=_now)


class VaultAttachment(Base):
    """9b — an encrypted file attached to a vault entry (blob on disk, AES-GCM)."""

    __tablename__ = "vault_attachments"
    id = Column(String, primary_key=True, default=_uid)
    entry_id = Column(String, nullable=False)
    filename = Column(String, default="")
    size = Column(Integer, default=0)  # plaintext size
    created_at = Column(DateTime, default=_now)


class VaultShare(Base):
    """9b — a per-item share: only the envelope ciphertext lives here; the key is in the URL."""

    __tablename__ = "vault_shares"
    id = Column(String, primary_key=True, default=_uid)
    token = Column(String, default=_uid)
    entry_id = Column(String, nullable=False)
    blob = Column(Text, default="")  # base64 nonce+ct (random-key envelope)
    created_at = Column(DateTime, default=_now)


class WebAuthnCredential(Base):
    """9c — a registered platform authenticator that can release a vault's unlock token."""

    __tablename__ = "webauthn_credentials"
    id = Column(String, primary_key=True, default=_uid)
    vault_id = Column(String, default="default")
    label = Column(String, default="")
    credential_id = Column(String, default="")  # b64
    public_key = Column(Text, default="")  # b64 SPKI DER (ES256)
    sign_count = Column(Integer, default=0)
    role = Column(String, default="")  # "" = biometric/primary, "2fa" = hardware second factor (9d)
    created_at = Column(DateTime, default=_now)


class Contact(Base):
    __tablename__ = "contacts"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    email = Column(String, default="")
    phone = Column(String, default="")
    notes = Column(Text, default="")
    tags = Column(Text, default="[]")  # json list
    company = Column(String, default="")
    title = Column(String, default="")  # job title
    address = Column(Text, default="")
    birthday = Column(String, default="")  # ISO date or MM-DD
    website = Column(String, default="")
    favorite = Column(Boolean, default=False)
    avatar = Column(String, default="")  # 8c: stored avatar filename
    is_me = Column(Boolean, default=False)  # 8c: the single "Me" card
    carddav_uid = Column(String, default="")  # 8d: vCard UID for two-way sync
    carddav_href = Column(String, default="")  # 8d: resource path on the server
    carddav_etag = Column(String, default="")  # 8d: last-seen etag
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now)


class ContactField(Base):
    """8c — a labeled multi-value field on a contact (work email, home phone, …)."""

    __tablename__ = "contact_fields"
    id = Column(String, primary_key=True, default=_uid)
    contact_id = Column(String, nullable=False)
    kind = Column(String, default="custom")  # email|phone|address|url|social|custom
    label = Column(String, default="")  # home|work|mobile|... freeform
    value = Column(Text, default="")
    sort_order = Column(Integer, default=0)


class ContactGroup(Base):
    """8c — a contact group; manual members, or smart membership by tag/company."""

    __tablename__ = "contact_groups"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    smart = Column(Boolean, default=False)
    rule_tag = Column(String, default="")
    rule_company = Column(String, default="")
    created_at = Column(DateTime, default=_now)


class ContactGroupMember(Base):
    __tablename__ = "contact_group_members"
    id = Column(String, primary_key=True, default=_uid)
    group_id = Column(String, nullable=False)
    contact_id = Column(String, nullable=False)


class MailAccount(Base):
    __tablename__ = "mail_accounts"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, default="")  # display label
    email = Column(String, default="")
    imap_host = Column(String, default="")
    imap_port = Column(Integer, default=993)
    smtp_host = Column(String, default="")
    smtp_port = Column(Integer, default=587)
    username = Column(String, default="")
    password = Column(EncryptedText, default="")  # AES-GCM at rest, see secretstore
    use_ssl = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)


class MailDraft(Base):
    __tablename__ = "mail_drafts"
    id = Column(String, primary_key=True, default=_uid)
    account_id = Column(String, default="", index=True)
    to = Column(Text, default="")
    cc = Column(Text, default="")
    bcc = Column(Text, default="")
    subject = Column(Text, default="")
    body = Column(Text, default="")
    in_reply_to = Column(String, default="")
    references = Column(Text, default="")
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class Album(Base):
    __tablename__ = "albums"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    cover_id = Column(String, nullable=True)  # a Photo.id
    created_at = Column(DateTime, default=_now)


class Photo(Base):
    __tablename__ = "photos"
    id = Column(String, primary_key=True, default=_uid)
    filename = Column(String, nullable=False)  # stored original: uid.ext
    thumb = Column(String, default="")  # uid.jpg in .thumbs
    original_name = Column(String, default="")
    album_id = Column(String, ForeignKey("albums.id", ondelete="SET NULL"), nullable=True)
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    taken_at = Column(DateTime, nullable=True)  # EXIF DateTimeOriginal, else file mtime
    exif = Column(Text, default="{}")
    favorite = Column(Boolean, default=False)
    caption = Column(Text, default="")  # 7a — free-text caption
    keywords = Column(String, default="")  # 7a — csv of normalized keywords/tags
    hidden = Column(Boolean, default=False)  # 7a — hidden/locked album (gated on vault unlock)
    is_video = Column(Boolean, default=False)  # 7c — mp4/mov/etc; played, not thumbnailed
    deleted_at = Column(DateTime, nullable=True)  # soft-delete (1d trash); None = live
    created_at = Column(DateTime, default=_now)  # import time


class Reminder(Base):
    __tablename__ = "reminders"
    id = Column(String, primary_key=True, default=_uid)
    text = Column(Text, nullable=False)
    trigger_at = Column(DateTime, nullable=False)
    type = Column(String, default="reminder")  # reminder | message
    session_id = Column(String, nullable=True)  # for type=message
    fired = Column(Boolean, default=False)
    notified = Column(Boolean, default=False)  # web push already sent
    created_at = Column(DateTime, default=_now)


class AutomationRule(Base):
    __tablename__ = "automation_rules"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, default="")
    trigger = Column(
        String, nullable=False
    )  # mail_from | sub_renewing | day_event_near | daily_at | doc_tag
    trigger_arg = Column(String, default="")  # sender substr | days | days | HH:MM | tag
    action = Column(String, nullable=False)  # create_task | push | create_note | push_digest
    action_arg = Column(Text, default="")  # template ({from} {subject} {name} {date} {path} {tag})
    enabled = Column(Boolean, default=True)
    state = Column(Text, default="{}")  # engine state: dedupe keys, last mail uids, last daily run
    created_at = Column(DateTime, default=_now)


class DayEvent(Base):
    __tablename__ = "day_events"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    date = Column(String, nullable=False)  # ISO date YYYY-MM-DD
    repeat = Column(String, default="none")  # none | yearly | monthly
    category = Column(String, default="")
    notes = Column(Text, default="")
    pinned = Column(Boolean, default=False)
    notify_days = Column(Integer, default=1)  # push window; -1 = off, 0 = day-of only
    last_notified = Column(String, default="")  # occurrence date already pushed
    created_at = Column(DateTime, default=_now)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    price = Column(Float, default=0.0)
    currency = Column(String, default="$")
    cycle = Column(String, default="monthly")  # weekly | monthly | quarterly | yearly | custom
    cycle_days = Column(Integer, default=30)  # only used for cycle=custom
    next_due = Column(String, nullable=False)  # ISO date YYYY-MM-DD
    category = Column(String, default="")
    url = Column(String, default="")
    notes = Column(Text, default="")
    active = Column(Boolean, default=True)
    remind_days = Column(Integer, default=1)  # push N days before renewal (0 = off)
    last_notified_due = Column(String, default="")  # due date we already pushed for
    account_id = Column(String, default="")  # money account to auto-post the charge to (optional)
    last_posted_due = Column(String, default="")  # due date we already posted a txn for
    trial_end = Column(String, default="")  # ISO date a free trial ends / cancel-by
    cancel_url = Column(String, default="")  # explicit "how to cancel" link / steps (4e)
    created_at = Column(DateTime, default=_now)


class SubPayment(Base):
    # one row per time a subscription was marked paid — drives history + undo
    __tablename__ = "sub_payments"
    id = Column(String, primary_key=True, default=_uid)
    sub_id = Column(String, index=True, nullable=False)
    date = Column(String, nullable=False)  # the due/cycle date that was paid (ISO)
    amount = Column(Float, default=0.0)
    txn_id = Column(String, default="")  # linked money transaction, if posted (for undo)
    created_at = Column(DateTime, default=_now)


class SubPriceChange(Base):
    # recorded whenever a sub's price changes — drives price-history + hike flag
    __tablename__ = "sub_price_changes"
    id = Column(String, primary_key=True, default=_uid)
    sub_id = Column(String, index=True, nullable=False)
    old_price = Column(Float, default=0.0)
    new_price = Column(Float, default=0.0)
    date = Column(String, default="")  # ISO date of the change
    created_at = Column(DateTime, default=_now)


class Account(Base):
    __tablename__ = "money_accounts"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    kind = Column(String, default="checking")  # checking | savings | cash | credit | investment
    currency = Column(String, default="$")
    opening = Column(Float, default=0.0)  # starting balance; live balance = opening + txns
    color = Column(String, default="accent")
    archived = Column(Boolean, default=False)
    low_balance = Column(Float, default=0.0)  # alert threshold; 0 = off (4e)
    created_at = Column(DateTime, default=_now)


class Transaction(Base):
    __tablename__ = "money_transactions"
    id = Column(String, primary_key=True, default=_uid)
    account_id = Column(String, ForeignKey("money_accounts.id", ondelete="CASCADE"))
    date = Column(String, nullable=False)  # ISO date YYYY-MM-DD
    amount = Column(Float, default=0.0)  # positive = income, negative = expense
    category = Column(String, default="")
    payee = Column(String, default="")
    notes = Column(Text, default="")
    transfer_id = Column(String, default="")  # links the two legs of an inter-account transfer
    tags = Column(Text, default="")  # csv structured tags (4a)
    receipt_id = Column(String, default="")  # Upload.id of an attached receipt (4a)
    cleared = Column(Boolean, default=False)  # reconciled-against-statement flag (4a)
    created_at = Column(DateTime, default=_now)


class TxnSplit(Base):
    # one piece of a split transaction (4a) — re-buckets a txn's amount across
    # several categories. amount is the positive magnitude of this slice.
    __tablename__ = "money_txn_splits"
    id = Column(String, primary_key=True, default=_uid)
    txn_id = Column(String, ForeignKey("money_transactions.id", ondelete="CASCADE"), index=True)
    category = Column(String, default="")
    amount = Column(Float, default=0.0)  # magnitude of this slice (always positive)
    created_at = Column(DateTime, default=_now)


class Budget(Base):
    __tablename__ = "money_budgets"
    id = Column(String, primary_key=True, default=_uid)
    category = Column(String, nullable=False)
    limit_amt = Column(Float, default=0.0)  # monthly spending cap for this category
    created_at = Column(DateTime, default=_now)


class BudgetAssignment(Base):
    # YNAB envelope: money assigned to a category for a given month (4b)
    __tablename__ = "money_assignments"
    id = Column(String, primary_key=True, default=_uid)
    category = Column(String, nullable=False, index=True)
    month = Column(String, nullable=False, index=True)  # YYYY-MM
    assigned = Column(Float, default=0.0)
    created_at = Column(DateTime, default=_now)


class FundingTarget(Base):
    # YNAB funding target: want `amount` in `category` by `target_date` (4b)
    __tablename__ = "money_targets"
    id = Column(String, primary_key=True, default=_uid)
    category = Column(String, nullable=False, unique=True)
    amount = Column(Float, default=0.0)
    target_date = Column(String, default="")
    created_at = Column(DateTime, default=_now)


class RecurringTxn(Base):
    # a scheduled transaction (rent, salary, loan payment) auto-posted each cycle
    __tablename__ = "money_recurring"
    id = Column(String, primary_key=True, default=_uid)
    account_id = Column(String, ForeignKey("money_accounts.id", ondelete="CASCADE"))
    amount = Column(Float, default=0.0)  # signed: + income, - expense
    category = Column(String, default="")
    payee = Column(String, default="")
    notes = Column(Text, default="")
    cycle = Column(String, default="monthly")  # weekly|monthly|quarterly|yearly|custom
    cycle_days = Column(Integer, default=30)  # only used when cycle == custom
    next_date = Column(String, default="")  # ISO date of the next occurrence to post
    active = Column(Boolean, default=True)
    last_posted = Column(String, default="")  # ISO date we last auto-posted
    created_at = Column(DateTime, default=_now)


class Goal(Base):
    # a savings or debt-payoff goal (4d). savings: current grows to target; debt:
    # current is the remaining balance shrinking to 0. monthly drives the ETA.
    __tablename__ = "money_goals"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    kind = Column(String, default="savings")  # savings | debt
    target = Column(Float, default=0.0)
    current = Column(Float, default=0.0)
    monthly = Column(Float, default=0.0)  # planned monthly contribution / payment
    created_at = Column(DateTime, default=_now)


class Holding(Base):
    # a manual investment holding (4c): value = qty*price, gain = qty*(price − cost_basis)
    __tablename__ = "money_holdings"
    id = Column(String, primary_key=True, default=_uid)
    symbol = Column(String, nullable=False)
    name = Column(String, default="")
    qty = Column(Float, default=0.0)
    cost_basis = Column(Float, default=0.0)  # per-share cost
    price = Column(Float, default=0.0)  # latest (manual) price per share
    created_at = Column(DateTime, default=_now)


class Watch(Base):
    # a watched payee/category (4c) — drives alerts when matching txns land
    __tablename__ = "money_watches"
    id = Column(String, primary_key=True, default=_uid)
    kind = Column(String, default="category")  # payee | category
    value = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)


class CategoryRule(Base):
    # payee substring → category, applied to typed/imported txns with no category
    __tablename__ = "money_category_rules"
    id = Column(String, primary_key=True, default=_uid)
    match = Column(String, nullable=False)  # case-insensitive substring of the payee
    category = Column(String, default="")
    created_at = Column(DateTime, default=_now)


class FileTag(Base):
    # macOS-Finder-style labels for a file/folder in the files app, keyed by its
    # root-relative path. tags = comma-separated, color = one swatch name.
    __tablename__ = "file_tags"
    id = Column(String, primary_key=True, default=_uid)
    path = Column(String, unique=True, index=True)  # files-root-relative
    tags = Column(String, default="")  # csv of normalized (lowercased) tags
    color = Column(String, default="")  # swatch name: red/orange/green/blue/purple/gray
    starred = Column(Boolean, default=False)  # favorite flag (6a)
    created_at = Column(DateTime, default=_now)


class DocRevision(Base):
    __tablename__ = "doc_revisions"
    id = Column(String, primary_key=True, default=_uid)
    path = Column(String, nullable=False, index=True)  # vault-relative, normalized
    content = Column(Text, default="")
    created_at = Column(DateTime, default=_now)


class IndexChunk(Base):
    # reusable, persistent, multi-kind text index (1c) — shared by docs RAG (3d)
    # and code semantic search (10a). vec is a JSON float list, or "" when no embedder.
    __tablename__ = "index_chunks"
    id = Column(String, primary_key=True, default=_uid)
    kind = Column(String, nullable=False, index=True)  # doc | code | ...
    ref = Column(String, nullable=False, index=True)  # vault path, symbol id, ...
    chunk_no = Column(Integer, default=0)
    text = Column(Text, default="")
    vec = Column(Text, default="")  # json.dumps(list[float]) or ""
    created_at = Column(DateTime, default=_now)


class FileVersion(Base):
    # generic file version history (1e) — blobs stored under <data>/.versions, deduped by sha.
    __tablename__ = "file_versions"
    id = Column(String, primary_key=True, default=_uid)
    path = Column(String, nullable=False, index=True)  # files-relative path
    sha = Column(String, default="")
    size = Column(Integer, default=0)
    stored = Column(String, default="")  # blob filename in the versions dir
    created_at = Column(DateTime, default=_now)


class TrashItem(Base):
    # generic soft-delete registry (1d). files stash their bytes in the trash dir;
    # photos flip Photo.deleted_at. restore/purge dispatch on kind. expires_at drives purge.
    __tablename__ = "trash_items"
    id = Column(String, primary_key=True, default=_uid)
    kind = Column(String, nullable=False, index=True)  # file | photo
    ref = Column(String, nullable=False)  # files-relative path | photo id
    name = Column(String, default="")
    payload = Column(Text, default="{}")  # json: {trash_name, is_dir, ...}
    trashed_at = Column(DateTime, default=_now)
    expires_at = Column(DateTime, nullable=True)


class Share(Base):
    # generic read-only share/publish for any resource (1a). sessions keep their
    # own share_token column for back-compat; this covers doc/file/photo/etc.
    __tablename__ = "shares"
    id = Column(String, primary_key=True, default=_uid)
    token = Column(
        String, unique=True, index=True, nullable=False, default=lambda: uuid.uuid4().hex
    )
    kind = Column(String, nullable=False)  # doc|file|photo|album|contact|event|session
    ref = Column(String, nullable=False)  # resource id, or vault/files-relative path
    level = Column(String, default="view")  # view | download
    created_at = Column(DateTime, default=_now)


class DocComment(Base):
    # inline comments anchored to a quoted span of a doc (3e). a thread root has
    # parent_id == None; replies point at the root via parent_id. anchor holds the
    # quoted text — orphaned (computed on read) when it no longer occurs in the note.
    __tablename__ = "doc_comments"
    id = Column(String, primary_key=True, default=_uid)
    doc = Column(String, nullable=False, index=True)  # vault-relative path
    anchor = Column(Text, default="")  # the quoted text the thread is pinned to
    body = Column(Text, default="")
    author = Column(String, default="me")
    parent_id = Column(String, nullable=True, index=True)  # None = thread root
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)


class FileComment(Base):
    # comments on a file in the files app (6c), keyed by files-relative path. threaded like
    # DocComment: a root has parent_id == None, replies point at the root via parent_id.
    __tablename__ = "file_comments"
    id = Column(String, primary_key=True, default=_uid)
    path = Column(String, nullable=False, index=True)  # files-root-relative
    body = Column(Text, default="")
    author = Column(String, default="me")
    parent_id = Column(String, nullable=True, index=True)  # None = thread root
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id = Column(String, primary_key=True, default=_uid)
    endpoint = Column(Text, unique=True, nullable=False)  # browser push URL
    p256dh = Column(String, default="")  # client public key
    auth = Column(String, default="")  # client auth secret
    created_at = Column(DateTime, default=_now)


class CachedMessage(Base):
    # header cache for the mail inbox — instant open + offline fallback + local search,
    # so we're not waiting on an IMAP round-trip every time. populated on each live fetch.
    __tablename__ = "cached_messages"
    id = Column(String, primary_key=True, default=_uid)
    account_id = Column(String, index=True, nullable=False)
    folder = Column(String, default="INBOX", index=True)
    uid = Column(String, nullable=False)
    sender = Column(Text, default="")
    subject = Column(Text, default="")
    date = Column(String, default="")
    date_ts = Column(Float, default=0)
    seen = Column(Boolean, default=False)
    flagged = Column(Boolean, default=False)  # local star/flag (Apple Mail style)
    list_unsubscribe = Column(Text, default="")  # raw List-Unsubscribe header (5a)
    muted = Column(Boolean, default=False)  # muted thread → hidden from lists (5a)
    snoozed_until = Column(String, default="")  # ISO time; hidden until then (5b)
    labels = Column(Text, default="")  # csv user labels (5e)
    cached_at = Column(DateTime, default=_now)


class MailRule(Base):
    # a triage rule (5d): if match_field contains match_value → action
    __tablename__ = "mail_rules"
    id = Column(String, primary_key=True, default=_uid)
    match_field = Column(String, default="from")  # from | subject
    match_value = Column(String, default="")
    action = Column(String, default="markread")  # markread | mute | label | autoreply
    action_arg = Column(String, default="")
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)


class ScheduledMail(Base):
    # an outbound message queued to send at send_at (5b). also powers undo-send
    # (schedule a few seconds out, cancel within the window).
    __tablename__ = "mail_scheduled"
    id = Column(String, primary_key=True, default=_uid)
    account_id = Column(String, index=True, nullable=False)
    to = Column(Text, default="")
    cc = Column(Text, default="")
    bcc = Column(Text, default="")
    subject = Column(Text, default="")
    body = Column(Text, default="")
    html = Column(Text, default="")  # optional HTML alternative (5c)
    in_reply_to = Column(String, default="")
    references = Column(String, default="")
    send_at = Column(String, default="")  # ISO datetime
    status = Column(String, default="scheduled")  # scheduled | sent | canceled
    created_at = Column(DateTime, default=_now)


class SavedSearch(Base):
    # a named mail search / smart mailbox (5a) — stores a query with operators
    __tablename__ = "mail_saved_searches"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    query = Column(Text, default="")
    created_at = Column(DateTime, default=_now)


class Connection(Base):
    __tablename__ = "connections"
    id = Column(String, primary_key=True, default=_uid)
    service = Column(String, nullable=False)  # github | gitlab | slack | ...
    token = Column(Text, default="")  # access token / PAT
    meta = Column(Text, default="{}")  # json: base_url, username, scopes...
    created_at = Column(DateTime, default=_now)


class Monitor(Base):
    # watch — an external thing to keep an eye on (a site, a /health endpoint, a cert)
    __tablename__ = "monitors"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    kind = Column(String, default="http")  # http | health | cert
    interval_secs = Column(Integer, default=300)
    expect_status = Column(Integer, default=0)  # 0 = accept any 2xx/3xx
    expect_keyword = Column(String, default="")  # must appear in body (health/http)
    latency_ceiling_ms = Column(Integer, default=0)  # 0 = no ceiling
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)


class MonitorCheck(Base):
    # one probe result; we keep a rolling window per monitor (pruned in record_check)
    # int PK = sqlite rowid = insertion order, so "newest first" is deterministic even
    # when several checks land in the same (coarse, on windows) utcnow() tick
    __tablename__ = "monitor_checks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    monitor_id = Column(String, index=True)
    ts = Column(DateTime, default=_now)
    ok = Column(Boolean, default=False)
    status_code = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    error = Column(String, default="")
    detail = Column(String, default="")  # e.g. "30d" cert days-left


class Habit(Base):
    __tablename__ = "habits"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    icon = Column(String, default="")
    color = Column(String, default="")
    cadence = Column(String, default="daily")  # daily | weekly
    target = Column(Integer, default=1)  # times per week (weekly cadence)
    created_at = Column(DateTime, default=_now)
    archived = Column(Boolean, default=False)


class HabitLog(Base):
    # presence of a row = the habit was done on that date (one per habit/day)
    __tablename__ = "habit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    habit_id = Column(String, index=True)
    date = Column(String, index=True)  # ISO YYYY-MM-DD (viewer-local)
    created_at = Column(DateTime, default=_now)


class ReadItem(Base):
    # read-later archive: a saved URL with its extracted readable text for offline search
    __tablename__ = "read_items"
    id = Column(String, primary_key=True, default=_uid)
    url = Column(String, nullable=False)
    title = Column(String, default="")
    text = Column(Text, default="")
    excerpt = Column(String, default="")
    site = Column(String, default="")
    image = Column(String, default="")
    read_minutes = Column(Integer, default=1)
    added_at = Column(DateTime, default=_now)
    read_at = Column(String, default="")  # iso when marked read; "" = unread
    fav = Column(Boolean, default=False)
    archived = Column(Boolean, default=False)
    tags = Column(String, default="")  # comma-separated


class ReadFeed(Base):
    # an rss/atom feed polled in the background; new entries auto-save as ReadItems
    __tablename__ = "read_feeds"
    id = Column(String, primary_key=True, default=_uid)
    url = Column(String, nullable=False, unique=True)
    title = Column(String, default="")
    last_checked = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)


class Book(Base):
    # reading list: books with shelves (want/reading/done), rating, notes
    __tablename__ = "books"
    id = Column(String, primary_key=True, default=_uid)
    title = Column(String, nullable=False)
    author = Column(String, default="")
    status = Column(String, default="want")  # want | reading | done
    rating = Column(Integer, default=0)  # 0-5
    started = Column(String, default="")
    finished = Column(String, default="")
    cover = Column(String, default="")
    notes = Column(Text, default="")
    isbn = Column(String, default="")
    year = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)


class HealthEntry(Base):
    # health/fitness log: a single measurement (weight, sleep hrs, workout min, med, custom)
    __tablename__ = "health_entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String, index=True)  # weight | sleep | workout | med | custom
    date = Column(String, index=True)  # ISO YYYY-MM-DD (viewer-local)
    value = Column(Float, default=0.0)
    unit = Column(String, default="")
    note = Column(String, default="")
    label = Column(String, default="")  # for custom kinds
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
        _add_col(conn, "cached_messages", "flagged", "BOOLEAN DEFAULT 0")
        # 4a — transaction depth: tags, receipt attachment, cleared/reconcile state
        _add_col(conn, "money_transactions", "tags", "TEXT DEFAULT ''")
        _add_col(conn, "money_transactions", "receipt_id", "TEXT DEFAULT ''")
        _add_col(conn, "money_transactions", "cleared", "BOOLEAN DEFAULT 0")
        # 4e — cancellation helper + low-balance alerts
        _add_col(conn, "subscriptions", "cancel_url", "TEXT DEFAULT ''")
        _add_col(conn, "money_accounts", "low_balance", "FLOAT DEFAULT 0")
        # 5a — mail triage: list-unsubscribe + muted threads
        _add_col(conn, "cached_messages", "list_unsubscribe", "TEXT DEFAULT ''")
        _add_col(conn, "cached_messages", "muted", "BOOLEAN DEFAULT 0")
        # 5b — snooze
        _add_col(conn, "cached_messages", "snoozed_until", "TEXT DEFAULT ''")
        # 5c — scheduled HTML body
        _add_col(conn, "mail_scheduled", "html", "TEXT DEFAULT ''")
        # 5e — message labels
        _add_col(conn, "cached_messages", "labels", "TEXT DEFAULT ''")
        # 6a — starred files
        _add_col(conn, "file_tags", "starred", "BOOLEAN DEFAULT 0")
        for _c, _t in [
            ("company", "TEXT DEFAULT ''"),
            ("title", "TEXT DEFAULT ''"),
            ("address", "TEXT DEFAULT ''"),
            ("birthday", "TEXT DEFAULT ''"),
            ("website", "TEXT DEFAULT ''"),
            ("favorite", "BOOLEAN DEFAULT 0"),
        ]:
            _add_col(conn, "contacts", _c, _t)
        _add_col(conn, "vault_entries", "type", "TEXT DEFAULT 'password'")
        _add_col(conn, "subscriptions", "trial_end", "TEXT DEFAULT ''")
        _add_col(conn, "money_transactions", "transfer_id", "TEXT DEFAULT ''")
        _add_col(conn, "sessions", "persona_id", "TEXT")
        _add_col(conn, "sessions", "project_id", "TEXT")
        _add_col(conn, "sessions", "working_dir", "TEXT DEFAULT ''")
        _add_col(conn, "sessions", "incognito", "BOOLEAN DEFAULT 0")
        _add_col(conn, "sessions", "mode", "TEXT DEFAULT 'chat'")
        _add_col(conn, "sessions", "starred", "BOOLEAN DEFAULT 0")
        _add_col(conn, "sessions", "archived", "BOOLEAN DEFAULT 0")
        _add_col(conn, "sessions", "share_token", "TEXT")
        _add_col(conn, "model_endpoints", "vision_models", "TEXT DEFAULT '[]'")
        _add_col(conn, "model_endpoints", "image_models", "TEXT DEFAULT '[]'")
        _add_col(conn, "personas", "initial_message", "TEXT DEFAULT ''")
        _add_col(conn, "projects", "working_dir", "TEXT DEFAULT ''")
        _add_col(conn, "vault_entries", "username", "TEXT DEFAULT ''")
        _add_col(conn, "calendar_events", "recurrence", "TEXT DEFAULT ''")
        _add_col(conn, "calendar_events", "recur_until", "TEXT")
        _add_col(conn, "calendar_events", "caldav_uid", "TEXT")
        _add_col(conn, "reminders", "notified", "BOOLEAN DEFAULT 0")
        _add_col(conn, "tasks", "parent_id", "TEXT")
        _add_col(conn, "tasks", "tags", "TEXT DEFAULT ''")
        _add_col(conn, "tasks", "repeat", "TEXT DEFAULT ''")
        _add_col(conn, "tasks", "notes", "TEXT DEFAULT ''")
        _add_col(conn, "tasks", "project", "TEXT DEFAULT ''")
        _add_col(conn, "tasks", "sort_order", "INTEGER DEFAULT 0")
        _add_col(conn, "personas", "temperature", "REAL")
        _add_col(conn, "personas", "default_mode", "TEXT DEFAULT ''")
        _add_col(conn, "personas", "accent", "TEXT DEFAULT ''")
        _add_col(conn, "subscriptions", "account_id", "TEXT DEFAULT ''")
        _add_col(conn, "subscriptions", "last_posted_due", "TEXT DEFAULT ''")
        _add_col(conn, "tasks", "completed_at", "DATETIME")
        _add_col(conn, "calendar_events", "calendar_id", "TEXT DEFAULT ''")
        _add_col(conn, "calendar_events", "location", "TEXT DEFAULT ''")
        _add_col(conn, "calendar_events", "guests", "TEXT DEFAULT ''")
        _add_col(conn, "calendar_events", "reminders", "TEXT DEFAULT '[]'")
        _add_col(conn, "calendar_events", "recur_interval", "INTEGER DEFAULT 1")
        _add_col(conn, "calendar_events", "recur_byday", "TEXT DEFAULT ''")
        _add_col(conn, "calendar_events", "recur_count", "INTEGER")
        _add_col(conn, "calendar_events", "recur_except", "TEXT DEFAULT '[]'")
        _add_col(conn, "photos", "deleted_at", "DATETIME")
        # 7a — captions/keywords + hidden album
        _add_col(conn, "photos", "caption", "TEXT DEFAULT ''")
        _add_col(conn, "photos", "keywords", "TEXT DEFAULT ''")
        _add_col(conn, "photos", "hidden", "BOOLEAN DEFAULT 0")
        # 7c — video assets
        _add_col(conn, "photos", "is_video", "BOOLEAN DEFAULT 0")
        # 8a — ICS URL subscriptions
        _add_col(conn, "calendar_events", "subscription_id", "VARCHAR")
        # 8b — video links (attendees/booking pages are new tables, no _add_col needed)
        _add_col(conn, "calendar_events", "meeting_url", "VARCHAR DEFAULT ''")
        # 8c — contact avatar + Me card (fields/groups are new tables)
        _add_col(conn, "contacts", "avatar", "VARCHAR DEFAULT ''")
        _add_col(conn, "contacts", "is_me", "BOOLEAN DEFAULT 0")
        # 8d — CardDAV sync columns
        _add_col(conn, "contacts", "carddav_uid", "VARCHAR DEFAULT ''")
        _add_col(conn, "contacts", "carddav_href", "VARCHAR DEFAULT ''")
        _add_col(conn, "contacts", "carddav_etag", "VARCHAR DEFAULT ''")
        # 9c — multi-vault: scope existing entries to the default vault
        _add_col(conn, "vault_entries", "vault_id", "TEXT DEFAULT 'default'")
        _add_col(conn, "vaults", "biometric_blob", "TEXT DEFAULT ''")
        _add_col(conn, "webauthn_credentials", "role", "TEXT DEFAULT ''")
        # webhook hardening — signing secret + delivery status
        _add_col(conn, "webhooks", "secret", "TEXT DEFAULT ''")
        _add_col(conn, "webhooks", "last_status", "TEXT DEFAULT ''")
        _add_col(conn, "webhooks", "last_error", "TEXT DEFAULT ''")
        _add_col(conn, "webhooks", "last_triggered", "DATETIME")
        _add_col(conn, "notes", "tags", "TEXT DEFAULT ''")
    _encrypt_plaintext_secrets()


def _encrypt_plaintext_secrets():
    """one-time (idempotent) — seal credentials that predate at-rest encryption"""
    from services.secretstore import PREFIX, seal

    with engine.begin() as conn:
        for table, col in (("model_endpoints", "api_key"), ("mail_accounts", "password")):
            rows = conn.execute(
                text(f"SELECT id, {col} FROM {table} WHERE {col} != '' AND {col} NOT LIKE :p"),
                {"p": PREFIX + "%"},
            ).fetchall()
            for rid, val in rows:
                conn.execute(
                    text(f"UPDATE {table} SET {col} = :v WHERE id = :id"),
                    {"v": seal(val), "id": rid},
                )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
