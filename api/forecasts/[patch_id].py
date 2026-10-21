"""GET /api/forecasts/:patch_id?horizon=24|48."""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler
from urllib.parse import unquote

from core.api_reads import get_forecast
from core.api_utils import (
    ApiRequestError,
    method_not_allowed,
    parse_query,
    route_parameter,
    send_json,
    send_unexpected_error,
)

logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        patch_id = unquote(route_parameter(self, "/api/forecasts/"))
        if not patch_id or len(patch_id) > 200:
            send_json(self, 400, {"error": "A valid patch_id is required."})
            return
        try:
            horizon_text = parse_query(self).get("horizon", "48")
            if horizon_text not in ("24", "48"):
                raise ApiRequestError("horizon must be 24 or 48.")
            result = get_forecast(patch_id, int(horizon_text))
            if result is None:
                send_json(self, 404, {"error": "Forecast not found."})
                return
            send_json(self, 200, result)
        except ApiRequestError as exc:
            send_json(self, exc.status_code, {"error": str(exc)})
        except Exception:
            send_unexpected_error(self, logger, "Forecast request failed.")

    def do_POST(self) -> None:
        method_not_allowed(self, ("GET",))
