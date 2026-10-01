import json

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from core.schema.base import Base, EncryptedText, _now, _uid


class ModelEndpoint(Base):
    __tablename__ = "model_endpoints"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    base_url = Column(String, nullable=False)
    api_key = Column(EncryptedText("model_endpoints.api_key"), default="")
    provider_id = Column(String, default="")
    auth_type = Column(String, default="api_key")
    auth_status = Column(String, default="incomplete")
    auth_error = Column(String, default="")
    account_identity = Column(String, default="")
    oauth_client_id = Column(EncryptedText("model_endpoints.oauth_client_id"), default="")
    oauth_client_secret = Column(EncryptedText("model_endpoints.oauth_client_secret"), default="")
    oauth_project_id = Column(String, default="")
    oauth_refresh_token = Column(EncryptedText("model_endpoints.oauth_refresh_token"), default="")
    oauth_expires_at = Column(Float, default=0.0)
    oauth_scopes = Column(Text, default="[]")
    enabled = Column(Boolean, default=True)
    cached_models = Column(Text, default="[]")  # json list of model id strings (chat)
    vision_models = Column(Text, default="[]")  # json list of vision-capable model ids
    image_models = Column(Text, default="[]")  # json list of image-generation model ids
    provider_adapter = Column(String, default="auto")
    catalog_status = Column(String, default="unverified")
    catalog_source = Column(String, default="")
    catalog_error = Column(String, default="")
    catalog_refreshed_at = Column(DateTime, nullable=True)
    unavailable_models = Column(Text, default="[]")
    model_metadata = Column(Text, default="{}")
    health_status = Column(String, default="unverified")
    last_tested_at = Column(DateTime, nullable=True)
    last_error_code = Column(String, default="")
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

    def unavailable_models_list(self):
        try:
            value = json.loads(self.unavailable_models or "[]")
            return value if isinstance(value, list) else []
        except Exception:
            return []

    def model_metadata_dict(self):
        try:
            value = json.loads(self.model_metadata or "{}")
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, default="new chat")
    model = Column(String, default="")
    endpoint_id = Column(
        String, ForeignKey("model_endpoints.id", ondelete="SET NULL"), nullable=True
    )
    mode = Column(String, default="chat")  # chat | jarvis; legacy agent reads as jarvis
    chat_behavior = Column(
        String, default=""
    )  # '' follows Settings | automatic_tools | answer_only
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


class AndromedaSavedSearch(Base):
    """A complete, reopenable search snapshot; no model or provider secrets."""

    __tablename__ = "andromeda_saved_searches"
    id = Column(String, primary_key=True, default=_uid)
    query = Column(Text, nullable=False)
    request_json = Column(Text, default="{}")
    results_json = Column(Text, default="[]")
    overview_json = Column(Text, default="{}")
    evidence_json = Column(Text, default="[]")
    model_json = Column(Text, default="{}")
    verification_json = Column(Text, default="{}")
    verifier_model_json = Column(Text, default="{}")
    checked_at = Column(DateTime, default=_now)
    created_at = Column(DateTime, default=_now)


class AndromedaVerificationJob(Base):
    """Durable background fact-check state for one fast Andromeda answer."""

    __tablename__ = "andromeda_verification_jobs"
    id = Column(String, primary_key=True, default=_uid)
    query = Column(Text, nullable=False)
    answer_json = Column(Text, nullable=False, default="{}")
    results_json = Column(Text, nullable=False, default="[]")
    evidence_json = Column(Text, nullable=False, default="[]")
    model_json = Column(Text, nullable=False, default="{}")
    result_json = Column(Text, nullable=False, default="{}")
    status = Column(String, nullable=False, default="pending", index=True)
    error_code = Column(String, nullable=False, default="")
    checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class McpServer(Base):
    __tablename__ = "mcp_servers"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    transport = Column(String, default="stdio")  # stdio | sse
    command = Column(String, default="")
    args = Column(EncryptedText("mcp_servers.args"), default="[]")  # json list
    url = Column(EncryptedText("mcp_servers.url"), default="")
    env = Column(EncryptedText("mcp_servers.env"), default="{}")
    headers = Column(EncryptedText("mcp_servers.headers"), default="{}")
    enabled = Column(Boolean, default=True)
    disabled_tools = Column(Text, default="[]")  # json list of disabled tool names
    created_at = Column(DateTime, default=_now)

    def args_list(self):
        try:
            return json.loads(self.args or "[]")
        except Exception:
            return []

    def env_dict(self):
        try:
            value = json.loads(self.env or "{}")
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def headers_dict(self):
        try:
            value = json.loads(self.headers or "{}")
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def disabled_tools_list(self):
        try:
            return json.loads(self.disabled_tools or "[]")
        except Exception:
            return []


