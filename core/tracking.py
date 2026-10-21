"""
Core patch tracking engine for Multispectral Ocean Debris Segmentation.
Implements particle ensemble prediction, density-based gating, cost matrix
formulation, Hungarian bipartite matching, split detection, merge detection,
new patch creation, and event logging.
"""

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from typing import Any, Dict, List, Optional, Tuple, Set

import numpy as np
import pyproj
from scipy.optimize import linear_sum_assignment
from scipy.stats import gaussian_kde
import shapely.geometry
from shapely.geometry import Point, Polygon, MultiPolygon

from core.config import (
    TRACKING_GATE_PERCENTILE,
    TRACKING_DENSITY_FLOOR,
    TRACKING_EPSILON,
    TRACKING_WEIGHT_AREA,
    TRACKING_WEIGHT_FDI,
    SPLIT_MIN_AREA_RATIO,
    SPLIT_MAX_AREA_RATIO,
    SPLIT_MAX_DISTANCE_KM,
)

_geod = pyproj.Geod(ellps="WGS84")


def geodesic_distance_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Compute geodesic distance in kilometers between two (lon, lat) coordinates."""
    _, _, dist_m = _geod.inv(lon1, lat1, lon2, lat2)
    return dist_m / 1000.0


@dataclass
class Detection:
    """Represents a vectorized debris candidate from a single satellite scene."""
    centroid: Tuple[float, float]  # (lon, lat)
    area_m2: float
    geom: Any = None  # shapely geometry or GeoJSON dict
    obs_id: Optional[int] = None
    confidence: float = 1.0
    mean_fdi: float = 0.0
    cloud_overlap: float = 0.0
    scene_id: Optional[str] = None


@dataclass
class TrackedPatch:
    """Represents a tracked debris patch across satellite scenes."""
    patch_id: str
    parent_id: Optional[str] = None
    aoi_id: Optional[int] = None
    status: str = "active"  # active | occluded | lost | split | merged | stranded | expired
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    last_obs_id: Optional[int] = None
    clear_evidence: float = 0.0
    last_centroid: Optional[Tuple[float, float]] = None  # (lon, lat)
    last_area_m2: Optional[float] = None
    last_mean_fdi: Optional[float] = None
    ensemble_particles: Optional[np.ndarray] = None  # (N, 2) in (lon, lat)
    p90_geom: Optional[Any] = None  # shapely polygon/multipolygon
    velocity: Optional[Tuple[float, float]] = None  # (vx, vy) in degrees/sec or m/s


@dataclass
class TrackingEvent:
    """Represents an audit event for a patch."""
    patch_id: str
    event: str  # born | matched | split | merged | occluded | reacquired | lost | stranded | expired
    at: datetime
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TrackingResult:
    """Result of running tracking on a scene's detections."""
    matched: List[Tuple[TrackedPatch, Detection]] = field(default_factory=list)
    split_parents: List[TrackedPatch] = field(default_factory=list)
    split_children: List[Tuple[TrackedPatch, Detection]] = field(default_factory=list)
    merged_parents: List[TrackedPatch] = field(default_factory=list)
    merged_successors: List[Tuple[TrackedPatch, Detection]] = field(default_factory=list)
    new_patches: List[Tuple[TrackedPatch, Detection]] = field(default_factory=list)
    unmatched_patches: List[TrackedPatch] = field(default_factory=list)
    events: List[TrackingEvent] = field(default_factory=list)

    @property
    def splits(self) -> List[Tuple[TrackedPatch, List[Tuple[TrackedPatch, Detection]]]]:
        """Convenience property grouping split_parents with their respective children."""
        res = []
        for p in self.split_parents:
            children = [c for c in self.split_children if c[0].parent_id == p.patch_id]
            res.append((p, children))
        return res


def get_next_sequence_number(existing_patch_ids: List[str]) -> int:
    """Extract next integer sequence number from existing patch IDs (P-NNNN)."""
    max_seq = 0
    pattern = re.compile(r"^P-(\d+)")
    for pid in existing_patch_ids:
        match = pattern.match(pid)
        if match:
            seq_val = int(match.group(1))
            if seq_val > max_seq:
                max_seq = seq_val
    return max_seq + 1


