"""CDSE push receiver: register a scene and enqueue its processing job."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, Optional, Tuple

from core.api_utils import (
    ApiRequestError,
    is_authorized,
    parse_positive_int,
    parse_fraction,
    read_json_body,
    send_json,
    validate_timestamp,
)
from core.config import INGEST_SECRET
from core.db import enqueue_scene_job
from core.worker import trigger_process_scene

logger = logging.getLogger(__name__)


def parse_scene_event(payload: Dict[str, Any]) -> Tuple[str, Optional[int], Optional[str], float]:
    """Extract the scene metadata used by the existing process-scene job."""
    event = payload.get("scene") or payload.get("data") or payload
    if not isinstance(event, dict):
        raise ApiRequestError("Scene event must be a JSON object.")

    properties = event.get("properties") or {}
    if not isinstance(properties, dict):
        raise ApiRequestError("Scene properties must be a JSON object.")
    scene_id = event.get("scene_id") or event.get("id")
    if not isinstance(scene_id, str) or not scene_id.strip():
        raise ApiRequestError("scene_id (or id) is required.")

    aoi_id = event.get("aoi_id", properties.get("aoi_id"))
    if aoi_id is not None:
        aoi_id = parse_positive_int(aoi_id, "aoi_id")

    sensing_time = (
        event.get("sensing_time")
        or event.get("datetime")
        or properties.get("datetime")
    )
    sensing_time = validate_timestamp(sensing_time, "sensing_time")

    cloud_frac = event.get("cloud_frac")
    if cloud_frac is None:
        cloud_cover = properties.get(
            "eo:cloud_cover",
            event.get("cloud_cover", properties.get("cloud_cover", 0.0)),
        )
        try:
            cloud_frac = float(cloud_cover) / 100.0
        except (TypeError, ValueError) as exc:
            raise ApiRequestError("Cloud cover must be numeric.") from exc
    else:
        cloud_frac = parse_fraction(cloud_frac, "cloud_frac")
    if not 0.0 <= cloud_frac <= 1.0:
        raise ApiRequestError("Cloud cover must be between 0 and 100.")

    return scene_id.strip(), aoi_id, sensing_time, cloud_frac


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if not is_authorized(self.headers, INGEST_SECRET):
            send_json(self, 401, {"error": "Unauthorized."})
            return

        try:
            payload = read_json_body(self)
            scene_id, aoi_id, sensing_time, cloud_frac = parse_scene_event(payload)
            job = enqueue_scene_job(
                scene_id=scene_id,
                aoi_id=aoi_id,
                sensing_time=sensing_time,
                source="cdse_push",
                cloud_frac=cloud_frac,
            )
            trigger = (
                trigger_process_scene()
                if job["status"] == "queued"
                else {"status": "not_needed"}
            )
            send_json(
                self,
                (
                    502
                    if job["status"] == "queued" and trigger["status"] == "failed"
                    else 202
                    if job["status"] == "queued"
                    else 200
                ),
                {
                    "status": job["status"],
                    "scene_id": scene_id,
                    "job_id": job["job_id"],
                    "duplicate": not job["created"],
                    "trigger": trigger,
                },
            )
        except ApiRequestError as exc:
            send_json(self, exc.status_code, {"error": str(exc)})
        except ValueError as exc:
            send_json(self, 409, {"error": str(exc)})
        except Exception:
            logger.exception("CDSE push handling failed.")
            send_json(self, 500, {"error": "Unable to enqueue scene processing."})

    def do_GET(self) -> None:
        send_json(self, 405, {"error": "Method not allowed.", "allowed": "POST"})
