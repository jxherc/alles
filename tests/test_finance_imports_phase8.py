import json
from decimal import Decimal
from unittest import mock

from core.database import FinanceImportBatch, FinanceImportRow, MoneyFxEvidence, Transaction
from routes import finance_imports as finance_import_routes
from services import finance_imports
from tests._client import ApiTest


class FinanceImportsPhase8Tests(ApiTest):
    def setUp(self):
        super().setUp()
        self.account = self.client.post(
            "/api/money/accounts",
            json={"name": "CIBC chequing", "kind": "checking", "currency": "CAD", "opening": 100},
        ).json()
        self.cmb_account = self.client.post(
            "/api/money/accounts",
            json={"name": "CMB account 1234", "kind": "checking", "currency": "CNY", "opening": 0},
        ).json()

    def _preview(self, content, profile="cibc-csv", source_name="statement.csv"):
        account = self.account if profile == "cibc-csv" else self.cmb_account
        response = self.client.post(
            "/api/finance/imports/preview",
            json={
                "account_id": account["id"],
                "profile": profile,
                "source_name": source_name,
                "content": content,
                "original_currency_code": "CAD" if profile == "cibc-csv" else "CNY",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_reviewed_profiles_and_read_only_providers_are_exposed(self):
        payload = self.client.get("/api/finance/imports/profiles").json()
        ids = {item["id"] for item in payload["profiles"]}
        self.assertTrue({"cibc-csv", "rbc-csv", "td-csv", "bmo-csv", "scotiabank-csv"} <= ids)
        self.assertTrue({"cmb-csv", "icbc-csv", "ccb-csv", "abc-csv", "boc-csv", "bocom-csv"} <= ids)
        self.assertEqual({item["id"] for item in payload["providers"]}, {"simplefin", "plaid"})
        self.assertTrue(payload["direct_sync_supported"])

    def test_import_receipt_reads_require_auth_even_without_middleware_enforcement(self):
        from core import auth

        token = auth.create_session_token()
        auth.store_token(token)
        try:
            with (
                mock.patch("app.auth_enabled", return_value=False),
                mock.patch("core.settings.auth_enabled", return_value=True),
            ):
                self.assertEqual(self.client.get("/api/finance/imports").status_code, 401)
                self.client.cookies.set("aide_session", token)
                self.assertEqual(self.client.get("/api/finance/imports").status_code, 200)
        finally:
            self.client.cookies.clear()
            auth.revoke_token(token)

    def test_conversion_review_holds_apply_and_authority_locks(self):
        class TrackingLock:
            def __init__(self):
                self.held = False

            def __enter__(self):
                self.held = True

            def __exit__(self, *_args):
                self.held = False

        apply_lock = TrackingLock()
        authority_lock = TrackingLock()

        def reviewed(*_args):
            self.assertTrue(apply_lock.held)
            self.assertTrue(authority_lock.held)
            return {"ok": True}

        body = finance_import_routes.ConversionEvidenceBody(
            base_amount_text="1.00",
            rate_text="1",
            rate_date="2026-07-18",
            source="owner note",
        )
        with (
            mock.patch.object(finance_import_routes, "_IMPORT_APPLY_LOCK", apply_lock),
            mock.patch.object(
                finance_import_routes.actual_finance, "AUTHORITY_LOCK", authority_lock
            ),
            mock.patch.object(
                finance_import_routes, "_review_conversion_locked", side_effect=reviewed
            ),
        ):
            result = finance_import_routes.review_conversion("batch", "row", body, object())
        self.assertEqual(result, {"ok": True})

    def test_preview_holds_the_authority_lock_for_ledger_classification_and_receipt(self):
        class TrackingLock:
            held = False

            def __enter__(self):
                self.held = True

            def __exit__(self, *_args):
                self.held = False

        lock = TrackingLock()

        def previewed(*_args):
            self.assertTrue(lock.held)
            return {"ok": True}

        with (
            mock.patch.object(finance_import_routes.actual_finance, "AUTHORITY_LOCK", lock),
            mock.patch.object(finance_import_routes, "_preview_locked", side_effect=previewed),
        ):
            result = finance_import_routes.preview(
                finance_import_routes.PreviewBody(
                    account_id="account",
                    profile="cibc-csv",
                    source_name="statement.csv",
                    content="header",
                ),
                object(),
            )
        self.assertEqual(result, {"ok": True})

    def test_every_money_changing_import_action_requires_a_recent_owner_session(self):
        from core import auth

        preview = self._preview(
            "交易日期,交易摘要,支出金额,收入金额,交易币种,交易流水号\n"
            "2026-07-04,午餐,38.60,,CNY,cmb-owner\n",
            profile="cmb-csv",
        )
        db = self.db()
        state = db.get(finance_import_routes.FinanceLedgerState, "primary")
        if state is None:
            state = finance_import_routes.FinanceLedgerState(id="primary")
            db.add(state)
        state.mode = "actual"
        state.base_currency_code = "CAD"
        state.legacy_read_only = True
        db.commit()
        db.close()
        token = auth.create_session_token()
        auth.store_token(token)
        auth._recent_auth[token] = 0
        self.client.cookies.set("aide_session", token)
        try:
            with (
                mock.patch("app.auth_enabled", return_value=True),
                mock.patch("core.settings.auth_enabled", return_value=True),
            ):
                responses = [
                    self.client.post(
                        "/api/finance/imports/preview",
                        json={
                            "account_id": self.account["id"],
                            "profile": "cibc-csv",
                            "source_name": "blocked.csv",
                            "content": "Date,Description,Amount,Currency\n2026-07-19,Coffee,-3.00,CAD\n",
                            "original_currency_code": "CAD",
                        },
                    ),
                    self.client.patch(
                        f"/api/finance/imports/{preview['id']}/rows/{preview['rows'][0]['id']}/conversion",
                        json={
                            "base_amount_text": "-7.72",
                            "rate_text": "0.2",
                            "rate_date": "2026-07-04",
                            "source": "statement",
                        },
                    ),
                    self.client.post(
                        f"/api/finance/imports/{preview['id']}/rows/{preview['rows'][0]['id']}/resolve-match",
                        json={"decision": "duplicate"},
                    ),
                    self.client.post(
                        f"/api/finance/imports/{preview['id']}/rows/{preview['rows'][0]['id']}/resolve-recovery",
                        json={"decision": "keep"},
                    ),
                    self.client.post(f"/api/finance/imports/{preview['id']}/apply"),
                    self.client.post(f"/api/finance/imports/{preview['id']}/undo"),
                ]
        finally:
            self.client.cookies.clear()
            auth._tokens.clear()
            auth._recent_auth.clear()
        for response in responses:
            self.assertEqual(response.status_code, 403, response.text)
            self.assertEqual(response.json()["code"], "recent_auth_required")

    def test_stale_conversion_is_invalidated_when_the_canonical_base_changes(self):
        db = self.db()
        state = db.get(finance_import_routes.FinanceLedgerState, "primary")
        if state is None:
            state = finance_import_routes.FinanceLedgerState(id="primary")
            db.add(state)
        state.mode = "actual"
        state.base_currency_code = "CAD"
        state.legacy_read_only = True
        db.commit()
        db.close()
        with (
            mock.patch.object(
                finance_import_routes.actual_finance,
                "accounts",
                return_value=[{"id": self.cmb_account["id"], "name": "CMB account"}],
            ),
            mock.patch.object(
                finance_import_routes.actual_finance, "transactions", return_value=[]
            ),
        ):
            preview = self._preview(
                "交易日期,交易摘要,支出金额,收入金额,交易币种,交易流水号\n"
                "2026-07-04,午餐,38.60,,CNY,cmb-base\n",
                profile="cmb-csv",
            )
        row_id = preview["rows"][0]["id"]
        reviewed = self.client.patch(
            f"/api/finance/imports/{preview['id']}/rows/{row_id}/conversion",
            json={
                "base_amount_text": "-7.72",
                "rate_text": "0.2",
                "rate_date": "2026-07-04",
                "source": "statement",
            },
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        db = self.db()
        db.get(finance_import_routes.FinanceLedgerState, "primary").base_currency_code = "USD"
        db.commit()
        db.close()
        with (
            mock.patch.object(
                finance_import_routes.actual_finance, "transactions", return_value=[]
            ),
            mock.patch.object(finance_import_routes.actual_finance, "create_transaction") as create,
        ):
            applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(applied.json()["status"], "preview", applied.text)
        self.assertEqual(applied.json()["rows"][0]["status"], "needs_review")
        create.assert_not_called()
        db = self.db()
        self.assertEqual(db.get(FinanceImportRow, row_id).conversion_json, "")
        db.close()

    def test_half_even_review_evidence_remains_valid_for_apply(self):
        preview = self._preview(
            "交易日期,交易摘要,支出金额,收入金额,交易币种,交易流水号\n"
            "2026-07-04,rounding,,0.01,CNY,cmb-half-even\n",
            profile="cmb-csv",
        )
        row_id = preview["rows"][0]["id"]
        db = self.db()
        state = db.get(finance_import_routes.FinanceLedgerState, "primary")
        if state is None:
            state = finance_import_routes.FinanceLedgerState(id="primary")
            db.add(state)
        state.mode = "actual"
        state.base_currency_code = "CAD"
        state.legacy_read_only = True
        db.commit()
        db.close()

        reviewed = self.client.patch(
            f"/api/finance/imports/{preview['id']}/rows/{row_id}/conversion",
            json={
                "base_amount_text": "0.00",
                "rate_text": "0.5",
                "rate_date": "2026-07-04",
                "source": "statement",
            },
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)

        db = self.db()
        batch = db.get(FinanceImportBatch, preview["id"])
        row = db.get(FinanceImportRow, row_id)
        evidence = finance_import_routes._conversion_evidence(
            row,
            json.loads(row.parsed_json),
            batch,
            db.get(finance_import_routes.FinanceLedgerState, "primary"),
        )
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence[0], "0.00")
        db.close()

    def test_repeated_canonical_foreign_rows_require_consistent_reviewed_conversion(self):
        db = self.db()
        state = db.get(finance_import_routes.FinanceLedgerState, "primary")
        if state is None:
            state = finance_import_routes.FinanceLedgerState(id="primary")
            db.add(state)
        state.mode = "actual"
        state.base_currency_code = "CAD"
        state.legacy_read_only = True
        db.commit()
        db.close()
        source = (
            "交易日期,交易摘要,支出金额,收入金额,交易币种,交易流水号\n"
            "2026-07-04,午餐,38.60,,CNY,cmb-repeat\n"
            "2026-07-04,午餐,38.60,,CNY,cmb-repeat\n"
        )
        with (
            mock.patch.object(
                finance_import_routes.actual_finance,
                "accounts",
                return_value=[{"id": self.cmb_account["id"], "name": "CMB account"}],
            ),
            mock.patch.object(
                finance_import_routes.actual_finance, "transactions", return_value=[]
            ),
        ):
            preview = self._preview(source, profile="cmb-csv", source_name="repeated-cny.csv")
        self.assertEqual([row["status"] for row in preview["rows"]], ["needs_review"] * 2)
        self.assertTrue(
            all("conversion evidence to CAD" in row["conflict_reason"] for row in preview["rows"])
        )

        for row, base_amount, rate in zip(
            preview["rows"], ("-7.72", "-11.58"), ("0.2", "0.3"), strict=True
        ):
            reviewed = self.client.patch(
                f"/api/finance/imports/{preview['id']}/rows/{row['id']}/conversion",
                json={
                    "base_amount_text": base_amount,
                    "rate_text": rate,
                    "rate_date": "2026-07-04",
                    "source": "statement",
                },
            )
            self.assertEqual(reviewed.status_code, 200, reviewed.text)

        with (
            mock.patch.object(
                finance_import_routes.actual_finance, "transactions", return_value=[]
            ),
            mock.patch.object(finance_import_routes.actual_finance, "create_transaction") as create,
        ):
            applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        payload = applied.json()
        self.assertEqual(payload["status"], "preview")
        self.assertEqual([row["status"] for row in payload["rows"]], ["conflict"] * 2)
        self.assertTrue(
            all(
                "conflicting reviewed conversion" in row["conflict_reason"]
                for row in payload["rows"]
            )
        )
        create.assert_not_called()

    def test_repeated_canonical_foreign_rows_apply_once_after_consistent_review(self):
        db = self.db()
        state = db.get(finance_import_routes.FinanceLedgerState, "primary")
        if state is None:
            state = finance_import_routes.FinanceLedgerState(id="primary")
            db.add(state)
        state.mode = "actual"
        state.base_currency_code = "CAD"
        state.legacy_read_only = True
        db.commit()
        db.close()
        source = (
            "交易日期,交易摘要,支出金额,收入金额,交易币种,交易流水号\n"
            "2026-07-04,午餐,38.60,,CNY,cmb-repeat-once\n"
            "2026-07-04,午餐,38.60,,CNY,cmb-repeat-once\n"
        )
        with (
            mock.patch.object(
                finance_import_routes.actual_finance,
                "accounts",
                return_value=[{"id": self.cmb_account["id"], "name": "CMB account"}],
            ),
            mock.patch.object(
                finance_import_routes.actual_finance, "transactions", return_value=[]
            ),
        ):
            preview = self._preview(source, profile="cmb-csv", source_name="repeated-cny.csv")

        for row in preview["rows"]:
            reviewed = self.client.patch(
                f"/api/finance/imports/{preview['id']}/rows/{row['id']}/conversion",
                json={
                    "base_amount_text": "-7.72",
                    "rate_text": "0.2",
                    "rate_date": "2026-07-04",
                    "source": "statement",
                },
            )
            self.assertEqual(reviewed.status_code, 200, reviewed.text)

        created = {
            "id": "finance-import:created",
            "actual_id": "actual-created",
            "account_id": self.cmb_account["id"],
            "date": "2026-07-04",
            "amount": "-7.72",
            "payee": "午餐",
            "notes": "imported from repeated-cny.csv",
            "import_identity": preview["rows"][0]["stable_identity"],
            "import_batch_id": preview["id"],
            "import_source": "cmb-csv",
        }
        create = mock.Mock(return_value=created)
        with (
            mock.patch.object(
                finance_import_routes.actual_finance, "transactions", return_value=[]
            ),
            mock.patch.object(finance_import_routes.actual_finance, "create_transaction", create),
        ):
            applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        payload = applied.json()
        self.assertEqual(payload["status"], "applied")
        self.assertEqual(payload["counts"]["applied"], 1)
        self.assertEqual(payload["counts"]["duplicates"], 1)
        self.assertEqual([row["status"] for row in payload["rows"]], ["applied", "duplicate"])
        create.assert_called_once()

    def test_conversion_review_rejects_unknown_original_or_base_currency(self):
        preview = self._preview(
            "交易日期,交易摘要,支出金额,收入金额,交易币种,交易流水号\n"
            "2026-07-04,午餐,38.60,,CNY,cmb-unknown-currency\n",
            profile="cmb-csv",
        )
        row_id = preview["rows"][0]["id"]
        db = self.db()
        state = db.get(finance_import_routes.FinanceLedgerState, "primary")
        if state is None:
            state = finance_import_routes.FinanceLedgerState(id="primary")
            db.add(state)
        state.mode = "actual"
        state.base_currency_code = "CAD"
        state.legacy_read_only = True
        row = db.get(FinanceImportRow, row_id)
        parsed = json.loads(row.parsed_json)
        parsed["currency_code"] = "元"
        row.parsed_json = json.dumps(parsed)
        db.commit()
        db.close()

        body = {
            "base_amount_text": "-7.72",
            "rate_text": "0.2",
            "rate_date": "2026-07-04",
            "source": "statement",
        }
        invalid_original = self.client.patch(
            f"/api/finance/imports/{preview['id']}/rows/{row_id}/conversion",
            json=body,
        )
        self.assertEqual(invalid_original.status_code, 409, invalid_original.text)
        self.assertIn("reviewed original and base", invalid_original.json()["detail"])

        db = self.db()
        row = db.get(FinanceImportRow, row_id)
        parsed = json.loads(row.parsed_json)
        parsed["currency_code"] = "CNY"
        row.parsed_json = json.dumps(parsed)
        db.get(finance_import_routes.FinanceLedgerState, "primary").base_currency_code = "元"
        db.commit()
        db.close()
        invalid_base = self.client.patch(
            f"/api/finance/imports/{preview['id']}/rows/{row_id}/conversion",
            json=body,
        )
        self.assertEqual(invalid_base.status_code, 409, invalid_base.text)
        self.assertIn("reviewed original and base", invalid_base.json()["detail"])
        db = self.db()
        self.assertEqual(db.get(FinanceImportRow, row_id).conversion_json, "{}")
        db.close()

    def test_cibc_preview_apply_repeat_duplicate_and_import_owned_undo(self):
        source = (
            "Transaction Date,Description,Debit,Credit,Transaction ID\n"
            "2026-07-01,Grocer,12.34,,cibc-1\n"
            "2026-07-02,Payroll,,1000.00,cibc-2\n"
        )
        preview = self._preview(source)
        self.assertEqual(preview["status"], "preview")
        self.assertEqual(
            {key: preview["counts"][key] for key in ("rows", "pending", "duplicates", "conflicts")},
            {"rows": 2, "pending": 2, "duplicates": 0, "conflicts": 0},
        )
        self.assertEqual(preview["rows"][0]["parsed"]["amount_text"], "-12.34")

        applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        receipt = applied.json()
        self.assertEqual(receipt["status"], "applied")
        self.assertEqual(receipt["counts"]["applied"], 2)

        db = self.db()
        imported = (
            db.query(Transaction)
            .filter_by(import_batch_id=preview["id"])
            .order_by(Transaction.date)
            .all()
        )
        self.assertEqual(
            [Decimal(item.original_amount_text) for item in imported],
            [Decimal("-12.34"), Decimal("1000.00")],
        )
        self.assertEqual(db.query(MoneyFxEvidence).count(), 2)
        manual = Transaction(
            account_id=self.account["id"], date="2026-07-03", amount=-5, payee="manual"
        )
        db.add(manual)
        db.commit()
        manual_id = manual.id
        db.close()

        repeat = self._preview(source, source_name="download-again.csv")
        self.assertEqual(repeat["counts"]["duplicates"], 2)
        self.assertEqual(repeat["counts"]["pending"], 0)
        duplicate_only = self.client.post(f"/api/finance/imports/{repeat['id']}/apply")
        self.assertEqual(duplicate_only.status_code, 200, duplicate_only.text)
        self.assertEqual(duplicate_only.json()["status"], "applied")
        self.assertEqual(duplicate_only.json()["counts"]["applied"], 0)
        self.assertEqual(duplicate_only.json()["counts"]["duplicates"], 2)

        repeated_existing = self._preview(
            "Transaction Date,Description,Debit,Credit,Transaction ID\n"
            "2026-07-01,Grocer,12.34,,cibc-1\n"
            "2026-07-01,Grocer,12.34,,cibc-1\n",
            source_name="repeated-existing.csv",
        )
        self.assertEqual(repeated_existing["counts"]["duplicates"], 2)
        self.assertEqual(
            {row["existing_transaction_id"] for row in repeated_existing["rows"]},
            {repeat["rows"][0]["existing_transaction_id"]},
        )
        repeated_applied = self.client.post(f"/api/finance/imports/{repeated_existing['id']}/apply")
        self.assertEqual(repeated_applied.status_code, 200, repeated_applied.text)
        self.assertEqual(repeated_applied.json()["counts"]["duplicates"], 2)

        undone = self.client.post(f"/api/finance/imports/{preview['id']}/undo")
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()["counts"]["undone"], 2)
        db = self.db()
        self.assertIsNotNone(db.get(Transaction, manual_id))
        self.assertEqual(db.query(Transaction).filter_by(import_batch_id=preview["id"]).count(), 0)
        self.assertEqual(db.query(Transaction).filter_by(import_batch_id=repeat["id"]).count(), 0)
        db.close()

    def test_real_headerless_cibc_download_keeps_its_first_transaction(self):
        preview = self._preview("2026-07-01,Grocer,12.34,,1234\n2026-07-02,Payroll,,1000.00,1234\n")

        self.assertEqual(preview["counts"]["rows"], 2)
        self.assertEqual(preview["counts"]["pending"], 2)
        self.assertEqual(
            [row["parsed"]["amount_text"] for row in preview["rows"]],
            ["-12.34", "1000.00"],
        )
        self.assertEqual(
            [row["parsed"]["payee"] for row in preview["rows"]],
            ["Grocer", "Payroll"],
        )

    def test_undo_refuses_to_delete_an_imported_transaction_edited_by_the_owner(self):
        source = (
            "Date,Description,Amount,Currency,Reference\n"
            "2026-07-01,Coffee,-10.00,CAD,owner-edited-row\n"
        )
        preview = self._preview(source, source_name="owner-edit.csv")
        applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        transaction_id = applied.json()["rows"][0]["created_transaction_id"]

        db = self.db()
        transaction = db.get(Transaction, transaction_id)
        transaction.category = "owner category"
        db.commit()
        db.close()

        refused = self.client.post(f"/api/finance/imports/{preview['id']}/undo")
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertIn("changed after apply", refused.text)
        db = self.db()
        self.assertEqual(db.get(Transaction, transaction_id).category, "owner category")
        db.close()

    def test_undo_refuses_a_live_amount_edit_even_when_import_evidence_is_unchanged(self):
        source = (
            "Date,Description,Amount,Currency,Reference\n2026-07-01,Coffee,-10.00,CAD,amount-edit\n"
        )
        preview = self._preview(source, source_name="amount-edit.csv")
        applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        transaction_id = applied.json()["rows"][0]["created_transaction_id"]

        db = self.db()
        transaction = db.get(Transaction, transaction_id)
        transaction.amount = -99
        db.commit()
        db.close()

        refused = self.client.post(f"/api/finance/imports/{preview['id']}/undo")
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertIn("changed after apply", refused.text)
        db = self.db()
        self.assertEqual(db.get(Transaction, transaction_id).amount, -99)
        db.close()

    def test_apply_revalidates_a_previewed_duplicate_against_the_current_ledger(self):
        source = (
            "Date,Description,Amount,Currency,Reference\n"
            "2026-07-01,Coffee,-10.00,CAD,stable-row-id\n"
        )
        first = self._preview(source, source_name="stable.csv")
        applied = self.client.post(f"/api/finance/imports/{first['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        repeated = self._preview(source, source_name="stable.csv")
        self.assertEqual(repeated["rows"][0]["status"], "duplicate")
        self.assertTrue(repeated["rows"][0]["existing_transaction_id"])

        db = self.db()
        transaction = db.get(Transaction, repeated["rows"][0]["existing_transaction_id"])
        transaction.amount = -99
        transaction.original_amount_text = "-99"
        db.commit()
        db.close()

        rechecked = self.client.post(f"/api/finance/imports/{repeated['id']}/apply")

        self.assertEqual(rechecked.status_code, 200, rechecked.text)
        payload = rechecked.json()
        self.assertEqual(payload["status"], "preview")
        self.assertEqual(payload["rows"][0]["status"], "needs_review")
        self.assertIn("changed or was deleted", payload["rows"][0]["conflict_reason"])

    def test_identical_source_preview_uses_the_same_deterministic_no_id_identity(self):
        source = "Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n"
        first = self._preview(source, source_name="same-statement.csv")
        applied = self.client.post(f"/api/finance/imports/{first['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)

        repeated = self._preview(source, source_name="same-statement.csv")

        self.assertEqual(
            repeated["rows"][0]["stable_identity"], first["rows"][0]["stable_identity"]
        )
        self.assertEqual(repeated["rows"][0]["status"], "duplicate")

    def test_same_external_id_with_changed_values_is_a_conflict_and_never_posts(self):
        original = self._preview(
            "Transaction Date,Description,Debit,Credit,Transaction ID\n2026-07-01,Grocer,12.34,,same-id\n"
        )
        self.client.post(f"/api/finance/imports/{original['id']}/apply")
        changed = self._preview(
            "Transaction Date,Description,Debit,Credit,Transaction ID\n2026-07-01,Grocer,99.99,,same-id\n"
        )
        self.assertEqual(changed["counts"]["conflicts"], 1)
        self.assertIn("same source identity", changed["rows"][0]["conflict_reason"])
        applied = self.client.post(f"/api/finance/imports/{changed['id']}/apply")
        self.assertEqual(applied.status_code, 409, applied.text)
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 1)
        db.close()

    def test_same_import_identity_in_another_account_is_a_conflict(self):
        source = (
            "Transaction Date,Description,Debit,Credit,Transaction ID\n"
            "2026-07-01,Grocer,12.34,,cross-account-id\n"
        )
        preview = self._preview(source)
        identity = preview["rows"][0]["stable_identity"]
        other = self.client.post(
            "/api/money/accounts",
            json={"name": "other", "kind": "checking", "currency": "CAD", "opening": 0},
        ).json()
        db = self.db()
        db.add(
            Transaction(
                account_id=other["id"],
                date="2026-07-01",
                amount=-12.34,
                payee="Grocer",
                import_identity=identity,
                original_amount_text="-12.34",
                original_currency_code="CAD",
            )
        )
        db.commit()
        db.close()
        repeated = self._preview(source, source_name="same-row-again.csv")
        self.assertEqual(repeated["counts"]["conflicts"], 1)
        self.assertEqual(repeated["counts"]["duplicates"], 0)

    def test_identical_no_id_rows_use_statement_bound_line_identity(self):
        source = "Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n2026-07-01,Coffee,5,,\n"
        preview = self._preview(source)
        identities = [row["stable_identity"] for row in preview["rows"]]
        self.assertTrue(all(identities))
        self.assertNotEqual(identities[0], identities[1])
        self.assertEqual([row["status"] for row in preview["rows"]], ["pending"] * 2)
        applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 2)
        db.close()

        repeated = self._preview(source)
        self.assertEqual([row["status"] for row in repeated["rows"]], ["duplicate"] * 2)

    def test_separate_no_id_statements_share_match_fingerprint_but_require_review(self):
        source = "Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n"
        first = self._preview(source, source_name="july.csv")
        applied = self.client.post(f"/api/finance/imports/{first['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)

        second = self._preview(source, source_name="august.csv")

        self.assertNotEqual(
            first["rows"][0]["stable_identity"],
            second["rows"][0]["stable_identity"],
        )
        self.assertEqual(
            first["rows"][0]["parsed"]["match_fingerprint"],
            second["rows"][0]["parsed"]["match_fingerprint"],
        )
        self.assertEqual(second["counts"]["duplicates"], 0)
        self.assertEqual(second["rows"][0]["status"], "needs_review")
        self.assertIn("different statement", second["rows"][0]["conflict_reason"])

    def test_overlapping_no_id_statement_is_not_silently_deduplicated(self):
        original = self._preview("Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n")
        applied = self.client.post(f"/api/finance/imports/{original['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)

        overlap = self._preview(
            "Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n",
            source_name="overlap.csv",
        )

        self.assertEqual(
            overlap["rows"][0]["parsed"]["match_fingerprint"],
            original["rows"][0]["parsed"]["match_fingerprint"],
        )
        self.assertEqual(overlap["counts"]["duplicates"], 0)
        self.assertEqual(overlap["counts"]["conflicts"], 1)
        self.assertEqual(overlap["rows"][0]["status"], "needs_review")
        self.assertIn("no bank reference", overlap["rows"][0]["conflict_reason"])
        self.assertIn("different statement", overlap["rows"][0]["conflict_reason"])

    def test_corrected_no_id_statement_gets_a_new_source_bound_identity(self):
        original = self._preview(
            "Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n",
            source_name="stable-statement.csv",
        )
        applied = self.client.post(f"/api/finance/imports/{original['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)

        corrected = self._preview(
            "Date,Description,Debit,Credit\n2026-07-01,Coffee,6,,\n",
            source_name="stable-statement.csv",
        )

        self.assertNotEqual(
            corrected["rows"][0]["stable_identity"],
            original["rows"][0]["stable_identity"],
        )
        self.assertEqual(corrected["rows"][0]["status"], "pending")

    def test_apply_time_recheck_preserves_review_for_a_new_no_id_match(self):
        row = "2026-07-01,Coffee,5,,\n"
        waiting = self._preview("Date,Description,Debit,Credit\n" + row)
        later = self._preview(
            "Date,Description,Debit,Credit\n" + row + "2026-07-02,Grocer,12.34,,\n",
            source_name="later-statement.csv",
        )
        applied_later = self.client.post(f"/api/finance/imports/{later['id']}/apply")
        self.assertEqual(applied_later.status_code, 200, applied_later.text)
        self.assertEqual(applied_later.json()["counts"]["applied"], 2)

        rechecked = self.client.post(f"/api/finance/imports/{waiting['id']}/apply")

        self.assertEqual(rechecked.status_code, 200, rechecked.text)
        payload = rechecked.json()
        self.assertEqual(payload["status"], "preview")
        self.assertEqual(payload["counts"]["applied"], 0)
        self.assertEqual(payload["rows"][0]["status"], "needs_review")
        self.assertIn("no bank reference", payload["rows"][0]["conflict_reason"])
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 2)
        db.close()

    def test_owner_can_resolve_overlapping_no_id_row_as_duplicate(self):
        original = self._preview("Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n")
        applied = self.client.post(f"/api/finance/imports/{original['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        overlap = self._preview(
            "Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n",
            source_name="overlap.csv",
        )

        resolved = self.client.post(
            f"/api/finance/imports/{overlap['id']}/rows/{overlap['rows'][0]['id']}/resolve-match",
            json={"decision": "duplicate"},
        )

        self.assertEqual(resolved.status_code, 200, resolved.text)
        payload = resolved.json()
        self.assertEqual(payload["counts"]["conflicts"], 0)
        self.assertEqual(payload["rows"][0]["status"], "duplicate")
        decision = payload["receipt"]["row_match_decisions"][overlap["rows"][0]["id"]]
        self.assertEqual(decision["decision"], "duplicate")
        self.assertEqual(
            decision["original_stable_identity"],
            decision["resolved_stable_identity"],
        )

    def test_owner_can_import_overlapping_no_id_row_as_new_without_replay_duplicates(self):
        source = "Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n"
        original = self._preview(source)
        applied = self.client.post(f"/api/finance/imports/{original['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        overlap = self._preview(source, source_name="overlap.csv")
        original_identity = overlap["rows"][0]["stable_identity"]

        resolved = self.client.post(
            f"/api/finance/imports/{overlap['id']}/rows/{overlap['rows'][0]['id']}/resolve-match",
            json={"decision": "new"},
        )

        self.assertEqual(resolved.status_code, 200, resolved.text)
        resolved_payload = resolved.json()
        approved_identity = resolved_payload["rows"][0]["stable_identity"]
        self.assertEqual(resolved_payload["rows"][0]["status"], "pending")
        self.assertNotEqual(approved_identity, original_identity)
        applied_new = self.client.post(f"/api/finance/imports/{overlap['id']}/apply")
        self.assertEqual(applied_new.status_code, 200, applied_new.text)
        self.assertEqual(applied_new.json()["counts"]["applied"], 1)

        replay = self._preview(source, source_name="overlap.csv")
        replay_resolved = self.client.post(
            f"/api/finance/imports/{replay['id']}/rows/{replay['rows'][0]['id']}/resolve-match",
            json={"decision": "new"},
        )
        self.assertEqual(replay_resolved.status_code, 200, replay_resolved.text)
        self.assertEqual(replay_resolved.json()["rows"][0]["status"], "duplicate")
        replay_decision = replay_resolved.json()["receipt"]["row_match_decisions"][
            replay["rows"][0]["id"]
        ]
        self.assertEqual(replay_decision["resolved_stable_identity"], approved_identity)

    def test_match_resolution_rejects_invalid_decisions_and_unrelated_review_rows(self):
        original = self._preview("Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n")
        self.client.post(f"/api/finance/imports/{original['id']}/apply")
        overlap = self._preview(
            "Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n",
            source_name="overlap.csv",
        )
        invalid = self.client.post(
            f"/api/finance/imports/{overlap['id']}/rows/{overlap['rows'][0]['id']}/resolve-match",
            json={"decision": "maybe"},
        )
        self.assertEqual(invalid.status_code, 400, invalid.text)

        notification = self._preview(
            "2026年7月4日，您尾号1234账户于商户:便利店支出人民币38.60元",
            profile="cmb-notification",
        )
        unrelated = self.client.post(
            f"/api/finance/imports/{notification['id']}/rows/{notification['rows'][0]['id']}/resolve-match",
            json={"decision": "duplicate"},
        )
        self.assertEqual(unrelated.status_code, 409, unrelated.text)

    def test_external_identities_do_not_change_when_statement_rows_are_reordered(self):
        header = "Date,Description,Debit,Credit,Transaction ID\n"
        first = finance_imports.parse(
            "cibc-csv",
            header + "2026-07-01,Coffee,5,,external-a\n" + "2026-07-01,Coffee,5,,external-b\n",
            account_id=self.account["id"],
            requested_currency="CAD",
        )
        reordered = finance_imports.parse(
            "cibc-csv",
            header + "2026-07-01,Coffee,5,,external-b\n" + "2026-07-01,Coffee,5,,external-a\n",
            account_id=self.account["id"],
            requested_currency="CAD",
        )
        identities = {row["parsed"]["external_id"]: row["stable_identity"] for row in first}
        reordered_identities = {
            row["parsed"]["external_id"]: row["stable_identity"] for row in reordered
        }
        self.assertEqual(identities, reordered_identities)

    def test_zero_unused_debit_or_credit_cells_are_not_ambiguous(self):
        preview = self._preview(
            "Date,Description,Debit,Credit,Currency\n"
            "2026-07-01,Debit,12.34,0.00,CAD\n"
            "2026-07-02,Credit,0.00,8.50,CAD\n"
        )
        self.assertEqual(preview["counts"]["pending"], 2)
        self.assertEqual(
            [row["parsed"]["amount_text"] for row in preview["rows"]],
            ["-12.34", "8.50"],
        )

    def test_cibc_funds_out_and_funds_in_columns_map_to_signed_amounts(self):
        preview = self._preview(
            "Date,Description,Funds Out,Funds In,Currency\n"
            "2026-07-01,Debit,12.34,,CAD\n"
            "2026-07-02,Credit,,8.50,CAD\n"
        )
        self.assertEqual(preview["counts"]["pending"], 2)
        self.assertEqual(
            [row["parsed"]["amount_text"] for row in preview["rows"]],
            ["-12.34", "8.50"],
        )

    def test_ambiguous_slash_date_stays_in_review(self):
        preview = self._preview(
            "Date,Description,Amount,Currency\n03/04/2026,Ambiguous date,-12.34,CAD\n"
        )
        self.assertEqual(preview["rows"][0]["status"], "needs_review")
        self.assertIn("date", preview["rows"][0]["conflict_reason"])

    def test_unambiguous_slash_dates_parse_in_the_only_valid_order(self):
        preview = self._preview(
            "Date,Description,Amount,Currency\n13/04/2026,Day first,-1.00,CAD\n"
            "04/13/2026,Month first,-2.00,CAD\n"
        )
        self.assertEqual(
            [row["parsed"]["date"] for row in preview["rows"]],
            ["2026-04-13", "2026-04-13"],
        )

    def test_cmb_statement_profile_maps_chinese_columns_and_exact_cny(self):
        preview = self._preview(
            "交易日期,交易摘要,支出金额,收入金额,交易币种,交易流水号\n"
            "2026-07-04,午餐,38.60,,CNY,cmb-1\n"
            "2026-07-05,退款,,5.20,CNY,cmb-2\n",
            profile="cmb-csv",
        )
        self.assertEqual(
            [row["parsed"]["amount_text"] for row in preview["rows"]], ["-38.60", "5.20"]
        )
        self.assertTrue(all(row["parsed"]["currency_code"] == "CNY" for row in preview["rows"]))

    def test_cmb_notification_requires_date_amount_direction_and_account_suffix(self):
        content = (
            "招商银行：您尾号1234账户于2026年07月06日支出人民币88.20元，商户茶馆。\n"
            "招商银行：2026年07月07日人民币10元。\n"
        )
        preview = self._preview(
            content, profile="cmb-notification", source_name="notifications.txt"
        )
        self.assertEqual(preview["counts"]["pending"], 0)
        self.assertEqual(preview["counts"]["conflicts"], 2)
        self.assertEqual(preview["rows"][0]["parsed"]["amount_text"], "-88.20")
        self.assertEqual(preview["rows"][0]["parsed"]["payee"], "茶馆")
        self.assertIn("confirm account ending 1234", preview["rows"][0]["conflict_reason"])
        self.assertEqual(preview["rows"][1]["status"], "needs_review")
        mismatched = self.client.post(
            f"/api/finance/imports/{preview['id']}/rows/{preview['rows'][0]['id']}/confirm-account",
            json={"account_id": self.account["id"], "account_suffix": "9999"},
        )
        self.assertEqual(mismatched.status_code, 409, mismatched.text)
        confirmed = self.client.post(
            f"/api/finance/imports/{preview['id']}/rows/{preview['rows'][0]['id']}/confirm-account",
            json={"account_id": self.cmb_account["id"], "account_suffix": "1234"},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        confirmed_payload = confirmed.json()
        self.assertEqual(confirmed_payload["counts"]["pending"], 1)
        self.assertEqual(
            confirmed_payload["receipt"]["confirmed_account_suffixes"]["1234"]["account_id"],
            self.cmb_account["id"],
        )
        applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 409, applied.text)
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_unconfirmed_notification_never_posts_to_the_selected_account(self):
        preview = self._preview(
            "招商银行：您尾号9876账户于2026年07月06日支出人民币18.20元，商户茶馆。",
            profile="cmb-notification",
            source_name="notification.txt",
        )
        self.assertEqual(preview["rows"][0]["status"], "needs_review")
        applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 409, applied.text)
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_legacy_import_currency_must_match_the_selected_account(self):
        response = self.client.post(
            "/api/finance/imports/preview",
            json={
                "account_id": self.account["id"],
                "profile": "cmb-csv",
                "source_name": "wrong-account.csv",
                "content": (
                    "交易日期,交易摘要,支出金额,收入金额,交易币种,交易流水号\n"
                    "2026-07-04,午餐,38.60,,CNY,cmb-wrong-account\n"
                ),
                "original_currency_code": "CNY",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        self.assertEqual(preview["rows"][0]["status"], "needs_review")
        self.assertIn("does not match", preview["rows"][0]["conflict_reason"])
        applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 409, applied.text)

    def test_legacy_apply_rechecks_that_the_preview_account_still_exists(self):
        preview = self._preview("Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n")
        deleted = self.client.delete(f"/api/money/accounts/{self.account['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)

        response = self.client.post(f"/api/finance/imports/{preview['id']}/apply")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "preview")
        self.assertEqual(payload["rows"][0]["status"], "needs_review")
        self.assertIn("deleted after preview", payload["rows"][0]["conflict_reason"])
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_legacy_apply_rechecks_the_preview_account_currency(self):
        preview = self._preview("Date,Description,Debit,Credit\n2026-07-01,Coffee,5,,\n")
        changed = self.client.patch(
            f"/api/money/accounts/{self.account['id']}", json={"currency": "USD"}
        )
        self.assertEqual(changed.status_code, 200, changed.text)

        response = self.client.post(f"/api/finance/imports/{preview['id']}/apply")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "preview")
        self.assertEqual(payload["rows"][0]["status"], "needs_review")
        self.assertIn("currency changed after preview", payload["rows"][0]["conflict_reason"])
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_legacy_receipt_persists_an_explicit_row_currency_over_the_profile_default(self):
        usd_account = self.client.post(
            "/api/money/accounts",
            json={"name": "USD account", "kind": "checking", "currency": "USD", "opening": 0},
        ).json()
        preview_response = self.client.post(
            "/api/finance/imports/preview",
            json={
                "account_id": usd_account["id"],
                "profile": "cibc-csv",
                "source_name": "usd.csv",
                "content": "Date,Description,Amount,Currency\n2026-07-01,Coffee,-5.00,USD\n",
            },
        )
        self.assertEqual(preview_response.status_code, 200, preview_response.text)
        preview = preview_response.json()
        self.assertEqual(preview["original_currency_code"], "USD")
        self.assertEqual(preview["rows"][0]["status"], "pending")

        applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")

        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(applied.json()["status"], "applied")
        db = self.db()
        batch = db.get(FinanceImportBatch, preview["id"])
        self.assertEqual(batch.original_currency_code, "USD")
        self.assertEqual(db.query(Transaction).filter_by(account_id=usd_account["id"]).count(), 1)
        db.close()

    def test_notification_identity_is_stable_across_separate_uploads(self):
        message = "招商银行：您尾号1234账户于2026年07月06日支出人民币88.20元，商户茶馆，参考号A。"
        first = finance_imports.parse(
            "cmb-notification",
            message,
            account_id=self.account["id"],
            requested_currency="CNY",
        )[0]
        repeated = finance_imports.parse(
            "cmb-notification",
            message,
            account_id=self.account["id"],
            requested_currency="CNY",
        )[0]
        self.assertEqual(first["parsed"]["external_id"], "A")
        self.assertEqual(first["parsed"]["external_id"], repeated["parsed"]["external_id"])
        self.assertEqual(first["stable_identity"], repeated["stable_identity"])

    def test_distinct_notifications_with_the_same_posted_values_do_not_collapse(self):
        first_message = (
            "招商银行：您尾号1234账户于2026年07月06日支出人民币88.20元，商户茶馆，参考号A。"
        )
        second_message = (
            "招商银行：您尾号1234账户于2026年07月06日支出人民币88.20元，商户茶馆，参考号B。"
        )
        first = finance_imports.parse(
            "cmb-notification",
            first_message,
            account_id=self.account["id"],
            requested_currency="CNY",
        )[0]
        second = finance_imports.parse(
            "cmb-notification",
            second_message,
            account_id=self.account["id"],
            requested_currency="CNY",
        )[0]
        self.assertEqual(first["parsed"]["date"], second["parsed"]["date"])
        self.assertEqual(first["parsed"]["amount_text"], second["parsed"]["amount_text"])
        self.assertEqual(first["parsed"]["payee"], second["parsed"]["payee"])
        self.assertEqual(first["parsed"]["external_id"], "A")
        self.assertEqual(second["parsed"]["external_id"], "B")
        self.assertNotEqual(first["parsed"]["external_id"], second["parsed"]["external_id"])
        self.assertNotEqual(first["stable_identity"], second["stable_identity"])

    def test_identical_notifications_without_a_bank_reference_fail_closed(self):
        message = "招商银行：您尾号1234账户于2026年07月06日支出人民币88.20元，商户茶馆。"
        rows = finance_imports.parse(
            "cmb-notification",
            f"{message}\n{message}",
            account_id=self.account["id"],
            requested_currency="CNY",
        )
        self.assertEqual([row["parsed"]["external_id"] for row in rows], ["", ""])
        self.assertEqual([row["stable_identity"] for row in rows], ["", ""])
        self.assertTrue(all("no bank reference" in row["error"] for row in rows))

    def test_cmb_notification_rejects_a_conflicting_requested_currency(self):
        response = self.client.post(
            "/api/finance/imports/preview",
            json={
                "account_id": self.account["id"],
                "profile": "cmb-notification",
                "source_name": "notification.txt",
                "content": "招商银行：您尾号1234账户于2026年07月06日支出人民币88.20元，商户茶馆。",
                "original_currency_code": "CAD",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        row = response.json()["rows"][0]
        self.assertEqual(row["status"], "needs_review")
        self.assertIn("conflicts", row["conflict_reason"])

    def test_nonfinite_statement_amount_is_review_only_and_never_posts(self):
        preview = self._preview("Date,Description,Amount,Currency\n2026-07-01,Broken,NaN,CAD\n")
        self.assertEqual(preview["rows"][0]["status"], "needs_review")
        response = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(response.status_code, 409, response.text)
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_extreme_statement_exponent_is_bounded_before_fixed_point_formatting(self):
        preview = self._preview(
            "Date,Description,Amount,Currency\n2026-07-01,Huge exponent,1e999999999,CAD\n"
        )
        self.assertEqual(preview["rows"][0]["status"], "needs_review")
        self.assertIn("exponent is out of range", preview["rows"][0]["conflict_reason"])
        response = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(response.status_code, 409, response.text)
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_ambiguous_currency_is_review_only_and_never_posts(self):
        preview = self._preview("Date,Description,Amount,Currency\n2026-07-01,Ambiguous,10.00,$\n")
        self.assertEqual(preview["rows"][0]["status"], "needs_review")
        self.assertIn("currency", preview["rows"][0]["conflict_reason"])
        response = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(response.status_code, 409, response.text)
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_unsupported_amount_precision_is_rejected_before_apply_claim(self):
        preview = self._preview("Date,Description,Amount,Currency\n2026-07-01,Precise,1.001,CAD\n")
        self.assertEqual(preview["rows"][0]["status"], "needs_review")
        self.assertIn("two decimal places", preview["rows"][0]["conflict_reason"])
        response = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(response.status_code, 409, response.text)
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_legacy_amount_that_float_would_round_is_rejected_before_write(self):
        preview = self._preview(
            "Date,Description,Amount,Currency\n"
            "2026-07-01,Too large for exact legacy storage,90071992547409.91,CAD\n"
        )
        self.assertEqual(preview["rows"][0]["status"], "pending")

        applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")

        self.assertEqual(applied.status_code, 200, applied.text)
        row = applied.json()["rows"][0]
        self.assertEqual(row["status"], "needs_review")
        self.assertIn("represented exactly", row["conflict_reason"])
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_apply_preflights_new_conflicts_before_writing_any_row(self):
        preview = self._preview(
            "Date,Description,Amount,Currency,Reference\n"
            "2026-07-01,Safe,20.00,CAD,race-1\n"
            "2026-07-02,Changed,10.00,CAD,race-2\n"
        )
        conflicting = preview["rows"][1]
        db = self.db()
        db.add(
            Transaction(
                account_id=self.account["id"],
                date="2026-07-02",
                amount=99,
                payee="different row",
                import_identity=conflicting["stable_identity"],
                original_amount_text="99",
                original_currency_code="CAD",
                base_amount_text="99",
                base_currency_code="CAD",
            )
        )
        db.commit()
        db.close()
        applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        payload = applied.json()
        self.assertEqual(payload["status"], "preview")
        self.assertEqual(payload["counts"]["conflicts"], 1)
        self.assertEqual(payload["counts"]["applied"], 0)
        self.assertEqual(payload["rows"][0]["status"], "pending")
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 1)
        db.close()

    def test_conflicting_external_ids_are_blocked_during_preview_before_any_apply(self):
        preview = self._preview(
            "Date,Description,Amount,Currency,Reference\n"
            "2026-07-01,Coffee,10.00,CAD,same-id\n"
            "2026-07-02,Changed,20.00,CAD,same-id\n"
        )
        self.assertEqual(preview["counts"]["conflicts"], 2)
        self.assertEqual([row["status"] for row in preview["rows"]], ["conflict", "conflict"])
        response = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(response.status_code, 409, response.text)
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_exact_repeated_external_id_keeps_one_pending_row(self):
        preview = self._preview(
            "Date,Description,Amount,Currency,Reference\n"
            "2026-07-01,Coffee,10.00,CAD,same-id\n"
            "2026-07-01,Coffee,10.00,CAD,same-id\n"
        )
        self.assertEqual(preview["counts"]["pending"], 1)
        self.assertEqual(preview["counts"]["duplicates"], 1)
        applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(applied.json()["counts"]["applied"], 1)
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 1)
        db.close()

    def test_fallback_match_fingerprint_normalizes_decimal_text_and_includes_currency(self):
        header = "Date,Description,Amount,Currency\n"
        first = finance_imports.parse(
            "cibc-csv",
            header + "2026-07-01,Coffee,10.0,CAD\n",
            account_id=self.account["id"],
            statement_identity="statement.csv",
        )[0]
        equivalent = finance_imports.parse(
            "cibc-csv",
            header + "2026-07-01,Coffee,10.00,CAD\n",
            account_id=self.account["id"],
            statement_identity="statement.csv",
        )[0]
        different_currency = finance_imports.parse(
            "cibc-csv",
            header + "2026-07-01,Coffee,10.00,USD\n",
            account_id=self.account["id"],
            statement_identity="statement.csv",
        )[0]
        self.assertEqual(first["stable_identity"], equivalent["stable_identity"])
        self.assertEqual(first["stable_identity"], different_currency["stable_identity"])
        self.assertEqual(
            first["parsed"]["match_fingerprint"],
            equivalent["parsed"]["match_fingerprint"],
        )
        self.assertNotEqual(
            first["parsed"]["match_fingerprint"],
            different_currency["parsed"]["match_fingerprint"],
        )

    def test_same_filename_and_row_identity_is_bound_to_statement_content(self):
        header = "Date,Description,Amount,Currency\n"
        first = self._preview(header + "2026-07-01,Coffee,10.00,CAD\n")
        repeated = self._preview(header + "2026-07-01,Coffee,10.00,CAD\n")
        changed = self._preview(header + "2026-07-02,Transit,12.00,CAD\n")
        self.assertEqual(
            first["rows"][0]["stable_identity"], repeated["rows"][0]["stable_identity"]
        )
        self.assertNotEqual(
            first["rows"][0]["stable_identity"], changed["rows"][0]["stable_identity"]
        )

    def test_receipt_does_not_store_whole_source_and_rows_are_auditable(self):
        source = "Date,Description,Debit,Credit,Reference\n2026-07-01,Coffee,4.50,,ref-1\n"
        preview = self._preview(source)
        db = self.db()
        batch = db.get(FinanceImportBatch, preview["id"])
        receipt = json.loads(batch.receipt_json)
        self.assertEqual(receipt["source_sha256"], preview["source_sha256"])
        self.assertEqual(
            receipt,
            {
                "version": 1,
                "account_id": self.account["id"],
                "profile": "cibc-csv",
                "source_name": "statement.csv",
                "source_sha256": preview["source_sha256"],
                "original_currency_code": "CAD",
                "ledger_backend": "alles",
            },
        )
        row = db.query(FinanceImportRow).filter_by(batch_id=preview["id"]).one()
        self.assertEqual(json.loads(row.raw_json)["Description"], "Coffee")
        db.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
