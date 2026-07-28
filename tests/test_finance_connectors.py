import base64
import json
from unittest import mock

from sqlalchemy import text

from core.database import FinanceConnection, Transaction
from services import finance_connectors
from tests._client import ApiTest


class Response:
    def __init__(self, payload=None, *, text_value="", status=200):
        self.payload = payload
        self.text = text_value
        self.status_code = status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("request failed")


class Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)


class FinanceConnectorTests(ApiTest):
    def test_simplefin_claim_is_one_time_and_secret_never_leaks(self):
        claim = "https://bridge.simplefin.org/simplefin/claim/test"
        setup = base64.urlsafe_b64encode(claim.encode()).decode()
        client = Client(Response(text_value="https://owner:private@bridge.simplefin.org/simplefin/access"))
        db = self.db()
        try:
            public = finance_connectors.connect_simplefin(db, setup, client=client, url_validator=lambda _url: True)
            self.assertEqual(public["provider"], "simplefin")
            self.assertNotIn("private", str(public))
            row = db.get(FinanceConnection, public["id"])
            self.assertIn("private", row.access_token)
            raw = db.execute(text("SELECT access_token FROM finance_connections WHERE id=:id"), {"id": row.id}).scalar_one()
            self.assertNotIn("private", raw)
        finally:
            db.close()

    def test_simplefin_rejects_non_https_claims(self):
        setup = base64.urlsafe_b64encode(b"http://127.0.0.1/claim").decode()
        with self.assertRaisesRegex(finance_connectors.FinanceConnectorError, "HTTPS"):
            finance_connectors.connect_simplefin(self.db(), setup, client=Client(), url_validator=lambda _url: True)

    def test_simplefin_rejects_private_claim_hosts(self):
        setup = base64.urlsafe_b64encode(b"https://127.0.0.1/claim").decode()
        with self.assertRaisesRegex(finance_connectors.FinanceConnectorError, "public HTTPS"):
            finance_connectors.connect_simplefin(
                self.db(), setup, client=Client(), url_validator=lambda _url: False
            )

    def test_simplefin_sync_is_read_only_and_idempotent(self):
        db = self.db()
        try:
            row = FinanceConnection(provider="simplefin", label="SimpleFIN", access_token="https://user:pass@example.com/access")
            db.add(row)
            db.commit()
            payload = {
                "accounts": [{
                    "id": "checking-1", "name": "daily", "currency": "CAD",
                    "transactions": [{"id": "txn-1", "posted": 1785000000, "amount": "-3.50", "description": "coffee"}],
                }]
            }
            first = finance_connectors.sync(db, row.id, client=Client(Response(payload)))
            second = finance_connectors.sync(db, row.id, client=Client(Response(payload)))
            self.assertEqual(first["created"], 1)
            self.assertEqual(second["updated"], 1)
            self.assertEqual(db.query(Transaction).count(), 1)
            txn = db.query(Transaction).one()
            self.assertEqual(txn.import_source, "simplefin")
            self.assertEqual(txn.amount, -3.5)
        finally:
            db.close()

    def test_plaid_link_exchange_and_cursor_sync(self):
        db = self.db()
        try:
            public = finance_connectors.configure_plaid(db, client_id="client", secret="secret", environment="sandbox")
            row = db.get(FinanceConnection, public["id"])
            link_client = Client(Response({"link_token": "link-sandbox-token", "expiration": "later"}))
            link = finance_connectors.plaid_link_token(db, row.id, client=link_client)
            self.assertEqual(link["link_token"], "link-sandbox-token")
            exchange_client = Client(Response({"access_token": "access-sandbox-token", "item_id": "item-1"}))
            finance_connectors.exchange_plaid_public_token(db, row.id, "public-sandbox-token", client=exchange_client)
            sync_client = Client(Response({
                "accounts": [{"account_id": "acct-1", "name": "chequing", "type": "depository", "balances": {"iso_currency_code": "CAD"}}],
                "added": [{"transaction_id": "ptxn-1", "account_id": "acct-1", "date": "2026-07-25", "amount": 7.25, "name": "store"}],
                "modified": [], "removed": [], "next_cursor": "cursor-1", "has_more": False,
            }))
            result = finance_connectors.sync(db, row.id, client=sync_client)
            self.assertEqual(result["created"], 1)
            self.assertEqual(db.get(FinanceConnection, row.id).cursor, "cursor-1")
            self.assertEqual(db.query(Transaction).one().amount, -7.25)
            request = sync_client.calls[0][2]["json"]
            self.assertNotIn("cursor", request)
        finally:
            db.close()

    def test_plaid_discovers_empty_accounts_and_applies_removed_transactions(self):
        db = self.db()
        try:
            row = FinanceConnection(
                provider="plaid",
                label="Plaid",
                environment="sandbox",
                client_id="client",
                client_secret="secret",
                access_token="access",
            )
            db.add(row)
            db.commit()
            first = Client(Response({
                "accounts": [
                    {"account_id": "acct-1", "name": "daily", "type": "depository", "balances": {"iso_currency_code": "CAD"}},
                    {"account_id": "acct-empty", "name": "empty", "type": "depository", "balances": {"iso_currency_code": "CAD"}},
                ],
                "added": [{"transaction_id": "remove-me", "account_id": "acct-1", "date": "2026-07-25", "amount": 4, "name": "old"}],
                "modified": [], "removed": [], "next_cursor": "one", "has_more": False,
            }))
            finance_connectors.sync(db, row.id, client=first)
            db.refresh(row)
            self.assertEqual(len(json.loads(row.account_map_json)), 2)
            second = Client(Response({
                "accounts": [], "added": [], "modified": [],
                "removed": [{"transaction_id": "remove-me"}],
                "next_cursor": "two", "has_more": False,
            }))
            result = finance_connectors.sync(db, row.id, client=second)
            self.assertEqual(result["removed"], 1)
            self.assertEqual(db.query(Transaction).count(), 0)
        finally:
            db.close()

    def test_simplefin_rejects_missing_posted_date(self):
        db = self.db()
        try:
            row = FinanceConnection(provider="simplefin", label="SimpleFIN", access_token="https://user:pass@example.com/access")
            db.add(row)
            db.commit()
            payload = {"accounts": [{"id": "one", "transactions": [{"id": "bad", "amount": "1"}]}]}
            with self.assertRaisesRegex(finance_connectors.FinanceConnectorError, "invalid transaction date"):
                finance_connectors.sync(db, row.id, client=Client(Response(payload)))
        finally:
            db.close()

    def test_api_public_payload_never_returns_tokens(self):
        db = self.db()
        try:
            row = FinanceConnection(provider="plaid", label="Plaid", client_id="client", client_secret="secret", access_token="access", item_id="item")
            db.add(row)
            db.commit()
        finally:
            db.close()
        payload = self.client.get("/api/finance/connections").json()
        serialized = json.dumps(payload)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("access", serialized)


class FinanceConnectorApiTests(ApiTest):
    def test_sync_and_disconnect_are_recent_owner_mutations(self):
        with mock.patch("routes.finance_connections.finance_connectors.sync", return_value={"ok": True}):
            response = self.client.post("/api/finance/connections/example/sync")
        self.assertEqual(response.status_code, 200)
