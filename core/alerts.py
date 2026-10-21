"""
Alert generation and deduplication module for Multispectral Ocean Debris Tracking.
Generates unique dedupe keys, checks trigger conditions (tier rise or P rise >= 0.15),
formats standardized alert payloads conforming to plan.md Section 9.7,
and records pending alerts in the alerts table.
"""

import json
import hashlib
import hmac
import html
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Union

import requests

from core.config import (
    ALERT_MIN_PROB_DELTA,
    EMAIL_API_KEY,
    EMAIL_FROM,
    EMAIL_PROVIDER,
    EMAIL_TO,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    ZONE_DEFAULT_ADVISORY,
    ZONE_DEFAULT_WARNING,
    WEBHOOK_SIGNING_KEY,
    WEBHOOK_URL,
)

logger = logging.getLogger(__name__)

# Numeric rank for evaluating tier rise
TIER_RANKS = {
    "None": 0,
    "none": 0,
    "Advisory": 1,
    "advisory": 1,
    "Warning": 2,
    "warning": 2,
}

DELIVERY_TIMEOUT_SECONDS = 10
MAX_DELIVERY_ATTEMPTS = 3
MAX_RETRY_DELAY_SECONDS = 60 * 60


class AlertDeliveryError(RuntimeError):
    """A configured alert channel did not accept its delivery."""


