"""SQLite infrastructure and the compatible model/session import interface."""

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from core.database_credentials import (
    _SECRET_COLUMNS as _SECRET_COLUMNS,
)
from core.database_credentials import (
    _lock_credential_session,
    _unlock_credential_session,
    encrypt_plaintext_secrets,
)
from core.schema import DEFAULT_LOCAL_STORAGE_LOCATION_ID as DEFAULT_LOCAL_STORAGE_LOCATION_ID
from core.schema import Account as Account
from core.schema import ActualEntityLink as ActualEntityLink
from core.schema import ActualMigrationRun as ActualMigrationRun
from core.schema import Album as Album
from core.schema import AndromedaSavedSearch as AndromedaSavedSearch
from core.schema import AndromedaVerificationJob as AndromedaVerificationJob
from core.schema import ApiToken as ApiToken
from core.schema import Attachment as Attachment
from core.schema import AuditRecord as AuditRecord
from core.schema import AutomationAttempt as AutomationAttempt
from core.schema import AutomationRule as AutomationRule
from core.schema import Base as Base
from core.schema import Blob as Blob
from core.schema import Book as Book
from core.schema import BookingPage as BookingPage
from core.schema import BrowserConnection as BrowserConnection
from core.schema import Budget as Budget
from core.schema import BudgetAssignment as BudgetAssignment
from core.schema import CachedMessage as CachedMessage
from core.schema import Calendar as Calendar
from core.schema import CalendarEvent as CalendarEvent
from core.schema import CalendarSubscription as CalendarSubscription
from core.schema import CapabilityGrant as CapabilityGrant
from core.schema import CapabilityGrantEvent as CapabilityGrantEvent
from core.schema import CategoryRule as CategoryRule
from core.schema import Connection as Connection
from core.schema import Contact as Contact
from core.schema import ContactField as ContactField
from core.schema import ContactGroup as ContactGroup
from core.schema import ContactGroupMember as ContactGroupMember
from core.schema import ContactLink as ContactLink
from core.schema import CookbookEntry as CookbookEntry
from core.schema import DayEvent as DayEvent
from core.schema import DelegatedAction as DelegatedAction
from core.schema import DocComment as DocComment
from core.schema import DocRevision as DocRevision
from core.schema import EncryptedText as EncryptedText
from core.schema import EventAttendee as EventAttendee
from core.schema import Face as Face
from core.schema import FileComment as FileComment
from core.schema import FileOperation as FileOperation
from core.schema import FileOperationPathClaim as FileOperationPathClaim
from core.schema import FileOperationSourceClaim as FileOperationSourceClaim
from core.schema import FileTag as FileTag
from core.schema import FileVersion as FileVersion
from core.schema import FinanceConnection as FinanceConnection
from core.schema import FinanceCreateReceipt as FinanceCreateReceipt
from core.schema import FinanceImportBatch as FinanceImportBatch
from core.schema import FinanceImportRow as FinanceImportRow
from core.schema import FinanceLedgerState as FinanceLedgerState
from core.schema import FundingTarget as FundingTarget
from core.schema import GalleryImage as GalleryImage
from core.schema import Goal as Goal
from core.schema import Habit as Habit
from core.schema import HabitCreateReceipt as HabitCreateReceipt
from core.schema import HabitLog as HabitLog
from core.schema import HealthCreateReceipt as HealthCreateReceipt
from core.schema import HealthEntry as HealthEntry
from core.schema import HealthImportReceipt as HealthImportReceipt
from core.schema import Holding as Holding
from core.schema import IndexChunk as IndexChunk
from core.schema import Insight as Insight
from core.schema import JarvisConnector as JarvisConnector
from core.schema import JarvisDeliveryAttempt as JarvisDeliveryAttempt
from core.schema import JarvisInboxEvent as JarvisInboxEvent
from core.schema import JarvisRun as JarvisRun
from core.schema import JarvisRunEvent as JarvisRunEvent
from core.schema import JarvisRunPrompt as JarvisRunPrompt
from core.schema import JarvisTrigger as JarvisTrigger
from core.schema import JarvisWorkflow as JarvisWorkflow
from core.schema import JournalEntry as JournalEntry
from core.schema import MailAccount as MailAccount
from core.schema import MailDraft as MailDraft
from core.schema import MailRule as MailRule
from core.schema import McpServer as McpServer
from core.schema import Memory as Memory
from core.schema import Message as Message
from core.schema import ModelEndpoint as ModelEndpoint
from core.schema import ModelVote as ModelVote
from core.schema import MoneyFxEvidence as MoneyFxEvidence
from core.schema import Monitor as Monitor
from core.schema import MonitorCheck as MonitorCheck
from core.schema import MutationEvent as MutationEvent
from core.schema import NewsBrief as NewsBrief
from core.schema import NewsConfiguration as NewsConfiguration
from core.schema import NewsEntry as NewsEntry
from core.schema import NewsSource as NewsSource
from core.schema import OfflineFile as OfflineFile
from core.schema import Person as Person
from core.schema import Persona as Persona
from core.schema import PersonaDoc as PersonaDoc
from core.schema import Photo as Photo
from core.schema import PriceHistory as PriceHistory
from core.schema import ProactiveItem as ProactiveItem
from core.schema import ProactiveOutcome as ProactiveOutcome
from core.schema import ProactiveState as ProactiveState
from core.schema import Project as Project
from core.schema import PushSubscription as PushSubscription
from core.schema import ReadFeed as ReadFeed
from core.schema import ReadItem as ReadItem
from core.schema import RecurringTxn as RecurringTxn
from core.schema import Reminder as Reminder
from core.schema import ResearchFinding as ResearchFinding
from core.schema import SavedSearch as SavedSearch
from core.schema import ScheduledMail as ScheduledMail
from core.schema import Session as Session
from core.schema import Share as Share
from core.schema import SignalSnapshot as SignalSnapshot
from core.schema import StorageLocation as StorageLocation
from core.schema import SubPayment as SubPayment
from core.schema import SubPriceChange as SubPriceChange
from core.schema import Subscription as Subscription
from core.schema import TagRule as TagRule
from core.schema import Task as Task
from core.schema import ToolChain as ToolChain
from core.schema import Transaction as Transaction
from core.schema import TrashItem as TrashItem
from core.schema import TxnSplit as TxnSplit
from core.schema import Upload as Upload
from core.schema import Vault as Vault
from core.schema import VaultAttachment as VaultAttachment
from core.schema import VaultCreateReceipt as VaultCreateReceipt
from core.schema import VaultEntry as VaultEntry
from core.schema import VaultShare as VaultShare
from core.schema import VaultUploadReceipt as VaultUploadReceipt
from core.schema import Watch as Watch
from core.schema import WebAuthnCredential as WebAuthnCredential
from core.schema import Webhook as Webhook
from core.schema import canonical_local_physical_claim_path as canonical_local_physical_claim_path
from core.schema import local_claim_case_insensitive as local_claim_case_insensitive
from core.schema import normalize_file_identity_path as normalize_file_identity_path
from core.schema.base import _now as _now
from core.schema.base import _uid as _uid

# default db lives in <data>/aide.db; ALLES_DB (or ALLES_DATA via settings.data_dir) isolates it
from core.settings import data_dir as _data_dir

DB_PATH = os.environ.get("ALLES_DB") or str(_data_dir() / "aide.db")
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


# wal mode so reads don't block writes
@event.listens_for(engine, "connect")
def _set_wal(conn, _):
    conn.execute("pragma journal_mode=wal")
    conn.execute("pragma foreign_keys=on")
    # keep sqlite from failing fast when background writes overlap
    conn.execute("pragma busy_timeout=5000")
    conn.execute("pragma synchronous=normal")
    conn.execute("pragma cache_size=-16000")  # ~16MB page cache (negative = KiB)
    conn.execute("pragma temp_store=memory")


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# Keep the existing import seam while initialization and credential migration own their order.
def init_db():
    from core.startup import initialize_database

    initialize_database(engine, DB_PATH)


def _encrypt_plaintext_secrets(force_reseal: bool = False) -> int:
    return encrypt_plaintext_secrets(engine, force_reseal=force_reseal)


event.listen(SessionLocal.class_, "before_flush", _lock_credential_session)
event.listen(SessionLocal.class_, "after_transaction_end", _unlock_credential_session)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
