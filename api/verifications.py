"""GET /api/verifications?patch=:patch_id."""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler

from core.api_reads import get_verifications
from core.api_utils import (
    ApiRequestError,
    method_not_allowed,
    parse_optional_int,
    parse_query,
    send_json,
    send_unexpected_error,
)

logger = logging.getLogger(__name__)
_MAX_LIMIT = 1000


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            query = parse_query(self)
            patch_id = query.get("patch")
            if patch_id == "":
                patch_id = None
            if patch_id is not None and len(patch_id) > 200:
                raise ApiRequestError("patch must be at most 200 characters.")
            limit = parse_optional_int(query.get("limit", "500"), "limit")
            offset_text = query.get("offset", "0")
            if not offset_text.isdigit():
                raise ApiRequestError("offset must be a non-negative integer.")
            offset = int(offset_text)
            if offset < 0:
                raise ApiRequestError("offset must be a non-negative integer.")
            if limit is None:
                limit = 500
            if limit > _MAX_LIMIT:
                raise ApiRequestError(f"limit cannot exceed {_MAX_LIMIT}.")
            send_json(
                self,
                200,
                get_verifications(patch_id, limit, offset),
            )
        except ApiRequestError as exc:
            send_json(self, exc.status_code, {"error": str(exc)})
        except Exception:
            send_unexpected_error(self, logger, "Verifications request failed.")

    def do_POST(self) -> None:
        method_not_allowed(self, ("GET",))
