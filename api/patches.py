"""GET /api/patches: list patches with their latest observations."""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler

from core.api_reads import list_patches
from core.api_utils import (
    ApiRequestError,
    method_not_allowed,
    parse_optional_int,
    parse_query,
    send_json,
    send_unexpected_error,
)

logger = logging.getLogger(__name__)
_PATCH_STATUSES = {
    "active",
    "occluded",
    "lost",
    "split",
    "merged",
    "stranded",
    "expired",
}


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            query = parse_query(self)
            aoi_id = parse_optional_int(query.get("aoi"), "aoi")
            raw_statuses = query.get("status")
            statuses = None
            if raw_statuses:
                statuses = sorted(
                    {status.strip() for status in raw_statuses.split(",") if status.strip()}
                )
                invalid = set(statuses) - _PATCH_STATUSES
                if not statuses or invalid:
                    raise ApiRequestError(
                        "status must contain one or more supported patch statuses."
                    )
            send_json(self, 200, list_patches(aoi_id, statuses))
        except ApiRequestError as exc:
            send_json(self, exc.status_code, {"error": str(exc)})
        except Exception:
            send_unexpected_error(self, logger, "Patch list request failed.")

    def do_POST(self) -> None:
        method_not_allowed(self, ("GET",))

    def do_PATCH(self) -> None:
        method_not_allowed(self, ("GET",))