def estimate_ensemble_density(
    particles: Optional[np.ndarray],
    predicted_centroid: Tuple[float, float],
    candidate_centroid: Tuple[float, float],
) -> float:
    """
    Evaluate spatial probability density p_ij at candidate centroid (lon, lat).
    Uses Gaussian KDE on ensemble particles if available, with 2D Gaussian fallback.
    """
    lon_c, lat_c = candidate_centroid

    if particles is not None and len(particles) >= 3:
        try:
            # Add subtle jitter if particles are nearly identical to avoid LinAlgError
            jitter = np.random.normal(0, 1e-7, particles.shape)
            kde = gaussian_kde((particles + jitter).T)
            density = float(kde.evaluate([[lon_c], [lat_c]])[0])
            if not math.isnan(density) and density >= 0:
                return density
        except Exception:
            pass

        # Fallback to empirical mean and covariance of particles
        mean_pt = np.mean(particles, axis=0)
        cov = np.cov(particles.T) + np.eye(2) * 1e-6
        diff = np.array([lon_c - mean_pt[0], lat_c - mean_pt[1]])
        try:
            inv_cov = np.linalg.inv(cov)
            det_cov = np.linalg.det(cov)
            if det_cov > 0:
                d2 = diff.T @ inv_cov @ diff
                density = (1.0 / (2.0 * math.pi * math.sqrt(det_cov))) * math.exp(-0.5 * d2)
                return max(0.0, float(density))
        except Exception:
            pass

    # Fallback to Gaussian centered at predicted_centroid with 0.02 deg (~2 km) sigma
    pred_lon, pred_lat = predicted_centroid
    sigma = 0.02
    d2 = ((lon_c - pred_lon) ** 2 + (lat_c - pred_lat) ** 2) / (sigma ** 2)
    density = (1.0 / (2.0 * math.pi * (sigma ** 2))) * math.exp(-0.5 * d2)
    return max(0.0, float(density))


def is_gated(
    patch: TrackedPatch,
    candidate_centroid: Tuple[float, float],
    density: float,
    predicted_centroid: Tuple[float, float],
) -> bool:
    """
    Gating check: candidate detection matches if within 90% probability region
    OR ensemble spatial density at candidate centroid > TRACKING_DENSITY_FLOOR (1e-6).
    Gating widens naturally with ensemble spread.
    """
    if density > TRACKING_DENSITY_FLOOR:
        return True

    lon_c, lat_c = candidate_centroid
    pt = Point(lon_c, lat_c)

    # 1. Explicit p90 polygon contour check
    if patch.p90_geom is not None:
        geom = patch.p90_geom
        if isinstance(geom, dict):
            geom = shapely.geometry.shape(geom)
        try:
            if geom.contains(pt) or geom.distance(pt) < 1e-6:
                return True
        except Exception:
            pass

    # 2. Particle cloud 90% distance percentile check
    if patch.ensemble_particles is not None and len(patch.ensemble_particles) >= 2:
        parts = patch.ensemble_particles
        mean_pt = np.mean(parts, axis=0)
        dists = np.hypot(parts[:, 0] - mean_pt[0], parts[:, 1] - mean_pt[1])
        r90 = float(np.percentile(dists, TRACKING_GATE_PERCENTILE))
        cand_dist = math.hypot(lon_c - mean_pt[0], lat_c - mean_pt[1])
        if cand_dist <= r90:
            return True

    return False


def calculate_cost(
    density: float,
    parent_area: Optional[float],
    det_area: float,
    parent_fdi: Optional[float],
    det_fdi: float,
) -> float:
    """
    Calculate assignment cost:
    c_ij = -ln(p_ij + eps) + w_a * |ln(A_j / A_i)| + w_s * |delta FDI|
    """
    p_term = -math.log(max(density, 0.0) + TRACKING_EPSILON)

    # Area discrepancy term
    if parent_area is not None and parent_area > 0 and det_area > 0:
        area_ratio = det_area / parent_area
        area_term = TRACKING_WEIGHT_AREA * abs(math.log(area_ratio))
    else:
        area_term = 0.0

    # Spectral FDI discrepancy term
    if parent_fdi is not None:
        fdi_term = TRACKING_WEIGHT_FDI * abs(det_fdi - parent_fdi)
    else:
        fdi_term = 0.0

    return p_term + area_term + fdi_term


