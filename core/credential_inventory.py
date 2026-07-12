"""Canonical fields protected by the machine-local credential keyring."""

DATABASE_CREDENTIAL_FIELDS = (
    ("model_endpoints", "api_key", "model_endpoints.api_key"),
    ("mail_accounts", "password", "mail_accounts.password"),
    ("mail_accounts", "oauth_access_token", "mail_accounts.oauth_access_token"),
    ("mail_accounts", "oauth_refresh_token", "mail_accounts.oauth_refresh_token"),
    ("webhooks", "secret", "webhooks.secret"),
    ("push_subscriptions", "auth", "push_subscriptions.auth"),
    ("connections", "token", "connections.token"),
    ("connections", "meta", "connections.meta"),
    ("mcp_servers", "args", "mcp_servers.args"),
    ("mcp_servers", "url", "mcp_servers.url"),
    ("mcp_servers", "env", "mcp_servers.env"),
    ("mcp_servers", "headers", "mcp_servers.headers"),
)

SETTING_CREDENTIAL_KEYS = (
    "brave_api_key",
    "google_pse_api_key",
    "mail_oauth_client_secret",
    "notify_discord_webhook",
    "notify_telegram_chat_id",
    "notify_telegram_token",
    "openai_api_key",
    "outbound_proxy",
    "searxng_url",
    "serper_api_key",
    "tavily_api_key",
)

CONFIG_CREDENTIAL_FIELDS = (
    ("caldav.json", "password", "caldav.password"),
    ("carddav.json", "password", "carddav.password"),
    ("webdav_backup.json", "password", "backup.webdav.password"),
)
