"""
Alert generation and deduplication module for Multispectral Ocean Debris Tracking.
Generates unique dedupe keys, checks trigger conditions (tier rise or P rise >= 0.15),
formats standardized alert payloads conforming to plan.md Section 9.7,
and records pending alerts in the alerts table.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Union

from core.config import (
    ALERT_MIN_PROB_DELTA,
    ZONE_DEFAULT_ADVISORY,
    ZONE_DEFAULT_WARNING,
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
    p_reach: float,
    eta_p10: Optional[datetime],
    eta_p90: Optional[datetime],
    scene_id: str,
    patch_status: str = "active",
    last_observed_utc: Optional[Union[datetime, str]] = None,
    dashboard_base_url: str = "https://ocean-debris.vercel.app",
) -> Dict[str, Any]:
    """
    Format standard alert payload conforming to plan.md Section 9.7.
    """
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
        "probability": round(float(p_reach), 2),
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

    last_tier = last_alert.get("tier", "None")
    last_p_reach = float(last_alert.get("p_reach", 0.0))

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
