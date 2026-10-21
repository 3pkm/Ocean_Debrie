"""
Preprocessing module for Sentinel-2 MSI data.
Handles:
- Windowed reading of Sentinel-2 bands from COG URLs, local files, or test arrays
- Resampling 20m / 60m bands (B1, B5, B6, B7, B8A, B11, B12, SCL) to 10m grid
- SCL Cloud Mask generation with 400m (40 pixels) dilation
- SCL Water Mask generation combining SCL water (class 6) and NDWI > 0
- Standardized dataclass output for downstream inference and tracking
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np
import rasterio
from rasterio.transform import Affine, from_bounds
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds as window_from_bounds
import scipy.ndimage

from core.config import CLOUD_DILATION_METERS
from core.indices import compute_ndwi

logger = logging.getLogger(__name__)

# Standard 11 bands for UNet input (in required order)
REQUIRED_BANDS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]

# SCL classes
SCL_NO_DATA = 0
SCL_SATURATED = 1
SCL_DARK_AREA = 2
SCL_CLOUD_SHADOW = 3
SCL_VEGETATION = 4
SCL_NOT_VEGETATED = 5
SCL_WATER = 6
SCL_UNCLASSIFIED = 7
SCL_CLOUD_MEDIUM_PROB = 8
SCL_CLOUD_HIGH_PROB = 9
SCL_THIN_CIRRUS = 10
SCL_SNOW = 11

CLOUD_CLASSES = (
    SCL_NO_DATA,
    SCL_CLOUD_SHADOW,
    SCL_CLOUD_MEDIUM_PROB,
    SCL_CLOUD_HIGH_PROB,
    SCL_THIN_CIRRUS,
)


@dataclass
class PreprocessedScene:
    """Dataclass holding all 10m resampled bands and masks for an AOI."""
    bands: Dict[str, np.ndarray]
    cloud_mask: np.ndarray
    water_mask: np.ndarray
    transform: Any
    crs: Any
    bounds: Tuple[float, float, float, float]
    scl: Optional[np.ndarray] = None
    raw_cloud_mask: Optional[np.ndarray] = None
    ndwi: Optional[np.ndarray] = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bands": self.bands,
            "cloud_mask": self.cloud_mask,
            "water_mask": self.water_mask,
            "transform": self.transform,
            "crs": self.crs,
            "bounds": self.bounds,
            "scl": self.scl,
            "raw_cloud_mask": self.raw_cloud_mask,
            "ndwi": self.ndwi,
        }


def normalize_band_name(name: str) -> str:
    """Normalize band names such as 'B01' -> 'B1', 'b2' -> 'B2', 'scl' -> 'SCL'."""
    clean = name.strip().upper()
    mapping = {
        "B01": "B1",
        "B02": "B2",
        "B03": "B3",
        "B04": "B4",
        "B05": "B5",
        "B06": "B6",
        "B07": "B7",
        "B08": "B8",
        "B8A": "B8A",
        "B08A": "B8A",
        "B11": "B11",
        "B12": "B12",
        "SCL": "SCL",
    }
    return mapping.get(clean, clean)


def resample_band(
    arr: np.ndarray,
    target_shape: Tuple[int, int],
    order: int = 1,
) -> np.ndarray:
    """
    Resample a 2D array to target_shape (H, W).
    order=1 for bilinear (continuous reflectance bands).
    order=0 for nearest-neighbor (categorical SCL classes).
    """
    if arr.shape == target_shape:
        return arr

    h_target, w_target = target_shape
    h_src, w_src = arr.shape
    if h_src == 0 or w_src == 0:
        return np.zeros(target_shape, dtype=arr.dtype)

    zoom_factors = (h_target / h_src, w_target / w_src)
    resampled = scipy.ndimage.zoom(arr, zoom_factors, order=order)

    # Correct rounding discrepancies if zoom size differs by +/- 1 pixel
    if resampled.shape != target_shape:
        out = np.zeros(target_shape, dtype=arr.dtype)
        sh = min(resampled.shape[0], h_target)
        sw = min(resampled.shape[1], w_target)
        out[:sh, :sw] = resampled[:sh, :sw]
        return out

    return resampled.astype(arr.dtype)


def generate_cloud_mask(
    scl: np.ndarray,
    dilation_pixels: int = 40,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generate SCL cloud mask:
    Flags:
      - Class 0: No-data
      - Class 3: Cloud shadow
      - Class 8: Medium cloud probability
      - Class 9: High cloud probability
      - Class 10: Thin cirrus

    Dilates by `dilation_pixels` (default 40 = 400m at 10m resolution)
    using scipy.ndimage.binary_dilation.

    Returns:
      (dilated_cloud_mask, raw_cloud_mask)
    """
    raw_cloud_mask = np.isin(scl, CLOUD_CLASSES)

    if dilation_pixels > 0 and np.any(raw_cloud_mask):
        dilated_cloud_mask = scipy.ndimage.binary_dilation(
            raw_cloud_mask, iterations=dilation_pixels
        )
    else:
        dilated_cloud_mask = raw_cloud_mask.copy()

    return dilated_cloud_mask, raw_cloud_mask


