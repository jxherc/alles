-- late-legacy-v0: frozen synthetic migration fixture.
-- Source: commit 2983f1f, created through its legacy init_db() path.
-- Expected schema: 76 application tables and 616 columns.
-- This snapshot intentionally has no schema_migrations table.
-- All rows are synthetic, secret-free, and safe to migrate or discard.

PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

-- table: albums
CREATE TABLE albums (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	cover_id VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: api_tokens
CREATE TABLE api_tokens (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	token_hash VARCHAR NOT NULL,
	prefix VARCHAR NOT NULL,
	created_at DATETIME,
	last_used_at DATETIME,
	PRIMARY KEY (id)
);

-- table: automation_rules
CREATE TABLE automation_rules (
	id VARCHAR NOT NULL,
	name VARCHAR,
	"trigger" VARCHAR NOT NULL,
	trigger_arg VARCHAR,
	action VARCHAR NOT NULL,
	action_arg TEXT,
	enabled BOOLEAN,
	state TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: booking_pages
CREATE TABLE booking_pages (
	id VARCHAR NOT NULL,
	token VARCHAR,
	title VARCHAR,
	duration_min INTEGER,
	work_start INTEGER,
	work_end INTEGER,
	days_ahead INTEGER,
	calendar_id VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: books
CREATE TABLE books (
	id VARCHAR NOT NULL,
	title VARCHAR NOT NULL,
	author VARCHAR,
	status VARCHAR,
	rating INTEGER,
	started VARCHAR,
	finished VARCHAR,
	cover VARCHAR,
	notes TEXT,
	isbn VARCHAR,
	year INTEGER,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: cached_messages
CREATE TABLE cached_messages (
	id VARCHAR NOT NULL,
	account_id VARCHAR NOT NULL,
	folder VARCHAR,
	uid VARCHAR NOT NULL,
	sender TEXT,
	subject TEXT,
	date VARCHAR,
	date_ts FLOAT,
	seen BOOLEAN,
	flagged BOOLEAN,
	list_unsubscribe TEXT,
	muted BOOLEAN,
	snoozed_until VARCHAR,
	labels TEXT,
	body_indexed BOOLEAN,
	cached_at DATETIME,
	PRIMARY KEY (id)
);

-- table: calendar_events
CREATE TABLE calendar_events (
	id VARCHAR NOT NULL,
	calendar_id VARCHAR,
	title VARCHAR NOT NULL,
	description TEXT,
	location VARCHAR,
	guests TEXT,
	start_dt VARCHAR NOT NULL,
	end_dt VARCHAR,
	all_day BOOLEAN,
	color VARCHAR,
	reminders TEXT,
	recurrence VARCHAR,
	recur_interval INTEGER,
	recur_byday VARCHAR,
	recur_count INTEGER,
	recur_until VARCHAR,
	recur_except TEXT,
	caldav_uid VARCHAR,
	subscription_id VARCHAR,
	meeting_url VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: calendar_subscriptions
CREATE TABLE calendar_subscriptions (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	url VARCHAR NOT NULL,
	calendar_id VARCHAR,
	last_synced VARCHAR,
	last_status VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: calendars
CREATE TABLE calendars (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	color VARCHAR,
	visible BOOLEAN,
	is_default BOOLEAN,
	sort_order INTEGER,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: connections
CREATE TABLE connections (
	id VARCHAR NOT NULL,
	service VARCHAR NOT NULL,
	token TEXT,
	meta TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: contact_fields
CREATE TABLE contact_fields (
	id VARCHAR NOT NULL,
	contact_id VARCHAR NOT NULL,
	kind VARCHAR,
	label VARCHAR,
	value TEXT,
	sort_order INTEGER,
	PRIMARY KEY (id)
);

-- table: contact_group_members
CREATE TABLE contact_group_members (
	id VARCHAR NOT NULL,
	group_id VARCHAR NOT NULL,
	contact_id VARCHAR NOT NULL,
	PRIMARY KEY (id)
);

-- table: contact_groups
CREATE TABLE contact_groups (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	smart BOOLEAN,
	rule_tag VARCHAR,
	rule_company VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: contacts
CREATE TABLE contacts (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	email VARCHAR,
	phone VARCHAR,
	notes TEXT,
	tags TEXT,
	company VARCHAR,
	title VARCHAR,
	address TEXT,
	birthday VARCHAR,
	website VARCHAR,
	favorite BOOLEAN,
	avatar VARCHAR,
	is_me BOOLEAN,
	carddav_uid VARCHAR,
	carddav_href VARCHAR,
	carddav_etag VARCHAR,
	created_at DATETIME,
	updated_at DATETIME,
	PRIMARY KEY (id)
);

-- table: cookbook
CREATE TABLE cookbook (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	description VARCHAR,
	prompt TEXT NOT NULL,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: day_events
CREATE TABLE day_events (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	date VARCHAR NOT NULL,
	repeat VARCHAR,
	category VARCHAR,
	notes TEXT,
	pinned BOOLEAN,
	notify_days INTEGER,
	last_notified VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: doc_comments
CREATE TABLE doc_comments (
	id VARCHAR NOT NULL,
	doc VARCHAR NOT NULL,
	anchor TEXT,
	body TEXT,
	author VARCHAR,
	parent_id VARCHAR,
	resolved BOOLEAN,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: doc_revisions
CREATE TABLE doc_revisions (
	id VARCHAR NOT NULL,
	path VARCHAR NOT NULL,
	content TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: event_attendees
CREATE TABLE event_attendees (
	id VARCHAR NOT NULL,
	event_id VARCHAR NOT NULL,
	name VARCHAR,
	email VARCHAR,
	status VARCHAR,
	token VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: file_comments
CREATE TABLE file_comments (
	id VARCHAR NOT NULL,
	path VARCHAR NOT NULL,
	body TEXT,
	author VARCHAR,
	parent_id VARCHAR,
	resolved BOOLEAN,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: file_tags
CREATE TABLE file_tags (
	id VARCHAR NOT NULL,
	path VARCHAR,
	tags VARCHAR,
	color VARCHAR,
	starred BOOLEAN,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: file_versions
CREATE TABLE file_versions (
	id VARCHAR NOT NULL,
	path VARCHAR NOT NULL,
	sha VARCHAR,
	size INTEGER,
	stored VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: gallery_images
CREATE TABLE gallery_images (
	id VARCHAR NOT NULL,
	filename VARCHAR NOT NULL,
	prompt TEXT,
	tags TEXT,
	source VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: habit_logs
CREATE TABLE habit_logs (
	id INTEGER NOT NULL,
	habit_id VARCHAR,
	date VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: habits
CREATE TABLE habits (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	icon VARCHAR,
	color VARCHAR,
	cadence VARCHAR,
	target INTEGER,
	created_at DATETIME,
	archived BOOLEAN,
	PRIMARY KEY (id)
);

-- table: health_entries
CREATE TABLE health_entries (
	id INTEGER NOT NULL,
	kind VARCHAR,
	date VARCHAR,
	value FLOAT,
	unit VARCHAR,
	note VARCHAR,
	label VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: index_chunks
CREATE TABLE index_chunks (
	id VARCHAR NOT NULL,
	kind VARCHAR NOT NULL,
	ref VARCHAR NOT NULL,
	chunk_no INTEGER,
	text TEXT,
	vec TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: journal_entries
CREATE TABLE journal_entries (
	id VARCHAR NOT NULL,
	date VARCHAR,
	content TEXT,
	mood VARCHAR,
	tags VARCHAR,
	created_at DATETIME,
	updated_at DATETIME,
	PRIMARY KEY (id)
);

-- table: mail_accounts
CREATE TABLE mail_accounts (
	id VARCHAR NOT NULL,
	name VARCHAR,
	email VARCHAR,
	imap_host VARCHAR,
	imap_port INTEGER,
	smtp_host VARCHAR,
	smtp_port INTEGER,
	username VARCHAR,
	password TEXT,
	use_ssl BOOLEAN,
	auth_type VARCHAR,
	oauth_provider VARCHAR,
	oauth_access_token TEXT,
	oauth_refresh_token TEXT,
	oauth_expires_at FLOAT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: mail_drafts
CREATE TABLE mail_drafts (
	id VARCHAR NOT NULL,
	account_id VARCHAR,
	"to" TEXT,
	cc TEXT,
	bcc TEXT,
	subject TEXT,
	body TEXT,
	in_reply_to VARCHAR,
	"references" TEXT,
	updated_at DATETIME,
	PRIMARY KEY (id)
);

-- table: mail_rules
CREATE TABLE mail_rules (
	id VARCHAR NOT NULL,
	match_field VARCHAR,
	match_value VARCHAR,
	action VARCHAR,
	action_arg VARCHAR,
	enabled BOOLEAN,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: mail_saved_searches
CREATE TABLE mail_saved_searches (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	"query" TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: mail_scheduled
CREATE TABLE mail_scheduled (
	id VARCHAR NOT NULL,
	account_id VARCHAR NOT NULL,
	"to" TEXT,
	cc TEXT,
	bcc TEXT,
	subject TEXT,
	body TEXT,
	html TEXT,
	in_reply_to VARCHAR,
	"references" VARCHAR,
	send_at VARCHAR,
	status VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: mcp_servers
CREATE TABLE mcp_servers (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	transport VARCHAR,
	command VARCHAR,
	args TEXT,
	url VARCHAR,
	enabled BOOLEAN,
	disabled_tools TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: memories
CREATE TABLE memories (
	id VARCHAR NOT NULL,
	text TEXT NOT NULL,
	category VARCHAR,
	source VARCHAR,
	session_id VARCHAR,
	pinned BOOLEAN,
	timestamp DATETIME,
	PRIMARY KEY (id)
);

-- table: messages
CREATE TABLE messages (
	id VARCHAR NOT NULL,
	session_id VARCHAR NOT NULL,
	role VARCHAR NOT NULL,
	content TEXT,
	meta TEXT,
	timestamp DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE
);

-- table: model_endpoints
CREATE TABLE model_endpoints (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	base_url VARCHAR NOT NULL,
	api_key TEXT,
	enabled BOOLEAN,
	cached_models TEXT,
	vision_models TEXT,
	image_models TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: model_votes
CREATE TABLE model_votes (
	id VARCHAR NOT NULL,
	winner VARCHAR NOT NULL,
	loser VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: money_accounts
CREATE TABLE money_accounts (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	kind VARCHAR,
	currency VARCHAR,
	opening FLOAT,
	color VARCHAR,
	archived BOOLEAN,
	low_balance FLOAT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: money_assignments
CREATE TABLE money_assignments (
	id VARCHAR NOT NULL,
	category VARCHAR NOT NULL,
	month VARCHAR NOT NULL,
	assigned FLOAT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: money_budgets
CREATE TABLE money_budgets (
	id VARCHAR NOT NULL,
	category VARCHAR NOT NULL,
	limit_amt FLOAT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: money_category_rules
CREATE TABLE money_category_rules (
	id VARCHAR NOT NULL,
	"match" VARCHAR NOT NULL,
	category VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: money_goals
CREATE TABLE money_goals (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	kind VARCHAR,
	target FLOAT,
	current FLOAT,
	monthly FLOAT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: money_holdings
CREATE TABLE money_holdings (
	id VARCHAR NOT NULL,
	symbol VARCHAR NOT NULL,
	name VARCHAR,
	qty FLOAT,
	cost_basis FLOAT,
	price FLOAT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: money_recurring
CREATE TABLE money_recurring (
	id VARCHAR NOT NULL,
	account_id VARCHAR,
	amount FLOAT,
	category VARCHAR,
	payee VARCHAR,
	notes TEXT,
	cycle VARCHAR,
	cycle_days INTEGER,
	next_date VARCHAR,
	active BOOLEAN,
	last_posted VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(account_id) REFERENCES money_accounts (id) ON DELETE CASCADE
);

-- table: money_targets
CREATE TABLE money_targets (
	id VARCHAR NOT NULL,
	category VARCHAR NOT NULL,
	amount FLOAT,
	target_date VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id),
	UNIQUE (category)
);

-- table: money_transactions
CREATE TABLE money_transactions (
	id VARCHAR NOT NULL,
	account_id VARCHAR,
	date VARCHAR NOT NULL,
	amount FLOAT,
	category VARCHAR,
	payee VARCHAR,
	notes TEXT,
	transfer_id VARCHAR,
	tags TEXT,
	receipt_id VARCHAR,
	cleared BOOLEAN,
	created_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(account_id) REFERENCES money_accounts (id) ON DELETE CASCADE
);

-- table: money_txn_splits
CREATE TABLE money_txn_splits (
	id VARCHAR NOT NULL,
	txn_id VARCHAR,
	category VARCHAR,
	amount FLOAT,
	created_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(txn_id) REFERENCES money_transactions (id) ON DELETE CASCADE
);

-- table: money_watches
CREATE TABLE money_watches (
	id VARCHAR NOT NULL,
	kind VARCHAR,
	value VARCHAR NOT NULL,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: monitor_checks
CREATE TABLE monitor_checks (
	id INTEGER NOT NULL,
	monitor_id VARCHAR,
	ts DATETIME,
	ok BOOLEAN,
	status_code INTEGER,
	latency_ms INTEGER,
	error VARCHAR,
	detail VARCHAR,
	PRIMARY KEY (id)
);

-- table: monitors
CREATE TABLE monitors (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	url VARCHAR NOT NULL,
	kind VARCHAR,
	interval_secs INTEGER,
	expect_status INTEGER,
	expect_keyword VARCHAR,
	latency_ceiling_ms INTEGER,
	enabled BOOLEAN,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: notes
CREATE TABLE notes (
	id VARCHAR NOT NULL,
	title VARCHAR,
	content TEXT,
	pinned BOOLEAN,
	archived BOOLEAN,
	tags VARCHAR,
	items TEXT,
	due VARCHAR,
	created_at DATETIME,
	updated_at DATETIME,
	PRIMARY KEY (id)
);

-- table: persona_docs
CREATE TABLE persona_docs (
	id VARCHAR NOT NULL,
	persona_id VARCHAR NOT NULL,
	title VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: personas
CREATE TABLE personas (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	emoji VARCHAR,
	system_prompt TEXT,
	model VARCHAR,
	temperature FLOAT,
	default_mode VARCHAR,
	accent VARCHAR,
	initial_message TEXT,
	is_default BOOLEAN,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: photos
CREATE TABLE photos (
	id VARCHAR NOT NULL,
	filename VARCHAR NOT NULL,
	thumb VARCHAR,
	original_name VARCHAR,
	album_id VARCHAR,
	width INTEGER,
	height INTEGER,
	taken_at DATETIME,
	exif TEXT,
	favorite BOOLEAN,
	caption TEXT,
	keywords VARCHAR,
	hidden BOOLEAN,
	is_video BOOLEAN,
	deleted_at DATETIME,
	created_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(album_id) REFERENCES albums (id) ON DELETE SET NULL
);

-- table: proactive_items
CREATE TABLE proactive_items (
	id VARCHAR NOT NULL,
	dedupe_key VARCHAR NOT NULL,
	category VARCHAR,
	title VARCHAR NOT NULL,
	body TEXT,
	link VARCHAR,
	score INTEGER,
	urgency INTEGER,
	source_keys TEXT,
	status VARCHAR,
	dismissed BOOLEAN,
	pushed BOOLEAN,
	created_at DATETIME,
	updated_at DATETIME,
	PRIMARY KEY (id)
);

-- table: proactive_state
CREATE TABLE proactive_state (
	id VARCHAR NOT NULL,
	seen_keys TEXT,
	updated_at DATETIME,
	PRIMARY KEY (id)
);

-- table: projects
CREATE TABLE projects (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	description TEXT,
	system_prompt TEXT,
	working_dir TEXT,
	color VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: push_subscriptions
CREATE TABLE push_subscriptions (
	id VARCHAR NOT NULL,
	endpoint TEXT NOT NULL,
	p256dh VARCHAR,
	auth VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id),
	UNIQUE (endpoint)
);

-- table: read_feeds
CREATE TABLE read_feeds (
	id VARCHAR NOT NULL,
	url VARCHAR NOT NULL,
	title VARCHAR,
	last_checked DATETIME,
	created_at DATETIME,
	PRIMARY KEY (id),
	UNIQUE (url)
);

-- table: read_items
CREATE TABLE read_items (
	id VARCHAR NOT NULL,
	url VARCHAR NOT NULL,
	title VARCHAR,
	text TEXT,
	excerpt VARCHAR,
	site VARCHAR,
	image VARCHAR,
	read_minutes INTEGER,
	added_at DATETIME,
	read_at VARCHAR,
	fav BOOLEAN,
	archived BOOLEAN,
	tags VARCHAR,
	PRIMARY KEY (id)
);

-- table: reminders
CREATE TABLE reminders (
	id VARCHAR NOT NULL,
	text TEXT NOT NULL,
	trigger_at DATETIME NOT NULL,
	type VARCHAR,
	session_id VARCHAR,
	fired BOOLEAN,
	notified BOOLEAN,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: sessions
CREATE TABLE sessions (
	id VARCHAR NOT NULL,
	name VARCHAR,
	model VARCHAR,
	endpoint_id VARCHAR,
	mode VARCHAR,
	persona_id VARCHAR,
	project_id VARCHAR,
	working_dir TEXT,
	starred BOOLEAN,
	archived BOOLEAN,
	incognito BOOLEAN,
	share_token VARCHAR,
	message_count INTEGER,
	created_at DATETIME,
	last_message_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(endpoint_id) REFERENCES model_endpoints (id) ON DELETE SET NULL,
	FOREIGN KEY(persona_id) REFERENCES personas (id) ON DELETE SET NULL,
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE SET NULL
);

-- table: shares
CREATE TABLE shares (
	id VARCHAR NOT NULL,
	token VARCHAR NOT NULL,
	kind VARCHAR NOT NULL,
	ref VARCHAR NOT NULL,
	level VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: sub_payments
CREATE TABLE sub_payments (
	id VARCHAR NOT NULL,
	sub_id VARCHAR NOT NULL,
	date VARCHAR NOT NULL,
	amount FLOAT,
	txn_id VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: sub_price_changes
CREATE TABLE sub_price_changes (
	id VARCHAR NOT NULL,
	sub_id VARCHAR NOT NULL,
	old_price FLOAT,
	new_price FLOAT,
	date VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: subscriptions
CREATE TABLE subscriptions (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	price FLOAT,
	currency VARCHAR,
	cycle VARCHAR,
	cycle_days INTEGER,
	next_due VARCHAR NOT NULL,
	category VARCHAR,
	url VARCHAR,
	notes TEXT,
	active BOOLEAN,
	remind_days INTEGER,
	last_notified_due VARCHAR,
	account_id VARCHAR,
	last_posted_due VARCHAR,
	trial_end VARCHAR,
	cancel_url VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: tasks
CREATE TABLE tasks (
	id VARCHAR NOT NULL,
	title VARCHAR NOT NULL,
	done BOOLEAN,
	priority INTEGER,
	due_date VARCHAR,
	parent_id VARCHAR,
	tags VARCHAR,
	repeat VARCHAR,
	notes TEXT,
	project VARCHAR,
	sort_order INTEGER,
	completed_at DATETIME,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: trash_items
CREATE TABLE trash_items (
	id VARCHAR NOT NULL,
	kind VARCHAR NOT NULL,
	ref VARCHAR NOT NULL,
	name VARCHAR,
	payload TEXT,
	trashed_at DATETIME,
	expires_at DATETIME,
	PRIMARY KEY (id)
);

-- table: uploads
CREATE TABLE uploads (
	id VARCHAR NOT NULL,
	filename VARCHAR NOT NULL,
	original_name VARCHAR NOT NULL,
	mime_type VARCHAR,
	size INTEGER,
	session_id VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: vault_attachments
CREATE TABLE vault_attachments (
	id VARCHAR NOT NULL,
	entry_id VARCHAR NOT NULL,
	filename VARCHAR,
	size INTEGER,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: vault_entries
CREATE TABLE vault_entries (
	id VARCHAR NOT NULL,
	vault_id VARCHAR,
	name VARCHAR NOT NULL,
	username VARCHAR,
	value_encrypted TEXT,
	category VARCHAR,
	type VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: vault_shares
CREATE TABLE vault_shares (
	id VARCHAR NOT NULL,
	token VARCHAR,
	entry_id VARCHAR NOT NULL,
	blob TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: vaults
CREATE TABLE vaults (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	verifier VARCHAR,
	travel_safe BOOLEAN,
	biometric_blob TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: webauthn_credentials
CREATE TABLE webauthn_credentials (
	id VARCHAR NOT NULL,
	vault_id VARCHAR,
	label VARCHAR,
	credential_id VARCHAR,
	public_key TEXT,
	sign_count INTEGER,
	role VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- table: webhooks
CREATE TABLE webhooks (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	url VARCHAR NOT NULL,
	events TEXT,
	enabled BOOLEAN,
	secret VARCHAR,
	last_status VARCHAR,
	last_error VARCHAR,
	last_triggered DATETIME,
	created_at DATETIME,
	PRIMARY KEY (id)
);

-- Explicit indexes created by the legacy SQLAlchemy metadata.
CREATE INDEX ix_cached_messages_account_id ON cached_messages (account_id);
CREATE INDEX ix_cached_messages_folder ON cached_messages (folder);
CREATE INDEX ix_doc_comments_doc ON doc_comments (doc);
CREATE INDEX ix_doc_comments_parent_id ON doc_comments (parent_id);
CREATE INDEX ix_doc_revisions_path ON doc_revisions (path);
CREATE INDEX ix_file_comments_parent_id ON file_comments (parent_id);
CREATE INDEX ix_file_comments_path ON file_comments (path);
CREATE UNIQUE INDEX ix_file_tags_path ON file_tags (path);
CREATE INDEX ix_file_versions_path ON file_versions (path);
CREATE INDEX ix_habit_logs_date ON habit_logs (date);
CREATE INDEX ix_habit_logs_habit_id ON habit_logs (habit_id);
CREATE INDEX ix_health_entries_date ON health_entries (date);
CREATE INDEX ix_health_entries_kind ON health_entries (kind);
CREATE INDEX ix_index_chunks_kind ON index_chunks (kind);
CREATE INDEX ix_index_chunks_ref ON index_chunks (ref);
CREATE UNIQUE INDEX ix_journal_entries_date ON journal_entries (date);
CREATE INDEX ix_mail_drafts_account_id ON mail_drafts (account_id);
CREATE INDEX ix_mail_scheduled_account_id ON mail_scheduled (account_id);
CREATE INDEX ix_money_assignments_category ON money_assignments (category);
CREATE INDEX ix_money_assignments_month ON money_assignments (month);
CREATE INDEX ix_money_txn_splits_txn_id ON money_txn_splits (txn_id);
CREATE INDEX ix_monitor_checks_monitor_id ON monitor_checks (monitor_id);
CREATE INDEX ix_persona_docs_persona_id ON persona_docs (persona_id);
CREATE INDEX ix_proactive_items_dedupe_key ON proactive_items (dedupe_key);
CREATE UNIQUE INDEX ix_shares_token ON shares (token);
CREATE INDEX ix_sub_payments_sub_id ON sub_payments (sub_id);
CREATE INDEX ix_sub_price_changes_sub_id ON sub_price_changes (sub_id);
CREATE INDEX ix_trash_items_kind ON trash_items (kind);

-- Synthetic note, task, chat, mail, and photo records.
INSERT INTO notes (id, title, content, pinned, archived, tags, items, due, created_at, updated_at)
VALUES ('fixture-note-legacy', 'Legacy fixture note', 'Synthetic note body for migration testing.', 0, 0, 'fixture,migration', '[{"text":"verify migration","done":false}]', '2026-01-15', '2026-01-02 03:04:05', '2026-01-02 03:04:05');

INSERT INTO tasks (id, title, done, priority, due_date, parent_id, tags, repeat, notes, project, sort_order, completed_at, created_at)
VALUES ('fixture-task-legacy', 'Verify the legacy migration', 0, 1, '2026-01-15', NULL, 'fixture,migration', '', 'Synthetic task row.', '', 0, NULL, '2026-01-02 03:04:05');

INSERT INTO sessions (id, name, model, endpoint_id, mode, persona_id, project_id, working_dir, starred, archived, incognito, share_token, message_count, created_at, last_message_at)
VALUES ('fixture-session-legacy', 'Legacy fixture chat', 'fixture-model', NULL, 'chat', NULL, NULL, '', 0, 0, 0, NULL, 1, '2026-01-02 03:04:05', '2026-01-02 03:05:00');
INSERT INTO messages (id, session_id, role, content, meta, timestamp)
VALUES ('fixture-message-legacy', 'fixture-session-legacy', 'user', 'Synthetic chat message for migration testing.', '{}', '2026-01-02 03:05:00');

INSERT INTO mail_accounts (id, name, email, imap_host, imap_port, smtp_host, smtp_port, username, password, use_ssl, auth_type, oauth_provider, oauth_access_token, oauth_refresh_token, oauth_expires_at, created_at)
VALUES ('fixture-mail-account', 'Fixture Mail', 'owner@example.invalid', 'imap.example.invalid', 993, 'smtp.example.invalid', 465, 'owner@example.invalid', '', 1, 'password', '', '', '', 0, '2026-01-02 03:04:05');
INSERT INTO cached_messages (id, account_id, folder, uid, sender, subject, date, date_ts, seen, flagged, list_unsubscribe, muted, snoozed_until, labels, body_indexed, cached_at)
VALUES ('fixture-mail-message', 'fixture-mail-account', 'INBOX', '1001', 'sender@example.invalid', 'Synthetic migration message', '2026-01-02', 1767323045, 0, 0, '', 0, '', 'fixture', 0, '2026-01-02 03:06:00');

INSERT INTO albums (id, name, cover_id, created_at)
VALUES ('fixture-album-legacy', 'Fixture album', NULL, '2026-01-02 03:04:05');
INSERT INTO photos (id, filename, thumb, original_name, album_id, width, height, taken_at, exif, favorite, caption, keywords, hidden, is_video, deleted_at, created_at)
VALUES ('fixture-photo-legacy', 'fixture-photo.jpg', '', 'fixture-photo.jpg', 'fixture-album-legacy', 1600, 1200, '2026-01-02 03:07:00', '{}', 0, 'Synthetic fixture photo', 'fixture,migration', 0, 0, NULL, '2026-01-02 03:07:00');

COMMIT;
