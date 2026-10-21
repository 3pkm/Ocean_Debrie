"""GET /api/patches/:patch_id: patch detail and lifecycle timeline."""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler
from urllib.parse import unquote

from core.api_reads import get_patch
from core.api_utils import (
    method_not_allowed,
    route_parameter,
    send_json,
    send_unexpected_error,
)

logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        patch_id = unquote(route_parameter(self, "/api/patches/"))
        if not patch_id or len(patch_id) > 200:
            send_json(self, 400, {"error": "A valid patch_id is required."})
            return
        try:
            patch = get_patch(patch_id)
            if patch is None:
                send_json(self, 404, {"error": "Patch not found."})
                return
            send_json(self, 200, patch)
        except Exception:
            send_unexpected_error(self, logger, "Patch detail request failed.")

    def do_POST(self) -> None:
        method_not_allowed(self, ("GET",))

    def do_PATCH(self) -> None:
        method_not_allowed(self, ("GET",))
