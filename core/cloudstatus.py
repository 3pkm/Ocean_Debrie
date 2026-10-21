"""
Cloud-aware status engine for Multispectral Ocean Debris Segmentation.
Implements visibility fraction evaluation against cloud masks, clear evidence
accumulation, status transitions (occluded, lost, stranded, expired), and
reacquisition logic.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import shapely.geometry
from shapely.geometry import Point

from core.config import (
    VISIBILITY_CLEAR_THRESHOLD,
    CLEAR_EVIDENCE_THRESHOLD,
    EXPIRY_DAYS,
)
from core.tracking import TrackedPatch, TrackingEvent, Detection


def compute_particle_visibility(
    particles: np.ndarray,
    cloud_mask: np.ndarray,
    transform_func: Optional[Callable[[float, float], Tuple[int, int]]] = None,
) -> float:
    """
    Calculate visibility V as the fraction of ensemble particles falling in clear pixels (cloud_mask == 0).

    Args:
        particles: (N, 2) array of particle coordinates (lon, lat).
        cloud_mask: 2D numpy array where 0 = clear water, > 0 = cloud/shadow/invalid.
        transform_func: Function mapping (lon, lat) -> (col, row) pixel indices.

    Returns:
        Fraction V between 0.0 and 1.0.
    """
    if len(particles) == 0:
        return 1.0

    if transform_func is None:
        # Default fallback: if cloud mask is provided without transform, assume average clear ratio
        return float(np.mean(cloud_mask == 0))

    height, width = cloud_mask.shape
    clear_count = 0
    valid_count = 0

    for lon, lat in particles:
        col, row = transform_func(lon, lat)
        if 0 <= row < height and 0 <= col < width:
            valid_count += 1
            if cloud_mask[row, col] == 0:
                clear_count += 1

    if valid_count == 0:
        return 0.0

    return clear_count / valid_count


def evaluate_unmatched_patch_status(
    patch: TrackedPatch,
    scene_time: datetime,
    visibility: Optional[float] = None,
    cloud_mask: Optional[np.ndarray] = None,
    transform_func: Optional[Callable[[float, float], Tuple[int, int]]] = None,
    stranded_fraction: Optional[float] = None,
    land_geom: Optional[Any] = None,
    scene_id: Optional[str] = None,
) -> List[TrackingEvent]:
    """
    Evaluate status for an active or occluded patch with NO matching detection in the current scene.

    Transitions:
    - If unobserved > EXPIRY_DAYS (21 days) => status becomes 'expired'.
    - If >= 70% particles reach coast/land => status becomes 'stranded'.
    - If visibility V < 0.5 => status is 'occluded' ("Not observed, forecast only"). Clear evidence is not increased.
    - If visibility V >= 0.5 => increment clear_evidence += V.
      - If clear_evidence >= 1.5 => status becomes 'lost' ("No longer detected").
      - Else status is 'occluded'.

    Returns:
        List of generated TrackingEvents.
    """
    events: List[TrackingEvent] = []
    prev_status = patch.status

    # 1. Check expiration (> 21 days unobserved)
    if patch.last_seen is not None:
        unobserved_days = (scene_time - patch.last_seen).total_seconds() / 86400.0
        if unobserved_days > EXPIRY_DAYS:
            patch.status = "expired"
            events.append(
                TrackingEvent(
                    patch_id=patch.patch_id,
                    event="expired",
                    at=scene_time,
                    detail={
                        "unobserved_days": round(unobserved_days, 2),
                        "scene_id": scene_id,
                    },
                )
            )
            return events

    # 2. Check stranding (>= 70% particles reach coast/land)
    frac_on_land = 0.0
    if stranded_fraction is not None:
        frac_on_land = stranded_fraction
    elif patch.ensemble_particles is not None and len(patch.ensemble_particles) > 0 and land_geom is not None:
        if isinstance(land_geom, dict):
            land_geom = shapely.geometry.shape(land_geom)
        land_hits = 0
        for lon, lat in patch.ensemble_particles:
            if land_geom.contains(Point(lon, lat)):
                land_hits += 1
        frac_on_land = land_hits / len(patch.ensemble_particles)

    if frac_on_land >= 0.70:
        patch.status = "stranded"
        events.append(
            TrackingEvent(
                patch_id=patch.patch_id,
                event="stranded",
                at=scene_time,
                detail={
                    "stranded_fraction": round(frac_on_land, 3),
                    "scene_id": scene_id,
                },
            )
        )
        return events

    # 3. Determine visibility V
    if visibility is not None:
        v = float(visibility)
    elif cloud_mask is not None:
        if patch.ensemble_particles is not None:
            v = compute_particle_visibility(patch.ensemble_particles, cloud_mask, transform_func)
        else:
            # Fraction of cloud mask that is clear (0 = clear)
            v = float(np.mean(cloud_mask == 0))
    else:
        # Default assumption: clear sky if no cloud mask or visibility provided
        v = 1.0

    # Ensure V is bounded between 0 and 1
    v = max(0.0, min(1.0, v))

    # 4. Status update based on visibility V
    if v < VISIBILITY_CLEAR_THRESHOLD:
        # V < 0.5: occluded ("Not observed, forecast only"). Clear evidence is not increased.
        patch.status = "occluded"
        if prev_status == "active":
            events.append(
                TrackingEvent(
                    patch_id=patch.patch_id,
                    event="occluded",
                    at=scene_time,
                    detail={
                        "visibility": round(v, 3),
                        "clear_evidence": round(patch.clear_evidence, 3),
                        "reason": "cloud_cover",
                        "scene_id": scene_id,
                    },
                )
            )
    else:
        # V >= 0.5: increment clear_evidence
        patch.clear_evidence += v

        if patch.clear_evidence >= CLEAR_EVIDENCE_THRESHOLD:
            # clear_evidence >= 1.5 => lost ("No longer detected")
            patch.status = "lost"
            events.append(
                TrackingEvent(
                    patch_id=patch.patch_id,
                    event="lost",
                    at=scene_time,
                    detail={
                        "visibility": round(v, 3),
                        "clear_evidence": round(patch.clear_evidence, 3),
                        "scene_id": scene_id,
                    },
                )
            )
        else:
            # Status stays occluded until evidence >= 1.5
            patch.status = "occluded"
            if prev_status == "active":
                events.append(
                    TrackingEvent(
                        patch_id=patch.patch_id,
                        event="occluded",
                        at=scene_time,
                        detail={
                            "visibility": round(v, 3),
                            "clear_evidence": round(patch.clear_evidence, 3),
                            "reason": "accumulating_clear_evidence",
                            "scene_id": scene_id,
                        },
                    )
                )

    return events


def reacquire_patch(
    patch: TrackedPatch,
    detection: Detection,
    scene_time: datetime,
    scene_id: Optional[str] = None,
) -> Optional[TrackingEvent]:
    """
    Handle reacquisition of an occluded patch when matched in a subsequent scene.
    Resets status to 'active', resets clear_evidence to 0.0, and emits 'reacquired' event.
    """
    was_occluded = (patch.status == "occluded")

    patch.status = "active"
    patch.clear_evidence = 0.0
    patch.last_seen = scene_time
    patch.last_obs_id = detection.obs_id
    patch.last_centroid = detection.centroid
    patch.last_area_m2 = detection.area_m2
    patch.last_mean_fdi = detection.mean_fdi

    if was_occluded:
        return TrackingEvent(
            patch_id=patch.patch_id,
            event="reacquired",
            at=scene_time,
            detail={
                "obs_id": detection.obs_id,
                "scene_id": scene_id,
            },
        )
    return None


def update_unmatched_patches(
    unmatched_patches: List[TrackedPatch],
    scene_time: datetime,
    visibility: Optional[float] = None,
    cloud_mask: Optional[np.ndarray] = None,
    transform_func: Optional[Callable[[float, float], Tuple[int, int]]] = None,
    stranded_fraction: Optional[float] = None,
    land_geom: Optional[Any] = None,
    scene_id: Optional[str] = None,
) -> List[TrackingEvent]:
    """Batch process a list of unmatched patches."""
    all_events: List[TrackingEvent] = []
    for patch in unmatched_patches:
        evs = evaluate_unmatched_patch_status(
            patch=patch,
            scene_time=scene_time,
            visibility=visibility,
            cloud_mask=cloud_mask,
            transform_func=transform_func,
            stranded_fraction=stranded_fraction,
            land_geom=land_geom,
            scene_id=scene_id,
        )
        all_events.extend(evs)
    return all_events
