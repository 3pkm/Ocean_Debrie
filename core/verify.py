"""
Forecast verification engine for Multispectral Ocean Debris Segmentation.
Computes geodesic forecast error (error_km via pyproj.Geod), lead time in hours (lead_h),
probabilistic contour containment (in_p50, in_p90), baseline benchmark errors
(persistence error, currents-only error), and split verification via area-weighted centroids.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pyproj
import shapely.geometry
from shapely.geometry import Point, Polygon, MultiPolygon

from core.tracking import Detection, TrackedPatch, geodesic_distance_km

_geod = pyproj.Geod(ellps="WGS84")


@dataclass
class ForecastData:
    """Represents a forecast issued for a patch covering a target scene sensing time."""
    patch_id: str
    t0: datetime  # initialization time of the forecast
    forecast_id: Optional[int] = None
    ensemble_mean_at_scene: Optional[Tuple[float, float]] = None  # (lon, lat)
    particles_at_scene: Optional[np.ndarray] = None  # (N, 2) in (lon, lat)
    p50_geom: Optional[Any] = None  # shapely polygon/multipolygon or GeoJSON
    p90_geom: Optional[Any] = None  # shapely polygon/multipolygon or GeoJSON
    currents_only_centroid: Optional[Tuple[float, float]] = None  # (lon, lat) with windage = 0


@dataclass
class VerificationRecord:
    """Represents a verification entry ready for the verifications table."""
    patch_id: str
    lead_h: float
    error_km: float
    in_p50: bool
    in_p90: bool
    forecast_id: Optional[int] = None
    obs_id: Optional[int] = None
    persistence_error_km: Optional[float] = None
    currents_only_error_km: Optional[float] = None
    created_at: Optional[datetime] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary matching database schema."""
        return {
            "patch_id": self.patch_id,
            "forecast_id": self.forecast_id,
            "obs_id": self.obs_id,
            "lead_h": round(self.lead_h, 3),
            "error_km": round(self.error_km, 4),
            "in_p50": self.in_p50,
            "in_p90": self.in_p90,
            "persistence_error_km": (
                round(self.persistence_error_km, 4)
                if self.persistence_error_km is not None
                else None
            ),
            "currents_only_error_km": (
                round(self.currents_only_error_km, 4)
                if self.currents_only_error_km is not None
                else None
            ),
            "created_at": self.created_at or datetime.now(timezone.utc),
            "detail": self.detail,
        }


def _check_point_in_geom(lon: float, lat: float, geom: Any) -> bool:
    """Check if point (lon, lat) is inside or on the boundary of a shapely geometry or GeoJSON dict."""
    if geom is None:
        return False
    if isinstance(geom, dict):
        try:
            geom = shapely.geometry.shape(geom)
        except Exception:
            return False

    pt = Point(lon, lat)
    try:
        return bool(geom.contains(pt) or geom.distance(pt) < 1e-6)
    except Exception:
        return False


def _distance_point_to_geom_km(lon: float, lat: float, geom: Any) -> float:
    """Approximate distance in kilometers from a point (lon, lat) to a geometry boundary."""
    if geom is None:
        return 0.0
    if isinstance(geom, dict):
        try:
            geom = shapely.geometry.shape(geom)
        except Exception:
            return 0.0

    pt = Point(lon, lat)
    try:
        if geom.contains(pt):
            return 0.0
        # Project nearest point on geometry boundary
        nearest_pt = shapely.ops.nearest_points(geom, pt)[0]
        return geodesic_distance_km(lon, lat, nearest_pt.x, nearest_pt.y)
    except Exception:
        return 0.0


def compute_verification(
    patch_id: str,
    obs_centroid: Tuple[float, float],
    scene_sensing_time: datetime,
    forecast: ForecastData,
    obs_id: Optional[int] = None,
    prev_obs_centroid: Optional[Tuple[float, float]] = None,
) -> VerificationRecord:
    """
    Compute verification metrics for a matched patch against an applicable forecast.

    Args:
        patch_id: ID of the patch.
        obs_centroid: Observed centroid (lon, lat) in current scene.
        scene_sensing_time: Sensing timestamp of current scene.
        forecast: Applicable ForecastData covering scene_sensing_time.
        obs_id: Optional ID of the observation row.
        prev_obs_centroid: Centroid (lon, lat) of previous observation for persistence baseline.

    Returns:
        VerificationRecord with error_km, lead_h, in_p50, in_p90, and baseline errors.
    """
    obs_lon, obs_lat = obs_centroid

    # 1. Compute lead time in hours
    lead_h = max(0.0, (scene_sensing_time - forecast.t0).total_seconds() / 3600.0)

    # 2. Determine forecast ensemble mean position at scene sensing time
    if forecast.ensemble_mean_at_scene is not None:
        pred_lon, pred_lat = forecast.ensemble_mean_at_scene
    elif forecast.particles_at_scene is not None and len(forecast.particles_at_scene) > 0:
        pred_lon = float(np.mean(forecast.particles_at_scene[:, 0]))
        pred_lat = float(np.mean(forecast.particles_at_scene[:, 1]))
    else:
        # If no forecast mean is provided, fall back to previous observation or (0, 0)
        pred_lon, pred_lat = prev_obs_centroid if prev_obs_centroid else obs_centroid

    # 3. Geodesic distance error (error_km)
    error_km = geodesic_distance_km(pred_lon, pred_lat, obs_lon, obs_lat)

    # 4. Check probabilistic contour containment (in_p50 and in_p90)
    in_p50 = _check_point_in_geom(obs_lon, obs_lat, forecast.p50_geom)
    in_p90 = _check_point_in_geom(obs_lon, obs_lat, forecast.p90_geom)

    # If geometric polygons are not provided but particle cloud is present, compute empirical radii
    if not in_p50 and forecast.p50_geom is None and forecast.particles_at_scene is not None:
        parts = forecast.particles_at_scene
        mean_pt = (pred_lon, pred_lat)
        dists_km = [
            geodesic_distance_km(mean_pt[0], mean_pt[1], p[0], p[1])
            for p in parts
        ]
        r50 = float(np.percentile(dists_km, 50.0))
        r90 = float(np.percentile(dists_km, 90.0))
        in_p50 = bool(error_km <= r50)
        in_p90 = bool(error_km <= r90)

    # 5. Baseline calculations
    # Persistence baseline: zero drift assumption (distance from previous observation centroid)
    persistence_error_km: Optional[float] = None
    if prev_obs_centroid is not None:
        persistence_error_km = geodesic_distance_km(
            prev_obs_centroid[0], prev_obs_centroid[1], obs_lon, obs_lat
        )

    # Currents-only baseline: distance from simulated drift with windage = 0
    currents_only_error_km: Optional[float] = None
    if forecast.currents_only_centroid is not None:
        currents_only_error_km = geodesic_distance_km(
            forecast.currents_only_centroid[0],
            forecast.currents_only_centroid[1],
            obs_lon,
            obs_lat,
        )

    return VerificationRecord(
        patch_id=patch_id,
        forecast_id=forecast.forecast_id,
        obs_id=obs_id,
        lead_h=lead_h,
        error_km=error_km,
        in_p50=in_p50,
        in_p90=in_p90,
        persistence_error_km=persistence_error_km,
        currents_only_error_km=currents_only_error_km,
    )


