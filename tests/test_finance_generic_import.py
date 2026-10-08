import csv
import io
from decimal import Decimal
from unittest.mock import patch

from core.database import CategoryRule, FinanceLedgerState, TagRule
from tests._client import ApiTest


class GenericFinanceImportTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.accounts = [
            self.client.post(
                "/api/money/accounts",
                json={
                    "name": name,
                    "currency": currency,
                    "opening": 100,
                },
            ).json()
            for name, currency in [("first account", "CAD"), ("chosen account", "USD")]
        ]

    def preview(self, content, name="daily.csv"):
        response = self.client.post(
            "/api/finance/imports/preview",
            json={
                "account_id": self.accounts[1]["id"],
                "profile": "generic-csv",
                "source_name": name,
                "content": content,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def transactions(self):
        response = self.client.get("/api/money/transactions")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_preview_apply_retry_preserves_chosen_account_and_metadata(self):
        content = 'date,payee,amount,category,notes,tags,reference\n2026-10-01,grocer,-12.34,food,weekly shop,"food,home",ref-1\n'
        batch = self.preview(content)
        self.assertEqual(self.transactions(), [])
        self.assertEqual(batch["counts"]["pending"], 1)
        self.assertEqual(batch["receipt"]["account_name"], "chosen account")
        self.assertEqual(batch["rows"][0]["parsed"]["currency_code"], "USD")
        for _ in range(2):
            response = self.client.post(f"/api/finance/imports/{batch['id']}/apply")
            self.assertEqual(response.status_code, 200, response.text)
        rows = self.transactions()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["account_id"], self.accounts[1]["id"])
        self.assertEqual(Decimal(row["original_amount_text"]), Decimal("-12.34"))
        self.assertEqual(row["original_currency_code"], "USD")
        self.assertEqual(
            (row["category"], row["notes"], row["tags"]), ("food", "weekly shop", "food,home")
        )
        duplicate = self.preview(content)
        self.assertEqual(duplicate["counts"]["duplicates"], 1)
        changed = self.preview(content.replace("weekly shop", "changed note"))
        self.assertEqual(changed["counts"]["conflicts"], 1)
        response = self.client.post(f"/api/finance/imports/{batch['id']}/undo")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.transactions(), [])

    def test_undo_preserves_changed_tags(self):
        batch = self.preview("date,payee,amount\n2026-10-01,grocer,-2.00\n")
        self.assertEqual(
            self.client.post(f"/api/finance/imports/{batch['id']}/apply").status_code, 200
        )
        row = self.transactions()[0]
        self.assertEqual(
            self.client.patch(
                f"/api/money/transactions/{row['id']}", json={"tags": "owner edit"}
            ).status_code,
            200,
        )
        response = self.client.post(f"/api/finance/imports/{batch['id']}/undo")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.transactions()[0]["tags"], "owner edit")

    def test_reordered_headers_are_not_positional_bank_rows(self):
        batch = self.preview("payee,amount,date\ncoffee,-3.25,2026-10-01\n")
        self.assertEqual(batch["counts"]["pending"], 1)
        self.assertEqual(batch["rows"][0]["parsed"]["payee"], "coffee")
        invalid = self.preview("coffee,-3.25,2026-10-01\nother,-1.00,2026-10-02\n")
        self.assertEqual(invalid["counts"]["pending"], 0)
        self.assertEqual(self.transactions(), [])

    def test_explicit_currency_mismatch_and_precision_need_review(self):
        for content in [
            "date,amount,currency\n2026-10-01,-1.00,CAD\n",
            "date,amount\n2026-10-01,-1.001\n",
            "date,debit,credit\n2026-10-01,1.00,2.00\n",
        ]:
            with self.subTest(content=content):
                batch = self.preview(content)
                self.assertEqual(batch["counts"]["pending"], 0)
                self.assertEqual(batch["counts"]["conflicts"], 1)
        self.assertEqual(self.transactions(), [])

    def test_exported_columns_keep_their_meaning(self):
        saved = self.client.post(
            "/api/money/transactions",
            json={
                "account_id": self.accounts[0]["id"],
                "date": "2026-10-01",
                "amount": -9.87,
                "payee": "grocer",
                "category": "food",
                "notes": "weekly shop",
                "tags": "food,home",
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        exported = self.client.get("/api/money/transactions/export.csv")
        self.assertEqual(exported.status_code, 200)
        batch = self.preview(exported.text)
        self.assertEqual(batch["counts"]["pending"], 1)
        self.assertEqual(
            self.client.post(f"/api/finance/imports/{batch['id']}/apply").status_code, 200
        )
        imported = next(
            row for row in self.transactions() if row["account_id"] == self.accounts[1]["id"]
        )
        original = next(csv.DictReader(io.StringIO(exported.text)))
        for field in ["payee", "category", "notes", "tags"]:
            self.assertEqual(imported[field], original[field])

    def test_existing_local_rules_are_visible_in_preview_and_frozen_until_apply(self):
        with self.db() as db:
            rule = CategoryRule(match="grocer", category="food")
            db.add(rule)
            db.add(TagRule(match="grocer", tags="food,home"))
            db.commit()
        batch = self.preview("date,payee,amount,tags\n2026-10-01,grocer,-2.00,local\n")
        parsed = batch["rows"][0]["parsed"]
        self.assertEqual(parsed["category"], "food")
        self.assertEqual(parsed["tags"], "local,food,home")
        with self.db() as db:
            db.query(CategoryRule).update({"category": "changed later"})
            db.commit()
        self.assertEqual(
            self.client.post(f"/api/finance/imports/{batch['id']}/apply").status_code, 200
        )
        self.assertEqual(self.transactions()[0]["category"], "food")

    def test_canonical_generic_import_uses_base_currency_and_preserves_metadata(self):
        with self.db() as db:
            db.add(
                FinanceLedgerState(
                    id="primary",
                    mode="actual",
                    base_currency_code="USD",
                    active_run_id="fixture",
                    actual_budget_id="fixture",
                    actual_sync_id="fixture",
                    legacy_read_only=True,
                )
            )
            db.commit()
        actual_rows = []

        def create(_db, values, **kwargs):
            row = {
                **values,
                "id": kwargs["source_id"],
                "cleared": False,
                "original_amount_text": values["amount"],
                "original_currency_code": "USD",
                "base_amount_text": values["amount"],
                "base_currency_code": "USD",
                "import_identity": kwargs["import_identity"],
                "import_batch_id": kwargs["evidence"]["import_batch_id"],
                "import_source": kwargs["evidence"]["import_source"],
            }
            actual_rows.append(row)
            return row

        with (
            patch(
                "routes.finance_imports.actual_finance.accounts", return_value=[self.accounts[1]]
            ),
            patch(
                "routes.finance_imports.actual_finance.transactions",
                side_effect=lambda _db: list(actual_rows),
            ),
            patch(
                "routes.finance_imports.actual_finance.create_transaction", side_effect=create
            ) as writes,
            patch("routes.finance_imports.actual_finance.delete_transaction") as deletes,
        ):
            content = "date,payee,amount,category,notes,tags,reference\n2026-10-01,grocer,-1.25,food,weekly,home,ref-actual\n"
            batch = self.preview(content)
            self.assertEqual(batch["counts"]["pending"], 1)
            self.assertEqual(batch["rows"][0]["parsed"]["currency_code"], "USD")
            for _ in range(2):
                applied = self.client.post(f"/api/finance/imports/{batch['id']}/apply")
                self.assertEqual(applied.status_code, 200, applied.text)
            writes.assert_called_once()
            self.assertEqual(
                (actual_rows[0]["category"], actual_rows[0]["notes"], actual_rows[0]["tags"]),
                ("food", "weekly", "home"),
            )
            duplicate = self.preview(content)
            self.assertEqual(duplicate["counts"]["duplicates"], 1)
            saved_receipt = self.client.get(f"/api/finance/imports/{batch['id']}").json()
            with patch("routes.finance_imports.actual_finance.transactions") as reads:
                for tags in ("owner edit", "home"):
                    actual_rows[0]["tags"] = tags
                    blocked = self.client.post(f"/api/finance/imports/{batch['id']}/undo")
                    self.assertEqual(blocked.status_code, 409, blocked.text)
                    self.assertEqual(
                        blocked.json()["detail"],
                        "undo is unavailable for Actual transactions; review before deleting",
                    )
                    reads.assert_not_called()
                    deletes.assert_not_called()
                    self.assertEqual(actual_rows[0]["tags"], tags)
                    self.assertEqual(
                        self.client.get(f"/api/finance/imports/{batch['id']}").json(), saved_receipt
                    )

    def test_date_and_amount_only_keep_optional_text_empty(self):
        batch = self.preview("date,amount\n2026-10-01,-2.00\n")
        self.assertEqual(batch["counts"]["pending"], 1)
        self.assertEqual(
            self.client.post(f"/api/finance/imports/{batch['id']}/apply").status_code, 200
        )
        row = self.transactions()[0]
        for key in ["payee", "category", "notes", "tags"]:
            self.assertEqual(row[key], "")
