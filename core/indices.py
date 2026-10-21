"""
Spectral indices computation for Sentinel-2 MSI data.
Formulas defined in plan.md Section 7:
- FDI (Floating Debris Index): B8 - [B6 + (B11 - B6) * 1.772]
- NDVI (Normalized Difference Vegetation Index): (B8 - B4) / (B8 + B4)
- NDWI (Normalized Difference Water Index): (B3 - B8) / (B3 + B8)
- NDCI (Normalized Difference Chlorophyll Index): (B5 - B4) / (B5 + B4)
"""

import numpy as np


def compute_fdi(b8: np.ndarray, b6: np.ndarray, b11: np.ndarray) -> np.ndarray:
    """
    Compute Floating Debris Index (FDI).
    FDI = B8 - [B6 + (B11 - B6) * 1.772]
    """
    b8 = b8.astype(np.float32)
    b6 = b6.astype(np.float32)
    b11 = b11.astype(np.float32)
    b8_prime = b6 + (b11 - b6) * 1.772
    return b8 - b8_prime


def compute_normalized_ratio(band_a: np.ndarray, band_b: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """
    Compute normalized difference ratio: (band_a - band_b) / (band_a + band_b + eps).
    """
    band_a = band_a.astype(np.float32)
    band_b = band_b.astype(np.float32)
    numerator = band_a - band_b
    denominator = band_a + band_b
    # Avoid division by zero
    mask = np.abs(denominator) > eps
    result = np.zeros_like(numerator, dtype=np.float32)
    result[mask] = numerator[mask] / (denominator[mask] + eps)
    return np.clip(result, -1.0, 1.0)


def compute_ndvi(b8: np.ndarray, b4: np.ndarray) -> np.ndarray:
    """NDVI = (B8 - B4) / (B8 + B4)"""
    return compute_normalized_ratio(b8, b4)


def compute_ndwi(b3: np.ndarray, b8: np.ndarray) -> np.ndarray:
    """NDWI = (B3 - B8) / (B3 + B8)"""
    return compute_normalized_ratio(b3, b8)


def compute_ndci(b5: np.ndarray, b4: np.ndarray) -> np.ndarray:
    """NDCI (Chlorophyll proxy) = (B5 - B4) / (B5 + B4)"""
    return compute_normalized_ratio(b5, b4)


def stack_14_channels(
    bands: dict[str, np.ndarray],
    means: list[float] | None = None,
    stds: list[float] | None = None,
) -> np.ndarray:
    """
    Construct the 14-channel input array for the UNet model:
    Channels 0..10: B1, B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12
    Channel 11: FDI
    Channel 12: NDVI
    Channel 13: NDWI
    Optionally applies per-channel standardization (x - mean) / std.
    """
    order = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]
    channel_list = [bands[name].astype(np.float32) for name in order]

    fdi = compute_fdi(bands["B8"], bands["B6"], bands["B11"])
    ndvi = compute_ndvi(bands["B8"], bands["B4"])
    ndwi = compute_ndwi(bands["B3"], bands["B8"])

    channel_list.extend([fdi, ndvi, ndwi])
    stacked = np.stack(channel_list, axis=0)  # Shape: (14, H, W)

    if means is not None and stds is not None:
        means_arr = np.array(means, dtype=np.float32).reshape(-1, 1, 1)
        stds_arr = np.array(stds, dtype=np.float32).reshape(-1, 1, 1)
        stacked = (stacked - means_arr) / np.maximum(stds_arr, 1e-6)

    return stacked
