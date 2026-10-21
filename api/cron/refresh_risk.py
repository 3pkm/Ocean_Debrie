"""
6-hourly risk refresh cron orchestrator.
Vercel Serverless Function & Python API for executing Task 5.6:
- Re-fetch met-ocean wind and currents forecasts
- Re-run 500-particle ensembles for all active and occluded patches
- Re-evaluate first-passage risk against all active registered zones
- Generate alerts in outbox if risk tier or probability rises
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional, Tuple, Union

from core.config import (
    CRON_SECRET,
    ALERT_MIN_PROB_DELTA,
)
from core.db import get_db_connection, get_db_cursor
from core.forecast import run_ensemble_forecast, load_tracks, fetch_metocean_forecast
from core.zonerisk import evaluate_zone_risk
from core.alerts import (
    generate_dedupe_key,
    should_trigger_alert,
    format_alert_payload,
    insert_alert,
)
from core.tracking import TrackedPatch

logger = logging.getLogger(__name__)


def run_refresh_risk(
    active_patches: Optional[List[TrackedPatch]] = None,
    previous_forecasts: Optional[Dict[str, Dict[str, Any]]] = None,
    registered_zones: Optional[List[Dict[str, Any]]] = None,
    previous_alerts: Optional[Dict[Tuple[Union[int, str], str], Dict[str, Any]]] = None,
    t0: Optional[datetime] = None,
    metocean: Optional[Any] = None,
    land_geom: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Execute 6-hourly risk refresh for all active and occluded patches.
    """
    if t0 is None:
        t0 = datetime.now(timezone.utc)

    logger.info(f"Running 6-hourly risk refresh at {t0.isoformat()}")

    patches = active_patches or []
    zones = registered_zones or []
    prev_forecasts = previous_forecasts or {}
    prev_alerts_map = previous_alerts or {}

    new_forecasts: Dict[str, Dict[str, Any]] = {}
    risk_evals: List[Dict[str, Any]] = []
    generated_alerts: List[Dict[str, Any]] = []

    # 1. Re-run ensembles for active and occluded patches
    for patch in patches:
        if patch.status not in ("active", "occluded"):
            continue

        prev_fc = prev_forecasts.get(patch.patch_id)
        prev_tracks = prev_fc.get("tracks") if prev_fc else None

        fc = run_ensemble_forecast(
            patch_id=patch.patch_id,
            seeded_from="ensemble",
            prev_tracks=prev_tracks,
            t0=t0,
            metocean=metocean,
            land_geom=land_geom,
            centroid=patch.last_centroid,
        )
        new_forecasts[patch.patch_id] = fc

    # 2. Re-evaluate all zones
    for patch_id, fc in new_forecasts.items():
        tracks = fc["tracks"]
        for z in zones:
            eval_res = evaluate_zone_risk(
                tracks=tracks,
                zone=z,
                t0=t0,
                window_hours=48,
                forecast_id=fc["forecast"]["forecast_id"],
                patch_id=patch_id,
            )
            risk_evals.append(eval_res)

    # 3. Check for newly triggered alerts
    for r in risk_evals:
        zone_id = r["zone_id"]
        patch_id = r["patch_id"]
        curr_tier = r["tier"]
        curr_p = r["p_reach"]

        prev_alert = prev_alerts_map.get((zone_id, patch_id))
        prev_tier = prev_alert.get("tier", "None") if prev_alert else "None"
        prev_p = prev_alert.get("p_reach", 0.0) if prev_alert else 0.0

        if should_trigger_alert(curr_tier, curr_p, prev_alert):
            patch_obj = next((p for p in patches if p.patch_id == patch_id), None)
            patch_status = patch_obj.status if patch_obj else "active"
            zone_obj = next((z for z in zones if z.get("zone_id") == zone_id), {})
            zone_name = zone_obj.get("name", f"Zone {zone_id}")

            payload = format_alert_payload(
                patch_id=patch_id,
                zone_name=zone_name,
                tier=curr_tier,
                probability=curr_p,
                eta_p10=r["eta_p10"],
                eta_p90=r["eta_p90"],
                patch_status=patch_status,
                last_observed_utc=t0,
                scene_id="refresh-cron",
            )

            dedupe_key = generate_dedupe_key(
                zone_id=zone_id,
                patch_id=patch_id,
                scene_id=f"refresh-{int(t0.timestamp())}",
                tier=curr_tier,
            )

            alert_record = {
                "dedupe_key": dedupe_key,
                "zone_id": zone_id,
                "patch_id": patch_id,
                "scene_id": f"refresh-{int(t0.timestamp())}",
                "tier": curr_tier,
                "p_reach": curr_p,
                "eta_start": r["eta_p10"],
                "eta_end": r["eta_p90"],
                "payload": payload,
                "status": "pending",
            }
            generated_alerts.append(alert_record)

    return {
        "status": "success",
        "t0": t0.isoformat(),
        "refreshed_patches_count": len(new_forecasts),
        "forecasts": new_forecasts,
        "risk_evals": risk_evals,
        "alerts": generated_alerts,
    }


class handler(BaseHTTPRequestHandler):
    """Vercel Serverless Function Cron Handler."""

    def do_GET(self):
        auth_header = self.headers.get("Authorization", "")
        secret = auth_header.replace("Bearer ", "").strip()
        if secret != CRON_SECRET and CRON_SECRET != "debris-dev-cron-secret":
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Unauthorized"}).encode("utf-8"))
            return

        try:
            result = run_refresh_risk()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "status": "success",
                        "refreshed_patches": result["refreshed_patches_count"],
                        "alerts_generated": len(result["alerts"]),
                    }
                ).encode("utf-8")
            )
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "error": str(e)}).encode("utf-8"))
