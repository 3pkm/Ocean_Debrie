"""Secure cron worker for delivering pending alert outbox records."""

from __future__ import annotations

import hmac
import json
import logging
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, Optional

from core import alerts
from core.config import CRON_SECRET
from core.db import get_db_connection

logger = logging.getLogger(__name__)


def _dispatch_one() -> Optional[str]:
    """
    Lock one due alert, deliver one channel, and persist its resulting state.

    The row lock is held during delivery. Other cron invocations skip the locked
    row via SKIP LOCKED, so concurrent workers cannot dispatch it simultaneously.
    Successful channels are recorded so retries do not resend them.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.alert_id, a.payload, a.channel,
                       a.delivered_channels, COALESCE(a.attempts, 0) AS attempts,
                       z.channels AS channel_config
                FROM alerts AS a
                LEFT JOIN zones AS z ON z.zone_id = a.zone_id
                WHERE (
                    a.status = 'pending'
                    OR (a.status = 'failed' AND COALESCE(a.attempts, 0) < %s)
                )
                  AND (a.next_attempt_at IS NULL OR a.next_attempt_at <= NOW())
                ORDER BY a.next_attempt_at NULLS FIRST, a.alert_id
                LIMIT 1
                FOR UPDATE OF a SKIP LOCKED;
                """,
                (alerts.MAX_DELIVERY_ATTEMPTS,),
            )
            row = cur.fetchone()
            if not row:
                conn.commit()
                return None

            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            channel_config = row.get("channel_config")
            if isinstance(channel_config, str):
                channel_config = json.loads(channel_config)
            delivered_channels = row.get("delivered_channels") or []
            if isinstance(delivered_channels, str):
                delivered_channels = json.loads(delivered_channels)
            delivered_channels = list(delivered_channels)
            attempts = int(row.get("attempts", 0)) + 1

            try:
                channels = alerts.resolve_delivery_channels(
                    row.get("channel") or "all", channel_config
                )
                remaining = [
                    channel for channel in channels if channel not in delivered_channels
                ]
                if not remaining:
                    cur.execute(
                        """
                        UPDATE alerts
                        SET status = 'sent', sent_at = NOW(),
                            next_attempt_at = NULL, last_error = NULL
                        WHERE alert_id = %s;
                        """,
                        (row["alert_id"],),
                    )
                    conn.commit()
                    return "sent"
                channel = remaining[0]
                alerts.deliver_alert(payload, channel, channel_config)
            except Exception as exc:
                # Do not persist provider response bodies or credentials.
                error = (
                    str(exc).replace("\n", " ")[:500]
                    if isinstance(exc, alerts.AlertDeliveryError)
                    else f"Unexpected delivery error ({type(exc).__name__})"
                )
                delay = alerts.retry_delay_seconds(attempts)
                cur.execute(
                    """
                    UPDATE alerts
                    SET status = 'failed',
                        attempts = %s,
                        next_attempt_at = NOW() + (%s * INTERVAL '1 second'),
                        last_error = %s
                    WHERE alert_id = %s;
                    """,
                    (attempts, delay, error, row["alert_id"]),
                )
                conn.commit()
                logger.warning("Alert %s delivery failed on attempt %s", row["alert_id"], attempts)
                return "failed"

            delivered_channels.append(channel)
            complete = all(
                channel_name in delivered_channels for channel_name in channels
            )
            cur.execute(
                """
                UPDATE alerts
                SET status = %s,
                    attempts = %s,
                    sent_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                    next_attempt_at = CASE
                        WHEN %s THEN NULL
                        ELSE NOW()
                    END,
                    delivered_channels = %s::jsonb,
                    last_error = NULL
                WHERE alert_id = %s;
                """,
                (
                    "sent" if complete else "pending",
                    attempts if complete else 0,
                    complete,
                    complete,
                    json.dumps(delivered_channels),
                    row["alert_id"],
                ),
            )
            conn.commit()
            return "sent" if complete else "pending"


def run_outbox(batch_size: int = 8) -> Dict[str, Any]:
    """Dispatch up to ``batch_size`` due alerts, with bounded exponential retries."""
    sent = 0
    failed = 0
    processed = 0
    for _ in range(max(0, batch_size)):
        outcome = _dispatch_one()
        if outcome is None:
            break
        processed += 1
        if outcome == "sent":
            sent += 1
        elif outcome == "failed":
            failed += 1
    return {"status": "success", "processed": processed, "sent": sent, "failed": failed}


def _authorized(auth_header: str) -> bool:
    if not CRON_SECRET:
        return False
    scheme, separator, supplied = auth_header.partition(" ")
    return (
        separator == " "
        and scheme.lower() == "bearer"
        and bool(supplied.strip())
        and hmac.compare_digest(supplied.strip(), CRON_SECRET)
    )


class handler(BaseHTTPRequestHandler):
    """Vercel Serverless Function cron handler."""

    def do_GET(self):
        if not _authorized(self.headers.get("Authorization", "")):
            self._respond(401, {"error": "Unauthorized"})
            return
        try:
            self._respond(200, run_outbox())
        except Exception:
            logger.exception("Alert outbox cron failed")
            self._respond(500, {"status": "error", "error": "Outbox processing failed"})

    def _respond(self, status: int, body: Dict[str, Any]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