# the `notes` table was retired (m0010) — notes live in the markdown vault now
# (services/notes_vault.py), so there is no Note model anymore.


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
    stage = Column(String, default="backlog")  # backlog | next | doing | waiting | done
    priority = Column(Integer, default=0)  # 0 normal, 1 high
    due_date = Column(String, nullable=True)
    parent_id = Column(String, nullable=True)  # subtasks point at their parent
    tags = Column(String, default="")  # comma-separated
    repeat = Column(String, default="")  # ''|daily|weekly|monthly|yearly
    anchor_day = Column(
        Integer, nullable=True
    )  # original day-of-month so monthly/yearly repeats don't drift
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
    blocked_scopes = Column(
        String, default=""
    )  # 3b - csv permission scopes this persona may NOT use
    blocked_tools = Column(String, default="")  # 3b - csv tool names this persona may NOT use
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


class ContactLink(Base):
    # 4a - a typed edge in the contact relationship graph (spouse/manager/colleague/...)
    __tablename__ = "contact_links"
    id = Column(String, primary_key=True, default=_uid)
    from_id = Column(String, index=True, nullable=False)
    to_id = Column(String, index=True, nullable=False)
    kind = Column(String, default="")
    created_at = Column(DateTime, default=_now)


class ResearchFinding(Base):
    # 3g - cross-session deep-research fact cache: one extracted finding, keyed by URL
    __tablename__ = "research_findings"
    id = Column(String, primary_key=True, default=_uid)
    url = Column(String, index=True, default="")
    question = Column(Text, default="")
    title = Column(String, default="")
    summary = Column(Text, default="")
    ts = Column(DateTime, default=_now)


class ToolChain(Base):
    # 3c - a saved macro: an ordered list of capability invocations run atomically
    __tablename__ = "tool_chains"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    steps = Column(Text, default="[]")  # json: [{kind, name, args}, ...]
    created_at = Column(DateTime, default=_now)


class Webhook(Base):
    __tablename__ = "webhooks"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    events = Column(Text, default="[]")  # json list: message, research_done, session_created
    enabled = Column(Boolean, default=True)
    secret = Column(EncryptedText("webhooks.secret"), default="")
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
    scopes = Column(Text, default='["read"]', nullable=False)
    created_at = Column(DateTime, default=_now)
    last_used_at = Column(DateTime, nullable=True)


class Memory(Base):
    __tablename__ = "memories"
    id = Column(String, primary_key=True, default=_uid)
    text = Column(Text, nullable=False)
    category = Column(String, default="general")  # identity | preference | fact | task | general
    source = Column(String, default="manual")  # manual | extracted | imported | distilled
    session_id = Column(String, nullable=True)  # which session it came from
    pinned = Column(Boolean, default=False)  # always inject if pinned
    timestamp = Column(DateTime, default=_now)
    # 1c - auto-distilled user-model facts: a learned confidence, a veto (hide + never
    # re-distill), and where the fact came from.
    confidence = Column(Float, default=1.0)
    vetoed = Column(Boolean, default=False)
    provenance = Column(String, default="")
    scope = Column(String, default="global")  # global | project
    project_id = Column(String, nullable=True)
    status = Column(String, default="active")  # active | suggested
    trust = Column(String, default="owner")  # owner | reviewed | derived | untrusted
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    used_in_runs = Column(Text, default="[]")


