from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from core.schema.base import Base, EncryptedText, _now, _uid


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
    # due date, or pending:/uncertain: delivery claim
    last_notified_due = Column(String, default="")
    account_id = Column(String, default="")  # money account to auto-post the charge to (optional)
    last_posted_due = Column(String, default="")  # due date we already posted a txn for
    trial_end = Column(String, default="")  # ISO date a free trial ends / cancel-by
    cancel_url = Column(String, default="")  # explicit "how to cancel" link / steps (4e)
    created_at = Column(DateTime, default=_now)
    # Phase 8 additive currency provenance. The legacy price/currency columns
    # remain the source until the Actual cutover gate passes.
    original_price_text = Column(String, default="")
    original_currency_code = Column(String, default="")
    base_price_text = Column(String, default="")
    base_currency_code = Column(String, default="")
    fx_rate_text = Column(String, default="")
    fx_rate_date = Column(String, default="")
    fx_source = Column(String, default="")


class SubPayment(Base):
    # one row per time a subscription was marked paid — drives history + undo
    __tablename__ = "sub_payments"
    id = Column(String, primary_key=True, default=_uid)
    sub_id = Column(String, index=True, nullable=False)
    date = Column(String, nullable=False)  # the due/cycle date that was paid (ISO)
    amount = Column(Float, default=0.0)
    txn_id = Column(String, default="")  # linked money transaction, if posted (for undo)
    created_at = Column(DateTime, default=_now)
    original_amount_text = Column(String, default="")
    original_currency_code = Column(String, default="")
    base_amount_text = Column(String, default="")
    base_currency_code = Column(String, default="")
    fx_rate_text = Column(String, default="")
    fx_rate_date = Column(String, default="")
    fx_source = Column(String, default="")


class SubPriceChange(Base):
    # recorded whenever a sub's price changes — drives price-history + hike flag
    __tablename__ = "sub_price_changes"
    id = Column(String, primary_key=True, default=_uid)
    sub_id = Column(String, index=True, nullable=False)
    old_price = Column(Float, default=0.0)
    new_price = Column(Float, default=0.0)
    date = Column(String, default="")  # ISO date of the change
    created_at = Column(DateTime, default=_now)


class FinanceCreateReceipt(Base):
    """One local create acknowledgment, committed atomically with its ledger change."""

    __tablename__ = "finance_create_receipts"
    id = Column(String, primary_key=True)  # operation + caller UUID
    payload_hash = Column(String(64), nullable=False)
    resource_id = Column(String, nullable=False, default="", index=True)
    response_json = Column(Text, nullable=False, default="")
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
    currency_code = Column(String, default="")
    base_currency_code = Column(String, default="")
    original_opening_text = Column(String, default="")
    base_opening_text = Column(String, default="")
    opening_fx_rate_text = Column(String, default="")
    opening_fx_rate_date = Column(String, default="")
    opening_fx_source = Column(String, default="")


class Transaction(Base):
    __tablename__ = "money_transactions"
    __table_args__ = (
        Index(
            "uq_money_transactions_import_identity",
            "import_identity",
            unique=True,
            sqlite_where=text("import_identity <> ''"),
        ),
    )
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
    original_amount_text = Column(String, default="")
    original_currency_code = Column(String, default="")
    base_amount_text = Column(String, default="")
    base_currency_code = Column(String, default="")
    fx_rate_text = Column(String, default="")
    fx_rate_date = Column(String, default="")
    fx_source = Column(String, default="")
    import_identity = Column(String, default="")
    import_batch_id = Column(String, default="")
    import_source = Column(String, default="")
    import_row_number = Column(Integer, default=0)
    import_receipt_json = Column(Text, default="{}")


class MoneyFxEvidence(Base):
    __tablename__ = "money_fx_evidence"
    id = Column(String, primary_key=True, default=_uid)
    transaction_id = Column(
        String,
        ForeignKey("money_transactions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    original_amount_text = Column(String, nullable=False)
    original_currency_code = Column(String, nullable=False)
    base_amount_text = Column(String, nullable=False)
    base_currency_code = Column(String, nullable=False)
    rate_text = Column(String, nullable=False)
    rate_date = Column(String, default="")
    source = Column(String, nullable=False)
    source_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)


class FinanceImportBatch(Base):
    __tablename__ = "finance_import_batches"
    id = Column(String, primary_key=True, default=_uid)
    # A receipt may belong to an Actual-native account, which has no legacy
    # money_accounts row. Keep the durable canonical owner ID without an FK.
    account_id = Column(String, nullable=False)
    profile = Column(String, nullable=False)
    source_name = Column(String, nullable=False)
    source_sha256 = Column(String, nullable=False, index=True)
    original_currency_code = Column(String, default="")
    status = Column(String, default="preview")
    row_count = Column(Integer, default=0)
    applied_count = Column(Integer, default=0)
    duplicate_count = Column(Integer, default=0)
    conflict_count = Column(Integer, default=0)
    receipt_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=_now)
    applied_at = Column(DateTime, nullable=True)
    undone_at = Column(DateTime, nullable=True)


