"""Database reads and response shaping for the Python API handlers."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.api_utils import db_fetch_all, db_fetch_one, geojson_value


_PATCH_SELECT = """
    SELECT p.patch_id, p.parent_id, p.aoi_id, p.status, p.first_seen,
           p.last_seen, p.clear_evidence,
           latest.obs_id, latest.scene_id, latest.centroid_geojson,
           latest.geom_geojson, latest.area_m2, latest.confidence,
           latest.mean_fdi, latest.cloud_overlap
    FROM patches AS p
    LEFT JOIN LATERAL (
        SELECT o.obs_id, o.scene_id,
               ST_AsGeoJSON(o.centroid) AS centroid_geojson,
               ST_AsGeoJSON(o.geom) AS geom_geojson,
               o.area_m2, o.confidence, o.mean_fdi, o.cloud_overlap
        FROM observations AS o
        WHERE o.patch_id = p.patch_id
        ORDER BY (o.obs_id = p.last_obs_id) DESC, o.obs_id DESC
        LIMIT 1
    ) AS latest ON TRUE
"""


def _patch_record(row: Dict[str, Any]) -> Dict[str, Any]:
    latest = None
    if row.get("obs_id") is not None:
        latest = {
            "obs_id": row["obs_id"],
            "scene_id": row["scene_id"],
            "centroid": geojson_value(row.get("centroid_geojson")),
            "geom": geojson_value(row.get("geom_geojson")),
            "area_m2": row.get("area_m2"),
            "confidence": row.get("confidence"),
            "mean_fdi": row.get("mean_fdi"),
            "cloud_overlap": row.get("cloud_overlap"),
        }
    return {
        "patch_id": row["patch_id"],
        "parent_id": row.get("parent_id"),
        "aoi_id": row.get("aoi_id"),
        "status": row["status"],
        "first_seen": row.get("first_seen"),
        "last_seen": row.get("last_seen"),
        "clear_evidence": row.get("clear_evidence"),
        "latest_obs": latest,
    }


def list_patches(
    aoi_id: Optional[int] = None, statuses: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if aoi_id is not None:
        clauses.append("p.aoi_id = %s")
        params.append(aoi_id)
    if statuses:
        clauses.append("p.status = ANY(%s)")
        params.append(statuses)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db_fetch_all(
        f"{_PATCH_SELECT} {where} ORDER BY p.last_seen DESC NULLS LAST, p.patch_id",
        tuple(params),
    )
    return [_patch_record(row) for row in rows]


def get_patch(patch_id: str) -> Optional[Dict[str, Any]]:
    row = db_fetch_one(
        f"{_PATCH_SELECT} WHERE p.patch_id = %s",
        (patch_id,),
    )
    if not row:
        return None
    patch = _patch_record(row)
    events = db_fetch_all(
        """
        SELECT event, at, detail
        FROM events
        WHERE patch_id = %s
        UNION ALL
        SELECT 'observed' AS event, s.sensing_time AS at,
               jsonb_build_object(
                   'obs_id', o.obs_id,
                   'scene_id', o.scene_id,
                   'area_m2', o.area_m2,
                   'confidence', o.confidence,
                   'mean_fdi', o.mean_fdi,
                   'cloud_overlap', o.cloud_overlap
               ) AS detail
        FROM observations AS o
        LEFT JOIN scenes AS s ON s.scene_id = o.scene_id
        WHERE o.patch_id = %s
        ORDER BY at ASC NULLS LAST
        """,
        (patch_id, patch_id),
    )
    patch["timeline"] = [
        {
            "event": item["event"],
            "at": item["at"],
            "detail": item["detail"],
        }
        for item in events
    ]
    return patch


def get_forecast(patch_id: str, horizon_h: int) -> Optional[Dict[str, Any]]:
    row = db_fetch_one(
        """
        SELECT f.patch_id, f.forecast_id, f.seeded_from, f.issued_at,
               fa.horizon_h,
               ST_AsGeoJSON(fa.centroid) AS centroid_geojson,
               ST_AsGeoJSON(fa.p50) AS p50_geojson,
               ST_AsGeoJSON(fa.p90) AS p90_geojson
        FROM forecasts AS f
        JOIN forecast_areas AS fa ON fa.forecast_id = f.forecast_id
        WHERE f.patch_id = %s AND fa.horizon_h = %s
        ORDER BY f.issued_at DESC NULLS LAST, f.forecast_id DESC
        LIMIT 1
        """,
        (patch_id, horizon_h),
    )
    if not row:
        return None
    return {
        "patch_id": row["patch_id"],
        "forecast_id": row["forecast_id"],
        "seeded_from": row["seeded_from"],
        "issued_at": row["issued_at"],
        "horizon_h": row["horizon_h"],
        "centroid": geojson_value(row.get("centroid_geojson")),
        "p50": geojson_value(row.get("p50_geojson")),
        "p90": geojson_value(row.get("p90_geojson")),
    }


def get_verifications(
    patch_id: Optional[str], limit: int, offset: int
) -> Dict[str, Any]:
    where = "WHERE patch_id = %s" if patch_id else ""
    params: List[Any] = [patch_id] if patch_id else []
    summary = db_fetch_one(
        f"""
        SELECT COUNT(*) AS total_matched,
               AVG(CASE WHEN in_p50 IS NOT NULL
                        THEN CASE WHEN in_p50 THEN 100.0 ELSE 0.0 END END)
                   AS in_p50_pct,
               AVG(CASE WHEN in_p90 IS NOT NULL
                        THEN CASE WHEN in_p90 THEN 100.0 ELSE 0.0 END END)
                   AS in_p90_pct,
               AVG(error_km) AS mean_error_km,
               AVG(persistence_error_km) AS mean_persistence_error_km,
               AVG(currents_only_error_km) AS mean_currents_only_error_km
        FROM verifications
        {where}
        """,
        tuple(params),
    )
    records = db_fetch_all(
        f"""
        SELECT patch_id, forecast_id, obs_id, lead_h, error_km, in_p50,
               in_p90, persistence_error_km, currents_only_error_km, created_at
        FROM verifications
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return {"summary": summary, "records": records}