class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    system_prompt = Column(Text, default="")
    working_dir = Column(Text, default="")
    scratchpad = Column(Text, default="")
    color = Column(String, default="")
    created_at = Column(DateTime, default=_now)
    last_opened_at = Column(DateTime, nullable=True)

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


class VaultCreateReceipt(Base):
    """A vault-scoped save identity with no secret fields or secret fingerprints."""

    __tablename__ = "vault_create_receipts"
    vault_id = Column(String, primary_key=True)
    id = Column(String, primary_key=True)
    entry_id = Column(String, nullable=True, index=True)
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


class BrowserConnection(Base):
    """Paired browser identity. Only a hash of the persistent device secret is stored."""

    __tablename__ = "browser_connections"
    id = Column(String, primary_key=True, default=_uid)
    vault_id = Column(String, nullable=False, default="default")
    name = Column(String, nullable=False, default="Browser")
    secret_hash = Column(String, nullable=False)
    extension_origin = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    last_seen_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


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
    password = Column(EncryptedText("mail_accounts.password"), default="")
    use_ssl = Column(Boolean, default=True)
    # oauth ("sign in with google") - tokens sealed at rest, no password stored
    auth_type = Column(String, default="password")  # password | oauth
    oauth_provider = Column(String, default="")  # google
    oauth_access_token = Column(EncryptedText("mail_accounts.oauth_access_token"), default="")
    oauth_refresh_token = Column(EncryptedText("mail_accounts.oauth_refresh_token"), default="")
    oauth_expires_at = Column(Float, default=0.0)  # unix ts the access token expires
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
    __table_args__ = (
        Index(
            "ux_photos_source_id",
            "source",
            "source_id",
            unique=True,
            sqlite_where=text("source_id IS NOT NULL AND source_id != ''"),
        ),
    )
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
    archived = Column(Boolean, default=False)  # out of the main timeline, still in the library
    is_video = Column(Boolean, default=False)  # 7c — mp4/mov/etc; played, not thumbnailed
    deleted_at = Column(DateTime, nullable=True)  # soft-delete (1d trash); None = live
    created_at = Column(DateTime, default=_now)  # import time
    aspect_ratio = Column(Float, nullable=True)  # w/h, served for the justified grid (phase 4)
    preview = Column(Text, default="")  # tiny base64 jpeg — upscaled = a blur-up placeholder
    checksum = Column(String, nullable=True)  # sha256 of the original bytes (dedupe, phase 6)
    stack_id = Column(String, nullable=True)  # cover photo's id, shared by stack members (phase 6)
    clip = Column(
        LargeBinary, nullable=True
    )  # CLIP image embedding (512 float32) for semantic search
    faces_at = Column(
        DateTime, nullable=True
    )  # when face detection last ran (null = not scanned yet)
    source = Column(String, nullable=True, index=True)  # e.g. apple_photos; null for local uploads
    source_id = Column(String, nullable=True, index=True)  # stable resource id for repeat sync
    source_asset_id = Column(String, nullable=True, index=True)  # groups PhotoKit live resources
    source_modified_at = Column(DateTime, nullable=True)  # source revision at last sync


class Person(Base):
    # a face cluster — one real person. unnamed until the user names it (phase 7a)
    __tablename__ = "people"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, default="")  # blank = unnamed cluster
    cover_face_id = Column(String, nullable=True)  # the face shown as the avatar
    hidden = Column(Boolean, default=False)  # "not a person" / hide from the People row
    created_at = Column(DateTime, default=_now)


