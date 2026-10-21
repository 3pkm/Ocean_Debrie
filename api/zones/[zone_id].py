"""GET/PATCH /api/zones/:zone_id."""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler

from core.api_utils import (
    ApiRequestError,
    method_not_allowed,
    is_authorized,
    parse_positive_int,
    read_json_body,
    route_parameter,
    send_json,
    send_unexpected_error,
)
from core.api_writes import get_zone, update_zone
from core.config import ZONE_API_KEY

logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def _zone_id(self):
        raw = route_parameter(self, "/api/zones/")
        return parse_positive_int(raw, "zone_id")

    def do_GET(self) -> None:
        try:
            zone = get_zone(self._zone_id())
            if zone is None:
                send_json(self, 404, {"error": "Zone not found."})
                return
            send_json(self, 200, zone)
        except ApiRequestError as exc:
            send_json(self, exc.status_code, {"error": str(exc)})
        except Exception:
            send_unexpected_error(self, logger, "Zone detail request failed.")

    def do_PATCH(self) -> None:
        if not ZONE_API_KEY:
            send_json(self, 503, {"error": "Zone write API key is not configured."})
            return
        if not is_authorized(self.headers, ZONE_API_KEY):
            send_json(self, 401, {"error": "Unauthorized."})
            return
        try:
            zone = update_zone(self._zone_id(), read_json_body(self))
            if zone is None:
                send_json(self, 404, {"error": "Zone not found."})
                return
            send_json(self, 200, zone)
        except ApiRequestError as exc:
            send_json(self, exc.status_code, {"error": str(exc)})
        except Exception:
            send_unexpected_error(self, logger, "Zone update failed.")

    def do_POST(self) -> None:
        method_not_allowed(self, ("GET", "PATCH"))
