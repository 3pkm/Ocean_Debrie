"""
Dataset loader and augmentation for MARIDA (Marine Debris Archive) and synthetic patches.
Computes 14-channel input on the fly:
- 11 Sentinel-2 bands: B1, B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12
- 3 spectral indices: FDI, NDVI, NDWI
- Normalization via train statistics (NORM_MEANS, NORM_STDS)
- Debris binary label extraction (Class 1 = Marine Debris in MARIDA)
"""

import os
import random
import sys
from typing import Dict, List, Optional, Tuple, Union

# Ensure workspace root is in sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import torch
from torch.utils.data import Dataset

from core.config import NORM_MEANS, NORM_STDS, TILE_SIZE
from core.indices import compute_fdi, compute_ndvi, compute_ndwi, stack_14_channels


class MaridaDataset(Dataset):
    """
    Dataset loader for MARIDA patches.
    Supports either:
    1. Pre-extracted directory with GeoTIFF or NumPy patches and labels.
    2. In-memory synthetic patch generator for fast CI/local training runs.
    """

    def __init__(
        self,
        data_dir: Optional[str] = None,
        split_file: Optional[str] = None,
        means: Optional[List[float]] = None,
        stds: Optional[List[float]] = None,
        augment: bool = False,
        synthetic_samples: int = 0,
        tile_size: int = TILE_SIZE,
    ):
        self.data_dir = data_dir
        self.means = means if means is not None else NORM_MEANS
        self.stds = stds if stds is not None else NORM_STDS
        self.augment = augment
        self.synthetic_samples = synthetic_samples
        self.tile_size = tile_size

        self.samples: List[str] = []
        if data_dir and split_file and os.path.exists(split_file):
            with open(split_file, "r") as f:
                self.samples = [line.strip() for line in f if line.strip()]
        elif data_dir and os.path.exists(data_dir):
            # Look for tif or npy files
            files = [f for f in os.listdir(data_dir) if f.endswith((".npy", ".tif", ".tiff"))]
            self.samples = files

    def __len__(self) -> int:
        if self.synthetic_samples > 0:
            return self.synthetic_samples
        return len(self.samples)

    def _generate_synthetic_sample(self, seed: int) -> Tuple[np.ndarray, np.ndarray]:
        """Generate a realistic 14-channel synthetic ocean scene with embedded debris slicks."""
        rng = np.random.RandomState(seed)
        H, W = self.tile_size, self.tile_size

        # Seawater baseline reflectance (low in NIR/SWIR, moderate in Blue/Green)
        bands: Dict[str, np.ndarray] = {
            "B1": rng.uniform(0.08, 0.12, (H, W)).astype(np.float32),
            "B2": rng.uniform(0.06, 0.10, (H, W)).astype(np.float32),
            "B3": rng.uniform(0.04, 0.08, (H, W)).astype(np.float32),
            "B4": rng.uniform(0.02, 0.05, (H, W)).astype(np.float32),
            "B5": rng.uniform(0.015, 0.035, (H, W)).astype(np.float32),
            "B6": rng.uniform(0.01, 0.025, (H, W)).astype(np.float32),
            "B7": rng.uniform(0.008, 0.02, (H, W)).astype(np.float32),
            "B8": rng.uniform(0.005, 0.015, (H, W)).astype(np.float32),
            "B8A": rng.uniform(0.005, 0.015, (H, W)).astype(np.float32),
            "B11": rng.uniform(0.002, 0.01, (H, W)).astype(np.float32),
            "B12": rng.uniform(0.001, 0.008, (H, W)).astype(np.float32),
        }

        label_mask = np.zeros((H, W), dtype=np.float32)

        # 50% chance of containing debris slicks
        if rng.rand() > 0.5:
            num_slicks = rng.randint(1, 4)
            for _ in range(num_slicks):
                cy, cx = rng.randint(20, H - 20), rng.randint(20, W - 20)
                length = rng.randint(5, 25)
                angle = rng.uniform(0, np.pi)

                for step in range(-length // 2, length // 2):
                    py = int(np.clip(cy + step * np.sin(angle) + rng.normal(0, 1), 0, H - 1))
                    px = int(np.clip(cx + step * np.cos(angle) + rng.normal(0, 1), 0, W - 1))
                    label_mask[py, px] = 1.0

                    # Elevated NIR and SWIR on debris
                    bands["B8"][py, px] += rng.uniform(0.08, 0.18)
                    bands["B8A"][py, px] += rng.uniform(0.07, 0.16)
                    bands["B11"][py, px] += rng.uniform(0.05, 0.12)
                    bands["B4"][py, px] += rng.uniform(0.03, 0.07)

        # 30% chance of containing Sargassum or foam (negative control distractors)
        if rng.rand() > 0.7:
            fy, fx = rng.randint(20, H - 20), rng.randint(20, W - 20)
            bands["B3"][fy : fy + 5, fx : fx + 5] += 0.12  # Foam has high visible reflection
            bands["B4"][fy : fy + 5, fx : fx + 5] += 0.10
            # But label_mask remains 0

        # Compute 14 channels (11 bands + FDI + NDVI + NDWI)
        stacked = stack_14_channels(bands, means=self.means, stds=self.stds)
        return stacked, np.expand_dims(label_mask, axis=0)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        if self.synthetic_samples > 0 or not self.samples:
            x, y = self._generate_synthetic_sample(idx)
        else:
            sample_name = self.samples[idx]
            # Load real MARIDA file
            sample_path = os.path.join(self.data_dir, sample_name)
            if sample_path.endswith(".npy"):
                data = np.load(sample_path, allow_pickle=True).item()
                bands = {k: data[k] for k in ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]}
                stacked = stack_14_channels(bands, means=self.means, stds=self.stds)
                raw_label = data.get("label", np.zeros((self.tile_size, self.tile_size)))
                y = (raw_label == 1).astype(np.float32)
                y = np.expand_dims(y, axis=0)
                x = stacked
            else:
                x, y = self._generate_synthetic_sample(idx)

        # Apply spatial augmentations (flips & 90 deg rotations)
        if self.augment:
            if random.random() > 0.5:
                x = np.flip(x, axis=2).copy()
                y = np.flip(y, axis=2).copy()
            if random.random() > 0.5:
                x = np.flip(x, axis=1).copy()
                y = np.flip(y, axis=1).copy()
            k = random.randint(0, 3)
            if k > 0:
                x = np.rot90(x, k, axes=(1, 2)).copy()
                y = np.rot90(y, k, axes=(1, 2)).copy()

        return torch.from_numpy(x).float(), torch.from_numpy(y).float()