def list_zones(active: Optional[bool] = None) -> List[Dict[str, Any]]:
    where = "WHERE active = %s" if active is not None else ""
    params = (active,) if active is not None else ()
    rows = db_fetch_all(
        f"""
        SELECT zone_id, name, ST_AsGeoJSON(geom) AS geom_geojson,
               threshold_advisory, threshold_warning, channels, active, created_at
        FROM zones
        {where}
        ORDER BY zone_id
        """,
        params,
    )
    return [_zone_record(row) for row in rows]


def _zone_record(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "zone_id": row["zone_id"],
        "name": row.get("name"),
        "geom": geojson_value(row.get("geom_geojson")),
        "threshold_advisory": row.get("threshold_advisory"),
        "threshold_warning": row.get("threshold_warning"),
        "active": row.get("active"),
        "created_at": row.get("created_at"),
    }


def list_alerts(
    patch_id: Optional[str],
    zone_id: Optional[int],
    status: Optional[str],
    limit: int,
    offset: int,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    for column, value in (
        ("patch_id", patch_id),
        ("zone_id", zone_id),
        ("status", status),
    ):
        if value is not None:
            clauses.append(f"{column} = %s")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return db_fetch_all(
        f"""
        SELECT alert_id, dedupe_key, zone_id, patch_id, scene_id, tier,
               p_reach, eta_start, eta_end, payload, channel, status,
               attempts, next_attempt_at, sent_at, last_error
        FROM alerts
        {where}
        ORDER BY alert_id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )


def get_freshness() -> Dict[str, Any]:
    row = db_fetch_one(
        """
        SELECT
            (SELECT MAX(sensing_time) FROM scenes) AS last_scene_utc,
            (SELECT EXTRACT(EPOCH FROM
                (NOW() - MAX(sensing_time))) / 3600.0
             FROM scenes) AS last_scene_age_hours,
            (SELECT MAX(evaluated_at) FROM risk_evals)
                AS last_risk_refresh_utc,
            (SELECT COUNT(*) FROM patches WHERE status = 'active')
                AS active_patches_count,
            (SELECT COUNT(*) FROM patches WHERE status = 'occluded')
                AS occluded_patches_count,
            (SELECT COUNT(*) FROM alerts WHERE status = 'pending')
                AS pending_alerts_count
        """
    )
    return {
        **row,
        # No met-ocean feed timestamps or cron-run table exist in schema.sql.
        "wind_forecast_updated_utc": None,
        "currents_forecast_updated_utc": None,
    }