class FinanceImportRow(Base):
    __tablename__ = "finance_import_rows"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_number", name="uq_finance_import_batch_row"),
    )
    id = Column(String, primary_key=True, default=_uid)
    batch_id = Column(
        String,
        ForeignKey("finance_import_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_number = Column(Integer, nullable=False)
    stable_identity = Column(String, nullable=False, index=True)
    raw_json = Column(Text, nullable=False)
    parsed_json = Column(Text, nullable=False)
    conversion_json = Column(Text, default="{}")
    status = Column(String, default="pending")
    existing_transaction_id = Column(String, default="")
    created_transaction_id = Column(String, default="")
    conflict_reason = Column(String, default="")
    created_at = Column(DateTime, default=_now)


class FinanceLedgerState(Base):
    __tablename__ = "finance_ledger_state"
    id = Column(String, primary_key=True, default="primary")
    mode = Column(String, nullable=False, default="alles")  # alles | actual
    base_currency_code = Column(String, nullable=False, default="CAD")
    active_run_id = Column(String, default="")
    actual_budget_id = Column(String, default="")
    actual_sync_id = Column(String, default="")
    legacy_read_only = Column(Boolean, nullable=False, default=False)
    cutover_at = Column(DateTime, nullable=True)
    rollback_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class FinanceConnection(Base):
    """Read-only aggregator connection. Tokens are always machine-key encrypted."""

    __tablename__ = "finance_connections"
    id = Column(String, primary_key=True, default=_uid)
    provider = Column(String, nullable=False, index=True)  # simplefin | plaid
    label = Column(String, nullable=False, default="bank connection")
    environment = Column(String, nullable=False, default="production")
    status = Column(String, nullable=False, default="connected")
    client_id = Column(EncryptedText("finance_connections.client_id"), default="")
    client_secret = Column(EncryptedText("finance_connections.client_secret"), default="")
    access_token = Column(EncryptedText("finance_connections.access_token"), default="")
    item_id = Column(String, default="")
    cursor = Column(Text, default="")
    account_map_json = Column(Text, default="{}")
    consent_expires_at = Column(DateTime, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class ActualMigrationRun(Base):
    __tablename__ = "actual_migration_runs"
    id = Column(String, primary_key=True, default=_uid)
    status = Column(String, nullable=False, default="staging")
    base_currency_code = Column(String, nullable=False)
    snapshot_sha256 = Column(String, nullable=False)
    snapshot_path = Column(Text, nullable=False)
    actual_budget_id = Column(String, default="")
    actual_sync_id = Column(String, default="")
    report_json = Column(Text, default="{}")
    error = Column(Text, default="")
    created_at = Column(DateTime, default=_now)
    verified_at = Column(DateTime, nullable=True)
    cutover_at = Column(DateTime, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)


class ActualEntityLink(Base):
    __tablename__ = "actual_entity_links"
    __table_args__ = (
        UniqueConstraint("run_id", "entity_kind", "source_id", name="uq_actual_link_source"),
    )
    id = Column(String, primary_key=True, default=_uid)
    run_id = Column(String, nullable=False, index=True)
    entity_kind = Column(String, nullable=False, index=True)
    source_id = Column(String, nullable=False)
    actual_id = Column(String, nullable=False)
    metadata_json = Column(Text, default="{}")
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
    tag = Column(String, default="")  # 2e - if set, this is a tag budget (hierarchy-rolled)
    limit_amt = Column(Float, default=0.0)  # monthly spending cap for this category
    created_at = Column(DateTime, default=_now)


class TagRule(Base):
    # 2e - payee substring -> tag(s), auto-applied to typed/imported txns (like CategoryRule)
    __tablename__ = "money_tag_rules"
    id = Column(String, primary_key=True, default=_uid)
    match = Column(String, nullable=False)  # case-insensitive substring of the payee
    tags = Column(String, default="")  # csv of tags to add
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
    anchor_day = Column(
        Integer, nullable=True
    )  # original day-of-month so monthly/yearly don't drift after short months
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


class PriceHistory(Base):
    # 2d - one row per symbol per price refresh, so holdings get a trend + return-since-first
    __tablename__ = "money_price_history"
    id = Column(String, primary_key=True, default=_uid)
    symbol = Column(String, nullable=False, index=True)
    price = Column(Float, default=0.0)
    ts = Column(DateTime, default=_now)


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
