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
        client = Client(
            Response(text_value="https://owner:private@bridge.simplefin.org/simplefin/access")
        )
        db = self.db()
        try:
            public = finance_connectors.connect_simplefin(
                db, setup, client=client, url_validator=lambda _url: True
            )
            self.assertEqual(public["provider"], "simplefin")
            self.assertNotIn("private", str(public))
            row = db.get(FinanceConnection, public["id"])
            self.assertIn("private", row.access_token)
            raw = db.execute(
                text("SELECT access_token FROM finance_connections WHERE id=:id"), {"id": row.id}
            ).scalar_one()
            self.assertNotIn("private", raw)
        finally:
            db.close()

    def test_simplefin_rejects_non_https_claims(self):
        setup = base64.urlsafe_b64encode(b"http://127.0.0.1/claim").decode()
        with self.assertRaisesRegex(finance_connectors.FinanceConnectorError, "HTTPS"):
            finance_connectors.connect_simplefin(
                self.db(), setup, client=Client(), url_validator=lambda _url: True
            )

    def test_simplefin_rejects_private_claim_hosts(self):
        setup = base64.urlsafe_b64encode(b"https://127.0.0.1/claim").decode()
        with self.assertRaisesRegex(finance_connectors.FinanceConnectorError, "public HTTPS"):
            finance_connectors.connect_simplefin(
                self.db(), setup, client=Client(), url_validator=lambda _url: False
            )

    def test_simplefin_sync_is_read_only_and_idempotent(self):
        db = self.db()
        try:
            row = FinanceConnection(
                provider="simplefin",
                label="SimpleFIN",
                access_token="https://user:pass@example.com/access",
            )
            db.add(row)
            db.commit()
            payload = {
                "accounts": [
                    {
                        "id": "checking-1",
                        "name": "daily",
                        "currency": "CAD",
                        "transactions": [
                            {
                                "id": "txn-1",
                                "posted": 1785000000,
                                "amount": "-3.50",
                                "description": "coffee",
                            }
                        ],
                    }
                ]
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

    def simplefin_row(self, db, **extra):
        row = FinanceConnection(
            provider="simplefin",
            label="SimpleFIN",
            access_token="https://user:pass@example.com/access",
            **extra,
        )
        db.add(row)
        db.commit()
        return row

    def test_simplefin_asks_for_90_days_first_then_a_week_before_the_last_sync(self):
        from datetime import datetime, timedelta

        db = self.db()
        try:
            row = self.simplefin_row(db)
            client = Client(Response({"accounts": [], "errlist": []}))
            finance_connectors.sync(db, row.id, client=client)
            first = int(client.calls[0][2]["params"]["start-date"])
            now = datetime.now().timestamp()
            self.assertAlmostEqual(now - first, 90 * 86400, delta=600)
            row.last_synced_at = datetime(2026, 11, 1, 12, 0)
            db.commit()
            client = Client(Response({"accounts": [], "errlist": []}))
            with mock.patch.object(
                finance_connectors, "_now", return_value=datetime(2026, 11, 5, 12, 0)
            ):
                finance_connectors.sync(db, row.id, client=client)
            later = int(client.calls[0][2]["params"]["start-date"])
            expected = (datetime(2026, 11, 1, 12, 0) - timedelta(days=7)).replace(
                tzinfo=finance_connectors.UTC
            )
            self.assertEqual(later, int(expected.timestamp()))
            self.assertEqual(client.calls[0][2]["params"]["version"], "2")
        finally:
            db.close()

    def test_simplefin_brings_in_what_came_and_shows_its_messages(self):
        db = self.db()
        try:
            row = self.simplefin_row(db)
            payload = {
                "errlist": [{"code": "con.auth", "msg": "Scotiabank needs you to sign in again"}],
                "accounts": [
                    {
                        "id": "td-1",
                        "name": "Chequing",
                        "org": {"name": "TD Canada Trust"},
                        "currency": "cad",
                        "balance": "1200.50",
                        "transactions": [
                            {"id": "a", "posted": 1785000000, "amount": "-20.00", "payee": "x"},
                            {"id": "b", "posted": 1785000100, "amount": "500.00", "payee": "y"},
                        ],
                    }
                ],
            }
            result = finance_connectors.sync(db, row.id, client=Client(Response(payload)))
            self.assertEqual(result["created"], 2)
            self.assertEqual(result["status"], "connected")
            self.assertEqual(result["last_error"], "Scotiabank needs you to sign in again")
            from core.database import Account

            account = db.query(Account).one()
            self.assertEqual(account.name, "TD Canada Trust · Chequing")
            self.assertEqual(account.currency, "CAD")
            # the account starts so its balance matches the bank's: 1200.50 - (480.00)
            self.assertAlmostEqual(account.opening, 720.50, places=2)
        finally:
            db.close()

    def test_simplefin_sharing_no_accounts_says_so_on_the_row(self):
        db = self.db()
        try:
            row = self.simplefin_row(db)
            result = finance_connectors.sync(
                db, row.id, client=Client(Response({"accounts": [], "errlist": []}))
            )
            self.assertEqual(result["created"], 0)
            self.assertIn("shared no accounts yet", result["last_error"])
        finally:
            db.close()

    def test_simplefin_with_only_messages_fails_in_plain_words(self):
        db = self.db()
        try:
            row = self.simplefin_row(db)
            payload = {
                "errlist": [{"code": "gen.auth", "msg": "your token was revoked"}],
                "accounts": [],
            }
            with self.assertRaises(finance_connectors.FinanceConnectorError) as raised:
                finance_connectors.sync(db, row.id, client=Client(Response(payload)))
            self.assertEqual(str(raised.exception), "SimpleFIN says: your token was revoked")
            self.assertEqual(db.get(FinanceConnection, row.id).status, "error")
        finally:
            db.close()

    def test_timed_sync_keeps_going_past_a_failing_connection(self):
        db = self.db()
        try:
            broken = self.simplefin_row(db)
            fine = self.simplefin_row(db)
            waiting = FinanceConnection(provider="plaid", label="Plaid", status="link_required")
            db.add(waiting)
            db.commit()
            client = Client(
                Response({"errlist": [{"msg": "down"}], "accounts": []}),
                Response({"accounts": [], "errlist": []}),
            )
            self.assertEqual(finance_connectors.sync_all(db, client=client), 1)
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(
                db.get(FinanceConnection, broken.id).last_error, "SimpleFIN says: down"
            )
            self.assertEqual(db.get(FinanceConnection, fine.id).status, "connected")
        finally:
            db.close()

    def test_plaid_link_exchange_and_cursor_sync(self):
        db = self.db()
        try:
            public = finance_connectors.configure_plaid(
                db,
                client_id="client",
                secret="secret",
                environment="sandbox",
                client=Client(Response({"institutions": []})),
            )
            row = db.get(FinanceConnection, public["id"])
            link_client = Client(
                Response({"link_token": "link-sandbox-token", "expiration": "later"})
            )
            link = finance_connectors.plaid_link_token(db, row.id, client=link_client)
            self.assertEqual(link["link_token"], "link-sandbox-token")
            self.assertFalse(link["update_mode"])
            exchange_client = Client(
                Response({"access_token": "access-sandbox-token", "item_id": "item-1"})
            )
            finance_connectors.exchange_plaid_public_token(
                db, row.id, "public-sandbox-token", client=exchange_client
            )
            sync_client = Client(
                Response(
                    {
                        "accounts": [
                            {
                                "account_id": "acct-1",
                                "name": "chequing",
                                "type": "depository",
                                "balances": {"iso_currency_code": "CAD"},
                            }
                        ],
                        "added": [
                            {
                                "transaction_id": "ptxn-1",
                                "account_id": "acct-1",
                                "date": "2026-07-25",
                                "amount": 7.25,
                                "name": "store",
                            }
                        ],
                        "modified": [],
                        "removed": [],
                        "next_cursor": "cursor-1",
                        "has_more": False,
                    }
                )
            )
            result = finance_connectors.sync(db, row.id, client=sync_client)
            self.assertEqual(result["created"], 1)
            self.assertEqual(db.get(FinanceConnection, row.id).cursor, "cursor-1")
            self.assertEqual(db.query(Transaction).one().amount, -7.25)
            request = sync_client.calls[0][2]["json"]
            self.assertNotIn("cursor", request)
        finally:
            db.close()

    def plaid_answers(self, **by_environment):
        """a fake plaid: each environment answers with the payload given for it."""

        class Plaid:
            def __init__(self):
                self.calls = []

            def post(self, url, **kwargs):
                self.calls.append((url, kwargs["json"]))
                name = "sandbox" if "sandbox." in url else "production"
                payload = by_environment[name]
                return Response(payload, status=400 if "error_code" in payload else 200)

        return Plaid()

    WRONG_KEYS = {
        "error_type": "INVALID_INPUT",
        "error_code": "INVALID_API_KEYS",
        "error_message": "invalid client_id or secret provided",
        "display_message": None,
    }

    def test_plaid_keys_are_trimmed_and_checked_when_saved(self):
        plaid = self.plaid_answers(production={"institutions": []}, sandbox=self.WRONG_KEYS)
        db = self.db()
        try:
            public = finance_connectors.configure_plaid(
                db,
                client_id=" abc \n",
                secret="  s3 cr\net\n",
                environment="production",
                client=plaid,
            )
            row = db.get(FinanceConnection, public["id"])
            self.assertEqual((row.client_id, row.client_secret), ("abc", "s3cret"))
            self.assertEqual(plaid.calls[0][1]["client_id"], "abc")
            self.assertEqual(plaid.calls[0][1]["secret"], "s3cret")
            self.assertEqual(public["environment"], "production")
            self.assertNotIn("message", public)
            self.assertEqual(len(plaid.calls), 1)
        finally:
            db.close()

    def test_sandbox_keys_for_a_real_bank_are_refused_not_switched(self):
        # sandbox's bank window only takes plaid's test login, so a real bank could never sign in
        plaid = self.plaid_answers(production=self.WRONG_KEYS, sandbox={"institutions": []})
        db = self.db()
        try:
            with self.assertRaises(finance_connectors.FinanceConnectorError) as raised:
                finance_connectors.configure_plaid(
                    db,
                    client_id="abc",
                    secret="sandbox-secret",
                    environment="production",
                    client=plaid,
                )
            self.assertIn("sandbox keys", str(raised.exception))
            self.assertIn("production secret", str(raised.exception))
            self.assertEqual(db.query(FinanceConnection).count(), 0)
        finally:
            db.close()

    def test_production_keys_for_test_data_switch_to_production_and_say_so(self):
        plaid = self.plaid_answers(production={"institutions": []}, sandbox=self.WRONG_KEYS)
        db = self.db()
        try:
            public = finance_connectors.configure_plaid(
                db,
                client_id="abc",
                secret="production-secret",
                environment="sandbox",
                client=plaid,
            )
            self.assertEqual(public["environment"], "production")
            self.assertIn("production", public["message"])
            self.assertEqual(db.get(FinanceConnection, public["id"]).environment, "production")
        finally:
            db.close()

    def test_keys_neither_environment_takes_show_plaids_own_error_and_save_nothing(self):
        plaid = self.plaid_answers(production=self.WRONG_KEYS, sandbox=self.WRONG_KEYS)
        db = self.db()
        try:
            with self.assertRaises(finance_connectors.FinanceConnectorError) as raised:
                finance_connectors.configure_plaid(
                    db, client_id="abc", secret="nope", environment="sandbox", client=plaid
                )
            self.assertIn("invalid client_id or secret provided", str(raised.exception))
            self.assertEqual(db.query(FinanceConnection).count(), 0)
        finally:
            db.close()

    def test_a_plaid_answer_that_is_not_about_the_keys_still_saves_them(self):
        # plaid checks the keys first, so a product setup error means the keys were accepted
        other = {"error_code": "INVALID_PRODUCT", "error_message": "not enabled"}
        plaid = self.plaid_answers(production=other, sandbox=self.WRONG_KEYS)
        db = self.db()
        try:
            public = finance_connectors.configure_plaid(
                db, client_id="abc", secret="s", environment="production", client=plaid
            )
            self.assertEqual(public["environment"], "production")
        finally:
            db.close()

    def test_an_unreachable_plaid_says_so_instead_of_blaming_the_keys(self):
        class Down:
            def post(self, *args, **kwargs):
                raise OSError("no route")

        db = self.db()
        try:
            with self.assertRaisesRegex(finance_connectors.FinanceConnectorError, "reach Plaid"):
                finance_connectors.configure_plaid(
                    db, client_id="abc", secret="s", environment="sandbox", client=Down()
                )
            self.assertEqual(db.query(FinanceConnection).count(), 0)
        finally:
            db.close()

    def test_a_failing_plaid_call_shows_plaids_message_and_code(self):
        db = self.db()
        try:
            row = FinanceConnection(
                provider="plaid",
                label="Plaid",
                environment="production",
                status="link_required",
                client_id="c",
                client_secret="s",
            )
            db.add(row)
            db.commit()
            with self.assertRaises(finance_connectors.FinanceConnectorError) as raised:
                finance_connectors.plaid_link_token(
                    db, row.id, client=Client(Response(self.WRONG_KEYS, status=400))
                )
            self.assertEqual(
                str(raised.exception), "invalid client_id or secret provided (INVALID_API_KEYS)"
            )
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
            first = Client(
                Response(
                    {
                        "accounts": [
                            {
                                "account_id": "acct-1",
                                "name": "daily",
                                "type": "depository",
                                "balances": {"iso_currency_code": "CAD"},
                            },
                            {
                                "account_id": "acct-empty",
                                "name": "empty",
                                "type": "depository",
                                "balances": {"iso_currency_code": "CAD"},
                            },
                        ],
                        "added": [
                            {
                                "transaction_id": "remove-me",
                                "account_id": "acct-1",
                                "date": "2026-07-25",
                                "amount": 4,
                                "name": "old",
                            }
                        ],
                        "modified": [],
                        "removed": [],
                        "next_cursor": "one",
                        "has_more": False,
                    }
                )
            )
            finance_connectors.sync(db, row.id, client=first)
            db.refresh(row)
            self.assertEqual(len(json.loads(row.account_map_json)), 2)
            second = Client(
                Response(
                    {
                        "accounts": [],
                        "added": [],
                        "modified": [],
                        "removed": [{"transaction_id": "remove-me"}],
                        "next_cursor": "two",
                        "has_more": False,
                    }
                )
            )
            result = finance_connectors.sync(db, row.id, client=second)
            self.assertEqual(result["removed"], 1)
            self.assertEqual(db.query(Transaction).count(), 0)
        finally:
            db.close()

    def test_simplefin_rejects_missing_posted_date(self):
        db = self.db()
        try:
            row = FinanceConnection(
                provider="simplefin",
                label="SimpleFIN",
                access_token="https://user:pass@example.com/access",
            )
            db.add(row)
            db.commit()
            payload = {"accounts": [{"id": "one", "transactions": [{"id": "bad", "amount": "1"}]}]}
            with self.assertRaisesRegex(
                finance_connectors.FinanceConnectorError, "invalid transaction date"
            ):
                finance_connectors.sync(db, row.id, client=Client(Response(payload)))
        finally:
            db.close()

    def test_api_public_payload_never_returns_tokens(self):
        db = self.db()
        try:
            row = FinanceConnection(
                provider="plaid",
                label="Plaid",
                client_id="client",
                client_secret="secret",
                access_token="access",
                item_id="item",
            )
            db.add(row)
            db.commit()
        finally:
            db.close()
        payload = self.client.get("/api/finance/connections").json()
        serialized = json.dumps(payload)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("access", serialized)


class FinanceConnectorApiTests(ApiTest):
    def test_oauth_return_is_a_no_store_page_with_local_resume_module(self):
        response = self.client.get("/api/finance/connections/plaid/return?oauth_state_id=synthetic")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("/static/js/finance_plaid_return.js", response.text)
        self.assertNotIn("synthetic", response.text)

    def test_plaid_reconnect_reuses_access_token_and_confirms_item(self):
        db = self.db()
        try:
            row = FinanceConnection(
                provider="plaid",
                label="Plaid",
                environment="sandbox",
                client_id="fake-client",
                client_secret="fake-secret",
                access_token="fake-access",
                item_id="fake-item",
                status="error",
            )
            db.add(row)
            db.commit()
            client = Client(Response({"link_token": "fake-link", "expiration": "later"}))
            uri = "https://alles.example/api/finance/connections/plaid/return"
            link = finance_connectors.plaid_link_token(db, row.id, redirect_uri=uri, client=client)
            self.assertTrue(link["update_mode"])
            self.assertEqual(link["redirect_uri"], uri)
            request = client.calls[0][2]["json"]
            self.assertEqual(request["access_token"], "fake-access")
            self.assertNotIn("products", request)
            with mock.patch(
                "services.finance_connectors.httpx.post",
                return_value=Response({"item": {"item_id": "fake-item", "error": None}}),
            ) as post:
                response = self.client.post(
                    f"/api/finance/connections/{row.id}/plaid/update-complete"
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "connected")
            self.assertTrue(post.call_args.args[0].endswith("/item/get"))
            db.refresh(row)
            self.assertEqual(row.access_token, "fake-access")
        finally:
            db.close()

    def test_plaid_link_skips_a_return_address_plaid_would_reject(self):
        db = self.db()
        try:
            row = FinanceConnection(
                provider="plaid",
                label="Plaid",
                environment="production",
                client_id="fake-client",
                client_secret="fake-secret",
                status="link_required",
            )
            db.add(row)
            db.commit()
            client = Client(Response({"link_token": "fake-link", "expiration": "later"}))
            uri = "http://alles.example/api/finance/connections/plaid/return"
            link = finance_connectors.plaid_link_token(db, row.id, redirect_uri=uri, client=client)
            self.assertEqual(link["redirect_uri"], "")
            self.assertNotIn("redirect_uri", client.calls[0][2]["json"])

            unregistered = Response(
                {
                    "error_message": "OAuth redirect URI must be configured in the developer dashboard"
                },
                status=400,
            )
            client = Client(
                unregistered, Response({"link_token": "fake-link", "expiration": "later"})
            )
            uri = "https://alles.example/api/finance/connections/plaid/return"
            link = finance_connectors.plaid_link_token(db, row.id, redirect_uri=uri, client=client)
            self.assertEqual(link["redirect_uri"], "")
            self.assertEqual(client.calls[0][2]["json"]["redirect_uri"], uri)
            self.assertNotIn("redirect_uri", client.calls[1][2]["json"])

            client = Client(Response({"error_message": "invalid secret"}, status=400))
            with self.assertRaisesRegex(finance_connectors.FinanceConnectorError, "invalid secret"):
                finance_connectors.plaid_link_token(db, row.id, redirect_uri=uri, client=client)
        finally:
            db.close()

    def test_plaid_link_token_uses_the_browser_origin_behind_a_proxy(self):
        db = self.db()
        try:
            row = FinanceConnection(
                provider="plaid",
                label="Plaid",
                environment="production",
                client_id="fake-client",
                client_secret="fake-secret",
                status="link_required",
            )
            db.add(row)
            db.commit()
            row_id = row.id
        finally:
            db.close()
        with mock.patch(
            "services.finance_connectors.httpx.post",
            return_value=Response({"link_token": "fake-link", "expiration": "later"}),
        ) as post:
            response = self.client.post(
                f"/api/finance/connections/{row_id}/plaid/link-token",
                headers={"origin": "https://testserver"},
            )
        self.assertEqual(response.status_code, 200)
        expected = "https://testserver/api/finance/connections/plaid/return"
        self.assertEqual(response.json()["redirect_uri"], expected)
        self.assertEqual(post.call_args.kwargs["json"]["redirect_uri"], expected)

    def test_plaid_update_does_not_clear_provider_error_or_accept_a_different_item(self):
        db = self.db()
        try:
            row = FinanceConnection(
                provider="plaid",
                label="Plaid",
                environment="sandbox",
                client_id="fake-client",
                client_secret="fake-secret",
                access_token="fake-access",
                item_id="fake-item",
                status="error",
                last_error="original failure",
            )
            db.add(row)
            db.commit()
            for payload in [
                [],
                {},
                {"item": {"item_id": "other"}},
                {"item": {"item_id": "fake-item", "error": {"error_code": "ITEM_LOGIN_REQUIRED"}}},
            ]:
                with (
                    self.subTest(payload=payload),
                    self.assertRaises(finance_connectors.FinanceConnectorError),
                ):
                    finance_connectors.complete_plaid_update(
                        db, row.id, client=Client(Response(payload))
                    )
                self.assertEqual(row.status, "error")
                self.assertEqual(row.last_error, "original failure")
        finally:
            db.close()

    def test_sync_and_disconnect_are_recent_owner_mutations(self):
        with mock.patch(
            "routes.finance_connections.finance_connectors.sync", return_value={"ok": True}
        ):
            response = self.client.post("/api/finance/connections/example/sync")
        self.assertEqual(response.status_code, 200)
