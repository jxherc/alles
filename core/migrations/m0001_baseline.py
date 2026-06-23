"""m0001 - baseline schema: the squashed column-adds that used to live inline in
core.database.init_db (the ~81 _add_col calls). ALWAYS re-runs so a dropped base column is
self-healed exactly like the old behaviour; add_column is idempotent + surfaces real errors."""

from core.migrations.runner import add_column

VERSION = 1
NAME = "baseline"
ALWAYS = True  # idempotent self-heal every boot (old init_db re-ran all _add_col each time)


def up(conn):
    add_column(conn, "cached_messages", "flagged", "BOOLEAN DEFAULT 0")
    # 4a - transaction depth: tags, receipt attachment, cleared/reconcile state
    add_column(conn, "money_transactions", "tags", "TEXT DEFAULT ''")
    add_column(conn, "money_transactions", "receipt_id", "TEXT DEFAULT ''")
    add_column(conn, "money_transactions", "cleared", "BOOLEAN DEFAULT 0")
    # 4e - cancellation helper + low-balance alerts
    add_column(conn, "subscriptions", "cancel_url", "TEXT DEFAULT ''")
    add_column(conn, "money_accounts", "low_balance", "FLOAT DEFAULT 0")
    # 5a - mail triage: list-unsubscribe + muted threads
    add_column(conn, "cached_messages", "list_unsubscribe", "TEXT DEFAULT ''")
    add_column(conn, "cached_messages", "muted", "BOOLEAN DEFAULT 0")
    # 5b - snooze
    add_column(conn, "cached_messages", "snoozed_until", "TEXT DEFAULT ''")
    # 5c - scheduled HTML body
    add_column(conn, "mail_scheduled", "html", "TEXT DEFAULT ''")
    # 5e - message labels
    add_column(conn, "cached_messages", "labels", "TEXT DEFAULT ''")
    # 6a - starred files
    add_column(conn, "file_tags", "starred", "BOOLEAN DEFAULT 0")
    for _c, _t in [
        ("company", "TEXT DEFAULT ''"),
        ("title", "TEXT DEFAULT ''"),
        ("address", "TEXT DEFAULT ''"),
        ("birthday", "TEXT DEFAULT ''"),
        ("website", "TEXT DEFAULT ''"),
        ("favorite", "BOOLEAN DEFAULT 0"),
    ]:
        add_column(conn, "contacts", _c, _t)
    add_column(conn, "vault_entries", "type", "TEXT DEFAULT 'password'")
    add_column(conn, "subscriptions", "trial_end", "TEXT DEFAULT ''")
    add_column(conn, "money_transactions", "transfer_id", "TEXT DEFAULT ''")
    add_column(conn, "sessions", "persona_id", "TEXT")
    add_column(conn, "sessions", "project_id", "TEXT")
    add_column(conn, "sessions", "working_dir", "TEXT DEFAULT ''")
    add_column(conn, "sessions", "incognito", "BOOLEAN DEFAULT 0")
    add_column(conn, "sessions", "mode", "TEXT DEFAULT 'chat'")
    add_column(conn, "sessions", "starred", "BOOLEAN DEFAULT 0")
    add_column(conn, "sessions", "archived", "BOOLEAN DEFAULT 0")
    add_column(conn, "sessions", "share_token", "TEXT")
    add_column(conn, "model_endpoints", "vision_models", "TEXT DEFAULT '[]'")
    add_column(conn, "model_endpoints", "image_models", "TEXT DEFAULT '[]'")
    add_column(conn, "personas", "initial_message", "TEXT DEFAULT ''")
    add_column(conn, "projects", "working_dir", "TEXT DEFAULT ''")
    add_column(conn, "vault_entries", "username", "TEXT DEFAULT ''")
    add_column(conn, "calendar_events", "recurrence", "TEXT DEFAULT ''")
    add_column(conn, "calendar_events", "recur_until", "TEXT")
    add_column(conn, "calendar_events", "caldav_uid", "TEXT")
    add_column(conn, "reminders", "notified", "BOOLEAN DEFAULT 0")
    add_column(conn, "tasks", "parent_id", "TEXT")
    add_column(conn, "tasks", "tags", "TEXT DEFAULT ''")
    add_column(conn, "tasks", "repeat", "TEXT DEFAULT ''")
    add_column(conn, "tasks", "notes", "TEXT DEFAULT ''")
    add_column(conn, "tasks", "project", "TEXT DEFAULT ''")
    add_column(conn, "tasks", "sort_order", "INTEGER DEFAULT 0")
    add_column(conn, "personas", "temperature", "REAL")
    add_column(conn, "personas", "default_mode", "TEXT DEFAULT ''")
    add_column(conn, "personas", "accent", "TEXT DEFAULT ''")
    add_column(conn, "subscriptions", "account_id", "TEXT DEFAULT ''")
    add_column(conn, "subscriptions", "last_posted_due", "TEXT DEFAULT ''")
    add_column(conn, "tasks", "completed_at", "DATETIME")
    add_column(conn, "calendar_events", "calendar_id", "TEXT DEFAULT ''")
    add_column(conn, "calendar_events", "location", "TEXT DEFAULT ''")
    add_column(conn, "calendar_events", "guests", "TEXT DEFAULT ''")
    add_column(conn, "calendar_events", "reminders", "TEXT DEFAULT '[]'")
    add_column(conn, "calendar_events", "recur_interval", "INTEGER DEFAULT 1")
    add_column(conn, "calendar_events", "recur_byday", "TEXT DEFAULT ''")
    add_column(conn, "calendar_events", "recur_count", "INTEGER")
    add_column(conn, "calendar_events", "recur_except", "TEXT DEFAULT '[]'")
    add_column(conn, "photos", "deleted_at", "DATETIME")
    # 7a - captions/keywords + hidden album
    add_column(conn, "photos", "caption", "TEXT DEFAULT ''")
    add_column(conn, "photos", "keywords", "TEXT DEFAULT ''")
    add_column(conn, "photos", "hidden", "BOOLEAN DEFAULT 0")
    # 7c - video assets
    add_column(conn, "photos", "is_video", "BOOLEAN DEFAULT 0")
    # 8a - ICS URL subscriptions
    add_column(conn, "calendar_events", "subscription_id", "VARCHAR")
    # 8b - video links (attendees/booking pages are new tables, no _add_col needed)
    add_column(conn, "calendar_events", "meeting_url", "VARCHAR DEFAULT ''")
    # 8c - contact avatar + Me card (fields/groups are new tables)
    add_column(conn, "contacts", "avatar", "VARCHAR DEFAULT ''")
    add_column(conn, "contacts", "is_me", "BOOLEAN DEFAULT 0")
    # 8d - CardDAV sync columns
    add_column(conn, "contacts", "carddav_uid", "VARCHAR DEFAULT ''")
    add_column(conn, "contacts", "carddav_href", "VARCHAR DEFAULT ''")
    add_column(conn, "contacts", "carddav_etag", "VARCHAR DEFAULT ''")
    # 9c - multi-vault: scope existing entries to the default vault
    add_column(conn, "vault_entries", "vault_id", "TEXT DEFAULT 'default'")
    add_column(conn, "vaults", "biometric_blob", "TEXT DEFAULT ''")
    add_column(conn, "webauthn_credentials", "role", "TEXT DEFAULT ''")
    # webhook hardening - signing secret + delivery status
    add_column(conn, "webhooks", "secret", "TEXT DEFAULT ''")
    add_column(conn, "webhooks", "last_status", "TEXT DEFAULT ''")
    add_column(conn, "webhooks", "last_error", "TEXT DEFAULT ''")
    add_column(conn, "webhooks", "last_triggered", "DATETIME")
    add_column(conn, "notes", "tags", "TEXT DEFAULT ''")
    add_column(conn, "notes", "items", "TEXT DEFAULT '[]'")
    add_column(conn, "notes", "due", "TEXT DEFAULT ''")
    add_column(conn, "cached_messages", "body_indexed", "BOOLEAN DEFAULT 0")
    # mail oauth (sign in with google)
    add_column(conn, "mail_accounts", "auth_type", "TEXT DEFAULT 'password'")
    add_column(conn, "mail_accounts", "oauth_provider", "TEXT DEFAULT ''")
    add_column(conn, "mail_accounts", "oauth_access_token", "TEXT DEFAULT ''")
    add_column(conn, "mail_accounts", "oauth_refresh_token", "TEXT DEFAULT ''")
    add_column(conn, "mail_accounts", "oauth_expires_at", "FLOAT DEFAULT 0")
