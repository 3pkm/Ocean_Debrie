"""Manual trigger for processing the newest scene already registered in the database."""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict

from core.api_utils import (
    ApiRequestError,
    read_json_body,
    send_json,
)
from core.db import enqueue_scene_job, get_db_cursor
from core.worker import trigger_process_scene

logger = logging.getLogger(__name__)


def _latest_scene() -> Dict[str, Any]:
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT s.scene_id, s.aoi_id, s.sensing_time, s.cloud_frac
            FROM scenes AS s
            JOIN aoi AS a ON a.aoi_id = s.aoi_id
            WHERE a.active IS TRUE
            ORDER BY s.sensing_time DESC NULLS LAST, s.scene_id DESC
            LIMIT 1
            """
        )
        scene = cur.fetchone()
    if not scene:
        raise ApiRequestError("No scene is registered for an active area of interest.", 404)
    return scene


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            read_json_body(self)
            scene = _latest_scene()
            job = enqueue_scene_job(
                scene_id=scene["scene_id"],
                aoi_id=scene["aoi_id"],
                sensing_time=scene["sensing_time"],
                cloud_frac=scene["cloud_frac"] or 0.0,
                source="manual_fetch_latest",
            )
            trigger = (
                trigger_process_scene()
                if job["status"] == "queued"
                else {"status": "not_needed"}
            )
            if job["status"] == "queued" and trigger["status"] == "failed":
                send_json(
                    self,
                    503,
                    {
                        "error": "The latest scene was queued but the worker could not be invoked.",
                        "scene_id": scene["scene_id"],
                        "job_id": job["job_id"],
                        "trigger": trigger,
                    },
                )
                return
            send_json(
                self,
                202 if job["status"] == "queued" else 200,
                {
                    "status": job["status"],
                    "scene_id": scene["scene_id"],
                    "job_id": job["job_id"],
                    "duplicate": not job["created"],
                    "message": (
                        "Latest registered scene queued."
                        if job["status"] == "queued"
                        else "Latest registered scene is already processing or complete."
                    ),
                    "trigger": trigger,
                },
            )
        except ApiRequestError as exc:
            send_json(self, exc.status_code, {"error": str(exc)})
        except ValueError as exc:
            send_json(self, 409, {"error": str(exc)})
        except Exception:
            logger.exception("Fetch-latest job enqueue failed.")
            send_json(self, 500, {"error": "Unable to enqueue scene processing."})

    def do_GET(self) -> None:
        send_json(self, 405, {"error": "Method not allowed.", "allowed": "POST"})