def generate_water_mask(
    scl: np.ndarray,
    ndwi: np.ndarray,
    ndwi_threshold: float = 0.0,
) -> np.ndarray:
    """
    Generate SCL Water Mask:
    SCL water (class 6) combined with NDWI > ndwi_threshold.
    """
    return (scl == SCL_WATER) | (ndwi > ndwi_threshold)


def read_band_window(
    source: Union[str, np.ndarray],
    bounds: Optional[Tuple[float, float, float, float]] = None,
    bounds_crs: str = "EPSG:4326",
) -> Tuple[np.ndarray, Any, Any]:
    """
    Read band data (windowed if COG/rasterio URL or path, or direct if ndarray).
    Returns (data_array, transform, crs).
    """
    if isinstance(source, np.ndarray):
        # In-memory array
        h, w = source.shape
        t = Affine.translation(0, 0)
        return source, t, "EPSG:4326"

    with rasterio.open(source) as src:
        src_crs = src.crs or "EPSG:4326"
        if bounds is not None:
            # Transform bounds to dataset CRS if needed
            if bounds_crs != src_crs and bounds_crs == "EPSG:4326":
                minx, miny, maxx, maxy = transform_bounds(
                    bounds_crs, src_crs, *bounds
                )
            else:
                minx, miny, maxx, maxy = bounds

            window = window_from_bounds(minx, miny, maxx, maxy, transform=src.transform)
            window = window.round_offsets().round_shape()
            data = src.read(1, window=window, boundless=True, fill_value=0)
            transform = rasterio.windows.transform(window, src.transform)
        else:
            data = src.read(1)
            transform = src.transform

        return data, transform, src_crs


