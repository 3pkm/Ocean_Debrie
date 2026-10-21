"""GET /api/freshness: scene, risk and active-patch telemetry."""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler

from core.api_reads import get_freshness
from core.api_utils import method_not_allowed, send_json, send_unexpected_error

logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            send_json(self, 200, get_freshness())
        except Exception:
            send_unexpected_error(self, logger, "Freshness request failed.")

    def do_POST(self) -> None:
        method_not_allowed(self, ("GET",))