def predict_patch_centroid(patch: TrackedPatch, scene_time: datetime) -> Tuple[float, float]:
    """Predict patch centroid at scene_time from ensemble particles, velocity, or last centroid."""
    if patch.ensemble_particles is not None and len(patch.ensemble_particles) > 0:
        mean_pt = np.mean(patch.ensemble_particles, axis=0)
        return (float(mean_pt[0]), float(mean_pt[1]))

    if patch.last_centroid is not None:
        lon, lat = patch.last_centroid
        if patch.velocity is not None and patch.last_seen is not None:
            dt_s = (scene_time - patch.last_seen).total_seconds()
            vx, vy = patch.velocity
            return (lon + vx * dt_s, lat + vy * dt_s)
        return (lon, lat)

    return (0.0, 0.0)


def track_scene_detections(
    patches: List[TrackedPatch],
    detections: List[Detection],
    scene_time: datetime,
    scene_id: Optional[str] = None,
    next_seq: Optional[int] = None,
) -> TrackingResult:
    """
    Execute patch tracking, split/merge detection, and bipartite matching for a new scene.

    Args:
        patches: Active or occluded patches to track.
        detections: Observed candidate debris detections in the current scene.
        scene_time: Sensing timestamp of the current scene.
        scene_id: Optional scene identifier.
        next_seq: Next integer sequence for new patch IDs (P-NNNN). If None, calculated automatically.

    Returns:
        TrackingResult containing matched patches, splits, merges, new patches, and events.
    """
    result = TrackingResult()

    if next_seq is None:
        existing_ids = [p.patch_id for p in patches]
        next_seq = get_next_sequence_number(existing_ids)

    # Filter eligible patches: only 'active' or 'occluded' are tracked
    candidate_patches = [p for p in patches if p.status in ("active", "occluded")]

    num_patches = len(candidate_patches)
    num_detections = len(detections)

    # If no patches exist, all detections become new patches
    if num_patches == 0:
        for det in detections:
            new_id = f"P-{next_seq:04d}"
            next_seq += 1
            new_patch = TrackedPatch(
                patch_id=new_id,
                aoi_id=None,
                status="active",
                first_seen=scene_time,
                last_seen=scene_time,
                last_obs_id=det.obs_id,
                clear_evidence=0.0,
                last_centroid=det.centroid,
                last_area_m2=det.area_m2,
                last_mean_fdi=det.mean_fdi,
            )
            result.new_patches.append((new_patch, det))
            result.events.append(
                TrackingEvent(
                    patch_id=new_id,
                    event="born",
                    at=scene_time,
                    detail={"obs_id": det.obs_id, "scene_id": scene_id, "area_m2": det.area_m2},
                )
            )
        return result

    # If no detections exist, all candidate patches are unmatched (to be evaluated by cloudstatus)
    if num_detections == 0:
        result.unmatched_patches = list(candidate_patches)
        return result

    # 1. Predict centroids and compute density, gating, and cost matrices
    predicted_centroids = [predict_patch_centroid(p, scene_time) for p in candidate_patches]

    density_matrix = np.zeros((num_patches, num_detections), dtype=np.float64)
    gated_matrix = np.zeros((num_patches, num_detections), dtype=bool)
    cost_matrix = np.full((num_patches, num_detections), 1e9, dtype=np.float64)

    for i, patch in enumerate(candidate_patches):
        pred_c = predicted_centroids[i]
        for j, det in enumerate(detections):
            d = estimate_ensemble_density(patch.ensemble_particles, pred_c, det.centroid)
            density_matrix[i, j] = d
            is_g = is_gated(patch, det.centroid, d, pred_c)
            gated_matrix[i, j] = is_g
            if is_g:
                cost_matrix[i, j] = calculate_cost(
                    d, patch.last_area_m2, det.area_m2, patch.last_mean_fdi, det.mean_fdi
                )

    assigned_detections: Set[int] = set()
    processed_patches: Set[int] = set()

    # 2. Split Detection
    # If a patch has >= 2 gated detections, their combined area is within 0.5-1.5x parent's area,
    # and they lie within <= 3 km of each other (or within the 90% region):
    for i, patch in enumerate(candidate_patches):
        gated_indices = [j for j in range(num_detections) if gated_matrix[i, j] and j not in assigned_detections]
        if len(gated_indices) >= 2 and patch.last_area_m2 is not None and patch.last_area_m2 > 0:
            parent_area = patch.last_area_m2
            combined_area = sum(detections[j].area_m2 for j in gated_indices)
            area_ratio = combined_area / parent_area

            if SPLIT_MIN_AREA_RATIO <= area_ratio <= SPLIT_MAX_AREA_RATIO:
                # Check spatial proximity: all pairwise distances <= 3.0 km or inside 90% region
                proximity_ok = True
                for idx_a in range(len(gated_indices)):
                    for idx_b in range(idx_a + 1, len(gated_indices)):
                        j_a = gated_indices[idx_a]
                        j_b = gated_indices[idx_b]
                        dist_km = geodesic_distance_km(
                            detections[j_a].centroid[0],
                            detections[j_a].centroid[1],
                            detections[j_b].centroid[0],
                            detections[j_b].centroid[1],
                        )
                        if dist_km > SPLIT_MAX_DISTANCE_KM:
                            # If distance > 3 km, check if both are within 90% region
                            in_p90_a = is_gated(patch, detections[j_a].centroid, 0.0, predicted_centroids[i])
                            in_p90_b = is_gated(patch, detections[j_b].centroid, 0.0, predicted_centroids[i])
                            if not (in_p90_a and in_p90_b):
                                proximity_ok = False
                                break
                    if not proximity_ok:
                        break

                if proximity_ok:
                    # Mark parent as split
                    patch.status = "split"
                    patch.last_seen = scene_time
                    result.split_parents.append(patch)
                    processed_patches.add(i)

                    child_ids = []
                    # Create children: P-NNNN-A, P-NNNN-B, ...
                    for k, j in enumerate(gated_indices):
                        suffix = chr(ord("A") + k)
                        child_id = f"{patch.patch_id}-{suffix}"
                        child_ids.append(child_id)
                        assigned_detections.add(j)
                        child_det = detections[j]

                        child_patch = TrackedPatch(
                            patch_id=child_id,
                            parent_id=patch.patch_id,
                            aoi_id=patch.aoi_id,
                            status="active",
                            first_seen=scene_time,
                            last_seen=scene_time,
                            last_obs_id=child_det.obs_id,
                            clear_evidence=0.0,
                            last_centroid=child_det.centroid,
                            last_area_m2=child_det.area_m2,
                            last_mean_fdi=child_det.mean_fdi,
                        )
                        result.split_children.append((child_patch, child_det))
                        result.events.append(
                            TrackingEvent(
                                patch_id=child_id,
                                event="born",
                                at=scene_time,
                                detail={
                                    "parent_id": patch.patch_id,
                                    "split_from": patch.patch_id,
                                    "obs_id": child_det.obs_id,
                                    "scene_id": scene_id,
                                    "area_m2": child_det.area_m2,
                                },
                            )
                        )

                    result.events.append(
                        TrackingEvent(
                            patch_id=patch.patch_id,
                            event="split",
                            at=scene_time,
                            detail={"children": child_ids, "scene_id": scene_id},
                        )
                    )

    # 3. Merge Detection
    # If an unassigned detection is gated by >= 2 active patches (and not handled yet):
    for j in range(num_detections):
        if j in assigned_detections:
            continue
        gating_patches = [
            i for i in range(num_patches)
            if gated_matrix[i, j] and i not in processed_patches
        ]
        if len(gating_patches) >= 2:
            # Check if these patches have distinct other exclusive detections
            parents = [candidate_patches[i] for i in gating_patches]
            successor_id = f"P-{next_seq:04d}"
            next_seq += 1
            det = detections[j]
            assigned_detections.add(j)

            for i in gating_patches:
                p = candidate_patches[i]
                p.status = "merged"
                p.last_seen = scene_time
                processed_patches.add(i)
                result.merged_parents.append(p)
                result.events.append(
                    TrackingEvent(
                        patch_id=p.patch_id,
                        event="merged",
                        at=scene_time,
                        detail={"successor_id": successor_id, "scene_id": scene_id},
                    )
                )

            successor = TrackedPatch(
                patch_id=successor_id,
                parent_id=parents[0].patch_id,
                aoi_id=parents[0].aoi_id,
                status="active",
                first_seen=min((p.first_seen for p in parents if p.first_seen), default=scene_time),
                last_seen=scene_time,
                last_obs_id=det.obs_id,
                clear_evidence=0.0,
                last_centroid=det.centroid,
                last_area_m2=det.area_m2,
                last_mean_fdi=det.mean_fdi,
            )
            result.merged_successors.append((successor, det))
            result.events.append(
                TrackingEvent(
                    patch_id=successor_id,
                    event="born",
                    at=scene_time,
                    detail={
                        "merged_from": [p.patch_id for p in parents],
                        "obs_id": det.obs_id,
                        "scene_id": scene_id,
                    },
                )
            )

    # 4. Standard 1-to-1 Bipartite Assignment for remaining patches and detections
    rem_patch_indices = [i for i in range(num_patches) if i not in processed_patches]
    rem_det_indices = [j for j in range(num_detections) if j not in assigned_detections]

    if rem_patch_indices and rem_det_indices:
        sub_cost = cost_matrix[np.ix_(rem_patch_indices, rem_det_indices)]
        row_ind, col_ind = linear_sum_assignment(sub_cost)

        for r, c in zip(row_ind, col_ind):
            i = rem_patch_indices[r]
            j = rem_det_indices[c]

            # Filter out pairs that violate gating or have invalid cost
            if gated_matrix[i, j] and cost_matrix[i, j] < 1e8:
                patch = candidate_patches[i]
                det = detections[j]
                processed_patches.add(i)
                assigned_detections.add(j)

                was_occluded = (patch.status == "occluded")
                patch.status = "active"
                patch.last_seen = scene_time
                patch.last_obs_id = det.obs_id
                patch.last_centroid = det.centroid
                patch.last_area_m2 = det.area_m2
                patch.last_mean_fdi = det.mean_fdi
                patch.clear_evidence = 0.0

                result.matched.append((patch, det))

                if was_occluded:
                    result.events.append(
                        TrackingEvent(
                            patch_id=patch.patch_id,
                            event="reacquired",
                            at=scene_time,
                            detail={"obs_id": det.obs_id, "scene_id": scene_id},
                        )
                    )
                result.events.append(
                    TrackingEvent(
                        patch_id=patch.patch_id,
                        event="matched",
                        at=scene_time,
                        detail={"obs_id": det.obs_id, "scene_id": scene_id},
                    )
                )

    # 5. New patch creation for unmatched detections
    for j in range(num_detections):
        if j not in assigned_detections:
            det = detections[j]
            new_id = f"P-{next_seq:04d}"
            next_seq += 1
            new_patch = TrackedPatch(
                patch_id=new_id,
                aoi_id=None,
                status="active",
                first_seen=scene_time,
                last_seen=scene_time,
                last_obs_id=det.obs_id,
                clear_evidence=0.0,
                last_centroid=det.centroid,
                last_area_m2=det.area_m2,
                last_mean_fdi=det.mean_fdi,
            )
            result.new_patches.append((new_patch, det))
            result.events.append(
                TrackingEvent(
                    patch_id=new_id,
                    event="born",
                    at=scene_time,
                    detail={"obs_id": det.obs_id, "scene_id": scene_id, "area_m2": det.area_m2},
                )
            )

    # 6. Unmatched patches (active or occluded with NO matching detection)
    for i, patch in enumerate(candidate_patches):
        if i not in processed_patches:
            result.unmatched_patches.append(patch)

    return result