class Face(Base):
    # one detected face in one photo, with its 512-d ArcFace embedding (phase 7a)
    __tablename__ = "faces"
    id = Column(String, primary_key=True, default=_uid)
    photo_id = Column(
        String, ForeignKey("photos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_id = Column(
        String, ForeignKey("people.id", ondelete="SET NULL"), nullable=True, index=True
    )
    bbox = Column(String, default="")  # "x1,y1,x2,y2" in original-pixel coords
    det_score = Column(Float, default=0.0)
    embedding = Column(LargeBinary, nullable=True)  # 512 float32, L2-normalized
    created_at = Column(DateTime, default=_now)


class Reminder(Base):
    __tablename__ = "reminders"
    id = Column(String, primary_key=True, default=_uid)
    text = Column(Text, nullable=False)
    trigger_at = Column(DateTime, nullable=False)
    type = Column(String, default="reminder")  # reminder | message
    session_id = Column(String, nullable=True)  # for type=message
    fired = Column(Boolean, default=False)
    # Durable delivery claim: true means sent or uncertain, so background jobs do not retry blindly.
    notified = Column(Boolean, default=False)
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
    migrated_workflow_id = Column(String, nullable=True, index=True)
    enabled_intent = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=_now)


class AutomationAttempt(Base):
    """One durable claim for one legacy automation occurrence.

    Phase 0 keeps this intentionally small. The fuller Jarvis run/delivery model
    comes later, but this claim is enough to prevent a crash or uncertain
    external response from causing the same action to run again blindly.
    """

    __tablename__ = "automation_attempts"
    __table_args__ = (
        Index(
            "ux_automation_attempts_rule_occurrence",
            "rule_id",
            "occurrence_key",
            unique=True,
        ),
    )

    id = Column(String, primary_key=True, default=_uid)
    rule_id = Column(
        String,
        ForeignKey("automation_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SHA-256 of the trigger identity. Paths and mail/account identifiers are not copied here.
    occurrence_key = Column(String(64), nullable=False)
    status = Column(String, nullable=False, default="running")
    action = Column(String, nullable=False, default="")
    error = Column(Text, default="")
    started_at = Column(DateTime, default=_now)
    finished_at = Column(DateTime, nullable=True)


class JarvisWorkflow(Base):
    __tablename__ = "jarvis_workflows"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    purpose = Column(Text, default="")
    project_id = Column(String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    prompt = Column(Text, default="")
    deterministic_action = Column(String, default="")
    model_override = Column(String, default="")
    capability_ceiling = Column(Text, default="[]")
    concurrency_mode = Column(String, default="one")
    context_mode = Column(String, default="fresh")
    delivery_policy = Column(Text, default="{}")
    enabled = Column(Boolean, default=False)
    active_run_id = Column(String, nullable=True, index=True)
    legacy_automation_id = Column(String, nullable=True, unique=True)
    review_state = Column(String, nullable=False, default="ready", index=True)
    legacy_enabled_intent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class JarvisTrigger(Base):
    __tablename__ = "jarvis_triggers"
    id = Column(String, primary_key=True, default=_uid)
    workflow_id = Column(
        String, ForeignKey("jarvis_workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String, nullable=False)
    config = Column(Text, default="{}")
    timezone = Column(String, default="UTC")
    enabled = Column(Boolean, default=False)
    next_run_at = Column(DateTime, nullable=True, index=True)
    last_run_at = Column(DateTime, nullable=True)
    fingerprint = Column(String, default="")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class JarvisRun(Base):
    __tablename__ = "jarvis_runs"
    __table_args__ = (
        Index(
            "ux_jarvis_runs_trigger_occurrence",
            "trigger_id",
            "occurrence_key",
            unique=True,
        ),
    )
    id = Column(String, primary_key=True, default=_uid)
    workflow_id = Column(
        String, ForeignKey("jarvis_workflows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trigger_id = Column(
        String, ForeignKey("jarvis_triggers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id = Column(String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    state = Column(String, nullable=False, default="queued", index=True)
    scheduled_for = Column(DateTime, nullable=True)
    occurrence_key = Column(String(64), nullable=True)
    lease_owner = Column(String, default="")
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    next_attempt_at = Column(DateTime, nullable=True, index=True)
    attempt_count = Column(Integer, default=0)
    failure_class = Column(String, default="")
    safe_error = Column(Text, default="")
    result_summary = Column(Text, default="")
    left_project_root = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class JarvisRunEvent(Base):
    __tablename__ = "jarvis_run_events"
    __table_args__ = (
        Index("ux_jarvis_run_events_run_sequence", "run_id", "sequence", unique=True),
    )
    id = Column(String, primary_key=True, default=_uid)
    run_id = Column(
        String, ForeignKey("jarvis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)
    source = Column(String, default="")
    tool_name = Column(String, default="")
    summary = Column(Text, default="")
    data = Column(Text, default="{}")
    created_at = Column(DateTime, default=_now)


class JarvisRunPrompt(Base):
    __tablename__ = "jarvis_run_prompts"
    id = Column(String, primary_key=True, default=_uid)
    run_id = Column(
        String, ForeignKey("jarvis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String, nullable=False)
    state = Column(String, nullable=False, default="pending", index=True)
    question = Column(Text, nullable=False)
    options = Column(Text, default="[]")
    question_schema = Column(Text, default="{}")
    action = Column(String, default="")
    target = Column(Text, default="")
    data_summary = Column(Text, default="")
    privacy_effect = Column(Text, default="")
    cost = Column(String, default="")
    capability = Column(String, default="")
    expires_at = Column(DateTime, nullable=True)
    answer = Column(Text, default="")
    answer_data = Column(Text, default="{}")
    responded_at = Column(DateTime, nullable=True)
    used_at = Column(DateTime, nullable=True)
    delegated_action_id = Column(String, nullable=True, unique=True)
    created_at = Column(DateTime, default=_now)


class JarvisDeliveryAttempt(Base):
    __tablename__ = "jarvis_delivery_attempts"
    id = Column(String, primary_key=True, default=_uid)
    run_id = Column(
        String, ForeignKey("jarvis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id = Column(
        String, ForeignKey("jarvis_run_events.id", ondelete="SET NULL"), nullable=True
    )
    connector_id = Column(
        String, ForeignKey("jarvis_connectors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    channel = Column(String, nullable=False)
    privacy_level = Column(String, default="title_status")
    state = Column(String, nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, default=0)
    next_attempt_at = Column(DateTime, nullable=True, index=True)
    lease_owner = Column(String, default="")
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    idempotency_supported = Column(Boolean, default=False)
    last_attempt_at = Column(DateTime, nullable=True)
    safe_error_class = Column(String, default="")
    provider_message_id = Column(String, default="")
    idempotency_key = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class JarvisConnector(Base):
    __tablename__ = "jarvis_connectors"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    config = Column(Text, default="{}")
    secret = Column(EncryptedText("jarvis_connectors.secret"), default="")
    allowlist = Column(Text, default="[]")
    enabled = Column(Boolean, default=False)
    external = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class CapabilityGrant(Base):
    __tablename__ = "capability_grants"
    id = Column(String, primary_key=True, default=_uid)
    scope_kind = Column(String, nullable=False, index=True)
    scope_id = Column(String, default="", index=True)
    capability = Column(String, nullable=False, index=True)
    target_root = Column(Text, default="")
    access_mode = Column(String, nullable=False, default="read")
    state = Column(String, nullable=False, default="active", index=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class DelegatedAction(Base):
    __tablename__ = "delegated_actions"
    id = Column(String, primary_key=True, default=_uid)
    origin = Column(String, nullable=False, index=True)
    run_id = Column(String, ForeignKey("jarvis_runs.id", ondelete="SET NULL"), nullable=True)
    agent_run_id = Column(String, nullable=True, index=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    grant_id = Column(
        String, ForeignKey("capability_grants.id", ondelete="SET NULL"), nullable=True
    )
    scope_kind = Column(String, nullable=False, index=True)
    scope_id = Column(String, default="", index=True)
    capability = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)
    target = Column(Text, default="")
    data_summary = Column(Text, default="")
    privacy_effect = Column(Text, default="")
    cost = Column(String, default="")
    exact_hash = Column(String(64), nullable=False, index=True)
    pending_key = Column(String(64), nullable=True, unique=True)
    state = Column(String, nullable=False, default="pending", index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    approved_at = Column(DateTime, nullable=True)
    used_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class CapabilityGrantEvent(Base):
    __tablename__ = "capability_grant_events"
    id = Column(String, primary_key=True, default=_uid)
    grant_id = Column(
        String, ForeignKey("capability_grants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action_id = Column(
        String, ForeignKey("delegated_actions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind = Column(String, nullable=False, index=True)
    actor = Column(String, default="")
    scope_kind = Column(String, default="")
    scope_id = Column(String, default="")
    capability = Column(String, default="")
    created_at = Column(DateTime, default=_now, index=True)


class JarvisInboxEvent(Base):
    __tablename__ = "jarvis_inbox_events"
    id = Column(String, primary_key=True, default=_uid)
    source_kind = Column(String, nullable=False, index=True)
    source_id = Column(String, default="")
    event_type = Column(String, nullable=False, index=True)
    entity_kind = Column(String, default="", index=True)
    entity_id = Column(String, default="")
    safe_summary = Column(Text, default="")
    external = Column(Boolean, default=False)
    state = Column(String, nullable=False, default="pending", index=True)
    dedupe_key = Column(String(64), nullable=False, unique=True)
    reviewed_at = Column(DateTime, nullable=True)
    dispatched_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, index=True)


class ProactiveItem(Base):
    __tablename__ = "proactive_items"
    id = Column(String, primary_key=True, default=_uid)
    dedupe_key = Column(String, index=True, nullable=False)  # one live card per key
    category = Column(String, default="")
    title = Column(String, nullable=False)
    body = Column(Text, default="")
    link = Column(String, default="")  # in-app nav: a view id or deep path
    score = Column(Integer, default=50)  # agent importance 0..100 -> ordering
    urgency = Column(Integer, default=0)  # carried from the source signal
    source_keys = Column(Text, default="[]")  # json list of signal keys summarized
    status = Column(String, default="new")  # new | seen | dismissed | acted
    dismissed = Column(Boolean, default=False)
    # Durable push claim: true also quarantines a delivery with an uncertain outcome.
    pushed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now)


class ProactiveState(Base):
    # single-row scratch: which signal keys the agent has already been shown, so a
    # scheduled run only fires when something genuinely new turns up (not every tick)
    __tablename__ = "proactive_state"
    id = Column(String, primary_key=True, default="singleton")
    seen_keys = Column(Text, default="[]")  # json list of signal keys presented last run
    updated_at = Column(DateTime, default=_now)


class ProactiveOutcome(Base):
    # one row per card fate (1a feedback loop). lets proactive learn which card types the owner
    # acts on vs ignores, and at what latency (cadence). drives a per-category score weight.
    __tablename__ = "proactive_outcomes"
    id = Column(String, primary_key=True, default=_uid)
    item_id = Column(String, index=True, default="")
    dedupe_key = Column(String, default="")
    category = Column(String, index=True, default="")
    outcome = Column(String, nullable=False)  # acted | dismissed | ignored
    latency_sec = Column(Float, default=0.0)  # card age when the outcome landed
    created_at = Column(DateTime, default=_now)


class Insight(Base):
    # cross-domain causal insight (1e) - a higher-level meta-pattern found over weeks of data,
    # with cited evidence. default-off generation; the user pins or dismisses.
    __tablename__ = "insights"
    id = Column(String, primary_key=True, default=_uid)
    kind = Column(String, default="")  # productivity | spending | mood | habit | ...
    title = Column(String, nullable=False)
    body = Column(Text, default="")
    evidence = Column(Text, default="[]")  # json list of evidence refs / signal keys
    dedupe_key = Column(String, index=True, default="")  # hash of the sorted evidence set
    pinned = Column(Boolean, default=False)
    dismissed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)


class SignalSnapshot(Base):
    # rolling history of signals (1b). written on the periodic proactive path (NOT in the pure
    # gather()), so synthesize() can detect trends + cross-category correlation over time.
    __tablename__ = "signal_snapshots"
    id = Column(String, primary_key=True, default=_uid)
    ts = Column(DateTime, default=_now, index=True)
    category = Column(String, index=True, default="")
    key = Column(String, default="")
    urgency = Column(Integer, default=0)
    data = Column(Text, default="{}")


class MutationEvent(Base):
    # durable log of every state change on a tracked model (0c spine). written by
    # SQLAlchemy mapper listeners in services/events.py, in the SAME transaction as the
    # change, so it commits/rolls-back with it. audit + history + the event stream the
    # learning brain consumes.
    __tablename__ = "mutation_events"
    id = Column(String, primary_key=True, default=_uid)
    entity_kind = Column(String, index=True, nullable=False)  # the table name
    entity_id = Column(String, index=True, default="")
    op = Column(String, nullable=False)  # insert | update | delete
    fields = Column(Text, default="{}")  # json: new (insert) or changed (update) columns
    actor = Column(String, default="")
    ts = Column(DateTime, default=_now, index=True)


class AuditRecord(Base):
    """Content-free owner audit trail for API and service control changes."""

    __tablename__ = "audit_records"
    id = Column(String, primary_key=True, default=_uid)
    action = Column(String, nullable=False, index=True)
    outcome = Column(String, nullable=False)
    actor = Column(String, default="")
    target = Column(String, default="")
    request_id = Column(String, default="")
    details = Column(Text, default="{}")
    created_at = Column(DateTime, default=_now, index=True)


class Blob(Base):
    # content-addressed binary store (0d). one row per unique content (sha256); files live at
    # <data>/.blobs/<sha[:2]>/<sha>. refcount tracks how many Attachments point here so a GC can
    # purge orphans. dedup: the same bytes stored twice = one Blob, refcount 2.
    __tablename__ = "blobs"
    id = Column(String, primary_key=True, default=_uid)
    sha256 = Column(String, unique=True, index=True, nullable=False)
    size = Column(Integer, default=0)
    mime = Column(String, default="")
    refcount = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)


class Attachment(Base):
    # generic join from any resource (kind+id) to a Blob, so file-versioning, sharing, export
    # and dedup work uniformly across upload/photo/vault/etc.
    __tablename__ = "attachments"
    id = Column(String, primary_key=True, default=_uid)
    resource_kind = Column(String, index=True, default="")
    resource_id = Column(String, index=True, default="")
    blob_id = Column(String, index=True, nullable=False)
    meta = Column(Text, default="{}")
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
    # occurrence date, or pending:/uncertain: occurrence claim
    last_notified = Column(String, default="")
    created_at = Column(DateTime, default=_now)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id = Column(String, primary_key=True, default=_uid)
    endpoint = Column(Text, unique=True, nullable=False)  # browser push URL
    p256dh = Column(String, default="")  # client public key
    auth = Column(EncryptedText("push_subscriptions.auth"), default="")
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
    recipients = Column(Text, default="")
    subject = Column(Text, default="")
    date = Column(String, default="")
    date_ts = Column(Float, default=0)
    seen = Column(Boolean, default=False)
    flagged = Column(Boolean, default=False)  # local star/flag (Apple Mail style)
    has_attachment = Column(Boolean, default=False)
    list_unsubscribe = Column(Text, default="")  # raw List-Unsubscribe header (5a)
    muted = Column(Boolean, default=False)  # muted thread → hidden from lists (5a)
    snoozed_until = Column(String, default="")  # ISO time; hidden until then (5b)
    labels = Column(Text, default="")  # csv user labels (5e)
    autoreplied = Column(
        Boolean, default=False
    )  # 2g - a rule autoreply already enqueued for this msg
    message_id = Column(String, default="")  # 2i - RFC-5322 Message-ID header
    in_reply_to = Column(String, default="")  # 2i - In-Reply-To header
    references = Column(Text, default="")  # 2i - References header (space-sep id list)
    thread_id = Column(String, default="", index=True)  # 2i - reference-graph thread root
    body_indexed = Column(Boolean, default=False)  # personal-rag: body pulled into the recall index
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
    status = Column(
        String, default="scheduled"
    )  # scheduled | sending | sent | uncertain | canceled
    created_at = Column(DateTime, default=_now)


class SavedSearch(Base):
    # a named mail search / smart mailbox (5a) — stores a query with operators
    __tablename__ = "mail_saved_searches"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    query = Column(Text, default="")
    created_at = Column(DateTime, default=_now)


class ModelVote(Base):
    # a single blind-compare vote: winner model beat loser model
    __tablename__ = "model_votes"
    id = Column(String, primary_key=True, default=_uid)
    winner = Column(String, nullable=False)
    loser = Column(String, default="")
    created_at = Column(DateTime, default=_now)


class Connection(Base):
    __tablename__ = "connections"
    id = Column(String, primary_key=True, default=_uid)
    service = Column(String, nullable=False)  # github | gitlab | slack | ...
    token = Column(EncryptedText("connections.token"), default="")
    meta = Column(EncryptedText("connections.meta"), default="{}")
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


class HabitCreateReceipt(Base):
    # Keep the request after deletion so a late retry cannot recreate the habit.
    __tablename__ = "habit_create_receipts"
    id = Column(String, primary_key=True)
    habit_id = Column(String, index=True, nullable=True)
    created_at = Column(DateTime, default=_now)


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


class NewsConfiguration(Base):
    """Singleton state for the first-class scheduled News workflow."""

    __tablename__ = "news_configuration"
    id = Column(String, primary_key=True, default="singleton")
    enabled = Column(Boolean, default=False)
    cadence = Column(String, default="morning")  # morning | evening | custom
    time_of_day = Column(String, default="08:00")
    timezone = Column(String, default="UTC")
    deliver_home = Column(Boolean, default=True)
    deliver_jarvis = Column(Boolean, default=False)
    next_run_at = Column(DateTime, nullable=True, index=True)
    run_token = Column(String, default="")
    run_lease_until = Column(DateTime, nullable=True, index=True)
    last_run_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_safe_error = Column(String, default="")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class NewsSource(Base):
    __tablename__ = "news_sources"
    id = Column(String, primary_key=True, default=_uid)
    url = Column(String, nullable=False, unique=True)
    name = Column(String, default="")
    category = Column(String, default="general")
    language = Column(String, default="en")
    priority = Column(Integer, default=1)
    schedule = Column(String, default="inherit")
    enabled = Column(Boolean, default=True)
    etag = Column(String, default="")
    last_modified = Column(String, default="")
    last_checked_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_safe_error = Column(String, default="")
    next_retry_at = Column(DateTime, nullable=True, index=True)
    failure_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class NewsEntry(Base):
    __tablename__ = "news_entries"
    __table_args__ = (
        UniqueConstraint("source_id", "guid", name="ux_news_entries_source_guid"),
        UniqueConstraint("canonical_url", name="ux_news_entries_canonical_url"),
    )
    id = Column(String, primary_key=True, default=_uid)
    source_id = Column(
        String, ForeignKey("news_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    guid = Column(String, nullable=False)
    canonical_url = Column(Text, nullable=False)
    title = Column(String, default="")
    excerpt = Column(Text, default="")
    published_at = Column(DateTime, nullable=True, index=True)
    content_hash = Column(String(64), nullable=False, index=True)
    cluster_key = Column(String(64), default="", index=True)
    fetched_at = Column(DateTime, default=_now)


class NewsBrief(Base):
    __tablename__ = "news_briefs"
    id = Column(String, primary_key=True, default=_uid)
    status = Column(String, nullable=False, default="summary_pending", index=True)
    title = Column(String, default="news brief")
    summary = Column(Text, default="")
    clusters = Column(Text, default="[]")
    source_failures = Column(Text, default="[]")
    scheduled_for = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True, index=True)
    delivered_home = Column(Boolean, default=False)
    jarvis_delivery_state = Column(String, default="off", index=True)
    jarvis_attempt_count = Column(Integer, default=0)
    jarvis_next_attempt_at = Column(DateTime, nullable=True, index=True)
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


class HealthCreateReceipt(Base):
    """One create identity; a null entry_id retains deletion without measurement content."""

    __tablename__ = "health_create_receipts"
    id = Column(String, primary_key=True)
    payload_hash = Column(String(64), nullable=False)
    entry_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=_now)