def preprocess_scene(
    sources: Dict[str, Union[str, np.ndarray]],
    aoi_bounds: Optional[Tuple[float, float, float, float]] = None,
    bounds_crs: str = "EPSG:4326",
    scale_reflectance: bool = True,
    dilation_meters: float = CLOUD_DILATION_METERS,
    resolution_meters: float = 10.0,
) -> PreprocessedScene:
    """
    Preprocess a Sentinel-2 scene:
    1. Read all required bands and SCL for specified AOI bounds.
    2. Resample all 20m/60m bands to match the 10m grid (reference band B2).
    3. Scale reflectance values (DN / 10000.0) if integer values.
    4. Compute NDWI.
    5. Generate dilated SCL cloud mask (400m / 40 pixels).
    6. Generate water mask (SCL water 6 | NDWI > 0).
    7. Return PreprocessedScene.
    """
    # Normalize input keys
    norm_sources = {normalize_band_name(k): v for k, v in sources.items()}

    # Determine reference 10m band (prefer B2, fallback to B4, B3, B8, or first available)
    ref_band_key = None
    for k in ["B2", "B4", "B3", "B8"]:
        if k in norm_sources:
            ref_band_key = k
            break
    if ref_band_key is None and norm_sources:
        ref_band_key = next(iter(norm_sources.keys()))

    if ref_band_key is None:
        raise ValueError("No bands provided to preprocess_scene.")

    # Read reference band
    ref_data, ref_transform, ref_crs = read_band_window(
        norm_sources[ref_band_key], bounds=aoi_bounds, bounds_crs=bounds_crs
    )
    target_shape = ref_data.shape

    raw_bands: Dict[str, np.ndarray] = {}
    resampled_bands: Dict[str, np.ndarray] = {}

    # Read and resample all bands
    for band_key, src in norm_sources.items():
        if band_key == ref_band_key:
            band_arr = ref_data
        else:
            band_arr, _, _ = read_band_window(
                src, bounds=aoi_bounds, bounds_crs=bounds_crs
            )

        raw_bands[band_key] = band_arr

        # Resampling
        order = 0 if band_key == "SCL" else 1
        resampled_bands[band_key] = resample_band(band_arr, target_shape, order=order)

    # Ensure all REQUIRED_BANDS are present (if missing, initialize with zeros or fallback)
    for req in REQUIRED_BANDS:
        if req not in resampled_bands:
            logger.warning(f"Band {req} missing from inputs. Initializing with zeros.")
            resampled_bands[req] = np.zeros(target_shape, dtype=np.float32)

    # Scale reflectance: if integer dtype or max > 100, scale to 0.0 - 1.0
    for req in REQUIRED_BANDS:
        arr = resampled_bands[req]
        if scale_reflectance and (np.issubdtype(arr.dtype, np.integer) or arr.max() > 100.0):
            resampled_bands[req] = (arr.astype(np.float32) / 10000.0).astype(np.float32)
        else:
            resampled_bands[req] = arr.astype(np.float32)

    # SCL array (if not present, default to water class 6)
    if "SCL" in resampled_bands:
        scl = resampled_bands["SCL"].astype(np.uint8)
    else:
        logger.warning("SCL band missing from inputs; defaulting to water class 6.")
        scl = np.full(target_shape, SCL_WATER, dtype=np.uint8)

    # Calculate NDWI: (B3 - B8) / (B3 + B8)
    ndwi = compute_ndwi(resampled_bands["B3"], resampled_bands["B8"])

    # Cloud Mask & Dilation (400m = 40 pixels at 10m res)
    dilation_pixels = int(round(dilation_meters / resolution_meters))
    dilated_cloud_mask, raw_cloud_mask = generate_cloud_mask(
        scl, dilation_pixels=dilation_pixels
    )

    # Water Mask: SCL water (6) combined with NDWI > 0
    water_mask = generate_water_mask(scl, ndwi, ndwi_threshold=0.0)

    # Bounds calculation
    h, w = target_shape
    if isinstance(ref_transform, Affine):
        try:
            minx, maxy = ref_transform @ (0, 0)
            maxx, miny = ref_transform @ (w, h)
        except Exception:
            minx, maxy = ref_transform * (0, 0)
            maxx, miny = ref_transform * (w, h)
        bounds = (min(minx, maxx), min(miny, maxy), max(minx, maxx), max(miny, maxy))
    elif aoi_bounds is not None:
        bounds = aoi_bounds
    else:
        bounds = (0.0, 0.0, float(w), float(h))

    return PreprocessedScene(
        bands={k: resampled_bands[k] for k in REQUIRED_BANDS},
        cloud_mask=dilated_cloud_mask,
        water_mask=water_mask,
        transform=ref_transform,
        crs=ref_crs,
        bounds=bounds,
        scl=scl,
        raw_cloud_mask=raw_cloud_mask,
        ndwi=ndwi,
    )
