"""GET and POST /api/zones."""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler

from core.api_reads import list_zones
from core.api_utils import (
    ApiRequestError,
    is_authorized,
    method_not_allowed,
    parse_query,
    read_json_body,
    send_json,
    send_unexpected_error,
)
from core.api_writes import create_zone
from core.config import ZONE_API_KEY

logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            active_text = parse_query(self).get("active")
            if active_text is None or active_text == "all":
                active = None
            elif active_text.lower() in ("true", "1"):
                active = True
            elif active_text.lower() in ("false", "0"):
                active = False
            else:
                raise ApiRequestError("active must be true, false, or all.")
            send_json(self, 200, list_zones(active))
        except ApiRequestError as exc:
            send_json(self, exc.status_code, {"error": str(exc)})
        except Exception:
            send_unexpected_error(self, logger, "Zone list request failed.")

    def do_POST(self) -> None:
        if not ZONE_API_KEY:
            send_json(self, 503, {"error": "Zone write API key is not configured."})
            return
        if not is_authorized(self.headers, ZONE_API_KEY):
            send_json(self, 401, {"error": "Unauthorized."})
            return
        try:
            zone = create_zone(read_json_body(self))
            send_json(self, 201, zone)
        except ApiRequestError as exc:
            send_json(self, exc.status_code, {"error": str(exc)})
        except Exception:
            send_unexpected_error(self, logger, "Zone creation failed.")

    def do_PATCH(self) -> None:
        method_not_allowed(self, ("GET", "POST"))
