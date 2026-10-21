import hashlib
import hmac
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, Mock

import pytest

from api.cron import outbox
from core import alerts


def test_webhook_uses_signature_of_exact_posted_body(monkeypatch):
    secret = "unit-test-secret"
    monkeypatch.setattr(alerts, "WEBHOOK_SIGNING_KEY", secret)
    monkeypatch.setattr(alerts, "WEBHOOK_URL", "https://example.test/hook")
    response = Mock()
    monkeypatch.setattr(alerts.requests, "post", Mock(return_value=response))

    payload = {"patch_id": "patch-1", "tier": "Warning", "zone": "A"}
    alerts.send_webhook_alert(payload)

    args, kwargs = alerts.requests.post.call_args
    body = kwargs["data"]
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert args[0] == "https://example.test/hook"
    assert json.loads(body) == payload
    assert kwargs["headers"]["X-Signature"] == expected
    assert kwargs["timeout"] > 0


def test_dedupe_key_is_stable_for_same_alert_identity():
    key = alerts.generate_dedupe_key(7, "patch-1", "scene-2", "Warning")
    assert key == "7|patch-1|scene-2|Warning"
    assert key == alerts.generate_dedupe_key(7, "patch-1", "scene-2", "Warning")

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    record = {
        "dedupe_key": key,
        "zone_id": 7,
        "patch_id": "patch-1",
        "scene_id": "scene-2",
        "tier": "Warning",
        "p_reach": 0.5,
        "eta_start": None,
        "eta_end": None,
        "payload": {},
        "channel": "all",
        "status": "pending",
        "attempts": 0,
        "next_attempt_at": None,
    }
    assert alerts.insert_alert(record, conn=connection) is None
    assert "ON CONFLICT (dedupe_key) DO NOTHING" in (
        connection.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
    )


def test_retry_delay_is_exponential_and_capped():
    assert alerts.retry_delay_seconds(1) == 60
    assert alerts.retry_delay_seconds(2) == 120
    assert alerts.retry_delay_seconds(20) == alerts.MAX_RETRY_DELAY_SECONDS


def test_zone_channel_configuration_is_used_for_delivery():
    configuration = {
        "telegram_chat_id": "1234",
        "email": "coast@example.test",
        "webhook_url": "https://example.test/alerts",
        "webhook_secret": "zone-secret",
    }
    assert alerts.resolve_delivery_channels("all", configuration) == [
        "telegram",
        "email",
        "webhook",
    ]
    assert alerts._channel_options(configuration)["webhook"] == {
        "url": "https://example.test/alerts",
        "signing_key": "zone-secret",
    }


@pytest.mark.parametrize(
    ("provider", "expected_url"),
    [
        ("resend", "https://api.resend.com/emails"),
        ("sendgrid", "https://api.sendgrid.com/v3/mail/send"),
    ],
)
def test_email_provider_uses_configured_bearer_key(monkeypatch, provider, expected_url):
    monkeypatch.setattr(alerts, "EMAIL_API_KEY", "email-secret")
    monkeypatch.setattr(alerts, "EMAIL_FROM", "alerts@example.test")
    monkeypatch.setattr(alerts, "EMAIL_PROVIDER", provider)
    monkeypatch.setattr(alerts, "EMAIL_TO", "coast@example.test")
    monkeypatch.setattr(alerts.requests, "post", Mock(return_value=Mock()))

    alerts.send_email_alert({"patch_id": "patch-3", "tier": "Warning"})

    args, kwargs = alerts.requests.post.call_args
    assert args[0] == expected_url
    assert kwargs["headers"]["Authorization"] == "Bearer email-secret"


@pytest.mark.parametrize(
    ("header", "secret", "expected"),
    [
        ("Bearer correct", "correct", True),
        ("bearer correct", "correct", True),
        ("Bearer wrong", "correct", False),
        ("correct", "correct", False),
        ("Bearer correct", "", False),
    ],
)
def test_cron_authorization_requires_bearer_secret(monkeypatch, header, secret, expected):
    monkeypatch.setattr(outbox, "CRON_SECRET", secret)
    assert outbox._authorized(header) is expected


def test_run_outbox_reports_dispatch_results(monkeypatch):
    outcomes = iter(("sent", "failed", None))
    monkeypatch.setattr(outbox, "_dispatch_one", lambda: next(outcomes))
    assert outbox.run_outbox(batch_size=5) == {
        "status": "success",
        "processed": 2,
        "sent": 1,
        "failed": 1,
    }


def test_failed_dispatch_updates_attempt_and_schedules_backoff(monkeypatch):
    class Cursor:
        def __init__(self):
            self.statements = []
            self.params = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, params=None):
            self.statements.append(statement)
            self.params.append(params)

        def fetchone(self):
            return {"alert_id": 42, "payload": {"patch_id": "p-1"}, "channel": "email", "attempts": 1}

    class Connection:
        def __init__(self):
            self.cur = Cursor()
            self.commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self.cur

        def commit(self):
            self.commits += 1

    connection = Connection()

    @contextmanager
    def connection_context():
        yield connection

    monkeypatch.setattr(outbox, "get_db_connection", connection_context)
    monkeypatch.setattr(
        alerts,
        "deliver_alert",
        Mock(side_effect=alerts.AlertDeliveryError("Provider request failed (HTTP 503)")),
    )

    assert outbox._dispatch_one() == "failed"
    claim_sql = connection.cur.statements[0]
    assert "FOR UPDATE OF a SKIP LOCKED" in claim_sql
    assert connection.cur.params[1] == (2, 120, "Provider request failed (HTTP 503)", 42)
    assert connection.commits == 1


def test_partial_delivery_retries_only_undelivered_channels(monkeypatch):
    class Cursor:
        def __init__(self):
            self.statements = []
            self.params = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, params=None):
            self.statements.append(statement)
            self.params.append(params)

        def fetchone(self):
            return {
                "alert_id": 43,
                "payload": {"patch_id": "p-2"},
                "channel": "all",
                "channel_config": {"email": "coast@example.test"},
                "delivered_channels": ["telegram"],
                "attempts": 1,
            }

    class Connection:
        def __init__(self):
            self.cur = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self.cur

        def commit(self):
            pass

    connection = Connection()

    @contextmanager
    def connection_context():
        yield connection

    monkeypatch.setattr(outbox, "get_db_connection", connection_context)
    deliver = Mock()
    monkeypatch.setattr(alerts, "deliver_alert", deliver)

    assert outbox._dispatch_one() == "sent"
    deliver.assert_called_once_with(
        {"patch_id": "p-2"},
        "email",
        {"email": "coast@example.test"},
    )
    assert json.loads(connection.cur.params[-1][4]) == ["telegram", "email"]
