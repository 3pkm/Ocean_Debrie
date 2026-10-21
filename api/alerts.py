"""GET /api/alerts: alert history with delivery state."""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler

from core.api_reads import list_alerts
from core.api_utils import (
    ApiRequestError,
    method_not_allowed,
    parse_optional_int,
    parse_query,
    send_json,
    send_unexpected_error,
)

logger = logging.getLogger(__name__)
_ALERT_STATUSES = {"pending", "sent", "failed"}


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            query = parse_query(self)
            patch_id = query.get("patch")
            if patch_id == "":
                patch_id = None
            if patch_id is not None and len(patch_id) > 200:
                raise ApiRequestError("patch must be at most 200 characters.")
            zone_id = parse_optional_int(query.get("zone"), "zone")
            status = query.get("status")
            if status is not None and status not in _ALERT_STATUSES:
                raise ApiRequestError("status must be pending, sent, or failed.")
            limit = parse_optional_int(query.get("limit", "100"), "limit")
            offset_text = query.get("offset", "0")
            if not offset_text.isdigit():
                raise ApiRequestError("offset must be a non-negative integer.")
            offset = int(offset_text)
            if offset < 0:
                raise ApiRequestError("offset must be a non-negative integer.")
            if limit is None:
                limit = 100
            if limit > 500:
                raise ApiRequestError("limit cannot exceed 500.")
            send_json(
                self,
                200,
                list_alerts(patch_id, zone_id, status, limit, offset),
            )
        except ApiRequestError as exc:
            send_json(self, exc.status_code, {"error": str(exc)})
        except Exception:
            send_unexpected_error(self, logger, "Alert history request failed.")

    def do_POST(self) -> None:
        method_not_allowed(self, ("GET",))
