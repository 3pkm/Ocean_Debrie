"""
Local development server for Tidewatch / Ocean Debris Drift Intelligence.
Runs on http://127.0.0.1:8000 and dispatches to the Vercel-compatible API handlers in `api/`.
If DATABASE_URL is not configured or PostgreSQL is unreachable, it provides realistic
in-memory simulated telemetry for the Eastern Caribbean AOI so the frontend is 100% functional.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, List
from urllib.parse import urlsplit, parse_qs

# Ensure root directory is on python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.config import DATABASE_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dev_server")

# --- Fallback Mock Data for Offline / No-DB Local Development ---
MOCK_PATCHES = [
    {
        "patch_id": "P-0001-A",
        "parent_id": "P-0001",
        "aoi_id": 1,
        "status": "active",
        "first_seen": "2026-10-18T10:30:00Z",
        "last_seen": "2026-10-21T10:30:00Z",
        "clear_evidence": 0.0,
        "latest_obs": {
            "obs_id": 101,
            "scene_id": "S2A_MSIL2A_20261021T103021_N0500_R108_T20PPC",
            "centroid": {"type": "Point", "coordinates": [-61.15, 13.14]},
            "geom": {
                "type": "Polygon",
                "coordinates": [[
                    [-61.16, 13.13], [-61.14, 13.13], [-61.14, 13.15], [-61.16, 13.15], [-61.16, 13.13]
                ]]
            },
            "area_m2": 24200,
            "confidence": 0.89,
            "mean_fdi": 0.0145,
            "cloud_overlap": 0.02
        }
    },
    {
        "patch_id": "P-0001-B",
        "parent_id": "P-0001",
        "aoi_id": 1,
        "status": "active",
        "first_seen": "2026-10-18T10:30:00Z",
        "last_seen": "2026-10-21T10:30:00Z",
        "clear_evidence": 0.0,
        "latest_obs": {
            "obs_id": 102,
            "scene_id": "S2A_MSIL2A_20261021T103021_N0500_R108_T20PPC",
            "centroid": {"type": "Point", "coordinates": [-61.22, 13.11]},
            "geom": {
                "type": "Polygon",
                "coordinates": [[
                    [-61.23, 13.10], [-61.21, 13.10], [-61.21, 13.12], [-61.23, 13.12], [-61.23, 13.10]
                ]]
            },
            "area_m2": 18500,
            "confidence": 0.78,
            "mean_fdi": 0.0098,
            "cloud_overlap": 0.04
        }
    },
    {
        "patch_id": "P-0002",
        "parent_id": None,
        "aoi_id": 1,
        "status": "occluded",
        "first_seen": "2026-10-15T10:30:00Z",
        "last_seen": "2026-10-19T10:30:00Z",
        "clear_evidence": 0.0,
        "latest_obs": {
            "obs_id": 95,
            "scene_id": "S2A_MSIL2A_20261019T103021_N0500_R108_T20PPC",
            "centroid": {"type": "Point", "coordinates": [-61.30, 13.20]},
            "geom": {
                "type": "Polygon",
                "coordinates": [[
                    [-61.31, 13.19], [-61.29, 13.19], [-61.29, 13.21], [-61.31, 13.21], [-61.31, 13.19]
                ]]
            },
            "area_m2": 32000,
            "confidence": 0.82,
            "mean_fdi": 0.0112,
            "cloud_overlap": 0.72
        }
    }
]

MOCK_ZONES = [
    {
        "zone_id": 1,
        "name": "Kingstown Harbour",
        "geom": {
            "type": "Polygon",
            "coordinates": [[
                [-61.24, 13.13], [-61.18, 13.13], [-61.18, 13.17], [-61.24, 13.17], [-61.24, 13.13]
            ]]
        },
        "threshold_advisory": 0.20,
        "threshold_warning": 0.50,
        "risk_tier": "warning",
        "active": True
    },
    {
        "zone_id": 2,
        "name": "Bequia Marine Park",
        "geom": {
            "type": "Polygon",
            "coordinates": [[
                [-61.26, 12.98], [-61.20, 12.98], [-61.20, 13.04], [-61.26, 13.04], [-61.26, 12.98]
            ]]
        },
        "threshold_advisory": 0.20,
        "threshold_warning": 0.50,
        "risk_tier": "advisory",
        "active": True
    }
]


class DevServerHandler(BaseHTTPRequestHandler):
    def _send_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def _json(self, status: int, data: Any) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        path = url.path.rstrip("/")
        query = parse_qs(url.query)

        logger.info(f"GET {path}")

        # Try real DB handler if DATABASE_URL is configured
        if DATABASE_URL:
            try:
                from core.api_reads import list_patches, list_zones, get_freshness, get_forecast, get_patch, get_verifications

                if path == "/api/patches":
                    statuses = query.get("status", [None])[0]
                    st_list = [s.strip() for s in statuses.split(",")] if statuses else None
                    return self._json(200, list_patches(statuses=st_list))

                if path == "/api/zones":
                    return self._json(200, list_zones())

                if path == "/api/freshness":
                    return self._json(200, get_freshness())

                if path.startswith("/api/forecasts/"):
                    patch_id = path[len("/api/forecasts/"):].strip("/")
                    horizon = int(query.get("horizon", ["24"])[0])
                    fc = get_forecast(patch_id, horizon)
                    if fc:
                        return self._json(200, fc)

                if path.startswith("/api/patches/"):
                    patch_id = path[len("/api/patches/"):].strip("/")
                    p = get_patch(patch_id)
                    if p:
                        return self._json(200, p)

                if path == "/api/verifications":
                    return self._json(200, get_verifications(None, 50, 0))

            except Exception as e:
                logger.warning(f"Database query failed, using simulated fallback: {e}")

        # Fallback simulated response
        if path == "/api/patches":
            return self._json(200, MOCK_PATCHES)

        if path == "/api/zones":
            return self._json(200, MOCK_ZONES)

        if path == "/api/freshness":
            return self._json(200, {
                "last_scene_utc": "2026-10-21T10:30:21Z",
                "last_scene_age_hours": 3.2,
                "wind_forecast_updated_utc": "2026-10-21T12:00:00Z",
                "currents_forecast_updated_utc": "2026-10-21T12:00:00Z",
                "last_risk_refresh_utc": "2026-10-21T12:15:00Z",
                "active_patches_count": 2,
                "occluded_patches_count": 1,
                "pending_alerts_count": 1,
            })

        if path.startswith("/api/forecasts/"):
            patch_id = path[len("/api/forecasts/"):].strip("/")
            center = [-61.18, 13.12] if "B" in patch_id else [-61.12, 13.15]
            radius = 0.03
            return self._json(200, {
                "patch_id": patch_id,
                "horizon_h": 24,
                "centroid": {"type": "Point", "coordinates": center},
                "p50": {
                    "type": "Polygon",
                    "coordinates": [[
                        [center[0] - radius * 0.5, center[1] - radius * 0.3],
                        [center[0] + radius * 0.5, center[1] - radius * 0.3],
                        [center[0] + radius * 0.5, center[1] + radius * 0.3],
                        [center[0] - radius * 0.5, center[1] + radius * 0.3],
                        [center[0] - radius * 0.5, center[1] - radius * 0.3]
                    ]]
                },
                "p90": {
                    "type": "Polygon",
                    "coordinates": [[
                        [center[0] - radius, center[1] - radius * 0.7],
                        [center[0] + radius, center[1] - radius * 0.7],
                        [center[0] + radius, center[1] + radius * 0.7],
                        [center[0] - radius, center[1] + radius * 0.7],
                        [center[0] - radius, center[1] - radius * 0.7]
                    ]]
                }
            })

        if path.startswith("/api/patches/"):
            patch_id = path[len("/api/patches/"):].strip("/")
            patch = next((p for p in MOCK_PATCHES if p["patch_id"] == patch_id), MOCK_PATCHES[0])
            return self._json(200, {
                **patch,
                "timeline": [
                    {"event": "born", "at": "2026-10-18T10:30:00Z", "detail": "Detected in Sentinel-2 scene"},
                    {"event": "matched", "at": "2026-10-19T10:30:00Z", "detail": "Propagated with 0.8km drift error"},
                    {"event": "split", "at": "2026-10-21T10:30:00Z", "detail": "Split into daughter patches P-0001-A and P-0001-B"}
                ]
            })

        if path == "/api/verifications":
            return self._json(200, {
                "summary": {
                    "total_matched": 42,
                    "in_p50_pct": 54.8,
                    "in_p90_pct": 92.9,
                    "mean_error_km": 2.14,
                    "mean_persistence_error_km": 6.82,
                    "mean_currents_only_error_km": 4.19
                },
                "records": [
                    {"lead_h": 24, "error_km": 1.8, "in_p50": True, "in_p90": True, "persistence_error_km": 5.4, "currents_only_error_km": 3.2},
                    {"lead_h": 24, "error_km": 2.3, "in_p50": False, "in_p90": True, "persistence_error_km": 7.1, "currents_only_error_km": 4.6},
                    {"lead_h": 48, "error_km": 3.9, "in_p50": True, "in_p90": True, "persistence_error_km": 12.3, "currents_only_error_km": 7.8}
                ]
            })

        self._json(404, {"error": f"Endpoint {path} not found"})

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        path = url.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length > 0 else b""
        payload = json.loads(raw_body) if raw_body else {}

        logger.info(f"POST {path}")

        if path == "/api/zones":
            new_zone = {
                "zone_id": len(MOCK_ZONES) + 1,
                "name": payload.get("name", "New Zone"),
                "geom": payload.get("geom"),
                "threshold_advisory": payload.get("threshold_advisory", 0.2),
                "threshold_warning": payload.get("threshold_warning", 0.5),
                "risk_tier": "advisory",
                "active": True
            }
            MOCK_ZONES.append(new_zone)
            return self._json(201, new_zone)

        if path in ("/api/jobs/fetch-latest", "/api/jobs/fetch_latest"):
            return self._json(200, {
                "status": "queued",
                "message": "Sentinel-2 query triggered for Eastern Caribbean AOI",
                "scene_id": "S2A_MSIL2A_20261021T103021_N0500_R108_T20PPC"
            })

        self._json(404, {"error": f"Endpoint {path} not found"})


def run_server(port: int = 8000) -> None:
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, DevServerHandler)
    logger.info(f"Tidewatch API Server running at http://127.0.0.1:{port}")
    logger.info("Serving /api/patches, /api/zones, /api/freshness, /api/forecasts, etc.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutting down.")
        httpd.server_close()


if __name__ == "__main__":
    run_server(8000)
