"""
Polygon vectorization and attribute calculation module for ocean debris candidates.
Handles:
- Probability thresholding against DEBRIS_PROB_THRESHOLD
- Application of water mask and exclusion of cloud mask
- Connected-component extraction & vectorization to Polygons (EPSG:4326)
- Quantification:
  * Area in m^2 (pixels * 100.0 m^2 at 10m Sentinel-2 resolution)
  * Centroid (lon, lat Point)
  * Mean model confidence
  * Mean Floating Debris Index (FDI)
  * Cloud overlap fraction (buffer/bbox overlap with cloud mask)
- Output dictionaries formatted according to the `observations` schema.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pyproj
import rasterio.features
from rasterio.transform import Affine, from_bounds
import scipy.ndimage
import shapely.geometry
import shapely.ops
import shapely.validation

from core.config import DEBRIS_PROB_THRESHOLD

logger = logging.getLogger(__name__)


def extract_debris_polygons(
    debris_prob: np.ndarray,
    water_mask: Optional[np.ndarray] = None,
    cloud_mask: Optional[np.ndarray] = None,
    fdi: Optional[np.ndarray] = None,
    transform: Optional[Any] = None,
    crs: Any = "EPSG:4326",
    threshold: float = DEBRIS_PROB_THRESHOLD,
    min_pixels: int = 1,
    scene_id: Optional[str] = None,
    cloud_buffer_pixels: int = 5,
) -> List[Dict[str, Any]]:
    """
    Vectorize debris probability detections into polygon observations.

    Parameters:
      debris_prob: 2D float32 array (H, W) with model probabilities in [0.0, 1.0].
      water_mask: Optional 2D bool array (H, W). If provided, only pixels on water are kept.
      cloud_mask: Optional 2D bool array (H, W). If provided, pixels under cloud are masked out.
      fdi: Optional 2D float32 array (H, W) of Floating Debris Index values.
      transform: Affine transform mapping pixel coords to spatial coords.
      crs: Coordinate reference system of transform (e.g. 'EPSG:4326' or UTM 'EPSG:32631').
      threshold: Debris probability threshold (default 0.50).
      min_pixels: Minimum contiguous pixel count to consider a debris patch (default 1).
      scene_id: Scene ID to attach to observation dictionary.
      cloud_buffer_pixels: Margin in pixels around bbox to assess cloud overlap fraction.

    Returns:
      List of observation dictionaries matching the `observations` schema:
      [
        {
          "scene_id": str,
          "patch_id": None,
          "geom": Dict (GeoJSON Polygon in EPSG:4326),
          "centroid": Dict (GeoJSON Point in EPSG:4326),
          "area_m2": float,
          "confidence": float,
          "mean_fdi": float,
          "cloud_overlap": float,
          "pixel_count": int,
        },
        ...
      ]
    """
    h, w = debris_prob.shape

    # 1. Candidate binary mask
    candidate_mask = debris_prob >= threshold

    # 2. Exclude non-water and clouds
    if water_mask is not None:
        candidate_mask = candidate_mask & water_mask
    if cloud_mask is not None:
        candidate_mask = candidate_mask & (~cloud_mask)

    if not np.any(candidate_mask):
        return []

    # Default affine transform if none provided
    if transform is None:
        transform = Affine.translation(0, 0)

    # Prepare coordinate transformer to EPSG:4326 if not already in 4326
    needs_reproject = False
    transformer = None
    if crs is not None:
        crs_str = str(crs).upper()
        if "4326" not in crs_str:
            try:
                transformer = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
                needs_reproject = True
            except Exception as e:
                logger.warning(f"Could not build transformer from CRS {crs} to EPSG:4326: {e}")

    # 3. Label contiguous connected components (8-connectivity)
    connectivity_structure = np.ones((3, 3), dtype=int)
    labeled, num_features = scipy.ndimage.label(
        candidate_mask, structure=connectivity_structure
    )

    observations: List[Dict[str, Any]] = []

    for feat_id in range(1, num_features + 1):
        comp_mask = labeled == feat_id
        pixel_count = int(np.sum(comp_mask))

        if pixel_count < min_pixels:
            continue

        rows, cols = np.where(comp_mask)
        r_min, r_max = int(rows.min()), int(rows.max())
        c_min, c_max = int(cols.min()), int(cols.max())

        # Metrics on feature pixels
        conf_mean = float(np.mean(debris_prob[rows, cols]))
        fdi_mean = float(np.mean(fdi[rows, cols])) if fdi is not None else 0.0

        # Area: 10m x 10m pixel = 100 m^2
        area_m2 = float(pixel_count * 100.0)

        # Cloud overlap: fraction of bounding box (with buffer) touching cloud mask
        if cloud_mask is not None:
            r0 = max(0, r_min - cloud_buffer_pixels)
            r1 = min(h, r_max + cloud_buffer_pixels + 1)
            c0 = max(0, c_min - cloud_buffer_pixels)
            c1 = min(w, c_max + cloud_buffer_pixels + 1)
            cloud_sub = cloud_mask[r0:r1, c0:c1]
            cloud_overlap = float(np.mean(cloud_sub)) if cloud_sub.size > 0 else 0.0
        else:
            cloud_overlap = 0.0

        # 4. Vectorize to polygon geometries
        shapes_gen = rasterio.features.shapes(
            comp_mask.astype(np.uint8),
            mask=comp_mask,
            transform=transform,
            connectivity=8,
        )

        for geom_dict, val in shapes_gen:
            if val != 1:
                continue

            try:
                poly = shapely.geometry.shape(geom_dict)
            except Exception as e:
                logger.debug(f"Failed to parse shape {geom_dict}: {e}")
                continue

            if poly.is_empty or poly.area <= 0:
                continue

            # Reproject to EPSG:4326 if required
            if needs_reproject and transformer is not None:
                try:
                    poly_4326 = shapely.transform(
                        poly,
                        lambda coords: np.column_stack(
                            transformer.transform(coords[:, 0], coords[:, 1])
                        ),
                    )
                except Exception as e:
                    logger.debug(f"Reprojection error: {e}. Falling back to original.")
                    poly_4326 = poly
            else:
                poly_4326 = poly

            if not poly_4326.is_valid:
                poly_4326 = shapely.validation.make_valid(poly_4326)

            # Handle possible MultiPolygon split
            sub_polygons = (
                list(poly_4326.geoms)
                if poly_4326.geom_type == "MultiPolygon"
                else [poly_4326]
            )

            for p in sub_polygons:
                if p.geom_type != "Polygon" or p.is_empty:
                    continue

                centroid_x = float(p.centroid.x)
                centroid_y = float(p.centroid.y)

                obs_entry = {
                    "scene_id": scene_id,
                    "patch_id": None,
                    "geom": shapely.geometry.mapping(p),
                    "centroid": {
                        "type": "Point",
                        "coordinates": [centroid_x, centroid_y],
                    },
                    "area_m2": area_m2,
                    "confidence": conf_mean,
                    "mean_fdi": fdi_mean,
                    "cloud_overlap": cloud_overlap,
                    "pixel_count": pixel_count,
                }
                observations.append(obs_entry)

    return observations
