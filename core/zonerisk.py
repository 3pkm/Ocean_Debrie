"""
First-passage zone risk evaluation for Multispectral Ocean Debris Tracking.
Calculates particle arrival probabilities, ETA percentiles (p10/p90), and risk tiers
(Warning / Advisory / None) against protected coastal zones over a 48-hour window.
Conforms to plan.md Sections 8, 9.6 and execution_plan.md Phase 5.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Union

import numpy as np
import shapely
from shapely.geometry import Point, LineString, Polygon, MultiPolygon, shape
import shapely.prepared

from core.config import (
    ZONE_DEFAULT_ADVISORY,
    ZONE_DEFAULT_WARNING,
    ALERT_WINDOW_P10,
    ALERT_WINDOW_P90,
)

logger = logging.getLogger(__name__)


def _to_shapely_geom(geom: Any) -> Any:
    """Normalize input geometry to a Shapely Polygon or MultiPolygon."""
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    if isinstance(geom, dict):
        return shape(geom)
    if isinstance(geom, str):
        import shapely.wkt
        return shapely.wkt.loads(geom)
    raise ValueError(f"Unsupported zone geometry type: {type(geom)}")


def evaluate_zone_risk(
    tracks: np.ndarray,
    zone: Dict[str, Any],
    t0: Optional[datetime] = None,
    window_hours: int = 48,
    forecast_id: Optional[Union[int, str]] = None,
    patch_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluate first-passage risk of ensemble drift tracks into a protected zone.

    Args:
      tracks: shape (N, T, 2) array of particle [lon, lat] coordinates.
      zone: dict containing 'zone_id', 'geom', and optional 'threshold_warning', 'threshold_advisory', 'name'.
      t0: Start timestamp of forecast (UTC).
      window_hours: Evaluation window in hours (default: 48).
      forecast_id: Optional associated forecast identifier.
      patch_id: Optional associated debris patch identifier.

    Returns:
      Dict matching risk_evals table record.
    """
    if t0 is None:
        t0 = datetime.now(timezone.utc)

    zone_geom = _to_shapely_geom(zone["geom"])
    prep_zone = shapely.prepared.prep(zone_geom)
    zone_bounds = zone_geom.bounds  # minx, miny, maxx, maxy

    th_warning = float(zone.get("threshold_warning", ZONE_DEFAULT_WARNING))
    th_advisory = float(zone.get("threshold_advisory", ZONE_DEFAULT_ADVISORY))

    n_particles = tracks.shape[0]
    max_steps = min(window_hours, tracks.shape[1] - 1)

    arrival_hours: List[float] = []

    for i in range(n_particles):
        p_track = tracks[i, : max_steps + 1, :]

        # Fast bounding box rejection
        minx, miny = p_track.min(axis=0)
        maxx, maxy = p_track.max(axis=0)
        if (
            maxx < zone_bounds[0]
            or minx > zone_bounds[2]
            or maxy < zone_bounds[1]
            or miny > zone_bounds[3]
        ):
            continue

        # Check if particle started inside zone at t=0
        p0 = Point(p_track[0, 0], p_track[0, 1])
        if prep_zone.contains(p0):
            arrival_hours.append(0.0)
            continue

        # Check each 1-hour line segment for first passage into zone
        arrived = False
        for step in range(max_steps):
            p_start = p_track[step]
            p_end = p_track[step + 1]
            seg = LineString([p_start, p_end])

            if prep_zone.intersects(seg):
                # Calculate entry fraction along segment
                arr_hour = float(step)
                try:
                    inter = seg.intersection(zone_geom.boundary)
                    if not inter.is_empty:
                        if isinstance(inter, Point):
                            inter_pt = inter
                        elif hasattr(inter, "geoms"):
                            # If multiple intersections, take the closest to start point
                            inter_pt = min(inter.geoms, key=lambda pt: Point(p_start).distance(pt))
                        else:
                            inter_pt = None

                        if inter_pt is not None:
                            d_total = Point(p_start).distance(Point(p_end))
                            d_entry = Point(p_start).distance(inter_pt)
                            frac = min(1.0, max(0.0, d_entry / d_total)) if d_total > 1e-9 else 0.0
                            arr_hour = step + frac
                        else:
                            arr_hour = step + 0.5
                    else:
                        arr_hour = step + 0.5
                except Exception:
                    arr_hour = step + 0.5

                arrival_hours.append(arr_hour)
                arrived = True
                break  # Record only the first passage for this particle

    # Compute probability of reach
    m_arrived = len(arrival_hours)
    p_reach = float(m_arrived / float(n_particles))

    # Calculate arrival window (p10 to p90)
    eta_p10: Optional[datetime] = None
    eta_p90: Optional[datetime] = None

    if m_arrived > 0:
        p10_h = float(np.percentile(arrival_hours, ALERT_WINDOW_P10 * 100.0))
        p90_h = float(np.percentile(arrival_hours, ALERT_WINDOW_P90 * 100.0))
        eta_p10 = t0 + timedelta(hours=p10_h)
        eta_p90 = t0 + timedelta(hours=p90_h)

    # Assign tier
    if p_reach >= th_warning:
        tier = "Warning"
    elif p_reach >= th_advisory:
        tier = "Advisory"
    else:
        tier = "None"

    zone_name = zone.get("name", f"Zone {zone.get('zone_id')}")

    eval_record = {
        "zone_id": zone.get("zone_id"),
        "zone_name": zone_name,
        "patch_id": patch_id,
        "forecast_id": forecast_id,
        "p_reach": round(p_reach, 4),
        "eta_p10": eta_p10,
        "eta_p90": eta_p90,
        "tier": tier,
        "evaluated_at": datetime.now(timezone.utc),
        "arriving_count": m_arrived,
        "total_particles": n_particles,
    }

    return eval_record


def evaluate_all_zones(
    tracks: np.ndarray,
    zones: List[Dict[str, Any]],
    t0: Optional[datetime] = None,
    window_hours: int = 48,
    forecast_id: Optional[Union[int, str]] = None,
    patch_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Evaluate first-passage zone risk for a collection of registered zones.
    """
    evaluations: List[Dict[str, Any]] = []
    for zone in zones:
        eval_record = evaluate_zone_risk(
            tracks=tracks,
            zone=zone,
            t0=t0,
            window_hours=window_hours,
            forecast_id=forecast_id,
            patch_id=patch_id,
        )
        evaluations.append(eval_record)
    return evaluations


def insert_risk_eval(eval_record: Dict[str, Any], conn: Optional[Any] = None) -> Optional[int]:
    """
    Insert a risk evaluation record into the risk_evals database table.
    Returns the newly inserted id, or None if offline / database unavailable.
    """
    from core.db import get_db_cursor

    sql = """
    INSERT INTO risk_evals (
        zone_id, patch_id, forecast_id, p_reach, eta_p10, eta_p90, tier, evaluated_at
    )
    VALUES (
        %(zone_id)s, %(patch_id)s, %(forecast_id)s, %(p_reach)s,
        %(eta_p10)s, %(eta_p90)s, %(tier)s, %(evaluated_at)s
    )
    RETURNING id;
    """

    try:
        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, eval_record)
                row = cur.fetchone()
                return row["id"] if row else None
        else:
            with get_db_cursor() as cur:
                cur.execute(sql, eval_record)
                row = cur.fetchone()
                return row["id"] if row else None
    except Exception as e:
        logger.warning(f"Could not insert risk_eval into database ({e}).")
        return None