def webhook_signature(
    payload: Union[Dict[str, Any], bytes, str],
    signing_key: Optional[str] = None,
) -> str:
    """Return the SHA-256 HMAC header value for a serialized webhook payload."""
    if isinstance(payload, dict):
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    elif isinstance(payload, str):
        body = payload.encode("utf-8")
    else:
        body = payload
    signature = hmac.new(
        (signing_key or WEBHOOK_SIGNING_KEY).encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return f"sha256={signature}"


def _post(
    url: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    raw_body: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
):
    """POST an alert to a provider without leaking response contents or credentials."""
    try:
        response = requests.post(
            url,
            json=json_body if raw_body is None else None,
            data=raw_body,
            headers=headers,
            timeout=DELIVERY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        detail = f" (HTTP {status})" if status else ""
        raise AlertDeliveryError(f"Provider request failed{detail}") from None


def _telegram_message(payload: Dict[str, Any]) -> str:
    arrival = payload.get("arrival_window_utc") or ["", ""]
    if not isinstance(arrival, (list, tuple)):
        arrival = ["", ""]
    start = html.escape(str(arrival[0]) if arrival else "")
    end = html.escape(str(arrival[1]) if len(arrival) > 1 else "")
    return (
        f"<b>Ocean debris {html.escape(str(payload.get('tier', 'Alert')))}</b>\n"
        f"Patch: <code>{html.escape(str(payload.get('patch_id', '')))}</code>\n"
        f"Zone: {html.escape(str(payload.get('zone', '')))}\n"
        f"Probability: {html.escape(str(payload.get('probability', '')))}\n"
        f"Arrival window (UTC): {start} – {end}\n"
        f"Status: {html.escape(str(payload.get('patch_status', '')))}\n"
        f'<a href="{html.escape(str(payload.get("dashboard_url", "")), quote=True)}">Open dashboard</a>'
    )


def send_telegram_alert(
    payload: Dict[str, Any], chat_id: Optional[str] = None
) -> None:
    """Send an alert through the Telegram Bot API."""
    recipient = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not recipient:
        raise AlertDeliveryError("Telegram delivery is not fully configured")
    response = _post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json_body={
            "chat_id": recipient,
            "text": _telegram_message(payload),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )
    try:
        if response.json().get("ok") is False:
            raise AlertDeliveryError("Telegram rejected the alert")
    except (ValueError, AttributeError):
        raise AlertDeliveryError("Telegram returned an invalid response") from None


def send_webhook_alert(
    payload: Dict[str, Any],
    url: Optional[str] = None,
    signing_key: Optional[str] = None,
) -> None:
    """Send JSON to the configured webhook with an HMAC-SHA256 signature."""
    destination = url or WEBHOOK_URL
    secret = signing_key or WEBHOOK_SIGNING_KEY
    if not destination or not secret:
        raise AlertDeliveryError("Webhook delivery is not fully configured")
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    _post(
        destination,
        raw_body=body.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Signature": webhook_signature(body, secret),
        },
    )


def _email_recipients(override: Any = None) -> list[str]:
    recipients = override if override is not None else EMAIL_TO
    if isinstance(recipients, str):
        return [address.strip() for address in recipients.split(",") if address.strip()]
    if isinstance(recipients, list):
        return [
            address.strip()
            for address in recipients
            if isinstance(address, str) and address.strip()
        ]
    return []


def send_email_alert(payload: Dict[str, Any], to: Any = None) -> None:
    """Send an HTML alert using the configured Resend or SendGrid HTTP API."""
    recipients = _email_recipients(to)
    if not EMAIL_API_KEY or not EMAIL_FROM or not recipients:
        raise AlertDeliveryError("Email delivery is not fully configured")

    patch_id = html.escape(str(payload.get("patch_id", "")))
    tier = html.escape(str(payload.get("tier", "Alert")))
    dashboard_url = html.escape(str(payload.get("dashboard_url", "")), quote=True)
    fields = {
        "zone": payload.get("zone", ""),
        "probability": payload.get("probability", ""),
        "arrival_window_utc": payload.get("arrival_window_utc", ["", ""]),
        "patch_status": payload.get("patch_status", ""),
    }
    details = "".join(
        f"<li><strong>{html.escape(str(name).replace('_', ' ').title())}:</strong> "
        f"{html.escape(json.dumps(value) if isinstance(value, (list, dict)) else str(value))}</li>"
        for name, value in fields.items()
    )
    message_html = (
        f"<h2>Ocean debris {tier}</h2><p>Patch: {patch_id}</p>"
        f"<ul>{details}</ul><p><a href=\"{dashboard_url}\">Open dashboard</a></p>"
    )
    subject = " ".join(
        f"Ocean debris {payload.get('tier', 'alert')}: {payload.get('patch_id', '')}".splitlines()
    )[:200]
    provider = EMAIL_PROVIDER.strip().lower()
    if provider == "resend":
        url = "https://api.resend.com/emails"
        body = {
            "from": EMAIL_FROM,
            "to": recipients,
            "subject": subject,
            "html": message_html,
        }
        headers = {"Authorization": f"Bearer {EMAIL_API_KEY}"}
    elif provider == "sendgrid":
        url = "https://api.sendgrid.com/v3/mail/send"
        body = {
            "personalizations": [{"to": [{"email": address} for address in recipients]}],
            "from": {"email": EMAIL_FROM},
            "subject": subject,
            "content": [{"type": "text/html", "value": message_html}],
        }
        headers = {"Authorization": f"Bearer {EMAIL_API_KEY}"}
    else:
        raise AlertDeliveryError(f"Unsupported email provider: {provider}")
    _post(url, json_body=body, headers=headers)


_CHANNEL_SENDERS = {
    "telegram": send_telegram_alert,
    "webhook": send_webhook_alert,
    "email": send_email_alert,
}


def _channel_options(channel_config: Any) -> Dict[str, Dict[str, Any]]:
    """Normalize zone channel settings to provider-specific options."""
    options: Dict[str, Dict[str, Any]] = {}
    if isinstance(channel_config, list):
        entries = channel_config
    elif isinstance(channel_config, dict):
        if any(
            key in channel_config
            for key in ("telegram_chat_id", "email", "webhook_url")
        ):
            entries = [
                {
                    "type": "telegram",
                    "chat_id": channel_config.get("telegram_chat_id"),
                },
                {"type": "email", "to": channel_config.get("email")},
                {
                    "type": "webhook",
                    "url": channel_config.get("webhook_url"),
                    "secret": channel_config.get("webhook_secret"),
                },
            ]
        else:
            entries = [
                {"type": name, **(value if isinstance(value, dict) else {})}
                for name, value in channel_config.items()
                if name in _CHANNEL_SENDERS
            ]
    else:
        entries = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("type", "")).strip().lower()
        if name == "telegram" and entry.get("chat_id"):
            options[name] = {"chat_id": str(entry["chat_id"])}
        elif name == "email" and entry.get("to"):
            options[name] = {"to": entry["to"]}
        elif name == "webhook" and entry.get("url") and entry.get("secret"):
            options[name] = {
                "url": str(entry["url"]),
                "signing_key": str(entry["secret"]),
            }
    return options


