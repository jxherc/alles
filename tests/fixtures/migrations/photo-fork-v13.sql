-- Frozen, synthetic, secret-free migration fixture. Do not regenerate from a live database.
-- Source: Alles commit 9c7f6575b3307141fa2efc31887dac6e1ce5cca1 (Photos fork through legacy migration v13/photo_faces).
-- Expected schema: 90 application tables, 717 columns, 47 explicit indexes.
-- Expected history: 13 rows; legacy Photos fork occupies versions 9 through 13.
-- Synthetic survival rows: notes=1, mail_accounts=1, cached_messages=1, photos=1.
-- Reserved domains use example.invalid; all credentials and tokens are empty.
BEGIN TRANSACTION;
CREATE TABLE albums (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	cover_id VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE api_tokens (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	token_hash VARCHAR NOT NULL,
	prefix VARCHAR NOT NULL,
	created_at DATETIME,
	last_used_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE attachments (
	id VARCHAR NOT NULL,
	resource_kind VARCHAR,
	resource_id VARCHAR,
	blob_id VARCHAR NOT NULL,
	meta TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE blobs (
	id VARCHAR NOT NULL,
	sha256 VARCHAR NOT NULL,
	size INTEGER,
	mime VARCHAR,
	refcount INTEGER,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
	autoreplied BOOLEAN,
	message_id VARCHAR,
	in_reply_to VARCHAR,
	"references" TEXT,
	thread_id VARCHAR,
	body_indexed BOOLEAN,
	cached_at DATETIME,
	PRIMARY KEY (id)
);
INSERT INTO "cached_messages" VALUES('fixture-mail-message-v13','fixture-mail-account-v13','INBOX','fixture-uid-1','Sender <sender@example.invalid>','Synthetic migration message','2026-06-30T00:00:00Z',1782777600.0,0,1,'',0,'','fixture,migration',0,'<fixture-message-v13@example.invalid>','','','fixture-thread-v13',0,'2026-06-30 00:00:00');
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
CREATE TABLE connections (
	id VARCHAR NOT NULL,
	service VARCHAR NOT NULL,
	token TEXT,
	meta TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE contact_fields (
	id VARCHAR NOT NULL,
	contact_id VARCHAR NOT NULL,
	kind VARCHAR,
	label VARCHAR,
	value TEXT,
	sort_order INTEGER,
	PRIMARY KEY (id)
);
CREATE TABLE contact_group_members (
	id VARCHAR NOT NULL,
	group_id VARCHAR NOT NULL,
	contact_id VARCHAR NOT NULL,
	PRIMARY KEY (id)
);
CREATE TABLE contact_groups (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	smart BOOLEAN,
	rule_tag VARCHAR,
	rule_company VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE contact_links (
	id VARCHAR NOT NULL,
	from_id VARCHAR NOT NULL,
	to_id VARCHAR NOT NULL,
	kind VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE cookbook (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	description VARCHAR,
	prompt TEXT NOT NULL,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE doc_revisions (
	id VARCHAR NOT NULL,
	path VARCHAR NOT NULL,
	content TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE faces (
	id VARCHAR NOT NULL,
	photo_id VARCHAR NOT NULL,
	person_id VARCHAR,
	bbox VARCHAR,
	det_score FLOAT,
	embedding BLOB,
	created_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(photo_id) REFERENCES photos (id) ON DELETE CASCADE,
	FOREIGN KEY(person_id) REFERENCES people (id) ON DELETE SET NULL
);
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
CREATE TABLE file_tags (
	id VARCHAR NOT NULL,
	path VARCHAR,
	tags VARCHAR,
	color VARCHAR,
	starred BOOLEAN,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE file_versions (
	id VARCHAR NOT NULL,
	path VARCHAR NOT NULL,
	sha VARCHAR,
	size INTEGER,
	stored VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE gallery_images (
	id VARCHAR NOT NULL,
	filename VARCHAR NOT NULL,
	prompt TEXT,
	tags TEXT,
	source VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE habit_logs (
	id INTEGER NOT NULL,
	habit_id VARCHAR,
	date VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE insights (
	id VARCHAR NOT NULL,
	kind VARCHAR,
	title VARCHAR NOT NULL,
	body TEXT,
	evidence TEXT,
	dedupe_key VARCHAR,
	pinned BOOLEAN,
	dismissed BOOLEAN,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
INSERT INTO "mail_accounts" VALUES('fixture-mail-account-v13','Synthetic Mail','fixture@example.invalid','imap.example.invalid',993,'smtp.example.invalid',465,'fixture@example.invalid','',1,'password','','','',0.0,'2026-06-30 00:00:00');
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
CREATE TABLE mail_saved_searches (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	"query" TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE memories (
	id VARCHAR NOT NULL,
	text TEXT NOT NULL,
	category VARCHAR,
	source VARCHAR,
	session_id VARCHAR,
	pinned BOOLEAN,
	timestamp DATETIME,
	confidence FLOAT,
	vetoed BOOLEAN,
	provenance VARCHAR,
	PRIMARY KEY (id)
);
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
CREATE TABLE model_votes (
	id VARCHAR NOT NULL,
	winner VARCHAR NOT NULL,
	loser VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE money_assignments (
	id VARCHAR NOT NULL,
	category VARCHAR NOT NULL,
	month VARCHAR NOT NULL,
	assigned FLOAT,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE money_budgets (
	id VARCHAR NOT NULL,
	category VARCHAR NOT NULL,
	tag VARCHAR,
	limit_amt FLOAT,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE money_category_rules (
	id VARCHAR NOT NULL,
	"match" VARCHAR NOT NULL,
	category VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE money_price_history (
	id VARCHAR NOT NULL,
	symbol VARCHAR NOT NULL,
	price FLOAT,
	ts DATETIME,
	PRIMARY KEY (id)
);
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
	anchor_day INTEGER,
	active BOOLEAN,
	last_posted VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(account_id) REFERENCES money_accounts (id) ON DELETE CASCADE
);
CREATE TABLE money_tag_rules (
	id VARCHAR NOT NULL,
	"match" VARCHAR NOT NULL,
	tags VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE money_targets (
	id VARCHAR NOT NULL,
	category VARCHAR NOT NULL,
	amount FLOAT,
	target_date VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id),
	UNIQUE (category)
);
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
CREATE TABLE money_txn_splits (
	id VARCHAR NOT NULL,
	txn_id VARCHAR,
	category VARCHAR,
	amount FLOAT,
	created_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(txn_id) REFERENCES money_transactions (id) ON DELETE CASCADE
);
CREATE TABLE money_watches (
	id VARCHAR NOT NULL,
	kind VARCHAR,
	value VARCHAR NOT NULL,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE mutation_events (
	id VARCHAR NOT NULL,
	entity_kind VARCHAR NOT NULL,
	entity_id VARCHAR,
	op VARCHAR NOT NULL,
	fields TEXT,
	actor VARCHAR,
	ts DATETIME,
	PRIMARY KEY (id)
);
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
INSERT INTO "notes" VALUES('fixture-note-v13','Synthetic migration note','This is secret-free fixture content used only to verify migration survival.',1,0,'fixture,migration','[{"text":"verify note survives","done":false}]','2026-07-01','2026-06-30 00:00:00','2026-06-30 00:00:00');
CREATE TABLE people (
	id VARCHAR NOT NULL,
	name VARCHAR,
	cover_face_id VARCHAR,
	hidden BOOLEAN,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE persona_docs (
	id VARCHAR NOT NULL,
	persona_id VARCHAR NOT NULL,
	title VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE personas (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	emoji VARCHAR,
	system_prompt TEXT,
	model VARCHAR,
	temperature FLOAT,
	default_mode VARCHAR,
	blocked_scopes VARCHAR,
	blocked_tools VARCHAR,
	accent VARCHAR,
	initial_message TEXT,
	is_default BOOLEAN,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
	archived BOOLEAN,
	is_video BOOLEAN,
	deleted_at DATETIME,
	created_at DATETIME,
	aspect_ratio FLOAT,
	preview TEXT,
	checksum VARCHAR,
	stack_id VARCHAR,
	clip BLOB,
	faces_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(album_id) REFERENCES albums (id) ON DELETE SET NULL
);
INSERT INTO "photos" VALUES('fixture-photo-v13','fixture-photo.jpg','fixture-photo-thumb.jpg','fixture-original.jpg',NULL,4,3,'2026-06-30 00:00:00','{"camera":"synthetic"}',1,'Synthetic migration photo','fixture,migration',0,0,0,NULL,'2026-06-30 00:00:00',1.333333333333333259e+00,'data:image/jpeg;base64,','fd14bbc40527abdbf2b167683882c0e3ed2931ce5c1960e18acdbe1b5c239d35','',X'73796E7468657469632D636C69702D763133','2026-06-30 00:00:00');
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
CREATE TABLE proactive_outcomes (
	id VARCHAR NOT NULL,
	item_id VARCHAR,
	dedupe_key VARCHAR,
	category VARCHAR,
	outcome VARCHAR NOT NULL,
	latency_sec FLOAT,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE proactive_state (
	id VARCHAR NOT NULL,
	seen_keys TEXT,
	updated_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE push_subscriptions (
	id VARCHAR NOT NULL,
	endpoint TEXT NOT NULL,
	p256dh VARCHAR,
	auth VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id),
	UNIQUE (endpoint)
);
CREATE TABLE read_feeds (
	id VARCHAR NOT NULL,
	url VARCHAR NOT NULL,
	title VARCHAR,
	last_checked DATETIME,
	created_at DATETIME,
	PRIMARY KEY (id),
	UNIQUE (url)
);
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
CREATE TABLE research_findings (
	id VARCHAR NOT NULL,
	url VARCHAR,
	question TEXT,
	title VARCHAR,
	summary TEXT,
	ts DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT);
INSERT INTO "schema_migrations" VALUES(1,'baseline','2026-06-30T00:00:01');
INSERT INTO "schema_migrations" VALUES(2,'memory_distill','2026-06-30T00:00:02');
INSERT INTO "schema_migrations" VALUES(3,'budget_tag','2026-06-30T00:00:03');
INSERT INTO "schema_migrations" VALUES(4,'msg_autoreplied','2026-06-30T00:00:04');
INSERT INTO "schema_migrations" VALUES(5,'msg_threading','2026-06-30T00:00:05');
INSERT INTO "schema_migrations" VALUES(6,'persona_policy','2026-06-30T00:00:06');
INSERT INTO "schema_migrations" VALUES(7,'share_expiry_pw','2026-06-30T00:00:07');
INSERT INTO "schema_migrations" VALUES(8,'recurring_anchor_day','2026-06-30T00:00:08');
INSERT INTO "schema_migrations" VALUES(9,'photo_archive','2026-06-30T00:00:09');
INSERT INTO "schema_migrations" VALUES(10,'photo_perf','2026-06-30T00:00:10');
INSERT INTO "schema_migrations" VALUES(11,'photo_stack','2026-06-30T00:00:11');
INSERT INTO "schema_migrations" VALUES(12,'photo_clip','2026-06-30T00:00:12');
INSERT INTO "schema_migrations" VALUES(13,'photo_faces','2026-06-30T00:00:13');
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
CREATE TABLE shares (
	id VARCHAR NOT NULL,
	token VARCHAR NOT NULL,
	kind VARCHAR NOT NULL,
	ref VARCHAR NOT NULL,
	level VARCHAR,
	expires_at VARCHAR,
	password_hash VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE signal_snapshots (
	id VARCHAR NOT NULL,
	ts DATETIME,
	category VARCHAR,
	"key" VARCHAR,
	urgency INTEGER,
	data TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE sub_payments (
	id VARCHAR NOT NULL,
	sub_id VARCHAR NOT NULL,
	date VARCHAR NOT NULL,
	amount FLOAT,
	txn_id VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE sub_price_changes (
	id VARCHAR NOT NULL,
	sub_id VARCHAR NOT NULL,
	old_price FLOAT,
	new_price FLOAT,
	date VARCHAR,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE tasks (
	id VARCHAR NOT NULL,
	title VARCHAR NOT NULL,
	done BOOLEAN,
	priority INTEGER,
	due_date VARCHAR,
	parent_id VARCHAR,
	tags VARCHAR,
	repeat VARCHAR,
	anchor_day INTEGER,
	notes TEXT,
	project VARCHAR,
	sort_order INTEGER,
	completed_at DATETIME,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE tool_chains (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	steps TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE vault_attachments (
	id VARCHAR NOT NULL,
	entry_id VARCHAR NOT NULL,
	filename VARCHAR,
	size INTEGER,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE TABLE vault_shares (
	id VARCHAR NOT NULL,
	token VARCHAR,
	entry_id VARCHAR NOT NULL,
	blob TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);
CREATE TABLE vaults (
	id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	verifier VARCHAR,
	travel_safe BOOLEAN,
	biometric_blob TEXT,
	created_at DATETIME,
	PRIMARY KEY (id)
);
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
CREATE UNIQUE INDEX ix_journal_entries_date ON journal_entries (date);
CREATE INDEX ix_persona_docs_persona_id ON persona_docs (persona_id);
CREATE INDEX ix_contact_links_to_id ON contact_links (to_id);
CREATE INDEX ix_contact_links_from_id ON contact_links (from_id);
CREATE INDEX ix_research_findings_url ON research_findings (url);
CREATE INDEX ix_mail_drafts_account_id ON mail_drafts (account_id);
CREATE INDEX ix_proactive_items_dedupe_key ON proactive_items (dedupe_key);
CREATE INDEX ix_proactive_outcomes_category ON proactive_outcomes (category);
CREATE INDEX ix_proactive_outcomes_item_id ON proactive_outcomes (item_id);
CREATE INDEX ix_insights_dedupe_key ON insights (dedupe_key);
CREATE INDEX ix_signal_snapshots_category ON signal_snapshots (category);
CREATE INDEX ix_signal_snapshots_ts ON signal_snapshots (ts);
CREATE INDEX ix_mutation_events_entity_id ON mutation_events (entity_id);
CREATE INDEX ix_mutation_events_ts ON mutation_events (ts);
CREATE INDEX ix_mutation_events_entity_kind ON mutation_events (entity_kind);
CREATE UNIQUE INDEX ix_blobs_sha256 ON blobs (sha256);
CREATE INDEX ix_attachments_resource_kind ON attachments (resource_kind);
CREATE INDEX ix_attachments_resource_id ON attachments (resource_id);
CREATE INDEX ix_attachments_blob_id ON attachments (blob_id);
CREATE INDEX ix_sub_payments_sub_id ON sub_payments (sub_id);
CREATE INDEX ix_sub_price_changes_sub_id ON sub_price_changes (sub_id);
CREATE INDEX ix_money_assignments_month ON money_assignments (month);
CREATE INDEX ix_money_assignments_category ON money_assignments (category);
CREATE INDEX ix_money_price_history_symbol ON money_price_history (symbol);
CREATE UNIQUE INDEX ix_file_tags_path ON file_tags (path);
CREATE INDEX ix_doc_revisions_path ON doc_revisions (path);
CREATE INDEX ix_index_chunks_ref ON index_chunks (ref);
CREATE INDEX ix_index_chunks_kind ON index_chunks (kind);
CREATE INDEX ix_file_versions_path ON file_versions (path);
CREATE INDEX ix_trash_items_kind ON trash_items (kind);
CREATE UNIQUE INDEX ix_shares_token ON shares (token);
CREATE INDEX ix_doc_comments_parent_id ON doc_comments (parent_id);
CREATE INDEX ix_doc_comments_doc ON doc_comments (doc);
CREATE INDEX ix_file_comments_parent_id ON file_comments (parent_id);
CREATE INDEX ix_file_comments_path ON file_comments (path);
CREATE INDEX ix_cached_messages_folder ON cached_messages (folder);
CREATE INDEX ix_cached_messages_account_id ON cached_messages (account_id);
CREATE INDEX ix_cached_messages_thread_id ON cached_messages (thread_id);
CREATE INDEX ix_mail_scheduled_account_id ON mail_scheduled (account_id);
CREATE INDEX ix_monitor_checks_monitor_id ON monitor_checks (monitor_id);
CREATE INDEX ix_habit_logs_habit_id ON habit_logs (habit_id);
CREATE INDEX ix_habit_logs_date ON habit_logs (date);
CREATE INDEX ix_health_entries_date ON health_entries (date);
CREATE INDEX ix_health_entries_kind ON health_entries (kind);
CREATE INDEX ix_faces_photo_id ON faces (photo_id);
CREATE INDEX ix_faces_person_id ON faces (person_id);
CREATE INDEX ix_money_txn_splits_txn_id ON money_txn_splits (txn_id);
COMMIT;
