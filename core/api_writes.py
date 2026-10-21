"""Validated database writes used by public API handlers."""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Optional

from core.api_utils import ApiRequestError, parse_fraction
from core.db import get_db_connection, get_db_cursor


def validate_polygon_geojson(value: Any) -> str:
    if not isinstance(value, dict) or value.get("type") != "Polygon":
        raise ApiRequestError("geom must be a GeoJSON Polygon.")
    rings = value.get("coordinates")
    if not isinstance(rings, list) or not rings:
        raise ApiRequestError("geom must contain at least one coordinate ring.")
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4:
            raise ApiRequestError("Each polygon ring must contain at least four points.")
        points = []
        for point in ring:
            if (
                not isinstance(point, (list, tuple))
                or len(point) != 2
                or isinstance(point[0], bool)
                or isinstance(point[1], bool)
            ):
                raise ApiRequestError("Polygon coordinates must be longitude/latitude pairs.")
            try:
                longitude, latitude = float(point[0]), float(point[1])
            except (TypeError, ValueError) as exc:
                raise ApiRequestError("Polygon coordinates must be numeric.") from exc
            if (
                not math.isfinite(longitude)
                or not math.isfinite(latitude)
                or longitude < -180
                or longitude > 180
                or latitude < -90
                or latitude > 90
            ):
                raise ApiRequestError("Polygon coordinates must be within WGS84 bounds.")
            points.append((longitude, latitude))
        if points[0] != points[-1]:
            raise ApiRequestError("Polygon rings must be closed.")
    return json.dumps(value, separators=(",", ":"))


def _validate_postgis_polygon(cur: Any, geom: str) -> None:
    cur.execute(
        "SELECT ST_IsValid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)) AS valid",
        (geom,),
    )
    row = cur.fetchone()
    if not row or not row["valid"]:
        raise ApiRequestError("geom must be a valid, non-self-intersecting Polygon.")


def _validate_name(value: Any, field: str = "name") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiRequestError(f"{field} must be a non-empty string.")
    if len(value.strip()) > 200:
        raise ApiRequestError(f"{field} must be at most 200 characters.")
    return value.strip()


def _validate_channels(value: Any) -> str:
    if not isinstance(value, (dict, list)):
        raise ApiRequestError("channels must be a JSON object or array.")
    try:
        encoded = json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ApiRequestError("channels must be valid JSON.") from exc
    if len(encoded.encode("utf-8")) > 16_384:
        raise ApiRequestError("channels is too large.")
    return encoded


def _zone_response(row: Dict[str, Any]) -> Dict[str, Any]:
    geom = row.get("geom_geojson")
    if isinstance(geom, str):
        geom = json.loads(geom)
    return {
        "zone_id": row["zone_id"],
        "name": row["name"],
        "geom": geom,
        "threshold_advisory": row["threshold_advisory"],
        "threshold_warning": row["threshold_warning"],
        "active": row["active"],
        "created_at": row["created_at"],
    }


def create_zone(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _validate_name(payload.get("name"))
    geom = validate_polygon_geojson(payload.get("geom"))
    advisory = parse_fraction(
        payload.get("threshold_advisory", 0.20), "threshold_advisory"
    )
    warning = parse_fraction(
        payload.get("threshold_warning", 0.50), "threshold_warning"
    )
    if advisory > warning:
        raise ApiRequestError(
            "threshold_advisory cannot exceed threshold_warning."
        )
    channels = _validate_channels(payload.get("channels", {}))
    active = payload.get("active", True)
    if not isinstance(active, bool):
        raise ApiRequestError("active must be a boolean.")
    with get_db_cursor() as cur:
        _validate_postgis_polygon(cur, geom)
        cur.execute(
            """
            INSERT INTO zones
                (name, geom, threshold_advisory, threshold_warning, channels, active)
            VALUES (
                %s,
                ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                %s, %s, %s::jsonb, %s
            )
            RETURNING zone_id, name, ST_AsGeoJSON(geom) AS geom_geojson,
                      threshold_advisory, threshold_warning, channels,
                      active, created_at
            """,
            (name, geom, advisory, warning, channels, active),
        )
        row = cur.fetchone()
    return _zone_response(row)


def get_zone(zone_id: int) -> Optional[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT zone_id, name, ST_AsGeoJSON(geom) AS geom_geojson,
                   threshold_advisory, threshold_warning, channels,
                   active, created_at
            FROM zones
            WHERE zone_id = %s
            """,
            (zone_id,),
        )
        row = cur.fetchone()
    return _zone_response(row) if row else None


def update_zone(zone_id: int, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {
        "name",
        "geom",
        "threshold_advisory",
        "threshold_warning",
        "channels",
        "active",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ApiRequestError(f"Unsupported zone field(s): {', '.join(sorted(unknown))}.")
    if not payload:
        raise ApiRequestError("At least one zone field must be provided.")

    values: Dict[str, Any] = {}
    if "name" in payload:
        values["name"] = _validate_name(payload["name"])
    if "geom" in payload:
        values["geom"] = validate_polygon_geojson(payload["geom"])
    if "threshold_advisory" in payload:
        values["threshold_advisory"] = parse_fraction(
            payload["threshold_advisory"], "threshold_advisory"
        )
    if "threshold_warning" in payload:
        values["threshold_warning"] = parse_fraction(
            payload["threshold_warning"], "threshold_warning"
        )
    if "channels" in payload:
        values["channels"] = _validate_channels(payload["channels"])
    if "active" in payload:
        if not isinstance(payload["active"], bool):
            raise ApiRequestError("active must be a boolean.")
        values["active"] = payload["active"]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT threshold_advisory, threshold_warning
                FROM zones WHERE zone_id = %s FOR UPDATE
                """,
                (zone_id,),
            )
            existing = cur.fetchone()
            if not existing:
                return None
            advisory = values.get(
                "threshold_advisory", existing["threshold_advisory"]
            )
            warning = values.get("threshold_warning", existing["threshold_warning"])
            if advisory > warning:
                raise ApiRequestError(
                    "threshold_advisory cannot exceed threshold_warning."
                )
            if "geom" in values:
                _validate_postgis_polygon(cur, values["geom"])

            assignments = []
            params = []
            for field in (
                "name",
                "threshold_advisory",
                "threshold_warning",
                "active",
            ):
                if field in values:
                    assignments.append(f"{field} = %s")
                    params.append(values[field])
            if "geom" in values:
                assignments.append(
                    "geom = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)"
                )
                params.append(values["geom"])
            if "channels" in values:
                assignments.append("channels = %s::jsonb")
                params.append(values["channels"])
            params.append(zone_id)
            cur.execute(
                f"""
                UPDATE zones SET {', '.join(assignments)}
                WHERE zone_id = %s
                RETURNING zone_id, name, ST_AsGeoJSON(geom) AS geom_geojson,
                          threshold_advisory, threshold_warning, channels,
                          active, created_at
                """,
                tuple(params),
            )
            row = cur.fetchone()
        conn.commit()
    return _zone_response(row)