def _configured_channels(channel_config: Any = None) -> list[str]:
    if channel_config:
        return list(_channel_options(channel_config))
    channels = []
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        channels.append("telegram")
    if WEBHOOK_URL and WEBHOOK_SIGNING_KEY:
        channels.append("webhook")
    if EMAIL_API_KEY and EMAIL_FROM and _email_recipients():
        channels.append("email")
    return channels


def resolve_delivery_channels(
    channel: str = "all", channel_config: Any = None
) -> list[str]:
    """Return the distinct configured providers for an alert."""
    requested = [
        part.strip().lower()
        for part in (channel or "all").split(",")
        if part.strip()
    ]
    configured = _configured_channels(channel_config)
    if not requested or "all" in requested:
        requested = configured
    elif channel_config:
        requested = [name for name in requested if name in configured]
    if not requested:
        raise AlertDeliveryError("No alert delivery channels are configured")
    return list(dict.fromkeys(requested))


def deliver_alert(
    payload: Dict[str, Any],
    channel: str = "all",
    channel_config: Any = None,
) -> list[str]:
    """Deliver an alert to one or more configured channels, failing if any fails."""
    requested = resolve_delivery_channels(channel, channel_config)
    options = _channel_options(channel_config)

    delivered = []
    for name in requested:
        sender = _CHANNEL_SENDERS.get(name)
        if sender is None:
            raise AlertDeliveryError(f"Unsupported alert channel: {name}")
        if channel_config and name in options:
            sender(payload, **options[name])
        else:
            sender(payload)
        delivered.append(name)
    return delivered


def retry_delay_seconds(attempt_number: int) -> int:
    """Exponential retry delay, capped at one hour."""
    return min(60 * (2 ** max(0, attempt_number - 1)), MAX_RETRY_DELAY_SECONDS)


def generate_dedupe_key(
    zone_id: Union[int, str],
    patch_id: str,
    scene_id: str,
    tier: str,
) -> str:
    """
    Generate unique deduplication key for zone alerts.
    Format: {zone_id}|{patch_id}|{scene_id}|{tier}
    """
    return f"{zone_id}|{patch_id}|{scene_id}|{tier}"