def verify_split(
    parent_forecast: ForecastData,
    children_detections: List[Detection],
    scene_sensing_time: datetime,
    prev_obs_centroid: Optional[Tuple[float, float]] = None,
) -> VerificationRecord:
    """
    Compute verification metrics for a split event.
    Compares the parent forecast against the area-weighted centroid of all children,
    and stores each child's distance to the parent's nearest 50% probability region.
    """
    if not children_detections:
        raise ValueError("Cannot verify split with empty children_detections")

    total_area = sum(c.area_m2 for c in children_detections)
    if total_area > 0:
        weighted_lon = sum(c.area_m2 * c.centroid[0] for c in children_detections) / total_area
        weighted_lat = sum(c.area_m2 * c.centroid[1] for c in children_detections) / total_area
    else:
        weighted_lon = sum(c.centroid[0] for c in children_detections) / len(children_detections)
        weighted_lat = sum(c.centroid[1] for c in children_detections) / len(children_detections)

    area_weighted_centroid = (weighted_lon, weighted_lat)

    record = compute_verification(
        patch_id=parent_forecast.patch_id,
        obs_centroid=area_weighted_centroid,
        scene_sensing_time=scene_sensing_time,
        forecast=parent_forecast,
        obs_id=children_detections[0].obs_id,
        prev_obs_centroid=prev_obs_centroid,
    )

    # Store each child's distance to the nearest 50% probability region
    child_distances: List[Dict[str, Any]] = []
    for c in children_detections:
        d_p50 = _distance_point_to_geom_km(c.centroid[0], c.centroid[1], parent_forecast.p50_geom)
        child_distances.append({
            "centroid": c.centroid,
            "area_m2": c.area_m2,
            "distance_to_p50_km": round(d_p50, 4),
        })

    record.detail = {
        "is_split": True,
        "children_count": len(children_detections),
        "area_weighted_centroid": [round(weighted_lon, 6), round(weighted_lat, 6)],
        "child_distances_to_p50_km": child_distances,
    }

    return record


def verify_scene_matches(
    matched_pairs: List[Tuple[TrackedPatch, Detection]],
    forecasts_by_patch: Dict[str, ForecastData],
    scene_sensing_time: datetime,
    prev_centroids_by_patch: Optional[Dict[str, Tuple[float, float]]] = None,
) -> List[VerificationRecord]:
    """
    Verify all matched patches in a processed scene.
    """
    records: List[VerificationRecord] = []
    prev_centroids = prev_centroids_by_patch or {}

    for patch, det in matched_pairs:
        forecast = forecasts_by_patch.get(patch.patch_id)
        if forecast is None:
            continue

        prev_c = prev_centroids.get(patch.patch_id) or patch.last_centroid
        rec = compute_verification(
            patch_id=patch.patch_id,
            obs_centroid=det.centroid,
            scene_sensing_time=scene_sensing_time,
            forecast=forecast,
            obs_id=det.obs_id,
            prev_obs_centroid=prev_c,
        )
        records.append(rec)

    return records


def verify_forecast(
    forecast: ForecastData,
    detection: Detection,
    scene_time: datetime,
    previous_obs_centroid: Optional[Tuple[float, float]] = None,
) -> VerificationRecord:
    """Convenience wrapper for single detection verification."""
    return compute_verification(
        patch_id=forecast.patch_id,
        obs_centroid=detection.centroid,
        scene_sensing_time=scene_time,
        forecast=forecast,
        obs_id=detection.obs_id,
        prev_obs_centroid=previous_obs_centroid,
    )


def verify_split_forecast(
    parent_forecast: ForecastData,
    children_detections: Union[List[Detection], List[Tuple[TrackedPatch, Detection]]],
    scene_time: datetime,
    prev_obs_centroid: Optional[Tuple[float, float]] = None,
) -> VerificationRecord:
    """Convenience wrapper for split verification with flexible children inputs."""
    dets = []
    for item in children_detections:
        if isinstance(item, tuple):
            dets.append(item[1])
        else:
            dets.append(item)
    return verify_split(
        parent_forecast=parent_forecast,
        children_detections=dets,
        scene_sensing_time=scene_time,
        prev_obs_centroid=prev_obs_centroid,
    )

