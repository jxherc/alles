# 1f — Transaction ingestion + recurring-detection — audit (2026-06-19)

Backend-only. Current: money has CSV import (`routes/money.py:import_txns_csv`, dedups on
date+amount+payee) and subs are entered manually; no OFX/QFX import and no recurring-pattern
detection over transactions. subs auto-detect (4e) and bill detection have nothing to build on.

## Gap (1f)
A shared ingestion layer: OFX/QFX parsing + a `detect_recurring()` engine that clusters txns by
payee + amount + cadence. Reused by money (recurring/bills) and subs (auto-detect, 4e).

## Plan
- 1f-1: `services/txn_ingest.py` — `parse_ofx(text)` (OFX 1.x SGML + 2.x XML <STMTTRN>) +
  `detect_recurring(txns)` (group by payee+amount, infer weekly/monthly/quarterly/yearly from median
  gap, >=3 occurrences). Unit tests >=10.
- 1f-2: `POST /api/money/import-ofx` (dedup-insert like CSV) + `GET /api/money/recurring-detect` +
  `GET /api/subscriptions/detect` (candidates not already tracked). API tests >=8.