def _format_iso(dt: Optional[Union[datetime, str]]) -> str:
    """Format datetime as UTC ISO-8601 string (e.g. 2026-10-21T05:10:00Z)."""
    if dt is None:
        return ""
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_alert_payload(
    patch_id: str,
    zone_name: str,
    tier: str,
    p_reach: float = 0.0,
    eta_p10: Optional[datetime] = None,
    eta_p90: Optional[datetime] = None,
    scene_id: str = "",
    patch_status: str = "active",
    last_observed_utc: Optional[Union[datetime, str]] = None,
    dashboard_base_url: str = "https://ocean-debris.vercel.app",
    probability: Optional[float] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Format standard alert payload conforming to plan.md Section 9.7.
    """
    prob = probability if probability is not None else p_reach
    arrival_window = [
        _format_iso(eta_p10),
        _format_iso(eta_p90),
    ]

    last_obs_str = _format_iso(last_observed_utc) if last_observed_utc else ""
    dashboard_url = f"{dashboard_base_url.rstrip('/')}/patch/{patch_id}"

    payload = {
        "patch_id": patch_id,
        "zone": zone_name,
        "tier": tier,
        "probability": round(float(prob), 2),
        "arrival_window_utc": arrival_window,
        "patch_status": patch_status,
        "last_observed_utc": last_obs_str,
        "scene_id": scene_id,
        "dashboard_url": dashboard_url,
    }
    return payload


def should_trigger_alert(
    current_tier: str,
    current_p_reach: float,
    last_alert: Optional[Dict[str, Any]] = None,
    min_prob_delta: float = ALERT_MIN_PROB_DELTA,
) -> bool:
    """
    Determine if an alert should be triggered.
    Trigger conditions:
    - Current tier must be 'Advisory' or 'Warning'.
    - If no previous alert exists: triggers if tier is Advisory or Warning (tier rose from None).
    - If previous alert exists: triggers if tier rises (e.g. Advisory -> Warning)
      OR if p_reach rises by >= min_prob_delta (0.15) since the last alert for that zone and patch.
    """
    if current_tier not in ("Advisory", "Warning"):
        return False

    if last_alert is None:
        return True

    if isinstance(last_alert, str):
        last_tier = last_alert
        last_p_reach = 0.0
    elif isinstance(last_alert, dict):
        last_tier = last_alert.get("tier", "None")
        last_p_reach = float(last_alert.get("p_reach", 0.0))
    else:
        last_tier = "None"
        last_p_reach = 0.0

    current_rank = TIER_RANKS.get(current_tier, 0)
    last_rank = TIER_RANKS.get(last_tier, 0)

    # Check tier rise
    tier_rises = current_rank > last_rank

    # Check probability rise
    prob_delta = current_p_reach - last_p_reach
    prob_rises = prob_delta >= min_prob_delta

    return tier_rises or prob_rises


def create_alert_record(
    eval_record: Dict[str, Any],
    zone: Dict[str, Any],
    scene_id: str,
    patch_status: str = "active",
    last_observed_utc: Optional[Union[datetime, str]] = None,
    channel: str = "all",
    last_alert: Optional[Dict[str, Any]] = None,
    dashboard_base_url: str = "https://ocean-debris.vercel.app",
) -> Optional[Dict[str, Any]]:
    """
    Evaluate trigger condition and build an alert record for insertion into the alerts table.
    Returns None if trigger condition is not met.
    """
    current_tier = eval_record.get("tier", "None")
    p_reach = float(eval_record.get("p_reach", 0.0))
    zone_id = zone.get("zone_id") or eval_record.get("zone_id")
    zone_name = zone.get("name") or eval_record.get("zone_name", f"Zone {zone_id}")
    patch_id = eval_record.get("patch_id", "")

    if not should_trigger_alert(current_tier, p_reach, last_alert=last_alert):
        return None

    dedupe_key = generate_dedupe_key(
        zone_id=zone_id,
        patch_id=patch_id,
        scene_id=scene_id,
        tier=current_tier,
    )

    eta_p10 = eval_record.get("eta_p10")
    eta_p90 = eval_record.get("eta_p90")

    payload = format_alert_payload(
        patch_id=patch_id,
        zone_name=zone_name,
        tier=current_tier,
        p_reach=p_reach,
        eta_p10=eta_p10,
        eta_p90=eta_p90,
        scene_id=scene_id,
        patch_status=patch_status,
        last_observed_utc=last_observed_utc,
        dashboard_base_url=dashboard_base_url,
    )

    now = datetime.now(timezone.utc)

    alert_record = {
        "dedupe_key": dedupe_key,
        "zone_id": zone_id,
        "patch_id": patch_id,
        "scene_id": scene_id,
        "tier": current_tier,
        "p_reach": p_reach,
        "eta_start": eta_p10,
        "eta_end": eta_p90,
        "payload": payload,
        "channel": channel,
        "status": "pending",
        "attempts": 0,
        "next_attempt_at": now,
        "sent_at": None,
        "last_error": None,
    }

    return alert_record


def insert_alert(alert_record: Dict[str, Any], conn: Optional[Any] = None) -> Optional[int]:
    """
    Insert a pending alert record into the alerts database table.
    Uses ON CONFLICT (dedupe_key) DO NOTHING for idempotency.
    Returns alert_id if inserted, None if duplicate or offline.
    """
    from core.db import get_db_cursor

    sql = """
    INSERT INTO alerts (
        dedupe_key, zone_id, patch_id, scene_id, tier, p_reach,
        eta_start, eta_end, payload, channel, status, attempts, next_attempt_at
    )
    VALUES (
        %(dedupe_key)s, %(zone_id)s, %(patch_id)s, %(scene_id)s, %(tier)s, %(p_reach)s,
        %(eta_start)s, %(eta_end)s, %(payload)s, %(channel)s, %(status)s, %(attempts)s, %(next_attempt_at)s
    )
    ON CONFLICT (dedupe_key) DO NOTHING
    RETURNING alert_id;
    """

    params = alert_record.copy()
    if isinstance(params.get("payload"), dict):
        params["payload"] = json.dumps(params["payload"])

    try:
        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return row["alert_id"] if row else None
        else:
            with get_db_cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return row["alert_id"] if row else None
    except Exception as e:
        logger.warning(f"Could not insert alert into database ({e}).")
        return None
