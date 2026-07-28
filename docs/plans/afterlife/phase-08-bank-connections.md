# Phase 8 bank connection report

- **Status:** current evidence reviewed 2026-07-18
- **Banks:** CIBC Canada and China Merchants Bank
- **Decision:** ship reviewed file/notification imports first; do not label direct sync supported until
  the exact owner account passes the provider connection check

## Provider boundary

Actual currently lists Akahu for New Zealand, Enable Banking and legacy GoCardless for Europe,
SimpleFIN for North America, and Pluggy for Brazil. Actual does not fetch automatically on a schedule;
the owner or the Alles-managed job must trigger bank sync. Its server stores provider keys and tokens
outside Actual's end-to-end budget encryption.

[Actual bank-sync documentation](https://actualbudget.org/docs/advanced/bank-sync/) and
[Actual import documentation](https://actualbudget.org/docs/transactions/importing/) are the authority
for this report.

## CIBC Canada

### Current connection finding

SimpleFIN is the only built-in Actual provider whose stated region covers a Canadian CIBC account. Its
public institution search is interactive and explicitly limited to US/Canadian versions of
international institutions. It does not prove that every CIBC product, login, or multi-factor flow is
eligible. Alles therefore may offer **Check with SimpleFIN** but must not predeclare a CIBC account
supported.

The SimpleFIN Bridge currently costs USD 1.50 plus tax monthly or USD 15 plus tax yearly and supports up
to 25 institutions and 25 apps. It is read-only. Its current privacy policy says credentials go to MX,
financial data can be accessed by connected third parties, and service data is operated in the United
States. Its security page records a corrected May 28, 2026 MX account-mixing incident that may have
shown account names, balances, and transactions for up to 39 users.

- [SimpleFIN price and limits](https://beta-bridge.simplefin.org/)
- [SimpleFIN supported-institution search](https://beta-bridge.simplefin.org/search-institutions)
- [SimpleFIN privacy policy](https://beta-bridge.simplefin.org/info/privacy)
- [SimpleFIN security and incident record](https://beta-bridge.simplefin.org/info/security)

CIBC itself warns that third-party aggregators commonly ask for online banking credentials, that a
CIBC-branded sign-in is not an endorsement, and that sharing credentials breaches its electronic
access agreement and can affect responsibility for losses. CIBC also prohibits automated gathering
from its online services. Alles will not scrape CIBC or store a CIBC password.

- [CIBC third-party app warning](https://www.cibc.com/en/privacy-security/protect-yourself-3rd-party-apps.html)
- [CIBC electronic access agreement](https://www.cibc.com/en/legal/agreements/electronic-access.html)

### Supported Phase 8 path

1. Prefer CIBC OFX/QFX or CSV statement import with preview.
2. When the bank supplies a provider-stable transaction or row identifier, derive the durable source
   identity from the institution, account fingerprint, and that identifier so overlapping exports
   deduplicate correctly. Only bind identity to a stable statement identifier plus row position when
   the format has no cross-export transaction identifier. Keep date, amount, currency, and normalized
   description in a separate comparison fingerprint so corrected no-ID rows become reviewable
   conflicts instead of silent duplicates.
3. Use Actual `importTransactions` with `reimportDeleted: false` and a stable `imported_id`.
4. Keep the source statement hash and per-row receipt in the encrypted Alles sidecar so preview and
   undo are auditable.
5. Offer the SimpleFIN connection only after showing its current cost, privacy, token-storage, refresh,
   and failure disclosures. The owner performs the provider-hosted connection; Alles never receives the
   bank password.

## China Merchants Bank

### Current connection finding

Actual lists no built-in provider for mainland Chinese banks. China Merchants Bank operates an official
Open API platform, but its terms describe a developer subscription that requires authentication,
per-API agreements, bank approval, quotas, and possible fees. The public material does not establish a
consumer transaction-feed entitlement for a self-hosted personal app. This is not a proven Phase 8 bank
sync path.

- [China Merchants Bank Open API agreement](https://openapi.cmbchina.com/serviceAgreement)
- [China Merchants Bank Open API overview](https://openapi.cmbchina.com/aboutUs)

The bank's official personal software and app provide authenticated account and income/expense views.
Its official business help also documents SMS and email transaction-notification configuration. These
sources establish owner-mediated export/notification paths, not permission to scrape either product.

- [China Merchants Bank personal PC client](https://www.cmbchina.com/pbankwebNew/DownLoadQA.aspx)
- [China Merchants Bank notification help](https://market.cmbchina.com/personal/qyMobile/qyMobile/qywysc/xtcz/24dxtzzd.html)

### Supported Phase 8 path

1. Import a statement or transaction export chosen by the owner, with an explicit CMB mapping profile.
2. Optionally parse an owner-forwarded CMB device/email notification profile only after a preview
   proves the date, amount, direction, currency, and account suffix. A notification with missing or
   ambiguous fields stays pending and never posts automatically.
3. Store neither CMB login credentials nor session material. Do not automate the bank site or app.
4. Treat Open API access as unsupported until the owner supplies an approved product, entitlement,
   documented price, and sandbox credentials. Any future connector gets a separate security review.

## Refresh and failure behavior

Provider sync is manual or Alles-scheduled only after explicit enablement. A failed or partial fetch
does not advance the last-success cursor. Statement and notification imports are always previewed. A
duplicate source ID is a no-op, a changed row with the same source ID is a conflict, and undo targets
only transactions owned by that import receipt. Bank/provider downtime never changes the last verified
ledger balance.
